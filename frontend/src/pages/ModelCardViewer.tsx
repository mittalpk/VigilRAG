import { useEffect, useState } from 'react'
import { apiClient } from '../api/client'

export default function ModelCardViewer() {
  const [markdown, setMarkdown] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const text = await apiClient.getLatestModelCard()
      setMarkdown(text)
    } catch (err: any) {
      setError(err.message || 'Failed to load model card')
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
          <h2 className="card-title">Model / System Card</h2>
          <p className="card-hint">
            Latest published governance card (FR-013 / NFR-012). Admin-only.
          </p>
        </div>
        <button className="btn-secondary" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="error-card mt-16 p-12">
          <span className="badge badge-error">Model Card Error</span>
          <p style={{ color: '#f87171', marginTop: 4 }}>{error}</p>
        </div>
      )}

      {!error && (
        <pre
          className="mt-16"
          style={{
            whiteSpace: 'pre-wrap',
            background: '#0f172a',
            border: '1px solid #334155',
            borderRadius: 8,
            padding: 16,
            color: '#e2e8f0',
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
