<script setup lang="ts">
const toast = useToast()
const { data: datevSettings, refresh } = useDatevSettings()
const { save: saveDatevSettings } = useDatevSettingsMutations()

const datevConfig = ref({
  beraternummer: '',
  mandantennummer: '',
  wirtschaftsjahr_beginn: `${new Date().getFullYear()}-01-01`,
})

// Load DATEV config from API
watch(datevSettings, (settings) => {
  if (settings) {
    datevConfig.value = {
      beraternummer: settings.beraternummer || '',
      mandantennummer: settings.mandantennummer || '',
      wirtschaftsjahr_beginn: settings.wirtschaftsjahr_beginn || `${new Date().getFullYear()}-01-01`,
    }
  }
}, { immediate: true })

const isSaving = ref(false)

async function save() {
  isSaving.value = true
  try {
    await saveDatevSettings(datevConfig.value)
    toast.add({ title: 'DATEV-Konfiguration gespeichert', color: 'success', icon: 'i-lucide-check' })
    refresh()
  }
  catch {
    toast.add({ title: 'Fehler beim Speichern', color: 'error', icon: 'i-lucide-circle-x' })
  }
  finally {
    isSaving.value = false
  }
}
</script>

<template>
  <SectionCard title="DATEV-Konfiguration" description="Standardwerte für den DATEV-Export. Werden beim Exportieren vorausgefüllt.">
    <div class="max-w-1/2 space-y-5">
      <div class="grid gap-4 sm:grid-cols-2">
        <UFormField label="Beraternummer">
          <UInput
            v-model="datevConfig.beraternummer"
            placeholder="1234567"
            maxlength="7"
            class="w-full"
          />
        </UFormField>

        <UFormField label="Mandantennummer">
          <UInput
            v-model="datevConfig.mandantennummer"
            placeholder="12345"
            maxlength="5"
            class="w-full"
          />
        </UFormField>
      </div>

      <UFormField label="Wirtschaftsjahr Beginn">
        <UInput
          v-model="datevConfig.wirtschaftsjahr_beginn"
          type="date"
          size="md"
          class="w-full"
        />
      </UFormField>

      <UFormField label="Sachkontenlänge">
        <UInput
          model-value="4"
          disabled
          class="w-full opacity-60"
        />
        <template #hint>
          <span class="text-xs text-stone-400">Standardwert (nicht änderbar)</span>
        </template>
      </UFormField>
    </div>

    <template #footer>
      <div class="flex justify-end">
        <UButton
          color="primary"
          :loading="isSaving"
          @click="save"
        >
          Speichern
        </UButton>
      </div>
    </template>
  </SectionCard>
</template>
