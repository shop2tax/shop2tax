<script setup lang="ts">
interface Tab {
  label: string
  value: string
  icon?: string
}

defineProps<{
  tabs: Tab[]
}>()

const model = defineModel<string>({ required: true })
</script>

<template>
  <div class="flex gap-1 rounded-lg border border-stone-200 bg-stone-100 p-1 dark:border-stone-800 dark:bg-stone-900">
    <button
      v-for="tab in tabs"
      :key="tab.value"
      class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
      :class="model === tab.value
        ? 'bg-white text-stone-900 shadow-sm dark:bg-stone-800 dark:text-stone-100'
        : 'text-stone-500 hover:text-stone-700 dark:text-stone-400 dark:hover:text-stone-300'"
      @click="model = tab.value"
    >
      <UIcon v-if="tab.icon" :name="tab.icon" class="size-4" />
      {{ tab.label }}
    </button>
  </div>
</template>
