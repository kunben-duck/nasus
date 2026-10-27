import type { ImageObjectMember, ImageRevisionPage } from './types/imageRevision'

export const imageSectionLabels = {
  objects: 'Objects', members: 'Frozen membership', relationships: 'Relations', source_members: 'Input sources', assertion_members: 'Frozen reviews',
  semantic_assertion_members: 'Frozen semantic reviews',
} as const
export interface ImageRowView {
  id: string
  title: string
  objectType?: string
  reviewStatus?: 'Accepted reference' | 'Rejected reference' | 'Deferred reference' | 'Accepted relation' | 'Rejected relation' | 'Deferred relation'
  kind: 'Code entity' | 'Source document projection' | 'Legacy observation' | 'Inferred relationship' | 'Captured input' | 'Reviewed reference snapshot' | 'Reviewed semantic snapshot'
  details: [string, string][]
  member?: ImageObjectMember
}

const sourceComponentLabels: Record<string, string> = {
  SourceAcceptanceCriterion: 'Acceptance criterion', SourceBusinessRule: 'Business rule',
}

export function imageRevisionRows(page: ImageRevisionPage, members?: ImageRevisionPage<'members'>): ImageRowView[] {
  switch (page.section) {
    case 'semantic_assertion_members': return page.items.map(({ assertion: a, decision: d }) => ({
      id: d.claim_id, title: a.predicate, kind: 'Reviewed semantic snapshot',
      reviewStatus: d.decision === 'accept' ? 'Accepted relation' : d.decision === 'reject' ? 'Rejected relation' : 'Deferred relation',
      details: [['Pinned review decision', d.decision], ['Decision ID', d.decision_id], ['Review reason', d.reason],
        ['Assertion ID', d.assertion_id], ['Assertion digest', d.assertion_digest], ['Evidence digest', d.evidence_digest],
        ['Evaluation ID', a.evaluation_id], ['From object', a.subject_object_id], ['To object', a.object_id]],
    }))
    case 'assertion_members': return page.items.map((item) => ({
      id: item.assertion_id, title: item.predicate, kind: 'Reviewed reference snapshot',
      reviewStatus: item.decision === 'accept' ? 'Accepted reference' : item.decision === 'reject' ? 'Rejected reference' : 'Deferred reference',
      details: [['Pinned review decision', item.decision], ['Decision ID', item.decision_id],
        ['Decision digest', item.decision_digest], ['Assertion ID', item.assertion_id], ['Assertion digest', item.assertion_digest],
        ['From object', item.subject_object_id], ['To object', item.object_id], ['Evidence digest', item.evidence_digest]],
    }))
    case 'objects': return page.items.map((item, index) => ({
      id: item.id, title: item.name, objectType: sourceComponentLabels[item.type] ?? item.type,
      kind: item.document_reference ? 'Source document projection' : item.code_reference ? 'Code entity' : 'Legacy observation',
      details: [['Object ID', item.id], ['Object type', item.type]], member: members?.items[index],
    }))
    case 'members': return page.items.map((item) => ({
      id: item.object_id, title: item.object_id,
      kind: item.kind === 'source_document' ? 'Source document projection' : item.kind === 'code_entity' ? 'Code entity' : 'Legacy observation',
      details: [['Object hash', item.object_hash], ['Entity ID', item.entity_id ?? ''],
        ['Entity revision', item.document_revision_id ?? item.entity_revision_id ?? ''], ['Pinned source revision', item.source_revision_id ?? '']], member: item,
    }))
    case 'relationships': return page.items.map((item) => ({
      id: item.id, title: item.relationship_type, kind: 'Inferred relationship',
      details: [['Relationship ID', item.id], ['From object', item.from_object_id], ['To object', item.to_object_id]],
    }))
    case 'source_members': return page.items.map((item) => ({
      id: item.binding_id, title: item.source_type, kind: 'Captured input',
      details: [['Source binding', item.binding_id], ['Pinned source revision', item.source_revision_id]],
    }))
  }
}

export function requireMatchingMembers(page: ImageRevisionPage<'objects'>, members: ImageRevisionPage) {
  if (members.section !== 'members' || members.revision.artifact_hash !== page.revision.artifact_hash
    || members.items.length !== page.items.length || members.total !== page.total || members.next_offset !== page.next_offset
    || members.items.some((item, index) => item.object_id !== page.items[index].id)) {
    throw new Error('Frozen object membership mismatch')
  }
  return members
}
