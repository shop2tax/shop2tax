<script setup lang="ts">
import type { ExtractionResult, ReceiptLineItemCreate, ReceiptStatus, ReceiptType, TaxRule } from '~/types/api'
import { isReverseCharge } from '~/utils/tax'

definePageMeta({
  middleware: ['auth'],
})

const route = useRoute()
const router = useRouter()
const toast = useToast()

// Edit mode: ?edit=<receipt-id>
const editId = computed(() => route.query.edit as string | undefined)
const isEditMode = computed(() => !!editId.value)

// Optional transaction prefill via ?transaction=xxx or ?transaction_id=xxx
const transactionId = computed(() => (route.query.transaction ?? route.query.transaction_id) as string | undefined)
const hasTransaction = computed(() => !!transactionId.value)

// Bulk linking mode: ?bulk_transaction_ids=xxx,yyy&bulk_total=123.45 or ?bulk_storage_key=key
const bulkTransactionIdsParam = computed(() => route.query.bulk_transaction_ids as string | undefined)
const bulkTotalParam = computed(() => route.query.bulk_total as string | undefined)
const bulkStorageKey = computed(() => route.query.bulk_storage_key as string | undefined)
const bulkTransactionIds = ref<string[]>([])
const bulkTransactionsTotal = ref(0)
const isBulkMode = computed(() => bulkTransactionIds.value.length > 0)

// Query param prefill (from LinkingModal "Neuen Beleg anlegen")
const queryAmount = computed(() => route.query.amount as string | undefined)
const queryDate = computed(() => route.query.date as string | undefined)
const queryCounterparty = computed(() => route.query.counterparty as string | undefined)

// Fetch transaction data only if query param provided
const { data: transaction } = useFetch<{
  id: string
  date: string
  amount: string
  counterparty: string
  description: string
  source: string
}>(() => transactionId.value ? `/api/v1/transactions/${transactionId.value}` : '', {
  immediate: hasTransaction.value,
  watch: false,
})

// Fetch SKR03 accounts for category selection
const { data: accounts } = useActiveAccounts()
const { createReceipt, createAndLinkReceipt, createAndLinkBulkReceipt, updateReceipt, uploadFile, downloadFile } = useReceiptMutations()

// Fetch site settings for is_small_business (affects RC VSt default) and rc_tax_rate
const { data: siteSettings } = useSiteSettings()
const isSmallBusiness = computed(() => siteSettings.value?.is_small_business ?? true)
const rcTaxRate = computed(() => siteSettings.value?.rc_tax_rate ?? 0.19)

// Fetch existing receipt for edit mode
const { data: existingReceipt } = useFetch<{
  id: string
  receipt_number: string
  date: string
  counterparty: string
  type: ReceiptType
  status: string
  due_date: string | null
  payment_date: string | null
  delivery_date: string | null
  delivery_period: string | null
  currency: string
  extraction_source: string | null
  has_file: boolean
  file_original_name: string | null
  file_mime_type: string | null
  line_items: Array<{
    id: string
    description: string
    amount: string
    skr03_account_id: number | null
    tax_rule: TaxRule
    tax_rate: string
    depreciation: string | null
  }>
}>(() => editId.value ? `/api/v1/receipts/${editId.value}` : '', {
  immediate: !!editId.value,
  watch: false,
})
const { extracting, extractionError, extractionSource, extractionWarnings, extractFromFile } = useDocumentExtraction()
const detectedProvider = ref<string | null>(null)

// File upload state
const selectedFile = ref<File | null>(null)
const filePreviewUrl = ref<string | null>(null)
const existingFileMimeType = ref<string | null>(null)
const existingFileName = ref<string | null>(null)

// Form state
const receiptType = ref<ReceiptType>('expense')
const receiptNumber = ref('')
const receiptDate = ref('')
const supplier = ref('')
const deliveryDate = ref('')
const deliveryPeriod = ref('')
const showMoreFields = ref(false)
const dueDate = ref('')
const paymentDate = ref('')
const currency = ref('EUR')

// Auto-suggest SKR03 account based on counterparty
const { suggestedAccountId } = useSuggestAccount(supplier)
const userHasSelectedAccount = ref(false)

// Line items (positions)
// RC UI state for SevDesk-style 3-step selection
type RcOrigin = 'eu' | 'de' | 'non_eu'

interface LineItemForm {
  id: number
  description: string
  amount: string
  skr03_account_id: number | undefined
  tax_rule: TaxRule
  tax_rate: string
  depreciation: string
  // RC UI state (only used when tax_rule is RC variant)
  rc_origin: RcOrigin
  rc_with_vst: boolean
}

