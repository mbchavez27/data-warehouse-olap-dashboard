// What the URL hash opens: the home page (no hash or #home), a report's id
// (#r1 .. #r4), or the not-found page for anything else, such as a stale or
// mistyped link.
export const HOME = 'home'
export const NOT_FOUND = 'not-found'

export const routeFromHash = (hash, reportIds) => {
  const id = String(hash ?? '').replace(/^#/, '')
  if (id === '' || id === HOME) return HOME
  return reportIds.includes(id) ? id : NOT_FOUND
}
