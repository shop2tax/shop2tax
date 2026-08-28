"""Tests for the provider-agnostic OMS receipt sync service."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models.oms_provider import OmsProviderType
from app.models.receipt import Receipt
from app.models.receipt_line_item import ReceiptLineItem, TaxRule
from app.models.site_settings import SiteSettings
from app.services.oms_provider import EnrichmentResult, OmsOrder, OmsOrderItem
from app.services.oms_sync import (
    SyncAlreadyInProgressError,
    TaxSettingNotConfiguredError,
    _sync_lock,
    sync_receipts_from_oms,
)
from app.services.receipt_service import (
    SKR03_KLEINUNTERNEHMER,
    SKR03_REVENUE_7,
    SKR03_REVENUE_19,
    determine_line_item_accounting,
)
from sqlalchemy import select


def _example_oms_order(
    order_id: int,
    order_number: str | None = None,
    invoice_number: str | None = None,
    state: int = 4,
    tags: list[str] | None = None,
) -> OmsOrder:
    """Create a minimal OmsOrder for sync tests."""
    return OmsOrder(
        order_id=str(order_id),
        order_number=order_number or f"ORD-{order_id}",
        invoice_number=invoice_number or f"INV-{order_id}",
        invoice_number_prefix="",
        state=state,
        created_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
        total_cost=Decimal("10.00"),
        currency="EUR",
        customer_name="Test Customer",
        customer_email="test@example.com",
        shop_id=100,
        shop_name="Test Shop",
        platform="etsy",
        items=[
            OmsOrderItem(
                product_title=f"Item {order_id}",
                quantity=1,
                total_price=Decimal("10.00"),
                sku=None,
                tax_index=1,
                tax_amount=Decimal("1.60"),
            )
        ],
        tags=tags or [],
        paid_amount=Decimal("10.00"),
        is_paid=True,
        paid_at=datetime(2026, 3, 1, tzinfo=UTC).date(),
        tax_rate_1=Decimal("19"),
        tax_rate_2=Decimal("7"),
    )


class FakeOmsProvider:
    """In-memory OmsProvider fake for sync tests.

    Returns provided OmsOrders; PDF fetch returns (pdf_bytes, error) per configuration.
    Captures label-setting calls.
    """

    def __init__(
        self,
        orders: list[OmsOrder] | None = None,
        pdf_result: tuple[bytes | None, str | None] = (None, None),
        pdf_results_by_order: dict[str, tuple[bytes | None, str | None]] | None = None,
        order_fetch_delay: float = 0.0,
        display_name: str = "Billbee",
    ) -> None:
        self._orders = orders or []
        self._pdf_result = pdf_result
        self._pdf_results_by_order = pdf_results_by_order or {}
        self._order_fetch_delay = order_fetch_delay
        self._display_name = display_name
        self.fetch_orders_calls: list[dict] = []
        self.label_calls: list[tuple[list[str], str]] = []

    @property
    def provider_type(self) -> OmsProviderType:
        return OmsProviderType.BILLBEE

    @property
    def display_name(self) -> str:
        return self._display_name

    async def fetch_orders(self, store_ids=None, min_date=None, max_date=None) -> list[OmsOrder]:
        self.fetch_orders_calls.append({"store_ids": store_ids, "min_date": min_date, "max_date": max_date})
        if self._order_fetch_delay > 0:
            await asyncio.sleep(self._order_fetch_delay)
        return self._orders

    async def fetch_orders_cached(self, store_ids=None, min_date=None, max_date=None, force_refresh=False):
        orders = await self.fetch_orders(store_ids=store_ids, min_date=min_date, max_date=max_date)
        return orders, False, None

    async def fetch_order_by_id(self, order_id: str) -> OmsOrder | None:
        for order in self._orders:
            if order.order_id == order_id:
                return order
        return None

    async def fetch_invoice_pdf(self, order_id: str) -> tuple[bytes | None, str | None]:
        if order_id in self._pdf_results_by_order:
            return self._pdf_results_by_order[order_id]
        return self._pdf_result

    async def set_labels(self, order_ids: list[str], label: str) -> tuple[int, list[str]]:
        self.label_calls.append((order_ids, label))
        return len(order_ids), []

    def enrich_transaction(self, order: OmsOrder) -> EnrichmentResult:
        invoice_number = None
        if order.invoice_number:
            invoice_number = f"{order.invoice_number_prefix or ''}{order.invoice_number}"
        return EnrichmentResult(
            oms_order_id=order.order_id,
            invoice_number=invoice_number,
            shop_name=order.shop_name,
            platform=order.platform,
            customer_name=order.customer_name,
            order_date=order.paid_at,
        )


@pytest.fixture
def site_settings_configured(seeded_session, example_user):
    """Session with SiteSettings.is_small_business configured (Regelbesteuert)."""
    settings = seeded_session.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
    if settings is None:
        settings = SiteSettings(id=1)
        seeded_session.add(settings)
    settings.is_small_business = False
    seeded_session.commit()
    return seeded_session


@pytest.fixture
def site_settings_small_business(seeded_session, example_user):
    """Session with SiteSettings.is_small_business = True (Kleinunternehmer)."""
    settings = seeded_session.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
    if settings is None:
        settings = SiteSettings(id=1)
        seeded_session.add(settings)
    settings.is_small_business = True
    seeded_session.commit()
    return seeded_session


class TestDetermineLineItemAccounting:
    """Tests for determine_line_item_accounting() helper function."""

    def should_return_8195_for_small_business(self, seeded_session):
        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=True,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=1,
            database=seeded_session,
        )

        assert skr03_id == SKR03_KLEINUNTERNEHMER  # 8195
        assert tax_rule == TaxRule.NO_TAX
        assert tax_rate == Decimal("0")

    def should_return_8400_for_19_percent(self, seeded_session):
        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=1,
            database=seeded_session,
        )

        assert skr03_id == SKR03_REVENUE_19  # 8400
        assert tax_rule == TaxRule.TAX_INCLUDED
        assert tax_rate == Decimal("19")

    def should_return_8300_for_7_percent(self, seeded_session):
        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=2,
            database=seeded_session,
        )

        assert skr03_id == SKR03_REVENUE_7  # 8300
        assert tax_rule == TaxRule.TAX_INCLUDED
        assert tax_rate == Decimal("7")

    def should_use_default_rates_when_none(self, seeded_session):
        _, _, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=None,
            tax_rate_2=None,
            tax_index=1,
            database=seeded_session,
        )
        assert tax_rate == Decimal("19")

        _, _, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=None,
            tax_rate_2=None,
            tax_index=2,
            database=seeded_session,
        )
        assert tax_rate == Decimal("7")

    def should_ignore_tax_for_small_business(self, seeded_session):
        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=True,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=2,
            database=seeded_session,
        )

        assert skr03_id == SKR03_KLEINUNTERNEHMER
        assert tax_rule == TaxRule.NO_TAX
        assert tax_rate == Decimal("0")


class TestReceiptCreation:
    """Tests for receipt creation via create_revenue_receipt()."""

    def should_create_line_items_per_order_item(self, site_settings_configured, example_user):
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            create_revenue_receipt,
        )

        session = site_settings_configured

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12345",
            receipt_number="INV-001",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test Customer",
            description="Test Order",
            line_items=[
                ReceiptLineItemInput(
                    description="Product A",
                    amount=Decimal("100.00"),
                    skr03_account_id=SKR03_REVENUE_19,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("19"),
                ),
                ReceiptLineItemInput(
                    description="Product B",
                    amount=Decimal("50.00"),
                    skr03_account_id=SKR03_REVENUE_7,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("7"),
                ),
            ],
        )
        session.commit()

        line_items = (
            session.execute(select(ReceiptLineItem).where(ReceiptLineItem.receipt_id == receipt.id).order_by(ReceiptLineItem.position))
            .scalars()
            .all()
        )

        assert len(line_items) == 2
        assert line_items[0].description == "Product A"
        assert line_items[0].amount == Decimal("100.00")
        assert line_items[0].skr03_account_id == SKR03_REVENUE_19
        assert line_items[1].description == "Product B"
        assert line_items[1].amount == Decimal("50.00")
        assert line_items[1].skr03_account_id == SKR03_REVENUE_7

    def should_allow_negative_line_item_amounts(self, site_settings_configured, example_user):
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            create_revenue_receipt,
        )

        session = site_settings_configured

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12346",
            receipt_number="INV-002",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test Customer",
            description="Order with discount",
            line_items=[
                ReceiptLineItemInput(
                    description="Widget",
                    amount=Decimal("100.00"),
                    skr03_account_id=SKR03_REVENUE_19,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("19"),
                ),
                ReceiptLineItemInput(
                    description="Rabatt",
                    amount=Decimal("-10.00"),
                    skr03_account_id=SKR03_REVENUE_19,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("19"),
                ),
            ],
        )
        session.commit()

        line_items = (
            session.execute(select(ReceiptLineItem).where(ReceiptLineItem.receipt_id == receipt.id).order_by(ReceiptLineItem.position))
            .scalars()
            .all()
        )

        assert len(line_items) == 2
        assert line_items[1].description == "Rabatt"
        assert line_items[1].amount == Decimal("-10.00")

    def should_assign_skr03_8195_for_small_business(self, site_settings_small_business, example_user):
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            create_revenue_receipt,
        )

        session = site_settings_small_business

        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=True,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=1,
            database=session,
        )

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12347",
            receipt_number="INV-003",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test Customer",
            description="Kleinunternehmer Order",
            line_items=[
                ReceiptLineItemInput(
                    description="Product",
                    amount=Decimal("100.00"),
                    skr03_account_id=skr03_id,
                    tax_rule=tax_rule,
                    tax_rate=tax_rate,
                ),
            ],
        )
        session.commit()

        line_item = session.execute(select(ReceiptLineItem).where(ReceiptLineItem.receipt_id == receipt.id)).scalar_one()
        assert line_item.skr03_account_id == SKR03_KLEINUNTERNEHMER

    def should_set_tax_rule_no_tax_for_small_business(self, site_settings_small_business, example_user):
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            create_revenue_receipt,
        )

        session = site_settings_small_business

        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=True,
            tax_rate_1=None,
            tax_rate_2=None,
            tax_index=1,
            database=session,
        )

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12348",
            receipt_number="INV-004",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test",
            description="Test",
            line_items=[
                ReceiptLineItemInput(
                    description="Item",
                    amount=Decimal("50.00"),
                    skr03_account_id=skr03_id,
                    tax_rule=tax_rule,
                    tax_rate=tax_rate,
                ),
            ],
        )
        session.commit()

        line_item = session.execute(select(ReceiptLineItem).where(ReceiptLineItem.receipt_id == receipt.id)).scalar_one()
        assert line_item.tax_rule == TaxRule.NO_TAX
        assert line_item.tax_rate == Decimal("0")

    def should_set_tax_rule_tax_included_for_regular(self, site_settings_configured, example_user):
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            create_revenue_receipt,
        )

        session = site_settings_configured

        skr03_id, tax_rule, tax_rate = determine_line_item_accounting(
            is_small_business=False,
            tax_rate_1=Decimal("19"),
            tax_rate_2=Decimal("7"),
            tax_index=1,
            database=session,
        )

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12349",
            receipt_number="INV-005",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test",
            description="Test",
            line_items=[
                ReceiptLineItemInput(
                    description="Item",
                    amount=Decimal("119.00"),
                    skr03_account_id=skr03_id,
                    tax_rule=tax_rule,
                    tax_rate=tax_rate,
                ),
            ],
        )
        session.commit()

        line_item = session.execute(select(ReceiptLineItem).where(ReceiptLineItem.receipt_id == receipt.id)).scalar_one()
        assert line_item.tax_rule == TaxRule.TAX_INCLUDED
        assert line_item.tax_rate == Decimal("19")


class TestFileStorage:
    """Tests for file storage in receipt creation."""

    def should_store_pdf_metadata(self, site_settings_configured, example_user):
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            StoredFileMetadata,
            create_revenue_receipt,
        )

        session = site_settings_configured

        file_metadata = StoredFileMetadata(
            file_hash="abc123def456",
            file_storage_id="users/test-user/receipts/invoice_123.pdf",
            file_mime_type="application/pdf",
            file_original_name="invoice_123.pdf",
        )

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12350",
            receipt_number="INV-006",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test",
            description="With PDF",
            line_items=[
                ReceiptLineItemInput(
                    description="Item",
                    amount=Decimal("100.00"),
                    skr03_account_id=SKR03_REVENUE_19,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("19"),
                ),
            ],
            file_metadata=file_metadata,
        )
        session.commit()

        assert receipt.file_hash == "abc123def456"
        assert receipt.file_storage_id == "users/test-user/receipts/invoice_123.pdf"
        assert receipt.file_mime_type == "application/pdf"
        assert receipt.file_original_name == "invoice_123.pdf"

    def should_create_receipt_without_pdf(self, site_settings_configured, example_user):
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            create_revenue_receipt,
        )

        session = site_settings_configured

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12351",
            receipt_number="INV-007",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test",
            description="No PDF",
            line_items=[
                ReceiptLineItemInput(
                    description="Item",
                    amount=Decimal("50.00"),
                    skr03_account_id=SKR03_REVENUE_19,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("19"),
                ),
            ],
            file_metadata=None,
        )
        session.commit()

        assert receipt.id is not None
        assert receipt.file_hash is None
        assert receipt.file_storage_id is None


class TestAuditLogging:
    """Tests for audit log creation."""

    def should_create_file_uploaded_audit_log(self, site_settings_configured, example_user):
        from app.models.receipt_audit_log import ReceiptAuditAction, ReceiptAuditLog
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            StoredFileMetadata,
            create_revenue_receipt,
        )

        session = site_settings_configured

        file_metadata = StoredFileMetadata(
            file_hash="test-hash",
            file_storage_id="test-storage-id",
            file_mime_type="application/pdf",
            file_original_name="test.pdf",
        )

        receipt = create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="12352",
            receipt_number="INV-008",
            receipt_date=datetime(2026, 2, 15).date(),
            counterparty="Test",
            description="Test",
            line_items=[
                ReceiptLineItemInput(
                    description="Item",
                    amount=Decimal("100.00"),
                    skr03_account_id=SKR03_REVENUE_19,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("19"),
                ),
            ],
            file_metadata=file_metadata,
        )
        session.commit()

        audit_logs = (
            session.execute(select(ReceiptAuditLog).where(ReceiptAuditLog.receipt_id == receipt.id).order_by(ReceiptAuditLog.created_at))
            .scalars()
            .all()
        )

        actions = [log.action for log in audit_logs]
        assert ReceiptAuditAction.CREATED in actions
        assert ReceiptAuditAction.FILE_UPLOADED in actions

        file_uploaded_log = next(log for log in audit_logs if log.action == ReceiptAuditAction.FILE_UPLOADED)
        assert file_uploaded_log.details["file_hash"] == "test-hash"
        assert file_uploaded_log.details["object_name"] == "test-storage-id"


# --- Sync Orchestration Tests ---


class TestSyncPreconditions:
    """Tests for sync precondition checks."""

    @pytest.mark.anyio
    async def should_refuse_sync_without_tax_settings(self, seeded_session, example_user, oms_provider_record):
        """Sync should raise error if is_small_business not configured."""
        settings = seeded_session.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one_or_none()
        if settings is None:
            settings = SiteSettings(id=1)
            seeded_session.add(settings)
        settings.is_small_business = None
        seeded_session.commit()

        provider = FakeOmsProvider(orders=[])
        with pytest.raises(TaxSettingNotConfiguredError) as exc_info:
            await sync_receipts_from_oms(
                provider=provider,
                provider_id=oms_provider_record.id,
                database=seeded_session,
                user_id=example_user.id,
            )

        assert "Umsatzsteuer-Einstellung" in str(exc_info.value)


class TestSyncFiltering:
    """Tests for order filtering during sync."""

    @pytest.mark.anyio
    async def should_create_receipt_from_order(self, site_settings_configured, example_user, oms_provider_record):
        """A valid order should produce a receipt with the order's data."""
        session = site_settings_configured
        provider = FakeOmsProvider(orders=[_example_oms_order(7001)])

        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.imported_count == 1
        receipt = session.execute(select(Receipt).where(Receipt.oms_order_id == "7001")).scalar_one()
        assert receipt.oms_provider_id == oms_provider_record.id
        assert receipt.oms_shop_name == "Test Shop"
        assert receipt.oms_platform == "etsy"
        assert receipt.counterparty == "Test Customer"

    @pytest.mark.anyio
    async def should_skip_orders_with_sync_label(self, site_settings_configured, example_user, oms_provider_record):
        session = site_settings_configured
        provider = FakeOmsProvider(orders=[_example_oms_order(7002, tags=["shop2tax"])])

        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.imported_count == 0
        assert result.skipped_count == 1

    @pytest.mark.anyio
    async def should_skip_orders_below_state_3(self, site_settings_configured, example_user, oms_provider_record):
        session = site_settings_configured
        provider = FakeOmsProvider(orders=[_example_oms_order(7003, state=2)])

        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.imported_count == 0
        assert result.skipped_count == 1

    @pytest.mark.anyio
    async def should_skip_orders_without_invoice_number(self, site_settings_configured, example_user, oms_provider_record):
        session = site_settings_configured
        order = _example_oms_order(7004)
        order_no_invoice = OmsOrder(**{**order.__dict__, "invoice_number": None})
        provider = FakeOmsProvider(orders=[order_no_invoice])

        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.imported_count == 0
        assert result.skipped_count == 1


