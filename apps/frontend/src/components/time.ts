/**
 * Formatting for the timestamps the API returns.
 *
 * Display only. Nothing here is compared, sorted or fed back to the backend: ordering is the
 * backend's, and a string parsed for display is never allowed to become an input to a
 * decision. An unparseable value is shown as it arrived rather than silently blanked.
 */
const TIME = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })
const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})

function parse(value: string): Date | null {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** A clock time, for a column where the day is already obvious from context. */
export function formatTime(value: string | null): string | null {
  if (value === null) return null
  const date = parse(value)
  return date === null ? value : TIME.format(date)
}

/** A date and a clock time, for anything that may fall outside today. */
export function formatDateTime(value: string | null): string | null {
  if (value === null) return null
  const date = parse(value)
  return date === null ? value : DATE_TIME.format(date)
}
