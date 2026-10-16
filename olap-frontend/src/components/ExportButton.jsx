import { DownloadIcon } from './Icons.jsx'

export default function ExportButton({ onClick, disabled }) {
  return (
    <button type="button" className="button" onClick={onClick} disabled={disabled}>
      <DownloadIcon className="button-icon" />
      Export CSV
    </button>
  )
}
