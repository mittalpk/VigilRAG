import { useEffect, useState } from 'react'
import { apiClient } from '../api/client'

export default function ModelCardViewer() {
  const [markdown, setMarkdown] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [missing, setMissing] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    setMissing(false)
    try {
      const text = await apiClient.getLatestModelCard()
      setMarkdown(text)
    } catch (err: any) {
      const msg = err.message || 'Failed to load model card'
      if (/404|not found/i.test(msg)) {
        setMissing(true)
        setMarkdown('')
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="card fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 className="card-title">Model card</h2>
          <p className="card-hint">
            Published system and model governance documentation for this environment.
          </p>
        </div>
        <button className="btn-secondary" onClick={load} disabled={loading} type="button">
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="error-card mt-16 p-12">
          <span className="badge badge-error">Could not load</span>
          <p style={{ color: 'var(--color-error)', marginTop: 4 }}>{error}</p>
        </div>
      )}

      {missing && !error && (
        <div className="mt-16" style={{ padding: 16, background: 'var(--color-surface-muted)', border: '1px solid var(--color-border)', borderRadius: 8 }}>
          <p style={{ margin: 0, color: 'var(--color-muted)', fontSize: '0.92rem' }}>
            No model card has been published for this environment yet. Cards appear here after a release publishes governance documentation.
          </p>
        </div>
      )}

      {!error && !missing && (
        <pre
          className="mt-16"
          style={{
            whiteSpace: 'pre-wrap',
            background: 'var(--color-surface-muted)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            padding: 16,
            color: 'var(--color-text)',
            fontSize: '0.85rem',
            maxHeight: '70vh',
            overflow: 'auto',
          }}
        >
          {loading && !markdown ? 'Loading model card…' : markdown || 'No card content.'}
        </pre>
      )}
    </div>
  )
}
