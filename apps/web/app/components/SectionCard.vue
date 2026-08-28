<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex items-center justify-between">
        <div>
          <h3 class="font-display text-lg font-semibold text-stone-700 dark:text-stone-300">
            {{ title }}
          </h3>
          <p v-if="description" class="mt-1 text-sm text-stone-500">
            {{ description }}
          </p>
        </div>
        <slot name="header" />
      </div>
    </template>

    <slot />

    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </UCard>
</template>
