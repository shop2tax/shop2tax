/**
 * API TypeScript types matching FastAPI Pydantic schemas.
 *
 * Keep in sync with apps/api/app/schemas/*.py
 */

// --- Enums ---

export type SourceType = 'csv_parser' | 'api_sync' | 'csv_mapping' | 'marketplace_mapping'
export type MatchStatus = 'matched' | 'unmatched' | 'no_enrichment'

// Computed transaction status
export type TransactionStatus = 'open' | 'assigned' | 'booked' | 'automatic' | 'private' | 'internal'

// Summary of a linked receipt (for transaction response)
export interface LinkedReceiptSummary {
  id: string
  receipt_number: string
  counterparty: string
  amount: string // Decimal as string
  date: string // ISO date
  type: ReceiptType
  has_file: boolean
}

export type AccountCategory = 'revenue' | 'expense' | 'neutral'

// --- SKR03 Account ---

export interface SKR03AccountResponse {
  id: number
  name: string
  category: AccountCategory
  active: boolean
  bu_schluessel: number | null
  is_system: boolean
}

export interface SKR03AccountCreate {
  id: number
  name: string
  category: AccountCategory
  bu_schluessel?: number | null
}

export interface SKR03AccountUpdate {
  name?: string
  active?: boolean
  bu_schluessel?: number | null
}

// --- Transaction ---

export interface TransactionResponse {
  id: string
  date: string // ISO date
  amount: string // Decimal as string
  counterparty: string
  description: string
  source_config_id: string | null
  source_config_name: string | null
  source_reference: string | null
  oms_order_id: string | null
  notes: string | null
  is_private: boolean
  remaining_amount: string | null // OMS partial payment tracking
  // Currency (for non-EUR transactions like PayPal foreign currency)
  original_currency: string | null // ISO 4217 code (e.g., 'USD', 'GBP')
  original_amount: string | null // Decimal as string
  exchange_rate: string | null // Decimal as string
  // Computed status (Phase 2)
  status: TransactionStatus
  // Open amount: abs(amount) - sum(linked_receipt_line_items.amount)
  open_amount: string // Decimal as string
  // All linked receipts (from junction table)
  linked_receipts: LinkedReceiptSummary[]
  // Internal transfer (Geldbewegung)
  is_internal_transfer: boolean
  linked_transfer_id: string | null
  created_at: string
  updated_at: string
}

export interface TransactionListResponse {
  items: TransactionResponse[]
  total: number
}

export interface TransactionCreate {
  date: string
  amount: string
  counterparty: string
  description: string
  source_config_id: string
  source_reference?: string
  notes?: string
  is_private?: boolean
}

export interface TransactionUpdate {
  date?: string
  amount?: string
  counterparty?: string
  description?: string
  notes?: string
  is_private?: boolean
}

// Transfer (Geldbewegung) types
export interface TransferSuggestion {
  id: string
  date: string // ISO date
  amount: string // Decimal as string
  counterparty: string
  source_config_name: string | null
  description: string
}

export interface TransferLinkRequest {
  target_transaction_id: string
}

export interface TransactionImportItem {
  date: string
  amount: string
  counterparty: string
  description: string
  source_reference?: string
  // Marketplace-specific fields (from parse-marketplace response)
  import_hash?: string | null
  is_internal_transfer?: boolean
  extra_data?: Record<string, unknown> | null
  oms_order_id?: string | null
}

export interface TransactionImportRequest {
  source_config_id: string
  items: TransactionImportItem[]
  skip_duplicates?: boolean
}

export interface TransactionImportError {
  row_index: number
  error: string
}

export interface TransactionImportResponse {
  imported_count: number
  skipped_count: number
  error_count: number
  errors: TransactionImportError[]
  import_log_id: string
  linked_count: number
  no_receipt_count: number
  skipped_locked_count: number
}

export interface AutoLinkResponse {
  linked: number
  already_linked: number
  no_receipt: number
  skipped_locked: number
}

// --- CSV ---

export interface CsvFormatInfo {
  source: string // Source name (e.g., "Etsy", "Amazon")
  source_config_id: string | null
  config_name: string
  delimiter: string
  row_count: number
}

export interface ParsedRowResponse {
  date: string | null
  amount: string | null
  counterparty: string | null
  description: string | null
  source_reference: string | null
  oms_order_id?: string | null
}

export interface CsvDetectResponse {
  success: boolean
  format: CsvFormatInfo | null
  error: string | null
}