// Helper: Compute TaxRule from UI selections
function computeRcTaxRule(origin: RcOrigin, withVst: boolean): TaxRule {
  const suffix = withVst ? 'with_vst' : 'no_vst'
  return `rc_${origin}_${suffix}` as TaxRule
}

// Helper: Extract origin and VSt from TaxRule
function parseRcTaxRule(rule: TaxRule): { origin: RcOrigin, withVst: boolean } | null {
  if (rule === 'reverse_charge') {
    // Legacy: default to EU + no VSt (Kleinunternehmer)
    return { origin: 'eu', withVst: false }
  }
  const match = rule.match(/^rc_(eu|de|non_eu)_(no_vst|with_vst)$/)
  if (!match)
    return null
  return {
    origin: match[1] as RcOrigin,
    withVst: match[2] === 'with_vst',
  }
}

const lineItems = ref<LineItemForm[]>([
  {
    id: 1,
    description: '',
    amount: '',
    skr03_account_id: undefined,
    tax_rule: 'tax_included',
    tax_rate: '19.00',
    depreciation: '',
    rc_origin: 'eu',
    rc_with_vst: false, // Will be set based on isSmallBusiness
  },
])

let lineItemCounter = 2

// Load bulk transaction IDs and total from URL or sessionStorage
function loadBulkTransactions() {
  // Load from URL param
  if (bulkTransactionIdsParam.value) {
    bulkTransactionIds.value = bulkTransactionIdsParam.value.split(',').filter(Boolean)
    if (bulkTotalParam.value) {
      bulkTransactionsTotal.value = Number.parseFloat(bulkTotalParam.value)
    }
  }
  // Load from sessionStorage (for large selections)
  else if (bulkStorageKey.value) {
    const stored = sessionStorage.getItem(bulkStorageKey.value)
    if (stored) {
      const data = JSON.parse(stored) as { ids: string[], total: number } | string[]
      // Support both new { ids, total } and legacy string[] format
      if (Array.isArray(data)) {
        bulkTransactionIds.value = data
      }
      else {
        bulkTransactionIds.value = data.ids
        bulkTransactionsTotal.value = data.total
      }
      sessionStorage.removeItem(bulkStorageKey.value) // Clean up after loading
    }
  }

  // Prefill form with bulk data
  const total = bulkTransactionsTotal.value
  if (total > 0 && lineItems.value[0] && !lineItems.value[0].amount) {
    lineItems.value[0].amount = total.toFixed(2)
    receiptType.value = 'expense' // Bulk linking is typically for fees
  }
}

// Prefill form from existing receipt (edit mode)
watch(existingReceipt, (r) => {
  if (!r)
    return
  receiptType.value = r.type
  receiptNumber.value = r.receipt_number
  receiptDate.value = r.date
  supplier.value = r.counterparty
  deliveryDate.value = r.delivery_date ?? ''
  deliveryPeriod.value = r.delivery_period ?? ''
  dueDate.value = r.due_date ?? ''
  paymentDate.value = r.payment_date ?? ''
  currency.value = r.currency || 'EUR'
  if (r.line_items.length > 0) {
    lineItems.value = r.line_items.map((item, index) => {
      const rcParsed = parseRcTaxRule(item.tax_rule)
      return {
        id: index + 1,
        description: item.description ?? '',
        amount: item.amount,
        skr03_account_id: item.skr03_account_id ?? undefined,
        tax_rule: item.tax_rule,
        tax_rate: item.tax_rate,
        depreciation: item.depreciation ?? '',
        rc_origin: rcParsed?.origin ?? 'eu',
        rc_with_vst: rcParsed?.withVst ?? !isSmallBusiness.value,
      }
    })
    lineItemCounter = lineItems.value.length + 1
    userHasSelectedAccount.value = true
  }
  // Load existing file preview
  if (r.has_file) {
    existingFileMimeType.value = r.file_mime_type
    existingFileName.value = r.file_original_name
    downloadFile(r.id).then((blob) => {
      filePreviewUrl.value = URL.createObjectURL(blob)
    })
  }
}, { immediate: true })

// Handle primary tax type change (Normal / RC / No Tax)
type TaxType = 'normal' | 'reverse_charge' | 'no_tax'

function getTaxType(rule: TaxRule): TaxType {
  if (isReverseCharge(rule))
    return 'reverse_charge'
  if (rule === 'no_tax')
    return 'no_tax'
  return 'normal'
}

