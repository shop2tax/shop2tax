<script setup lang="ts">
import type { OmsStoreCreate, OmsStoreResponse } from '~/types/api'

const toast = useToast()
const { data: omsSettings, refresh } = useOmsSettings()
const { createStore, deleteStore, updateStore } = useOmsMutations()
const { data: allSources } = useSources()
const { primaryProvider } = useOmsProviders()

const providerDisplayName = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

const marketplaceSources = computed(() =>
  (allSources.value || []).filter(s => s.type === 'marketplace_mapping'),
)

// New store form
const newStore = ref<OmsStoreCreate>({
  store_type: 'etsy',
  label: '',
  external_shop_id: 0,
})
const isAddingStore = ref(false)
const showAddStore = ref(false)

const storeTypeOptions = [
  { label: 'Etsy', value: 'etsy' },
  { label: 'Amazon', value: 'amazon' },
  { label: 'Shopify', value: 'shopify' },
  { label: 'Sonstige', value: 'other' },
]

const matchStrategyOptions = [
  { label: 'Bestellnummer', value: 'order_number' },
  { label: 'E-Mail', value: 'email' },
]

// --- Inline updates for source link + match strategy ---
async function handleUpdateSourceLink(store: OmsStoreResponse, sourceConfigId: string | undefined) {
  try {
    await updateStore(store.id, { source_config_id: sourceConfigId || null })
    toast.add({ title: 'Quelle verknüpft', color: 'success', icon: 'i-lucide-check' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Verknüpfen', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

async function handleUpdateMatchStrategy(store: OmsStoreResponse, strategy: string) {
  try {
    await updateStore(store.id, { match_strategy: strategy })
    toast.add({ title: 'Strategie aktualisiert', color: 'success', icon: 'i-lucide-check' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Aktualisieren', color: 'error', icon: 'i-lucide-circle-x' })
  }
}

async function handleAddStore() {
  if (!newStore.value.label || !newStore.value.external_shop_id)
    return

  isAddingStore.value = true
  try {
    await createStore(newStore.value)
    toast.add({ title: 'Shop hinzugefügt', color: 'success', icon: 'i-lucide-check' })
    showAddStore.value = false
    newStore.value = { store_type: 'etsy', label: '', external_shop_id: 0 }
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Hinzufügen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isAddingStore.value = false
  }
}

// Delete store
const storeToDelete = ref<OmsStoreResponse | null>(null)
const showDeleteStore = ref(false)
const isDeletingStore = ref(false)

function openDeleteStore(store: OmsStoreResponse) {
  storeToDelete.value = store
  showDeleteStore.value = true
}

async function confirmDeleteStore() {
  if (!storeToDelete.value)
    return
  isDeletingStore.value = true
  try {
    await deleteStore(storeToDelete.value.id)
    toast.add({ title: 'Shop gelöscht', color: 'success', icon: 'i-lucide-check' })
    showDeleteStore.value = false
    storeToDelete.value = null
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Löschen', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isDeletingStore.value = false
  }
}
</script>

<template>
  <SectionCard title="Shop-Zuordnungen" :description="`Verknüpfe deine Marketplace-Shops mit ${providerDisplayName} Shop-IDs.`">
    <template #header>
      <UButton
        size="md"
        color="primary"
        icon="i-lucide-plus"
        @click="showAddStore = true"
      >
        Shop hinzufügen
      </UButton>
    </template>

    <UTable
      :data="omsSettings?.stores || []"
      :columns="[
        { accessorKey: 'store_type', header: 'Typ' },
        { accessorKey: 'label', header: 'Name' },
        { accessorKey: 'external_shop_id', header: `${providerDisplayName} Shop-ID` },
        { accessorKey: 'source_config_id', header: 'Verknüpfte Marktplatz-Quelle' },
        { accessorKey: 'match_strategy', header: 'Match-Strategie' },
        { accessorKey: 'actions', header: '' },
      ]"
      :empty-state="{ icon: 'i-lucide-store', label: 'Keine Shops konfiguriert' }"
    >
      <template #store_type-cell="{ row }">
        <UBadge color="neutral" variant="soft">
          {{ row.original.store_type.toUpperCase() }}
        </UBadge>
      </template>

      <template #external_shop_id-cell="{ row }">
        <span class="font-tabular text-sm">{{ row.original.external_shop_id }}</span>
      </template>

      <template #source_config_id-cell="{ row }">
        <USelect
          :model-value="row.original.source_config_id || undefined"
          :items="marketplaceSources.map(s => ({ value: s.id, label: s.name }))"
          placeholder="Keine Quelle"
          size="md"
          class="min-w-40"
          @update:model-value="(value: string) => { handleUpdateSourceLink(row.original, value) }"
        />
      </template>

      <template #match_strategy-cell="{ row }">
        <USelect
          :model-value="row.original.match_strategy"
          :items="matchStrategyOptions"
          size="md"
          class="min-w-36"
          @update:model-value="(value: string) => { handleUpdateMatchStrategy(row.original, value) }"
        />
      </template>

      <template #actions-cell="{ row }">
        <UButton
          icon="i-lucide-trash-2"
          color="error"
          variant="ghost"
          size="md"
          @click="openDeleteStore(row.original)"
        />
      </template>
    </UTable>
  </SectionCard>

  <!-- Add Store Modal -->
  <UModal v-model:open="showAddStore">
    <template #content>
      <UCard>
        <template #header>
          <h3 class="font-display text-lg font-semibold text-stone-700 dark:text-stone-300">
            Shop hinzufügen
          </h3>
        </template>

        <div class="space-y-4">
          <UFormField label="Shop-Typ">
            <USelect
              v-model="newStore.store_type"
              :items="storeTypeOptions"
              size="md"
              class="min-w-40"
            />
          </UFormField>

          <UFormField label="Name">
            <UInput
              v-model="newStore.label"
              placeholder="z.B. Mein Etsy Shop"
            />
          </UFormField>

          <UFormField :label="`${providerDisplayName} Shop-ID`">
            <UInput
              v-model="newStore.external_shop_id"
              type="number"
              placeholder="123456"
            />
          </UFormField>

          <UFormField label="Verknüpfte Marktplatz-Quelle">
            <USelect
              :model-value="newStore.source_config_id ?? undefined"
              :items="marketplaceSources.map(s => ({ value: s.id, label: s.name }))"
              placeholder="Keine Quelle"
              size="md"
              class="min-w-40"
              @update:model-value="(value: string) => { newStore.source_config_id = value }"
            />
          </UFormField>

          <UFormField label="Match-Strategie">
            <USelect
              v-model="newStore.match_strategy"
              :items="matchStrategyOptions"
              size="md"
              class="min-w-40"
            />
          </UFormField>
        </div>

        <template #footer>
          <div class="flex justify-end gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              @click="showAddStore = false"
            >
              Abbrechen
            </UButton>
            <UButton
              color="primary"
              :loading="isAddingStore"
              :disabled="!newStore.label || !newStore.external_shop_id"
              @click="handleAddStore"
            >
              Hinzufügen
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>

  <!-- Delete Store Confirmation Modal -->
  <UModal v-model:open="showDeleteStore">
    <template #content>
      <UCard>
        <template #header>
          <h3 class="font-display text-lg font-semibold text-stone-700 dark:text-stone-300">
            Shop löschen
          </h3>
        </template>

        <p>
          Store "{{ storeToDelete?.label }}" wirklich löschen?
        </p>

        <template #footer>
          <div class="flex justify-end gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              @click="showDeleteStore = false"
            >
              Abbrechen
            </UButton>
            <UButton
              color="error"
              :loading="isDeletingStore"
              @click="confirmDeleteStore"
            >
              Löschen
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
