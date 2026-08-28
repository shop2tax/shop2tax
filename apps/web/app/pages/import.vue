<script setup lang="ts">
definePageMeta({
  middleware: ['auth'],
})

const toast = useToast()
const { hasAnyProvider, primaryProvider } = useOmsProviders()

const omsProviderName = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

// Tab navigation
const tabs = computed(() => {
  const baseTabs = [
    { label: 'Bank Import', value: 'bank', icon: 'i-lucide-landmark' },
    { label: 'Marktplatz Import', value: 'marketplace', icon: 'i-lucide-store' },
    { label: 'PayPal Sync', value: 'paypal', icon: 'i-lucide-refresh-cw' },
  ]
  if (hasAnyProvider.value)
    baseTabs.push({ label: `${omsProviderName.value} Sync`, value: 'oms', icon: 'i-lucide-package' })
  return baseTabs
})
const tabValues = computed(() => tabs.value.map(t => t.value))
const activeTab = useQueryTab(tabValues, 'bank')

// --- PayPal Sync State ---
const { data: paypalLastSync, refresh: refreshPaypalLastSync } = usePaypalLastSync()
const paypalHistoryFilters = ref({ page: 1, page_size: 10 })
const { data: paypalSyncHistory, refresh: refreshPaypalHistory, status: paypalHistoryStatus } = usePaypalSyncHistory(paypalHistoryFilters)
const { triggerSync: triggerPaypalSync } = usePaypalMutations()

const paypalStartDate = ref('')
const paypalEndDate = ref('')
const isPaypalSyncing = ref(false)
const paypalSyncResult = ref<{ importedCount: number, skippedCount: number, feeCount: number, errors: string[] } | null>(null)

// Pre-fill dates on client only to avoid SSR hydration mismatch
onMounted(() => {
  paypalEndDate.value = todayIso()
  if (paypalLastSync.value && !paypalStartDate.value)
    paypalStartDate.value = nextDayIso(paypalLastSync.value.end_date)
})

// Also watch for late-arriving data (fetch resolves after mount)
watch(paypalLastSync, (value) => {
  if (value && !paypalStartDate.value)
    paypalStartDate.value = nextDayIso(value.end_date)
})

