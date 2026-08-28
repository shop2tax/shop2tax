"""Tests for ZUGFeRD/Factur-X document extraction service."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.schemas.extraction import ExtractionResult
from app.services.document_extraction import (
    EU_SERVICE_PROVIDERS,
    MAX_PAGES_FOR_LLM,
    _calculate_cost_cents,
    _detect_eu_provider,
    _get_suggested_tax_rule,
    call_anthropic_vision,
    call_gemini_vision,
    call_openai_vision,
    detect_xml_invoice_format,
    enrich_with_provider_detection,
    extract_from_document,
    extract_zugferd_xml,
    parse_zugferd_xml,
)

# ── Minimal CII XML fixture ──────────────────────────────────────────────

MINIMAL_CII_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument>
    <ram:ID>RE-2026-001</ram:ID>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20260115</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>Muster GmbH</ram:Name>
        <ram:PostalTradeAddress>
          <ram:LineOne>Musterstr. 1</ram:LineOne>
          <ram:PostcodeCode>12345</ram:PostcodeCode>
          <ram:CityName>Berlin</ram:CityName>
          <ram:CountryID>DE</ram:CountryID>
        </ram:PostalTradeAddress>
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="VA">DE123456789</ram:ID>
        </ram:SpecifiedTaxRegistration>
        <ram:SpecifiedTaxRegistration>
          <ram:ID schemeID="FC">12/345/67890</ram:ID>
        </ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery>
      <ram:ActualDeliverySupplyChainEvent>
        <ram:OccurrenceDateTime>
          <udt:DateTimeString format="102">20260110</udt:DateTimeString>
        </ram:OccurrenceDateTime>
      </ram:ActualDeliverySupplyChainEvent>
    </ram:ApplicableHeaderTradeDelivery>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:Information>Bankueberweisung</ram:Information>
        <ram:PayerPartyDebtorFinancialAccount>
          <ram:IBANID>DE89370400440532013000</ram:IBANID>
        </ram:PayerPartyDebtorFinancialAccount>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:SpecifiedTradePaymentTerms>
        <ram:DueDateDateTime>
          <udt:DateTimeString format="102">20260215</udt:DateTimeString>
        </ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>100.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount>19.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>119.00</ram:GrandTotalAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
      <ram:PaymentReference>RE-2026-001-REF</ram:PaymentReference>
    </ram:ApplicableHeaderTradeSettlement>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct>
        <ram:Name>Widget A</ram:Name>
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeDelivery>
        <ram:BilledQuantity>2</ram:BilledQuantity>
      </ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice>
          <ram:ChargeAmount>50.00</ram:ChargeAmount>
        </ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax>
          <ram:RateApplicablePercent>19.00</ram:RateApplicablePercent>
        </ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation>
          <ram:LineTotalAmount>100.00</ram:LineTotalAmount>
        </ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""


def _build_zugferd_pdf(xml_bytes: bytes) -> bytes:
    """Build a minimal PDF/A-3 with embedded XML attachment using pypdf."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_attachment("factur-x.xml", xml_bytes)
    import io

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ── Tests ─────────────────────────────────────────────────────────────────


class TestExtractZugferdXml:
    """extract_zugferd_xml: PDF attachment extraction."""

    def should_extract_xml_from_zugferd_pdf(self):
        pdf_bytes = _build_zugferd_pdf(MINIMAL_CII_XML)

        result = extract_zugferd_xml(pdf_bytes)

        assert result is not None
        assert b"CrossIndustryInvoice" in result

    def should_return_none_for_non_zugferd_pdf(self):
        """Plain PDF without XML attachment → None."""
        import io

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        buffer = io.BytesIO()
        writer.write(buffer)

        result = extract_zugferd_xml(buffer.getvalue())

        assert result is None

    def should_return_none_for_image_file(self):
        """JPEG bytes (not a PDF) → None."""
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100

        result = extract_zugferd_xml(fake_jpeg)

        assert result is None