class TestSyncDeduplication:
    """Tests for duplicate handling during sync."""

    @pytest.mark.anyio
    async def should_skip_duplicate_oms_order(self, site_settings_configured, example_user, oms_provider_record):
        """An order already imported should be skipped (DuplicateOmsReceiptError)."""
        from app.services.receipt_service import (
            ReceiptLineItemInput,
            create_revenue_receipt,
        )

        session = site_settings_configured

        # Pre-create a receipt with the same OMS order ID
        create_revenue_receipt(
            database=session,
            user_id=example_user.id,
            oms_order_id="7005",
            receipt_number="INV-EXISTING",
            receipt_date=datetime(2026, 2, 1).date(),
            counterparty="Existing",
            description="Existing",
            line_items=[
                ReceiptLineItemInput(
                    description="Item",
                    amount=Decimal("10.00"),
                    skr03_account_id=SKR03_REVENUE_19,
                    tax_rule=TaxRule.TAX_INCLUDED,
                    tax_rate=Decimal("19"),
                ),
            ],
        )
        session.commit()

        provider = FakeOmsProvider(orders=[_example_oms_order(7005)])
        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.imported_count == 0
        assert result.skipped_count == 1


class TestSyncPdfHandling:
    """Tests for PDF fetch/storage handling during sync."""

    @pytest.mark.anyio
    async def should_report_pdf_error_but_still_create_receipt(self, site_settings_configured, example_user, oms_provider_record):
        """PDF error → error in SyncResult, receipt still created without PDF."""
        session = site_settings_configured
        provider = FakeOmsProvider(
            orders=[_example_oms_order(9001)],
            pdf_result=(None, "PDF fetch failed: ConnectError"),
        )

        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.pdf_error_count == 1
        assert len(result.errors) >= 1
        assert any("ConnectError" in error for error in result.errors)
        assert result.imported_count == 1

        receipt = session.execute(select(Receipt).where(Receipt.oms_order_id == "9001")).scalar_one()
        assert receipt.file_hash is None

    @pytest.mark.anyio
    async def should_attach_pdf_when_available(self, site_settings_configured, example_user, oms_provider_record, monkeypatch):
        """When the provider returns PDF bytes, the receipt should get file metadata."""
        from app.services import oms_sync

        session = site_settings_configured

        def fake_store_file(pdf_bytes, file_name):
            return ("file-hash", "storage-id", "application/pdf")

        monkeypatch.setattr(oms_sync, "store_file", fake_store_file)

        provider = FakeOmsProvider(
            orders=[_example_oms_order(9003)],
            pdf_result=(b"%PDF-fake-content", None),
        )

        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.imported_count == 1
        assert result.pdf_count == 1
        receipt = session.execute(select(Receipt).where(Receipt.oms_order_id == "9003")).scalar_one()
        assert receipt.file_hash == "file-hash"


