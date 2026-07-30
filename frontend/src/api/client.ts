/**
 * VigilRAG API Client — typed wrappers for backend, agent, and audit services.
 */
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? '/api'
const AGENT_URL   = import.meta.env.VITE_AGENT_URL   ?? BACKEND_URL

let authToken: string | null = localStorage.getItem('vigilrag_token')

async function request<T>(url: string, options: RequestInit = {}, timeoutMs = 10000): Promise<T> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  const headers = new Headers(options.headers || {})
  headers.set('Content-Type', 'application/json')
  
  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`)
  }

  try {
    const res = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
      credentials: 'include',  // Include cookies and credentials for CORS
    })
    clearTimeout(timeoutId)

    if (res.status === 401) {
      localStorage.removeItem('vigilrag_token')
      window.location.reload()
    }

    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    return res.json() as Promise<T>
  } catch (err: any) {
    clearTimeout(timeoutId)
    if (err.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s. Please check backend connectivity.`)
    }
    throw err
  }
}

async function requestText(url: string, options: RequestInit = {}, timeoutMs = 10000): Promise<string> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  const headers = new Headers(options.headers || {})
  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`)
  }
  try {
    const res = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
      credentials: 'include',
    })
    clearTimeout(timeoutId)
    if (res.status === 401) {
      localStorage.removeItem('vigilrag_token')
      window.location.reload()
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)
    return res.text()
  } catch (err: any) {
    clearTimeout(timeoutId)
    if (err.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s. Please check backend connectivity.`)
    }
    throw err
  }
}


export interface UnifiedFact {
  fact: string;
  confidence: number;
  derived_from_stable_ids: string[];
}

export interface SourceMetadata {
  source_system: string;
  stable_id: string;
  timestamp: string;
  url: string;
}

export interface EvidenceItem {
  chunk_id: string;
  content: string;
  source_url: string;
  relevance_score: number;
  source_id: string;
  parent_doc_id?: string;
  references?: string[];
  permissions_ref?: string;
}


export interface HybridRetrievalResponse {
  evidence: EvidenceItem[];
  trace_id: string;
  query_id: string;  // GAP-F01: required for feedback submission (US-019)
  execution_time_ms: number;
  query: string;
  total_retrieved: number;
  source_availability_warning?: string[];
  groundedness_score?: number;
  retrieval_engine?: string;
}

export interface KnowledgeResponse {
  answer_synthesis: string;
  facts: UnifiedFact[];
  metadata: SourceMetadata[];
  execution_time_ms: number;
  evidence?: EvidenceItem[];
  trace_id?: string;
  query_id?: string;  // GAP-F01: populated from HybridRetrievalResponse for feedback submission
  groundedness_score?: number;
  retrieval_engine?: string;
}

export interface EvaluationRunItem {
  id: string
  pipeline_version: string
  dataset_version: string
  total_cases: number
  faithfulness: number
  context_precision: number
  context_recall: number
  answer_relevancy: number
  passed_threshold: boolean
  run_at: string
  details?: Array<{
    case_id: string
    query: string
    faithfulness: number
    context_precision: number
    context_recall: number
    answer_relevancy: number
  }>
}

export interface EvaluationRunListResponse {
  items: EvaluationRunItem[]
  total: number
  page: number
  size: number
}

// ── Audit Log Interfaces (US-018) ──────────────────────────────────────────

export interface AuditQueryItem {
  query_id: string
  requester_identity: string
  text: string
  timestamp: string
  answer_text?: string
  citations?: any[]
  groundedness_score?: number
  guardrail_flags?: string[]
}

export interface AuditQueryListResponse {
  items: AuditQueryItem[]
  total: number
  page: number
  per_page: number
}

export interface AuditEvidenceItem {
  id?: string
  chunk_id: string
  content_excerpt: string
  source_url?: string
  relevance_score?: number
  used_in_answer: boolean
  permission_denied: boolean
}

export interface AuditQueryDetailResponse extends AuditQueryItem {
  evidence_items: AuditEvidenceItem[]
  truncated: boolean
}

export interface AuditExportResponse {
  export_id: string
  status: string
  async: boolean
  row_count: number
  download_url?: string
  expires_at?: string
  message?: string
}

export interface AuditRetentionStatus {
  retention_days: number
  latest_run?: {
    id: string
    status: string
    started_at?: string
    finished_at?: string
    records_archived?: number
    cutoff_at?: string
    error_message?: string
  } | null
  recent_runs: Array<{
    id: string
    status: string
    records_archived?: number
    started_at?: string
  }>
}

export interface FeedbackResponse {
  received: boolean
  feedback_id: string
  query_id: string
  rating: string
  message: string
}

export interface FeedbackReviewItemResponse {
  id: string
  feedback_id?: string
  query_id: string
  requester_identity: string
  query_text: string
  answer_text?: string
  user_comment?: string
  rating: string
  status: string
  golden_answer?: string
  reviewed_by?: string
  created_at: string
}

export interface FeedbackReviewListResponse {
  items: FeedbackReviewItemResponse[]
  total: number
  page: number
  size: number
}

// ── Cost / SLO Dashboard (US-036) ──────────────────────────────────────────

export interface CostDailyPoint {
  date: string
  total_cost_usd: number
  query_count: number
  avg_cost_per_query_usd: number
}

export interface CostDashboardData {
  total_cost_usd: number
  total_queries: number
  avg_cost_per_query_usd: number
  cost_by_model: Record<string, number>
  daily_trend: CostDailyPoint[]
  pi_total_cost_usd: number
  alert_spike: boolean
  spike_message?: string | null
  window_days: number
}

export interface SLODailyPoint {
  date: string
  availability_pct: number
  total_probes: number
  healthy_probes: number
}

