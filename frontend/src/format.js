// Small helpers that turn raw values from the API into text people can read.

const MONEY_WORDS = /(revenue|sales|amount|price|cost|value|spend|spent|profit|turnover|income|earnings|aov)/
const NOT_MONEY_WORDS = /(quantity|qty|count|units|number|percent|pct|share|rate|stock)/

export function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

// "customer_id" holds name tags, not amounts, so it should never be charted or summed.
export function isIdColumn(name) {
  return /(^|_)id$/i.test(name)
}

export function isMoneyColumn(name) {
  const lower = name.toLowerCase()
  return MONEY_WORDS.test(lower) && !NOT_MONEY_WORDS.test(lower)
}

// "total_revenue" -> "Total revenue"
export function prettyColumn(name) {
  const text = name.replace(/_/g, ' ').trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

// "2026-01-01T00:00:00" -> "2026-01-01" (the time adds nothing when it is midnight)
export function shortDate(value) {
  return typeof value === 'string' ? value.replace(/T00:00:00(\.0+)?$/, '') : String(value)
}

// 184276.54 -> "$184,276.54" for a money column, "184,276.54" otherwise.
export function formatNumber(value, column = '') {
  if (isIdColumn(column)) return String(value)
  if (isMoneyColumn(column)) {
    return value.toLocaleString('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
      maximumFractionDigits: 2,
    })
  }
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

// Short form for chart axes, where space is tight: 184276.54 -> "$184K"
export function formatCompact(value, column = '') {
  const text = value.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 1 })
  return isMoneyColumn(column) ? `$${text}` : text
}

// Any table cell as text.
export function formatCell(value, column) {
  if (value === null || value === undefined) return '—' // a dash for "no value"
  if (isNumber(value)) return formatNumber(value, column)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return shortDate(value)
}

// For a chart we need one column of labels and one column of numbers.
// Returns their positions, or null if the rows don't have both.
export function pickChartColumns(columns, rows) {
  const hasNumbers = (i) =>
    !isIdColumn(columns[i]) && rows.some((row) => isNumber(row[i])) &&
    rows.every((row) => row[i] === null || isNumber(row[i]))
  const hasText = (i) => rows.some((row) => typeof row[i] === 'string')

  const valueIndex = columns.findIndex((_, i) => hasNumbers(i))
  let labelIndex = columns.findIndex((_, i) => hasText(i))
  if (labelIndex === -1) {
    // No text column (e.g. customer_id + total): use the first other column as the label.
    labelIndex = columns.findIndex((_, i) => i !== valueIndex)
  }
  if (valueIndex === -1 || labelIndex === -1) return null
  return { labelIndex, valueIndex }
}

// "2026-10-12T20:28:52Z" -> "Oct 12" (or the time, if it was today)
export function formatWhen(isoText) {
  const when = new Date(isoText)
  if (Number.isNaN(when.getTime())) return ''
  const today = new Date()
  if (when.toDateString() === today.toDateString()) {
    return when.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  }
  return when.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
