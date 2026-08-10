import { useEffect, useState } from 'react'
import { listReports } from '../api/client'
import type { ReportSummary } from '../types'

interface Props {
  onSelect: (reportId: string) => void
  refreshKey: number
}

export function ReportHistory({ onSelect, refreshKey }: Props) {
  const [reports, setReports] = useState<ReportSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listReports()
      .then(setReports)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [refreshKey])

  return (
    <section className="panel">
      <h2>🗂️ 6. 過去レポート履歴</h2>
      {error && <p className="error">{error}</p>}
      {reports.length === 0 && <p>まだレポートがありません。</p>}
      <ul className="report-history">
        {reports.map((r) => (
          <li key={r.report_id}>
            <button type="button" onClick={() => onSelect(r.report_id)}>
              📅 {r.created_at} — 📁 {r.portfolio_filename}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
