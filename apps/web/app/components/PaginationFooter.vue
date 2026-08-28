<script setup lang="ts">
const props = withDefaults(defineProps<{
  total: number
  page: number
  pageSize: number
  label?: string
}>(), {
  label: 'Einträge',
})

const emit = defineEmits<{
  'update:page': [page: number]
  'update:pageSize': [pageSize: number]
}>()

const PAGE_SIZE_OPTIONS = [
  { label: '10', value: 10 },
  { label: '25', value: 25 },
  { label: '50', value: 50 },
  { label: '100', value: 100 },
]

const currentPage = computed({
  get: () => props.page,
  set: value => emit('update:page', value),
})

const currentPageSize = computed({
  get: () => props.pageSize,
  set: (value: number) => {
    emit('update:pageSize', value)
    emit('update:page', 1)
  },
})

const totalPages = computed(() => Math.ceil(props.total / props.pageSize))
</script>

<template>
  <div v-if="total > 0" class="flex items-center justify-between border-t border-default px-4 py-3">
    <div class="flex items-center gap-2 text-sm text-muted">
      <span>{{ total }} {{ label }}</span>
      <template v-if="totalPages > 1">
        <span class="text-dimmed">·</span>
        <USelect
          v-model="currentPageSize"
          :items="PAGE_SIZE_OPTIONS"
          size="md"
          class="w-18"
        />
        <span class="text-dimmed">pro Seite</span>
      </template>
    </div>
    <UPagination
      v-if="totalPages > 1"
      v-model:page="currentPage"
      :total="total"
      :items-per-page="pageSize"
    />
  </div>
</template>
