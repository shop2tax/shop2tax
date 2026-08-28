"""AI extraction log model for tracking OCR/e-invoice extraction costs."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AIExtractionLog(Base):
    """Tracks AI-based document extraction attempts and their costs.

    Records every extraction attempt (ZUGFeRD, Gemini, OpenAI, Anthropic)
    for cost monitoring and usage analytics.
    """

    __tablename__ = "ai_extraction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255))  # Audit only (created_by), NOT for filtering (Shared Tenant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(20))  # "zugferd", "gemini", "openai", "anthropic"
    model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cents: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_mime_type: Mapped[str] = mapped_column(String(50))
    file_pages_total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Total pages in PDF
    file_pages_sent: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Pages actually sent to LLM
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
