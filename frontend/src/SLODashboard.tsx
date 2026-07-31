import React, { useEffect, useState } from 'react'
import { apiClient, SLODashboardData } from './api/client'

const SLO_TARGET = 99.5

export const SLODashboard: React.FC = () => {
  const [data, setData] = useState<SLODashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [evalMsg, setEvalMsg] = useState<string | null>(null)

  const fetchData = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.getSLODashboard(30)
      setData(res)
    } catch (err: any) {
      setError(err.message || 'Failed to load SLO dashboard')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  const evaluateAlert = async () => {
    setEvalMsg(null)
    try {
      const res = await apiClient.evaluateSLOAlert()
      if (res.breached) {
        setEvalMsg(res.message || 'SLO breach alert fired')
      } else {
        setEvalMsg(`Within SLO: ${res.rolling_availability_pct.toFixed(3)}% ≥ ${res.target_pct}%`)
      }
      await fetchData()
    } catch (err: any) {
      setEvalMsg(err.message || 'Alert evaluation failed')
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const rolling = data?.rolling_availability_pct ?? 100
  const meeting = rolling >= (data?.target_pct ?? SLO_TARGET)

  return (
    <div className="slo-dashboard" style={{ padding: '1.5rem', background: 'var(--color-surface)', color: 'var(--color-text)', borderRadius: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>Availability</h2>
          <p style={{ margin: '0.25rem 0 0 0', color: 'var(--color-muted)', fontSize: '0.875rem' }}>
            Query-path uptime against the {data?.target_pct ?? SLO_TARGET}% target · 30-day rolling window
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            onClick={evaluateAlert}
            style={{ background: 'var(--color-accent)', color: '#fff', border: 'none', padding: '0.5rem 1rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 500 }}
          >
            Evaluate Alert
          </button>
          <button
            onClick={fetchData}
            style={{ background: 'var(--color-ink)', color: '#fff', border: 'none', padding: '0.5rem 1rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 500 }}
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: 'var(--color-error-soft)', color: 'var(--color-error)', padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      {(data?.alert_active || evalMsg) && (
        <div
          style={{
            background: data?.alert_active ? 'var(--color-error-soft)' : 'var(--color-success-soft)',
            color: data?.alert_active ? 'var(--color-error)' : 'var(--color-success)',
            padding: '0.75rem 1rem',
            borderRadius: '8px',
            marginBottom: '1rem',
          }}
        >
          {data?.alert_message || evalMsg}
        </div>
      )}

      {loading && !data ? (
        <div style={{ color: 'var(--color-muted)' }}>Loading SLO metrics…</div>
      ) : data ? (
        <>
          <div
            style={{
              background: 'var(--color-surface-muted)',
              border: `1px solid ${meeting ? 'var(--color-success)' : 'var(--color-error)'}`,
              borderRadius: '10px',
              padding: '1.25rem',
              marginBottom: '1.5rem',
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              gap: '1rem',
            }}
          >
            <div>
              <div style={{ color: 'var(--color-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>30-day rolling</div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: meeting ? 'var(--color-success)' : 'var(--color-error)' }}>
                {rolling.toFixed(3)}%
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--color-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>SLO target</div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--color-accent)' }}>{data.target_pct}%</div>
            </div>
            <div>
              <div style={{ color: 'var(--color-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Healthy probes</div>
              <div style={{ fontSize: '1.35rem', fontWeight: 700 }}>
                {data.successful_probes}/{data.total_probes}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--color-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Status</div>
              <div style={{ marginTop: '0.35rem', fontWeight: 700, color: meeting ? 'var(--color-success)' : 'var(--color-error)' }}>
                {meeting ? 'MEETING SLO' : 'BREACH'}
              </div>
            </div>
          </div>

          <div style={{ background: 'var(--color-surface-muted)', padding: '1.25rem', borderRadius: '10px', marginBottom: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: 'var(--color-text)' }}>Per-service availability</h3>
            {Object.keys(data.services).length === 0 ? (
              <div style={{ color: 'var(--color-muted)', fontSize: '0.875rem' }}>
                No health probes recorded yet. Availability samples appear once the probe sampler is running.
              </div>
            ) : (
              Object.entries(data.services).map(([name, svc]) => (
                <div key={name} style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.75rem', fontSize: '0.85rem' }}>
                  <span style={{ width: '160px', color: 'var(--color-muted)' }}>{name}</span>
                  <div style={{ flex: 1, background: 'var(--color-surface-muted)', height: '22px', borderRadius: '4px', overflow: 'hidden' }}>
                    <div style={{ width: `${Math.min(svc.availability_pct, 100)}%`, background: 'var(--color-success)', height: '100%' }} />
                  </div>
                  <span style={{ width: '80px', textAlign: 'right', fontWeight: 600 }}>{svc.availability_pct.toFixed(2)}%</span>
                </div>
              ))
            )}
          </div>

          <div style={{ background: 'var(--color-surface-muted)', padding: '1.25rem', borderRadius: '10px', marginBottom: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: 'var(--color-text)' }}>Daily uptime</h3>
            {data.daily_uptime.length === 0 ? (
              <div style={{ color: 'var(--color-muted)', fontSize: '0.875rem', textAlign: 'center', padding: '1.5rem' }}>No daily samples yet.</div>
            ) : (
              data.daily_uptime.map((d) => (
                <div key={d.date} style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  <span style={{ width: '100px', fontFamily: 'monospace', color: 'var(--color-muted)' }}>{d.date}</span>
                  <div style={{ flex: 1, background: 'var(--color-surface-muted)', height: '18px', borderRadius: '4px', overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${Math.min(d.availability_pct, 100)}%`,
                        background: d.availability_pct >= (data.target_pct ?? SLO_TARGET) ? 'var(--color-success)' : 'var(--color-error)',
                        height: '100%',
                      }}
                    />
                  </div>
                  <span style={{ width: '80px', textAlign: 'right' }}>{d.availability_pct.toFixed(2)}%</span>
                </div>
              ))
            )}
          </div>

          {data.recent_alerts.length > 0 && (
            <div style={{ background: 'var(--color-surface-muted)', padding: '1.25rem', borderRadius: '10px' }}>
              <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: 'var(--color-text)' }}>Recent alerts</h3>
              {data.recent_alerts.map((a) => (
                <div key={a.id} style={{ borderBottom: '1px solid var(--color-border)', padding: '0.5rem 0', fontSize: '0.85rem', color: 'var(--color-error)' }}>
                  <div style={{ fontWeight: 600 }}>{a.message}</div>
                  <div style={{ color: 'var(--color-muted)', fontSize: '0.75rem' }}>
                    {a.created_at} · channel={a.channel} · delivered={String(a.delivered)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}

export default SLODashboard
