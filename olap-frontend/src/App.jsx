import { useEffect, useState } from 'react'
import { REPORTS } from './reports/index.js'
import { isMock } from './api/client.js'
import { DATA_RANGE } from './lib/dimensions.js'
import Logo from './components/Logo.jsx'

// The open report lives in the URL hash (#r1, #r2, ...) so a refresh or a
// shared link lands on the same report.
const reportFromHash = () => {
  const id = window.location.hash.replace('#', '')
  return REPORTS.some((r) => r.id === id) ? id : REPORTS[0].id
}

export default function App() {
  const [activeId, setActiveId] = useState(reportFromHash)

  useEffect(() => {
    const onHashChange = () => setActiveId(reportFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const active = REPORTS.find((r) => r.id === activeId)
  const Report = active.component

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Logo className="brand-mark" />
          <span className="brand-name">Road Runner</span>
        </div>
        <nav className="nav" aria-label="Reports">
          <p className="nav-label">Reports</p>
          <ul className="report-nav">
            {REPORTS.map((r) => {
              const Icon = r.icon
              return (
                <li key={r.id}>
                  <a href={`#${r.id}`} className="report-link" aria-current={r.id === activeId ? 'page' : undefined}>
                    <Icon className="report-icon" />
                    <span>{r.name}</span>
                  </a>
                </li>
              )
            })}
          </ul>
        </nav>
      </aside>

      <div className="main">
        <header className="topbar">
          <nav className="crumbs" aria-label="Breadcrumb">
            <span>Reports</span>
            <span className="crumbs-sep" aria-hidden="true">/</span>
            <span aria-current="page">{active.name}</span>
          </nav>
          <div className="topbar-meta">
            {isMock && (
              <span
                className="badge badge-warn"
                title="Numbers are sample data. Set VITE_API_MODE=live in olap-frontend/.env.local to load warehouse results."
              >
                Sample data
              </span>
            )}
            <span className="topbar-range">Deliveries {DATA_RANGE}</span>
          </div>
        </header>

        <main className="page">
          <header className="page-header">
            <h1>{active.name}</h1>
            <p>{active.question}</p>
          </header>
          <Report key={active.id} />
        </main>
      </div>
    </div>
  )
}