class TestParseZugferdXml:
    """parse_zugferd_xml: CII XML → ExtractionResult."""

    def should_parse_invoice_number_from_zugferd(self):
        result = parse_zugferd_xml(MINIMAL_CII_XML)

        assert isinstance(result, ExtractionResult)
        assert result.source == "zugferd"
        assert result.receipt_number == "RE-2026-001"
        assert result.date == "2026-01-15"
        assert result.delivery_date == "2026-01-10"

    def should_parse_line_items_from_zugferd(self):
        result = parse_zugferd_xml(MINIMAL_CII_XML)

        assert len(result.line_items) == 1
        item = result.line_items[0]
        assert item.description == "Widget A"
        assert item.quantity == Decimal("2")
        assert item.unit_price == Decimal("50.00")
        assert item.amount == Decimal("100.00")
        assert item.tax_rate == Decimal("19.00")

    def should_parse_totals_from_zugferd(self):
        result = parse_zugferd_xml(MINIMAL_CII_XML)

        assert result.total_net == Decimal("100.00")
        assert result.total_tax == Decimal("19.00")
        assert result.total_gross == Decimal("119.00")
        assert result.currency == "EUR"

    def should_parse_seller_info_from_zugferd(self):
        result = parse_zugferd_xml(MINIMAL_CII_XML)

        assert result.counterparty == "Muster GmbH"
        assert result.counterparty_address == "Musterstr. 1, 12345 Berlin, DE"
        assert result.vat_id == "DE123456789"
        assert result.tax_number == "12/345/67890"

    def should_parse_payment_info_from_zugferd(self):
        result = parse_zugferd_xml(MINIMAL_CII_XML)

        assert result.payer_iban == "DE89370400440532013000"
        assert result.due_date == "2026-02-15"
        assert result.payment_method == "Bankueberweisung"
        assert result.payment_reference == "RE-2026-001-REF"


class TestDetectXmlInvoiceFormat:
    """detect_xml_invoice_format: namespace detection."""

    def should_parse_xrechnung_standalone_xml(self):
        """Standalone CII XML is detected as 'cii'."""
        assert detect_xml_invoice_format(MINIMAL_CII_XML) == "cii"

    def should_detect_ubl_xml(self):
        ubl_xml = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>UBL-001</ID>
