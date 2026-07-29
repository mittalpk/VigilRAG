import React, { useEffect, useState } from 'react'

export interface SourceItem {
  id: string
  name: string
  source_type: string
  endpoint_url: string
  secret_reference: string
  owner_email: string
  sensitivity_level: string
  sensitivity_signed_off: boolean
  refresh_cadence_minutes: number
  status: string
  indexing_scope: string
  is_active: boolean
  created_at: string
  updated_at: string
  last_indexed_at?: string
}

export interface SourceTypeInfo {
  type_id: string
  display_name: string
  description: string
  supported: boolean
}

export default function SourceManagement() {
  const [sources, setSources] = useState<SourceItem[]>([])
  const [sourceTypes, setSourceTypes] = useState<SourceTypeInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [triggeringId, setTriggeringId] = useState<string | null>(null)

  const [formData, setFormData] = useState({
    name: '',
    source_type: 'github_repo',
    endpoint_url: '',
    secret_reference: '',
    owner_email: '',
    sensitivity_level: 'internal-general',
    sensitivity_signed_off: false,
    refresh_cadence_minutes: 1440,
    indexing_scope: '*',
  })
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const token = localStorage.getItem('access_token') || ''

  const fetchSources = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await fetch('/api/v1/admin/sources?include_inactive=true', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        throw new Error(`Failed to load sources (${res.status})`)
      }
      const data = await res.json()
      setSources(data.items || [])
    } catch (err: any) {
      setError(err.message || 'Failed to load source registry')
    } finally {
      setLoading(false)
    }
  }

  const fetchTypes = async () => {
    try {
      const res = await fetch('/api/v1/admin/sources/types', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const types = await res.json()
        setSourceTypes(types)
      }
    } catch (err) {
      console.warn('Failed to load source types:', err)
    }
  }

  useEffect(() => {
    fetchSources()
    fetchTypes()
  }, [])

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    setSubmitting(true)
    try {
      const res = await fetch('/api/v1/admin/sources', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(formData),
      })
      if (res.status === 409) {
        const errData = await res.json()
        throw new Error(errData.detail || 'This source is already registered.')
      }
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to register source')
      }
      setIsModalOpen(false)
      setFormData({
        name: '',
        source_type: 'github_repo',
        endpoint_url: '',
        secret_reference: '',
        owner_email: '',
        sensitivity_level: 'internal-general',
        sensitivity_signed_off: false,
        refresh_cadence_minutes: 1440,
        indexing_scope: '*',
      })
      fetchSources()
    } catch (err: any) {
      setFormError(err.message || 'Registration error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleTriggerIndex = async (id: string) => {
    setTriggeringId(id)
    try {
      const res = await fetch(`/api/v1/admin/sources/${id}/trigger-index`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        throw new Error('Failed to trigger index')
      }
      await fetchSources()
      // Poll briefly for background completion
      setTimeout(fetchSources, 1500)
    } catch (err: any) {
      alert(err.message || 'Trigger failed')
    } finally {
      setTriggeringId(null)
    }
  }

  const handleDeactivate = async (id: string) => {
    if (!confirm('Deactivate this source? Existing indexed chunks will remain until purged.')) return
    try {
      const res = await fetch(`/api/v1/admin/sources/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        fetchSources()
      }
    } catch (err) {
      console.error('Deactivation failed:', err)
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'indexed':
        return <span style={{ backgroundColor: '#10b981', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Indexed</span>
      case 'indexing':
        return <span style={{ backgroundColor: '#3b82f6', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Indexing...</span>
      case 'pending_first_index':
        return <span style={{ backgroundColor: '#f59e0b', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Pending First Index</span>
      case 'inactive':
        return <span style={{ backgroundColor: '#6b7280', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Inactive</span>
      default:
        return <span style={{ backgroundColor: '#ef4444', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>{status}</span>
    }
  }

  return (
    <div className="source-management-page" style={{ padding: '24px', color: '#f3f4f6' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 600, margin: 0 }}>Source Registration Self-Service (US-031)</h2>
          <p style={{ color: '#9ca3af', fontSize: '0.875rem', marginTop: '4px' }}>
            Register, edit, and trigger ingestion for knowledge sources without code modifications.
          </p>
        </div>
        <button
          className="btn-primary"
          style={{ backgroundColor: '#2563eb', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer' }}
          onClick={() => setIsModalOpen(true)}
        >
          + Register New Source
        </button>
      </div>

      {error && <div style={{ color: '#ef4444', backgroundColor: '#450a0a', padding: '12px', borderRadius: '6px', marginBottom: '16px' }}>{error}</div>}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: '#9ca3af' }}>Loading Source Registry...</div>
      ) : (
        <div style={{ backgroundColor: '#1f2937', borderRadius: '8px', overflow: 'hidden', border: '1px solid #374151' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ backgroundColor: '#111827', color: '#9ca3af', borderBottom: '1px solid #374151' }}>
                <th style={{ padding: '12px 16px' }}>Source Name</th>
                <th style={{ padding: '12px 16px' }}>Type</th>
                <th style={{ padding: '12px 16px' }}>Endpoint / Repo</th>
                <th style={{ padding: '12px 16px' }}>Sensitivity</th>
                <th style={{ padding: '12px 16px' }}>Status</th>
                <th style={{ padding: '12px 16px' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sources.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: '#9ca3af' }}>
                    No registered sources found. Click "Register New Source" to onboard a repository or wiki.
                  </td>
                </tr>
              ) : (
                sources.map((src) => (
                  <tr key={src.id} style={{ borderBottom: '1px solid #374151', opacity: src.is_active ? 1 : 0.6 }}>
                    <td style={{ padding: '12px 16px', fontWeight: 500 }}>
                      {src.name}
                      <div style={{ fontSize: '0.75rem', color: '#9ca3af' }}>Owner: {src.owner_email}</div>
                    </td>
                    <td style={{ padding: '12px 16px' }}>{src.source_type}</td>
                    <td style={{ padding: '12px 16px', fontFamily: 'monospace', fontSize: '0.8rem', color: '#60a5fa' }}>{src.endpoint_url}</td>
                    <td style={{ padding: '12px 16px' }}>
                      <span style={{ fontSize: '0.75rem', padding: '2px 6px', borderRadius: '4px', backgroundColor: '#374151' }}>
                        {src.sensitivity_level}
                      </span>
                    </td>
                    <td style={{ padding: '12px 16px' }}>{getStatusBadge(src.status)}</td>
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {src.is_active && (
                          <button
                            disabled={triggeringId === src.id || src.status === 'indexing'}
                            onClick={() => handleTriggerIndex(src.id)}
                            style={{ backgroundColor: '#10b981', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.75rem' }}
                          >
                            {triggeringId === src.id ? 'Triggering...' : 'Trigger Index'}
                          </button>
                        )}
                        {src.is_active && (
                          <button
                            onClick={() => handleDeactivate(src.id)}
                            style={{ backgroundColor: '#dc2626', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.75rem' }}
                          >
                            Deactivate
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Registration Modal */}
      {isModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.7)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 }}>
          <div style={{ backgroundColor: '#1f2937', padding: '24px', borderRadius: '8px', width: '500px', maxWidth: '90%', border: '1px solid #374151' }}>
            <h3 style={{ margin: 0, marginBottom: '16px', fontSize: '1.25rem' }}>Register Knowledge Source</h3>

            {formError && <div style={{ color: '#ef4444', backgroundColor: '#450a0a', padding: '8px 12px', borderRadius: '4px', marginBottom: '12px', fontSize: '0.875rem' }}>{formError}</div>}

            <form onSubmit={handleCreateSubmit}>
              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Source Display Name</label>
                <input
                  type="text"
                  required
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: '#111827', border: '1px solid #374151', color: '#fff' }}
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Connector Type</label>
                <select
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: '#111827', border: '1px solid #374151', color: '#fff' }}
                  value={formData.source_type}
                  onChange={(e) => setFormData({ ...formData, source_type: e.target.value })}
                >
                  {sourceTypes.map((t) => (
                    <option key={t.type_id} value={t.type_id} disabled={!t.supported}>
                      {t.display_name} {!t.supported ? '(Coming soon)' : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Endpoint URL / Repository Reference</label>
                <input
                  type="text"
                  required
                  placeholder="https://github.com/org/repo or https://wiki.example.com/space"
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: '#111827', border: '1px solid #374151', color: '#fff' }}
                  value={formData.endpoint_url}
                  onChange={(e) => setFormData({ ...formData, endpoint_url: e.target.value })}
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Key Vault Secret Reference Name</label>
                <input
                  type="text"
                  required
                  placeholder="kv-secret-github-pat"
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: '#111827', border: '1px solid #374151', color: '#fff' }}
                  value={formData.secret_reference}
                  onChange={(e) => setFormData({ ...formData, secret_reference: e.target.value })}
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Owner Email</label>
                <input
                  type="email"
                  required
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: '#111827', border: '1px solid #374151', color: '#fff' }}
                  value={formData.owner_email}
                  onChange={(e) => setFormData({ ...formData, owner_email: e.target.value })}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Sensitivity Level</label>
                  <select
                    style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: '#111827', border: '1px solid #374151', color: '#fff' }}
                    value={formData.sensitivity_level}
                    onChange={(e) => setFormData({ ...formData, sensitivity_level: e.target.value })}
                  >
                    <option value="public">Public</option>
                    <option value="internal-general">Internal General</option>
                    <option value="confidential">Confidential</option>
                    <option value="restricted">Restricted</option>
                  </select>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '20px' }}>
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  style={{ backgroundColor: '#4b5563', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  style={{ backgroundColor: '#2563eb', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}
                >
                  {submitting ? 'Saving...' : 'Save Source'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
