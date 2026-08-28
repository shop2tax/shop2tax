"""Document extraction service: ZUGFeRD/Factur-X XML parsing + Vision-LLM OCR.

Extracts structured invoice data from PDF/image documents:
1. ZUGFeRD/Factur-X — embedded CII XML (free, deterministic)
2. Vision-LLM — Gemini, OpenAI, Anthropic (configurable, ~0.02-0.4 ct/receipt)
3. Manual fallback — empty result when extraction fails
"""

from __future__ import annotations

import base64
import io
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET
import httpx
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from sqlalchemy.orm import Session

from app.schemas.extraction import ExtractionLineItem, ExtractionResult

if TYPE_CHECKING:
    # Vision-LLM request param types (annotation-only — not imported at runtime).
    from anthropic.types import DocumentBlockParam, ImageBlockParam, MessageParam
    from openai.types.chat import ChatCompletionContentPartParam, ChatCompletionMessageParam

logger = logging.getLogger(__name__)

# CII (Cross Industry Invoice) namespaces used in ZUGFeRD/Factur-X
CII_NAMESPACES = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}

# Valid ZUGFeRD/Factur-X and XRechnung profile URIs per EN16931 spec
_KNOWN_ZUGFERD_PROFILES = {
    "urn:factur-x.eu:1p0:minimum",
    "urn:factur-x.eu:1p0:basicwl",
    "urn:factur-x.eu:1p0:basic",
    "urn:factur-x.eu:1p0:en16931",
    "urn:factur-x.eu:1p0:extended",
    # XRechnung
    "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0",
    "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_2.3",
    "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_1.2",
    # ZUGFeRD 1.0 (legacy)
    "urn:ferd:CrossIndustryDocument:invoice:1p0:comfort",
    "urn:ferd:CrossIndustryDocument:invoice:1p0:extended",
    "urn:ferd:CrossIndustryDocument:invoice:1p0:basic",
}


def extract_zugferd_xml(pdf_bytes: bytes) -> bytes | None:
    """Extract ZUGFeRD/Factur-X XML attachment from a PDF.

    Reads PDF attachments and returns the first XML file found.
    ZUGFeRD PDFs (PDF/A-3) embed the invoice XML as an attachment.

    Returns None if no XML attachment is found or the PDF cannot be read.
    """
    try:
        reader = PdfReader(stream=io.BytesIO(pdf_bytes))
        for name, content in reader.attachments.items():
            if name.lower().endswith(".xml"):
                xml_bytes = content[0] if isinstance(content, list) else content
                if isinstance(xml_bytes, str):
                    xml_bytes = xml_bytes.encode("utf-8")
                logger.info("ZUGFeRD XML found in PDF attachment: %s", name)
                return xml_bytes
    except PdfReadError:
        logger.exception("Failed to read PDF attachments")
        return None

    logger.debug("No XML attachment found in PDF")
    return None


def _parse_date(text: str | None) -> str | None:
    """Convert YYYYMMDD date string to YYYY-MM-DD format."""
    if text and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return None


def _find_text(element: Element, xpath: str) -> str | None:
    """Find text content at xpath within element using CII namespaces."""
    node = element.find(xpath, CII_NAMESPACES)
    return node.text if node is not None else None


