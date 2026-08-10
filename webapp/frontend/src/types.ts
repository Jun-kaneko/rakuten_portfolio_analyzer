export interface PortfolioFile {
  filename: string
  uploaded_at: string
  size_bytes: number
}

export interface PreferenceRecord {
  code: string
  name: string
  affection_score: number
}

export interface AnalyzeRequest {
  portfolio_filename: string
  preferences_filename?: string | null
  cache_only?: boolean
  no_news?: boolean
  no_recommend?: boolean
}

export type JobStatusValue = 'pending' | 'running' | 'succeeded' | 'failed'

export interface JobStatusResponse {
  job_id: string
  status: JobStatusValue
  stage: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  report_id: string | null
  request: Record<string, unknown>
}

export interface ReportSummary {
  report_id: string
  created_at: string
  portfolio_filename: string
  preferences_filename: string
  options: Record<string, unknown>
}

export interface ReportDetail extends ReportSummary {
  markdown: string
}
