import { useState, useEffect } from 'react'
import { apiClient, KnowledgeResponse } from './api/client'
import CitationList, { formatAnswerWithInlineCitations } from './CitationList'

import './App.css'




const KnowledgeAnimation = () => (
  <svg viewBox="0 0 600 240" className="animated-diagram">
    <defs>
      <linearGradient id="lineGradInfo" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stopColor="#0c6b6e" stopOpacity="0.2"/>
        <stop offset="100%" stopColor="#0c6b6e" stopOpacity="0.85"/>
      </linearGradient>
    </defs>
    <path className="flow-path flow-forward" d="M 120 120 L 250 120" />
    <path className="flow-path flow-split" d="M 330 100 L 420 60" />
    <path className="flow-path flow-split" d="M 330 140 L 420 180" />
    
    <g transform="translate(20, 100)">
      <rect width="100" height="40" rx="6" className="node-rect" />
      <text x="50" y="24" className="node-text">User Query</text>
    </g>
    <g transform="translate(250, 80)">
      <rect width="80" height="80" rx="40" className="node-rect" style={{stroke: '#0c6b6e'}} />
      <text x="40" y="40" className="node-text">Router</text>
      <text x="40" y="55" className="node-sub">Hybrid</text>
    </g>
    <g transform="translate(420, 40)">
      <rect width="140" height="40" rx="6" className="node-rect" style={{stroke: 'var(--color-success)'}} />
      <text x="70" y="24" className="node-text">GitHub Repos</text>
    </g>
    <g transform="translate(420, 160)">
      <rect width="140" height="40" rx="6" className="node-rect" style={{stroke: 'var(--color-success)'}} />
      <text x="70" y="24" className="node-text">Azure Blob</text>
    </g>
    <g transform="translate(370, 70)">
      <circle cx="0" cy="0" r="4" fill="var(--color-success)" className="flow-dot" />
    </g>
    <g transform="translate(370, 170)">
      <circle cx="0" cy="0" r="4" fill="var(--color-success)" className="flow-dot" />
    </g>
  </svg>
);

const AgentAnimation = () => (
  <svg viewBox="0 0 700 240" className="animated-diagram">
    <path className="flow-path flow-forward" d="M 120 120 L 180 120" />
    <path className="flow-path flow-forward" d="M 340 120 L 440 120" />
    <path className="flow-path flow-forward" d="M 580 120 L 640 120" />
    <path className="flow-path flow-loop" d="M 260 80 C 260 20, 390 20, 390 80" />
    <path className="flow-path flow-loop-ret" d="M 390 80 C 390 140, 260 140, 260 80" />
    
    <g transform="translate(20, 100)">
      <rect width="100" height="40" rx="6" className="node-rect" />
      <text x="50" y="24" className="node-text">User Task</text>
    </g>
    <g transform="translate(180, 80)">
      <rect width="160" height="80" rx="8" className="node-rect" style={{stroke: '#f59e0b'}} />
      <text x="80" y="30" className="node-text">1. Planner Node</text>
      <text x="80" y="50" className="node-sub">Gemini 2.5 Flash</text>
      <text x="80" y="65" className="node-sub llm-badge">(Low Latency)</text>
    </g>
    <g transform="translate(440, 80)">
      <rect width="140" height="80" rx="8" className="node-rect" style={{stroke: '#0c6b6e'}} />
      <text x="70" y="30" className="node-text">2. Synthesizer</text>
      <text x="70" y="50" className="node-sub">Gemini 2.5 Pro</text>
      <text x="70" y="65" className="node-sub llm-badge">(High Reasoning)</text>
    </g>
    <g transform="translate(320, 25)">
      <rect width="140" height="30" rx="15" className="node-rect" style={{stroke: 'var(--color-success)'}} />
      <text x="70" y="19" className="node-text">Execute Tools</text>
    </g>
    <g transform="translate(640, 100)">
      <rect width="40" height="40" rx="20" className="node-rect" style={{stroke: 'var(--color-text)'}} />
      <text x="20" y="24" className="node-text">End</text>
    </g>
  </svg>
);

import EvaluationDashboard from './EvaluationDashboard'
import CostDashboard from './CostDashboard'
import SLODashboard from './SLODashboard'
import AuditLog from './pages/AuditLog'
import FeedbackBar from './FeedbackBar'
import FeedbackReview from './pages/FeedbackReview'
import SourceManagement from './SourceManagement'
import ModelCardViewer from './pages/ModelCardViewer'

