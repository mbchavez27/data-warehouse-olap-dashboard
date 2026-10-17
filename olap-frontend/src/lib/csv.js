// Downloads the rows on screen as a CSV file. Headers are the column labels
// the user sees; values are the raw numbers (not the ₱1.2B display format),
// so the file opens cleanly in Excel or Sheets.
export function downloadCsv(filename, columns, rows) {
  const cell = (v) => {
    if (v === null || v === undefined) return ''
    const s = String(v)
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [
    columns.map((c) => cell(c.label)).join(','),
    ...rows.map((r) => columns.map((c) => cell(c.csv ? c.csv(r) : r[c.key])).join(',')),
  ]
  // The BOM makes Excel read ₱ and other non-ASCII text correctly.
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const slug = (text) =>
  String(text)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