function handleTaxTypeChange(item: LineItemForm, taxType: TaxType) {
  if (taxType === 'normal') {
    item.tax_rule = 'tax_included'
    item.tax_rate = '19.00'
  }
  else if (taxType === 'no_tax') {
    item.tax_rule = 'no_tax'
    item.tax_rate = '0.00'
  }
  else {
    // Reverse Charge: use current origin + VSt state
    item.rc_with_vst = !isSmallBusiness.value // Default based on business type
    item.tax_rule = computeRcTaxRule(item.rc_origin, item.rc_with_vst)
    item.tax_rate = '19.00' // RC is always 19%
  }
}

function handleRcOriginChange(item: LineItemForm, origin: RcOrigin) {
  item.rc_origin = origin
  item.tax_rule = computeRcTaxRule(origin, item.rc_with_vst)
}

function handleRcVstChange(item: LineItemForm, withVst: boolean) {
  item.rc_with_vst = withVst
  item.tax_rule = computeRcTaxRule(item.rc_origin, withVst)
}

// Computed totals with tax breakdown (using rc_tax_rate from SiteSettings)
const { totalNetto, taxBreakdown, totalBrutto } = useReceiptTotals(lineItems, rcTaxRate)

// Prefill form when transaction loads (or from query params)
watch(transaction, (tx) => {
  if (tx) {
    receiptDate.value = tx.date
    supplier.value = tx.counterparty
    deliveryDate.value = tx.date
    // For expenses (negative amount), use absolute value
    const amount = Math.abs(Number.parseFloat(tx.amount))
    lineItems.value[0]!.amount = amount.toFixed(2)
    // Set type based on transaction amount
    receiptType.value = Number.parseFloat(tx.amount) >= 0 ? 'revenue' : 'expense'
  }
}, { immediate: true })

// Fallback: prefill from query params if no transaction fetch (LinkingModal sends these)
onMounted(async () => {
  // Load bulk transactions first (if applicable)
  loadBulkTransactions()

  // Query param prefill (only if not bulk mode and no transaction ID)
  if (!transactionId.value && !isBulkMode.value) {
    if (queryDate.value && !receiptDate.value)
      receiptDate.value = queryDate.value
    if (queryCounterparty.value && !supplier.value)
      supplier.value = queryCounterparty.value
    if (queryAmount.value && lineItems.value[0] && !lineItems.value[0].amount) {
      const amount = Math.abs(Number.parseFloat(queryAmount.value))
      lineItems.value[0].amount = amount.toFixed(2)
      receiptType.value = Number.parseFloat(queryAmount.value) >= 0 ? 'revenue' : 'expense'
    }
  }
})

// Auto-apply suggestion to first line item (only if user hasn't manually selected)
watch(suggestedAccountId, (accountId) => {
  if (accountId && !userHasSelectedAccount.value && lineItems.value[0]) {
    lineItems.value[0].skr03_account_id = accountId
  }
})

// Tax type options (SevDesk pattern: primary selection)
const taxTypeOptions = [
  { label: 'Normal (USt ausgewiesen)', value: 'normal' },
  { label: 'Reverse Charge (§13b)', value: 'reverse_charge' },
  { label: 'Keine USt', value: 'no_tax' },
]

// RC origin options (shown when RC selected)
const rcOriginOptions = [
  { label: 'EU-Ausland', value: 'eu' },
  { label: 'Deutschland', value: 'de' },
  { label: 'Drittland', value: 'non_eu' },
]

const taxRateOptions = [
  { label: '19%', value: '19.00' },
  { label: '7%', value: '7.00' },
  { label: '0%', value: '0.00' },
]

const currencyOptions = [
  { label: 'EUR', value: 'EUR' },
  { label: 'USD', value: 'USD' },
  { label: 'GBP', value: 'GBP' },
]

// File handling — triggered by ReceiptDocumentViewer
async function handleFileSelected(file: File) {
  selectedFile.value = file
  filePreviewUrl.value = URL.createObjectURL(file)
  detectedProvider.value = null

  // Attempt document extraction
  const result = await extractFromFile(file)
  if (result) {
    applyExtractionResult(result)
  }
}

