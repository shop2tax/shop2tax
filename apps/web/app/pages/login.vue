<script setup lang="ts">
definePageMeta({
  layout: false,
  middleware: [],
})

// Local Mode: No OAuth configured → redirect to dashboard (no login needed)
const config = useRuntimeConfig()
if (!config.public.authEnabled) {
  await navigateTo('/', { replace: true })
}

const error = computed(() => {
  const route = useRoute()
  return route.query.error as string | undefined
})

// Fetch company name for login page footer
const { data: publicSettings } = usePublicSettings()
const companyName = computed(() => publicSettings.value?.company_name || 'shop2tax')
</script>

<template>
  <div class="grid min-h-screen lg:grid-cols-2">
    <!-- Left: Brand panel -->
    <div class="relative hidden overflow-hidden bg-primary-950 lg:flex lg:flex-col lg:justify-between">
      <!-- Gradient mesh background -->
      <div class="absolute inset-0">
        <div class="absolute -left-20 -top-20 size-96 rounded-full bg-primary-800/40 blur-3xl" />
        <div class="absolute bottom-0 right-0 size-80 rounded-full bg-primary-900/30 blur-3xl" />
        <div class="absolute left-1/3 top-1/2 size-64 rounded-full bg-primary-700/20 blur-3xl" />
      </div>

      <!-- Content -->
      <div class="relative z-10 flex flex-1 flex-col justify-center px-12 xl:px-16">
        <svg class="size-12 text-primary-300" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1068 1222">
          <path fill="currentColor" d="m599.53 484.56 86 49.68c3.08 1.79 5.61.32 5.61-3.24v-73.37c0-3.57-2.54-7.95-5.61-9.72l-86.05-49.68c-3.08-1.78-8.13-1.78-11.23 0L359.97 530.04c-3.08 1.78-8.14 1.78-11.23 0l-86-49.68c-3.1-1.78-5.63-.32-5.63 3.24v73.37c0 3.57 2.54 7.95 5.63 9.73l86.03 49.67c3.09 1.78 8.15 1.78 11.22 0l228.3-131.82c3.08-1.78 8.13-1.78 11.23 0Z" />
          <path fill="currentColor" d="m599.5 616.38 63.56-36.71c3.08-1.78 3.08-4.7 0-6.49l-63.53-36.71c-3.1-1.78-8.15-1.78-11.23 0l-63.59 36.73c-3.07 1.78-3.07 4.7 0 6.48l63.56 36.7c3.08 1.78 8.14 1.78 11.23 0ZM479.75 605.64c-3.07-1.79-8.13-1.79-11.22-.02l-63.57 36.71c-3.09 1.79-3.09 4.71 0 6.49l63.52 36.71c3.1 1.78 8.16 1.78 11.23 0l63.6-36.72c3.08-1.78 3.08-4.69 0-6.49l-63.57-36.68ZM285.23 441.43l63.54 36.7c3.08 1.78 8.14 1.78 11.22 0l63.59-36.71c3.07-1.78 3.07-4.71 0-6.49l-63.57-36.69c-3.07-1.78-8.13-1.78-11.22 0l-63.56 36.71c-3.08 1.78-3.08 4.7 0 6.49Z" />
          <path fill="currentColor" d="M1050.58 292.75 551.32 4.5C546.56 1.75 540.28.38 534 .38s-12.56 1.38-17.32 4.12L17.42 292.75c-9.53 5.5-17.32 19-17.32 30v576.5c0 11 7.79 24.5 17.32 30l499.26 288.25c4.76 2.75 11.04 4.12 17.32 4.12s12.56-1.38 17.32-4.12l499.26-288.25c9.53-5.5 17.32-19 17.32-30v-576.5c0-11-7.79-24.5-17.32-30ZM855.82 790.31c0 3.56-2.52 7.94-5.61 9.72l-130.97 75.63c-3.09 1.78-8.15 1.78-11.23 0L599.5 813c-3.09-1.77-8.15-1.77-11.23 0l-108.53 62.66c-3.07 1.78-8.13 1.78-11.22 0l-130.98-75.63c-3.1-1.78-5.61-6.16-5.61-9.72V665.02c0-3.56-2.53-7.94-5.62-9.72l-108.53-62.65c-3.08-1.78-5.61-6.16-5.61-9.73V431.67c0-3.56 2.54-7.94 5.61-9.71l130.99-75.63c3.09-1.78 8.15-1.78 11.22 0l108.53 62.65c3.09 1.78 8.15 1.78 11.22 0l108.51-62.65c3.1-1.78 8.15-1.78 11.23 0l130.99 75.63c3.09 1.78 5.61 6.15 5.61 9.71v125.3c0 3.57 2.55 7.96 5.63 9.74l108.51 62.64c3.1 1.78 5.61 6.16 5.61 9.73v151.24Z" />
          <path fill="currentColor" d="m805.27 655.29-86.03-49.67c-3.09-1.78-8.15-1.78-11.23 0L479.72 737.43c-3.07 1.79-8.14 1.79-11.23 0l-85.99-49.67c-3.1-1.79-5.61-.34-5.61 3.23v73.37c0 3.58 2.52 7.96 5.61 9.74l86.03 49.67c3.09 1.78 8.15 1.78 11.22 0l228.3-131.81c3.08-1.78 8.13-1.78 11.22 0l86 49.68c3.1 1.78 5.61.32 5.61-3.24v-73.39c0-3.57-2.52-7.95-5.61-9.73Z" />
          <path fill="currentColor" d="m782.8 780.58-63.54-36.71c-3.09-1.78-8.14-1.78-11.23 0l-63.6 36.74c-3.1 1.78-3.1 4.69 0 6.47l63.57 36.7c3.08 1.78 8.14 1.78 11.23 0l63.57-36.71c3.1-1.78 3.1-4.71 0-6.49Z" />
        </svg>
        <h1 class="mt-6 font-display text-4xl font-bold tracking-tight text-white xl:text-5xl">
          shop2tax
        </h1>
        <p class="mt-3 max-w-sm text-lg leading-relaxed text-primary-200/80">
          Deine Belege. Deine Konten. Kein Abo.
          <br><br>
          Selbstgehostete Buchhaltung für Kleinunternehmer.
        </p>
      </div>

      <!-- Footer -->
      <div class="relative z-10 px-12 pb-8 xl:px-16">
        <p class="text-sm text-primary-400/60">
          {{ companyName }}
        </p>
      </div>
    </div>

    <!-- Right: Login form -->
    <div class="flex flex-col items-center justify-center bg-stone-50 px-6 dark:bg-stone-950">
      <div class="w-full max-w-sm space-y-8 text-center">
        <!-- Mobile brand (hidden on desktop where left panel shows) -->
        <div class="lg:hidden">
          <svg class="mx-auto mb-4 size-12 text-primary-600 dark:text-primary-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1068 1222">
            <path fill="currentColor" d="m599.53 484.56 86 49.68c3.08 1.79 5.61.32 5.61-3.24v-73.37c0-3.57-2.54-7.95-5.61-9.72l-86.05-49.68c-3.08-1.78-8.13-1.78-11.23 0L359.97 530.04c-3.08 1.78-8.14 1.78-11.23 0l-86-49.68c-3.1-1.78-5.63-.32-5.63 3.24v73.37c0 3.57 2.54 7.95 5.63 9.73l86.03 49.67c3.09 1.78 8.15 1.78 11.22 0l228.3-131.82c3.08-1.78 8.13-1.78 11.23 0Z" />
            <path fill="currentColor" d="m599.5 616.38 63.56-36.71c3.08-1.78 3.08-4.7 0-6.49l-63.53-36.71c-3.1-1.78-8.15-1.78-11.23 0l-63.59 36.73c-3.07 1.78-3.07 4.7 0 6.48l63.56 36.7c3.08 1.78 8.14 1.78 11.23 0ZM479.75 605.64c-3.07-1.79-8.13-1.79-11.22-.02l-63.57 36.71c-3.09 1.79-3.09 4.71 0 6.49l63.52 36.71c3.1 1.78 8.16 1.78 11.23 0l63.6-36.72c3.08-1.78 3.08-4.69 0-6.49l-63.57-36.68ZM285.23 441.43l63.54 36.7c3.08 1.78 8.14 1.78 11.22 0l63.59-36.71c3.07-1.78 3.07-4.71 0-6.49l-63.57-36.69c-3.07-1.78-8.13-1.78-11.22 0l-63.56 36.71c-3.08 1.78-3.08 4.7 0 6.49Z" />
            <path fill="currentColor" d="M1050.58 292.75 551.32 4.5C546.56 1.75 540.28.38 534 .38s-12.56 1.38-17.32 4.12L17.42 292.75c-9.53 5.5-17.32 19-17.32 30v576.5c0 11 7.79 24.5 17.32 30l499.26 288.25c4.76 2.75 11.04 4.12 17.32 4.12s12.56-1.38 17.32-4.12l499.26-288.25c9.53-5.5 17.32-19 17.32-30v-576.5c0-11-7.79-24.5-17.32-30ZM855.82 790.31c0 3.56-2.52 7.94-5.61 9.72l-130.97 75.63c-3.09 1.78-8.15 1.78-11.23 0L599.5 813c-3.09-1.77-8.15-1.77-11.23 0l-108.53 62.66c-3.07 1.78-8.13 1.78-11.22 0l-130.98-75.63c-3.1-1.78-5.61-6.16-5.61-9.72V665.02c0-3.56-2.53-7.94-5.62-9.72l-108.53-62.65c-3.08-1.78-5.61-6.16-5.61-9.73V431.67c0-3.56 2.54-7.94 5.61-9.71l130.99-75.63c3.09-1.78 8.15-1.78 11.22 0l108.53 62.65c3.09 1.78 8.15 1.78 11.22 0l108.51-62.65c3.1-1.78 8.15-1.78 11.23 0l130.99 75.63c3.09 1.78 5.61 6.15 5.61 9.71v125.3c0 3.57 2.55 7.96 5.63 9.74l108.51 62.64c3.1 1.78 5.61 6.16 5.61 9.73v151.24Z" />
            <path fill="currentColor" d="m805.27 655.29-86.03-49.67c-3.09-1.78-8.15-1.78-11.23 0L479.72 737.43c-3.07 1.79-8.14 1.79-11.23 0l-85.99-49.67c-3.1-1.79-5.61-.34-5.61 3.23v73.37c0 3.58 2.52 7.96 5.61 9.74l86.03 49.67c3.09 1.78 8.15 1.78 11.22 0l228.3-131.81c3.08-1.78 8.13-1.78 11.22 0l86 49.68c3.1 1.78 5.61.32 5.61-3.24v-73.39c0-3.57-2.52-7.95-5.61-9.73Z" />
            <path fill="currentColor" d="m782.8 780.58-63.54-36.71c-3.09-1.78-8.14-1.78-11.23 0l-63.6 36.74c-3.1 1.78-3.1 4.69 0 6.47l63.57 36.7c3.08 1.78 8.14 1.78 11.23 0l63.57-36.71c3.1-1.78 3.1-4.71 0-6.49Z" />
          </svg>
          <h1 class="font-display text-2xl font-bold tracking-tight text-stone-700 dark:text-stone-300">
            shop2tax
          </h1>
        </div>

        <!-- Desktop heading -->
        <div class="hidden lg:block">
          <h2 class="font-display text-2xl font-semibold tracking-tight text-stone-700 dark:text-stone-300">
            Willkommen zurück
          </h2>
          <p class="mt-2 text-stone-500 dark:text-stone-400">
            Melde dich an, um fortzufahren.
          </p>
        </div>

        <!-- Error Message -->
        <UAlert
          v-if="error"
          color="error"
          variant="soft"
          title="Anmeldung fehlgeschlagen"
          :description="error === 'oauth_failed' ? 'Google Anmeldung fehlgeschlagen. Bitte erneut versuchen.' : error"
        />

        <!-- Google login — no card wrapper, just the button -->
        <div class="space-y-4">
          <UButton
            to="/auth/google"
            external
            block
            size="xl"
            variant="solid"
            color="neutral"
            class="justify-center gap-3 rounded-xl py-3.5 text-base font-medium shadow-sm"
          >
            <svg class="size-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Mit Google anmelden
          </UButton>
        </div>

        <!-- GitHub link -->
        <a
          href="https://github.com/shop2tax/shop2tax"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1.5 text-sm text-stone-400 transition-colors hover:text-stone-600 dark:text-stone-500 dark:hover:text-stone-300"
        >
          <UIcon name="i-lucide-github" class="size-4" />
          Powered by shop2tax
        </a>
      </div>
    </div>
  </div>
</template>
