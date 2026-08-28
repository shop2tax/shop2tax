import { describe, expect, it } from 'vitest'
import { isReverseCharge } from './tax'

describe('isReverseCharge', () => {
  it('matches the legacy reverse_charge rule', () => {
    expect(isReverseCharge('reverse_charge')).toBe(true)
  })

  it('matches any rc_ prefixed §13b variant', () => {
    expect(isReverseCharge('rc_eu_services')).toBe(true)
    expect(isReverseCharge('rc_construction')).toBe(true)
  })

  it('rejects standard tax rules', () => {
    expect(isReverseCharge('standard')).toBe(false)
    expect(isReverseCharge('reduced')).toBe(false)
    expect(isReverseCharge('exempt')).toBe(false)
  })

  it('does not match rules that merely contain rc_', () => {
    expect(isReverseCharge('source_rc_eu')).toBe(false)
  })
})
