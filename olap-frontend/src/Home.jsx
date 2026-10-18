import { REPORTS } from './reports/index.js'
import { DATA_RANGE } from './lib/dimensions.js'
import Logo from './components/Logo.jsx'
import { ArrowRightIcon } from './components/Icons.jsx'

// The landing page: the title, what the dashboard covers, and a card per
// report to open it. Static on purpose: it requests no data, so each report
// stays the only place its numbers come from.
export default function Home() {
  return (
    <div className="home">
      <header className="home-hero">
        <Logo className="home-mark" />
        <h1 className="home-title">Road Runner</h1>
        <p className="home-sub">Last-mile logistics analytics</p>
        <p className="home-lead">
          A year of deliveries from the data warehouse, read four ways: what was delivered, who carried it, which
          customers it served, and when the demand landed. Open a report to slice, dice and drill into it.
        </p>
        <p className="home-meta">Deliveries {DATA_RANGE}</p>
      </header>

      <section aria-labelledby="home-reports">
        <h2 id="home-reports" className="home-heading">
          Reports
        </h2>
        <ul className="home-grid">
          {REPORTS.map((r) => {
            const Icon = r.icon
            return (
              <li key={r.id}>
                <a href={`#${r.id}`} className="home-card">
                  <span className="home-card-top">
                    <Icon className="home-card-icon" />
                    <span className="home-card-tag">{r.id.toUpperCase()}</span>
                  </span>
                  <h3 className="home-card-title">{r.name}</h3>
                  <p className="home-card-question">{r.question}</p>
                  <p className="home-card-explore">{r.explore}</p>
                  <span className="home-card-open">
                    Open report <ArrowRightIcon className="home-card-arrow" />
                  </span>
                </a>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}
