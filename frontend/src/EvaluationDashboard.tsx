import React, { useState, useEffect } from 'react'
import { apiClient, EvaluationRunItem } from './api/client'

export interface EvaluationDashboardProps {
  thresholdFaithfulness?: number
}

export const EvaluationDashboard: React.FC<EvaluationDashboardProps> = ({
  thresholdFaithfulness = 0.85,
}) => {
  const [runs, setRuns] = useState<EvaluationRunItem[]>([])
  const [latestRun, setLatestRun] = useState<EvaluationRunItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [datasetFilter, setDatasetFilter] = useState<string>('')
  const [pipelineFilter, setPipelineFilter] = useState<string>('')

  const fetchDashboardData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [listRes, latestRes] = await Promise.allSettled([
        apiClient.getEvaluationRuns(
          datasetFilter || undefined,
          pipelineFilter || undefined,
          1,
          50
        ),
        apiClient.getLatestEvaluationRun(),
      ])

      if (listRes.status === 'fulfilled') {
        setRuns(listRes.value.items)
      } else {
        setRuns([])
      }

      if (latestRes.status === 'fulfilled') {
        setLatestRun(latestRes.value)
      } else {
        setLatestRun(null)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load evaluation runs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDashboardData()
  }, [datasetFilter, pipelineFilter])

  return (
    <div className="eval-dashboard" style={{ padding: '1.5rem', background: '#0f172a', color: '#f8fafc', borderRadius: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 600 }}>RAGAS Evaluation & Quality Dashboard</h2>
          <p style={{ margin: '0.25rem 0 0 0', color: '#94a3b8', fontSize: '0.875rem' }}>
            Historical evaluation runs, AI quality trends & CI gate compliance
          </p>
        </div>
        <button
          onClick={fetchDashboardData}
          style={{
            background: '#3b82f6',
            color: '#fff',
            border: 'none',
            padding: '0.5rem 1rem',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 500,
          }}
        >
          Refresh Runs
        </button>
      </div>

      {error && (
        <div style={{ background: '#7f1d1d', color: '#fca5a5', padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      {/* Prominent Latest Run Card */}
      {latestRun ? (
        <div
          style={{
            background: '#1e293b',
            border: `1px solid ${latestRun.faithfulness >= thresholdFaithfulness ? '#22c55e' : '#ef4444'}`,
            borderRadius: '10px',
            padding: '1.25rem',
            marginBottom: '1.5rem',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '1rem',
          }}
        >
          <div>
            <div style={{ color: '#94a3b8', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Latest Run Status
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
              <span
                style={{
                  display: 'inline-block',
                  padding: '0.25rem 0.6rem',
                  borderRadius: '9999px',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  background: latestRun.faithfulness >= thresholdFaithfulness ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                  color: latestRun.faithfulness >= thresholdFaithfulness ? '#4ade80' : '#f87171',
                }}
              >
                {latestRun.faithfulness >= thresholdFaithfulness ? '✓ PASSED CI GATE' : '✗ REGRESSION FLAG'}
              </span>
            </div>
          </div>
          <div>
            <div style={{ color: '#94a3b8', fontSize: '0.75rem', textTransform: 'uppercase' }}>Faithfulness</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#60a5fa' }}>
              {(latestRun.faithfulness * 100).toFixed(1)}%
            </div>
          </div>
          <div>
            <div style={{ color: '#94a3b8', fontSize: '0.75rem', textTransform: 'uppercase' }}>Context Precision</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#34d399' }}>
              {(latestRun.context_precision * 100).toFixed(1)}%
            </div>
          </div>
          <div>
            <div style={{ color: '#94a3b8', fontSize: '0.75rem', textTransform: 'uppercase' }}>Context Recall</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#a78bfa' }}>
              {(latestRun.context_recall * 100).toFixed(1)}%
            </div>
          </div>
          <div>
            <div style={{ color: '#94a3b8', fontSize: '0.75rem', textTransform: 'uppercase' }}>Answer Relevancy</div>
            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#facc15' }}>
              {(latestRun.answer_relevancy * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      ) : !loading ? (
        <div style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '10px', marginBottom: '1.5rem', color: '#94a3b8' }}>
          No evaluation runs recorded. Run <code>scripts/run_evaluation.py</code> to generate the first record.
        </div>
      ) : null}

      {/* Filter Controls */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
        <input
          type="text"
          placeholder="Filter by dataset_version (e.g. v1.0)"
          value={datasetFilter}
          onChange={(e) => setDatasetFilter(e.target.value)}
          style={{
            background: '#1e293b',
            border: '1px solid #334155',
            color: '#f8fafc',
            padding: '0.5rem 0.75rem',
            borderRadius: '6px',
            fontSize: '0.875rem',
            flex: 1,
          }}
        />
        <input
          type="text"
          placeholder="Filter by pipeline_version / commit"
          value={pipelineFilter}
          onChange={(e) => setPipelineFilter(e.target.value)}
          style={{
            background: '#1e293b',
            border: '1px solid #334155',
            color: '#f8fafc',
            padding: '0.5rem 0.75rem',
            borderRadius: '6px',
            fontSize: '0.875rem',
            flex: 1,
          }}
        />
      </div>

      {/* Trend Visualizer */}
      <div style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '10px', marginBottom: '1.5rem' }}>
        <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: '#cbd5e1' }}>Quality Trend Overview</h3>
        {runs.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: '0.875rem', textAlign: 'center', padding: '2rem' }}>
            No trend data available for current filters.
          </div>
        ) : runs.length === 1 ? (
          <div style={{ padding: '1.5rem', background: '#0f172a', borderRadius: '8px', textAlign: 'center' }}>
            <span style={{ fontSize: '0.875rem', color: '#94a3b8' }}>
              Single evaluation run recorded ({runs[0].pipeline_version}) — Faithfulness: {(runs[0].faithfulness * 100).toFixed(1)}%, Context Precision: {(runs[0].context_precision * 100).toFixed(1)}%, Context Recall: {(runs[0].context_recall * 100).toFixed(1)}%. (Trend line requires ≥2 runs).
            </span>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {runs.slice().reverse().map((r, idx) => (
              <div key={r.id || idx} style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.85rem' }}>
                <span style={{ width: '120px', color: '#94a3b8', fontFamily: 'monospace' }}>{r.pipeline_version}</span>
                <div style={{ flex: 1, background: '#0f172a', height: '24px', borderRadius: '4px', overflow: 'hidden', display: 'flex' }}>
                  <div
                    title={`Faithfulness: ${(r.faithfulness * 100).toFixed(1)}%`}
                    style={{ width: `${r.faithfulness * 100}%`, background: '#60a5fa', height: '100%' }}
                  />
                </div>
                <span style={{ width: '60px', textAlign: 'right', fontWeight: 600, color: '#60a5fa' }}>
                  {(r.faithfulness * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Summary Table */}
      <div style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '10px', overflowX: 'auto' }}>
        <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: '#cbd5e1' }}>Historical Runs</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #334155', color: '#94a3b8' }}>
              <th style={{ padding: '0.5rem' }}>Run ID / Commit</th>
              <th style={{ padding: '0.5rem' }}>Dataset</th>
              <th style={{ padding: '0.5rem' }}>Cases</th>
              <th style={{ padding: '0.5rem' }}>Faithfulness</th>
              <th style={{ padding: '0.5rem' }}>Context Precision</th>
              <th style={{ padding: '0.5rem' }}>Context Recall</th>
              <th style={{ padding: '0.5rem' }}>Relevancy</th>
              <th style={{ padding: '0.5rem' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} style={{ borderBottom: '1px solid #0f172a' }}>
                <td style={{ padding: '0.5rem', fontFamily: 'monospace' }}>{r.pipeline_version}</td>
                <td style={{ padding: '0.5rem' }}>{r.dataset_version}</td>
                <td style={{ padding: '0.5rem' }}>{r.total_cases}</td>
                <td style={{ padding: '0.5rem', fontWeight: 600, color: '#60a5fa' }}>{(r.faithfulness * 100).toFixed(1)}%</td>
                <td style={{ padding: '0.5rem', color: '#34d399' }}>{(r.context_precision * 100).toFixed(1)}%</td>
                <td style={{ padding: '0.5rem', color: '#a78bfa' }}>{(r.context_recall * 100).toFixed(1)}%</td>
                <td style={{ padding: '0.5rem', color: '#facc15' }}>{(r.answer_relevancy * 100).toFixed(1)}%</td>
                <td style={{ padding: '0.5rem' }}>
                  <span style={{ color: r.faithfulness >= thresholdFaithfulness ? '#4ade80' : '#f87171', fontWeight: 600 }}>
                    {r.faithfulness >= thresholdFaithfulness ? 'Passed' : 'Failed'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default EvaluationDashboard
