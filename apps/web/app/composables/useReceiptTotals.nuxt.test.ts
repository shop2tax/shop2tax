// @vitest-environment nuxt
import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { useReceiptTotals } from './useReceiptTotals'

function totals(items: { amount: string, tax_rate: string, tax_rule: string }[], rcTaxRate = 0.19) {
  return useReceiptTotals(ref(items), ref(rcTaxRate))
}

describe('useReceiptTotals', () => {
  it('returns zeros for no line items', () => {
    const { totalNetto, taxBreakdown, totalBrutto, totalRcTax } = totals([])
    expect(totalNetto.value).toBe(0)
    expect(taxBreakdown.value).toEqual([])
    expect(totalBrutto.value).toBe(0)
    expect(totalRcTax.value).toBe(0)
  })

  it('treats tax_excluded amounts as net and adds tax on top', () => {
    const { totalNetto, taxBreakdown, totalBrutto } = totals([
      { amount: '100', tax_rate: '19', tax_rule: 'tax_excluded' },
    ])
    expect(totalNetto.value).toBeCloseTo(100, 2)
    expect(taxBreakdown.value).toEqual([{ rate: '19%', amount: 19 }])
    expect(totalBrutto.value).toBeCloseTo(119, 2)
  })

  it('extracts net and tax from a tax_included (gross) amount', () => {
    const { totalNetto, taxBreakdown, totalBrutto } = totals([
      { amount: '119', tax_rate: '19', tax_rule: 'tax_included' },
    ])
    expect(totalNetto.value).toBeCloseTo(100, 2)
    expect(taxBreakdown.value).toEqual([{ rate: '19%', amount: expect.closeTo(19, 2) }])
    expect(totalBrutto.value).toBeCloseTo(119, 2)
  })

  it('skips tax for no_tax items', () => {
    const { totalNetto, taxBreakdown, totalBrutto, totalRcTax } = totals([
      { amount: '50', tax_rate: '0', tax_rule: 'no_tax' },
    ])
    expect(totalNetto.value).toBeCloseTo(50, 2)
    expect(taxBreakdown.value).toEqual([])
    expect(totalBrutto.value).toBeCloseTo(50, 2)
    expect(totalRcTax.value).toBe(0)
  })

  it('handles reverse charge (§13b): net amount with separately computed RC tax', () => {
    const { totalNetto, taxBreakdown, totalRcTax } = totals([
      { amount: '200', tax_rate: '19', tax_rule: 'reverse_charge' },
    ], 0.19)
    expect(totalNetto.value).toBeCloseTo(200, 2)
    expect(taxBreakdown.value).toEqual([{ rate: '§13b USt', amount: 38 }])
    expect(totalRcTax.value).toBeCloseTo(38, 2)
  })

  it('aggregates tax per rate across multiple items', () => {
    const { taxBreakdown, totalNetto, totalBrutto } = totals([
      { amount: '100', tax_rate: '19', tax_rule: 'tax_excluded' },
      { amount: '200', tax_rate: '19', tax_rule: 'tax_excluded' },
      { amount: '100', tax_rate: '7', tax_rule: 'tax_excluded' },
    ])
    expect(totalNetto.value).toBeCloseTo(400, 2)
    const byRate = Object.fromEntries(taxBreakdown.value.map(t => [t.rate, t.amount]))
    expect(byRate['19%']).toBeCloseTo(57, 2) // 19% of 300
    expect(byRate['7%']).toBeCloseTo(7, 2)
    expect(totalBrutto.value).toBeCloseTo(464, 2)
  })

  it('reacts to changes in the underlying items ref', () => {
    const items = ref([{ amount: '100', tax_rate: '19', tax_rule: 'tax_excluded' }])
    const { totalBrutto } = useReceiptTotals(items, ref(0.19))
    expect(totalBrutto.value).toBeCloseTo(119, 2)
    items.value = [{ amount: '50', tax_rate: '7', tax_rule: 'tax_excluded' }]
    expect(totalBrutto.value).toBeCloseTo(53.5, 2)
  })
})
