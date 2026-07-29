import { useState, useEffect } from 'react'
import { apiClient, AuditQueryItem, AuditQueryDetailResponse } from '../api/client'

export default function AuditLog() {
  const [identityFilter, setIdentityFilter] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [page, setPage] = useState(1)
  const perPage = 50

  const [loading, setLoading] = useState(false)
  const [queries, setQueries] = useState<AuditQueryItem[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)

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
        perPage
      )
      setQueries(res.items)
      setTotal(res.total)
    } catch (err: any) {
      setError(err.message || 'Failed to fetch audit log records')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAuditLogs()
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

  const totalPages = Math.ceil(total / perPage) || 1

  return (
    <div className="card fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 className="card-title">Compliance Audit Log</h2>
          <p className="card-hint">
            Read-only compliance audit trail capturing requester identities, queries, retrieved evidence items, and synthesized answers.
          </p>
        </div>
        <span className="badge badge-info">FR-008 / NFR-004 Read-Only</span>
      </div>

      <form onSubmit={handleFilterSubmit} className="mt-16" style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div className="form-group" style={{ flex: '1 1 200px' }}>
          <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Requester Identity</label>
          <input
            type="text"
            className="task-input"
            style={{ padding: '8px 12px' }}
            placeholder="Filter by email or username..."
            value={identityFilter}
            onChange={(e) => setIdentityFilter(e.target.value)}
          />
        </div>

        <div className="form-group" style={{ flex: '1 1 150px' }}>
          <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>From Date</label>
          <input
            type="date"
            className="task-input"
            style={{ padding: '8px 12px' }}
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
          />
        </div>

        <div className="form-group" style={{ flex: '1 1 150px' }}>
          <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>To Date</label>
          <input
            type="date"
            className="task-input"
            style={{ padding: '8px 12px' }}
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Searching...' : 'Apply Filters'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setIdentityFilter('')
              setFromDate('')
              setToDate('')
              setPage(1)
              loadAuditLogs()
            }}
            disabled={loading}
          >
            Reset
          </button>
        </div>
      </form>

      {error && (
        <div className="error-card mt-16 p-12">
          <span className="badge badge-error">Audit Fetch Error</span>
          <p style={{ color: '#f87171', marginTop: 4 }}>{error}</p>
        </div>
      )}

      <div className="table-responsive mt-24">
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8', fontSize: '0.85rem' }}>
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
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: '#94a3b8' }}>
                  Loading audit logs...
                </td>
              </tr>
            ) : queries.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>
                  No audit query records found matching filters.
                </td>
              </tr>
            ) : (
              queries.map((item) => (
                <tr key={item.query_id} style={{ borderBottom: '1px solid #1e293b', fontSize: '0.9rem' }}>
                  <td style={{ padding: '10px 8px', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                    {item.timestamp ? new Date(item.timestamp).toLocaleString() : 'N/A'}
                  </td>
                  <td style={{ padding: '10px 8px', fontFamily: 'monospace', color: '#38bdf8' }}>
                    {item.query_id}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#cbd5e1' }}>
                    {item.requester_identity}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#f8fafc', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
                      <span style={{ color: '#34d399', fontSize: '0.8rem' }}>Clean</span>
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

      {/* Pagination Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '16px' }}>
        <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
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

      {/* Detail Drill-Down Modal */}
      {(selectedQueryDetail || loadingDetail) && (
        <div className="modal-backdrop fade-in" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="modal-card" style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: '8px', padding: '24px', maxWidth: '800px', width: '90%', maxHeight: '85vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, color: '#f8fafc' }}>Audit Query Detail Record</h3>
              <button
                className="btn-secondary"
                style={{ padding: '4px 10px' }}
                onClick={() => setSelectedQueryDetail(null)}
              >
                Close
              </button>
            </div>

            {loadingDetail ? (
              <p style={{ color: '#94a3b8' }}>Loading detail...</p>
            ) : selectedQueryDetail ? (
              <div>
                <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px', marginBottom: '16px', fontSize: '0.9rem' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                    <div><strong>Query ID:</strong> <code style={{ color: '#38bdf8' }}>{selectedQueryDetail.query_id}</code></div>
                    <div><strong>Requester:</strong> {selectedQueryDetail.requester_identity}</div>
                    <div><strong>Timestamp:</strong> {selectedQueryDetail.timestamp}</div>
                    <div><strong>Groundedness Score:</strong> {selectedQueryDetail.groundedness_score ?? 'N/A'}</div>
                  </div>
                  <div style={{ marginTop: '8px' }}>
                    <strong>Query Text:</strong>
                    <div style={{ color: '#cbd5e1', marginTop: '4px' }}>{selectedQueryDetail.text}</div>
                  </div>
                </div>

                <h4 style={{ color: '#f8fafc', marginBottom: '8px' }}>Synthesized Answer</h4>
                <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px', marginBottom: '16px', color: '#e2e8f0', fontSize: '0.9rem' }}>
                  {selectedQueryDetail.answer_text || 'No answer generated.'}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <h4 style={{ color: '#f8fafc', margin: 0 }}>Associated Evidence Chunks</h4>
                  {selectedQueryDetail.truncated && (
                    <span className="badge badge-info">Capped at 50 records (truncated)</span>
                  )}
                </div>

                {selectedQueryDetail.evidence_items.length === 0 ? (
                  <p style={{ color: '#64748b', fontSize: '0.9rem' }}>No evidence items recorded for this query.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {selectedQueryDetail.evidence_items.map((ev, idx) => (
                      <div key={ev.id || idx} style={{ background: '#1e293b', border: '1px solid #334155', padding: '10px', borderRadius: '6px', fontSize: '0.85rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                          <span style={{ color: '#38bdf8', fontWeight: 600 }}>Chunk ID: {ev.chunk_id}</span>
                          <span style={{ color: '#94a3b8' }}>Relevance: {ev.relevance_score ?? 'N/A'}</span>
                        </div>
                        {ev.source_url && (
                          <div style={{ color: '#64748b', fontSize: '0.8rem', marginBottom: '4px' }}>
                            Source: <a href={ev.source_url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>{ev.source_url}</a>
                          </div>
                        )}
                        <div style={{ color: '#cbd5e1' }}>{ev.content_excerpt}</div>
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
