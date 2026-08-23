export interface RunSummary {
  id: string
  status: string
  channel: 'web_runner'
  title: string
  summary: string
  started_at: string
}

export interface ExecutionEvidence {
  id: string
  project_id: string
  run_id: string
  us_id?: string | null
  case_ref?: string | null
  evidence_type: 'script' | 'trace' | 'log' | 'screenshot' | 'video' | 'report' | 'failure_artifact'
  storage_ref: string
  content_hash: string
  producer: 'agent' | 'web_runner' | 'system'
  captured_at: string
  redaction_status: 'not_required' | 'pending' | 'redacted'
  retention_policy: string
}

export interface FailureReport {
  id: string
  project_id: string
  run_id: string
  us_id?: string | null
  failure_kind: 'assertion' | 'selector' | 'environment' | 'data' | 'network' | 'timeout' | 'unknown'
  failure_fingerprint: string
  summary: string
  root_cause: string
  evidence_refs: string[]
  status: 'open' | 'under_review' | 'healing_proposed' | 'fallback_to_human' | 'resolved' | 'closed'
  healing_attempt_count: number
  fallback_to_human: boolean
  cooldown_until?: string | null
  created_at: string
}

export interface RunDetail extends RunSummary {
  timeline: string[]
  evidence: string[]
  failure_summary: string
  healing_status: string
}
