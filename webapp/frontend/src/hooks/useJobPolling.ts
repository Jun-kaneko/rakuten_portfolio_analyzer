import { useEffect, useRef, useState } from 'react'
import { getJob } from '../api/client'
import type { JobStatusResponse } from '../types'

const POLL_INTERVAL_MS = 2000

/** pending/running中のジョブを定期ポーリングし、完了したら自動で止まるフック。 */
export function useJobPolling(jobId: string | null) {
  const [job, setJob] = useState<JobStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    setJob(null)
    setError(null)
    if (!jobId) {
      return
    }
    let cancelled = false

    async function poll() {
      try {
        const data = await getJob(jobId as string)
        if (cancelled) return
        setJob(data)
        if (data.status === 'pending' || data.status === 'running') {
          timerRef.current = window.setTimeout(poll, POLL_INTERVAL_MS)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }

    poll()
    return () => {
      cancelled = true
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [jobId])

  return { job, error }
}
