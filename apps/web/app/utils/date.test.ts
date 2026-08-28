import { describe, expect, it } from 'vitest'
import { nextDayIso } from './date'

describe('nextDayIso', () => {
  it('returns the following calendar day', () => {
    expect(nextDayIso('2026-03-15')).toBe('2026-03-16')
  })

  it('rolls over month boundaries', () => {
    expect(nextDayIso('2026-01-31')).toBe('2026-02-01')
  })

  it('rolls over year boundaries', () => {
    expect(nextDayIso('2026-12-31')).toBe('2027-01-01')
  })

  it('handles leap day correctly', () => {
    expect(nextDayIso('2028-02-28')).toBe('2028-02-29')
    expect(nextDayIso('2028-02-29')).toBe('2028-03-01')
  })
})
