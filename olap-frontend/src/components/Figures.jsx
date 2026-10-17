// KPI cards for the current view. Item: { label, value, title?, sub?, text? }
// `text` marks a word value (a category or product name) so it's set smaller.
export default function Figures({ items }) {
  return (
    <dl className="figures">
      {items.map((item) => (
        <div key={item.label} className="figure">
          <dt>{item.label}</dt>
          <dd className={item.text ? 'figure-value is-text' : 'figure-value'} title={item.title}>
            {item.value}
          </dd>
          {item.sub && <dd className="figure-sub">{item.sub}</dd>}
        </div>
      ))}
    </dl>
  )
}
