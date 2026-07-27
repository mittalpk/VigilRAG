import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import EvaluationDashboard from './EvaluationDashboard'
import { apiClient } from './api/client'

vi.mock('./api/client', () => ({
  apiClient: {
    getEvaluationRuns: vi.fn(),
    getLatestEvaluationRun: vi.fn(),
  },
}))

describe('EvaluationDashboard Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders empty state gracefully when no runs exist', async () => {
    vi.mocked(apiClient.getEvaluationRuns).mockResolvedValue({ items: [], total: 0, page: 1, size: 10 })
    vi.mocked(apiClient.getLatestEvaluationRun).mockRejectedValue(new Error('HTTP 404'))

    render(<EvaluationDashboard />)

    await waitFor(() => {
      expect(screen.getByText(/No evaluation runs recorded/i)).toBeDefined()
    })
  })

  it('renders latest run summary and historical runs table', async () => {
    const mockRun = {
      id: 'run-1',
      pipeline_version: 'a1b2c3d',
      dataset_version: 'v1.0',
      total_cases: 20,
      faithfulness: 0.92,
      context_precision: 0.88,
      context_recall: 0.95,
      answer_relevancy: 0.90,
      passed_threshold: true,
      run_at: '2026-07-27T18:00:00Z',
    }

    vi.mocked(apiClient.getEvaluationRuns).mockResolvedValue({ items: [mockRun], total: 1, page: 1, size: 10 })
    vi.mocked(apiClient.getLatestEvaluationRun).mockResolvedValue(mockRun)

    render(<EvaluationDashboard />)

    await waitFor(() => {
      expect(screen.getByText(/✓ PASSED CI GATE/i)).toBeDefined()
      expect(screen.getByText('92.0%')).toBeDefined()
      expect(screen.getByText('a1b2c3d')).toBeDefined()
    })
  })
})
