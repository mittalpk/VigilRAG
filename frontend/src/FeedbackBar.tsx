import { useState } from 'react'
import { apiClient } from './api/client'

interface FeedbackBarProps {
  queryId?: string
}

export default function FeedbackBar({ queryId }: FeedbackBarProps) {
  const [rating, setRating] = useState<'positive' | 'negative' | null>(null)
  const [comment, setComment] = useState('')
  const [showCommentBox, setShowCommentBox] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!queryId) return null

  const handleRatingClick = (selectedRating: 'positive' | 'negative') => {
    if (submitted) return
    setRating(selectedRating)
    setShowCommentBox(true)
  }

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!rating || submitted) return

    setSubmitting(true)
    setError(null)
    try {
      await apiClient.submitFeedback(queryId, rating, comment.trim() || undefined)
      setSubmitted(true)
      setShowCommentBox(false)
    } catch (err: any) {
      if (err.message && err.message.includes('409')) {
        setError('Feedback already submitted for this query.')
        setSubmitted(true)
      } else {
        setError('Feedback couldn\'t be saved — please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="feedback-bar mt-16 p-12" style={{ background: 'var(--color-surface-muted)', borderRadius: '6px', border: '1px solid var(--color-border)' }}>
      {submitted ? (
        <div style={{ color: 'var(--color-success)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
          ✓ Thanks for your feedback! {rating === 'positive' ? '👍' : '👎'}
        </div>
      ) : (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>Was this answer helpful?</span>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                className={`btn-secondary ${rating === 'positive' ? 'active' : ''}`}
                style={{ padding: '4px 10px', fontSize: '0.9rem', borderColor: rating === 'positive' ? 'var(--color-success)' : undefined }}
                onClick={() => handleRatingClick('positive')}
                disabled={submitting}
              >
                👍 Helpful
              </button>
              <button
                className={`btn-secondary ${rating === 'negative' ? 'active' : ''}`}
                style={{ padding: '4px 10px', fontSize: '0.9rem', borderColor: rating === 'negative' ? 'var(--color-error)' : undefined }}
                onClick={() => handleRatingClick('negative')}
                disabled={submitting}
              >
                👎 Unhelpful
              </button>
            </div>
          </div>

          {showCommentBox && (
            <div className="mt-12 fade-in">
              <textarea
                className="task-input"
                rows={2}
                maxLength={500}
                placeholder={rating === 'negative' ? "What was wrong with this answer? (optional, max 500 chars)" : "Add optional details (max 500 chars)..."}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                style={{ fontSize: '0.85rem', padding: '8px' }}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' }}>
                <button
                  type="button"
                  className="btn-primary"
                  style={{ padding: '4px 12px', fontSize: '0.85rem' }}
                  onClick={() => handleSubmit()}
                  disabled={submitting}
                >
                  {submitting ? 'Submitting...' : 'Submit Feedback'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ color: 'var(--color-error)', fontSize: '0.8rem', marginTop: '4px' }}>
          {error}
        </div>
      )}
    </div>
  )
}
