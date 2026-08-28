<script setup lang="ts">
/**
 * SourcesManager - Manage transaction sources (bank + marketplace).
 *
 * Features:
 * - List all sources with type badge
 * - Add/edit sources via shared modal
 * - Delete source (only if no transactions reference it)
 * - System marketplace sources are read-only
 */
import type { SourceType, TransactionSourceConfigResponse } from '~/types/api'

const toast = useToast()
const { data: sources, refresh, status } = useSources()
const { create, update, remove } = useSourceMutations()
const { data: omsSettings } = useOmsSettings()
const { primaryProvider } = useOmsProviders()

const omsProviderName = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

const sourceTypeOptions = [
  { value: 'csv_mapping', label: 'Bank (CSV)' },
  { value: 'marketplace_mapping', label: 'Marktplatz (CSV)' },
  { value: 'api_sync', label: 'API-Sync' },
]

const parserOptions = [
  { value: '', label: 'Kein Parser (manuelle Zuordnung)' },
  { value: 'etsy', label: 'Etsy' },
  { value: 'amazon', label: 'Amazon' },
  { value: 'shopify', label: 'Shopify' },
]

// Find linked OMS store for a marketplace source
function linkedOmsStore(sourceId: string) {
  return omsSettings.value?.stores.find(s => s.source_config_id === sourceId) ?? null
}

// --- Add/Edit Source (shared modal) ---
const showSourceModal = ref(false)
const sourceToEdit = ref<TransactionSourceConfigResponse | null>(null)
const sourceName = ref('')
const sourceType = ref<SourceType>('csv_mapping')
const sourceCheckAccountId = ref<number | undefined>(undefined)
const sourceParser = ref('')
const sourceHasUstId = ref(true)
const isSaving = ref(false)

const isEditing = computed(() => sourceToEdit.value !== null)
const isMarketplace = computed(() => sourceType.value === 'marketplace_mapping')

function openAddSource() {
  sourceToEdit.value = null
  sourceName.value = ''
  sourceType.value = 'csv_mapping'
  sourceCheckAccountId.value = undefined // Auto-assigned by API
  sourceParser.value = ''
  sourceHasUstId.value = true
  showSourceModal.value = true
}

function openEditSource(source: TransactionSourceConfigResponse) {
  sourceToEdit.value = source
  sourceName.value = source.name
  sourceType.value = source.type
  sourceCheckAccountId.value = source.check_account_id
  sourceParser.value = source.source_config?.parser ?? ''
  sourceHasUstId.value = source.source_config?.has_ust_id_registered ?? true
  showSourceModal.value = true
}

