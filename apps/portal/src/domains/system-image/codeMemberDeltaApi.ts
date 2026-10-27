import { request } from '../../shared/api/client'
import { ApiRequestError } from '../../shared/api/errors'
import { requireCodeDeltaPage, requireCodeDeltaSelection } from './codeMemberDeltaValidation'
import type { CodeMemberDeltaPage, CodeMemberDeltaPair, CodeMemberDeltaSelection } from './types/codeMemberDelta'

export async function readCodeMemberDelta(projectId: string, pair: CodeMemberDeltaPair,
  selection: CodeMemberDeltaSelection, signal: AbortSignal, expectedHash?: string) {
  requireCodeDeltaSelection(projectId, pair, selection)
  let limit = 20
  for (;;) {
    signal.throwIfAborted()
    const params = new URLSearchParams({ before_image_revision_id: pair.before.image_revision_id,
      before_image_hash: pair.before.artifact_hash, after_image_revision_id: pair.after.image_revision_id,
      after_image_hash: pair.after.artifact_hash, offset: String(selection.offset), limit: String(limit) })
    if (selection.kind !== null) params.set('kind', selection.kind)
    try {
      const page = await request<CodeMemberDeltaPage>(`/v1/projects/${encodeURIComponent(projectId)}/system-image/code-member-delta?${params}`,
        { signal, cache: 'no-store' })
      signal.throwIfAborted()
      return requireCodeDeltaPage(page, projectId, pair, selection, limit, expectedHash)
    } catch (error) {
      if (!(error instanceof ApiRequestError) || error.status !== 413 || error.code !== 'image_page_too_large' || limit === 1) throw error
      limit = Math.max(1, Math.floor(limit / 2))
    }
  }
}
