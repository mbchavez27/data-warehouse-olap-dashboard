import Logo from './Logo.jsx'

// Full-page message for when a page can't be shown: an unknown link, or a crash
// caught by ErrorBoundary. Says what happened and what to do next, then offers
// the way out. `children` are the actions (links or buttons); `details` is an
// optional technical note kept folded away.
export default function ErrorPage({ code, title, children, actions, details }) {
  return (
    <section className="error-page" role="alert" aria-labelledby="error-page-title">
      <Logo className="error-page-mark" />
      {code && <p className="error-page-code">{code}</p>}
      <h1 id="error-page-title" className="error-page-title">
        {title}
      </h1>
      <div className="error-page-body">{children}</div>
      {actions && <div className="error-page-actions">{actions}</div>}
      {details && (
        <details className="error-page-details">
          <summary>Technical details</summary>
          <pre>{details}</pre>
        </details>
      )}
    </section>
  )
}
