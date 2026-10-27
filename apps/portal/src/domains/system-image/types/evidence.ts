export interface SourceEvidence {
  evidence_id: string
  source_revision_id: string
  binding_id: string
  locator: {
    relative_path: string
    start_line: number
    end_line: number
    precision: 'exact' | 'approximate'
  }
  file_hash: string
  snippet_hash: string | null
  decoder_version: string
  captured_at: string
}

export interface SourceEvidencePage {
  evidence: SourceEvidence
  content: string
  start_line: number
  end_line: number
  next_start_line: number | null
  excerpt_hash: string
  integrity: 'verified'
}
