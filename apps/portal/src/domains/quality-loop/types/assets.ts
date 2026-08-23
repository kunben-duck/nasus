export interface AssetLane {
  id: string
  label: string
  status: string
  summary: string
  updated_at: string
}

export interface QualityAssetPart {
  id: string
  part_type:
    | 'scope_pack'
    | 'scenario_set'
    | 'verification_plan'
    | 'case_set'
    | 'automation_blueprint'
    | 'change_document'
    | 'release_assessment'
  status: 'draft' | 'ready_for_review' | 'approved' | 'completed' | 'blocked'
  title: string
  summary: string
  revision: number
  object_refs: string[]
  evidence_refs: string[]
  updated_at: string
}

export interface QualityAssetPack {
  id: string
  project_id: string
  version_id?: string | null
  us_id: string
  status: 'draft' | 'in_review' | 'approved' | 'completed' | 'pending_merge' | 'blocked'
  current_revision: number
  parts: QualityAssetPart[]
  source_refs: string[]
  evidence_refs: string[]
  updated_at: string
}

export interface QualityLoopState {
  status: 'no_us' | 'not_started' | 'in_progress' | 'ready_for_release' | 'blocked'
  stage_index: number
  stage_total: number
  label: string
  release_score: number
  next_recommended_tools: string[]
  blockers: string[]
}
