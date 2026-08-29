"""DATEV export service.

Generates DATEV Buchungsstapel format CSV for import by Steuerberater.
Supports ZIP export with Belegbilder (receipt documents) for DATEV Belegtransfer.
"""

import csv
import io
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.export_log import ExportLog
from app.models.receipt import Receipt, ReceiptType
from app.models.receipt_line_item import ReceiptLineItem
from app.models.receipt_transaction_link import ReceiptTransactionLink
from app.models.skr03 import SKR03Account
from app.models.transaction import Transaction
from app.schemas.datev import (
    DatevBookingLine,
    DatevConfig,
    DatevExportResponse,
    DatevValidationResult,
    DatevZipExportResponse,
)

# Default Gegenkonto (1200 = Bank) for transactions without source_config
DEFAULT_CHECK_ACCOUNT = 1200

# UUID v5 namespace for BEDI GUIDs
# ⚠️ NEVER CHANGE THIS VALUE - deterministic UUIDs depend on it
# Same Receipt ID will always produce the same BEDI GUID
SHOP2TAX_BEDI_NAMESPACE = uuid.UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479")

# BU-Schlüssel (tax keys) for DATEV
# 2 = 7% USt (revenue)
# 3 = 19% USt (revenue)
# 8 = 7% VSt (expense/input tax)
# 9 = 19% VSt (expense/input tax)
BU_SCHLUESSEL_TO_VAT_RATE: dict[int, Decimal] = {
    2: Decimal("7.00"),
    3: Decimal("19.00"),
    8: Decimal("7.00"),
    9: Decimal("19.00"),
}


def generate_bedi_guid(receipt_id: str) -> str:
    """Generate deterministic BEDI GUID for a receipt.

    Uses UUID v5 (SHA-1 based) for determinism: same receipt_id → same GUID.
    """
    return str(uuid.uuid5(SHOP2TAX_BEDI_NAMESPACE, receipt_id))