export interface CsvParseResponse {
  success: boolean
  source: string | null
  source_config_id: string | null
  config_name: string | null
  row_count: number
  rows: ParsedRowResponse[]
  error: string | null
}

export interface CsvUploadResponse {
  success: boolean
  filename: string
  format: CsvFormatInfo | null
  preview_rows: ParsedRowResponse[]
  total_rows: number
  error: string | null
}

// --- Generic CSV Import (bank imports with column mapping) ---

export interface SuggestedColumns {
  column_date: string | null
  column_amount: string | null
  column_counterparty: string | null
  column_description: string | null
  column_reference: string | null
}

export interface CsvAnalyzeResponse {
  success: boolean
  filename: string

  // Detected parsing options (editable in UI)
  delimiter: string | null
  encoding: string | null
  has_header: boolean
  skip_rows: number
  date_format: string | null
  date_ambiguous: boolean // True if DD/MM vs MM/DD ambiguity
  amount_format: string | null // "german" or "english"

  // Column information for mapping UI
  column_headers: string[]
  sample_values: Record<string, string[]> // column_name → first 5 values
  unique_values: Record<string, string[]> // column_name → ALL unique values (for filter dropdowns)

  // Auto-detected column suggestions (pre-fill dropdowns)
  suggested_columns: SuggestedColumns | null

  error: string | null
}

export interface GenericCsvMappingRequest {
  // CSV parsing options
  delimiter: string
  encoding: string
  has_header: boolean
  skip_rows: number
  date_format?: string | null
  amount_format?: string | null // "german" or "english"

  // Column assignments (all optional — bank needs date+amount+counterparty+description, marketplace only needs reference)
  column_date?: string | null
  column_amount?: string | null
  column_counterparty?: string | null
  column_description?: string | null
  column_reference?: string | null

  // Filter (marketplace)
  column_filter?: string | null
  filter_include_values?: string[] | null
}

export interface GenericCsvParseResponse {
  success: boolean
  row_count: number
  rows: ParsedRowResponse[]
  errors: string[] // Per-row error messages
  error: string | null // Overall error
  filtered_count?: number // Number of rows filtered out
}

// --- File-based CSV Upload ---

export interface CsvFileUploadResponse {
  success: boolean
  file_id: string | null
  filename: string
  expires_at: string | null
}

// --- OMS Enrichment ---

export interface EnrichedRowResponse {
  date: string | null
  amount: string | null
  counterparty: string | null
  description: string | null
  source_reference: string | null
  enriched_counterparty: string | null
  enriched_description: string | null
  enriched_date: string | null
  enriched_amount: string | null
  match_status: MatchStatus
}

export interface CsvEnrichResponse {
  success: boolean
  rows: EnrichedRowResponse[]
  total_rows: number
  matched_count: number
  unmatched_count: number
  errors: string[]
  error: string | null
}

// --- OMS ---

export type OmsProviderType = 'billbee' | 'jtl' | 'xentral'

export interface OmsProviderInfo {
  id: string
  type: OmsProviderType
  display_name: string
  is_active: boolean
}

export interface OmsOrderItem {
  product_title: string
  quantity: number
  total_price: string
  sku: string | null
  tax_index: number
  tax_amount: string
}

export interface OmsOrder {
  order_id: string
  order_number: string
  invoice_number: string | null
  invoice_number_prefix: string | null
  state: number
  created_at: string
  total_cost: string
  currency: string
  customer_name: string
  customer_email: string | null
  shop_id: number
  shop_name: string | null
  platform: string | null
  items: OmsOrderItem[]
  tags: string[]
  paid_amount: string
  is_paid: boolean
  paid_at: string | null
  tax_rate_1: string | null
  tax_rate_2: string | null
}

export interface OmsOrderListResponse {
  items: OmsOrder[]
  total: number
  cached: boolean
  cache_expires_at: string | null
}

export interface OmsStoreResponse {
  id: string
  store_type: string
  label: string
  external_shop_id: number
  provider_id: string | null
  source_config_id: string | null
  source_config_name: string | null
  match_strategy: string // "order_number" or "email"
  created_at: string
  updated_at: string
}

export interface OmsSettingsResponse {
  has_credentials: boolean
  stores: OmsStoreResponse[]
}

export interface OmsMatchSuggestion {
  oms_order_id: string
  order_number: string
  confidence: number
  match_reasons: string[]
  order_amount: string
  order_date: string
  customer_name: string
}

