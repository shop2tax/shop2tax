<script setup lang="ts">
import { CalendarDate, DateFormatter, getLocalTimeZone } from '@internationalized/date'

const startDate = defineModel<string | undefined>('startDate')
const endDate = defineModel<string | undefined>('endDate')

const df = new DateFormatter('de-DE', { dateStyle: 'medium' })

// Bridge: string (YYYY-MM-DD) ↔ CalendarDate
function toCalendarDate(value: string | undefined): CalendarDate | undefined {
  if (!value)
    return undefined
  const [year, month, day] = value.split('-').map(Number)
  return new CalendarDate(year!, month!, day!)
}

function toIsoString(date: CalendarDate): string {
  return `${date.year}-${String(date.month).padStart(2, '0')}-${String(date.day).padStart(2, '0')}`
}

const rangeValue = computed({
  get: () => {
    const start = toCalendarDate(startDate.value)
    const end = toCalendarDate(endDate.value)
    if (!start && !end)
      return undefined
    return { start: start!, end: end ?? start! }
  },
  set: (value) => {
    if (!value) {
      startDate.value = undefined
      endDate.value = undefined
      return
    }
    startDate.value = toIsoString(value.start)
    endDate.value = toIsoString(value.end)
  },
})

function formatRange(): string {
  if (!rangeValue.value)
    return ''
  const tz = getLocalTimeZone()
  const start = df.format(rangeValue.value.start.toDate(tz))
  if (rangeValue.value.start.compare(rangeValue.value.end) === 0)
    return start
  const end = df.format(rangeValue.value.end.toDate(tz))
  return `${start} – ${end}`
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <label class="text-xs font-medium text-stone-500 dark:text-stone-400">Zeitraum</label>
    <UPopover>
      <UButton
        color="neutral"
        variant="outline"
        icon="i-lucide-calendar"
        size="md"
        class="min-w-56 justify-start font-normal"
        :class="{ 'text-stone-400': !rangeValue }"
      >
        {{ rangeValue ? formatRange() : 'Zeitraum wählen' }}
      </UButton>

      <template #content>
        <UCalendar
          v-model="rangeValue"
          class="p-2"
          :number-of-months="2"
          range
        />
      </template>
    </UPopover>
  </div>
</template>
