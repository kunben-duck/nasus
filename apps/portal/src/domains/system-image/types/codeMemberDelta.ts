import type { ImageRevisionSummary } from './imageRevision'

export const codeMemberKinds = ['added_member', 'removed_member', 'revision_changed', 'projection_changed', 'unchanged'] as const
export type CodeMemberKind = typeof codeMemberKinds[number]
export interface CodeMemberPin {
  object_id: string; entity_revision_id: string; source_revision_id: string; object_hash: string; evidence_ids: string[]
}
export interface CodeMemberChange {
  binding_id: string; entity_id: string; kind: CodeMemberKind; before: CodeMemberPin | null; after: CodeMemberPin | null
}
export interface CodeMemberDeltaPage {
  project_id: string; before_image_revision_id: string; before_image_hash: string
  after_image_revision_id: string; after_image_hash: string; content_hash: string
  counts: Record<CodeMemberKind, number>; source_scope_changed: boolean
  kind: CodeMemberKind | null; items: CodeMemberChange[]; total: number; next_offset: number | null
  schema: 'nasus.code-member-delta.v1'; comparison_scope: 'registered_members_of_two_frozen_images'
  source_deletions_verified: false; rename_lineage_transferred: false; impact_complete: false
  approval_transferred: false; execution_authorized: false
}
export interface CodeMemberDeltaPair { before: ImageRevisionSummary; after: ImageRevisionSummary }
export interface CodeMemberDeltaSelection { kind: CodeMemberKind | null; offset: number }
