import { useEffect, useRef, useState } from 'react'
import { listPortfolios, uploadPortfolio } from '../api/client'
import type { PortfolioFile } from '../types'

interface Props {
  selected: string | null
  onSelect: (filename: string) => void
}

export function PortfolioPanel({ selected, onSelect }: Props) {
  const [portfolios, setPortfolios] = useState<PortfolioFile[]>([])
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function refresh(preferFilename?: string) {
    try {
      const data = await listPortfolios()
      setPortfolios(data)
      if (preferFilename) {
        onSelect(preferFilename)
      } else if (!selected && data.length > 0) {
        onSelect(data[0].filename)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    refresh()
    // 初回マウント時のみ実行する
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const uploaded = await uploadPortfolio(file)
      await refresh(uploaded.filename)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <section className="panel">
      <h2>📁 1. ポートフォリオ選択</h2>
      <div className="field">
        <select value={selected ?? ''} onChange={(e) => onSelect(e.target.value)}>
          <option value="" disabled>
            選択してください
          </option>
          {portfolios.map((p) => (
            <option key={p.filename} value={p.filename}>
              {p.filename}（{p.size_bytes} bytes）
            </option>
          ))}
        </select>
        <button type="button" className="btn btn-secondary" onClick={() => refresh()} disabled={uploading}>
          🔄 再読み込み
        </button>
      </div>
      <div className="field">
        <label className="upload-label">
          📤 CSVをアップロード:
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleFileChange}
            disabled={uploading}
          />
        </label>
        {uploading && <span>⏳ アップロード中...</span>}
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  )
}