def _parse_decimal(text: str | None) -> Decimal | None:
    """Parse a string to Decimal, returning None on failure."""
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def detect_xml_invoice_format(xml_bytes: bytes) -> str | None:
    """Detect e-invoice format from XML root element namespace.

    Returns:
        "cii" for Cross Industry Invoice (ZUGFeRD/Factur-X/XRechnung CII),
        "ubl" for Universal Business Language (XRechnung UBL),
        None for unknown/non-invoice XML.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return None
    tag = root.tag
    if "CrossIndustryInvoice" in tag:
        return "cii"
    if tag.endswith("}Invoice") and "oasis" in tag and "ubl" in tag:
        return "ubl"
    return None


def parse_zugferd_xml(xml_bytes: bytes) -> ExtractionResult:
    """Parse ZUGFeRD/Factur-X CII XML into structured extraction data.

    Uses defusedxml.ElementTree for safe XML parsing (prevents
    XML bomb / entity expansion attacks from manipulated PDFs).
    """
    root = ET.fromstring(xml_bytes)

    warnings: list[str] = []

    # GuidelineID check
    context = root.find("rsm:ExchangedDocumentContext", CII_NAMESPACES)
    if context is not None:
        guideline_id = _find_text(context, "ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
        if guideline_id and guideline_id not in _KNOWN_ZUGFERD_PROFILES:
            warnings.append(f"Unbekanntes ZUGFeRD-Profil: {guideline_id}")

    header = root.find(".//rsm:ExchangedDocument", CII_NAMESPACES)
    trade = root.find(".//rsm:SupplyChainTradeTransaction", CII_NAMESPACES)
    agreement = trade.find("ram:ApplicableHeaderTradeAgreement", CII_NAMESPACES) if trade is not None else None
    delivery = trade.find("ram:ApplicableHeaderTradeDelivery", CII_NAMESPACES) if trade is not None else None
    settlement = trade.find("ram:ApplicableHeaderTradeSettlement", CII_NAMESPACES) if trade is not None else None

    # Receipt number
    receipt_number = _find_text(header, "ram:ID") if header is not None else None

    # Issue date
    date = None
    if header is not None:
        date_node = header.find("ram:IssueDateTime/udt:DateTimeString", CII_NAMESPACES)
        if date_node is not None:
            date = _parse_date(date_node.text)

    # Delivery date
    delivery_date = None
    if delivery is not None:
        delivery_date_node = delivery.find(
            "ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString",
            CII_NAMESPACES,
        )
        if delivery_date_node is not None:
            delivery_date = _parse_date(delivery_date_node.text)

    # Seller info
    counterparty = None
    counterparty_address = None
    tax_number = None
    vat_id = None

    if agreement is not None:
        seller = agreement.find("ram:SellerTradeParty", CII_NAMESPACES)
        if seller is not None:
            counterparty = _find_text(seller, "ram:Name")

            # Address
            address = seller.find("ram:PostalTradeAddress", CII_NAMESPACES)
            if address is not None:
                parts = []
                line = _find_text(address, "ram:LineOne")
                if line:
                    parts.append(line)
                postcode = _find_text(address, "ram:PostcodeCode")
                city = _find_text(address, "ram:CityName")
                if postcode and city:
                    parts.append(f"{postcode} {city}")
                country = _find_text(address, "ram:CountryID")
                if country:
                    parts.append(country)
                if parts:
                    counterparty_address = ", ".join(parts)

            # Tax registrations
            for tax_registration in seller.findall("ram:SpecifiedTaxRegistration", CII_NAMESPACES):
                tax_id_element = tax_registration.find("ram:ID", CII_NAMESPACES)
                if tax_id_element is not None:
                    scheme = tax_id_element.get("schemeID", "")
                    if scheme == "VA":
                        vat_id = tax_id_element.text
                    elif scheme == "FC":
                        tax_number = tax_id_element.text

    # Currency
    currency = (_find_text(settlement, "ram:InvoiceCurrencyCode") if settlement is not None else "EUR") or "EUR"

    # Line items
    line_items: list[ExtractionLineItem] = []
    if trade is not None:
        for item in trade.findall("ram:IncludedSupplyChainTradeLineItem", CII_NAMESPACES):
            description = None
            product = item.find("ram:SpecifiedTradeProduct", CII_NAMESPACES)
            if product is not None:
                description = _find_text(product, "ram:Name")

            quantity = None
            delivery_item = item.find("ram:SpecifiedLineTradeDelivery", CII_NAMESPACES)
            if delivery_item is not None:
                quantity = _parse_decimal(_find_text(delivery_item, "ram:BilledQuantity"))

            unit_price = None
            agreement_item = item.find("ram:SpecifiedLineTradeAgreement", CII_NAMESPACES)
            if agreement_item is not None:
                unit_price = _parse_decimal(
                    _find_text(
                        agreement_item,
                        "ram:NetPriceProductTradePrice/ram:ChargeAmount",
                    )
                )

            amount = None
            tax_rate = None
            settlement_item = item.find("ram:SpecifiedLineTradeSettlement", CII_NAMESPACES)
            if settlement_item is not None:
                amount = _parse_decimal(
                    _find_text(
                        settlement_item,
                        "ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
                    )
                )
                tax_element = settlement_item.find("ram:ApplicableTradeTax", CII_NAMESPACES)
                if tax_element is not None:
                    tax_rate = _parse_decimal(_find_text(tax_element, "ram:RateApplicablePercent"))

            line_items.append(
                ExtractionLineItem(
                    description=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    amount=amount,
                    tax_rate=tax_rate,
                )
            )

    # Line item math check (EN16931 BR-24: LineTotalAmount = BilledQuantity × NetPriceProductTradePrice)
    for index, item in enumerate(line_items, start=1):
        if item.quantity is not None and item.unit_price is not None and item.amount is not None:
            expected = (item.quantity * item.unit_price).quantize(Decimal("0.01"))
            if abs(expected - item.amount) > Decimal("0.02"):
                warnings.append(f"Position {index}: Menge × Einzelpreis ({item.quantity} × {item.unit_price}) ≠ Zeilenbetrag ({item.amount})")

    # Totals
    total_net = None
    total_tax = None
    total_gross = None
    due_date = None
    billing_period = None
    payment_method = None
    payment_reference = None
    payer_iban = None

    if settlement is not None:
        summary = settlement.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", CII_NAMESPACES)
        if summary is not None:
            total_net = _parse_decimal(_find_text(summary, "ram:TaxBasisTotalAmount"))
            total_tax = _parse_decimal(_find_text(summary, "ram:TaxTotalAmount"))
            total_gross = _parse_decimal(_find_text(summary, "ram:GrandTotalAmount"))

        # Due date
        payment_terms = settlement.find("ram:SpecifiedTradePaymentTerms", CII_NAMESPACES)
        if payment_terms is not None:
            due_date_node = payment_terms.find("ram:DueDateDateTime/udt:DateTimeString", CII_NAMESPACES)
            if due_date_node is not None:
                due_date = _parse_date(due_date_node.text)

        # Payment method + payer IBAN
        payment_means = settlement.find("ram:SpecifiedTradeSettlementPaymentMeans", CII_NAMESPACES)
        if payment_means is not None:
            payment_method = _find_text(payment_means, "ram:Information")
            payer_iban = _find_text(payment_means, "ram:PayerPartyDebtorFinancialAccount/ram:IBANID")

        # Payment reference
        payment_reference = _find_text(settlement, "ram:PaymentReference")

        # Billing period
        billing_period_element = settlement.find("ram:BillingSpecifiedPeriod", CII_NAMESPACES)
        if billing_period_element is not None:
            start = billing_period_element.find("ram:StartDateTime/udt:DateTimeString", CII_NAMESPACES)
            end = billing_period_element.find("ram:EndDateTime/udt:DateTimeString", CII_NAMESPACES)
            period_parts = []
            for node in [start, end]:
                if node is not None and node.text:
                    parsed = _parse_date(node.text)
                    if parsed:
                        period_parts.append(parsed)
            if period_parts:
                billing_period = " bis ".join(period_parts)

    return ExtractionResult(
        source="zugferd",
        warnings=warnings,
        receipt_number=receipt_number,
        date=date,
        delivery_date=delivery_date,
        due_date=due_date,
        billing_period=billing_period,
        counterparty=counterparty,
        counterparty_address=counterparty_address,
        tax_number=tax_number,
        vat_id=vat_id,
        currency=currency,
        line_items=line_items,
        total_net=total_net,
        total_tax=total_tax,
        total_gross=total_gross,
        payment_method=payment_method,
        payment_reference=payment_reference,
        payer_iban=payer_iban,
    )


# ---------------------------------------------------------------------------
# 🤖 Vision-LLM extraction
# ---------------------------------------------------------------------------

MAX_PAGES_FOR_LLM = 5
LLM_TIMEOUT_SECONDS = 30
LLM_TIMEOUT_MS = LLM_TIMEOUT_SECONDS * 1000  # google-genai HttpOptions expects milliseconds

# Shared prompt for all providers (German, JSON output)
EXTRACTION_PROMPT = """Extrahiere alle Rechnungsdaten aus diesem Dokument als JSON.

