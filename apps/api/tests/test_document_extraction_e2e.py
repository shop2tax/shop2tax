"""E2E integration tests for document extraction pipeline.

Tests the full flow through the /extract endpoint: upload → detect → parse → ExtractionResult.
LLM providers are mocked at SDK level (no real API calls).
"""

from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from app.models.ai_extraction_log import AIExtractionLog
from app.schemas.extraction import ExtractionResult

from tests.test_document_extraction import MINIMAL_CII_XML, _build_zugferd_pdf

AUTH_HEADERS = {"X-User-Id": "test-user-id", "X-User-Email": "test@example.com", "X-User-Name": "Test User"}


def _make_plain_pdf() -> bytes:
    """Create a minimal PDF without ZUGFeRD attachment."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ── E2E Pipeline Tests ──────────────────────────────────────────────────


class TestExtractionPipelineE2E:
    """Full pipeline: upload file → detect format → extract → return ExtractionResult."""

    def should_extract_zugferd_and_prefill_all_fields(self, api_client):
        """ZUGFeRD PDF → parse XML → ExtractionResult with all fields populated."""
        zugferd_pdf = _build_zugferd_pdf(MINIMAL_CII_XML)

        response = api_client.post(
            "/api/v1/receipts/extract",
            files={"file": ("invoice.pdf", BytesIO(zugferd_pdf), "application/pdf")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        result = response.json()
        assert result["source"] == "zugferd"
        assert result["receipt_number"] == "RE-2026-001"
        assert result["date"] == "2026-01-15"
        assert result["delivery_date"] == "2026-01-10"
        assert result["due_date"] == "2026-02-15"
        assert result["counterparty"] == "Muster GmbH"
        assert result["vat_id"] == "DE123456789"
        assert result["currency"] == "EUR"
        assert result["total_net"] == "100.00"
        assert result["total_tax"] == "19.00"
        assert result["total_gross"] == "119.00"
        assert result["payment_reference"] == "RE-2026-001-REF"
        # Line items
        assert len(result["line_items"]) == 1
        assert result["line_items"][0]["description"] == "Widget A"
        assert result["line_items"][0]["quantity"] == "2"
        # No LLM cost for ZUGFeRD
        assert result["cost_cents"] is None
        assert result["input_tokens"] is None

    @patch("app.routers.receipts.extract_from_document", new_callable=AsyncMock)
    def should_fallback_to_llm_when_no_zugferd(self, mock_extract, api_client):
        """Normal PDF (no ZUGFeRD XML) → LLM dispatch → ExtractionResult."""
        plain_pdf = _make_plain_pdf()

        mock_extract.return_value = ExtractionResult(
            source="gemini",
            receipt_number="INV-999",
            counterparty="Test Corp",
            currency="EUR",
            input_tokens=100,
            output_tokens=50,
            cost_cents=0.02,
        )

        response = api_client.post(
            "/api/v1/receipts/extract",
            files={"file": ("invoice.pdf", BytesIO(plain_pdf), "application/pdf")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        result = response.json()
        assert result["source"] == "gemini"
        assert result["receipt_number"] == "INV-999"
        assert result["counterparty"] == "Test Corp"
        assert result["cost_cents"] == pytest.approx(0.02)
        mock_extract.assert_called_once()

    @patch("app.services.document_extraction.call_vision_llm")
    def should_cascade_zugferd_then_skip_llm(self, mock_llm, api_client):
        """ZUGFeRD PDF → successful parse → LLM never called."""
        zugferd_pdf = _build_zugferd_pdf(MINIMAL_CII_XML)

        response = api_client.post(
            "/api/v1/receipts/extract",
            files={"file": ("invoice.pdf", BytesIO(zugferd_pdf), "application/pdf")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["source"] == "zugferd"
        mock_llm.assert_not_called()

    def should_handle_xml_upload_as_xrechnung(self, api_client):
        """Standalone XML file → parse as XRechnung/CII → ExtractionResult."""
        response = api_client.post(
            "/api/v1/receipts/extract",
            files={"file": ("invoice.xml", BytesIO(MINIMAL_CII_XML), "application/xml")},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        result = response.json()
        assert result["source"] == "zugferd"
        assert result["receipt_number"] == "RE-2026-001"
        assert result["counterparty"] == "Muster GmbH"

    def should_track_costs_across_multiple_extractions(self, api_client, database_session):
        """Multiple extractions → dashboard endpoint shows correct aggregation."""
        # Directly insert extraction logs (since mocking the endpoint bypasses logging)
        for i in range(3):
            log = AIExtractionLog(
                user_id="test-user-id",
                source="gemini",
                model="gemini-2.5-flash",
                file_mime_type="application/pdf",
                success=True,
                input_tokens=200,
                output_tokens=100,
                cost_cents=Decimal("0.05"),
            )
            database_session.add(log)
        database_session.flush()

        # Check dashboard aggregation
        response = api_client.get("/api/v1/dashboard/ai-costs", headers=AUTH_HEADERS)
        assert response.status_code == 200
        costs = response.json()
        assert costs["total_extractions"] == 3
        assert costs["total_cost_cents"] == pytest.approx(0.15, abs=0.01)
        assert len(costs["by_provider"]) == 1
        assert costs["by_provider"][0]["provider"] == "gemini"
        assert costs["by_provider"][0]["extraction_count"] == 3


# ── Dashboard AI Costs Tests ─────────────────────────────────────────────


class TestAICostsDashboard:
    """GET /api/v1/dashboard/ai-costs endpoint tests."""

    def should_return_empty_when_no_extractions(self, api_client):
        """No extraction logs → zero totals, empty provider breakdown."""
        response = api_client.get("/api/v1/dashboard/ai-costs", headers=AUTH_HEADERS)

        assert response.status_code == 200
        costs = response.json()
        assert costs["total_extractions"] == 0
        assert costs["total_cost_cents"] == 0.0
        assert costs["by_provider"] == []

    def should_return_aggregated_costs_for_current_month(self, api_client, database_session):
        """Extractions in current month → correct aggregation by provider."""
        # Insert logs for two providers
        database_session.add(
            AIExtractionLog(
                user_id="test-user-id",
                source="gemini",
                model="gemini-2.5-flash",
                file_mime_type="application/pdf",
                success=True,
                input_tokens=100,
                output_tokens=50,
                cost_cents=Decimal("0.03"),
            )
        )
        database_session.add(
            AIExtractionLog(
                user_id="test-user-id",
                source="openai",
                model="gpt-4o-mini",
                file_mime_type="application/pdf",
                success=True,
                input_tokens=200,
                output_tokens=80,
                cost_cents=Decimal("0.10"),
            )
        )
        database_session.flush()

        # Check dashboard
        response = api_client.get("/api/v1/dashboard/ai-costs", headers=AUTH_HEADERS)
        assert response.status_code == 200
        costs = response.json()
        assert costs["total_extractions"] == 2
        assert costs["total_cost_cents"] == pytest.approx(0.13, abs=0.01)
        assert len(costs["by_provider"]) == 2

        providers = {p["provider"]: p for p in costs["by_provider"]}
        assert providers["gemini"]["extraction_count"] == 1
        assert providers["openai"]["extraction_count"] == 1