async function handleSaveSource() {
  if (!sourceName.value.trim())
    return

  isSaving.value = true
  try {
    const sourceConfig = isMarketplace.value
      ? {
          parser: sourceParser.value || null,
          has_ust_id_registered: sourceHasUstId.value,
        }
      : undefined

    if (isEditing.value) {
      await update(sourceToEdit.value!.id, {
        name: sourceName.value.trim(),
        type: sourceType.value,
        check_account_id: sourceCheckAccountId.value,
        source_config: sourceConfig,
      })
      toast.add({ title: 'Quelle aktualisiert', color: 'success', icon: 'i-lucide-check' })
    }
    else {
      await create({
        name: sourceName.value.trim(),
        type: sourceType.value,
        check_account_id: sourceCheckAccountId.value,
        source_config: sourceConfig,
      })
      toast.add({ title: 'Quelle hinzugefügt', color: 'success', icon: 'i-lucide-check' })
    }
    showSourceModal.value = false
    sourceToEdit.value = null
    refresh()
  }
  catch {
    toast.add({ title: isEditing.value ? 'Fehler beim Aktualisieren' : 'Fehler beim Hinzufügen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isSaving.value = false
  }
}

// --- Delete Source ---
const showDeleteSource = ref(false)
const sourceToDelete = ref<TransactionSourceConfigResponse | null>(null)
const isDeletingSource = ref(false)

function openDeleteSource(source: TransactionSourceConfigResponse) {
  sourceToDelete.value = source
  showDeleteSource.value = true
}

async function confirmDeleteSource() {
  if (!sourceToDelete.value)
    return

  isDeletingSource.value = true
  try {
    await remove(sourceToDelete.value.id)
    toast.add({ title: 'Quelle gelöscht', color: 'success', icon: 'i-lucide-check' })
    showDeleteSource.value = false
    sourceToDelete.value = null
    refresh()
  }
  catch (error: unknown) {
    const errorMessage = error instanceof Error ? error.message : String(error)
    if (errorMessage.includes('transactions')) {
      toast.add({
        title: 'Löschen nicht möglich',
        description: 'Es existieren noch Transaktionen mit dieser Quelle.',
        color: 'error',
        icon: 'i-lucide-circle-x',
      })
    }
    else {
      toast.add({ title: 'Fehler beim Löschen', color: 'error', icon: 'i-lucide-circle-x' })
    }
  }
  finally {
    isDeletingSource.value = false
  }
}

// --- Table Columns ---
const columns = computed(() => [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'type', header: 'Typ' },
  { accessorKey: 'oms', header: omsProviderName.value },
  { accessorKey: 'check_account_id', header: 'Konto' },
  { accessorKey: 'import_method', header: 'Import' },
  { accessorKey: 'actions', header: '' },
])
</script>

<template>
  <SectionCard title="Quellen" description="Bank- und Marktplatz-Quellen für den Import verwalten.">
    <template #header>
      <UButton
        size="md"
        color="primary"
        icon="i-lucide-plus"
        @click="openAddSource"
      >
        Quelle hinzufügen
      </UButton>
    </template>

    <UTable
      :data="sources || []"
      :columns="columns"
      :loading="status === 'pending'"
      :empty-state="{ icon: 'i-lucide-landmark', label: 'Keine Quellen vorhanden' }"
    >
      <template #type-cell="{ row }">
        <UBadge
          color="neutral"
          variant="soft"
          size="sm"
        >
          {{ row.original.type === 'csv_mapping' ? 'Bank' : row.original.type === 'api_sync' ? 'API' : 'Marktplatz' }}
        </UBadge>
      </template>

      <template #oms-cell="{ row }">
        <template v-if="row.original.type === 'marketplace_mapping'">
          <div v-if="linkedOmsStore(row.original.id)" class="flex items-center gap-1.5 text-sm text-emerald-600">
            <UIcon name="i-lucide-link" class="size-3.5" />
            {{ linkedOmsStore(row.original.id)!.label }}
          </div>
          <div v-else class="flex items-center gap-1.5 text-sm text-amber-500">
            <UIcon name="i-lucide-alert-triangle" class="size-3.5" />
            <span>Nicht verknüpft</span>
          </div>
        </template>
        <span v-else class="text-stone-300">—</span>
      </template>

      <template #check_account_id-cell="{ row }">
        <span class="font-mono text-sm">{{ row.original.check_account_id }}</span>
      </template>

      <template #import_method-cell="{ row }">
        <UBadge
          color="neutral"
          variant="soft"
          size="sm"
        >
          {{ row.original.import_method }}
        </UBadge>
      </template>

      <template #actions-cell="{ row }">
        <div v-if="!row.original.is_system || row.original.type === 'csv_mapping'" class="flex items-center justify-end gap-1">
          <UButton
            icon="i-lucide-pencil"
            color="neutral"
            variant="ghost"
            size="md"
            @click="openEditSource(row.original)"
          />
          <UButton
            icon="i-lucide-trash-2"
            color="error"
            variant="ghost"
            size="md"
            @click="openDeleteSource(row.original)"
          />
        </div>
        <span v-else class="text-xs text-stone-400">System</span>
      </template>
    </UTable>
  </SectionCard>

  <!-- Add/Edit Source Modal -->
  <UModal v-model:open="showSourceModal">
    <template #content>
      <UCard>
        <template #header>
          <h3 class="font-display text-lg font-semibold text-stone-700 dark:text-stone-300">
            {{ isEditing ? 'Quelle bearbeiten' : 'Quelle hinzufügen' }}
          </h3>
        </template>

        <div class="flex flex-col gap-4">
          <UFormField label="Name">
            <UInput
              v-model="sourceName"
              placeholder="z.B. DKB, Sparkasse, Stripe"
              class="w-full"
              @keydown.enter="handleSaveSource"
            />
          </UFormField>

          <UFormField label="Typ">
            <USelect
              v-model="sourceType"
              :items="sourceTypeOptions"
              class="w-full"
            />
          </UFormField>

          <UFormField label="Buchungskonto">
            <UInput
              v-model.number="sourceCheckAccountId"
              type="number"
              :placeholder="isEditing ? '' : 'Auto'"
              class="w-full"
            />
            <p class="mt-1 text-xs text-stone-400">
              SKR03: 1200–1288 (Bank) oder 1590 (Durchlaufende Posten). Leer = automatisch.
            </p>
          </UFormField>

          <!-- Marketplace-specific: Parser + USt-ID -->
          <template v-if="isMarketplace">
            <UFormField label="Parser">
              <USelect
                v-model="sourceParser"
                :items="parserOptions"
                class="w-full"
              />
              <p class="mt-1 text-xs text-stone-400">
                Parser erkennt Transaktionstypen automatisch (Fees, Sales, Refunds, etc.)
              </p>
            </UFormField>

            <UCheckbox
              v-model="sourceHasUstId"
              label="USt-ID bei diesem Marktplatz hinterlegt"
            />
            <p v-if="sourceParser" class="-mt-2 text-xs text-stone-400">
              Beeinflusst die Reverse-Charge-Behandlung (§13b): {{ sourceHasUstId ? 'RC-USt wird berechnet' : 'Kein RC (ohne USt-ID)' }}
            </p>
          </template>
        </div>

        <template #footer>
          <div class="flex justify-end gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              @click="showSourceModal = false"
            >
              Abbrechen
            </UButton>
            <UButton
              color="primary"
              :loading="isSaving"
              :disabled="!sourceName.trim()"
              @click="handleSaveSource"
            >
              {{ isEditing ? 'Speichern' : 'Hinzufügen' }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>

  <!-- Delete Source Confirmation Modal -->
  <UModal v-model:open="showDeleteSource">
    <template #content>
      <UCard>
        <template #header>
          <h3 class="font-display text-lg font-semibold text-stone-700 dark:text-stone-300">
            Quelle löschen
          </h3>
        </template>

        <p>
          Quelle "{{ sourceToDelete?.name }}" wirklich löschen?
        </p>
        <p class="mt-2 text-sm text-stone-500">
          Dies ist nur möglich, wenn keine Transaktionen diese Quelle verwenden.
        </p>

        <template #footer>
          <div class="flex justify-end gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              @click="showDeleteSource = false"
            >
              Abbrechen
            </UButton>
            <UButton
              color="error"
              :loading="isDeletingSource"
              @click="confirmDeleteSource"
            >
              Löschen
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