Felder:
- receipt_number: Rechnungsnummer / Belegnummer
- date: Rechnungsdatum (YYYY-MM-DD)
- delivery_date: Lieferdatum (YYYY-MM-DD, falls vorhanden)
- counterparty: Lieferant / Absender (Firmenname)
- counterparty_address: Adresse des Lieferanten (falls vorhanden)
- tax_number: Steuernummer des Lieferanten (falls vorhanden)
- vat_id: USt-ID des Lieferanten (falls vorhanden)
- currency: Währung (ISO 4217, default EUR)
- line_items: Array von Positionen, jeweils:
  - description: Beschreibung
  - quantity: Menge (falls vorhanden)
  - unit_price: Einzelpreis netto (falls vorhanden)
  - amount: NETTO-Betrag der Position (ohne Umsatzsteuer!)
  - tax_rate: Steuersatz in % (falls erkennbar)
- total_net: Nettobetrag gesamt (Summe aller Positionen ohne USt)
- total_tax: Steuerbetrag gesamt
- total_gross: Bruttobetrag gesamt (inkl. USt, der Betrag den der Käufer zahlt)
- payment_date: Zahldatum / Bezahldatum (YYYY-MM-DD, falls vorhanden)
- payment_method: Zahlungsart (falls vorhanden)
- payment_reference: Verwendungszweck (falls vorhanden)
- payer_iban: IBAN des Empfängers (falls vorhanden)
- due_date: Fälligkeitsdatum (YYYY-MM-DD, falls vorhanden)
- billing_period: Abrechnungszeitraum (falls vorhanden)

