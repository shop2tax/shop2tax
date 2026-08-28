<script setup lang="ts">
/**
 * AccountsManager - Manage SKR03 accounts in settings.
 *
 * Features:
 * - Table: Nr | Name | Kategorie | BU | Aktiv | System
 * - Search across all columns
 * - Toggle active/inactive via PATCH
 * - Inline form for creating new accounts
 * - Badge "Standard" for is_system accounts
 */
import type { AccountCategory, SKR03AccountResponse } from '~/types/api'

const toast = useToast()
const { data: accounts, refresh, status } = useAccounts()
const { createAccount, updateAccount } = useAccountMutations()

// --- Search ---
const searchQuery = ref('')

const filteredAccounts = computed(() => {
  if (!accounts.value)
    return []
  const query = searchQuery.value.toLowerCase().trim()
  if (!query)
    return accounts.value
  return accounts.value.filter((account) => {
    return (
      String(account.id).includes(query)
      || account.name.toLowerCase().includes(query)
      || account.category.toLowerCase().includes(query)
      || (account.bu_schluessel !== null && String(account.bu_schluessel).includes(query))
    )
  })
})

// --- Category labels ---
const categoryLabels: Record<AccountCategory, string> = {
  revenue: 'Erlöse',
  expense: 'Aufwand',
  neutral: 'Neutral',
}

const categoryColors: Record<AccountCategory, 'success' | 'error' | 'neutral'> = {
  revenue: 'success',
  expense: 'error',
  neutral: 'neutral',
}

// --- BU-Schlüssel labels ---
const buLabels: Record<number, string> = {
  2: '2 (7% USt)',
  3: '3 (19% USt)',
  8: '8 (7% VSt)',
  9: '9 (19% VSt)',
}

// --- Toggle active ---
const togglingId = ref<number | null>(null)

async function toggleActive(account: SKR03AccountResponse) {
  togglingId.value = account.id
  try {
    await updateAccount(account.id, { active: !account.active })
    toast.add({
      title: account.active ? 'Konto deaktiviert' : 'Konto aktiviert',
      color: 'success',
      icon: 'i-lucide-check',
    })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Aktualisieren', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    togglingId.value = null
  }
}

// --- Add new account (inline form) ---
const showAddForm = ref(false)
const isSaving = ref(false)

const newAccountId = ref<number | undefined>(undefined)
const newAccountName = ref('')
const newAccountCategory = ref<AccountCategory>('expense')
const newAccountBuSchluessel = ref<number | undefined>(undefined)

const categoryOptions = [
  { value: 'revenue', label: 'Erlöse' },
  { value: 'expense', label: 'Aufwand' },
  { value: 'neutral', label: 'Neutral' },
]

const buSchluesselOptions = [
  { value: '', label: 'Kein BU-Schlüssel' },
  { value: '2', label: '2 — 7% USt (Erlöse)' },
  { value: '3', label: '3 — 19% USt (Erlöse)' },
  { value: '8', label: '8 — 7% VSt (Aufwand)' },
  { value: '9', label: '9 — 19% VSt (Aufwand)' },
]

const newBuSchluesselValue = ref('')

// Account class → expected category mapping
const accountClassToCategory: Record<number, AccountCategory> = {
  1: 'neutral',
  2: 'neutral',
  3: 'expense',
  4: 'expense',
  5: 'neutral',
  6: 'neutral',
  7: 'neutral',
  8: 'revenue',
}

// Auto-set category when account ID changes
watch(() => newAccountId.value, (value) => {
  if (value && value >= 1000 && value <= 8999) {
    const accountClass = Math.floor(value / 1000)
    const expected = accountClassToCategory[accountClass]
    if (expected) {
      newAccountCategory.value = expected
    }
  }
})

function resetForm() {
  newAccountId.value = undefined
  newAccountName.value = ''
  newAccountCategory.value = 'expense'
  newAccountBuSchluessel.value = undefined
  newBuSchluesselValue.value = ''
  showAddForm.value = false
}

async function handleCreateAccount() {
  if (!newAccountId.value || !newAccountName.value.trim())
    return

  isSaving.value = true
  try {
    await createAccount({
      id: newAccountId.value,
      name: newAccountName.value.trim(),
      category: newAccountCategory.value,
      bu_schluessel: newBuSchluesselValue.value ? Number.parseInt(newBuSchluesselValue.value) : null,
    })
    toast.add({ title: 'Konto angelegt', color: 'success', icon: 'i-lucide-check' })
    resetForm()
    refresh()
  }
  catch (error: unknown) {
    const errorMessage = error instanceof Error ? error.message : String(error)
    if (errorMessage.includes('409') || errorMessage.includes('already exists')) {
      toast.add({ title: 'Kontonummer existiert bereits', color: 'error', icon: 'i-lucide-circle-x' })
    }
    else if (errorMessage.includes('422')) {
      toast.add({ title: 'Ungültige Eingabe', description: 'Prüfen Sie Kontonummer und Kategorie.', color: 'error', icon: 'i-lucide-circle-x' })
    }
    else {
      toast.add({ title: 'Fehler beim Anlegen', color: 'error', icon: 'i-lucide-circle-x' })
    }
  }
  finally {
    isSaving.value = false
  }
}

