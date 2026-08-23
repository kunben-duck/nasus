export interface RawAssetRecord {
  id: string
  project_id: string
  version_id?: string | null
  source_type: 'code' | 'us_doc' | 'test_asset'
  source_uri: string
  source_label?: string | null
  ingestion_status: 'pending' | 'ingesting' | 'indexed' | 'failed' | 'stale'
  content_hash: string
  content_ref?: string | null
  evidence_refs: string[]
  registered_at?: string | null
  registered_by_actor: 'user' | 'agent' | 'system'
  registered_from_invocation_id?: string | null
  credential_ref?: string | null
  permission_status: 'not_checked' | 'allowed' | 'denied'
  permission_checked_at?: string | null
  ingest_started_at?: string | null
  last_ingested_at?: string | null
  failure_reason?: string | null
  file_count: number
  byte_count: number
}

export interface RawAssetChunk {
  id: string
  project_id: string
  raw_asset_id: string
  source_type: 'code' | 'us_doc' | 'test_asset'
  chunk_kind: 'code' | 'requirement' | 'test' | 'summary'
  section_path: string
  content_ref: string
  content_hash: string
  token_estimate: number
  metadata: Record<string, unknown>
  embedding_record_id?: string | null
  created_at: string
}

export interface SourceUploadResult {
  source_type: 'us_doc' | 'test_asset'
  source_uri: string
  content_hash: string
  file_count: number
  byte_count: number
  evidence_refs: string[]
}
