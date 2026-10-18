import { REPORTS } from './reports/index.js'
import ErrorPage from './components/ErrorPage.jsx'

// Shown for a link to a page that doesn't exist (#r9, a typo, an old bookmark),
// with the way back: home, or straight to a report.
export default function NotFound({ hash }) {
  return (
    <ErrorPage
      code="Page not found"
      title="There's no page at this link"
      actions={
        <a href="#home" className="button button-primary">
          Go to the home page
        </a>
      }
    >
      <p>
        {hash ? (
          <>
            Nothing lives at <code>{hash}</code>.{' '}
          </>
        ) : null}
        The link may be mistyped or out of date. Pick a report instead:
      </p>
      <ul className="error-page-links">
        {REPORTS.map((r) => (
          <li key={r.id}>
            <a href={`#${r.id}`}>{r.name}</a>
          </li>
        ))}
      </ul>
    </ErrorPage>
  )
}