WICHTIG: "amount" in line_items ist immer der NETTO-Betrag (ohne Steuer).
Zwischensummen, Versandkosten oder sonstige Nebenkosten NICHT als amount verwenden.
total_gross ist der Endbetrag inkl. aller Steuern.

Antworte NUR mit validem JSON, kein Markdown, kein Text drumherum."""

# 💰 Hardcoded pricing per 1M tokens (USD)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1m, output_per_1m)
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}


def _calculate_cost_cents(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Calculate extraction cost in cents from token counts."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        logger.warning("Unknown model %r not in MODEL_PRICING — cost_cents will be None", model)
        return None
    input_per_million, output_per_million = pricing
    cost_usd = (input_tokens * input_per_million + output_tokens * output_per_million) / 1_000_000
    return round(cost_usd * 100, 4)


def _truncate_pdf(pdf_bytes: bytes, max_pages: int = MAX_PAGES_FOR_LLM) -> bytes:
    """Truncate PDF to first N pages. Returns original bytes if <= max_pages."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if len(reader.pages) <= max_pages:
        return pdf_bytes
    writer = PdfWriter()
    for page in reader.pages[:max_pages]:
        writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    logger.info(
        "Truncated PDF from %d to %d pages for LLM extraction",
        len(reader.pages),
        max_pages,
    )
    return buffer.getvalue()


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences from LLM JSON responses."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _parse_llm_response(text: str, source: str) -> ExtractionResult:
    """Parse LLM JSON response into ExtractionResult. Returns manual fallback on failure."""
    cleaned = _clean_json_response(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON (source=%s): %s", source, text[:200])
        return ExtractionResult(source="manual")

    # Normalize: LLM may return flat dict without 'source'
    data["source"] = source
    # Remove fields not in ExtractionResult schema
    data.pop("payment_info", None)
    data.pop("notes", None)

    try:
        return ExtractionResult.model_validate(data)
    except ValidationError:
        logger.warning("LLM response failed schema validation (source=%s)", source, exc_info=True)
        return ExtractionResult(source="manual")


async def call_gemini_vision(file_bytes: bytes, mime_type: str, api_key: str, model: str) -> ExtractionResult:
    """Extract invoice data via Google Gemini Vision API."""
    from google import genai
    from google.genai import types

    # Truncate PDFs to MAX_PAGES_FOR_LLM
    if mime_type == "application/pdf":
        file_bytes = _truncate_pdf(file_bytes)

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS),
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                EXTRACTION_PROMPT,
            ],
            config=types.GenerateContentConfig(temperature=0.0),
        )
    except httpx.TimeoutException:
        logger.warning("Gemini vision call timed out after %ds", LLM_TIMEOUT_SECONDS)
        return ExtractionResult(source="manual")
    except Exception:
        logger.exception("Gemini vision call failed")
        return ExtractionResult(source="manual")

    result = _parse_llm_response(response.text or "", source="gemini")

    # Token usage
    usage = response.usage_metadata
    if usage:
        result.input_tokens = usage.prompt_token_count
        result.output_tokens = usage.candidates_token_count
        result.cost_cents = _calculate_cost_cents(model, result.input_tokens or 0, result.output_tokens or 0)

    return result


