/**
 * Shared formatting utilities for currency and dates.
 * Used across transactions, receipts, and other pages.
 */
export function useFormatters() {
  /**
   * Format a decimal amount string as German currency (EUR).
   * API returns amounts as strings to preserve precision.
   */
  function formatCurrency(amount: string | number): string {
    const value = typeof amount === 'string' ? Number.parseFloat(amount) : amount
    return value.toLocaleString('de-DE', { style: 'currency', currency: 'EUR' })
  }

  /**
   * Format an ISO date string as German locale date (dd.mm.yyyy).
   * Pinned to Europe/Berlin to avoid SSR hydration mismatches.
   */
  function formatDate(date: string): string {
    return new Date(date).toLocaleDateString('de-DE', { timeZone: 'Europe/Berlin' })
  }

  /**
   * Format an ISO datetime string as German locale datetime (dd.mm.yyyy, HH:MM).
   * Pinned to Europe/Berlin to avoid SSR hydration mismatches.
   */
  function formatDateTime(date: string): string {
    return new Date(date).toLocaleString('de-DE', {
      timeZone: 'Europe/Berlin',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  function amountColorClass(amount: string | number): string {
    const value = typeof amount === 'string' ? Number.parseFloat(amount) : amount
    return value >= 0 ? 'text-emerald-600' : 'text-red-500'
  }

  function receiptTypeLabel(type: string): string {
    return type === 'revenue' ? 'Einnahme' : 'Ausgabe'
  }

  function receiptTypeColor(type: string): 'success' | 'error' {
    return type === 'revenue' ? 'success' : 'error'
  }

  return {
    formatCurrency,
    formatDate,
    formatDateTime,
    amountColorClass,
    receiptTypeLabel,
    receiptTypeColor,
  }
}
