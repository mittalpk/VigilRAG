import React, { useEffect, useState } from 'react'
import { apiClient, CostDashboardData } from './api/client'

export const CostDashboard: React.FC = () => {
  const [data, setData] = useState<CostDashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(30)

  const fetchData = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.getCostDashboard(days)
      setData(res)
    } catch (err: any) {
      setError(err.message || 'Failed to load cost dashboard')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [days])

  const maxDaily = Math.max(...(data?.daily_trend.map((d) => d.avg_cost_per_query_usd) || [0]), 0.000001)

  return (
    <div className="cost-dashboard" style={{ padding: '1.5rem', background: 'var(--color-surface)', color: 'var(--color-text)', borderRadius: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>Query cost</h2>
          <p style={{ margin: '0.25rem 0 0 0', color: 'var(--color-muted)', fontSize: '0.875rem' }}>
            Estimated spend per query based on model token usage and published pricing.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            style={{ background: 'var(--color-surface)', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: '6px', padding: '0.4rem 0.6rem' }}
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
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

      {data?.alert_spike && (
        <div style={{ background: 'var(--color-warn-soft)', color: 'var(--color-warn)', padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1rem' }}>
          {data.spike_message || 'Unexpected cost spike detected — investigate query types / model routing.'}
        </div>
      )}

      {loading && !data ? (
        <div style={{ color: 'var(--color-muted)' }}>Loading cost metrics…</div>
      ) : data ? (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: '1rem',
              marginBottom: '1.5rem',
            }}
          >
            <SummaryCard label="Avg cost / query" value={`$${data.avg_cost_per_query_usd.toFixed(6)}`} accent="var(--color-accent)" />
            <SummaryCard label={`Total (${days}d)`} value={`$${data.total_cost_usd.toFixed(4)}`} accent="var(--color-success)" />
            <SummaryCard label="Queries" value={String(data.total_queries)} accent="var(--color-accent)" />
            <SummaryCard label="90-day total" value={`$${data.pi_total_cost_usd.toFixed(4)}`} accent="var(--color-warn)" />
          </div>

          <div style={{ background: 'var(--color-surface-muted)', padding: '1.25rem', borderRadius: '10px', marginBottom: '1.5rem' }}>
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: 'var(--color-text)' }}>Cost breakdown by model</h3>
            {Object.keys(data.cost_by_model).length === 0 ? (
              <div style={{ color: 'var(--color-muted)', fontSize: '0.875rem' }}>No cost records yet. Costs appear after agent or knowledge queries run.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {Object.entries(data.cost_by_model).map(([family, cost]) => {
                  const pct = data.total_cost_usd > 0 ? (cost / data.total_cost_usd) * 100 : 0
                  return (
                    <div key={family} style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.85rem' }}>
                      <span style={{ width: '80px', color: 'var(--color-muted)' }}>{family}</span>
                      <div style={{ flex: 1, background: 'var(--color-surface-muted)', height: '24px', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{ width: `${Math.max(pct, 2)}%`, background: family === 'Flash' ? 'var(--color-success)' : 'var(--color-accent)', height: '100%' }} />
                      </div>
                      <span style={{ width: '100px', textAlign: 'right', fontWeight: 600 }}>${cost.toFixed(6)}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div style={{ background: 'var(--color-surface-muted)', padding: '1.25rem', borderRadius: '10px' }}>
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: 'var(--color-text)' }}>Cost / query trend</h3>
            {data.daily_trend.length === 0 ? (
              <div style={{ color: 'var(--color-muted)', fontSize: '0.875rem', textAlign: 'center', padding: '2rem' }}>
                No trend data yet. Run queries to populate the daily cost chart.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                {data.daily_trend.map((d) => (
                  <div key={d.date} style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.85rem' }}>
                    <span style={{ width: '100px', color: 'var(--color-muted)', fontFamily: 'monospace' }}>{d.date}</span>
                    <div style={{ flex: 1, background: 'var(--color-surface-muted)', height: '22px', borderRadius: '4px', overflow: 'hidden' }}>
                      <div
                        title={`$${d.avg_cost_per_query_usd.toFixed(8)} / query`}
                        style={{
                          width: `${Math.max((d.avg_cost_per_query_usd / maxDaily) * 100, 2)}%`,
                          background: 'var(--color-accent)',
                          height: '100%',
                        }}
                      />
                    </div>
                    <span style={{ width: '120px', textAlign: 'right', color: 'var(--color-accent)', fontWeight: 600 }}>
                      ${d.avg_cost_per_query_usd.toFixed(6)}
                    </span>
                    <span style={{ width: '60px', textAlign: 'right', color: 'var(--color-muted)' }}>{d.query_count}q</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}

const SummaryCard: React.FC<{ label: string; value: string; accent: string }> = ({ label, value, accent }) => (
  <div style={{ background: 'var(--color-surface-muted)', borderRadius: '10px', padding: '1rem', border: `1px solid ${accent}33` }}>
    <div style={{ color: 'var(--color-muted)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
    <div style={{ fontSize: '1.35rem', fontWeight: 700, color: accent, marginTop: '0.35rem' }}>{value}</div>
  </div>
)

export default CostDashboard
