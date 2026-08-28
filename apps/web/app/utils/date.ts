/**
 * Return the next day after dateStr as ISO date string (YYYY-MM-DD).
 */
export function nextDayIso(dateStr: string): string {
  const date = new Date(dateStr)
  date.setDate(date.getDate() + 1)
  return date.toISOString().slice(0, 10)
}

/**
 * Today as ISO date string (YYYY-MM-DD).
 */
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}
