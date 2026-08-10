import { useEffect, useState } from 'react'
import { getPreferences, savePreferences } from '../api/client'
import type { PreferenceRecord } from '../types'

interface Props {
  portfolioFilename: string | null
}

export function PreferencesEditor({ portfolioFilename }: Props) {
  const [records, setRecords] = useState<PreferenceRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedMessage, setSavedMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!portfolioFilename) return
    setSavedMessage(null)
    getPreferences(portfolioFilename)
      .then(setRecords)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [portfolioFilename])

  function updateScore(code: string, value: number) {
    setRecords((prev) => prev.map((r) => (r.code === code ? { ...r, affection_score: value } : r)))
  }

  function scoreEmoji(score: number): string {
    if (score >= 80) return '💖'
    if (score >= 50) return '🙂'
    return '💤'
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    setSavedMessage(null)
    try {
      const saved = await savePreferences(records)
      setRecords(saved)
      setSavedMessage('愛着度設定を保存しました。')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (!portfolioFilename) {
    return null
  }

  return (
    <section className="panel">
      <h2>💖 2. 愛着度設定</h2>
      <p className="hint">
        愛着度（1〜100、100が最も愛着が強い）は分析時に反映され、愛着度80以上の銘柄は含み損益に
        関わらず売却提案の対象から除外されます。
      </p>
      {records.length === 0 && <p>保有銘柄がありません。</p>}
      {records.length > 0 && (
        <table className="preferences-table">
          <thead>
            <tr>
              <th>コード</th>
              <th>銘柄名</th>
              <th>愛着度（1〜100）</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.code}>
                <td>{r.code}</td>
                <td>{r.name}</td>
                <td className="score-cell">
                  <span className="score-emoji" title={`${r.affection_score}/100`}>
                    {scoreEmoji(r.affection_score)}
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={r.affection_score}
                    onChange={(e) => updateScore(r.code, Number(e.target.value))}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button type="button" className="btn btn-primary" onClick={handleSave} disabled={saving || records.length === 0}>
        {saving ? '⏳ 保存中...' : '💾 愛着度設定を保存'}
      </button>
      {savedMessage && <p className="success">{savedMessage}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  )
}
