import React, { useEffect, useState } from 'react'
import {
  apiClient,
  SourceCreateRequest,
  SourceItem,
  SourceTypeInfo,
} from './api/client'

const emptyForm: SourceCreateRequest = {
  name: '',
  source_type: 'github_repo',
  endpoint_url: '',
  secret_reference: '',
  owner_email: '',
  sensitivity_level: 'internal-general',
  sensitivity_signed_off: false,
  refresh_cadence_minutes: 1440,
  indexing_scope: '*',
}

export default function SourceManagement() {
  const [sources, setSources] = useState<SourceItem[]>([])
  const [sourceTypes, setSourceTypes] = useState<SourceTypeInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [triggeringId, setTriggeringId] = useState<string | null>(null)

  const [formData, setFormData] = useState<SourceCreateRequest>({ ...emptyForm })
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const fetchSources = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await apiClient.listSources(true)
      setSources(data.items || [])
    } catch (err: any) {
      setError(err.message || 'Failed to load source registry')
    } finally {
      setLoading(false)
    }
  }

  const fetchTypes = async () => {
    try {
      const types = await apiClient.getSourceTypes()
      setSourceTypes(types)
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
      await apiClient.createSource(formData)
      setIsModalOpen(false)
      setFormData({ ...emptyForm })
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
      await apiClient.triggerSourceIndex(id)
      await fetchSources()
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
      await apiClient.deactivateSource(id)
      fetchSources()
    } catch (err: any) {
      alert(err.message || 'Deactivation failed')
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'indexed':
        return <span style={{ backgroundColor: 'var(--color-success)', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Indexed</span>
      case 'indexing':
        return <span style={{ backgroundColor: 'var(--color-ink)', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Indexing...</span>
      case 'pending_first_index':
        return <span style={{ backgroundColor: '#f59e0b', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Pending First Index</span>
      case 'inactive':
        return <span style={{ backgroundColor: 'var(--color-muted)', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Inactive</span>
      default:
        return <span style={{ backgroundColor: 'var(--color-error)', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>{status}</span>
    }
  }

  return (
    <div className="source-management-page" style={{ padding: '4px 0', color: 'var(--color-text)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 600, margin: 0 }}>Knowledge sources</h2>
          <p style={{ color: 'var(--color-muted)', fontSize: '0.875rem', marginTop: '4px' }}>
            Register repositories and wikis, then trigger indexing from the console.
          </p>
        </div>
        <button
          className="btn-primary"
          style={{ backgroundColor: 'var(--color-ink)', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer' }}
          onClick={() => setIsModalOpen(true)}
          type="button"
        >
          + Register New Source
        </button>
      </div>

      {error && <div style={{ color: 'var(--color-error)', backgroundColor: 'var(--color-error-soft)', padding: '12px', borderRadius: '6px', marginBottom: '16px' }}>{error}</div>}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-muted)' }}>Loading Source Registry...</div>
      ) : (
        <div style={{ backgroundColor: 'var(--color-surface)', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--color-border)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ backgroundColor: 'var(--color-surface-muted)', color: 'var(--color-muted)', borderBottom: '1px solid var(--color-border)' }}>
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
                  <td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: 'var(--color-muted)' }}>
                    No registered sources found. Click "Register New Source" to onboard a repository or wiki.
                  </td>
                </tr>
              ) : (
                sources.map((src) => (
                  <tr key={src.id} style={{ borderBottom: '1px solid var(--color-border)', opacity: src.is_active ? 1 : 0.6 }}>
                    <td style={{ padding: '12px 16px', fontWeight: 500 }}>
                      {src.name}
                      <div style={{ fontSize: '0.75rem', color: 'var(--color-muted)' }}>Owner: {src.owner_email}</div>
                    </td>
                    <td style={{ padding: '12px 16px' }}>{src.source_type}</td>
                    <td style={{ padding: '12px 16px', fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--color-accent)' }}>{src.endpoint_url}</td>
                    <td style={{ padding: '12px 16px' }}>
                      <span style={{ fontSize: '0.75rem', padding: '2px 6px', borderRadius: '4px', backgroundColor: 'var(--color-border)' }}>
                        {src.sensitivity_level}
                      </span>
                    </td>
                    <td style={{ padding: '12px 16px' }}>{getStatusBadge(src.status)}</td>
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {src.is_active && (
                          <button
                            type="button"
                            disabled={triggeringId === src.id || src.status === 'indexing'}
                            onClick={() => handleTriggerIndex(src.id)}
                            style={{ backgroundColor: 'var(--color-success)', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.75rem' }}
                          >
                            {triggeringId === src.id ? 'Triggering...' : 'Trigger Index'}
                          </button>
                        )}
                        {src.is_active && (
                          <button
                            type="button"
                            onClick={() => handleDeactivate(src.id)}
                            style={{ backgroundColor: 'var(--color-error)', color: '#fff', border: 'none', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.75rem' }}
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

      {isModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(18, 32, 51, 0.45)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 }}>
          <div style={{ backgroundColor: 'var(--color-surface)', padding: '24px', borderRadius: '8px', width: '500px', maxWidth: '90%', border: '1px solid var(--color-border)' }}>
            <h3 style={{ margin: 0, marginBottom: '16px', fontSize: '1.25rem' }}>Register Knowledge Source</h3>

            {formError && <div style={{ color: 'var(--color-error)', backgroundColor: 'var(--color-error-soft)', padding: '8px 12px', borderRadius: '4px', marginBottom: '12px', fontSize: '0.875rem' }}>{formError}</div>}

            <form onSubmit={handleCreateSubmit}>
              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Source Display Name</label>
                <input
                  type="text"
                  required
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Connector Type</label>
                <select
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  value={formData.source_type}
                  onChange={(e) => setFormData({ ...formData, source_type: e.target.value })}
                >
                  {(sourceTypes.length > 0 ? sourceTypes : [
                    { type_id: 'github_repo', display_name: 'GitHub Repository', description: '', supported: true },
                    { type_id: 'confluence_wiki', display_name: 'Confluence / Wiki Space', description: '', supported: true },
                  ]).map((t) => (
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
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
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
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  value={formData.secret_reference}
                  onChange={(e) => setFormData({ ...formData, secret_reference: e.target.value })}
                />
              </div>

              <div style={{ marginBottom: '12px' }}>
                <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Owner Email</label>
                <input
                  type="email"
                  required
                  style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  value={formData.owner_email}
                  onChange={(e) => setFormData({ ...formData, owner_email: e.target.value })}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', fontSize: '0.875rem', marginBottom: '4px' }}>Sensitivity Level</label>
                  <select
                    style={{ width: '100%', padding: '8px', borderRadius: '4px', backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
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
                  style={{ backgroundColor: 'var(--color-muted)', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  style={{ backgroundColor: 'var(--color-ink)', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}
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
