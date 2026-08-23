import type { ProjectCard } from '../../platform/types'
import type { BaselineRecord, SystemImageBuildState } from './baseline'
import type { ContextObjectOverlay, ContextRelationship, KnowledgeObject } from './knowledge'
import type { QualityMetricSnapshot } from './metrics'
import type { RawAssetChunk, RawAssetRecord } from './source'

export interface SystemImageData {
  project: ProjectCard
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
