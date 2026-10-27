import type { ProjectCard } from '../../platform/types'
import type { BaselineRecord, SystemImageBuildState } from './baseline'
import type { ContextObjectOverlay, ContextRelationship, KnowledgeObject } from './knowledge'
import type { QualityMetricSnapshot } from './metrics'
import type { RawAssetChunk, RawAssetRecord } from './source'

export interface SystemImageData {
  read_state?: {
    mode: 'legacy_draft' | 'working_draft' | 'published' | 'unpublished'
    version_id: string | null
    pin: { publication_id: string; baseline_id: string; image_revision_id: string; image_artifact_hash: string;
      manifest_id: string; manifest_hash: string; sequence: number; quality_generation_authorized: false; release_authorized: false } | null
  }
  source_manifest?: { manifest_id: string; project_id: string; content_hash: string } | null
  visibility?: { mode: 'project' | 'source_filtered'; withheld_sections: string[] }
  project: Pick<ProjectCard, 'id' | 'name' | 'code'> & {
    [Key in Exclude<keyof ProjectCard, 'id' | 'name' | 'code'>]: ProjectCard[Key] | null
  }
  summary: string
  build_state: SystemImageBuildState
  baselines: BaselineRecord[]
  sources: RawAssetRecord[]
  chunks: RawAssetChunk[]
  objects: KnowledgeObject[]
  relationships: ContextRelationship[]
  overlays: ContextObjectOverlay[]
  metric_snapshots: QualityMetricSnapshot[]
}