async def call_openai_vision(file_bytes: bytes, mime_type: str, api_key: str, model: str) -> ExtractionResult:
    """Extract invoice data via OpenAI Vision API."""
    from openai import AsyncOpenAI

    # Truncate PDFs to MAX_PAGES_FOR_LLM
    if mime_type == "application/pdf":
        file_bytes = _truncate_pdf(file_bytes)

    encoded = base64.standard_b64encode(file_bytes).decode()
    data_url = f"data:{mime_type};base64,{encoded}"

    client = AsyncOpenAI(api_key=api_key, timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS))

    # Use file attachment for PDFs, image_url for images
    file_content: ChatCompletionContentPartParam
    if mime_type == "application/pdf":
        file_content = {
            "type": "file",
            "file": {"filename": "document.pdf", "file_data": data_url},
        }
    else:
        file_content = {
            "type": "image_url",
            "image_url": {"url": data_url},
        }

    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "user",
            "content": [
                file_content,
                {"type": "text", "text": EXTRACTION_PROMPT},
            ],
        }
    ]

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=messages,
        )
    except httpx.TimeoutException:
        logger.warning("OpenAI vision call timed out after %ds", LLM_TIMEOUT_SECONDS)
        return ExtractionResult(source="manual")
    except Exception:
        logger.exception("OpenAI vision call failed")
        return ExtractionResult(source="manual")

    result_text = response.choices[0].message.content or ""
    result = _parse_llm_response(result_text, source="openai")

    # Token usage
    usage = response.usage
    if usage:
        result.input_tokens = usage.prompt_tokens
        result.output_tokens = usage.completion_tokens
        result.cost_cents = _calculate_cost_cents(model, result.input_tokens or 0, result.output_tokens or 0)

    return result


def _anthropic_image_media_type(mime_type: str) -> Literal["image/jpeg", "image/png", "image/gif", "image/webp"]:
    """Narrow an image MIME type to the literal set Anthropic's vision API accepts."""
    match mime_type:
        case "image/jpeg" | "image/png" | "image/gif" | "image/webp" as media_type:
            return media_type
        case _:
            raise ValueError(f"Unsupported image media type for Anthropic vision: {mime_type}")


async def call_anthropic_vision(file_bytes: bytes, mime_type: str, api_key: str, model: str) -> ExtractionResult:
    """Extract invoice data via Anthropic Claude Vision API."""
    from anthropic import AsyncAnthropic

    # Truncate PDFs to MAX_PAGES_FOR_LLM
    if mime_type == "application/pdf":
        file_bytes = _truncate_pdf(file_bytes)

    encoded = base64.standard_b64encode(file_bytes).decode()

    client = AsyncAnthropic(
        api_key=api_key,
        timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS),
    )

    # Anthropic uses "document" type for PDFs, "image" for images
    document_content: DocumentBlockParam | ImageBlockParam
    if mime_type == "application/pdf":
        document_content = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
        }
    else:
        document_content = {
            "type": "image",
            "source": {"type": "base64", "media_type": _anthropic_image_media_type(mime_type), "data": encoded},
        }

    messages: list[MessageParam] = [
        {
            "role": "user",
            "content": [
                document_content,
                {"type": "text", "text": EXTRACTION_PROMPT},
            ],
        }
    ]

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            messages=messages,
            temperature=0.0,
        )
    except httpx.TimeoutException:
        logger.warning("Anthropic vision call timed out after %ds", LLM_TIMEOUT_SECONDS)
        return ExtractionResult(source="manual")
    except Exception:
        logger.exception("Anthropic vision call failed")
        return ExtractionResult(source="manual")

    first_block = response.content[0]
    result_text = first_block.text if first_block.type == "text" else ""
    result = _parse_llm_response(result_text, source="anthropic")

    # Token usage
    result.input_tokens = response.usage.input_tokens
    result.output_tokens = response.usage.output_tokens
    result.cost_cents = _calculate_cost_cents(model, result.input_tokens or 0, result.output_tokens or 0)

    return result


# Provider dispatch table
_PROVIDER_DISPATCH = {
    "gemini": call_gemini_vision,
    "openai": call_openai_vision,
    "anthropic": call_anthropic_vision,
}