// --- Table columns ---
const columns = [
  { accessorKey: 'id', header: 'Nr' },
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'category', header: 'Kategorie' },
  { accessorKey: 'bu_schluessel', header: 'BU' },
  { accessorKey: 'active', header: 'Aktiv' },
  { accessorKey: 'actions', header: '' },
]
</script>

<template>
  <SectionCard title="Kontenrahmen" description="SKR03-Konten für die Kontierung verwalten.">
    <template #header>
      <UButton
        size="md"
        color="primary"
        icon="i-lucide-plus"
        @click="showAddForm = !showAddForm"
      >
        Neues Konto
      </UButton>
    </template>

    <!-- Add form (inline, above table) -->
    <div v-if="showAddForm" class="mb-6 rounded-lg border border-primary-200 bg-primary-50/50 p-4 dark:border-primary-800 dark:bg-primary-950/30">
      <div class="mb-3 flex items-start gap-2">
        <UIcon name="i-lucide-info" class="mt-0.5 size-4 shrink-0 text-primary-600" />
        <p class="text-sm text-primary-700 dark:text-primary-300">
          SKR03-Referenz:
          <a
            href="https://www.datev.de/web/de/berufsgruppenuebergreifend/ratgeber/rechnungswesen/datev-standard-kontenrahmen"
            target="_blank"
            rel="noopener"
            class="underline hover:no-underline"
          >DATEV Standard-Kontenrahmen</a>
        </p>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <UFormField label="Kontonummer">
          <UInput
            v-model.number="newAccountId"
            type="number"
            placeholder="z.B. 4964"
            :min="1000"
            :max="8999"
            class="w-full"
          />
        </UFormField>

        <UFormField label="Name" class="lg:col-span-2">
          <UInput
            v-model="newAccountName"
            placeholder="z.B. Lizenzen und Konzessionen"
            class="w-full"
            @keydown.enter="handleCreateAccount"
          />
        </UFormField>

        <UFormField label="Kategorie">
          <USelect
            v-model="newAccountCategory"
            :items="categoryOptions"
            class="w-full"
          />
        </UFormField>

        <UFormField label="BU-Schlüssel">
          <USelect
            v-model="newBuSchluesselValue"
            :items="buSchluesselOptions"
            placeholder="Kein BU"
            class="w-full"
          />
        </UFormField>
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <UButton
          color="neutral"
          variant="ghost"
          @click="resetForm"
        >
          Abbrechen
        </UButton>
        <UButton
          color="primary"
          :loading="isSaving"
          :disabled="!newAccountId || !newAccountName.trim()"
          @click="handleCreateAccount"
        >
          Anlegen
        </UButton>
      </div>
    </div>

    <!-- Search -->
    <div class="mb-4">
      <UInput
        v-model="searchQuery"
        placeholder="Konten durchsuchen..."
        icon="i-lucide-search"
        size="md"
        class="max-w-sm"
      />
    </div>

    <!-- Table -->
    <UTable
      :data="filteredAccounts"
      :columns="columns"
      :loading="status === 'pending'"
      :empty-state="{ icon: 'i-lucide-book-open', label: 'Keine Konten vorhanden' }"
    >
      <template #id-cell="{ row }">
        <span class="font-tabular font-mono text-sm">{{ row.original.id }}</span>
      </template>

      <template #name-cell="{ row }">
        <div class="flex items-center gap-2">
          <span>{{ row.original.name }}</span>
          <UBadge
            v-if="row.original.is_system"
            color="neutral"
            variant="subtle"
            size="sm"
          >
            Standard
          </UBadge>
        </div>
      </template>

      <template #category-cell="{ row }">
        <UBadge
          :color="categoryColors[row.original.category as AccountCategory]"
          variant="soft"
          size="sm"
        >
          {{ categoryLabels[row.original.category as AccountCategory] }}
        </UBadge>
      </template>

      <template #bu_schluessel-cell="{ row }">
        <span v-if="row.original.bu_schluessel !== null" class="font-tabular text-sm">
          {{ buLabels[row.original.bu_schluessel] || row.original.bu_schluessel }}
        </span>
        <span v-else class="text-stone-300">—</span>
      </template>

      <template #active-cell="{ row }">
        <USwitch
          :model-value="row.original.active"
          :loading="togglingId === row.original.id"
          size="sm"
          @update:model-value="toggleActive(row.original)"
        />
      </template>

      <template #actions-cell="{ row }">
        <span v-if="!row.original.active" class="text-xs text-stone-400">Deaktiviert</span>
      </template>
    </UTable>
  </SectionCard>
</template>
