<script setup lang="ts">
definePageMeta({
  middleware: ['auth'],
})

const { user } = useUserSession()
const { hasAnyProvider, primaryProvider } = useOmsProviders()

const omsTabLabel = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

// Tab navigation
const tabs = computed(() => [
  { label: 'Allgemein', value: 'general', icon: 'i-lucide-settings' },
  { label: 'Kontenrahmen', value: 'accounts', icon: 'i-lucide-book-open' },
  { label: 'Bank-Quellen', value: 'sources', icon: 'i-lucide-landmark' },
  { label: 'DATEV', value: 'datev', icon: 'i-lucide-file-spreadsheet' },
  { label: omsTabLabel.value, value: 'oms', icon: 'i-lucide-link' },
])
const tabValues = computed(() => tabs.value.map(t => t.value))
const activeTab = useQueryTab(tabValues, 'general')
</script>

<template>
  <div class="flex-1 min-w-0">
    <PageHeader title="Einstellungen">
      <div class="flex items-center gap-3">
        <div class="text-right">
          <p class="text-sm font-medium text-stone-900 dark:text-stone-100">
            {{ user?.name }}
          </p>
          <p class="text-xs text-stone-500 dark:text-stone-400">
            {{ user?.email }}
          </p>
        </div>
        <UAvatar
          :src="user?.picture"
          :alt="user?.name"
          size="md"
        />
      </div>
    </PageHeader>

    <div class="p-6 space-y-6">
      <TabNav v-model="activeTab" :tabs="tabs" />

      <SettingsGeneralSettings v-if="activeTab === 'general'" />
      <SettingsAccountsManager v-if="activeTab === 'accounts'" />
      <SettingsSourcesManager v-if="activeTab === 'sources'" />
      <SettingsDatevSettings v-if="activeTab === 'datev'" />
      <template v-if="activeTab === 'oms'">
        <SettingsOmsStoresManager v-if="hasAnyProvider" />
        <UAlert
          v-else
          color="neutral"
          variant="soft"
          icon="i-lucide-link"
          title="Optional: Verbinde eine Warenwirtschaft für automatischen Beleg-Import"
        />
      </template>
    </div>
  </div>
</template>
