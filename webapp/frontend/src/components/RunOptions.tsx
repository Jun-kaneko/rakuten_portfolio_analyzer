import { useState } from 'react'
import { startAnalysis } from '../api/client'

interface Props {
  portfolioFilename: string | null
  onStarted: (jobId: string) => void
}

export function RunOptions({ portfolioFilename, onStarted }: Props) {
  const [cacheOnly, setCacheOnly] = useState(false)
  const [noNews, setNoNews] = useState(false)
  const [noRecommend, setNoRecommend] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    if (!portfolioFilename) return
    setStarting(true)
    setError(null)
    try {
      const res = await startAnalysis({
        portfolio_filename: portfolioFilename,
        cache_only: cacheOnly,
        no_news: noNews,
        no_recommend: noRecommend,
      })
      onStarted(res.job_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  return (
    <section className="panel">
      <h2>⚙️ 3. 実行オプション</h2>
      <label className="checkbox-row">
        <input type="checkbox" checked={cacheOnly} onChange={(e) => setCacheOnly(e.target.checked)} />
        🗄️ キャッシュのみ使用（Yahoo Financeへ問い合わせない。おすすめ銘柄提案も自動でスキップされます）
      </label>
      <label className="checkbox-row">
        <input type="checkbox" checked={noNews} onChange={(e) => setNoNews(e.target.checked)} />
        📰 ニュース取得をスキップ（実行時間短縮）
      </label>
      <label className="checkbox-row">
        <input type="checkbox" checked={noRecommend} onChange={(e) => setNoRecommend(e.target.checked)} />
        💡 おすすめ新規投資候補の提案をスキップ
      </label>
      <div className="field">
        <button type="button" className="btn btn-run" onClick={handleRun} disabled={!portfolioFilename || starting}>
          {starting ? '⏳ 実行中...' : '🚀 分析を実行'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  )
}
