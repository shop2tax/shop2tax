import type { TaxRule } from '~/types/api'

/** Check if a tax rule is any Reverse Charge (§13b) variant. */
export function isReverseCharge(rule: TaxRule | string): boolean {
  return rule.startsWith('rc_') || rule === 'reverse_charge'
}
