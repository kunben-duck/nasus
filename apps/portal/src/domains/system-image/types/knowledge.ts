export interface KnowledgeCodeReference {
  entity_id: string
  entity_revision_id: string
  source_revision_id: string
}

export interface KnowledgeObject {
  id: string
  name: string
  type: string
  branch: string
  confidence: string
  relations: string[]
  evidence: string[]
  freshness: string
  code_reference?: KnowledgeCodeReference | null
  document_reference?: { document_revision_id: string; source_revision_id: string } | null
}

export interface ContextRelationship {
  id: string
  project_id: string
  baseline_id: string
  from_object_id: string
  relationship_type: 'implements' | 'depends_on' | 'covers' | 'validates' | 'impacts' | 'evidenced_by' | 'belongs_to'
  to_object_id: string
  confidence: number
  source_refs: string[]
}

export interface ContextObjectOverlay {
  id: string
  project_id: string
  baseline_id: string
  object_id: string
  field_path: string
  operation: 'add' | 'replace' | 'remove'
  value_ref?: string | null
  source_refs: string[]
  status: 'candidate' | 'merged' | 'rejected'
}
