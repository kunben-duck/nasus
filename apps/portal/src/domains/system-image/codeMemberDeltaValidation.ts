import { codeMemberKinds, type CodeMemberDeltaPage, type CodeMemberDeltaPair, type CodeMemberDeltaSelection, type CodeMemberPin } from './types/codeMemberDelta'

const identifier = (value: unknown): value is string => typeof value === 'string' && value.length > 0
  && value.length <= 128 && !Array.from(value).some((character) => character.charCodeAt(0) < 32)
const hash = (value: unknown) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= 100000

export function requireCodeDeltaSelection(projectId: string, pair: CodeMemberDeltaPair, selection: CodeMemberDeltaSelection) {
  if (!identifier(projectId) || !pair?.before || !pair.after || !count(selection.offset)
    || (selection.kind !== null && !codeMemberKinds.includes(selection.kind))) throw new Error('Invalid code delta selection')
  for (const image of [pair.before, pair.after]) {
    if (image.project_id !== projectId || !identifier(image.image_revision_id) || !hash(image.artifact_hash)
      || !count(image.code_member_count)) throw new Error('Invalid fixed code delta image')
  }
  if (pair.before.image_revision_id === pair.after.image_revision_id && pair.before.artifact_hash !== pair.after.artifact_hash) {
    throw new Error('Conflicting immutable code delta images')
  }
}

function requirePin(pin: CodeMemberPin) {
  if (!pin || !identifier(pin.object_id) || !identifier(pin.entity_revision_id) || !identifier(pin.source_revision_id)
    || !hash(pin.object_hash) || !Array.isArray(pin.evidence_ids) || pin.evidence_ids.length > 100
    || pin.evidence_ids.some((value) => !identifier(value)) || new Set(pin.evidence_ids).size !== pin.evidence_ids.length) {
    throw new Error('Invalid registered code member pin')
  }
}

export function requireCodeDeltaPage(page: CodeMemberDeltaPage, projectId: string, pair: CodeMemberDeltaPair,
  selection: CodeMemberDeltaSelection, limit: number, expectedHash?: string) {
  requireCodeDeltaSelection(projectId, pair, selection)
  if (page.project_id !== projectId || page.before_image_revision_id !== pair.before.image_revision_id
    || page.before_image_hash !== pair.before.artifact_hash || page.after_image_revision_id !== pair.after.image_revision_id
    || page.after_image_hash !== pair.after.artifact_hash || !hash(page.content_hash)
    || (expectedHash !== undefined && page.content_hash !== expectedHash)
    || page.schema !== 'nasus.code-member-delta.v1' || page.comparison_scope !== 'registered_members_of_two_frozen_images'
    || page.kind !== selection.kind || typeof page.source_scope_changed !== 'boolean'
    || [page.source_deletions_verified, page.rename_lineage_transferred, page.impact_complete,
      page.approval_transferred, page.execution_authorized].some((value) => value !== false)) {
    throw new Error('Fixed code delta scope mismatch')
  }
  if (!page.counts || Object.keys(page.counts).length !== codeMemberKinds.length
    || codeMemberKinds.some((kind) => !count(page.counts[kind]))) throw new Error('Invalid complete code delta counts')
  const matched = page.counts.revision_changed + page.counts.projection_changed + page.counts.unchanged
  const total = selection.kind === null ? matched + page.counts.added_member + page.counts.removed_member : page.counts[selection.kind]
  if (matched + page.counts.removed_member !== pair.before.code_member_count
    || matched + page.counts.added_member !== pair.after.code_member_count || !count(page.total) || page.total !== total
    || !Array.isArray(page.items) || page.items.length !== Math.min(limit, total - selection.offset)
    || page.next_offset !== (selection.offset + page.items.length < total ? selection.offset + page.items.length : null)) {
    throw new Error('Code delta pagination mismatch')
  }
  let previous = ''
  for (const item of page.items) {
    if (!identifier(item.binding_id) || !identifier(item.entity_id) || !codeMemberKinds.includes(item.kind)
      || (selection.kind !== null && item.kind !== selection.kind)) throw new Error('Invalid code delta member')
    const identity = `${item.binding_id}\x00${item.entity_id}`
    if (previous && identity <= previous) throw new Error('Duplicate or unordered code delta identity')
    previous = identity
    if (item.before !== null) requirePin(item.before)
    if (item.after !== null) requirePin(item.after)
    if (item.before && item.after && item.before.entity_revision_id === item.after.entity_revision_id
      && item.before.source_revision_id !== item.after.source_revision_id) throw new Error('Code revision scope changed')
    const kind = item.before === null && item.after ? 'added_member' : item.after === null && item.before ? 'removed_member'
      : item.before && item.after ? item.before.entity_revision_id !== item.after.entity_revision_id ? 'revision_changed'
        : item.before.object_id !== item.after.object_id || item.before.object_hash !== item.after.object_hash
          || JSON.stringify(item.before.evidence_ids) !== JSON.stringify(item.after.evidence_ids) ? 'projection_changed' : 'unchanged' : null
    if (item.kind !== kind) throw new Error('Code delta classification mismatch')
  }
  return page
}
