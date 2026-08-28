export default defineAppConfig({
  ui: {
    colors: {
      primary: 'blue',
      neutral: 'stone',
    },
    input: { slots: { root: 'w-full' } },
    select: { slots: { base: 'w-full' } },
    selectMenu: { slots: { base: 'w-full' } },
    textarea: { slots: { root: 'w-full' } },
    alert: {
      compoundVariants: [
        {
          color: 'warning' as const,
          variant: 'soft' as const,
          class: {
            root: 'bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200',
            icon: 'text-amber-600 dark:text-amber-400',
          },
        },
      ],
    },
    button: {
      compoundVariants: [
        {
          color: 'warning' as const,
          variant: 'soft' as const,
          class: 'text-amber-800 bg-amber-100 hover:bg-amber-200 dark:text-amber-200 dark:bg-amber-900/50 dark:hover:bg-amber-900',
        },
      ],
    },
  },
})
