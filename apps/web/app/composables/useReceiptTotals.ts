import { isReverseCharge } from '~/utils/tax'

/**
 * Computes Netto / USt breakdown / Brutto from line items.
 * Works with both form line items (new.vue) and API response line items ([id].vue).
 *
 * Handles Reverse Charge (§13b) items: amount is NET, RC tax shown separately.
 *
 * @param items - Line items with amount, tax_rate, tax_rule
 * @param rcTaxRate - RC tax rate from SiteSettings (e.g., 0.19 for 19%)
 */

export function useReceiptTotals(
  items: Ref<{ amount: string, tax_rate: string, tax_rule: string }[]>,
  rcTaxRate: Ref<number>,
) {
  const totalNetto = computed(() => {
    return items.value.reduce((sum, item) => {
      const amount = Number.parseFloat(item.amount) || 0
      const rate = Number.parseFloat(item.tax_rate) || 0

      // RC items: amount is already NET
      if (isReverseCharge(item.tax_rule)) {
        return sum + amount
      }

      // Tax included: extract net from gross
      if (item.tax_rule === 'tax_included' && rate > 0) {
        return sum + amount / (1 + rate / 100)
      }

      // Tax excluded or no_tax: amount is NET
      return sum + amount
    }, 0)
  })

  const taxBreakdown = computed(() => {
    const byRate = new Map<string, number>()
    for (const item of items.value) {
      const amount = Number.parseFloat(item.amount) || 0
      const rate = Number.parseFloat(item.tax_rate) || 0

      // No tax or zero rate: skip
      if (rate === 0 || item.tax_rule === 'no_tax')
        continue

      let tax = 0

      // RC items: use SiteSettings rc_tax_rate
      if (isReverseCharge(item.tax_rule)) {
        tax = amount * rcTaxRate.value
        const key = '§13b USt'
        byRate.set(key, (byRate.get(key) || 0) + tax)
        continue
      }

      // Tax included: extract tax from gross
      if (item.tax_rule === 'tax_included') {
        tax = amount - amount / (1 + rate / 100)
      }
      // Tax excluded: calculate tax on net
      else if (item.tax_rule === 'tax_excluded') {
        tax = amount * (rate / 100)
      }

      const key = `${rate}%`
      byRate.set(key, (byRate.get(key) || 0) + tax)
    }
    return Array.from(byRate.entries()).map(([rate, amount]) => ({ rate, amount }))
  })

  // Total RC tax (separate from regular tax for display purposes)
  const totalRcTax = computed(() => {
    return items.value.reduce((sum, item) => {
      if (!isReverseCharge(item.tax_rule))
        return sum
      const amount = Number.parseFloat(item.amount) || 0
      return sum + amount * rcTaxRate.value
    }, 0)
  })

  const totalBrutto = computed(() => {
    return totalNetto.value + taxBreakdown.value.reduce((sum, t) => sum + t.amount, 0)
  })

  return { totalNetto, taxBreakdown, totalBrutto, totalRcTax }
}
