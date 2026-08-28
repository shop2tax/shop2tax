"""Initial schema — squashed from 40+ development migrations.

Revision ID: 0001_initial
Revises: (none)
Create Date: 2026-02-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enum types ──────────────────────────────────────────────────────
    receipt_type = postgresql.ENUM("REVENUE", "EXPENSE", name="receipttype", create_type=False)
    receipt_status = postgresql.ENUM("DRAFT", "FINAL", name="receiptstatus", create_type=False)
    receipt_audit_action = postgresql.ENUM(
        "CREATED",
        "UPDATED",
        "FINALIZED",
        "LINKED",
        "UNLINKED",
        "DELETED",
        "LOCKED",
        "PAYMENT_RECORDED",
        "FILE_UPLOADED",
        "FILE_DOWNLOADED",
        name="receiptauditaction",
        create_type=False,
    )
    tax_rule = postgresql.ENUM("TAX_INCLUDED", "TAX_EXCLUDED", "NO_TAX", "REVERSE_CHARGE", name="taxrule", create_type=False)
    account_category = postgresql.ENUM("REVENUE", "EXPENSE", "NEUTRAL", name="accountcategory", create_type=False)
    source_type = postgresql.ENUM("CSV_PARSER", "API_SYNC", "CSV_MAPPING", "MARKETPLACE_MAPPING", name="sourcetype", create_type=False)
    billbee_sync_status = postgresql.ENUM("SUCCESS", "PARTIAL", "FAILED", name="billbeesyncstatus", create_type=False)
    paypal_sync_status = postgresql.ENUM("SUCCESS", "PARTIAL", "FAILED", name="paypalsyncstatus", create_type=False)

    for enum in [
        receipt_type,
        receipt_status,
        receipt_audit_action,
        tax_rule,
        account_category,
        source_type,
        billbee_sync_status,
        paypal_sync_status,
    ]:
        enum.create(op.get_bind(), checkfirst=True)

    # ── users ───────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(255), nullable=False, index=True),
        sa.Column("provider_type", sa.String(50), nullable=False, server_default="google"),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider_id", "provider_type", name="uq_user_provider"),
    )

    # ── skr03_accounts ──────────────────────────────────────────────────
    op.create_table(
        "skr03_accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", account_category, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("bu_schluessel", sa.Integer, nullable=True),
    )

    # ── site_settings ───────────────────────────────────────────────────
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("is_small_business", sa.Boolean, nullable=True),
        sa.Column("tax_number", sa.String(50), nullable=True),
        sa.Column("vat_id", sa.String(20), nullable=True),
        sa.Column("legal_form", sa.String(100), nullable=True),
        sa.Column("datev_config", postgresql.JSONB, nullable=True),
        sa.Column("ai_provider", sa.String(20), nullable=True),
        sa.Column("ai_model", sa.String(50), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_site_settings_singleton"),
    )

    # ── transaction_source_configs ──────────────────────────────────────
    op.create_table(
        "transaction_source_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", source_type, nullable=False),
        sa.Column("check_account_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("check_account_id", name="uq_source_check_account_id"),
    )

    # ── csv_mapping_profiles ────────────────────────────────────────────
    op.create_table(
        "csv_mapping_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("transaction_source_configs.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("delimiter", sa.String(5), nullable=False, server_default=","),
        sa.Column("encoding", sa.String(20), nullable=False, server_default="utf-8"),
        sa.Column("has_header", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("skip_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("date_format", sa.String(30), nullable=True),
        sa.Column("amount_format", sa.String(20), nullable=True),
        sa.Column("column_date", sa.String(100), nullable=True),
        sa.Column("column_amount", sa.String(100), nullable=True),
        sa.Column("column_counterparty", sa.String(100), nullable=True),
        sa.Column("column_description", sa.String(100), nullable=True),
        sa.Column("column_reference", sa.String(100), nullable=True),
        sa.Column("column_filter", sa.String(100), nullable=True),
        sa.Column("filter_include_values", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", name="uq_mapping_source"),
    )

    # ── transactions ────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("date", sa.DATE, nullable=False, index=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("counterparty", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("source_config_id", sa.String(36), sa.ForeignKey("transaction_source_configs.id"), nullable=False, index=True),
        sa.Column("source_reference", sa.String(255), nullable=True),
        sa.Column("import_hash", sa.String(64), nullable=True, index=True),
        sa.Column("billbee_order_id", sa.String(255), nullable=True, index=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_private", sa.Boolean, nullable=False, server_default=sa.text("false"), index=True),
        sa.Column("remaining_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("original_currency", sa.String(3), nullable=True),
        sa.Column("original_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("linked_transfer_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("is_internal_transfer", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── tags ────────────────────────────────────────────────────────────
    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
    )

    # ── receipts ────────────────────────────────────────────────────────
    op.create_table(
        "receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("type", receipt_type, nullable=False, index=True),
        sa.Column("receipt_number", sa.String(100), nullable=False),
        sa.Column("date", sa.DATE, nullable=False, index=True),
        sa.Column("counterparty", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", receipt_status, nullable=False, server_default="FINAL", index=True),
        sa.Column("due_date", sa.DATE, nullable=True),
        sa.Column("payment_date", sa.DATE, nullable=True),
        sa.Column("delivery_date", sa.DATE, nullable=True),
        sa.Column("delivery_period", sa.String(255), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("extraction_source", sa.String(20), nullable=True),
        sa.Column("billbee_order_id", sa.String(255), nullable=True, index=True),
        sa.Column("billbee_invoice_number", sa.String(100), nullable=True),
        sa.Column("billbee_shop_name", sa.String(255), nullable=True),
        sa.Column("billbee_platform", sa.String(100), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("file_storage_id", sa.String(500), nullable=True),
        sa.Column("file_original_name", sa.String(255), nullable=True),
        sa.Column("file_mime_type", sa.String(100), nullable=True),
        sa.Column("payment_status", sa.String(10), nullable=False, server_default="unpaid", index=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial unique index for Billbee deduplication
    op.create_index(
        "uq_receipt_billbee_order",
        "receipts",
        ["billbee_order_id"],
        unique=True,
        postgresql_where=sa.text("billbee_order_id IS NOT NULL AND deleted_at IS NULL"),
    )

    # ── receipt_tags (M:N junction) ─────────────────────────────────────
    op.create_table(
        "receipt_tags",
        sa.Column("receipt_id", sa.String(36), sa.ForeignKey("receipts.id"), primary_key=True),
        sa.Column("tag_id", sa.String(36), sa.ForeignKey("tags.id"), primary_key=True),
    )

    # ── receipt_line_items ──────────────────────────────────────────────
    op.create_table(
        "receipt_line_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("receipt_id", sa.String(36), sa.ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("skr03_account_id", sa.Integer, sa.ForeignKey("skr03_accounts.id"), nullable=True),
        sa.Column("tax_rule", tax_rule, nullable=False, server_default="TAX_INCLUDED"),
        sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="19.00"),
        sa.Column("depreciation", sa.String(255), nullable=True),
    )

    # ── receipt_transaction_links ───────────────────────────────────────
    op.create_table(
        "receipt_transaction_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("receipt_id", sa.String(36), sa.ForeignKey("receipts.id"), nullable=False, index=True),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("receipt_id", name="uq_receipt_transaction_link_receipt"),
    )

    # ── receipt_audit_logs ──────────────────────────────────────────────
    op.create_table(
        "receipt_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("receipt_id", sa.String(36), sa.ForeignKey("receipts.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("action", receipt_audit_action, nullable=False, index=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── accounting_patterns ─────────────────────────────────────────────
    op.create_table(
        "accounting_patterns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("skr03_account_id", sa.Integer, sa.ForeignKey("skr03_accounts.id"), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("hits", sa.Integer, nullable=False, server_default="0"),
    )

    # ── imports ─────────────────────────────────────────────────────────
    op.create_table(
        "imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("source_config_id", sa.String(36), sa.ForeignKey("transaction_source_configs.id"), nullable=True),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("imported_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── export_logs ─────────────────────────────────────────────────────
    op.create_table(
        "export_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("export_type", sa.String(50), nullable=False, server_default="datev"),
        sa.Column("transaction_count", sa.Integer, nullable=False),
        sa.Column("line_item_count", sa.Integer, nullable=False),
        sa.Column("date_from", sa.DATE, nullable=True),
        sa.Column("date_to", sa.DATE, nullable=True),
        sa.Column("beraternummer", sa.String(20), nullable=False),
        sa.Column("mandantennummer", sa.String(20), nullable=False),
        sa.Column("filename", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── billbee_stores ──────────────────────────────────────────────────
    op.create_table(
        "billbee_stores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("store_type", sa.String(50), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("billbee_shop_id", sa.Integer, nullable=False),
        sa.Column("source_config_id", sa.String(36), sa.ForeignKey("transaction_source_configs.id"), nullable=True),
        sa.Column("match_strategy", sa.String(20), nullable=False, server_default="order_number"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── billbee_sync_logs ───────────────────────────────────────────────
    op.create_table(
        "billbee_sync_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("imported_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", billbee_sync_status, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── paypal_sync_logs ────────────────────────────────────────────────
    op.create_table(
        "paypal_sync_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("imported_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fee_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", paypal_sync_status, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── ai_extraction_logs ──────────────────────────────────────────────
    op.create_table(
        "ai_extraction_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("model", sa.String(50), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("cost_cents", sa.Float, nullable=True),
        sa.Column("file_mime_type", sa.String(50), nullable=False),
        sa.Column("file_pages_total", sa.Integer, nullable=True),
        sa.Column("file_pages_sent", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("error_message", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("ai_extraction_logs")
    op.drop_table("paypal_sync_logs")
    op.drop_table("billbee_sync_logs")
    op.drop_table("billbee_stores")
    op.drop_table("export_logs")
    op.drop_table("imports")
    op.drop_table("accounting_patterns")
    op.drop_table("receipt_audit_logs")
    op.drop_table("receipt_transaction_links")
    op.drop_table("receipt_line_items")
    op.drop_table("receipt_tags")
    op.drop_table("receipts")
    op.drop_table("tags")
    op.drop_table("transactions")
    op.drop_table("csv_mapping_profiles")
    op.drop_table("transaction_source_configs")
    op.drop_table("site_settings")
    op.drop_table("skr03_accounts")
    op.drop_table("users")

    # Drop enum types
    for enum_name in [
        "paypalsyncstatus",
        "billbeesyncstatus",
        "sourcetype",
        "accountcategory",
        "taxrule",
        "receiptauditaction",
        "receiptstatus",
        "receipttype",
    ]:
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
