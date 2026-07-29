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
  execution_time_ms: number;
  query: string;
  total_retrieved: number;
}

export interface KnowledgeResponse {
  answer_synthesis: string;
  facts: UnifiedFact[];
  metadata: SourceMetadata[];
  execution_time_ms: number;
  evidence?: EvidenceItem[];
  trace_id?: string;
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

  getAuditQueries: (identity?: string, fromDate?: string, toDate?: string, page = 1, perPage = 50) => {
    const params = new URLSearchParams({ page: String(page), per_page: String(perPage) })
    if (identity) params.set('identity', identity)
    if (fromDate) params.set('from_date', fromDate)
    if (toDate) params.set('to_date', toDate)
    return request<AuditQueryListResponse>(`${BACKEND_URL}/api/v1/audit/queries?${params.toString()}`)
  },

  getAuditQueryDetail: (queryId: string) =>
    request<AuditQueryDetailResponse>(`${BACKEND_URL}/api/v1/audit/queries/${queryId}`),
}
