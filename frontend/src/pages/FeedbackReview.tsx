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
          <h2 className="card-title">Feedback Review Queue</h2>
          <p className="card-hint">
            Review user-flagged negative feedback entries, curate expected golden answers, and promote failure cases into the evaluation dataset (US-020).
          </p>
        </div>
        <span className="badge badge-info">FR-009 / US-020 Admin Queue</span>
      </div>

      <div className="mt-16" style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>Filter Status:</span>
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
          <p style={{ color: '#f87171', marginTop: 4 }}>{error}</p>
        </div>
      )}

      <div className="table-responsive mt-24">
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8', fontSize: '0.85rem' }}>
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
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: '#94a3b8' }}>
                  Loading feedback review items...
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>
                  No items in review queue matching filter.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} style={{ borderBottom: '1px solid #1e293b', fontSize: '0.9rem' }}>
                  <td style={{ padding: '10px 8px', color: '#94a3b8', whiteSpace: 'nowrap' }}>
                    {item.created_at ? new Date(item.created_at).toLocaleDateString() : 'N/A'}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#cbd5e1' }}>
                    {item.requester_identity}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#f8fafc', maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.query_text}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#f87171', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
        <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
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
        <div className="modal-backdrop fade-in" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="modal-card" style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: '8px', padding: '24px', maxWidth: '750px', width: '90%', maxHeight: '85vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, color: '#f8fafc' }}>Review & Curate Feedback Item</h3>
              <button
                className="btn-secondary"
                style={{ padding: '4px 10px' }}
                onClick={() => setActiveItem(null)}
              >
                Close
              </button>
            </div>

            <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px', marginBottom: '16px', fontSize: '0.9rem' }}>
              <div style={{ marginBottom: '8px' }}>
                <strong style={{ color: '#94a3b8' }}>Query Text:</strong>
                <div style={{ color: '#f8fafc', marginTop: '2px' }}>{activeItem.query_text}</div>
              </div>
              <div style={{ marginBottom: '8px' }}>
                <strong style={{ color: '#94a3b8' }}>System Answer Given:</strong>
                <div style={{ color: '#cbd5e1', marginTop: '2px', background: '#0f172a', padding: '8px', borderRadius: '4px' }}>
                  {activeItem.answer_text || 'No system answer recorded.'}
                </div>
              </div>
              <div>
                <strong style={{ color: '#94a3b8' }}>User Feedback Comment:</strong>
                <div style={{ color: '#f87171', marginTop: '2px' }}>{activeItem.user_comment || 'None provided.'}</div>
              </div>
            </div>

            <div className="form-group mb-16">
              <label style={{ fontSize: '0.85rem', color: '#38bdf8', fontWeight: 600 }}>
                Expected Golden Answer (Required for Dataset Promotion):
              </label>
              <textarea
                className="task-input mt-4"
                rows={3}
                placeholder="Enter verified correct answer to add as a golden EvaluationCase..."
                value={goldenAnswerInput}
                onChange={(e) => setGoldenAnswerInput(e.target.value)}
                style={{ fontSize: '0.85rem' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button
                className="btn-secondary"
                style={{ borderColor: '#64748b' }}
                disabled={actionLoading}
                onClick={() => handleAction(activeItem.id, 'dismiss')}
              >
                Dismiss Item
              </button>
              <button
                className="btn-secondary"
                style={{ borderColor: '#f59e0b', color: '#fbbf24' }}
                disabled={actionLoading}
                onClick={() => handleAction(activeItem.id, 'needs_investigation')}
              >
                Needs Investigation
              </button>
              <button
                className="btn-primary"
                style={{ background: '#059669', borderColor: '#10b981' }}
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