async function handlePaypalSync(startDate: string | undefined, endDate: string | undefined) {
  if (!startDate || !endDate)
    return

  isPaypalSyncing.value = true
  paypalSyncResult.value = null

  try {
    const result = await triggerPaypalSync({ start_date: startDate, end_date: endDate })
    paypalSyncResult.value = {
      importedCount: result.imported_count,
      skippedCount: result.skipped_count,
      feeCount: result.fee_count,
      errors: result.errors,
    }
    toast.add({ title: `${result.imported_count} Transaktionen importiert`, color: 'success', icon: 'i-lucide-check' })
    refreshPaypalLastSync()
    refreshPaypalHistory()
  }
  catch {
    toast.add({ title: 'Fehler beim PayPal-Sync', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isPaypalSyncing.value = false
  }
}

// --- OMS Sync State ---
const { data: omsLastSync, refresh: refreshOmsLastSync } = useOmsLastSync()
const omsHistoryFilters = ref({ page: 1, page_size: 10 })
const { data: omsSyncHistory, refresh: refreshOmsHistory, status: omsHistoryStatus } = useOmsSyncHistory(omsHistoryFilters)
const { triggerSync: triggerOmsSync } = useOmsMutations()

const omsStartDate = ref<string | undefined>(undefined)
const omsEndDate = ref('')
const isOmsSyncing = ref(false)
const omsSyncResult = ref<{ importedCount: number, skippedCount: number, pdfCount: number, pdfErrorCount: number, linkedCount: number, errors: string[] } | null>(null)
const omsSyncProgress = ref<{ processed: number, total: number, imported: number, errors: number } | null>(null)

// Pre-fill dates on client only to avoid SSR hydration mismatch
onMounted(() => {
  omsEndDate.value = todayIso()
  if (omsLastSync.value && !omsStartDate.value)
    omsStartDate.value = nextDayIso(omsLastSync.value.end_date)
})

// Also watch for late-arriving data (fetch resolves after mount)
watch(omsLastSync, (value) => {
  if (value && !omsStartDate.value)
    omsStartDate.value = nextDayIso(value.end_date)
})

async function handleOmsSync(startDate: string | undefined, endDate: string | undefined) {
  isOmsSyncing.value = true
  omsSyncResult.value = null
  omsSyncProgress.value = null

  try {
    const result = await triggerOmsSync(startDate, endDate, (progress) => {
      omsSyncProgress.value = {
        processed: progress.processed,
        total: progress.total,
        imported: progress.imported,
        errors: progress.errors,
      }
    })
    omsSyncResult.value = {
      importedCount: result.imported_count,
      skippedCount: result.skipped_count,
      pdfCount: result.pdf_count,
      pdfErrorCount: result.pdf_error_count,
      linkedCount: result.linked_count,
      errors: result.errors,
    }
    if (result.errors.length > 0) {
      toast.add({
        title: `${result.imported_count} importiert, ${result.errors.length} Fehler`,
        description: result.errors.slice(0, 3).join('\n') + (result.errors.length > 3 ? `\n...und ${result.errors.length - 3} weitere` : ''),
        color: 'warning',
        icon: 'i-lucide-alert-triangle',
      })
    }
    else {
      toast.add({
        title: `${result.imported_count} Belege importiert, ${result.skipped_count} übersprungen`,
        color: 'success',
        icon: 'i-lucide-check',
      })
    }
    refreshOmsLastSync()
    refreshOmsHistory()
  }
  catch (error) {
    const message = error instanceof Error ? error.message : 'Fehler beim Synchronisieren'
    // Handle 409 Conflict (sync already in progress)
    if (message.includes('409') || message.toLowerCase().includes('already in progress')) {
      toast.add({ title: 'Sync läuft bereits', description: 'Bitte warten Sie, bis der aktuelle Sync abgeschlossen ist.', color: 'warning', icon: 'i-lucide-clock' })
    }
    else {
      toast.add({ title: 'Fehler beim Synchronisieren', description: message, color: 'error', icon: 'i-lucide-circle-x' })
    }
  }
  finally {
    isOmsSyncing.value = false
    omsSyncProgress.value = null
  }
}
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader title="Import" />

    <div class="p-6 space-y-6">
      <!-- 🗂️ Tab navigation -->
      <TabNav v-model="activeTab" :tabs="tabs" />

      <!-- ===== Bank Import Tab (Generic CSV with column mapping) ===== -->
      <div v-show="activeTab === 'bank'">
        <ImportBankImportWizard />
      </div>

      <!-- ===== Marketplace Import Tab ===== -->
      <div v-show="activeTab === 'marketplace'">
        <ImportMarketplaceImportWizard />
      </div>

      <!-- ===== PayPal Sync Tab ===== -->
      <div v-show="activeTab === 'paypal'" class="space-y-6">
        <SyncDateRangeForm
          v-model:start-date="paypalStartDate"
          v-model:end-date="paypalEndDate"
          title="PayPal-Synchronisierung"
          description="Transaktionen direkt von der PayPal-API abrufen und importieren."
          :last-sync-date="paypalLastSync?.end_date"
          :start-date-required="true"
          :end-date-required="true"
          :loading="isPaypalSyncing"
          :result="paypalSyncResult"
          result-link="/transactions"
          result-link-label="Zu Buchungen"
          @sync="handlePaypalSync"
        />

        <SyncHistoryTable
          v-model:page="paypalHistoryFilters.page"
          :data="paypalSyncHistory?.items || []"
          :loading="paypalHistoryStatus === 'pending'"
          :total="paypalSyncHistory?.total"
          :page-size="paypalHistoryFilters.page_size"
          extra-column-key="fee_count"
          extra-column-label="Gebühren"
        />
      </div>

      <!-- ===== OMS Sync Tab ===== -->
      <div v-if="hasAnyProvider" v-show="activeTab === 'oms'" class="space-y-6">
        <SyncDateRangeForm
          v-model:start-date="omsStartDate"
          v-model:end-date="omsEndDate"
          :title="`${omsProviderName}-Synchronisierung`"
          :description="`Bestellungen von ${omsProviderName} als Belege importieren.`"
          :last-sync-date="omsLastSync?.end_date"
          :start-date-required="false"
          :loading="isOmsSyncing"
          :progress="omsSyncProgress"
          :result="omsSyncResult"
          result-link="/receipts"
          result-link-label="Zu Belegen"
          @sync="handleOmsSync"
        />

        <SyncHistoryTable
          v-model:page="omsHistoryFilters.page"
          :data="omsSyncHistory?.items || []"
          :loading="omsHistoryStatus === 'pending'"
          :total="omsSyncHistory?.total"
          :page-size="omsHistoryFilters.page_size"
          extra-column-key="skipped_count"
          extra-column-label="Übersprungen"
        />
      </div>
    </div>
  </div>
</template>