export interface OmsStoreCreate {
  store_type: string
  label: string
  external_shop_id: number
  provider_id?: string | null
  source_config_id?: string | null
  match_strategy?: string
}

export interface OmsStoreUpdate {
  store_type?: string
  label?: string
  external_shop_id?: number
  provider_id?: string | null
  source_config_id?: string | null
  match_strategy?: string
}

export interface OmsLinkRequest {
  oms_order_id: string
  amount_covered?: string
}

// --- OMS Sync ---

export type OmsSyncStatus = 'success' | 'partial' | 'failed'

export interface OmsSyncLogResponse {
  id: string
  start_date: string
  end_date: string
  fetched_count: number
  imported_count: number
  skipped_count: number
  status: OmsSyncStatus
  error_message: string | null
  created_at: string
}

export interface OmsSyncLogListResponse {
  items: OmsSyncLogResponse[]
  total: number
}

// --- DATEV ---

export interface DatevConfig {
  beraternummer: string
  mandantennummer: string
  wirtschaftsjahr_beginn: string
  sachkontenlaenge?: number
}

export interface DatevExportRequest {
  config: DatevConfig
  date_from?: string
  date_to?: string
  include_unreconciled?: boolean
}

export interface DatevZipExportRequest {
  config: DatevConfig
  date_from?: string
  date_to?: string
  include_receipts?: boolean
  finalized_only?: boolean
  document_types?: string[] | null
}

export interface DatevBookingLine {
  umsatz: string
  soll_haben: string
  waehrung: string
  konto: number
  gegenkonto: number
  bu_schluessel: number | null
  belegfeld_1: string
  belegfeld_2: string | null
  datum: string
  buchungstext: string
  ust_satz: string | null
  netto: string | null
  ust_betrag: string | null
}

export interface DatevExportResponse {
  header: string[]
  column_headers: string[]
  rows: string[][]
  transaction_count: number
  line_item_count: number
  csv_content: string
}

export interface DatevValidationResult {
  valid: boolean
  errors: string[]
  warnings: string[]
}

export interface DatevZipValidationResult {
  valid: boolean
  errors: string[]
  warnings: string[]
  receipts_without_file: string[]
  estimated_size_bytes: number
}

export interface ExportLogResponse {
  id: string
  export_type: string
  export_format: string // 'csv' or 'zip'
  transaction_count: number
  line_item_count: number
  date_from: string | null
  date_to: string | null
  beraternummer: string
  mandantennummer: string
  filename: string | null
  created_at: string
}

export interface ExportHistoryResponse {
  items: ExportLogResponse[]
  total: number
}

// --- Receipt ---

export type ReceiptType = 'revenue' | 'expense'
export type ReceiptStatus = 'draft' | 'final'
export type PaymentStatus = 'unpaid' | 'paid'
export type ReceiptTab = 'all' | 'draft' | 'open' | 'overdue' | 'finalized'
export type TaxRule
  = | 'tax_included'
    | 'tax_excluded'
    | 'no_tax'
    | 'reverse_charge' // Legacy — prefer specific RC variants below
  // Reverse Charge: EU-Ausland (§13b Abs. 1) — Etsy, PayPal, Google, Meta
    | 'rc_eu_no_vst' // Kleinunternehmer → BU 95, Konto 3165
    | 'rc_eu_with_vst' // Regelbesteuert → BU 94, Konto 3125
  // Reverse Charge: Deutschland (§13b Abs. 2) — Bauleistungen etc.
    | 'rc_de_no_vst'
    | 'rc_de_with_vst'
  // Reverse Charge: Drittland (§13b Abs. 2) — Non-EU services
    | 'rc_non_eu_no_vst'
    | 'rc_non_eu_with_vst'

export interface ReceiptLineItemResponse {
  id: string
  position: number
  description: string
  amount: string // Decimal as string
  skr03_account_id: number | null
  skr03_account_number: number | null
  skr03_account_name: string | null
  tax_rule: TaxRule
  tax_rate: string // Decimal as string (e.g., "19.00")
  depreciation: string | null
  // Reverse Charge computed fields
  reverse_charge_tax_amount: string | null // 19% RC tax if applicable
  effective_tax_rate: string | null // Always 19% for RC, otherwise tax_rate
}

export interface TagResponse {
  id: string
  name: string
}

export interface LinkedTransactionSummary {
  id: string
  date: string // ISO date
  amount: string // Decimal as string
  counterparty: string
  source_config_name: string | null
}

