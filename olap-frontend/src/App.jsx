import { useEffect, useState } from 'react'
import { REPORTS } from './reports/index.js'
import { isMock } from './api/client.js'
import { DATA_RANGE } from './lib/dimensions.js'
import { HOME, NOT_FOUND, routeFromHash } from './lib/route.js'
import Logo from './components/Logo.jsx'
import ThemeToggle from './components/ThemeToggle.jsx'
import { HomeIcon } from './components/Icons.jsx'
import Home from './Home.jsx'
import NotFound from './NotFound.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'

// The open page lives in the URL hash (#r1, #r2, ... or #home) so a refresh or
// a shared link lands on the same page. No hash opens the home page, and an
// unknown hash the not-found page.
const REPORT_IDS = REPORTS.map((r) => r.id)

export default function App() {
  // The hash itself, not just the page it opens, so moving between two unknown
  // links still updates the not-found page.
  const [hash, setHash] = useState(() => window.location.hash)

  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const activeId = routeFromHash(hash, REPORT_IDS)

  const isHome = activeId === HOME
  const isNotFound = activeId === NOT_FOUND
  const active = REPORTS.find((r) => r.id === activeId)
  const Report = active?.component

  return (
    <div className="app">
      <aside className="sidebar">
        <a href="#home" className="brand" aria-label="Road Runner home">
          <Logo className="brand-mark" />
          <span className="brand-name">Road Runner</span>
        </a>
        <nav className="nav" aria-label="Reports">
          <a href="#home" className="report-link home-link" aria-current={isHome ? 'page' : undefined}>
            <HomeIcon className="report-icon" />
            <span>Home</span>
          </a>
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
        <div className="sidebar-foot">
          <ThemeToggle />
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <nav className="crumbs" aria-label="Breadcrumb">
            {isHome ? (
              <span aria-current="page">Home</span>
            ) : (
              <>
                <a href="#home" className="crumbs-link">
                  Home
                </a>
                <span className="crumbs-sep" aria-hidden="true">/</span>
                <span aria-current="page">{isNotFound ? 'Page not found' : active.name}</span>
              </>
            )}
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
          <ErrorBoundary key={activeId}>
            {isHome ? (
              <Home />
            ) : isNotFound ? (
              <NotFound hash={hash} />
            ) : (
              <>
                <header className="page-header">
                  <h1>{active.name}</h1>
                  <p>{active.question}</p>
                </header>
                <Report key={active.id} />
              </>
            )}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
