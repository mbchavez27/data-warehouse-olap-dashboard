import { DATA_RANGE } from '../lib/dimensions.js'

// Error and empty states, written as directions rather than mood. Loading is
// shown by the panel's progress bar. `onRetry` (useReport's retry) adds a
// "Try again" button to the error.
export default function ReportStatus({ loading, error, empty, onRetry }) {
  if (error) {
    return (
      <div className="status is-error" role="alert">
        <p>
          <strong>This report didn't load.</strong> {error} The report service may be down or restarting; try again
          in a moment.
        </p>
        {onRetry && (
          <button type="button" className="button status-retry" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    )
  }
  if (empty && !loading) {
    return (
      <div className="status">
        <strong>No deliveries match these filters.</strong> The data covers {DATA_RANGE}, so try another period or clear
        a filter.
      </div>
    )
  }
  return null
}
