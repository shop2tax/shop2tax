<script setup lang="ts">
import type { AIProviderResponse } from '~/types/api'

const toast = useToast()
const { data: siteSettings, refresh } = useSiteSettings()
const { update: updateSiteSettings } = useSiteSettingsMutations()
const { hasAnyProvider, primaryProvider } = useOmsProviders()

const omsProviderName = computed(() => primaryProvider.value?.display_name ?? 'Warenwirtschaft')

const companyName = ref('')
const legalForm = ref('')
const isSmallBusiness = ref<boolean | null>(null)
const taxNumber = ref('')
const vatId = ref('')
const rcTaxRatePercent = ref('19') // Display as percentage (0-100), store as decimal (0-1)
const aiProvider = ref<string | undefined>(undefined)
const aiModel = ref<string | undefined>(undefined)
const omsSyncSetLabels = ref(true) // OMS sync: set shop2tax label
const isSaving = ref(false)

// Fetch available AI providers (only those with configured API keys)
const { data: aiProviders } = useFetch<AIProviderResponse[]>('/api/v1/settings/ai-providers', {
  key: 'ai-providers',
})

const vatOptions = [
  { label: 'Regelbesteuert (19%/7%)', value: 'false' },
  { label: 'Kleinunternehmer §19 UStG (keine USt)', value: 'true' },
]

const selectedVatOption = computed({
  get: () => isSmallBusiness.value === null ? undefined : String(isSmallBusiness.value),
  set: (value: string | undefined) => {
    isSmallBusiness.value = value === undefined ? null : value === 'true'
  },
})

// AI provider options (from available providers + "Deaktiviert")
const providerOptions = computed(() => {
  if (!aiProviders.value)
    return []
  return aiProviders.value.map(provider => ({
    label: provider.provider === 'gemini' ? 'Gemini' : provider.provider === 'openai' ? 'OpenAI' : provider.provider === 'anthropic' ? 'Anthropic' : provider.provider,
    value: provider.provider,
  }))
})

// AI model options (filtered by selected provider)
const modelOptions = computed(() => {
  if (!aiProvider.value || !aiProviders.value)
    return []
  const provider = aiProviders.value.find(p => p.provider === aiProvider.value)
  if (!provider)
    return []
  return provider.models.map(m => ({ label: m, value: m }))
})

// Reset model when provider changes
watch(aiProvider, (newProvider, oldProvider) => {
  if (newProvider !== oldProvider) {
    // Auto-select first model of new provider
    const provider = aiProviders.value?.find(p => p.provider === newProvider)
    aiModel.value = provider?.models[0] ?? undefined
  }
})

// Load settings from API
watch(siteSettings, (settings) => {
  if (settings) {
    companyName.value = settings.company_name ?? ''
    legalForm.value = settings.legal_form ?? ''
    isSmallBusiness.value = settings.is_small_business
    taxNumber.value = settings.tax_number ?? ''
    vatId.value = settings.vat_id ?? ''
    rcTaxRatePercent.value = String((settings.rc_tax_rate ?? 0.19) * 100)
    aiProvider.value = settings.ai_provider ?? undefined
    aiModel.value = settings.ai_model ?? undefined
    omsSyncSetLabels.value = settings.oms_sync_set_labels ?? true
  }
}, { immediate: true })

