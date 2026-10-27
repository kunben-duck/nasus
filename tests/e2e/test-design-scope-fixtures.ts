import { expect, type APIRequestContext } from '@playwright/test'
import { resolve } from 'node:path'
import { analysisApi, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions } from './image-revision-fixtures'

export interface ScopeFixtureOptions { requirementsPath?: string; constraintCount?: number }
export async function scopeFixture(request: APIRequestContext, source: string, options: ScopeFixtureOptions = {}) {
  const v = await captureAnalysis(request, source)
  const confirm = async (id: string) => {
    const response = await request.post(`${analysisApi}/v1/tool-invocations/${id}/confirm`, { headers: v.owner.headers })
    expect(response.ok()).toBeTruthy()
    const value = await response.json()
    expect(value.status).toBe('completed')
    return value
  }
  await v.invoke('system_image.sources.register', { source_specs: [
    { source_type: 'us_doc', source_uri: resolve(options.requirementsPath ?? 'tests/fixtures/system-image/exweb-requirements.md') },
    { source_type: 'test_asset', source_uri: resolve('tests/fixtures/system-image/exweb-test-cases.csv') },
  ] })
  await v.invoke('system_image.sources.ingest'); await v.invoke('system_image.context.materialize')
  const image = await (await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image`, { headers: v.owner.headers })).json()
  const candidate = (await frozenRevisions(request, v.projectId, v.owner.headers)).find((item) => item.manifest_id === image.source_manifest.manifest_id)!
  for (const object of image.objects.filter((item: { type: string }) => ['SourceAcceptanceCriterion', 'SourceBusinessRule'].includes(item.type))) {
    const rule = object.type === 'SourceBusinessRule'
    const params = { image_revision_id: candidate.image_revision_id, image_artifact_hash: candidate.artifact_hash, object_id: object.id }
    const response = await request.get(`${analysisApi}/v1/projects/${v.projectId}/quality/${rule ? 'business-rules' : 'acceptance-specifications'}`, { headers: v.owner.headers, params })
    expect(response.ok()).toBeTruthy()
    const authority = await response.json()
    const pending = await v.invoke(rule ? 'quality.business_rule.review' : 'quality.acceptance_specification.review', {
      ...params, basis_digest: authority.basis_digest, expected_previous_revision_id: null, policy_revision: authority.policy_revision,
      decision: 'approve', authority_basis: rule ? 'user_confirmed_business_rule' : 'user_confirmed_requirement',
      reason: 'Explicit browser companion fixture, not exweb maintainer approval',
      oracle: { preconditions: 'Isolated fixture environment', action: 'Send fixture chat request', observation: 'HTTP response',
        expected_result: rule ? 'Unauthenticated request is denied' : 'Content-Type includes text/event-stream' },
    }, 'waiting_confirmation')
    await confirm(pending.id)
  }
  const publications = `${analysisApi}/v1/projects/${v.projectId}/system-image/publications`
  const preview = await (await request.get(`${publications}/preview`, { headers: v.owner.headers, params: {
    image_revision_id: candidate.image_revision_id, image_artifact_hash: candidate.artifact_hash, target_baseline_id: candidate.baseline_id,
  } })).json()
  const review = await v.invoke('system_image.revisions.review_publication', { ...preview.target,
    expected_preview_digest: preview.preview_digest, expected_review_id: null, decision: 'approve', reason: 'Browser fixture publication' }, 'waiting_confirmation')
  const approval = await confirm(review.id)
  await v.invoke('baseline.promote', { ...preview.target, expected_preview_digest: preview.preview_digest, approval_id: approval.result.object_refs[0].split(':')[1] })
  const head = (await (await request.get(publications, { headers: v.owner.headers, params: { baseline_id: candidate.baseline_id } })).json()).head
  const packs = `${analysisApi}/v1/projects/${v.projectId}/system-image/context-packs`
  const contextPreview = await (await request.get(`${packs}/preview`, { headers: v.owner.headers, params: {
    image_revision_id: candidate.image_revision_id, image_artifact_hash: candidate.artifact_hash,
    publication_id: head.publication_id, policy_revision: 'nasus.test-design-context.v4',
  } })).json()
  expect(contextPreview.context.required_constraints).toHaveLength(options.constraintCount ?? 2)
  const compile = await v.invoke('system_image.context.compile', { ...contextPreview.request, expected_input_digest: contextPreview.input_digest }, 'waiting_confirmation')
  const saved = await confirm(compile.id)
  const contextId = saved.result.object_refs[0].split(':')[1]
  const read = await request.get(`${packs}/${contextId}`, { headers: v.owner.headers })
  expect(read.ok()).toBeTruthy()
  return { ...v, confirm, contextId, context: await read.json() }
}