</Invoice>
"""
        assert detect_xml_invoice_format(ubl_xml) == "ubl"

    def should_return_none_for_non_invoice_xml(self):
        random_xml = b"<root><data>hello</data></root>"

        assert detect_xml_invoice_format(random_xml) is None

    def should_return_none_for_invalid_xml(self):
        assert detect_xml_invoice_format(b"not xml at all") is None

    def should_return_none_for_image_bytes(self):
        assert detect_xml_invoice_format(b"\xff\xd8\xff\xe0\x00") is None


# ── Helpers for Vision-LLM tests ─────────────────────────────────────────

FAKE_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
FAKE_INVOICE_JSON = '{"receipt_number": "INV-001", "total_gross": "119.00", "currency": "EUR"}'


def _build_multi_page_pdf(number_of_pages: int) -> bytes:
    """Build a PDF with N blank pages."""
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(number_of_pages):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ── Vision-LLM Provider Dispatch Tests ───────────────────────────────────


class TestCallGeminiVision:
    """call_gemini_vision: Gemini SDK dispatch."""

    @pytest.mark.asyncio
    async def should_dispatch_to_gemini_when_configured(self):
        """Mock Gemini SDK → verify correct API call and result parsing."""
        fake_response = MagicMock()
        fake_response.text = FAKE_INVOICE_JSON
        fake_response.usage_metadata = SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=50,
        )

        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = fake_response

        # Gemini uses lazy `from google import genai` — patch via sys.modules
        fake_types = MagicMock()
        fake_genai = MagicMock()
        fake_genai.Client.return_value = fake_client
        fake_google = MagicMock()
        fake_google.genai = fake_genai

        with patch.dict(
            "sys.modules",
            {
                "google": fake_google,
                "google.genai": fake_genai,
                "google.genai.types": fake_types,
            },
        ):
            result = await call_gemini_vision(FAKE_IMAGE_BYTES, "image/png", "fake-api-key", "gemini-2.5-flash")

        assert result.source == "gemini"
        assert result.receipt_number == "INV-001"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        fake_client.models.generate_content.assert_called_once()


class TestCallOpenaiVision:
    """call_openai_vision: OpenAI SDK dispatch."""

    @pytest.mark.asyncio
    async def should_dispatch_to_openai_when_configured(self):
        """Mock OpenAI AsyncClient → verify correct API call and result parsing."""
        fake_usage = SimpleNamespace(prompt_tokens=200, completion_tokens=80)
        fake_message = SimpleNamespace(content=FAKE_INVOICE_JSON)
        fake_choice = SimpleNamespace(message=fake_message)
        fake_response = SimpleNamespace(choices=[fake_choice], usage=fake_usage)

        fake_client = AsyncMock()
        fake_client.chat.completions.create.return_value = fake_response

        with patch.dict("sys.modules", {"openai": MagicMock()}):
            with patch("openai.AsyncOpenAI", return_value=fake_client):
                result = await call_openai_vision(FAKE_IMAGE_BYTES, "image/png", "fake-api-key", "gpt-4o-mini")

        assert result.source == "openai"
        assert result.receipt_number == "INV-001"
        assert result.input_tokens == 200
        assert result.output_tokens == 80
        fake_client.chat.completions.create.assert_called_once()


class TestCallAnthropicVision:
    """call_anthropic_vision: Anthropic SDK dispatch."""

    @pytest.mark.asyncio
    async def should_dispatch_to_anthropic_when_configured(self):
        """Mock Anthropic AsyncClient → verify correct API call and result parsing."""
        fake_content_block = SimpleNamespace(type="text", text=FAKE_INVOICE_JSON)
        fake_usage = SimpleNamespace(input_tokens=150, output_tokens=60)
        fake_response = SimpleNamespace(
            content=[fake_content_block],
            usage=fake_usage,
        )

        fake_client = AsyncMock()
        fake_client.messages.create.return_value = fake_response

        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            with patch("anthropic.AsyncAnthropic", return_value=fake_client):
                result = await call_anthropic_vision(FAKE_IMAGE_BYTES, "image/png", "fake-api-key", "claude-haiku-4-5-20251001")

        assert result.source == "anthropic"
        assert result.receipt_number == "INV-001"
        assert result.input_tokens == 150
        assert result.output_tokens == 60
        fake_client.messages.create.assert_called_once()


# ── Skip / Fallback Tests ────────────────────────────────────────────────


class TestExtractFromDocumentSkipLlm:
    """extract_from_document: skip LLM when not configured."""

    @pytest.mark.asyncio
    async def should_skip_llm_when_no_provider_configured(self, database_session):
        """No AI provider in SiteSettings → ExtractionResult(source='manual')."""
        from app.models.site_settings import SiteSettings

        database_session.add(SiteSettings(id=1, ai_provider=None, ai_model=None))
        database_session.flush()

        result = await extract_from_document(FAKE_IMAGE_BYTES, "image/png", "test-user", database_session)

        assert result.source == "manual"

    @pytest.mark.asyncio
    async def should_skip_llm_when_no_api_key(self, database_session):
        """Provider configured but no API key in env → ExtractionResult(source='manual')."""
        from app.models.site_settings import SiteSettings

        database_session.add(SiteSettings(id=1, ai_provider="gemini", ai_model="gemini-2.5-flash"))
        database_session.flush()

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(gemini_api_key="")
            result = await extract_from_document(FAKE_IMAGE_BYTES, "image/png", "test-user", database_session)

        assert result.source == "manual"


class TestLlmJsonValidation:
    """_parse_llm_response: JSON validation."""

    def should_validate_llm_json_response(self):
        """Invalid JSON from LLM → ExtractionResult(source='manual')."""
        from app.services.document_extraction import _parse_llm_response

        result = _parse_llm_response("this is not json {{{", "gemini")

        assert result.source == "manual"

    def should_strip_markdown_fences(self):
        """JSON wrapped in markdown fences → correctly parsed."""
        from app.services.document_extraction import _parse_llm_response

        fenced = f"```json\n{FAKE_INVOICE_JSON}\n```"
        result = _parse_llm_response(fenced, "openai")

        assert result.source == "openai"
        assert result.receipt_number == "INV-001"


class TestLlmTimeout:
    """Vision-LLM timeout handling."""

    @pytest.mark.asyncio
    async def should_timeout_after_30_seconds(self):
        """httpx.TimeoutException → ExtractionResult(source='manual')."""
        fake_client = AsyncMock()
        fake_client.chat.completions.create.side_effect = httpx.TimeoutException("timed out")

        with patch.dict("sys.modules", {"openai": MagicMock()}):
            with patch("openai.AsyncOpenAI", return_value=fake_client):
                result = await call_openai_vision(FAKE_IMAGE_BYTES, "image/png", "fake-key", "gpt-4o-mini")

        assert result.source == "manual"


# ── PDF Page Limit Tests ─────────────────────────────────────────────────


class TestPdfPageLimit:
    """_truncate_pdf: limit pages sent to LLM."""

    def should_limit_pdf_to_max_pages(self):
        """PDF with >5 pages → only first 5 sent."""
        from app.services.document_extraction import _truncate_pdf
        from pypdf import PdfReader

        big_pdf = _build_multi_page_pdf(10)
        truncated = _truncate_pdf(big_pdf, max_pages=MAX_PAGES_FOR_LLM)

        import io

        reader = PdfReader(io.BytesIO(truncated))
        assert len(reader.pages) == MAX_PAGES_FOR_LLM

    def should_keep_small_pdf_unchanged(self):
        """PDF with <=5 pages → returned as-is."""
        from app.services.document_extraction import _truncate_pdf

        small_pdf = _build_multi_page_pdf(3)
        result = _truncate_pdf(small_pdf, max_pages=MAX_PAGES_FOR_LLM)

        assert result == small_pdf


# ── Logging Tests ────────────────────────────────────────────────────────


class TestExtractionLogging:
    """_log_extraction and extract_from_document: AIExtractionLog entries."""

    @pytest.mark.asyncio
    async def should_log_extraction_to_ai_extraction_log(self, database_session):
        """Successful LLM extraction → AIExtractionLog with success=True."""
        from app.models.ai_extraction_log import AIExtractionLog
        from app.models.site_settings import SiteSettings
        from sqlalchemy import select

        database_session.add(SiteSettings(id=1, ai_provider="gemini", ai_model="gemini-2.5-flash"))
        database_session.flush()

        fake_result = ExtractionResult(
            source="gemini",
            receipt_number="INV-001",
            input_tokens=100,
            output_tokens=50,
            cost_cents=0.0045,
        )

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(gemini_api_key="fake-key")
            with patch("app.services.document_extraction.call_vision_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = fake_result
                await extract_from_document(FAKE_IMAGE_BYTES, "image/png", "test-user", database_session)

        log = database_session.execute(select(AIExtractionLog)).scalar_one()
        assert log.success is True
        assert log.source == "gemini"
        assert log.model == "gemini-2.5-flash"
        assert log.input_tokens == 100
        assert log.output_tokens == 50

    @pytest.mark.asyncio
    async def should_log_failed_extraction(self, database_session):
        """LLM exception → AIExtractionLog with success=False."""
        from app.models.ai_extraction_log import AIExtractionLog
        from app.models.site_settings import SiteSettings
        from sqlalchemy import select

        database_session.add(SiteSettings(id=1, ai_provider="openai", ai_model="gpt-4o-mini"))
        database_session.flush()

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(openai_api_key="fake-key")
            with patch("app.services.document_extraction.call_vision_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = RuntimeError("API down")
                await extract_from_document(FAKE_IMAGE_BYTES, "image/png", "test-user", database_session)

        log = database_session.execute(select(AIExtractionLog)).scalar_one()
        assert log.success is False
        assert log.error_message == "API down"

    @pytest.mark.asyncio
    async def should_log_page_counts(self, database_session):
        """PDF extraction → file_pages_total and file_pages_sent logged."""
        from app.models.ai_extraction_log import AIExtractionLog
        from app.models.site_settings import SiteSettings
        from sqlalchemy import select

        database_session.add(SiteSettings(id=1, ai_provider="gemini", ai_model="gemini-2.5-flash"))
        database_session.flush()

        fake_result = ExtractionResult(source="gemini", input_tokens=100, output_tokens=50)
        pdf_bytes = _build_multi_page_pdf(8)

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(gemini_api_key="fake-key")
            with patch("app.services.document_extraction.call_vision_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = fake_result
                await extract_from_document(pdf_bytes, "application/pdf", "test-user", database_session)

        log = database_session.execute(select(AIExtractionLog)).scalar_one()
        assert log.file_pages_total == 8
        assert log.file_pages_sent == MAX_PAGES_FOR_LLM


# ── Cost Calculation Tests ───────────────────────────────────────────────


class TestCostCalculation:
    """_calculate_cost_cents: token pricing."""

    def should_calculate_cost_correctly(self):
        """Token counts × known pricing = expected cents."""
        # gemini-2.5-flash: input $0.15/1M, output $0.60/1M
        cost = _calculate_cost_cents("gemini-2.5-flash", input_tokens=1000, output_tokens=500)

        # (1000 * 0.15 + 500 * 0.60) / 1_000_000 = 0.00045 USD
        # 0.00045 * 100 = 0.045 cents
        assert cost == 0.045

    def should_log_warning_for_unknown_model_pricing(self):
        """Unknown model → cost_cents=None."""
        cost = _calculate_cost_cents("unknown-model-v99", input_tokens=1000, output_tokens=500)

        assert cost is None


# ── Cascade / XML Tests ──────────────────────────────────────────────────


class TestZugferdCascade:
    """extract_from_document: ZUGFeRD failure → LLM fallback."""

    @pytest.mark.asyncio
    async def should_cascade_zugferd_parse_failure_to_llm(self, database_session):
        """Malformed ZUGFeRD XML in PDF → falls through to LLM extraction."""
        from app.models.site_settings import SiteSettings

        database_session.add(SiteSettings(id=1, ai_provider="gemini", ai_model="gemini-2.5-flash"))
        database_session.flush()

        # Build PDF with invalid XML attachment
        malformed_xml = b"<rsm:CrossIndustryInvoice><broken>"
        pdf_bytes = _build_zugferd_pdf(malformed_xml)

        fake_result = ExtractionResult(source="gemini", receipt_number="LLM-001")

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(gemini_api_key="fake-key")
            with patch("app.services.document_extraction.call_vision_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = fake_result
                result = await extract_from_document(pdf_bytes, "application/pdf", "test-user", database_session)

        assert result.source == "gemini"
        assert result.receipt_number == "LLM-001"
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def should_not_send_xml_to_vision_llm(self, database_session):
        """Standalone XML with unknown format → empty result, no LLM call."""
        from app.models.site_settings import SiteSettings

        database_session.add(SiteSettings(id=1, ai_provider="gemini", ai_model="gemini-2.5-flash"))
        database_session.flush()

        unknown_xml = b"<root><data>not an invoice</data></root>"

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(gemini_api_key="fake-key")
            with patch("app.services.document_extraction.call_vision_llm", new_callable=AsyncMock) as mock_llm:
                result = await extract_from_document(unknown_xml, "application/xml", "test-user", database_session)

        assert result.source == "manual"
        mock_llm.assert_not_called()


# ── Rate Limit Test ──────────────────────────────────────────────────────
# Rate limiting is tested at endpoint level in test_receipts.py
# (should_enforce_global_rate_limit) because it uses slowapi decorator.


# ── EU Service Provider Detection Tests ──────────────────────────────────


class TestDetectEuProvider:
    """_detect_eu_provider: VAT ID and counterparty pattern matching."""

    def should_detect_etsy_by_vat_id(self):
        result = ExtractionResult(source="gemini", vat_id="IE9777587C")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "etsy"

    def should_detect_etsy_by_counterparty_name(self):
        result = ExtractionResult(source="gemini", counterparty="Etsy Ireland UC")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "etsy"

    def should_detect_paypal_by_vat_id(self):
        result = ExtractionResult(source="gemini", vat_id="LU22046007")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "paypal"

    def should_detect_google_by_counterparty_name(self):
        result = ExtractionResult(source="gemini", counterparty="Google Ireland Ltd.")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "google"

    def should_detect_meta_by_facebook_counterparty(self):
        result = ExtractionResult(source="gemini", counterparty="Facebook Ireland Ltd")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "meta"

    def should_return_none_for_unknown_provider(self):
        result = ExtractionResult(source="gemini", counterparty="Random GmbH", vat_id="DE123456789")

        provider = _detect_eu_provider(result)

        assert provider is None

    def should_prefer_vat_id_over_counterparty(self):
        """VAT ID match takes priority over counterparty name."""
        result = ExtractionResult(source="gemini", counterparty="Some PayPal Thing", vat_id="IE9777587C")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "etsy"  # VAT ID wins

    def should_handle_case_insensitive_vat_id(self):
        result = ExtractionResult(source="gemini", vat_id="ie9777587c")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "etsy"

    def should_handle_vat_id_with_spaces(self):
        result = ExtractionResult(source="gemini", vat_id="IE 9777587C")

        provider = _detect_eu_provider(result)

        assert provider is not None
        assert provider["provider"] == "etsy"


class TestGetSuggestedTaxRule:
    """_get_suggested_tax_rule: RC tax rule based on origin + business status."""

    def should_return_rc_eu_no_vst_for_small_business(self):
        provider = {"origin": "eu"}

        rule = _get_suggested_tax_rule(provider, is_small_business=True)

        assert rule == "rc_eu_no_vst"

    def should_return_rc_eu_with_vst_for_regular_business(self):
        provider = {"origin": "eu"}

        rule = _get_suggested_tax_rule(provider, is_small_business=False)

        assert rule == "rc_eu_with_vst"

    def should_return_rc_non_eu_for_non_eu_provider(self):
        provider = {"origin": "non_eu"}

        rule = _get_suggested_tax_rule(provider, is_small_business=True)

        assert rule == "rc_non_eu_no_vst"


class TestEnrichWithProviderDetection:
    """enrich_with_provider_detection: full enrichment pipeline."""

    def should_enrich_etsy_invoice_for_small_business(self):
        result = ExtractionResult(
            source="gemini",
            counterparty="ETSY IRELAND",
            total_gross=Decimal("241.66"),
        )

        enriched = enrich_with_provider_detection(result, is_small_business=True)

        assert enriched.detected_provider == "etsy"
        assert enriched.suggested_tax_rule == "rc_eu_no_vst"
        assert enriched.is_marketplace_invoice is True
        assert enriched.counterparty == "Etsy Ireland UC"  # normalized
        assert enriched.vat_id == "IE9777587C"  # filled in

    def should_enrich_etsy_invoice_for_regular_business(self):
        result = ExtractionResult(
            source="gemini",
            vat_id="IE9777587C",
            counterparty="Etsy Ireland UC",
        )

        enriched = enrich_with_provider_detection(result, is_small_business=False)

        assert enriched.detected_provider == "etsy"
        assert enriched.suggested_tax_rule == "rc_eu_with_vst"
        assert enriched.is_marketplace_invoice is True

    def should_enrich_google_as_non_marketplace(self):
        result = ExtractionResult(source="gemini", counterparty="Google Ireland Ltd.")

        enriched = enrich_with_provider_detection(result, is_small_business=True)

        assert enriched.detected_provider == "google"
        assert enriched.is_marketplace_invoice is False
        assert enriched.suggested_tax_rule == "rc_eu_no_vst"

    def should_not_enrich_manual_source(self):
        result = ExtractionResult(source="manual", counterparty="Etsy Ireland UC")

        enriched = enrich_with_provider_detection(result, is_small_business=True)

        assert enriched.detected_provider is None
        assert enriched.suggested_tax_rule is None
        assert enriched.is_marketplace_invoice is False

    def should_not_enrich_unknown_provider(self):
        result = ExtractionResult(source="gemini", counterparty="Random Shop GmbH")

        enriched = enrich_with_provider_detection(result, is_small_business=True)

        assert enriched.detected_provider is None
        assert enriched.suggested_tax_rule is None

    def should_preserve_existing_vat_id(self):
        """If LLM already extracted VAT ID, don't overwrite it."""
        result = ExtractionResult(
            source="gemini",
            counterparty="Etsy Ireland UC",
            vat_id="IE9777587C",  # already extracted
        )

        enriched = enrich_with_provider_detection(result, is_small_business=True)

        assert enriched.vat_id == "IE9777587C"