export interface AvailabilityAlertItem {
  id: string
  alert_type: string
  message: string
  rolling_availability_pct: number
  target_pct: number
  channel: string
  delivered: boolean
  created_at?: string | null
}

export interface SLODashboardData {
  target_pct: number
  window_days: number
  rolling_availability_pct: number
  total_probes: number
  successful_probes: number
  failed_probes: number
  services: Record<string, { total: number; healthy: number; availability_pct: number }>
  alert_active: boolean
  alert_message?: string | null
  recent_alerts: AvailabilityAlertItem[]
  daily_uptime: SLODailyPoint[]
}

export const apiClient = {
  setToken: (token: string | null) => {
    authToken = token
    if (token) localStorage.setItem('vigilrag_token', token)
    else localStorage.removeItem('vigilrag_token')
  },

  isLoggedIn: () => !!authToken,

  login: (credentials: { username: string; password: string }) =>
    request<{ token: string; access_token?: string; role?: string }>(`${BACKEND_URL}/api/v1/auth/token`, {
      method: 'POST',
      body: JSON.stringify(credentials)
    }),

  checkHealth: () =>
    request<{ status: string; service: string }>(`${BACKEND_URL}/health`),

  queryKnowledge: (query: string, target_systems: string[] = ["confluence", "code_repos", "databases"], top_k: number = 5) =>
    request<HybridRetrievalResponse & KnowledgeResponse>(
      `${BACKEND_URL}/api/v1/knowledge/query`,
      { method: 'POST', body: JSON.stringify({ query, target_systems, top_k }) }
    ),

  runAgentTask: (task: string, max_iterations = 10) =>
    request<{ task: string; answer: string; steps: string[] }>(
      `${AGENT_URL}/api/v1/agent/run`,
      { method: 'POST', body: JSON.stringify({ task, max_iterations }) }
    ),

  getLatestEvaluationRun: () =>
    request<EvaluationRunItem>(`${BACKEND_URL}/api/v1/admin/evaluation-runs/latest`),

  getEvaluationRuns: (datasetVersion?: string, pipelineVersion?: string, page = 1, size = 10) => {
    const params = new URLSearchParams({ page: String(page), size: String(size) })
    if (datasetVersion) params.set('dataset_version', datasetVersion)
    if (pipelineVersion) params.set('pipeline_version', pipelineVersion)
    return request<EvaluationRunListResponse>(`${BACKEND_URL}/api/v1/admin/evaluation-runs?${params.toString()}`)
  },

  getAuditQueries: (identity?: string, fromDate?: string, toDate?: string, page = 1, perPage = 50, q?: string) => {
    const params = new URLSearchParams({ page: String(page), per_page: String(perPage) })
    if (identity) params.set('identity', identity)
    if (fromDate) params.set('from_date', fromDate)
    if (toDate) params.set('to_date', toDate)
    if (q) params.set('q', q)
    return request<AuditQueryListResponse>(`${BACKEND_URL}/api/v1/audit/queries?${params.toString()}`)
  },

  getAuditQueryDetail: (queryId: string) =>
    request<AuditQueryDetailResponse>(`${BACKEND_URL}/api/v1/audit/queries/${queryId}`),

  exportAuditLog: (fromDate: string, toDate: string, format: 'csv' | 'pdf' | 'json' = 'csv', identity?: string, q?: string) =>
    request<AuditExportResponse>(`${BACKEND_URL}/api/v1/audit/export`, {
      method: 'POST',
      body: JSON.stringify({ from_date: fromDate, to_date: toDate, format, identity, q }),
    }),

  getAuditRetentionStatus: () =>
    request<AuditRetentionStatus>(`${BACKEND_URL}/api/v1/audit/retention`),

  triggerAuditDigest: (cadence: 'weekly' | 'monthly' = 'weekly') =>
    request<{ status: string; stats: Record<string, unknown> }>(
      `${BACKEND_URL}/api/v1/audit/digest?cadence=${cadence}`,
      { method: 'POST' }
    ),

  submitFeedback: (queryId: string, rating: 'positive' | 'negative', comment?: string) =>
    request<FeedbackResponse>(`${BACKEND_URL}/api/v1/feedback`, {
      method: 'POST',
      body: JSON.stringify({ query_id: queryId, rating, comment }),
    }),

  getFeedbackReviewQueue: (statusFilter?: string, page = 1, size = 10) => {
    const params = new URLSearchParams({ page: String(page), size: String(size) })
    if (statusFilter) params.set('status_filter', statusFilter)
    return request<FeedbackReviewListResponse>(`${BACKEND_URL}/api/v1/admin/feedback-review?${params.toString()}`)
  },

  actionFeedbackReviewItem: (itemId: string, action: 'promote' | 'dismiss' | 'needs_investigation', goldenAnswer?: string) =>
    request<{ success: boolean; item_id: string; status: string }>(`${BACKEND_URL}/api/v1/admin/feedback-review/${itemId}/action`, {
      method: 'POST',
      body: JSON.stringify({ action, golden_answer: goldenAnswer }),
    }),

  getCostDashboard: (days = 30) =>
    request<CostDashboardData>(`${BACKEND_URL}/api/v1/admin/costs/dashboard?days=${days}`),

  getSLODashboard: (days = 30) =>
    request<SLODashboardData>(`${BACKEND_URL}/api/v1/admin/slo/dashboard?days=${days}`),

  evaluateSLOAlert: () =>
    request<{ breached: boolean; rolling_availability_pct: number; target_pct: number; alert_id?: string; message?: string }>(
      `${BACKEND_URL}/api/v1/admin/slo/evaluate-alert`,
      { method: 'POST' }
    ),

  getLatestModelCard: () =>
    requestText(`${BACKEND_URL}/api/v1/admin/model-cards/latest`),
}
