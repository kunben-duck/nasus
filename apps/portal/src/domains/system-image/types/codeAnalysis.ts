export interface CodeSourceRevision {
  project_id: string
  source_id: string
  source_label: string
  binding_id: string
  source_revision_id: string
  external_revision: string
  acquired_at: string
  file_count: number
}

export interface CursorPage<T> { items: T[]; next_after_id: string | null }
export type ParserStatus = 'parsed' | 'unsupported' | 'failed' | 'not_analyzed'
export type StructureKind = 'module' | 'package' | 'service' | 'entrypoint' | 'route' | 'event_consumer'
  | 'database_access' | 'test_entrypoint' | 'configuration_boundary'
export type CodeEnumerationStatus = 'complete' | 'partial' | 'unknown' | 'not_run'
export type CodeIdentityStatus = 'exact' | 'ambiguous' | 'unresolved'
export type AnalysisSection = 'files' | 'facts' | 'entities' | 'relationships'
export interface CodeEntityObservation {
  provider_node_id: string; name: string; qualified_name: string; entity_kind: string
  relative_path: string; language: string; start_line: number; end_line: number
  identity_status: CodeIdentityStatus; location_precision: 'exact' | 'approximate'
}
export interface CodeRelationObservation {
  from_provider_node_id: string; to_provider_node_id: string
  relationship_kind: 'belongs_to' | 'depends_on' | 'calls' | 'exposes'; confidence: number
}
export interface CodeProviderProjection {
  schema: 'nasus.code-provider-projection.v1'
  scope: 'normalized_static_projection_not_business_or_runtime_acceptance'
  status: 'complete' | 'partial'
  providers: {
    capabilities: {
      provider: string
      provider_version: string
      operations: string[]
      languages: string[]
      language_coverage: 'declared' | 'unknown'
      limits: Record<string, number | null>
    }
    availability: 'observed' | 'unavailable' | 'not_run'
    entity_count: number
    relationship_count: number
    exact_locations: number
    approximate_locations: number
    entity_enumeration: CodeEnumerationStatus
    relationship_enumeration: CodeEnumerationStatus
    gaps: { reason: string; count: number | null }[]
  }[]
}
export interface CodeAnalysisSummary {
  analysis_id: string
  project_id: string
  binding_id: string
  source_revision_id: string
  report_hash: string
  recorded_at: string
  provider: string
  provider_version: string
  algorithm: string
  scope: string
  raw_inventory_available: boolean
  summary: Record<ParserStatus | 'file_count' | 'fact_count', number>
  projection?: CodeProviderProjection | null
  observation_summary?: {
    basis: 'received_projection_not_complete_native_graph'
    entity_count: number; relationship_count: number; identity_counts: Record<CodeIdentityStatus, number>
  } | null
}
export interface CodeFileAnalysis {
  relative_path: string
  language: string
  status: ParserStatus
  reason: string
  parser_version: string
  syntax_errors: number
  source_file_hash: string
  byte_count: number
  rules: string[]
}
export interface CodeStructureSpan { start_line: number; end_line: number; role: string; snippet_hash: string }
export interface CodeStructureFact {
  relative_path: string
  kind: StructureKind
  name: string
  start_line: number
  end_line: number
  rule: string
  status: 'observed' | 'unresolved' | 'path_hint'
  method: string | null
  route_path: string | null
  source_file_hash: string
  snippet_hash?: string
  supporting_spans: CodeStructureSpan[]
}
export interface CodeAnalysisPage {
  analysis: CodeAnalysisSummary
  section: AnalysisSection
  items: (CodeFileAnalysis | CodeStructureFact | CodeEntityObservation | CodeRelationObservation)[]
  total: number
  next_offset: number | null
}
export interface AnalysisPageSelection { section: AnalysisSection; offset: number; filter: string }
