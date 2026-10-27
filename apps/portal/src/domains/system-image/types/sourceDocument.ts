export interface SourceDocumentPage {
  document: { document_revision_id: string; project_id: string; binding_id: string; source_revision_id: string; title: string; kind: string; parent_document_revision_id?: string }
  projection: { external_id: string | null; identity_status: string; references: string[]; gaps: string[];
    parent?: { external_id: string; payload_hash: string; field_indices: number[]; relation: 'source_contains' } }
  fields: { name: string; value: string; start_line: number; end_line: number; snippet_hash: string }[]
  total_fields: number
  next_offset: number | null
}