export interface ReceiptResponse {
  id: string
  type: ReceiptType
  status: ReceiptStatus
  receipt_number: string
  date: string // ISO date
  amount: string // Decimal as string (computed from line_items)
  counterparty: string
  description: string

  // New fields
  due_date: string | null // ISO date
  payment_date: string | null // ISO date
  delivery_period: string | null
  currency: string

  // Line items (multi-position support)
  line_items: ReceiptLineItemResponse[]

  // Tags
  tags: TagResponse[]

  // OMS provider fields (revenue)
  oms_order_id: string | null
  oms_invoice_number: string | null
  oms_shop_name: string | null
  oms_platform: string | null

  // File attachment
  has_file: boolean
  file_original_name: string | null
  file_mime_type: string | null

  // Open amount: receipt total - linked transaction amount
  open_amount: string // Decimal as string

  // Reverse Charge aggregates
  total_reverse_charge_tax: string // Sum of all RC tax (§13b USt)
  has_reverse_charge_items: boolean // True if any line item uses RC

  // GoBD status
  is_locked: boolean
  locked_at: string | null

  // Payment status (synced with link status)
  payment_status: PaymentStatus

  // Link status (from junction table)
  // Note: linked_transaction_id and linked_transaction are deprecated (single link)
  // Use linked_transactions for the full list (Sammelbeleg: 1 Receipt → N Transactions)
  linked_transaction_id: string | null
  linked_transaction: LinkedTransactionSummary | null
  linked_transactions: LinkedTransactionSummary[]

  // Extraction
  delivery_date: string | null // ISO date
  extraction_source: string | null // "zugferd", "gemini", "openai", "anthropic", "manual"

  // Timestamps
  created_at: string
  updated_at: string
}

export interface ReceiptListResponse {
  receipts: ReceiptResponse[]
  total: number
}

// --- Document Extraction ---

export interface ExtractionLineItem {
  description: string | null
  quantity: string | null // Decimal → string
  unit_price: string | null // Decimal → string
  amount: string | null // Decimal → string
  tax_rate: string | null // Decimal → string
}

export interface ExtractionResult {
  source: string
  warnings: string[]
  receipt_number: string | null
  date: string | null
  delivery_date: string | null
  due_date: string | null
  billing_period: string | null
  counterparty: string | null
  counterparty_address: string | null
  tax_number: string | null
  vat_id: string | null
  currency: string
  line_items: ExtractionLineItem[]
  total_net: string | null // Decimal → string
  total_tax: string | null // Decimal → string
  total_gross: string | null // Decimal → string
  payment_date: string | null
  payment_method: string | null
  payment_reference: string | null
  input_tokens: number | null
  output_tokens: number | null
  cost_cents: number | null
  // Phase 9: EU Provider Detection
  detected_provider: string | null
  suggested_tax_rule: TaxRule | null
  is_marketplace_invoice: boolean
}

export interface ReceiptMatchSuggestion {
  id: string // Transaction ID
  counterparty: string | null
  amount: string
  date: string
  confidence: number
  reasons: string[]
}

export interface ReceiptSuggestionForPayment {
  id: string // Receipt ID
  receipt_number: string
  type: ReceiptType
  counterparty: string
  amount: string
  date: string
  confidence: number
  reasons: string[]
}

export interface AccountSuggestionResponse {
  skr03_account_id: number
  confidence: number
  pattern: string
}

export interface SyncResultResponse {
  imported_count: number
  skipped_count: number
  pdf_count: number
  pdf_error_count: number
  linked_count: number
  errors: string[]
}

// OMS sync streaming progress events (NDJSON)
export interface OmsSyncProgressEvent {
  type: 'progress'
  processed: number
  total: number
  imported: number
  skipped: number
  errors: number
}

export interface OmsSyncCompleteEvent {
  type: 'complete'
  imported_count: number
  skipped_count: number
  pdf_count: number
  pdf_error_count: number
  errors: string[]
}

export type OmsSyncEvent = OmsSyncProgressEvent | OmsSyncCompleteEvent

export interface ReceiptLineItemCreate {
  description?: string
  amount: string // Decimal as string
  skr03_account_id?: number
  tax_rule?: TaxRule // Default: 'tax_included'
  tax_rate?: string // Decimal as string (e.g., "19.00")
  depreciation?: string
}