function applyExtractionResult(result: ExtractionResult) {
  // Autofill only empty fields — never overwrite user input
  if (!receiptNumber.value && result.receipt_number)
    receiptNumber.value = result.receipt_number
  if (!receiptDate.value && result.date)
    receiptDate.value = result.date
  if (!supplier.value && result.counterparty)
    supplier.value = result.counterparty
  if (!deliveryDate.value && result.delivery_date)
    deliveryDate.value = result.delivery_date
  if (!deliveryPeriod.value && result.billing_period)
    deliveryPeriod.value = result.billing_period
  if (!dueDate.value && result.due_date) {
    dueDate.value = result.due_date
    showMoreFields.value = true
  }
  if (!paymentDate.value && result.payment_date) {
    paymentDate.value = result.payment_date
    showMoreFields.value = true
  }
  if (!currency.value || currency.value === 'EUR')
    currency.value = result.currency

  // Line items: only populate when first item is still empty
  const firstItem = lineItems.value[0]
  if (firstItem && !firstItem.amount) {
    // Determine tax rate from totals or line items
    const totalGross = Number.parseFloat(result.total_gross ?? '') || 0
    const totalNet = Number.parseFloat(result.total_net ?? '') || 0
    const totalTax = Number.parseFloat(result.total_tax ?? '') || 0

    if (result.line_items.length > 0) {
      // Extracted amounts are NET — convert to GROSS and use tax_included ("USt ausgewiesen")
      lineItems.value = result.line_items.map((item, index) => {
        const taxRate = Number.parseFloat(item.tax_rate ?? '') || 19
        const netAmount = Number.parseFloat(item.amount ?? '') || 0
        const grossAmount = taxRate > 0 ? netAmount * (1 + taxRate / 100) : netAmount
        return {
          id: index + 1,
          description: item.description ?? '',
          amount: grossAmount > 0 ? grossAmount.toFixed(2) : '',
          skr03_account_id: undefined,
          tax_rule: (taxRate > 0 ? 'tax_included' : 'no_tax') as TaxRule,
          tax_rate: taxRate > 0 ? taxRate.toFixed(2) : '0.00',
          depreciation: '',
          rc_origin: 'eu' as RcOrigin,
          rc_with_vst: !isSmallBusiness.value,
        }
      })
      lineItemCounter = lineItems.value.length + 1

      // Plausibility check: if total_gross is known, verify computed sum matches
      if (totalGross > 0) {
        const computedGross = lineItems.value.reduce((sum, item) => sum + (Number.parseFloat(item.amount) || 0), 0)
        const tolerance = totalGross * 0.05
        if (Math.abs(computedGross - totalGross) > tolerance) {
          // LLM likely returned gross amounts instead of net — fall back to total_gross
          console.warn(`Extraction plausibility failed: computed ${computedGross.toFixed(2)} vs total_gross ${totalGross.toFixed(2)}, using total_gross`)
          const taxRate = totalNet > 0 ? (totalTax / totalNet) * 100 : 19
          const roundedRate = Math.round(taxRate) === 7 ? 7 : Math.round(taxRate) === 19 ? 19 : Math.round(taxRate)
          lineItems.value = [{
            id: 1,
            description: result.line_items.map(item => item.description).filter(Boolean).join(', '),
            amount: totalGross.toFixed(2),
            skr03_account_id: undefined,
            tax_rule: (roundedRate > 0 ? 'tax_included' : 'no_tax') as TaxRule,
            tax_rate: roundedRate > 0 ? roundedRate.toFixed(2) : '0.00',
            rc_origin: 'eu' as RcOrigin,
            rc_with_vst: !isSmallBusiness.value,
            depreciation: '',
          }]
          lineItemCounter = 2
        }
      }
    }
    else if (totalGross > 0) {
      // Fallback: create single line item from total_gross
      const taxRate = totalTax > 0 && totalNet > 0 ? (totalTax / totalNet) * 100 : 19
      const roundedRate = Math.round(taxRate) === 7 ? 7 : Math.round(taxRate) === 19 ? 19 : Math.round(taxRate)
      firstItem.amount = totalGross.toFixed(2)
      firstItem.tax_rate = roundedRate > 0 ? roundedRate.toFixed(2) : '0.00'
      firstItem.tax_rule = roundedRate > 0 ? 'tax_included' : 'no_tax'
    }
  }

  // Phase 9: Auto-detect RC tax rule + SKR03 account from provider
  if (result.suggested_tax_rule && result.detected_provider) {
    const isDefaultTaxRule = lineItems.value.every(
      item => item.tax_rule === 'tax_included' || item.tax_rule === 'no_tax',
    )
    if (isDefaultTaxRule) {
      const suggestedRule = result.suggested_tax_rule
      // §13b SKR03: rc_eu_no_vst → 3165, rc_eu_with_vst → 3125
      const rcAccountId = suggestedRule.endsWith('_no_vst') ? 3165 : 3125
      for (const item of lineItems.value) {
        if (item.amount) {
          item.tax_rule = suggestedRule
          item.skr03_account_id = rcAccountId
          const parsed = parseRcTaxRule(suggestedRule)
          if (parsed) {
            item.rc_origin = parsed.origin
            item.rc_with_vst = parsed.withVst
          }
        }
      }
    }
  }

  // Phase 9: Show detected provider hint
  if (result.detected_provider) {
    detectedProvider.value = result.detected_provider
  }
}

