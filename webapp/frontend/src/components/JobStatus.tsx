import { useEffect, useRef, useState } from 'react'
import { useJobPolling } from '../hooks/useJobPolling'

interface Props {
  jobId: string | null
  onSucceeded: (reportId: string) => void
}

export function JobStatus({ jobId, onSucceeded }: Props) {
  const { job, error } = useJobPolling(jobId)
  const [elapsed, setElapsed] = useState(0)
  const notifiedJobIdRef = useRef<string | null>(null)

  useEffect(() => {
    if (!job || (job.status !== 'pending' && job.status !== 'running')) {
      return
    }
    const startMs = job.started_at ? new Date(job.started_at).getTime() : Date.now()
    setElapsed(Math.max(0, Math.floor((Date.now() - startMs) / 1000)))
    const timer = window.setInterval(() => {
      setElapsed(Math.max(0, Math.floor((Date.now() - startMs) / 1000)))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [job])

  useEffect(() => {
    if (job?.status === 'succeeded' && job.report_id && notifiedJobIdRef.current !== job.job_id) {
      notifiedJobIdRef.current = job.job_id
      onSucceeded(job.report_id)
    }
  }, [job, onSucceeded])

  if (!jobId) return null

  return (
    <section className="panel">
      <h2>🚦 4. 実行状況</h2>
      {error && <p className="error">{error}</p>}
      {job && (
        <div>
          <p>
            状態: <span className={`status-badge status-${job.status}`}>{statusEmoji(job.status)} {statusLabel(job.status)}</span>
            {job.stage ? ` — ${job.stage}` : ''}
          </p>
          {(job.status === 'pending' || job.status === 'running') && <p>⏱️ 経過時間: {elapsed}秒</p>}
          {job.status === 'failed' && <p className="error">エラー: {job.error}</p>}
          {job.status === 'succeeded' && <p className="success">🎉 分析が完了しました！レポートを確認してください。</p>}
        </div>
      )}
    </section>
  )
}

function statusLabel(status: string): string {
  switch (status) {
    case 'pending':
      return '待機中'
    case 'running':
      return '実行中'
    case 'succeeded':
      return '完了'
    case 'failed':
      return '失敗'
    default:
      return status
  }
}

function statusEmoji(status: string): string {
  switch (status) {
    case 'pending':
      return '⏳'
    case 'running':
      return '🔄'
    case 'succeeded':
      return '✅'
    case 'failed':
      return '❌'
    default:
      return '❔'
  }
}
