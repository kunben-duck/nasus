import type { ContextRelationship, KnowledgeObject } from './knowledge'
import type { SemanticAssertion, SemanticReviewDecision } from './semanticReview'

export interface ImageRevisionSummary {
  image_revision_id: string
  project_id: string
  baseline_id: string
  manifest_id: string
  manifest_hash: string
  artifact_hash: string
  membership_hash: string
  policy_version: string
  recorded_at: string
  object_count: number
  code_member_count: number
  relationship_count: number
  status: 'candidate'
  publication: 'blocked_pending_revision_governance'
  parent_revision_id: string | null
  parent_artifact_hash: string | null
  assertion_count: number
}

export interface ImageObjectMember {
  object_id: string
  object_hash: string
  kind: 'code_entity' | 'source_document' | 'legacy_observation'
  document_revision_id?: string | null
  entity_id: string | null
  entity_revision_id: string | null
  source_revision_id: string | null
  evidence_ids: string[]
}

export interface ImageSourceMember {
  binding_id: string
  source_type: string
  source_revision_id: string
  status: 'captured'
}

export interface ImageSectionItems {
  objects: Omit<KnowledgeObject, 'freshness'>
  members: ImageObjectMember
  relationships: ContextRelationship
  source_members: ImageSourceMember
  assertion_members: ImageAssertionMember
  semantic_assertion_members: ImageSemanticMember
}
export interface ImageSemanticMember {
  assertion: Omit<SemanticAssertion, 'assertion_id' | 'assertion_digest' | 'claim_id' | 'can_accept'>
  decision: SemanticReviewDecision
}
export interface ImageAssertionMember {
  assertion_id: string; proposal_id: string; origin_image_revision_id: string
  assertion_digest: string; proposal_digest: string; evidence_digest: string
  decision_id: string; decision_digest: string; decision: 'accept' | 'reject' | 'defer'
  subject_object_id: string; subject_revision_id: string; object_id: string; object_revision_id: string
  subject_evidence_ids: string[]; object_evidence_ids: string[]; predicate: 'references'
}
export type ImageSection = keyof ImageSectionItems
export interface ImagePageSelection { section: ImageSection; offset: number }
export type ImageRevisionPage<S extends ImageSection = ImageSection> = {
  [K in S]: { revision: ImageRevisionSummary; section: K; items: ImageSectionItems[K][]; total: number; next_offset: number | null }
}[S]
export interface ImageRevisionList { items: ImageRevisionSummary[]; next_after_id: string | null }