export interface ReceiptCreate {
  receipt_number: string
  date: string // ISO date
  counterparty: string
  type: ReceiptType
  description?: string
  status?: ReceiptStatus // Default: 'final'
  due_date?: string // ISO date
  payment_date?: string // ISO date
  delivery_period?: string
  currency?: string // Default: 'EUR'
  delivery_date?: string // ISO date
  extraction_source?: string // "zugferd", "gemini", etc.
  // Multi-position support
  line_items: ReceiptLineItemCreate[]
}

export interface ReceiptCreateAndLink extends ReceiptCreate {
  transaction_id: string
}

export interface ReceiptCreateAndLinkBulk extends ReceiptCreate {
  transaction_ids: string[]
}

export interface ReceiptLinkRequest {
  transaction_id: string
}

// --- Bulk Linking (Sammelbeleg) ---

export interface BulkLinkRequest {
  transaction_ids: string[]
}

export interface BulkLinkResponse {
  linked_count: number
  skipped_count: number
  receipt_open_amount: string // Decimal
  amount_difference: string // Decimal
  is_amount_matched: boolean
}

export interface BulkUnlinkRequest {
  transaction_ids: string[] // Empty = unlink all
}

export interface BulkUnlinkResponse {
  unlinked_count: number
  remaining_link_count: number
}

export interface TransactionGroup {
  type: string
  count: number
  total: string // Decimal
  transaction_ids: string[]
}

export interface TransactionSummary {
  id: string
  date: string // ISO date
  amount: string // Decimal
  counterparty: string | null
  description: string
  type: string | null
}

export interface BulkSuggestionResponse {
  transactions: TransactionSummary[]
  groups: TransactionGroup[]
  total: string // Decimal
  receipt_amount: string // Decimal
  difference: string // Decimal
  is_amount_matched: boolean
  source_config_id: string | null
}

export interface MatchingReceiptSummary {
  id: string
  receipt_number: string
  date: string // ISO date
  counterparty: string
  amount: string // Decimal
  type: ReceiptType
  has_file: boolean
  match_score: number
}

export interface FindMatchingReceiptsResponse {
  matching_receipts: MatchingReceiptSummary[]
  selected_total: string // Decimal
  transaction_count: number
}

export interface ReceiptLockRequest {
  start_date: string
  end_date: string
}

export interface RecordPaymentRequest {
  source_config_id: string // Required — which bank account
  date: string // Required — payment date (ISO date)
  amount?: string // Optional — Default: receipt total amount
  counterparty?: string // Optional — Default: receipt counterparty
  description?: string // Optional — Default: "Zahlung Beleg #{receipt_number}"
}

// --- PayPal Sync ---

export type PayPalSyncStatus = 'success' | 'partial' | 'failed'

export interface PayPalSyncRequest {
  start_date: string // ISO date (YYYY-MM-DD)
  end_date: string // ISO date (YYYY-MM-DD)
}

export interface PayPalSyncResponse {
  imported_count: number
  skipped_count: number
  fee_count: number
  sync_log_id: string
  errors: string[]
}

export interface PayPalSyncLogResponse {
  id: string
  start_date: string // ISO datetime
  end_date: string // ISO datetime
  fetched_count: number
  imported_count: number
  fee_count: number
  status: PayPalSyncStatus
  error_message: string | null
  created_at: string // ISO datetime
}

export interface PayPalSyncLogListResponse {
  items: PayPalSyncLogResponse[]
  total: number
}

// --- Site Settings ---

export interface PublicSettingsResponse {
  company_name: string | null
}

export interface SiteSettingsResponse {
  company_name: string | null
  is_small_business: boolean | null
  tax_number: string | null
  vat_id: string | null
  rc_tax_rate: number // Default 0.19 (19%)
  legal_form: string | null
  ai_provider: string | null
  ai_model: string | null
  oms_sync_set_labels: boolean // Set shop2tax label on synced orders
}

export interface SiteSettingsUpdate {
  company_name?: string | null
  is_small_business?: boolean | null
  tax_number?: string | null
  vat_id?: string | null
  rc_tax_rate?: number // 0.00–1.00 (e.g., 0.19 = 19%)
  legal_form?: string | null
  ai_provider?: string | null
  ai_model?: string | null
  oms_sync_set_labels?: boolean // Set shop2tax label on synced orders
}

export interface AIProviderResponse {
  provider: string
  models: string[]
}

export interface AICostResponse {
  total_extractions: number
  total_cost_cents: number
  by_provider: ProviderCostSummary[]
  period_start: string
  period_end: string
}