class TestProviderRegistryCompleteness:
    """Verify EU_SERVICE_PROVIDERS registry has required fields."""

    def should_have_all_required_fields(self):
        required_fields = {"provider", "name", "vat_id", "counterparty_patterns", "origin", "is_marketplace"}

        for entry in EU_SERVICE_PROVIDERS:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Provider {entry.get('provider', '?')} missing fields: {missing}"

    def should_have_unique_vat_ids(self):
        vat_ids = [entry["vat_id"] for entry in EU_SERVICE_PROVIDERS]

        assert len(vat_ids) == len(set(vat_ids)), "Duplicate VAT IDs in provider registry"

    def should_have_unique_provider_names(self):
        providers = [entry["provider"] for entry in EU_SERVICE_PROVIDERS]

        assert len(providers) == len(set(providers)), "Duplicate provider names in registry"


class TestExtractFromDocumentWithProviderDetection:
    """extract_from_document: integration with provider detection."""

    @pytest.mark.asyncio
    async def should_enrich_llm_result_with_provider_detection(self, database_session):
        """LLM extracts Etsy invoice → enriched with RC tax rule."""
        from app.models.site_settings import SiteSettings

        database_session.add(SiteSettings(id=1, ai_provider="gemini", ai_model="gemini-2.5-flash", is_small_business=True))
        database_session.flush()

        fake_result = ExtractionResult(
            source="gemini",
            counterparty="Etsy Ireland UC",
            vat_id="IE9777587C",
            total_gross=Decimal("241.66"),
            input_tokens=100,
            output_tokens=50,
        )

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(gemini_api_key="fake-key")
            with patch("app.services.document_extraction.call_vision_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = fake_result
                result = await extract_from_document(FAKE_IMAGE_BYTES, "image/png", "test-user", database_session)

        assert result.detected_provider == "etsy"
        assert result.suggested_tax_rule == "rc_eu_no_vst"
        assert result.is_marketplace_invoice is True

    @pytest.mark.asyncio
    async def should_not_enrich_non_provider_invoice(self, database_session):
        """LLM extracts regular invoice → no provider detection."""
        from app.models.site_settings import SiteSettings

        database_session.add(SiteSettings(id=1, ai_provider="gemini", ai_model="gemini-2.5-flash", is_small_business=True))
        database_session.flush()

        fake_result = ExtractionResult(
            source="gemini",
            counterparty="Bürobedarf Schmidt GmbH",
            vat_id="DE987654321",
            input_tokens=100,
            output_tokens=50,
        )

        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(gemini_api_key="fake-key")
            with patch("app.services.document_extraction.call_vision_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = fake_result
                result = await extract_from_document(FAKE_IMAGE_BYTES, "image/png", "test-user", database_session)

        assert result.detected_provider is None
        assert result.suggested_tax_rule is None
        assert result.is_marketplace_invoice is False