export default function App() {
  useEffect(() => {
    console.log('🚀 VigilRAG Production UI loaded correctly. Version: 1.0.1 (Final)');
  }, [])
  const [activeTab, setActiveTab] = useState<'knowledge' | 'agent' | 'evaluation' | 'cost' | 'slo' | 'audit' | 'feedback-review' | 'sources' | 'documentation' | 'model-cards'>('knowledge')

  // Knowledge State
  const [query, setQuery] = useState('')
  const [loadingKnowledge, setLoadingKnowledge] = useState(false)
  const [knowData, setKnowData] = useState<KnowledgeResponse | null>(null)

  // Agent State
  const [task, setTask] = useState('')
  const [loadingAgent, setLoadingAgent] = useState(false)
  const [agentData, setAgentData] = useState<{ answer: string; steps: string[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showDoc, setShowDoc] = useState(false)

  // Auth State
  const [isLoggedIn, setIsLoggedIn] = useState(apiClient.isLoggedIn())
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [loadingAuth, setLoadingAuth] = useState(false)

  const clearKnowledge = () => {
    setQuery('')
    setKnowData(null)
    setError(null)
  }

  const clearAgent = () => {
    setTask('')
    setAgentData(null)
    setError(null)
  }

  const runKnowledgeQuery = async () => {
    if (!query.trim()) return
    setLoadingKnowledge(true); setError(null); setKnowData(null)
    try {
      const data = await apiClient.queryKnowledge(query)
      setKnowData(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Knowledge API request failed')
    } finally {
      setLoadingKnowledge(false)
    }
  }

  const runAgentTask = async () => {
    if (!task.trim()) return
    setLoadingAgent(true); setError(null); setAgentData(null)
    try {
      const data = await apiClient.runAgentTask(task)
      setAgentData(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Agent orchestration failed')
    } finally {
      setLoadingAgent(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent, fn: () => void) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) fn()
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoadingAuth(true); setError(null)
    try {
      const res = await apiClient.login(loginForm)
      const token = res.token || res.access_token
      if (!token) throw new Error('No token returned')
      apiClient.setToken(token)
      setIsLoggedIn(true)
    } catch (err: any) {
      setError(err?.message ? `Login failed: ${err.message}` : 'Login failed: Invalid credentials.')
    } finally {
      setLoadingAuth(false)
    }
  }

  const handleLogout = () => {
    apiClient.setToken(null)
    setIsLoggedIn(false)
    setLoginForm({ username: '', password: '' })
  }

  if (!isLoggedIn) {
    return (
      <div className="login-page">
        <aside className="login-brand">
          <div className="login-brand-inner">
            <div className="logo">
              <div className="logo-icon">V</div>
              <div>
                <div className="logo-title">VigilRAG</div>
                <div className="logo-sub">Governance console</div>
              </div>
            </div>
            <p className="login-brand-copy">
              Enterprise retrieval with policy gates, auditability, and grounded answers for regulated teams.
            </p>
          </div>
        </aside>
        <div className="login-panel">
          <div className="login-card">
            <h2 className="card-title">Sign in</h2>
            <p className="card-hint">
              Use your console credentials to access knowledge, agents, and compliance tooling.
            </p>

            <form className="mt-24" onSubmit={handleLogin}>
              <div className="form-group">
                <label htmlFor="login-username">Username</label>
                <input
                  id="login-username"
                  type="text"
                  className="task-input"
                  autoComplete="username"
                  value={loginForm.username}
                  onChange={e => setLoginForm({...loginForm, username: e.target.value})}
                  required
                />
              </div>
              <div className="form-group mt-16">
                <label htmlFor="login-password">Password</label>
                <input
                  id="login-password"
                  type="password"
                  className="task-input"
                  autoComplete="current-password"
                  value={loginForm.password}
                  onChange={e => setLoginForm({...loginForm, password: e.target.value})}
                  required
                />
              </div>

              {error && <p className="error-text mt-16">{error}</p>}

              <button className="btn-primary mt-24 w-full" type="submit" disabled={loadingAuth}>
                {loadingAuth ? 'Verifying…' : 'Continue'}
              </button>
            </form>

            <p className="login-footnote">
              Need access? Ask your platform administrator for console credentials.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="logo">
          <div className="logo-icon">V</div>
          <div>
            <div className="logo-title">VigilRAG</div>
            <div className="logo-sub">Operations console</div>
          </div>
        </div>
        <div className="header-actions">
          <div className="header-status">
            <div className="status-dot" />
            Live · Auth enabled
          </div>
          <button className="btn-link logout-btn" onClick={handleLogout} type="button">
            Sign out
          </button>
        </div>
      </header>

      <main className="app-main">
        <div className="tabs">
          <button
            id="tab-knowledge"
            className={`tab ${activeTab === 'knowledge' ? 'active' : ''}`}
            onClick={() => setActiveTab('knowledge')}
          >
            Knowledge
          </button>
          <button
            id="tab-agent"
            className={`tab ${activeTab === 'agent' ? 'active' : ''}`}
            onClick={() => setActiveTab('agent')}
          >
            Agents
          </button>
          <button
            id="tab-evaluation"
            className={`tab ${activeTab === 'evaluation' ? 'active' : ''}`}
            onClick={() => setActiveTab('evaluation')}
          >
            Evaluation
          </button>
          <button
            id="tab-cost"
            className={`tab ${activeTab === 'cost' ? 'active' : ''}`}
            onClick={() => setActiveTab('cost')}
          >
            Cost
          </button>
          <button
            id="tab-slo"
            className={`tab ${activeTab === 'slo' ? 'active' : ''}`}
            onClick={() => setActiveTab('slo')}
          >
            SLO
          </button>
          <button
            id="tab-feedback"
            className={`tab ${activeTab === 'feedback-review' ? 'active' : ''}`}
            onClick={() => setActiveTab('feedback-review')}
          >
            Feedback
          </button>
          <button
            id="tab-sources"
            className={`tab ${activeTab === 'sources' ? 'active' : ''}`}
            onClick={() => setActiveTab('sources')}
          >
            Sources
          </button>
          <button
            id="tab-audit"
            className={`tab ${activeTab === 'audit' ? 'active' : ''}`}
            onClick={() => setActiveTab('audit')}
          >
            Audit
          </button>
          <button
            id="tab-model-cards"
            className={`tab ${activeTab === 'model-cards' ? 'active' : ''}`}
            onClick={() => setActiveTab('model-cards')}
          >
            Model Cards
          </button>
          <button
            id="tab-documentation"
            className={`tab ${activeTab === 'documentation' ? 'active' : ''}`}
            onClick={() => setActiveTab('documentation')}
          >
            Docs
          </button>
        </div>

        {activeTab === 'knowledge' && (
          <div className="card fade-in">
            <h2 className="card-title">Knowledge search</h2>
            <p className="card-hint">
              Semantic retrieval across repositories, document stores, and databases — with citations and stable source IDs.
            </p>
            <textarea
              id="knowledge-query-input"
              className="task-input"
              rows={3}
              placeholder="e.g., What is our PII policy and how does the auth service handle token validation?"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => handleKeyDown(e, runKnowledgeQuery)}
            />
            <div className="button-group">
              <button
                id="knowledge-submit-btn"
                className="btn-primary"
                onClick={runKnowledgeQuery}
                disabled={loadingKnowledge || !query.trim()}
              >
                {loadingKnowledge ? 'Searching knowledge graph…' : 'Execute Query'}
              </button>
              <button className="btn-secondary" onClick={clearKnowledge} disabled={loadingKnowledge}>
                Clear
              </button>
              <button className="btn-link" onClick={() => setShowDoc(!showDoc)}>
                {showDoc ? 'Hide Details' : 'How it works?'}
              </button>
            </div>

            {showDoc && (
              <div className="doc-panel fade-in">
                <div className="doc-header">
                  <h4>How knowledge search works</h4>
                  <span className="badge badge-info">Overview</span>
                </div>
                
                <div className="doc-content">
                  <div className="svg-diagram-wrapper">
                    <KnowledgeAnimation />
                  </div>
                  
                  <div className="doc-grid-cols">
                    <div className="doc-section">
                      <h5>Architectural Role</h5>
                      <p>The Knowledge API is a <strong>unified semantic retrieval layer</strong> that abstracts enterprise systems into a single predictable interface.</p>
                      <ul>
                        <li><strong>Source Abstraction</strong>: Hides the complexity of GitHub, Azure Blob, and SQL.</li>
                        <li><strong>Trust Boundary</strong>: Enforces safe, read-only data access.</li>
                      </ul>
                    </div>
                    <div className="doc-section">
                      <h5>System Design Properties (Non-LLM)</h5>
                      <ul>
                        <li><strong>Data Contracts</strong>: Normalized JSON schema with stable IDs.</li>
                        <li><strong>Traceability</strong>: All retrieved facts are strictly traceable.</li>
                        <li><strong>LLM Role</strong>: <em>None in this layer.</em> Hybrid vector + keyword (RRF) over Postgres/pgvector with optional cross-encoder reranking; synthesis happens in the Agent Orchestrator.</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {knowData && (
              <div className="results-container mt-24 fade-in">
                <h4 className="section-heading">Response & Synthesis</h4>
                <div className="synthesis-text">
                  {formatAnswerWithInlineCitations(
                    knowData.answer_synthesis || `Retrieved ${knowData.evidence?.length || 0} evidence records from hybrid semantic search.`
                  )}
                </div>

                <CitationList
                  citations={knowData.evidence}
                  guardrailFlags={(knowData as any).guardrail_flags}
                />

                {(knowData as any).groundedness_score != null && (
                  <div className="mt-12" style={{ fontSize: '0.9rem', color: 'var(--color-muted)' }}>
                    <strong style={{ color: 'var(--color-text)' }}>Groundedness score:</strong>{' '}
                    {Number((knowData as any).groundedness_score).toFixed(2)}
                    {(knowData as any).retrieval_engine && (
                      <span style={{ marginLeft: 12 }}>
                        Engine: <code style={{ color: 'var(--color-accent)' }}>{(knowData as any).retrieval_engine}</code>
                      </span>
                    )}
                  </div>
                )}

                <FeedbackBar queryId={(knowData as any).query_id || knowData.trace_id} />



                <details className="mt-16" style={{ cursor: 'pointer', opacity: 0.85 }}>
                  <summary style={{ fontWeight: 600, color: 'var(--color-muted)' }}>Debug & Execution Trace</summary>

                  <div className="meta-grid mt-12" style={{ padding: '12px', background: 'var(--color-surface-muted)', borderRadius: '6px' }}>
                    {knowData.trace_id && (
                      <div className="meta-row">
                        <span className="source-tag">Trace ID</span>
                        <code style={{ color: 'var(--color-accent)' }}>{knowData.trace_id}</code>
                      </div>
                    )}

                    <div className="meta-row">
                      <span className="source-tag">Execution Time</span>
                      <span>{knowData.execution_time_ms} ms</span>
                    </div>

                  </div>

                </details>

              </div>
            )}
          </div>
        )}


        {activeTab === 'agent' && (
          <div className="card fade-in">
            <h2 className="card-title">Agent orchestrator</h2>
            <p className="card-hint">
              Breaks multi-source questions into a plan, retrieves grounded evidence, and returns a cited answer.
            </p>
            <textarea
              id="agent-task-input"
              className="task-input"
              rows={3}
              placeholder="e.g., Trace the auth implementation and verify it matches the API Authentication Policy."
              value={task}
              onChange={e => setTask(e.target.value)}
              onKeyDown={e => handleKeyDown(e, runAgentTask)}
            />
            <div className="button-group">
              <button
                id="agent-submit-btn"
                className="btn-primary"
                onClick={runAgentTask}
                disabled={loadingAgent || !task.trim()}
              >
                {loadingAgent ? 'Running…' : 'Run agent'}
              </button>
              <button className="btn-secondary" onClick={clearAgent} disabled={loadingAgent}>
                Clear
              </button>
              <button className="btn-link" onClick={() => setShowDoc(!showDoc)}>
                {showDoc ? 'Hide Details' : 'How it works?'}
              </button>
            </div>

            {showDoc && (
              <div className="doc-panel fade-in">
                <div className="doc-header">
                  <h4>How the agent works</h4>
                  <span className="badge badge-success">Orchestration</span>
                </div>

                <div className="doc-content">
                  <div className="svg-diagram-wrapper">
                    <AgentAnimation />
                  </div>

                  <div className="doc-grid-cols">
                    <div className="doc-section">
                      <h5>What it does</h5>
                      <p>A <strong>stateful orchestration layer</strong> that plans retrieval steps and synthesizes a cited answer from evidence.</p>
                      <ul>
                        <li><strong>Session state</strong>: Keeps context across plan → retrieve → answer steps.</li>
                        <li><strong>Controlled tools</strong>: Only calls approved knowledge and utility tools.</li>
                      </ul>
                    </div>
                    <div className="doc-section">
                      <h5>Pipeline</h5>
                      <ul>
                        <li><strong>1. Planner</strong>: Decomposes the task and chooses retrieval steps.</li>
                        <li><strong>2. Retrieval</strong>: Runs knowledge searches against registered sources.</li>
                        <li><strong>3. Synthesizer</strong>: Builds the final answer from retrieved facts only.</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {loadingAgent && (
              <div className="agent-loader mt-24 fade-in">
                <div className="pulse-ring"></div>
                <div className="loader-text">
                  <strong>Agent orchestrating...</strong>
                  <span>Decomposing query, searching knowledge base, and synthesizing...</span>
                </div>
              </div>
            )}

            {agentData && !loadingAgent && (
              <div className="results-container mt-24 fade-in">
                <div className="agent-meta">
                  <span className="badge badge-info">Complete</span>
                  <span className="badge badge-success">{agentData.steps.length} tools executed</span>
                </div>

                <div className="agent-steps fade-in">
                  <h4 className="section-heading">Execution Trace</h4>
                  <ul className="step-timeline">
                    {agentData.steps.map((step, i) => (
                      <li key={i} className="timeline-item">
                        <div className="timeline-dot"></div>
                        <div className="timeline-content">
                          {step}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>

                <h4 className="section-heading">Agent Conclusion</h4>
                <div className="agent-answer">{agentData.answer}</div>
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="card error-card fade-in mt-16">
            <span className="badge badge-error">Error</span>
            <p style={{ marginTop: 8, color: 'var(--color-error)', fontSize: '0.9rem' }}>{error}</p>
          </div>
        )}

        {activeTab === 'evaluation' && (
          <div className="tab-content fade-in">
            <EvaluationDashboard />
          </div>
        )}

        {activeTab === 'cost' && (
          <div className="tab-content fade-in">
            <CostDashboard />
          </div>
        )}

        {activeTab === 'slo' && (
          <div className="tab-content fade-in">
            <SLODashboard />
          </div>
        )}

        {activeTab === 'audit' && (
          <div className="tab-content fade-in">
            <AuditLog />
          </div>
        )}

        {activeTab === 'model-cards' && (
          <div className="tab-content fade-in">
            <ModelCardViewer />
          </div>
        )}

        {activeTab === 'feedback-review' && (
          <div className="tab-content fade-in">
            <FeedbackReview />
          </div>
        )}

        {activeTab === 'sources' && (
          <div className="tab-content fade-in">
            <SourceManagement />
          </div>
        )}

        {activeTab === 'documentation' && (
          <div className="card fade-in">
            <h2 className="card-title">Documentation</h2>
            <p className="card-hint">
              How VigilRAG retrieves knowledge, keeps answers grounded, and scales as corpus size grows.
            </p>

            <div className="faq-container mt-16">
              
              {/* Beginner / Non-Tech */}
              <div className="faq-item">
                <div className="faq-badge badge-success">Beginner</div>
                <h3 className="faq-question">How does the agent know the answers? Does it make things up?</h3>
                <p className="faq-answer">
                  The Multi-Agent Orchestrator acts like a very fast researcher. Before it answers your question, it creates a "plan" and reaches out to the Knowledge API. The Knowledge API reads your exact, live company files (from GitHub code and Azure Wiki documents). The agent then summarizes <strong>only</strong> the facts it physically retrieved from those documents. This strictly prevents the AI from "hallucinating" or inventing made-up answers.
                </p>
              </div>

              {/* Technical / Developer */}
              <div className="faq-item">
                <div className="faq-badge badge-info">Technical</div>
                <h3 className="faq-question">Are we using a Vector Database for Semantic Search?</h3>
                <p className="faq-answer">
                  <strong>Yes.</strong> Layer 2 runs hybrid retrieval: dense embeddings stored in{' '}
                  <strong>Postgres + pgvector</strong>, fused with keyword/FTS via Reciprocal Rank Fusion (RRF),
                  then optionally reranked with a cross-encoder. A modular <code>QueryRouter</code> selects the
                  vector engine today and reserves a graph-engine stub for future GraphRAG (Phase 4+).
                </p>
              </div>

              <div className="faq-item">
                <div className="faq-badge badge-accent" style={{background: 'var(--color-accent-soft)', color: 'var(--color-accent)', border: '1px solid rgba(12,107,110,0.3)'}}>Expert / Architect</div>
                <h3 className="faq-question">How do we scale retrieval next?</h3>
                <p className="faq-answer">
                  At current pilot scale, Postgres with pgvector remains the default vector store.
                  A pluggable search backend (pgvector, Qdrant, or dual-write) is available if latency
                  or corpus size requires it. Graph-style retrieval can join through the same query
                  router when relationship-shaped questions need more than vector search.
                </p>
              </div>

            </div>
          </div>
        )}
      </main>
    </div>
  )
}
