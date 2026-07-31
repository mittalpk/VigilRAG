import { useState, useEffect } from 'react'
import { apiClient, FeedbackReviewItemResponse } from '../api/client'

export default function FeedbackReview() {
  const [statusFilter, setStatusFilter] = useState('pending')
  const [page, setPage] = useState(1)
  const size = 10

  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<FeedbackReviewItemResponse[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const [activeItem, setActiveItem] = useState<FeedbackReviewItemResponse | null>(null)
  const [goldenAnswerInput, setGoldenAnswerInput] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  const loadQueue = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.getFeedbackReviewQueue(
        statusFilter.trim() || undefined,
        page,
        size
      )
      setItems(res.items)
      setTotal(res.total)
    } catch (err: any) {
      setError(err.message || 'Failed to fetch feedback review queue')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadQueue()
  }, [page, statusFilter])

  const handleAction = async (itemId: string, action: 'promote' | 'dismiss' | 'needs_investigation') => {
    setActionLoading(true)
    setError(null)
    try {
      await apiClient.actionFeedbackReviewItem(
        itemId,
        action,
        action === 'promote' ? goldenAnswerInput.trim() || undefined : undefined
      )
      setActiveItem(null)
      setGoldenAnswerInput('')
      await loadQueue()
    } catch (err: any) {
      setError(`Action failed: ${err.message}`)
    } finally {
      setActionLoading(false)
    }
  }

  const totalPages = Math.ceil(total / size) || 1

  return (
    <div className="card fade-in">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 className="card-title">Feedback review</h2>
          <p className="card-hint">
            Review flagged answers, capture expected responses, and promote cases into the evaluation set.
          </p>
        </div>
      </div>

      <div className="mt-16" style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>Filter Status:</span>
        {['pending', 'promoted', 'dismissed', 'needs_investigation', ''].map((st) => (
          <button
            key={st}
            className={`btn-secondary ${statusFilter === st ? 'active' : ''}`}
            style={{ padding: '4px 12px', fontSize: '0.8rem', textTransform: 'capitalize' }}
            onClick={() => {
              setStatusFilter(st)
              setPage(1)
            }}
          >
            {st === '' ? 'All Items' : st.replace('_', ' ')}
          </button>
        ))}
      </div>

      {error && (
        <div className="error-card mt-16 p-12">
          <span className="badge badge-error">Review Error</span>
          <p style={{ color: 'var(--color-error)', marginTop: 4 }}>{error}</p>
        </div>
      )}

      <div className="table-responsive mt-24">
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--color-border)', color: 'var(--color-muted)', fontSize: '0.85rem' }}>
              <th style={{ padding: '12px 8px' }}>Created At</th>
              <th style={{ padding: '12px 8px' }}>Requester</th>
              <th style={{ padding: '12px 8px' }}>Query Text</th>
              <th style={{ padding: '12px 8px' }}>User Comment</th>
              <th style={{ padding: '12px 8px' }}>Status</th>
              <th style={{ padding: '12px 8px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: 'var(--color-muted)' }}>
                  Loading feedback review items...
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: 'var(--color-muted)' }}>
                  No items in review queue matching filter.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} style={{ borderBottom: '1px solid var(--color-surface-muted)', fontSize: '0.9rem' }}>
                  <td style={{ padding: '10px 8px', color: 'var(--color-muted)', whiteSpace: 'nowrap' }}>
                    {item.created_at ? new Date(item.created_at).toLocaleDateString() : 'N/A'}
                  </td>
                  <td style={{ padding: '10px 8px', color: 'var(--color-text)' }}>
                    {item.requester_identity}
                  </td>
                  <td style={{ padding: '10px 8px', color: 'var(--color-ink)', maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.query_text}
                  </td>
                  <td style={{ padding: '10px 8px', color: 'var(--color-error)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.user_comment || 'No comment provided.'}
                  </td>
                  <td style={{ padding: '10px 8px' }}>
                    <span className={`badge ${item.status === 'promoted' ? 'badge-success' : item.status === 'dismissed' ? 'badge-info' : 'badge-error'}`} style={{ fontSize: '0.75rem', textTransform: 'capitalize' }}>
                      {item.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td style={{ padding: '10px 8px' }}>
                    <button
                      className="btn-secondary"
                      style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                      onClick={() => {
                        setActiveItem(item)
                        setGoldenAnswerInput(item.golden_answer || '')
                      }}
                    >
                      Review
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
        <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>
          Page {page} of {totalPages} ({total} queue items)
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

      {/* Action Modal */}
      {activeItem && (
        <div className="modal-backdrop fade-in" style={{ position: 'fixed', inset: 0, background: 'rgba(18, 32, 51, 0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="modal-card" style={{ background: 'var(--color-surface-muted)', border: '1px solid var(--color-border)', borderRadius: '8px', padding: '24px', maxWidth: '750px', width: '90%', maxHeight: '85vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, color: 'var(--color-ink)' }}>Review & Curate Feedback Item</h3>
              <button
                className="btn-secondary"
                style={{ padding: '4px 10px' }}
                onClick={() => setActiveItem(null)}
              >
                Close
              </button>
            </div>

            <div style={{ background: 'var(--color-surface-muted)', padding: '12px', borderRadius: '6px', marginBottom: '16px', fontSize: '0.9rem' }}>
              <div style={{ marginBottom: '8px' }}>
                <strong style={{ color: 'var(--color-muted)' }}>Query Text:</strong>
                <div style={{ color: 'var(--color-ink)', marginTop: '2px' }}>{activeItem.query_text}</div>
              </div>
              <div style={{ marginBottom: '8px' }}>
                <strong style={{ color: 'var(--color-muted)' }}>System Answer Given:</strong>
                <div style={{ color: 'var(--color-text)', marginTop: '2px', background: 'var(--color-surface-muted)', padding: '8px', borderRadius: '4px' }}>
                  {activeItem.answer_text || 'No system answer recorded.'}
                </div>
              </div>
              <div>
                <strong style={{ color: 'var(--color-muted)' }}>User Feedback Comment:</strong>
                <div style={{ color: 'var(--color-error)', marginTop: '2px' }}>{activeItem.user_comment || 'None provided.'}</div>
              </div>
            </div>

            <div className="form-group mb-16">
              <label style={{ fontSize: '0.85rem', color: 'var(--color-accent)', fontWeight: 600 }}>
                Expected answer (required to promote):
              </label>
              <textarea
                className="task-input mt-4"
                rows={3}
                placeholder="Enter the verified correct answer for the evaluation set…"
                value={goldenAnswerInput}
                onChange={(e) => setGoldenAnswerInput(e.target.value)}
                style={{ fontSize: '0.85rem' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button
                className="btn-secondary"
                style={{ borderColor: 'var(--color-muted)' }}
                disabled={actionLoading}
                onClick={() => handleAction(activeItem.id, 'dismiss')}
              >
                Dismiss Item
              </button>
              <button
                className="btn-secondary"
                style={{ borderColor: '#f59e0b', color: 'var(--color-warn)' }}
                disabled={actionLoading}
                onClick={() => handleAction(activeItem.id, 'needs_investigation')}
              >
                Needs Investigation
              </button>
              <button
                className="btn-primary"
                style={{ background: 'var(--color-success)', borderColor: 'var(--color-success)' }}
                disabled={actionLoading}
                onClick={() => handleAction(activeItem.id, 'promote')}
              >
                {actionLoading ? 'Promoting...' : 'Promote to Evaluation Dataset'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