async def call_vision_llm(
    file_bytes: bytes,
    mime_type: str,
    provider: str,
    api_key: str,
    model: str,
) -> ExtractionResult:
    """Dispatch vision extraction to configured AI provider.

    Args:
        file_bytes: Raw file content (PDF or image)
        mime_type: MIME type of the file
        provider: AI provider name ("gemini", "openai", "anthropic")
        api_key: API key for the provider
        model: Model identifier (e.g. "gemini-2.5-flash", "gpt-4o-mini")

    Returns:
        ExtractionResult with source set to provider name, or "manual" on failure.
    """
    dispatch_function = _PROVIDER_DISPATCH.get(provider)
    if dispatch_function is None:
        logger.error("Unknown AI provider: %s", provider)
        return ExtractionResult(source="manual")

    logger.info("Starting %s vision extraction (model=%s, mime=%s)", provider, model, mime_type)
    result = await dispatch_function(file_bytes, mime_type, api_key, model)
    logger.info(
        "Extraction complete (source=%s, tokens=%s/%s, cost=%.4f ct)",
        result.source,
        result.input_tokens,
        result.output_tokens,
        result.cost_cents or 0,
    )
    return result


# Provider → Settings attribute mapping
_PROVIDER_API_KEY_ATTR = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
}

# MIME types that are standalone XML (not suitable for Vision-LLM)
_XML_MIME_TYPES = {"application/xml", "text/xml"}