function removeFile() {
  selectedFile.value = null
  if (filePreviewUrl.value) {
    URL.revokeObjectURL(filePreviewUrl.value)
    filePreviewUrl.value = null
  }
}

// Line item management
function addLineItem() {
  lineItems.value.push({
    id: lineItemCounter++,
    description: '',
    amount: '',
    skr03_account_id: undefined,
    tax_rule: 'tax_included',
    tax_rate: '19.00',
    depreciation: '',
    rc_origin: 'eu',
    rc_with_vst: !isSmallBusiness.value,
  })
}

function removeLineItem(id: number) {
  if (lineItems.value.length > 1) {
    lineItems.value = lineItems.value.filter(item => item.id !== id)
  }
}

// Form submission
const isSaving = ref(false)

async function handleSubmit(status: ReceiptStatus) {
  // Validation
  if (!receiptNumber.value.trim()) {
    toast.add({ title: 'Belegnummer erforderlich', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }
  if (!receiptDate.value) {
    toast.add({ title: 'Belegdatum erforderlich', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }
  if (!supplier.value.trim()) {
    toast.add({ title: receiptType.value === 'revenue' ? 'Kunde erforderlich' : 'Lieferant erforderlich', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }
  if (!deliveryDate.value) {
    toast.add({ title: 'Lieferdatum erforderlich', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }

  // Validate line items
  const validLineItems = lineItems.value.filter(item => item.amount && Number.parseFloat(item.amount) > 0)
  if (validLineItems.length === 0) {
    toast.add({ title: 'Mindestens eine Position mit Betrag erforderlich', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }
  if (status === 'final' && validLineItems.some(item => !item.skr03_account_id)) {
    toast.add({ title: 'SKR03-Konto für alle Positionen erforderlich', color: 'error', icon: 'i-lucide-circle-x' })
    return
  }

  isSaving.value = true

  try {
    // Build line items for API
    const apiLineItems: ReceiptLineItemCreate[] = validLineItems.map(item => ({
      description: item.description || '',
      amount: item.amount,
      skr03_account_id: item.skr03_account_id,
      tax_rule: item.tax_rule,
      tax_rate: item.tax_rate,
      depreciation: item.depreciation || undefined,
    }))

    // Build receipt data
    const receiptData = {
      receipt_number: receiptNumber.value,
      date: receiptDate.value,
      counterparty: supplier.value,
      type: receiptType.value,
      description: '',
      status,
      due_date: dueDate.value || undefined,
      payment_date: paymentDate.value || undefined,
      delivery_date: deliveryDate.value || undefined,
      delivery_period: deliveryPeriod.value || undefined,
      currency: currency.value,
      extraction_source: extractionSource.value || undefined,
      line_items: apiLineItems,
    }

    let receipt
    if (isEditMode.value) {
      // Update existing receipt — strip type/status (not allowed in PATCH, handled separately)
      const { type: _type, status: _status, ...updateData } = receiptData
      receipt = await updateReceipt(editId.value!, updateData)

      // Finalize if requested
      if (status === 'final') {
        receipt = await $fetch(`/api/v1/receipts/${editId.value}/finalize`, { method: 'POST' })
      }

      // Upload file if newly selected
      if (selectedFile.value) {
        await uploadFile(receipt.id, selectedFile.value)
      }

      toast.add({
        title: status === 'draft' ? 'Entwurf aktualisiert' : 'Beleg fertiggestellt',
        color: 'success',
        icon: 'i-lucide-check',
      })

      router.push(`/receipts/${editId.value}`)
    }
    else {
      // Create receipt with appropriate linking
      if (isBulkMode.value) {
        // Bulk mode: create and link to multiple transactions
        receipt = await createAndLinkBulkReceipt(receiptData, bulkTransactionIds.value)
      }
      else if (transactionId.value) {
        // Single transaction link
        receipt = await createAndLinkReceipt({ ...receiptData, transaction_id: transactionId.value })
      }
      else {
        // No linking
        receipt = await createReceipt(receiptData)
      }

      // Upload file if selected
      if (selectedFile.value) {
        await uploadFile(receipt.id, selectedFile.value)
      }

      const linkedCount = isBulkMode.value ? bulkTransactionIds.value.length : 0
      toast.add({
        title: status === 'draft'
          ? 'Entwurf gespeichert'
          : linkedCount > 0
            ? `Beleg erstellt und mit ${linkedCount} Transaktionen verknüpft`
            : 'Beleg erstellt',
        color: 'success',
        icon: 'i-lucide-check',
      })

      // Navigate back to transactions if coming from bulk mode or single transaction
      router.push(isBulkMode.value || transactionId.value ? '/transactions' : '/receipts')
    }
  }
  catch (error) {
    console.error('Failed to create receipt:', error)
    toast.add({ title: 'Fehler beim Erstellen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isSaving.value = false
  }
}

function handleDiscard() {
  router.push(isEditMode.value ? `/receipts/${editId.value}` : (isBulkMode.value || transactionId.value) ? '/transactions' : '/receipts')
}

// Account options for select (exclude NEUTRAL accounts — those are bank/clearing accounts, not for receipts)
const accountOptions = computed(() => {
  if (!accounts.value)
    return []
  return accounts.value
    .filter(a => a.category !== 'neutral')
    .map(a => ({
      label: `${a.id} - ${a.name}`,
      value: a.id,
    }))
})

const { formatCurrency, formatDate, amountColorClass } = useFormatters()
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader :title="isEditMode ? 'Beleg bearbeiten' : isBulkMode ? 'Sammelbeleg erstellen' : 'Beleg erstellen'" :back-to="isEditMode ? `/receipts/${editId}` : (isBulkMode || hasTransaction) ? '/transactions' : '/receipts'">
      <div class="flex items-center gap-2">
        <UButton
          :variant="receiptType === 'expense' ? 'solid' : 'outline'"
          :color="receiptType === 'expense' ? 'error' : 'neutral'"
          size="md"
          @click="receiptType = 'expense'"
        >
          <UIcon name="i-lucide-arrow-up-right" class="size-4 mr-1" />
          Ausgabe
        </UButton>
        <UButton
          :variant="receiptType === 'revenue' ? 'solid' : 'outline'"
          :color="receiptType === 'revenue' ? 'success' : 'neutral'"
          size="md"
          @click="receiptType = 'revenue'"
        >
          <UIcon name="i-lucide-arrow-down-left" class="size-4 mr-1" />
          Einnahme
        </UButton>
      </div>
    </PageHeader>

    <div class="p-6">
      <!-- Transaction context card (only when linked from transaction) -->
      <div v-if="transaction" class="mb-6 rounded-lg bg-stone-50 p-4 dark:bg-stone-900/50">
        <div class="flex items-center gap-2 text-sm text-stone-500">
          <UIcon name="i-lucide-credit-card" class="size-4" />
          <span>Transaktion verknüpfen mit:</span>
        </div>
        <div class="mt-2 flex items-center justify-between">
          <div>
            <p class="font-medium">
              {{ transaction.counterparty }}
            </p>
            <p class="text-sm text-stone-500">
              {{ formatDate(transaction.date) }} · {{ transaction.description }}
            </p>
          </div>
          <p
            class="text-lg font-bold font-tabular"
            :class="amountColorClass(transaction.amount)"
          >
            {{ formatCurrency(transaction.amount) }}
          </p>
        </div>
      </div>

      <!-- Bulk linking context card (when creating from selected transactions) -->
      <div v-if="isBulkMode" class="mb-6 rounded-lg bg-primary-50 border border-primary-200 p-4 dark:bg-primary-950/30 dark:border-primary-800">
        <div class="flex items-center gap-2 text-sm text-primary-700 dark:text-primary-300">
          <UIcon name="i-lucide-list-checks" class="size-4" />
          <span>Sammelbeleg für mehrere Transaktionen</span>
        </div>
        <div class="mt-2 flex items-center justify-between">
          <div>
            <p class="font-medium text-primary-900 dark:text-primary-100">
              {{ bulkTransactionIds.length }} Transaktionen ausgewählt
            </p>
            <p class="text-sm text-primary-600 dark:text-primary-400">
              Der Beleg wird nach dem Speichern automatisch verknüpft.
            </p>
          </div>
          <p
            v-if="bulkTransactionsTotal > 0"
            class="text-lg font-bold font-tabular text-primary-700 dark:text-primary-300"
          >
            {{ formatCurrency(bulkTransactionsTotal) }}
          </p>
        </div>
      </div>

      <!-- Split layout -->
      <div class="grid gap-6 lg:grid-cols-2">
        <!-- Left: File upload + preview -->
        <ReceiptDocumentViewer
          :file-url="filePreviewUrl"
          :mime-type="selectedFile?.type ?? existingFileMimeType"
          :file-name="selectedFile?.name ?? existingFileName"
          :file-size="selectedFile?.size"
          can-upload
          :can-remove="!!selectedFile"
          @file-select="handleFileSelected"
          @remove="removeFile"
        />

        <!-- Right: Form -->
        <div class="relative space-y-6">
          <!-- Extraction overlay -->
          <div v-if="extracting" class="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-white/80 dark:bg-stone-900/80">
            <div class="flex flex-col items-center gap-3">
              <UIcon name="i-lucide-loader-2" class="size-8 animate-spin text-primary" />
              <p class="text-sm font-medium text-stone-600 dark:text-stone-400">
                Daten werden erkannt...
              </p>
            </div>
          </div>

          <!-- Extraction error -->
          <div v-if="extractionError" class="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950/30">
            <UIcon name="i-lucide-circle-x" class="size-5 text-red-500 shrink-0" />
            <p class="flex-1 text-sm text-red-700 dark:text-red-300">
              {{ extractionError }}
            </p>
            <UButton
              v-if="selectedFile"
              variant="outline"
              color="error"
              size="xs"
              @click="extractFromFile(selectedFile!).then(r => r && applyExtractionResult(r))"
            >
              Erneut versuchen
            </UButton>
          </div>

          <!-- Extraction source badge -->
          <div v-if="extractionSource" class="flex items-center gap-2">
            <UBadge v-if="extractionWarnings.length === 0" color="primary" variant="soft" size="sm">
              <UIcon name="i-lucide-sparkles" class="size-3.5 mr-1" />
              Erkannt via {{ extractionSource === 'zugferd' ? 'ZUGFeRD' : extractionSource }}
            </UBadge>
            <UTooltip v-else :text="extractionWarnings.join('\n')">
              <UBadge color="warning" variant="soft" size="sm">
                <UIcon name="i-lucide-triangle-alert" class="size-3.5 mr-1" />
                Erkannt via {{ extractionSource === 'zugferd' ? 'ZUGFeRD' : extractionSource }} (Daten prüfen)
              </UBadge>
            </UTooltip>
          </div>

          <!-- Detected provider hint (Phase 9: EU Provider Detection) -->
          <UAlert
            v-if="detectedProvider"
            color="info"
            variant="soft"
            icon="i-lucide-scan-search"
            :title="`${detectedProvider}-Rechnung erkannt`"
            description="Reverse Charge wurde automatisch vorgeschlagen. Bitte prüfe die Steuerregel."
          />

          <!-- Details section -->
          <div class="space-y-4">
            <div class="grid gap-4 sm:grid-cols-2">
              <UFormField label="Belegnummer" required>
                <UInput v-model="receiptNumber" placeholder="RE-2024-001" />
              </UFormField>

              <UFormField label="Belegdatum" required>
                <UInput v-model="receiptDate" type="date" />
              </UFormField>
            </div>

            <UFormField :label="receiptType === 'revenue' ? 'Kunde' : 'Lieferant'" required>
              <UInput v-model="supplier" placeholder="Firmenname" />
            </UFormField>

            <div class="grid gap-4 sm:grid-cols-2">
              <UFormField label="Lieferdatum" required>
                <UInput v-model="deliveryDate" type="date" />
              </UFormField>

              <UFormField label="Zeitraum">
                <UInput v-model="deliveryPeriod" placeholder="z.B. Januar 2024" />
              </UFormField>
            </div>

            <div class="grid gap-4 sm:grid-cols-2">
              <UFormField label="Fälligkeit">
                <UInput v-model="dueDate" type="date" />
              </UFormField>

              <UFormField label="Bezahldatum">
                <UInput v-model="paymentDate" type="date" />
              </UFormField>
            </div>
          </div>

          <!-- Buchhaltung section -->
          <div class="space-y-4">
            <!-- Line items -->
            <div class="space-y-4">
              <div
                v-for="(item, index) in lineItems"
                :key="item.id"
                class="rounded-lg border border-stone-200 p-4 dark:border-stone-700"
              >
                <div class="flex items-start justify-between mb-3">
                  <span class="text-xs font-medium text-stone-500">Position {{ index + 1 }}</span>
                  <UButton
                    v-if="lineItems.length > 1"
                    icon="i-lucide-trash-2"
                    color="error"
                    variant="ghost"
                    size="xs"
                    @click="removeLineItem(item.id)"
                  />
                </div>

                <div class="space-y-3">
                  <UFormField label="Kategorie (SKR03)">
                    <USelectMenu
                      v-model="item.skr03_account_id"
                      :items="accountOptions"
                      value-key="value"
                      placeholder="Konto auswählen"
                      size="md"
                      class="min-w-40"
                      @update:model-value="userHasSelectedAccount = true"
                    />
                    <p v-if="index === 0 && suggestedAccountId && item.skr03_account_id === suggestedAccountId && !userHasSelectedAccount" class="mt-1 text-xs text-stone-400">
                      Vorgeschlagen basierend auf bisherigen Belegen
                    </p>
                  </UFormField>

                  <div class="grid gap-3 sm:grid-cols-2">
                    <UFormField label="Betrag" required>
                      <div class="flex gap-2">
                        <UInput
                          v-model="item.amount"
                          type="number"
                          step="0.01"
                          min="0"
                          placeholder="0,00"
                          class="flex-1"
                        />
                        <USelect
                          v-model="currency"
                          :items="currencyOptions"
                          class="w-24"
                          size="md"
                        />
                      </div>
                    </UFormField>

                    <UFormField label="Umsatzsteuer">
                      <div class="flex gap-2">
                        <USelect
                          :model-value="getTaxType(item.tax_rule)"
                          :items="taxTypeOptions"
                          class="flex-1"
                          @update:model-value="handleTaxTypeChange(item, $event as TaxType)"
                        />
                        <USelect
                          v-if="!isReverseCharge(item.tax_rule)"
                          v-model="item.tax_rate"
                          :items="taxRateOptions"
                          class="w-20"
                        />
                      </div>
                    </UFormField>
                  </div>

                  <!-- Reverse Charge Details (SevDesk pattern) -->
                  <div v-if="isReverseCharge(item.tax_rule)" class="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/30">
                    <div class="flex items-center gap-2 mb-3">
                      <UIcon name="i-lucide-alert-triangle" class="size-4 text-amber-600" />
                      <span class="text-sm font-medium text-amber-800 dark:text-amber-200">Reverse Charge (§13b UStG)</span>
                    </div>
                    <div class="grid gap-3 sm:grid-cols-2">
                      <UFormField label="Herkunft">
                        <USelect
                          :model-value="item.rc_origin"
                          :items="rcOriginOptions"
                          @update:model-value="handleRcOriginChange(item, $event as RcOrigin)"
                        />
                      </UFormField>
                      <UFormField label="Vorsteuerabzug">
                        <div class="flex items-center gap-2 h-[38px]">
                          <USwitch
                            :model-value="item.rc_with_vst"
                            :disabled="isSmallBusiness"
                            @update:model-value="handleRcVstChange(item, $event)"
                          />
                          <span class="text-sm">{{ item.rc_with_vst ? 'Mit VSt' : 'Ohne VSt' }}</span>
                        </div>
                      </UFormField>
                    </div>
                    <p v-if="isSmallBusiness" class="mt-2 text-xs text-amber-700 dark:text-amber-300">
                      Als Kleinunternehmer ist kein Vorsteuerabzug möglich. Die §13b-USt ist eine echte Kostenbelastung.
                    </p>
                    <p class="mt-2 text-xs text-amber-700 dark:text-amber-300">
                      USt-Schuld (19%): {{ formatCurrency(Number.parseFloat(item.amount || '0') * 0.19) }}
                    </p>
                  </div>

                  <UFormField label="Beschreibung">
                    <UInput v-model="item.description" placeholder="Optional" />
                  </UFormField>

                  <!-- Abschreibung (hidden for now)
                  <UFormField label="Abschreibung">
                    <UInput v-model="item.depreciation" placeholder="z.B. GWG, AfA 5 Jahre" />
                  </UFormField>
                  -->
                </div>
              </div>
            </div>

            <UButton
              icon="i-lucide-plus"
              variant="outline"
              color="neutral"
              size="md"
              @click="addLineItem"
            >
              Position hinzufügen
            </UButton>

            <!-- Summary: Netto / USt / Brutto -->
            <div class="rounded-lg bg-stone-100 p-4 dark:bg-stone-800">
              <div class="space-y-2 text-sm">
                <div class="flex justify-between">
                  <span class="text-stone-500">Netto</span>
                  <span class="font-tabular">{{ formatCurrency(totalNetto) }}</span>
                </div>
                <div
                  v-for="tax in taxBreakdown"
                  :key="tax.rate"
                  class="flex justify-between text-stone-500"
                >
                  <span>USt {{ tax.rate }}</span>
                  <span class="font-tabular">{{ formatCurrency(tax.amount) }}</span>
                </div>
                <div class="flex justify-between border-t border-stone-200 pt-2 dark:border-stone-700">
                  <span class="font-medium">Gesamt Brutto</span>
                  <span class="text-lg font-bold font-tabular">{{ formatCurrency(totalBrutto) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Actions -->
          <div class="flex items-center justify-between border-t border-stone-200 pt-6 dark:border-stone-700">
            <UButton
              variant="outline"
              color="neutral"
              @click="handleDiscard"
            >
              Verwerfen
            </UButton>

            <div class="flex items-center gap-2">
              <UButton
                variant="outline"
                color="neutral"
                :loading="isSaving"
                @click="handleSubmit('draft')"
              >
                Als Entwurf speichern
              </UButton>
              <UButton
                color="primary"
                :loading="isSaving"
                @click="handleSubmit('final')"
              >
                Fertigstellen
              </UButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
