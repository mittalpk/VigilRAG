import { useState, useEffect } from 'react'
import {
  apiClient,
  AuditQueryItem,
  AuditQueryDetailResponse,
  AuditExportResponse,
  AuditRetentionStatus,
} from '../api/client'

export default function AuditLog() {
  const [identityFilter, setIdentityFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [page, setPage] = useState(1)
  const perPage = 50

  const [loading, setLoading] = useState(false)
  const [queries, setQueries] = useState<AuditQueryItem[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [exportMsg, setExportMsg] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [retention, setRetention] = useState<AuditRetentionStatus | null>(null)

  const [selectedQueryDetail, setSelectedQueryDetail] = useState<AuditQueryDetailResponse | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const loadAuditLogs = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.getAuditQueries(
        identityFilter.trim() || undefined,
        fromDate.trim() || undefined,
        toDate.trim() || undefined,
        page,
        perPage,
        searchQuery.trim() || undefined
      )
      setQueries(res.items)
      setTotal(res.total)
    } catch (err: any) {
      setError(err.message || 'Failed to fetch audit log records')
    } finally {
      setLoading(false)
    }
  }

  const loadRetention = async () => {
    try {
      const status = await apiClient.getAuditRetentionStatus()
      setRetention(status)
    } catch {
      // Retention panel is best-effort for non-admin contexts
    }
  }

  useEffect(() => {
    loadAuditLogs()
    loadRetention()
  }, [page])

  const handleFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    loadAuditLogs()
  }

  const openDetailModal = async (queryId: string) => {
    setLoadingDetail(true)
    setSelectedQueryDetail(null)
    try {
      const detail = await apiClient.getAuditQueryDetail(queryId)
      setSelectedQueryDetail(detail)
    } catch (err: any) {
      setError(`Failed to load query detail: ${err.message}`)
    } finally {
      setLoadingDetail(false)
    }
  }

  const handleExport = async (format: 'csv' | 'pdf') => {
    if (!fromDate.trim() || !toDate.trim()) {
      setError('Export requires From Date and To Date')
      return
    }
    setExporting(true)
    setExportMsg(null)
    setError(null)
    try {
      const res: AuditExportResponse = await apiClient.exportAuditLog(
        fromDate.trim(),
        toDate.trim(),
        format,
        identityFilter.trim() || undefined,
        searchQuery.trim() || undefined
      )
      const ttlNote = res.expires_at ? ` Expires ${new Date(res.expires_at).toLocaleString()}.` : ''
      setExportMsg(
        `Export ${res.export_id} ${res.status} (${res.row_count} rows).` +
          (res.async ? ' Async (202) path used.' : '') +
          ttlNote
      )
      if (res.download_url) {
        const backendBase = (import.meta.env.VITE_BACKEND_URL as string | undefined) ?? ''
        const abs = res.download_url.startsWith('http')
          ? res.download_url
          : backendBase.startsWith('http')
            ? `${backendBase.replace(/\/$/, '')}${res.download_url}`
            : res.download_url
        window.open(abs, '_blank', 'noopener,noreferrer')
      }
    } catch (err: any) {
      setError(err.message || 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  const totalPages = Math.ceil(total / perPage) || 1

  return (
    <div className="card fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 className="card-title">Audit log</h2>
          <p className="card-hint">
            Searchable query trail with retention status and CSV/PDF export for compliance review.
          </p>
        </div>
      </div>

      {retention && (
        <div
          className="mt-16"
          style={{ background: 'var(--color-surface-muted)', border: '1px solid var(--color-border)', borderRadius: 6, padding: 12, fontSize: '0.85rem' }}
        >
          <strong style={{ color: 'var(--color-text)' }}>Retention policy:</strong>{' '}
          <span style={{ color: 'var(--color-muted)' }}>{retention.retention_days} days</span>
          {retention.latest_run && (
            <span style={{ color: 'var(--color-muted)', marginLeft: 12 }}>
              Last run: {retention.latest_run.status} — archived {retention.latest_run.records_archived ?? 0}{' '}
              ({retention.latest_run.started_at ? new Date(retention.latest_run.started_at).toLocaleString() : 'n/a'})
            </span>
          )}
        </div>
      )}

      <form onSubmit={handleFilterSubmit} className="mt-16" style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div className="form-group" style={{ flex: '1 1 200px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--color-muted)' }}>Requester Identity</label>
          <input
            type="text"
            className="task-input"
            style={{ padding: '8px 12px' }}
            placeholder="Filter by email or username..."
            value={identityFilter}
            onChange={(e) => setIdentityFilter(e.target.value)}
          />
        </div>

        <div className="form-group" style={{ flex: '1 1 200px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--color-muted)' }}>Full-text search</label>
          <input
            type="text"
            className="task-input"
            style={{ padding: '8px 12px' }}
            placeholder="Search query text (?q=)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="form-group" style={{ flex: '1 1 150px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--color-muted)' }}>From Date</label>
          <input
            type="date"
            className="task-input"
            style={{ padding: '8px 12px' }}
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
        </div>

        <div className="form-group" style={{ flex: '1 1 150px' }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--color-muted)' }}>To Date</label>
          <input
            type="date"
            className="task-input"
            style={{ padding: '8px 12px' }}
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Searching...' : 'Apply Filters'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setIdentityFilter('')
              setSearchQuery('')
              setFromDate('')
              setToDate('')
              setPage(1)
              loadAuditLogs()
            }}
            disabled={loading}
          >
            Reset
          </button>
          <button type="button" className="btn-secondary" disabled={exporting} onClick={() => handleExport('csv')}>
            {exporting ? 'Exporting...' : 'Export CSV'}
          </button>
          <button type="button" className="btn-secondary" disabled={exporting} onClick={() => handleExport('pdf')}>
            Export PDF
          </button>
        </div>
      </form>

      {exportMsg && (
        <div className="mt-12 p-12" style={{ background: 'var(--color-surface-muted)', border: '1px solid var(--color-border)', borderRadius: 6 }}>
          <span className="badge badge-info">Export</span>
          <p style={{ color: 'var(--color-text)', marginTop: 4, fontSize: '0.85rem' }}>{exportMsg}</p>
        </div>
      )}

      {error && (
        <div className="error-card mt-16 p-12">
          <span className="badge badge-error">Audit Fetch Error</span>
          <p style={{ color: 'var(--color-error)', marginTop: 4 }}>{error}</p>
        </div>
      )}

      <div className="table-responsive mt-24">
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-muted)', fontSize: '0.85rem' }}>
              <th style={{ padding: '12px 8px' }}>Timestamp</th>
              <th style={{ padding: '12px 8px' }}>Query ID</th>
              <th style={{ padding: '12px 8px' }}>Requester Identity</th>
              <th style={{ padding: '12px 8px' }}>Query Text</th>
              <th style={{ padding: '12px 8px' }}>Guardrail Flags</th>
              <th style={{ padding: '12px 8px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: 'var(--color-muted)' }}>
                  Loading audit logs...
                </td>
              </tr>
            ) : queries.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: 'var(--color-muted)' }}>
                  No audit query records found matching filters.
                </td>
              </tr>
            ) : (
              queries.map((item) => (
                <tr key={item.query_id} style={{ borderBottom: '1px solid var(--color-surface-muted)', fontSize: '0.9rem' }}>
                  <td style={{ padding: '10px 8px', color: 'var(--color-muted)', whiteSpace: 'nowrap' }}>
                    {item.timestamp ? new Date(item.timestamp).toLocaleString() : 'N/A'}
                  </td>
                  <td style={{ padding: '10px 8px', fontFamily: 'monospace', color: 'var(--color-accent)' }}>
                    {item.query_id}
                  </td>
                  <td style={{ padding: '10px 8px', color: 'var(--color-text)' }}>
                    {item.requester_identity}
                  </td>
                  <td style={{ padding: '10px 8px', color: 'var(--color-ink)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.text}
                  </td>
                  <td style={{ padding: '10px 8px' }}>
                    {item.guardrail_flags && item.guardrail_flags.length > 0 ? (
                      item.guardrail_flags.map((flag) => (
                        <span key={flag} className="badge badge-error" style={{ marginRight: 4, fontSize: '0.7rem' }}>
                          {flag}
                        </span>
                      ))
                    ) : (
                      <span style={{ color: 'var(--color-success)', fontSize: '0.8rem' }}>Clean</span>
                    )}
                  </td>
                  <td style={{ padding: '10px 8px' }}>
                    <button
                      className="btn-secondary"
                      style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                      onClick={() => openDetailModal(item.query_id)}
                    >
                      View Detail
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '16px' }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>
          Showing page {page} of {totalPages} ({total} total records)
        </span>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            className="btn-secondary"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(p - 1, 1))}
          >
            Previous
          </button>
          <button
            className="btn-secondary"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>

      {(selectedQueryDetail || loadingDetail) && (
        <div className="modal-backdrop fade-in" style={{ position: 'fixed', inset: 0, background: 'rgba(18, 32, 51, 0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="modal-card" style={{ background: 'var(--color-surface-muted)', border: '1px solid var(--color-border)', borderRadius: '8px', padding: '24px', maxWidth: '800px', width: '90%', maxHeight: '85vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, color: 'var(--color-ink)' }}>Audit Query Detail Record</h3>
              <button
                className="btn-secondary"
                style={{ padding: '4px 10px' }}
                onClick={() => setSelectedQueryDetail(null)}
              >
                Close
              </button>
            </div>

            {loadingDetail ? (
              <p style={{ color: 'var(--color-muted)' }}>Loading detail...</p>
            ) : selectedQueryDetail ? (
              <div>
                <div style={{ background: 'var(--color-surface-muted)', padding: '12px', borderRadius: '6px', marginBottom: '16px', fontSize: '0.9rem' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                    <div><strong>Query ID:</strong> <code style={{ color: 'var(--color-accent)' }}>{selectedQueryDetail.query_id}</code></div>
                    <div><strong>Requester:</strong> {selectedQueryDetail.requester_identity}</div>
                    <div><strong>Timestamp:</strong> {selectedQueryDetail.timestamp}</div>
                    <div><strong>Groundedness Score:</strong> {selectedQueryDetail.groundedness_score ?? 'N/A'}</div>
                  </div>
                  <div style={{ marginTop: '8px' }}>
                    <strong>Query Text:</strong>
                    <div style={{ color: 'var(--color-text)', marginTop: '4px' }}>{selectedQueryDetail.text}</div>
                  </div>
                </div>

                <h4 style={{ color: 'var(--color-ink)', marginBottom: '8px' }}>Synthesized Answer</h4>
                <div style={{ background: 'var(--color-surface-muted)', padding: '12px', borderRadius: '6px', marginBottom: '16px', color: 'var(--color-text)', fontSize: '0.9rem' }}>
                  {selectedQueryDetail.answer_text || 'No answer generated.'}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <h4 style={{ color: 'var(--color-ink)', margin: 0 }}>Associated Evidence Chunks</h4>
                  {selectedQueryDetail.truncated && (
                    <span className="badge badge-info">Capped at 50 records (truncated)</span>
                  )}
                </div>

                {selectedQueryDetail.evidence_items.length === 0 ? (
                  <p style={{ color: 'var(--color-muted)', fontSize: '0.9rem' }}>No evidence items recorded for this query.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {selectedQueryDetail.evidence_items.map((ev, idx) => (
                      <div key={ev.id || idx} style={{ background: 'var(--color-surface-muted)', border: '1px solid var(--color-border)', padding: '10px', borderRadius: '6px', fontSize: '0.85rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>Chunk ID: {ev.chunk_id}</span>
                          <span style={{ color: 'var(--color-muted)' }}>Relevance: {ev.relevance_score ?? 'N/A'}</span>
                        </div>
                        {ev.source_url && (
                          <div style={{ color: 'var(--color-muted)', fontSize: '0.8rem', marginBottom: '4px' }}>
                            Source: <a href={ev.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent)' }}>{ev.source_url}</a>
                          </div>
                        )}
                        <div style={{ color: 'var(--color-text)' }}>{ev.content_excerpt}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}