def sanitize_filename(name: str) -> str:
    """Sanitize filename for ZIP: only alphanumeric, underscore, hyphen, dot."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)


# Characters that make a spreadsheet treat a cell as a formula when the CSV is
# opened (CSV formula injection). Leading tab / carriage return can shift a
# value into an adjacent formula cell, so they are neutralized as well.
FORMULA_TRIGGER_CHARACTERS: frozenset[str] = frozenset({"=", "+", "-", "@", "\t", "\r"})


def neutralize_formula_cell(value: str) -> str:
    """Prevent CSV formula injection when a cell is opened in a spreadsheet.

    Prepends a single apostrophe when the value is non-empty and its first
    character can trigger formula evaluation (one of ``= + - @`` or a tab /
    carriage return). Any other value is returned unchanged and byte-identical.

    The first-character-only check is intentional: it also neutralizes stacked
    prefixes (a leading ``==`` still starts with ``=``) without scanning or
    rewriting the rest of the value, so it is O(1) and cannot be abused to
    burn CPU on a crafted cell.
    """
    if value and value[0] in FORMULA_TRIGGER_CHARACTERS:
        return "'" + value
    return value


class DatevExportService:
    """Service for generating DATEV export files."""

    # All 124 DATEV columns (from official sevdesk export)
    # fmt: off
    DATEV_COLUMNS = [
        # 1-14: Core booking data
        "Umsatz", "Soll-/Haben-Kennzeichen", "WKZ Umsatz", "Kurs", "Basisumsatz",
        "WKZ Basisumsatz", "Konto", "Gegenkonto (ohne BU-Schlüssel)", "BU-Schlüssel",
        "Belegdatum", "Belegfeld 1", "Belegfeld 2", "Skonto", "Buchungstext",
        # 15-19: Additional fields
        "Postensperre", "Diverse Adressnummer", "Geschäftspartnerbank", "Sachverhalt", "Zinssperre",
        # 20: Beleglink (BEDI GUID)
        "Beleglink",
        # 21-36: Beleginfo fields (8 pairs of Art/Inhalt)
        "Beleginfo-Art 1", "Beleginfo-Inhalt 1", "Beleginfo-Art 2", "Beleginfo-Inhalt 2",
        "Beleginfo-Art 3", "Beleginfo-Inhalt 3", "Beleginfo-Art 4", "Beleginfo-Inhalt 4",
        "Beleginfo-Art 5", "Beleginfo-Inhalt 5", "Beleginfo-Art 6", "Beleginfo-Inhalt 6",
        "Beleginfo-Art 7", "Beleginfo-Inhalt 7", "Beleginfo-Art 8", "Beleginfo-Inhalt 8",
        # 37-47: Cost centers and EU fields
        "KOST1-Kostenstelle", "KOST2-Kostenstelle", "KOST-Menge",
        "EU-Mitgliedstaat u. UStID (Bestimmung)", "EU-Steuersatz (Bestimmung)",
        "Abw. Versteuerungsart", "Sachverhalt L+L", "Funktionsergänzung L+L",
        "BU 49 Hauptfunktiontyp", "BU 49 Hauptfunktionsnummer", "BU 49 Funktionsergänzung",
        # 48-87: Zusatzinformation (20 pairs of Art/Inhalt)
        "Zusatzinformation - Art 1", "Zusatzinformation - Inhalt 1",
        "Zusatzinformation - Art 2", "Zusatzinformation - Inhalt 2",
        "Zusatzinformation - Art 3", "Zusatzinformation - Inhalt 3",
        "Zusatzinformation - Art 4", "Zusatzinformation - Inhalt 4",
        "Zusatzinformation - Art 5", "Zusatzinformation - Inhalt 5",
        "Zusatzinformation - Art 6", "Zusatzinformation - Inhalt 6",
        "Zusatzinformation - Art 7", "Zusatzinformation - Inhalt 7",
        "Zusatzinformation - Art 8", "Zusatzinformation - Inhalt 8",
        "Zusatzinformation - Art 9", "Zusatzinformation - Inhalt 9",
        "Zusatzinformation - Art 10", "Zusatzinformation - Inhalt 10",
        "Zusatzinformation - Art 11", "Zusatzinformation - Inhalt 11",
        "Zusatzinformation - Art 12", "Zusatzinformation - Inhalt 12",
        "Zusatzinformation - Art 13", "Zusatzinformation - Inhalt 13",
        "Zusatzinformation - Art 14", "Zusatzinformation - Inhalt 14",
        "Zusatzinformation - Art 15", "Zusatzinformation - Inhalt 15",
        "Zusatzinformation - Art 16", "Zusatzinformation - Inhalt 16",
        "Zusatzinformation - Art 17", "Zusatzinformation - Inhalt 17",
        "Zusatzinformation - Art 18", "Zusatzinformation - Inhalt 18",
        "Zusatzinformation - Art 19", "Zusatzinformation - Inhalt 19",
        "Zusatzinformation - Art 20", "Zusatzinformation - Inhalt 20",
        # 88-101: Additional fields
        "Stück", "Gewicht", "Zahlweise", "Forderungsart", "Veranlagungsjahr",
        "Zugeordnete Fälligkeit", "Skontotyp", "Auftragsnummer", "Buchungstyp",
        "USt-Schlüssel (Anzahlungen)", "EU-Mitgliedstaat (Anzahlungen)",
        "Sachverhalt L+L (Anzahlungen)", "EU-Steuersatz (Anzahlungen)", "Erlöskonto (Anzahlungen)",
        # 102-124: More fields
        "Herkunft-Kz", "Leerfeld", "KOST-Datum", "SEPA-Mandatsreferenz", "Skontosperre",
        "Gesellschaftername", "Beteiligtennummer", "Identifikationsnummer", "Zeichnernummer",
        "Postensperre bis", "Bezeichnung SoBil-Sachverhalt", "Kennzeichen SoBil-Buchung",
        "Festschreibung", "Leistungsdatum", "Datum Zuord. Steuerperiode", "Fälligkeit",
        "Generalumkehr", "Steuersatz", "Land", "Abrechnungsreferenz",
        "BVV-Position (Betriebsvermögensvergleich)",
        "EU-Mitgliedstaat u. UStID (Ursprung)", "EU-Steuersatz (Ursprung)",
    ]
    # fmt: on

    def __init__(self, database: Session) -> None:
        self.database = database

    def generate_header_block(
        self,
        config: DatevConfig,
        date_from: date | None,
        date_to: date | None,
    ) -> list[str]:
        """Generate DATEV EXTF header (exactly 31 semicolon-separated fields).

        Format matches sevdesk export exactly. Line 2 is column headers (handled separately).
        """
        export_from = date_from or date(config.wirtschaftsjahr_beginn.year, 1, 1)
        export_to = date_to or date.today()

        # Build header as list of 31 fields, then join with semicolons
        # Positions verified against sevdesk export
        fields = [
            '"EXTF"',  # 1: Format identifier
            "700",  # 2: Version
            "21",  # 3: Category (Buchungsstapel)
            '"Buchungsstapel"',  # 4: Format name
            "12",  # 5: Format version
            "",  # 6: (empty in sevdesk)
            "",  # 7: (empty in sevdesk)
            '""',  # 8: Sachverhalt (empty string)
            '""',  # 9: (empty string)
            '""',  # 10: (empty string)
            str(config.beraternummer),  # 11: Beraternummer
            str(config.mandantennummer),  # 12: Mandantennummer
            config.wirtschaftsjahr_beginn.strftime("%Y%m%d"),  # 13: WJ-Beginn
            str(config.sachkontenlaenge),  # 14: Sachkontenlänge
            export_from.strftime("%Y%m%d"),  # 15: Datum von
            export_to.strftime("%Y%m%d"),  # 16: Datum bis
            '""',  # 17: (empty string)
            '""',  # 18: (empty string)
            "",  # 19: (empty)
            "",  # 20: (empty)
            "0",  # 21: Festschreibung (0 = not locked)
            '"EUR"',  # 22: Währungskennzeichen
            "",  # 23: (empty)
            '""',  # 24: (empty string)
            "",  # 25: (empty)
            "",  # 26: (empty)
            '""',  # 27: (empty string)
            "",  # 28: (empty)
            "",  # 29: (empty)
            '""',  # 30: (empty string)
            "",  # 31: (trailing empty)
        ]

        header_line = ";".join(fields)
        return [header_line]

    def get_gegenkonto(self, transaction: Transaction) -> int:
        """Get Gegenkonto (contra account) from transaction's source_config.

        Reads check_account_id directly from the source configuration.
        Falls back to DEFAULT_CHECK_ACCOUNT (1200 = Bank) if no source_config.
        """
        if transaction.source_config is not None:
            return transaction.source_config.check_account_id
        return DEFAULT_CHECK_ACCOUNT

    def get_bu_schluessel(self, skr03_account: SKR03Account | None) -> int | None:
        """Get BU-Schlüssel from SKR03 account."""
        if skr03_account is None:
            return None
        return skr03_account.bu_schluessel

    def calculate_vat_amounts(
        self,
        gross_amount: Decimal,
        bu_schluessel: int | None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Calculate net amount and VAT from gross and BU-Schlüssel.

        Returns (net_amount, vat_amount) or (None, None) if no VAT applies.
        """
        if bu_schluessel is None or bu_schluessel not in BU_SCHLUESSEL_TO_VAT_RATE:
            return None, None

        vat_rate = BU_SCHLUESSEL_TO_VAT_RATE[bu_schluessel]
        # gross = net * (1 + vat_rate/100)
        # net = gross / (1 + vat_rate/100)
        divisor = Decimal("1") + vat_rate / Decimal("100")
        net_amount = (gross_amount / divisor).quantize(Decimal("0.01"))
        vat_amount = (gross_amount - net_amount).quantize(Decimal("0.01"))

        return net_amount, vat_amount

    def transaction_to_booking_lines(
        self,
        transaction: Transaction,
    ) -> list[DatevBookingLine]:
        """Convert a transaction to DATEV booking lines.

        Reads SKR03 accounts from linked receipts' line items.
        Each receipt line item becomes a separate DATEV row.
        Access path: transaction.receipt_links → receipt.line_items → skr03_account

        Reverse Charge (§13b): BU-Schlüssel derived from tax_rule, not SKR03 account.
        """
        booking_lines = []
        gegenkonto = self.get_gegenkonto(transaction)

        for link in transaction.receipt_links:
            receipt = link.receipt
            for line_item in receipt.line_items:
                booking_lines.append(
                    self._create_booking_line(
                        line_item=line_item,
                        receipt=receipt,
                        gegenkonto=gegenkonto,
                        transaction_date=transaction.date,
                        reference=transaction.id[:8],
                        booking_text=self._create_booking_text(transaction, line_item),
                        counterparty=transaction.counterparty,
                    )
                )

        return booking_lines

    def _create_booking_line(
        self,
        line_item: ReceiptLineItem,
        receipt: Receipt,
        gegenkonto: int,
        transaction_date: date,
        reference: str,
        booking_text: str,
        counterparty: str,
    ) -> DatevBookingLine:
        """Create a single DATEV booking line with Beleglink and Beleginfo.

        Reverse Charge handling:
        - BU 94: §13b with input tax (Regelbesteuert) → Kz.67 filled with VAT
        - BU 95: §13b without input tax (Kleinunternehmer) → Kz.67 empty
        - VAT amount = 19% of net amount (always for RC)
        """
        amount = line_item.amount
        skr03_account = line_item.skr03_account

        # Soll/Haben derived from receipt type AND amount sign
        is_revenue = receipt.type == ReceiptType.REVENUE
        is_positive = amount >= 0

        if is_revenue:
            soll_haben = "H" if is_positive else "S"
        else:
            soll_haben = "S" if is_positive else "H"

        abs_amount = abs(amount)

        # Determine BU-Schlüssel: RC uses tax_rule, otherwise SKR03 account
        is_rc = line_item.tax_rule.is_reverse_charge()
        if is_rc:
            bu_schluessel = line_item.tax_rule.bu_schluessel()
            # Use persisted rc_tax_rate (GoBD: historical rate preserved) via effective_tax_rate property
            vat_rate = line_item.effective_tax_rate
            net_amount = abs_amount
            # Use persisted rc_tax_rate via property
            vat_amount = line_item.reverse_charge_tax_amount or Decimal("0.00")
        else:
            bu_schluessel = self.get_bu_schluessel(skr03_account)
            net_amount, vat_amount = self.calculate_vat_amounts(abs_amount, bu_schluessel)
            vat_rate = BU_SCHLUESSEL_TO_VAT_RATE.get(bu_schluessel) if bu_schluessel else None

        # Generate BEDI GUID only if receipt has a file attached
        beleglink = None
        if receipt.file_storage_id is not None:
            bedi_guid = generate_bedi_guid(receipt.id)
            # Format: BEDI "uuid" (literal quotes inside the string)
            beleglink = f'BEDI "{bedi_guid}"'

        # Leistungsdatum format: DDMMYYYY
        leistungsdatum = receipt.date.strftime("%d%m%Y") if receipt.date else None

        return DatevBookingLine(
            umsatz=abs_amount,
            soll_haben=soll_haben,
            waehrung="EUR",
            konto=skr03_account.id if skr03_account else 9999,
            gegenkonto=gegenkonto,
            bu_schluessel=bu_schluessel,
            belegfeld_1=reference,
            belegfeld_2=None,
            datum=transaction_date,
            buchungstext=booking_text[:60],
            ust_satz=vat_rate,
            netto=net_amount,
            ust_betrag=vat_amount,
            # New fields for ZIP export
            beleglink=beleglink,
            receipt_id=receipt.id,
            beleginfo_beschreibung=receipt.description or booking_text[:60],
            beleginfo_ust_prozent=str(int(vat_rate)) if vat_rate else None,
            beleginfo_name=counterparty,
            beleginfo_nettobetrag=net_amount,
            # BU 95 (Kleinunternehmer §13b): suppress Steuerbetrag — no Vorsteuerabzug (Kz.67 empty)
            # BU 94 (Regelbesteuert §13b): show Steuerbetrag — Vorsteuerabzug applies (Kz.67 filled)
            beleginfo_steuerbetrag=None if is_rc and not line_item.tax_rule.has_input_tax() else vat_amount,
            beleginfo_leistungsdatum=leistungsdatum,
        )

    def _create_booking_text(
        self,
        transaction: Transaction,
        line_item: ReceiptLineItem,
    ) -> str:
        """Create booking text from transaction/line item.

        For Reverse Charge items, includes "§13b" marker for documentation.
        """
        parts = [transaction.counterparty]

        # Add RC marker + VAT ID for §13b documentation (D7)
        if line_item.tax_rule.is_reverse_charge():
            vat_id = None
            if transaction.source_config and transaction.source_config.source_config:
                vat_id = transaction.source_config.source_config.get("vat_id")
            if vat_id:
                parts.append(f"§13b {vat_id}")
            else:
                parts.append("§13b")

        if line_item.description:
            parts.append(line_item.description)
        elif transaction.description and transaction.description != transaction.counterparty:
            parts.append(transaction.description[:30])

        return " - ".join(parts)

    def booking_line_to_row(self, booking_line: DatevBookingLine) -> list[str]:
        """Convert DatevBookingLine to CSV row values (124 columns)."""

        # Helper for German decimal format
        def german_decimal(value: Decimal | None) -> str:
            if value is None:
                return ""
            return f"{value:.2f}".replace(".", ",")

        # Build 124-column row
        row = [""] * 124

        # Columns 1-14: Core booking data
        row[0] = german_decimal(booking_line.umsatz)
        row[1] = booking_line.soll_haben
        row[2] = ""  # WKZ Umsatz (empty, EUR implied)
        row[3] = ""  # Kurs
        row[4] = ""  # Basisumsatz
        row[5] = ""  # WKZ Basisumsatz
        row[6] = str(booking_line.konto)
        row[7] = str(booking_line.gegenkonto)
        row[8] = str(booking_line.bu_schluessel) if booking_line.bu_schluessel else ""
        row[9] = booking_line.datum.strftime("%d%m")  # DDMM
        row[10] = booking_line.belegfeld_1
        row[11] = booking_line.belegfeld_2 or ""
        row[12] = ""  # Skonto
        row[13] = booking_line.buchungstext

        # Columns 15-19: Empty
        # (already empty)

        # Column 20: Beleglink
        row[19] = booking_line.beleglink or ""

        # Columns 21-36: Beleginfo fields (8 pairs)
        # Art 1 / Inhalt 1: Beschreibung
        row[20] = "Beschreibung"
        row[21] = booking_line.beleginfo_beschreibung or ""
        # Art 2 / Inhalt 2: Umsatzsteuerprozent
        row[22] = "Umsatzsteuerprozent"
        row[23] = booking_line.beleginfo_ust_prozent or ""
        # Art 3 / Inhalt 3: Name
        row[24] = "Name"
        row[25] = booking_line.beleginfo_name or ""
        # Art 4 / Inhalt 4: (empty)
        row[26] = ""
        row[27] = ""
        # Art 5 / Inhalt 5: Nettobetrag
        row[28] = "Nettobetrag"
        row[29] = german_decimal(booking_line.beleginfo_nettobetrag)
        # Art 6 / Inhalt 6: Steuerbetrag
        row[30] = "Steuerbetrag"
        row[31] = german_decimal(booking_line.beleginfo_steuerbetrag)
        # Art 7 / Inhalt 7: Leistungsdatum
        row[32] = "Leistungsdatum"
        row[33] = booking_line.beleginfo_leistungsdatum or ""
        # Art 8 / Inhalt 8: Kundennummer (empty for us)
        row[34] = "Kundennummer"
        row[35] = ""

        # Column 114: Leistungsdatum (also stored separately)
        row[113] = booking_line.beleginfo_leistungsdatum or ""

        # Neutralize CSV formula injection in every free-text column. Structured
        # numeric/date/account columns are left untouched so their values stay
        # byte-identical (amounts may legitimately start with '-').
        structured_column_indices = frozenset(
            {0, 1, 6, 7, 8, 9, 23, 29, 31, 33, 113}
        )
        return [
            cell if index in structured_column_indices else neutralize_formula_cell(cell)
            for index, cell in enumerate(row)
        ]

    def generate_csv_bytes(
        self,
        header_block: list[str],
        column_headers: list[str],
        rows: list[list[str]],
    ) -> bytes:
        """Generate complete DATEV CSV content as ISO-8859-1 bytes.

        DATEV expects Latin-1 encoding, not UTF-8.
        """
        buffer = io.BytesIO()
        wrapper = io.TextIOWrapper(buffer, encoding="latin-1", newline="")
        writer = csv.writer(wrapper, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")

        # Write header block (already formatted, write directly)
        for header_line in header_block:
            wrapper.write(header_line + "\n")

        # Write column headers
        writer.writerow(column_headers)

        # Write data rows
        for row in rows:
            writer.writerow(row)

        wrapper.flush()
        wrapper.detach()
        return buffer.getvalue()

    def generate_csv_content(
        self,
        header_block: list[str],
        column_headers: list[str],
        rows: list[list[str]],
    ) -> str:
        """Generate complete DATEV CSV content as string (for backward compatibility)."""
        csv_bytes = self.generate_csv_bytes(header_block, column_headers, rows)
        return csv_bytes.decode("latin-1")

    def generate_document_xml(
        self,
        receipts: list[Receipt],
        receipt_type: ReceiptType,
    ) -> bytes:
        """Generate document.xml manifest for Belegbilder ZIP.

        Format matches sevdesk export (simple variant, no property keys).
        """
        # XML namespace
        namespace = "http://xml.datev.de/bedi/tps/document/v06.0"
        xsi_namespace = "http://www.w3.org/2001/XMLSchema-instance"

        # Register namespaces
        ET.register_namespace("", namespace)
        ET.register_namespace("xsi", xsi_namespace)

        # Create root element
        root = ET.Element(
            "archive",
            {
                "xmlns": namespace,
                f"{{{xsi_namespace}}}schemaLocation": f"{namespace} Document_v060.xsd",
                "generatingSystem": "shop2tax",
                "version": "6.0",
            },
        )

        # Header with timestamp
        header = ET.SubElement(root, "header")
        date_elem = ET.SubElement(header, "date")
        date_elem.text = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        # Content with documents
        content = ET.SubElement(root, "content")

        for receipt in receipts:
            if receipt.file_storage_id is None:
                continue

            bedi_guid = generate_bedi_guid(receipt.id)
            # type="1" = Rechnungseingang (EXPENSE), type="2" = Rechnungsausgang (REVENUE)
            doc_type = "2" if receipt_type == ReceiptType.REVENUE else "1"

            document = ET.SubElement(
                content,
                "document",
                {
                    "guid": bedi_guid,
                    "type": doc_type,
                },
            )

            # Build filename: YYYY-MM-DD_Belegtyp_Belegnummer_hash.ext
            belegtyp = "Einnahmebeleg" if receipt_type == ReceiptType.REVENUE else "Ausgabebeleg"
            belegnummer = sanitize_filename(receipt.receipt_number or receipt.id[:8])
            file_hash = receipt.file_hash[:32] if receipt.file_hash else "unknown"
            ext = "pdf"  # Assume PDF, could detect from mime_type
            if receipt.file_mime_type == "image/jpeg":
                ext = "jpg"
            elif receipt.file_mime_type == "image/png":
                ext = "png"

            filename = f"{receipt.date.isoformat()}_{belegtyp}_{belegnummer}_{file_hash}.{ext}"

            ET.SubElement(
                document,
                "extension",
                {
                    "name": filename,
                    f"{{{xsi_namespace}}}type": "File",
                },
            )

        # Generate XML bytes with declaration
        return b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>' + ET.tostring(root, encoding="unicode").encode("utf-8")

    def export(
        self,
        config: DatevConfig,
        date_from: date | None = None,
        date_to: date | None = None,
        include_unreconciled: bool = False,
    ) -> DatevExportResponse:
        """Generate complete DATEV export."""
        # Build query for transactions
        query = (
            select(Transaction).where(Transaction.deleted_at.is_(None)).where(Transaction.is_private == False)  # noqa: E712 - SQLAlchemy needs ==
        )

        # Filter: only transactions with linked receipts (SKR03 lives on receipts)
        if not include_unreconciled:
            query = query.where(Transaction.id.in_(select(ReceiptTransactionLink.transaction_id)))

        # Filter by date range
        if date_from:
            query = query.where(Transaction.date >= date_from)
        if date_to:
            query = query.where(Transaction.date <= date_to)

        # Eager load receipt path for DATEV export

        query = query.options(
            joinedload(Transaction.receipt_links)
            .joinedload(ReceiptTransactionLink.receipt)
            .joinedload(Receipt.line_items)
            .joinedload(ReceiptLineItem.skr03_account),
        )

        # Order by date for consistent export
        query = query.order_by(Transaction.date.asc(), Transaction.id.asc())

        transactions = self.database.execute(query).unique().scalars().all()

        # Generate header block
        header_block = self.generate_header_block(config, date_from, date_to)

        # Convert transactions to booking lines
        all_booking_lines: list[DatevBookingLine] = []
        for transaction in transactions:
            booking_lines = self.transaction_to_booking_lines(transaction)
            all_booking_lines.extend(booking_lines)

        # Convert to rows
        rows = [self.booking_line_to_row(bz) for bz in all_booking_lines]

        # Generate CSV content
        csv_content = self.generate_csv_content(header_block, self.DATEV_COLUMNS, rows)

        return DatevExportResponse(
            header=header_block,
            column_headers=self.DATEV_COLUMNS,
            rows=rows,
            transaction_count=len(transactions),
            line_item_count=len(all_booking_lines),
            csv_content=csv_content,
        )

    def export_zip(
        self,
        config: DatevConfig,
        date_from: date | None = None,
        date_to: date | None = None,
        include_receipts: bool = True,
        finalized_only: bool = False,
        document_types: list[str] | None = None,
    ) -> DatevZipExportResponse:
        """Generate DATEV ZIP export with Belegbilder.

        ZIP structure:
        - EXTF_Buchungsstapel.csv
        - DATEV_Rechnungseingang_YYYYMMDD_bis_YYYYMMDD.zip (EXPENSE receipts)
        - DATEV_Rechnungsausgang_YYYYMMDD_bis_YYYYMMDD.zip (REVENUE receipts)
        """
        from app.models.receipt import ReceiptStatus
        from app.services.receipt_storage import get_file_content

        # Build query for transactions
        query = (
            select(Transaction).where(Transaction.deleted_at.is_(None)).where(Transaction.is_private == False)  # noqa: E712
        )

        # Filter: only transactions with linked receipts
        query = query.where(Transaction.id.in_(select(ReceiptTransactionLink.transaction_id)))

        # Filter by date range
        if date_from:
            query = query.where(Transaction.date >= date_from)
        if date_to:
            query = query.where(Transaction.date <= date_to)

        # Eager load receipt path

        query = query.options(
            joinedload(Transaction.receipt_links)
            .joinedload(ReceiptTransactionLink.receipt)
            .joinedload(Receipt.line_items)
            .joinedload(ReceiptLineItem.skr03_account),
        )

        query = query.order_by(Transaction.date.asc(), Transaction.id.asc())

        transactions = self.database.execute(query).unique().scalars().all()

        # Generate CSV
        header_block = self.generate_header_block(config, date_from, date_to)
        all_booking_lines: list[DatevBookingLine] = []
        for transaction in transactions:
            booking_lines = self.transaction_to_booking_lines(transaction)
            all_booking_lines.extend(booking_lines)

        rows = [self.booking_line_to_row(bz) for bz in all_booking_lines]
        csv_bytes = self.generate_csv_bytes(header_block, self.DATEV_COLUMNS, rows)

        # Collect receipts with files, grouped by type
        revenue_receipts: list[Receipt] = []
        expense_receipts: list[Receipt] = []
        receipts_without_file: list[str] = []

        seen_receipts: set[str] = set()
        for transaction in transactions:
            for link in transaction.receipt_links:
                receipt = link.receipt
                if receipt.id in seen_receipts:
                    continue
                seen_receipts.add(receipt.id)

                # Apply filters
                if finalized_only and receipt.status != ReceiptStatus.FINAL:
                    continue
                if document_types:
                    if receipt.type == ReceiptType.REVENUE and "revenue" not in document_types:
                        continue
                    if receipt.type == ReceiptType.EXPENSE and "expense" not in document_types:
                        continue

                if receipt.file_storage_id is None:
                    receipts_without_file.append(receipt.receipt_number or receipt.id[:8])
                    continue

                if receipt.type == ReceiptType.REVENUE:
                    revenue_receipts.append(receipt)
                else:
                    expense_receipts.append(receipt)

        # Build date range string for filenames
        export_from = date_from or date(config.wirtschaftsjahr_beginn.year, 1, 1)
        export_to = date_to or date.today()
        date_range = f"{export_from.strftime('%Y%m%d')}_bis_{export_to.strftime('%Y%m%d')}"

        # Create main ZIP
        main_zip_buffer = io.BytesIO()
        with zipfile.ZipFile(main_zip_buffer, "w", zipfile.ZIP_DEFLATED) as main_zip:
            # Add CSV
            main_zip.writestr(f"EXTF_Buchungsstapel_{date_range}.csv", csv_bytes)

            if include_receipts:
                # Create Rechnungsausgang (REVENUE) nested ZIP
                if revenue_receipts:
                    revenue_zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(revenue_zip_buffer, "w", zipfile.ZIP_DEFLATED) as revenue_zip:
                        # Add document.xml
                        doc_xml = self.generate_document_xml(revenue_receipts, ReceiptType.REVENUE)
                        revenue_zip.writestr("document.xml", doc_xml)

                        # Add files
                        for receipt in revenue_receipts:
                            if receipt.file_storage_id is None or receipt.file_hash is None:
                                receipts_without_file.append(receipt.receipt_number or receipt.id[:8])
                                continue
                            try:
                                content = get_file_content(receipt.file_storage_id, receipt.file_hash)
                                # Build filename
                                belegnummer = sanitize_filename(receipt.receipt_number or receipt.id[:8])
                                file_hash = receipt.file_hash[:32]
                                ext = "pdf"
                                if receipt.file_mime_type == "image/jpeg":
                                    ext = "jpg"
                                elif receipt.file_mime_type == "image/png":
                                    ext = "png"
                                filename = f"{receipt.date.isoformat()}_Einnahmebeleg_{belegnummer}_{file_hash}.{ext}"
                                revenue_zip.writestr(filename, content)
                            except Exception:
                                receipts_without_file.append(receipt.receipt_number or receipt.id[:8])

                    revenue_zip_buffer.seek(0)
                    main_zip.writestr(f"DATEV_Rechnungsausgang_{date_range}.zip", revenue_zip_buffer.read())

                # Create Rechnungseingang (EXPENSE) nested ZIP
                if expense_receipts:
                    expense_zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(expense_zip_buffer, "w", zipfile.ZIP_DEFLATED) as expense_zip:
                        # Add document.xml
                        doc_xml = self.generate_document_xml(expense_receipts, ReceiptType.EXPENSE)
                        expense_zip.writestr("document.xml", doc_xml)

                        # Add files
                        for receipt in expense_receipts:
                            if receipt.file_storage_id is None or receipt.file_hash is None:
                                receipts_without_file.append(receipt.receipt_number or receipt.id[:8])
                                continue
                            try:
                                content = get_file_content(receipt.file_storage_id, receipt.file_hash)
                                belegnummer = sanitize_filename(receipt.receipt_number or receipt.id[:8])
                                file_hash = receipt.file_hash[:32]
                                ext = "pdf"
                                if receipt.file_mime_type == "image/jpeg":
                                    ext = "jpg"
                                elif receipt.file_mime_type == "image/png":
                                    ext = "png"
                                filename = f"{receipt.date.isoformat()}_Ausgabebeleg_{belegnummer}_{file_hash}.{ext}"
                                expense_zip.writestr(filename, content)
                            except Exception:
                                receipts_without_file.append(receipt.receipt_number or receipt.id[:8])

                    expense_zip_buffer.seek(0)
                    main_zip.writestr(f"DATEV_Rechnungseingang_{date_range}.zip", expense_zip_buffer.read())

        main_zip_buffer.seek(0)
        zip_bytes = main_zip_buffer.read()

        return DatevZipExportResponse(
            zip_content=zip_bytes,
            filename=f"DATEV_Export_{date_range}.zip",
            transaction_count=len(transactions),
            line_item_count=len(all_booking_lines),
            revenue_receipt_count=len(revenue_receipts),
            expense_receipt_count=len(expense_receipts),
            receipts_without_file=receipts_without_file,
            zip_size_bytes=len(zip_bytes),
        )

    def log_export(
        self,
        user_id: str,
        config: DatevConfig,
        export_response: DatevExportResponse,
        date_from: date | None,
        date_to: date | None,
        filename: str | None = None,
        export_format: str = "csv",
    ) -> ExportLog:
        """Create an export log entry."""
        export_log = ExportLog(
            user_id=user_id,
            export_type="datev",
            transaction_count=export_response.transaction_count,
            line_item_count=export_response.line_item_count,
            date_from=date_from,
            date_to=date_to,
            beraternummer=config.beraternummer,
            mandantennummer=config.mandantennummer,
            filename=filename,
        )
        self.database.add(export_log)
        self.database.commit()
        self.database.refresh(export_log)
        return export_log

    def validate(self, export_response: DatevExportResponse) -> DatevValidationResult:
        """Validate DATEV export format."""
        errors = []
        warnings = []

        # Check header block
        if len(export_response.header) < 1:
            errors.append("Missing DATEV header block")

        if export_response.header and not export_response.header[0].startswith('"EXTF"'):
            errors.append("Invalid DATEV header format: must start with EXTF")

        # Check data rows
        if not export_response.rows:
            warnings.append("Export contains no transactions")

        for index, row in enumerate(export_response.rows, start=1):
            # Check required fields (now 124 columns)
            if len(row) < 124:
                errors.append(f"Row {index}: Missing columns (expected 124, got {len(row)})")
                continue

            # Check Umsatz (amount) - column 1
            umsatz = row[0]
            if not umsatz or umsatz == "0,00":
                warnings.append(f"Row {index}: Zero or empty amount")

            # Check Soll/Haben - column 2
            soll_haben = row[1]
            if soll_haben not in ("S", "H"):
                errors.append(f"Row {index}: Invalid Soll/Haben value '{soll_haben}' (must be S or H)")

            # Check Konto - column 7
            konto = row[6]
            if not konto.isdigit():
                errors.append(f"Row {index}: Invalid account number '{konto}'")
            elif konto == "9999":
                warnings.append(f"Row {index}: Unassigned account (9999)")

            # Check Gegenkonto - column 8
            gegenkonto = row[7]
            if not gegenkonto.isdigit():
                errors.append(f"Row {index}: Invalid contra account '{gegenkonto}'")

        return DatevValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def validate_zip(
        self,
        config: DatevConfig,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> DatevValidationResult:
        """Validate ZIP export before generating.

        Checks for potential issues without creating the full export.
        """
        warnings = []

        # Query receipts that would be included
        query = select(Receipt).where(
            Receipt.deleted_at.is_(None),
        )

        if date_from:
            query = query.where(Receipt.date >= date_from)
        if date_to:
            query = query.where(Receipt.date <= date_to)

        receipts = self.database.execute(query).scalars().all()

        # Check for receipts without files
        without_file = [r.receipt_number or r.id[:8] for r in receipts if r.file_storage_id is None]
        if without_file:
            if len(without_file) <= 5:
                warnings.append(f"Belegbild fehlt für: {', '.join(without_file)}")
            else:
                warnings.append(f"Belegbild fehlt für {len(without_file)} Belege")

        # Estimate ZIP size (rough: 100KB per receipt)
        estimated_size = len([r for r in receipts if r.file_storage_id]) * 100 * 1024
        if estimated_size > 465 * 1024 * 1024:  # 465 MB DATEV limit
            warnings.append("Geschätzte ZIP-Größe überschreitet DATEV Document-Package Limit (465 MB)")

        return DatevValidationResult(
            valid=True,  # Warnings don't block export
            errors=[],
            warnings=warnings,
        )
