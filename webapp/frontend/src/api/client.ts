import type {
  AnalyzeRequest,
  JobStatusResponse,
  PortfolioFile,
  PreferenceRecord,
  ReportDetail,
  ReportSummary,
} from '../types'

async function extractErrorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data.detail === 'string') return data.detail
    if (data.detail) return JSON.stringify(data.detail)
  } catch {
    // レスポンスボディがJSONでない場合はそのままフォールバックする
  }
  return res.statusText || `HTTP ${res.status}`
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: options?.body
      ? { 'Content-Type': 'application/json', ...(options.headers ?? {}) }
      : options?.headers,
  })
  if (!res.ok) {
    throw new Error(await extractErrorDetail(res))
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

export function listPortfolios(): Promise<PortfolioFile[]> {
  return request('/api/portfolios')
}

export async function uploadPortfolio(file: File): Promise<PortfolioFile> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch('/api/portfolios', { method: 'POST', body: formData })
  if (!res.ok) {
    throw new Error(await extractErrorDetail(res))
  }
  return (await res.json()) as PortfolioFile
}

export function getPreferences(portfolio?: string | null): Promise<PreferenceRecord[]> {
  const query = portfolio ? `?portfolio=${encodeURIComponent(portfolio)}` : ''
  return request(`/api/preferences${query}`)
}

export function savePreferences(records: PreferenceRecord[]): Promise<PreferenceRecord[]> {
  return request('/api/preferences', {
    method: 'PUT',
    body: JSON.stringify(records),
  })
}

export function startAnalysis(payload: AnalyzeRequest): Promise<{ job_id: string; status: string }> {
  return request('/api/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`)
}

export function listReports(): Promise<ReportSummary[]> {
  return request('/api/reports')
}

export function getReport(reportId: string): Promise<ReportDetail> {
  return request(`/api/reports/${encodeURIComponent(reportId)}`)
}
