import { DATA_RANGE } from '../lib/dimensions.js'

// Error and empty states, written as directions rather than mood. Loading is
// shown by the panel's progress bar.
export default function ReportStatus({ loading, error, empty }) {
  if (error) {
    return (
      <div className="status is-error" role="alert">
        <strong>This report didn't load.</strong> {error} Check that the Go API is running on port 8080, then change a
        filter to try again.
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
