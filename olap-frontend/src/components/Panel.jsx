// A titled card that holds one table. `title` is usually the drill path,
// `actions` the view switches and export, `subheader` the scope sentence.
export default function Panel({ title, actions, subheader, footer, loading, children }) {
  return (
    <section className="panel" aria-busy={loading || undefined}>
      {loading && (
        <div className="panel-progress" role="progressbar" aria-label="Loading report">
          <span />
        </div>
      )}
      <header className="panel-head">
        <div className="panel-title">{title}</div>
        {actions && <div className="panel-actions">{actions}</div>}
      </header>
      {subheader && <div className="panel-sub">{subheader}</div>}
      <div className="panel-body">{children}</div>
      {footer && <footer className="panel-foot">{footer}</footer>}
    </section>
  )
}
