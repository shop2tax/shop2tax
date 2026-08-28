import { describe, expect, it } from 'vitest'
import { useFormatters } from './useFormatters'

// Intl currency output separates the amount and symbol with a narrow no-break
// space (U+202F) whose codepoint varies across ICU versions. Normalise all
// whitespace to a plain space so assertions stay on the content, not the runtime.
function normalizeSpaces(value: string): string {
  return value.replace(/\s/g, ' ')
}

const { formatCurrency, formatDate, amountColorClass, receiptTypeLabel, receiptTypeColor } = useFormatters()

describe('formatCurrency', () => {
  it('formats a positive number as German EUR', () => {
    expect(normalizeSpaces(formatCurrency(1234.56))).toBe('1.234,56 €')
  })

  it('parses string amounts from the API', () => {
    expect(normalizeSpaces(formatCurrency('1234.56'))).toBe('1.234,56 €')
  })

  it('formats negative amounts with a leading minus', () => {
    expect(normalizeSpaces(formatCurrency(-42))).toBe('-42,00 €')
  })

  it('formats zero', () => {
    expect(normalizeSpaces(formatCurrency(0))).toBe('0,00 €')
  })
})

describe('formatDate', () => {
  it('renders an ISO date as German dd.mm.yyyy', () => {
    expect(formatDate('2026-03-15')).toBe('15.3.2026')
  })
})

describe('amountColorClass', () => {
  it('marks non-negative amounts as positive', () => {
    expect(amountColorClass(0)).toBe('text-emerald-600')
    expect(amountColorClass('10.00')).toBe('text-emerald-600')
  })

  it('marks negative amounts as negative', () => {
    expect(amountColorClass(-0.01)).toBe('text-red-500')
  })
})

describe('receipt type helpers', () => {
  it('labels revenue and expense in German', () => {
    expect(receiptTypeLabel('revenue')).toBe('Einnahme')
    expect(receiptTypeLabel('expense')).toBe('Ausgabe')
  })

  it('maps revenue to success and expense to error', () => {
    expect(receiptTypeColor('revenue')).toBe('success')
    expect(receiptTypeColor('expense')).toBe('error')
  })
})