class TestSyncLabelSetting:
    """Tests for the oms_sync_set_labels setting."""

    @pytest.mark.anyio
    async def should_set_labels_when_enabled(self, site_settings_configured, example_user, oms_provider_record):
        session = site_settings_configured
        settings = session.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one()
        settings.oms_sync_set_labels = True
        session.commit()

        provider = FakeOmsProvider(orders=[_example_oms_order(8001)])
        await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert len(provider.label_calls) == 1
        order_ids, label = provider.label_calls[0]
        assert order_ids == ["8001"]
        assert label == "shop2tax"

    @pytest.mark.anyio
    async def should_skip_labels_when_setting_disabled(self, site_settings_configured, example_user, oms_provider_record):
        """When oms_sync_set_labels is False, no label call should be made."""
        session = site_settings_configured
        settings = session.execute(select(SiteSettings).where(SiteSettings.id == 1)).scalar_one()
        settings.oms_sync_set_labels = False
        session.commit()

        provider = FakeOmsProvider(orders=[_example_oms_order(8002)])
        await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert len(provider.label_calls) == 0


class TestSyncOrchestration:
    """Tests for sync orchestration behavior."""

    @pytest.mark.anyio
    async def should_pass_date_range_to_fetch_orders(self, site_settings_configured, example_user, oms_provider_record):
        """min/max order dates must be forwarded to the provider's fetch_orders."""
        session = site_settings_configured
        provider = FakeOmsProvider(orders=[])

        min_date = datetime(2026, 3, 1, tzinfo=UTC)
        max_date = datetime(2026, 3, 15, tzinfo=UTC)

        await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
            min_order_date=min_date,
            max_order_date=max_date,
        )

        assert len(provider.fetch_orders_calls) == 1
        assert provider.fetch_orders_calls[0]["min_date"] == min_date
        assert provider.fetch_orders_calls[0]["max_date"] == max_date

    @pytest.mark.anyio
    async def should_process_zero_orders_without_error(self, site_settings_configured, example_user, oms_provider_record):
        session = site_settings_configured
        provider = FakeOmsProvider(orders=[])

        result = await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
        )

        assert result.imported_count == 0
        assert result.skipped_count == 0
        assert result.errors == []

    @pytest.mark.anyio
    async def should_report_progress_per_chunk(self, site_settings_configured, example_user, oms_provider_record):
        """75 orders → 2 chunks (50 + 25)."""
        session = site_settings_configured
        provider = FakeOmsProvider(orders=[_example_oms_order(i) for i in range(1, 76)])

        progress_events: list[dict] = []
        await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
            progress_callback=lambda event: progress_events.append(event),
        )

        assert len(progress_events) == 2
        assert progress_events[0]["processed"] == 50
        assert progress_events[0]["total"] == 75
        assert progress_events[1]["processed"] == 75
        assert progress_events[1]["total"] == 75

    @pytest.mark.anyio
    async def should_process_exactly_chunk_size_orders(self, site_settings_configured, example_user, oms_provider_record):
        """50 orders should result in exactly 1 chunk (no off-by-one)."""
        session = site_settings_configured
        provider = FakeOmsProvider(orders=[_example_oms_order(i) for i in range(1, 51)])

        progress_events: list[dict] = []
        await sync_receipts_from_oms(
            provider=provider,
            provider_id=oms_provider_record.id,
            database=session,
            user_id=example_user.id,
            progress_callback=lambda event: progress_events.append(event),
        )

        assert len(progress_events) == 1
        assert progress_events[0]["processed"] == 50
        assert progress_events[0]["total"] == 50


class TestConcurrentSyncPrevention:
    """Tests for concurrent sync prevention."""

    @pytest.mark.anyio
    async def should_reject_concurrent_sync_requests(self, site_settings_configured, example_user, oms_provider_record):
        """Second sync call while first runs should raise SyncAlreadyInProgressError."""
        session = site_settings_configured

        if _sync_lock.locked():
            _sync_lock.release()

        slow_provider = FakeOmsProvider(orders=[], order_fetch_delay=0.5)
        fast_provider = FakeOmsProvider(orders=[])

        first_sync = asyncio.create_task(
            sync_receipts_from_oms(
                provider=slow_provider,
                provider_id=oms_provider_record.id,
                database=session,
                user_id=example_user.id,
            )
        )

        await asyncio.sleep(0.01)

        with pytest.raises(SyncAlreadyInProgressError):
            await sync_receipts_from_oms(
                provider=fast_provider,
                provider_id=oms_provider_record.id,
                database=session,
                user_id=example_user.id,
            )

        await first_sync
