import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getReport } from '../api/client'
import type { ReportDetail } from '../types'

interface Props {
  reportId: string | null
}

export function ReportViewer({ reportId }: Props) {
  const [report, setReport] = useState<ReportDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!reportId) {
      setReport(null)
      return
    }
    setError(null)
    getReport(reportId)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [reportId])

  if (!reportId) return null

  return (
    <section className="panel">
      <h2>📄 5. レポート</h2>
      {error && <p className="error">{error}</p>}
      {report && (
        <div className="report-markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.markdown}</ReactMarkdown>
        </div>
      )}
    </section>
  )
}