async function save() {
  isSaving.value = true
  try {
    await updateSiteSettings({
      company_name: companyName.value || null,
      legal_form: legalForm.value || null,
      is_small_business: isSmallBusiness.value,
      tax_number: taxNumber.value || null,
      vat_id: vatId.value || null,
      rc_tax_rate: Number.parseFloat(rcTaxRatePercent.value) / 100,
      ai_provider: aiProvider.value || null,
      ai_model: aiModel.value || null,
      oms_sync_set_labels: omsSyncSetLabels.value,
    })
    toast.add({ title: 'Einstellungen gespeichert', color: 'success', icon: 'i-lucide-check' })
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
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <SectionCard title="Unternehmen" description="Grundlegende Angaben zu deinem Unternehmen.">
      <div class="space-y-5">
        <UFormField label="Firmenname">
          <UInput
            v-model="companyName"
            placeholder="z.B. Meine Firma GmbH"
            class="w-full"
          />
          <template #hint>
            <span class="text-xs text-stone-400">Wird auf der Login-Seite angezeigt.</span>
          </template>
        </UFormField>

        <UFormField label="Rechtsform">
          <UInput
            v-model="legalForm"
            placeholder="z.B. GbR, Einzelunternehmen"
            class="w-full"
          />
        </UFormField>
      </div>
    </SectionCard>

    <SectionCard title="Buchhaltung & Steuer" description="Steuerliche Einstellungen für die automatische Kontierung.">
      <div class="space-y-5">
        <UFormField label="Umsatzsteuer">
          <USelect
            v-model="selectedVatOption"
            :items="vatOptions"
            placeholder="Bitte auswählen"
            size="md"
            class="min-w-40 w-full"
          />
          <template #hint>
            <span class="inline-flex items-center gap-1 text-xs text-stone-400">
              Beeinflusst SKR03-Kontierung.
              <UTooltip :delay-duration="100" :ui="{ content: 'bg-transparent! h-auto! ring-0! shadow-none! p-0!' }">
                <UIcon name="i-lucide-info" class="size-3.5 shrink-0 cursor-help" />
                <template #content>
                  <div class="max-w-xs rounded-lg bg-white p-3 text-xs leading-relaxed text-stone-700 shadow-lg ring-1 ring-stone-200">
                    <p>Bestimmt SKR03-Erlöskonten und Reverse-Charge-Behandlung bei Marktplatz-Importen (Etsy, Amazon, etc.).</p>
                    <p class="mt-2">
                      <strong>Kleinunternehmer:</strong><br>
                      Reverse-Charge-USt ohne Vorsteuerabzug (BU 95)
                    </p>
                    <p class="mt-1.5">
                      <strong>Regelbesteuert:</strong><br>
                      Reverse-Charge-USt mit Vorsteuerabzug (BU 94)
                    </p>
                  </div>
                </template>
              </UTooltip>
            </span>
          </template>
        </UFormField>

        <UFormField label="Steuernummer">
          <UInput
            v-model="taxNumber"
            placeholder="z.B. 329/5832/2840"
            class="w-full"
          />
        </UFormField>

        <UFormField label="USt-ID">
          <UInput
            v-model="vatId"
            placeholder="z.B. DE123456789"
            class="w-full"
          />
          <template #hint>
            <span class="text-xs text-stone-400">Format: DE + 9 Ziffern</span>
          </template>
        </UFormField>

        <UFormField label="Reverse-Charge-Steuersatz">
          <UInput
            v-model="rcTaxRatePercent"
            type="number"
            min="0"
            max="100"
            step="0.01"
            placeholder="19"
            class="w-full"
          >
            <template #trailing>
              <span class="text-stone-400">%</span>
            </template>
          </UInput>
          <template #hint>
            <span class="inline-flex items-center gap-1 text-xs text-stone-400">
              Für Reverse-Charge (§13b UStG).
              <UTooltip :delay-duration="100" :ui="{ content: 'bg-transparent! h-auto! ring-0! shadow-none! p-0!' }">
                <UIcon name="i-lucide-info" class="size-3.5 shrink-0 cursor-help" />
                <template #content>
                  <div class="max-w-xs rounded-lg bg-white p-3 text-xs leading-relaxed text-stone-700 shadow-lg ring-1 ring-stone-200">
                    <p>Umsatzsteuersatz für Reverse-Charge-Berechnungen nach §13b UStG. Wird bei Marktplatz-Importen (Etsy, Amazon, etc.) verwendet, wenn der Marktplatz die USt schuldet.</p>
                    <p class="mt-2"><strong>Standard:</strong> 19% (regulärer USt-Satz in Deutschland)</p>
                    <p class="mt-1.5">Nur ändern, falls ein abweichender Satz gilt (z.B. 7% für bestimmte Warengruppen).</p>
                  </div>
                </template>
              </UTooltip>
            </span>
          </template>
        </UFormField>
      </div>
    </SectionCard>
  </div>

  <SectionCard title="KI-Dokumenterkennung" description="Automatische Erkennung von Rechnungsdaten beim Beleg-Upload.">
    <div class="space-y-5">
      <UFormField label="Anbieter">
        <USelect
          v-model="aiProvider"
          :items="providerOptions"
          placeholder="Deaktiviert"
          size="md"
          class="min-w-40 w-full"
        />
        <template #hint>
          <span class="inline-flex items-center gap-1 text-xs text-stone-400">
            API-Key per Umgebungsvariable.
            <UTooltip :delay-duration="100" :ui="{ content: 'bg-transparent! h-auto! ring-0! shadow-none! p-0!' }">
              <UIcon name="i-lucide-info" class="size-3.5 shrink-0 cursor-help" />
              <template #content>
                <div class="max-w-xs rounded-lg bg-white p-3 text-xs leading-relaxed text-stone-700 shadow-lg ring-1 ring-stone-200">
                  <p>API-Keys werden über Umgebungsvariablen in der <code class="rounded bg-stone-100 px-1 py-0.5 font-mono text-[11px]">.env</code>-Datei konfiguriert:</p>
                  <ul class="mt-2 space-y-1">
                    <li><code class="rounded bg-stone-100 px-1 py-0.5 font-mono text-[11px]">GEMINI_API_KEY</code> — Google Gemini</li>
                    <li><code class="rounded bg-stone-100 px-1 py-0.5 font-mono text-[11px]">OPENAI_API_KEY</code> — OpenAI</li>
                    <li><code class="rounded bg-stone-100 px-1 py-0.5 font-mono text-[11px]">ANTHROPIC_API_KEY</code> — Anthropic Claude</li>
                  </ul>
                  <p class="mt-2">Nur Provider mit gesetztem Key erscheinen in der Auswahl oben.</p>
                </div>
              </template>
            </UTooltip>
          </span>
        </template>
      </UFormField>

      <UFormField v-if="aiProvider && modelOptions.length > 0" label="Modell">
        <USelect
          v-model="aiModel"
          :items="modelOptions"
          placeholder="Modell auswählen"
          size="md"
          class="min-w-40 w-full"
        />
      </UFormField>

      <UAlert
        v-if="aiProvider"
        color="warning"
        icon="i-lucide-shield-alert"
        title="DSGVO-Hinweis"
        :description="`Die KI-Erkennung greift nur, wenn keine eingebetteten E-Rechnungsdaten (ZUGFeRD/XRechnung) gefunden werden. In diesem Fall werden Rechnungsdaten zur Texterkennung an ${aiProvider === 'gemini' ? 'Google (Gemini)' : aiProvider === 'openai' ? 'OpenAI' : aiProvider === 'anthropic' ? 'Anthropic' : aiProvider} gesendet. Stellen Sie sicher, dass dies mit Ihren Datenschutzanforderungen vereinbar ist.`"
      />

      <p v-if="providerOptions.length === 0" class="text-sm text-stone-500">
        Keine API-Keys konfiguriert. ZUGFeRD/XRechnung-Erkennung funktioniert weiterhin ohne KI-Anbieter.
      </p>
    </div>
  </SectionCard>

  <SectionCard
    v-if="hasAnyProvider"
    :title="`${omsProviderName}-Synchronisierung`"
    :description="`Einstellungen für den ${omsProviderName}-Import.`"
  >
    <div class="flex items-center justify-between">
      <div>
        <p class="text-sm font-medium text-stone-700">
          Sync-Label setzen
        </p>
        <p class="text-xs text-stone-500 mt-0.5">
          Setzt das Label "shop2tax" auf synchronisierte Bestellungen in {{ omsProviderName }}, um doppelte Importe zu vermeiden.
        </p>
      </div>
      <USwitch v-model="omsSyncSetLabels" />
    </div>
  </SectionCard>

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
