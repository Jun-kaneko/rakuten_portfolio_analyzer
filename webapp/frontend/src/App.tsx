import { useState } from 'react'
import './App.css'
import { PortfolioPanel } from './components/PortfolioPanel'
import { PreferencesEditor } from './components/PreferencesEditor'
import { RunOptions } from './components/RunOptions'
import { JobStatus } from './components/JobStatus'
import { ReportViewer } from './components/ReportViewer'
import { ReportHistory } from './components/ReportHistory'

function App() {
  const [portfolioFilename, setPortfolioFilename] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [reportId, setReportId] = useState<string | null>(null)
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0)

  function handleJobSucceeded(newReportId: string) {
    setReportId(newReportId)
    setHistoryRefreshKey((k) => k + 1)
  }

  return (
    <div className="app">
      <h1>
        <span className="app-title-emoji">📈</span> <span className="app-title-text">ポートフォリオ分析システム</span>
      </h1>
      <PortfolioPanel selected={portfolioFilename} onSelect={setPortfolioFilename} />
      <PreferencesEditor portfolioFilename={portfolioFilename} />
      <RunOptions portfolioFilename={portfolioFilename} onStarted={setJobId} />
      <JobStatus jobId={jobId} onSucceeded={handleJobSucceeded} />
      <ReportViewer reportId={reportId} />
      <ReportHistory onSelect={setReportId} refreshKey={historyRefreshKey} />
    </div>
  )
}

export default App
