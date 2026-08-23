export interface QualityMetricSnapshot {
  id: string
  project_id: string
  baseline_id: string
  version_id?: string | null
  us_id?: string | null
  task_id?: string | null
  metric_group: 'code_quality' | 'us_completion_quality' | 'test_quality' | 'release_readiness'
  metrics: Record<string, unknown>
  evidence_refs: string[]
  captured_at: string
}