export interface ProviderCostSummary {
  provider: string
  extraction_count: number
  total_cost_cents: number
  total_input_tokens: number
  total_output_tokens: number
}

// --- Pagination ---

export interface PaginatedResponse<T> {
  items: T[]
  total: number
}

// --- Transaction Source Config ---

export interface MarketplaceSourceConfig {
  parser: string | null // "etsy", "amazon", "shopify" — determines dedicated parser
  has_ust_id_registered: boolean // USt-ID bei Marktplatz hinterlegt (affects RC tax treatment)
}

export interface TransactionSourceConfigResponse {
  id: string
  name: string
  type: SourceType
  check_account_id: number // SKR03 Buchungskonto (1200-1288 or 1590)
  is_system: boolean // True if marketplace (not user-created)
  has_mapping: boolean // True if user has a mapping profile for this source
  import_method: string // Human-readable: "CSV-Parser (automatisch)", "API-Sync", etc.
  source_config: MarketplaceSourceConfig | null // Marketplace-specific config
  created_at: string // ISO datetime
  updated_at: string // ISO datetime
}

export interface TransactionSourceConfigCreate {
  name: string
  type?: SourceType
  check_account_id?: number // Auto-assigned if not provided (1200-1288)
  source_config?: MarketplaceSourceConfig
}

export interface MarketplaceSourceConfigUpdate {
  parser?: string | null
  has_ust_id_registered?: boolean | null
}

export interface TransactionSourceConfigUpdate {
  name?: string
  type?: SourceType
  check_account_id?: number // SKR03 Buchungskonto (1200-1288 or 1590)
  source_config?: MarketplaceSourceConfigUpdate | null
}

// --- CSV Mapping Profile ---

export interface CsvMappingProfileResponse {
  id: string
  source_id: string
  source_name: string
  name: string | null

  // CSV parsing options
  delimiter: string
  encoding: string
  has_header: boolean
  skip_rows: number
  date_format: string | null
  amount_format: string | null // "german" or "english"

  // Column assignments (all nullable — marketplace only needs reference)
  column_date: string | null
  column_amount: string | null
  column_counterparty: string | null
  column_description: string | null
  column_reference: string | null
  column_filter: string | null
  filter_include_values: string[] | null

  created_at: string // ISO datetime
  updated_at: string // ISO datetime
}

export interface CsvMappingProfileCreate {
  source_id: string
  name?: string

  // CSV parsing options
  delimiter?: string
  encoding?: string
  has_header?: boolean
  skip_rows?: number
  date_format?: string | null
  amount_format?: string | null

  // Column assignments (all optional — marketplace only needs reference)
  column_date?: string | null
  column_amount?: string | null
  column_counterparty?: string | null
  column_description?: string | null
  column_reference?: string | null
  column_filter?: string | null
  filter_include_values?: string[] | null
}

export interface CsvMappingProfileUpdate {
  name?: string | null
  delimiter?: string
  encoding?: string
  has_header?: boolean
  skip_rows?: number
  date_format?: string | null
  amount_format?: string | null

  column_date?: string
  column_amount?: string | null
  column_counterparty?: string
  column_description?: string
  column_reference?: string | null
  column_filter?: string | null
  filter_include_values?: string[] | null
}

// --- Marketplace CSV Parsing (dedicated parsers: Etsy, Amazon, Shopify) ---

export interface MarketplaceParsedRowResponse {
  date: string // ISO date
  amount: string // Decimal as string
  counterparty: string
  description: string
  source_reference: string | null
  marketplace_type: string | null // Transaction type (e.g., "sale", "refund", "charge", "payout")
  suggested_skr03: number | null
  order_id: string | null
  oms_order_id: string | null
  is_internal_transfer: boolean
  is_rc_eligible: boolean
  rc_fee_amount: string | null // Decimal as string — Fee amount for RC calculation
  import_hash: string | null
  extra_data: Record<string, unknown> | null
}

export interface MarketplaceEnrichmentStats {
  matched: number
  unmatched: number
  skipped: number
  error?: string
}

export interface MarketplaceCsvParseResponse {
  success: boolean
  row_count: number
  rows: MarketplaceParsedRowResponse[]
  errors: string[]
  skipped_rows: number
  error: string | null
  enrichment: MarketplaceEnrichmentStats | null
  rc_ust_amount: string | null // Decimal as string — §13b RC USt on eligible fees
}