def _get_pdf_page_count(pdf_bytes: bytes) -> int | None:
    """Get total page count of a PDF. Returns None on failure."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        return None


def _log_extraction(
    database: Session,
    *,
    user_id: str,
    source: str,
    model: str | None,
    mime_type: str,
    success: bool,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_cents: float | None = None,
    pages_total: int | None = None,
    pages_sent: int | None = None,
    error_message: str | None = None,
) -> None:
    """Write an AIExtractionLog entry."""
    from app.models.ai_extraction_log import AIExtractionLog

    log_entry = AIExtractionLog(
        user_id=user_id,
        source=source,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cents=cost_cents,
        file_mime_type=mime_type,
        file_pages_total=pages_total,
        file_pages_sent=pages_sent,
        success=success,
        error_message=error_message[:500] if error_message else None,
    )
    database.add(log_entry)
    database.commit()


async def extract_from_document(
    file_bytes: bytes,
    mime_type: str,
    user_id: str,
    database: Session,
) -> ExtractionResult:
    """Extract invoice data from uploaded document.

    Strategy:
    1. If PDF: try ZUGFeRD XML extraction (free, deterministic)
    2. If no XML found or not PDF: try Vision-LLM (if configured)
    3. Return empty ExtractionResult if nothing works

    ZUGFeRD parse failures cascade to LLM path instead of returning an error.
    Standalone XML files are never sent to Vision-LLM (they can't process raw XML).
    """
    from sqlalchemy import select

    from app.config import get_settings
    from app.models.site_settings import SiteSettings

    settings = get_settings()
    site_settings = database.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()

    is_small_business = bool(site_settings.is_small_business) if site_settings else False

    pages_total = _get_pdf_page_count(file_bytes) if mime_type == "application/pdf" else None

    # ── Step 1: ZUGFeRD/CII XML extraction (free, deterministic) ──
    xml_bytes: bytes | None = None

    if mime_type == "application/pdf":
        xml_bytes = extract_zugferd_xml(file_bytes)
    elif mime_type in _XML_MIME_TYPES:
        # Standalone XML upload — detect CII/UBL root element before parsing
        xml_format = detect_xml_invoice_format(file_bytes)
        if xml_format == "cii":
            xml_bytes = file_bytes
        elif xml_format == "ubl":
            logger.info("UBL XML detected — not yet supported, returning manual")
            _log_extraction(
                database,
                user_id=user_id,
                source="zugferd",
                model=None,
                mime_type=mime_type,
                success=False,
                error_message="UBL XML format not yet supported",
            )
            return ExtractionResult(source="manual")
        else:
            logger.info("Standalone XML is not a recognized e-invoice format")
            _log_extraction(
                database,
                user_id=user_id,
                source="zugferd",
                model=None,
                mime_type=mime_type,
                success=False,
                error_message="XML is not CII or UBL e-invoice format",
            )
            return ExtractionResult(source="manual")

    if xml_bytes is not None:
        try:
            result = parse_zugferd_xml(xml_bytes)
            _log_extraction(
                database,
                user_id=user_id,
                source="zugferd",
                model=None,
                mime_type=mime_type,
                success=True,
                pages_total=pages_total,
            )
            return enrich_with_provider_detection(result, is_small_business)
        except Exception as error:
            logger.warning("ZUGFeRD XML parse failed, cascading to LLM: %s", error)
            _log_extraction(
                database,
                user_id=user_id,
                source="zugferd",
                model=None,
                mime_type=mime_type,
                success=False,
                pages_total=pages_total,
                error_message=str(error),
            )
            # Standalone XML that failed CII/UBL parsing — don't send raw XML to Vision-LLM
            if mime_type in _XML_MIME_TYPES:
                return ExtractionResult(source="manual")

    # ── Step 2: Vision-LLM extraction ──
    provider = site_settings.ai_provider if site_settings else None
    model = site_settings.ai_model if site_settings else None

    if not provider or not model:
        logger.debug("No AI provider configured in SiteSettings — returning manual")
        return ExtractionResult(source="manual")

    api_key_attr = _PROVIDER_API_KEY_ATTR.get(provider)
    if not api_key_attr:
        logger.error("Unknown AI provider in SiteSettings: %s", provider)
        return ExtractionResult(source="manual")

    api_key = getattr(settings, api_key_attr, "")
    if not api_key:
        logger.warning("AI provider %s configured but no API key set (%s)", provider, api_key_attr)
        return ExtractionResult(source="manual")

    pages_sent = min(pages_total, MAX_PAGES_FOR_LLM) if pages_total else None

    try:
        result = await call_vision_llm(file_bytes, mime_type, provider, api_key, model)
        _log_extraction(
            database,
            user_id=user_id,
            source=result.source,
            model=model,
            mime_type=mime_type,
            success=result.source != "manual",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_cents=result.cost_cents,
            pages_total=pages_total,
            pages_sent=pages_sent,
            error_message="LLM returned unparseable response" if result.source == "manual" else None,
        )
        return enrich_with_provider_detection(result, is_small_business)
    except Exception as error:
        logger.exception("Vision-LLM extraction failed")
        _log_extraction(
            database,
            user_id=user_id,
            source=provider,
            model=model,
            mime_type=mime_type,
            success=False,
            pages_total=pages_total,
            pages_sent=pages_sent,
            error_message=str(error),
        )
        return ExtractionResult(source="manual")


# ---------------------------------------------------------------------------
# 🏢 EU Service Provider Detection
# ---------------------------------------------------------------------------

# Provider registry: VAT IDs and counterparty patterns for EU service providers.
# Used for automatic Reverse Charge detection on uploaded invoices.
# Origin: §13b UStG requires German recipients to self-assess VAT on EU services.

EU_SERVICE_PROVIDERS: list[dict[str, str | list[str] | bool]] = [
    {
        "provider": "etsy",
        "name": "Etsy Ireland UC",
        "vat_id": "IE9777587C",
        "counterparty_patterns": ["etsy ireland", "etsy.com", "etsy, inc"],
        "origin": "eu",
        "is_marketplace": True,
    },
    {
        "provider": "paypal",
        "name": "PayPal (Europe)",
        "vat_id": "LU22046007",
        "counterparty_patterns": ["paypal", "paypal europe"],
        "origin": "eu",
        "is_marketplace": True,
    },
    {
        "provider": "stripe",
        "name": "Stripe Payments Europe",
        "vat_id": "IE3396855EH",
        "counterparty_patterns": ["stripe payments", "stripe, inc"],
        "origin": "eu",
        "is_marketplace": True,
    },
    {
        "provider": "amazon",
        "name": "Amazon Services Europe",
        "vat_id": "LU20260743",
        "counterparty_patterns": ["amazon services europe", "amazon.de", "amazon eu"],
        "origin": "eu",
        "is_marketplace": True,
    },
    {
        "provider": "shopify",
        "name": "Shopify International",
        "vat_id": "IE3347697KH",
        "counterparty_patterns": ["shopify international", "shopify payments"],
        "origin": "eu",
        "is_marketplace": True,
    },
    {
        "provider": "google",
        "name": "Google Ireland",
        "vat_id": "IE6388047V",
        "counterparty_patterns": ["google ireland", "google ads", "google cloud"],
        "origin": "eu",
        "is_marketplace": False,
    },
    {
        "provider": "meta",
        "name": "Meta Platforms Ireland",
        "vat_id": "IE9692928F",
        "counterparty_patterns": [
            "meta platforms ireland",
            "facebook ireland",
            "facebook ads",
            "instagram ads",
        ],
        "origin": "eu",
        "is_marketplace": False,
    },
    {
        "provider": "microsoft",
        "name": "Microsoft Ireland",
        "vat_id": "IE8256796U",
        "counterparty_patterns": ["microsoft ireland", "microsoft 365", "azure"],
        "origin": "eu",
        "is_marketplace": False,
    },
    {
        "provider": "adobe",
        "name": "Adobe Systems Ireland",
        "vat_id": "IE6364932G",
        "counterparty_patterns": ["adobe ireland", "adobe systems"],
        "origin": "eu",
        "is_marketplace": False,
    },
]


def _detect_eu_provider(result: ExtractionResult) -> dict[str, str | list[str] | bool] | None:
    """Detect EU service provider from VAT ID or counterparty name.

    Returns provider info dict if detected, None otherwise.
    Priority: VAT ID match (exact) > counterparty name match (substring).
    """
    # 1. Try VAT ID match (exact, case-insensitive)
    if result.vat_id:
        vat_id_upper = result.vat_id.upper().replace(" ", "")
        for provider in EU_SERVICE_PROVIDERS:
            if provider["vat_id"] == vat_id_upper:
                return provider

    # 2. Try counterparty name match (substring, case-insensitive)
    if result.counterparty:
        counterparty_lower = result.counterparty.lower()
        for provider in EU_SERVICE_PROVIDERS:
            patterns = provider["counterparty_patterns"]
            if isinstance(patterns, list):
                for pattern in patterns:
                    if pattern in counterparty_lower:
                        return provider

    return None


def _get_suggested_tax_rule(provider_info: dict[str, str | list[str] | bool], is_small_business: bool) -> str:
    """Determine suggested TaxRule based on provider origin and user tax status.

    Returns TaxRule enum value string for Reverse Charge.
    """
    origin = provider_info.get("origin", "eu")

    if origin == "eu":
        if is_small_business:
            return "rc_eu_no_vst"  # TaxRule.REVERSE_CHARGE_EU_NO_INPUT_TAX
        return "rc_eu_with_vst"  # TaxRule.REVERSE_CHARGE_EU_WITH_INPUT_TAX
    elif origin == "de":
        if is_small_business:
            return "rc_de_no_vst"
        return "rc_de_with_vst"
    else:  # non_eu
        if is_small_business:
            return "rc_non_eu_no_vst"
        return "rc_non_eu_with_vst"


def enrich_with_provider_detection(
    result: ExtractionResult,
    is_small_business: bool,
) -> ExtractionResult:
    """Post-process extraction result to detect EU service providers.

    If a known provider is detected (by VAT ID or counterparty name):
    - Sets detected_provider (e.g., "etsy", "paypal")
    - Sets suggested_tax_rule (RC variant based on origin + user tax status)
    - Sets is_marketplace_invoice if provider is a marketplace (enables bulk-link CTA)
    - Normalizes counterparty name if not already set

    This enables the frontend to:
    1. Pre-fill Reverse Charge tax rule on receipt creation
    2. Show "Link to fees" CTA for marketplace invoices
    3. Auto-suggest source for transaction linking
    """
    if result.source == "manual":
        return result

    provider_info = _detect_eu_provider(result)
    if provider_info is None:
        return result

    # Enrich result with provider detection
    result.detected_provider = str(provider_info["provider"])
    result.suggested_tax_rule = _get_suggested_tax_rule(provider_info, is_small_business)
    result.is_marketplace_invoice = bool(provider_info.get("is_marketplace", False))

    # Normalize counterparty if LLM extracted a variant (e.g., "ETSY IRELAND" → "Etsy Ireland UC")
    provider_name = str(provider_info["name"])
    if not result.counterparty or result.counterparty.lower() != provider_name.lower():
        result.counterparty = provider_name

    # Ensure VAT ID is set if we detected by counterparty name
    if not result.vat_id:
        result.vat_id = str(provider_info["vat_id"])

    logger.info(
        "EU provider detected: %s (tax_rule=%s, marketplace=%s)",
        result.detected_provider,
        result.suggested_tax_rule,
        result.is_marketplace_invoice,
    )

    return result
