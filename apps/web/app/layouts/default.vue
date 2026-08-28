<script setup lang="ts">
const { user, clear } = useUserSession()
const route = useRoute()
const config = useRuntimeConfig()
const authEnabled = config.public.authEnabled
const colorMode = useColorMode()

const isDark = computed({
  get() {
    return colorMode.value === 'dark'
  },
  set(value: boolean) {
    colorMode.preference = value ? 'dark' : 'light'
  },
})

// 🧭 Flat navigation for horizontal header
const navItems = [
  { label: 'Dashboard', icon: 'i-lucide-layout-dashboard', to: '/' },
  { label: 'Buchungen', icon: 'i-lucide-credit-card', to: '/transactions' },
  { label: 'Belege', icon: 'i-lucide-file-text', to: '/receipts' },
  { label: 'Import', icon: 'i-lucide-wallet', to: '/import' },
  { label: 'Export', icon: 'i-lucide-file-down', to: '/export' },
  { label: 'Einstellungen', icon: 'i-lucide-settings', to: '/settings' },
]

function isActive(to: string) {
  if (to === '/')
    return route.path === '/'
  return route.path.startsWith(to)
}

async function logout() {
  await clear()
  navigateTo('/login')
}
</script>

<template>
  <div class="flex min-h-screen flex-col bg-stone-50 dark:bg-stone-950">
    <!-- 🗄️ Row 1: Logo + Navigation + User -->
    <header class="sticky top-0 z-50 flex h-[52px] items-center justify-between border-b border-stone-200 bg-white px-6 dark:border-stone-800 dark:bg-stone-900">
      <!-- Left: Logo + Nav -->
      <div class="flex items-center">
        <NuxtLink to="/" class="flex items-center gap-2.5">
          <svg class="size-7 text-primary-600 dark:text-primary-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1068 1222">
            <path fill="currentColor" d="m599.53 484.56 86 49.68c3.08 1.79 5.61.32 5.61-3.24v-73.37c0-3.57-2.54-7.95-5.61-9.72l-86.05-49.68c-3.08-1.78-8.13-1.78-11.23 0L359.97 530.04c-3.08 1.78-8.14 1.78-11.23 0l-86-49.68c-3.1-1.78-5.63-.32-5.63 3.24v73.37c0 3.57 2.54 7.95 5.63 9.73l86.03 49.67c3.09 1.78 8.15 1.78 11.22 0l228.3-131.82c3.08-1.78 8.13-1.78 11.23 0Z" />
            <path fill="currentColor" d="m599.5 616.38 63.56-36.71c3.08-1.78 3.08-4.7 0-6.49l-63.53-36.71c-3.1-1.78-8.15-1.78-11.23 0l-63.59 36.73c-3.07 1.78-3.07 4.7 0 6.48l63.56 36.7c3.08 1.78 8.14 1.78 11.23 0ZM479.75 605.64c-3.07-1.79-8.13-1.79-11.22-.02l-63.57 36.71c-3.09 1.79-3.09 4.71 0 6.49l63.52 36.71c3.1 1.78 8.16 1.78 11.23 0l63.6-36.72c3.08-1.78 3.08-4.69 0-6.49l-63.57-36.68ZM285.23 441.43l63.54 36.7c3.08 1.78 8.14 1.78 11.22 0l63.59-36.71c3.07-1.78 3.07-4.71 0-6.49l-63.57-36.69c-3.07-1.78-8.13-1.78-11.22 0l-63.56 36.71c-3.08 1.78-3.08 4.7 0 6.49Z" />
            <path fill="currentColor" d="M1050.58 292.75 551.32 4.5C546.56 1.75 540.28.38 534 .38s-12.56 1.38-17.32 4.12L17.42 292.75c-9.53 5.5-17.32 19-17.32 30v576.5c0 11 7.79 24.5 17.32 30l499.26 288.25c4.76 2.75 11.04 4.12 17.32 4.12s12.56-1.38 17.32-4.12l499.26-288.25c9.53-5.5 17.32-19 17.32-30v-576.5c0-11-7.79-24.5-17.32-30ZM855.82 790.31c0 3.56-2.52 7.94-5.61 9.72l-130.97 75.63c-3.09 1.78-8.15 1.78-11.23 0L599.5 813c-3.09-1.77-8.15-1.77-11.23 0l-108.53 62.66c-3.07 1.78-8.13 1.78-11.22 0l-130.98-75.63c-3.1-1.78-5.61-6.16-5.61-9.72V665.02c0-3.56-2.53-7.94-5.62-9.72l-108.53-62.65c-3.08-1.78-5.61-6.16-5.61-9.73V431.67c0-3.56 2.54-7.94 5.61-9.71l130.99-75.63c3.09-1.78 8.15-1.78 11.22 0l108.53 62.65c3.09 1.78 8.15 1.78 11.22 0l108.51-62.65c3.1-1.78 8.15-1.78 11.23 0l130.99 75.63c3.09 1.78 5.61 6.15 5.61 9.71v125.3c0 3.57 2.55 7.96 5.63 9.74l108.51 62.64c3.1 1.78 5.61 6.16 5.61 9.73v151.24Z" />
            <path fill="currentColor" d="m805.27 655.29-86.03-49.67c-3.09-1.78-8.15-1.78-11.23 0L479.72 737.43c-3.07 1.79-8.14 1.79-11.23 0l-85.99-49.67c-3.1-1.79-5.61-.34-5.61 3.23v73.37c0 3.58 2.52 7.96 5.61 9.74l86.03 49.67c3.09 1.78 8.15 1.78 11.22 0l228.3-131.81c3.08-1.78 8.13-1.78 11.22 0l86 49.68c3.1 1.78 5.61.32 5.61-3.24v-73.39c0-3.57-2.52-7.95-5.61-9.73Z" />
            <path fill="currentColor" d="m782.8 780.58-63.54-36.71c-3.09-1.78-8.14-1.78-11.23 0l-63.6 36.74c-3.1 1.78-3.1 4.69 0 6.47l63.57 36.7c3.08 1.78 8.14 1.78 11.23 0l63.57-36.71c3.1-1.78 3.1-4.71 0-6.49Z" />
          </svg>
          <span class="font-display text-lg font-semibold tracking-tight text-stone-700 dark:text-stone-300">shop2tax</span>
        </NuxtLink>

        <nav class="ml-10 flex items-center gap-1">
          <NuxtLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="relative flex h-[52px] items-center gap-1.5 px-3 text-[13px] font-medium transition-colors"
            :class="isActive(item.to)
              ? 'text-primary-600 dark:text-primary-400'
              : 'text-stone-500 hover:text-stone-700 dark:text-stone-400 dark:hover:text-stone-200'"
          >
            <UIcon :name="item.icon" class="size-4" />
            <span>{{ item.label }}</span>
            <!-- Active indicator: bottom border -->
            <span
              v-if="isActive(item.to)"
              class="absolute inset-x-0 bottom-0 h-0.5 bg-primary-600 dark:bg-primary-400"
            />
          </NuxtLink>
        </nav>
      </div>

      <!-- Right: Color mode + User dropdown -->
      <div class="flex items-center gap-6">
        <ClientOnly>
          <UButton
            :icon="isDark ? 'i-lucide-moon' : 'i-lucide-sun'"
            :label="isDark ? 'Dunkel' : 'Hell'"
            color="neutral"
            variant="ghost"
            size="sm"
            :aria-label="isDark ? 'Zum hellen Modus wechseln' : 'Zum dunklen Modus wechseln'"
            @click="isDark = !isDark"
          />
          <template #fallback>
            <div class="h-8 w-20" />
          </template>
        </ClientOnly>

        <UDropdownMenu
          v-if="authEnabled"
          :items="[{ label: 'Abmelden', icon: 'i-lucide-log-out', onSelect: logout }]"
          :content="{ side: 'bottom', align: 'end' }"
        >
          <button class="flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-stone-50 dark:hover:bg-stone-800">
            <span class="text-[13px] font-medium text-stone-700 dark:text-stone-300">
              {{ user?.name || user?.email || 'Benutzer' }}
            </span>
            <UIcon name="i-lucide-chevron-down" class="size-3.5 text-stone-400" />
            <div
              v-if="user?.picture"
              class="size-8 overflow-hidden rounded-full border border-primary-500/20"
            >
              <img :src="user.picture" :alt="user.name || ''" class="size-full object-cover">
            </div>
            <div
              v-else
              class="flex size-8 items-center justify-center rounded-full bg-primary-600 text-xs font-semibold text-white"
            >
              {{ (user?.name || user?.email || 'U').charAt(0).toUpperCase() }}
            </div>
          </button>
        </UDropdownMenu>
      </div>
    </header>

    <!-- 📄 Main content (pages provide their own context bar / title) -->
    <main class="flex-1">
      <slot />
    </main>
  </div>
</template>
