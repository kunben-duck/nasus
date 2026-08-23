export interface BaselineRecord {
  id: string
  project_id: string
  kind: 'official' | 'version_working' | 'version_shared'
  status: 'draft' | 'building' | 'ready' | 'stale' | 'pending_merge' | 'promoted'
  source_version_id?: string | null
  parent_baseline_id?: string | null
  fork_strategy: 'copy_on_write' | 'materialized_snapshot'
  object_count: number
  relationship_count: number
  metric_snapshot_count: number
  updated_at: string
}

export interface SystemImageBuildState {
  status:
    | 'source_required'
    | 'sources_registered'
    | 'ingesting'
    | 'indexed'
    | 'materialized'
    | 'ready'
    | 'partially_failed'
    | 'failed'
  stage_index: number
  stage_total: number
  label: string
  missing_source_types: string[]
  failed_source_ids: string[]
  next_recommended_tools: string[]
}
