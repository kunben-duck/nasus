export interface ReleaseDecision {
  id: string
  project_id: string
  version_id: string
  us_id?: string | null
  status: 'ready' | 'conditional' | 'blocked' | 'needs_evidence'
  score: number
  rationale: string
  evidence_refs: string[]
  approval_ref?: string | null
  created_at: string
}

export interface ApprovalSummary {
  id: string
  title: string
  status: string
  summary: string
}

export interface ApprovalDetail extends ApprovalSummary {
  policy_reason: string
  conflict_fields: string[]
  recommended_resolution: string
  evidence: string[]
}

export interface ReleaseReadiness {
  version_id: string
  status: string
  score: number
  blockers: number
  approvals_open: number
  pending_merge: number
  execution_health: string
  summary: string
  blocker_items: string[]
  score_breakdown: Record<string, number>
  evidence_summary: Record<string, number>
}
