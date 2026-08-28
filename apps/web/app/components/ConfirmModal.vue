<script setup lang="ts">
/**
 * Generic confirmation modal for destructive actions.
 * Used for delete confirmations across transactions, receipts, etc.
 */

const props = withDefaults(defineProps<{
  title: string
  message: string
  confirmLabel?: string
  confirmColor?: 'error' | 'warning' | 'primary'
  loading?: boolean
}>(), {
  confirmLabel: 'Bestätigen',
  confirmColor: 'error',
  loading: false,
})

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const isOpen = defineModel<boolean>('open', { required: true })

function handleConfirm() {
  emit('confirm')
}

function handleCancel() {
  isOpen.value = false
  emit('cancel')
}
</script>

<template>
  <UModal v-model:open="isOpen">
    <template #content>
      <UCard>
        <template #header>
          <h3 class="text-lg font-semibold">
            {{ props.title }}
          </h3>
        </template>

        <p>{{ props.message }}</p>

        <template #footer>
          <div class="flex justify-end gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              @click="handleCancel"
            >
              Abbrechen
            </UButton>
            <UButton
              :color="props.confirmColor"
              :loading="props.loading"
              @click="handleConfirm"
            >
              {{ props.confirmLabel }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
