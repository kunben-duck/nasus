import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { FrozenIndexStatus, IndexBuildRequest, IndexGeneration, IndexModelBinding, IndexPreview, IndexSelection, PublicationPin } from './types/frozenIndex'

const root = (project: string) => `/v1/projects/${encodeURIComponent(project)}/system-image/indexes`
const digest = (value: string) => /^sha256:[0-9a-f]{64}$/.test(value)
const bounded = (value: number, max: number) => Number.isInteger(value) && value > 0 && value <= max
function samePin(actual: PublicationPin, expected: PublicationPin) {
  return actual && Object.entries(expected).every(([key, value]) => actual[key as keyof PublicationPin] === value)
    && actual.quality_generation_authorized === false && actual.release_authorized === false
}
function sameRequest(actual: IndexBuildRequest, expected: IndexSelection) {
  return actual && Object.entries(expected).every(([key, value]) => actual[key as keyof IndexBuildRequest] === value)
    && digest(actual.input_digest) && digest(actual.model_config_digest)
}
function validModel(model: IndexModelBinding, input: IndexBuildRequest) {
  if (!model || model.config_id !== input.model_config_id || model.config_digest !== input.model_config_digest
      || !['openai', 'openai_compatible'].includes(model.provider) || !model.model_name?.trim()) return false
  const destination = new URL(model.base_url)
  return destination.protocol === 'https:' && !destination.username && !destination.password && !destination.search && !destination.hash
}
function requireGeneration(value: IndexGeneration, project: string, pin: PublicationPin) {
  if (!value || value.project_id !== project || !value.generation_id || !samePin(value.publication_pin, pin)
      || !sameRequest(value.request, { project_id: project, publication_id: pin.publication_id,
        model_config_id: value.model?.config_id, method_version: 'nasus.frozen-evidence-index.v1' })
      || !validModel(value.model, value.request) || !bounded(value.document_count, 4096) || !bounded(value.dimensions, 4096)
      || !digest(value.artifact_hash) || value.quality_generation_authorized !== false) throw new Error('Index generation could not be verified')
}

export const frozenIndexApi = {
  async status(project: string, pin: PublicationPin, signal: AbortSignal) {
    const value = await request<FrozenIndexStatus>(`${root(project)}?${new URLSearchParams({ publication_id: pin.publication_id })}`, { signal, cache: 'no-store' })
    if (value.project_id !== project || !samePin(value.publication_pin, pin) || typeof value.can_build !== 'boolean'
        || !['not_built', 'ready', 'rebuild_required'].includes(value.state) || value.quality_generation_authorized !== false
        || (value.state === 'not_built' ? value.generation !== null : !value.generation)) throw new Error('Index status scope mismatch')
    if (value.generation) requireGeneration(value.generation, project, pin)
    return value
  },
  async preview(project: string, pin: PublicationPin, model: string) {
    const selection: IndexSelection = { project_id: project, publication_id: pin.publication_id,
      model_config_id: model, method_version: 'nasus.frozen-evidence-index.v1' }
    const result = await platformApi.invokeTool({ tool_id: 'query.system_image.index.preview', idempotency_key: crypto.randomUUID(), input: { ...selection } })
    const preview = result.result?.index_preview as IndexPreview | undefined
    if (result.status !== 'completed' || result.tool_id !== 'query.system_image.index.preview' || !preview
        || !samePin(preview.publication_pin, pin) || !sameRequest(preview.request, selection) || !validModel(preview.model, preview.request)
        || !bounded(preview.document_count, 4096) || !bounded(preview.input_bytes, 4 * 1024 * 1024)
        || preview.max_model_calls !== Math.ceil(preview.document_count / 32) || preview.batch_size !== 32
        || preview.timeout_per_call_seconds !== 60 || preview.cost_estimate_available !== false
        || preview.rerank_egress_authorized !== false || preview.quality_generation_authorized !== false || !preview.query_egress
        || !Array.isArray(preview.source_binding_ids) || !preview.source_binding_ids.length
        || preview.source_binding_ids.some((id) => typeof id !== 'string' || !id)
        || new Set(preview.source_binding_ids).size !== preview.source_binding_ids.length) throw new Error('Index preview could not be verified')
    return { preview, attemptKey: crypto.randomUUID() }
  },
  async build(preview: IndexPreview, attemptKey: string) {
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.index.build', idempotency_key: attemptKey, input: { ...preview.request } })
    if (pending.status !== 'waiting_confirmation' || pending.tool_id !== 'system_image.index.build'
        || !sameRequest(pending.input_payload as unknown as IndexBuildRequest, preview.request)) throw new Error('Exact index confirmation required')
    const result = await platformApi.confirmToolInvocation(pending.id)
    if (result.id !== pending.id || result.tool_id !== 'system_image.index.build' || result.status !== 'completed'
        || !result.result?.object_refs.includes(`image_index:${result.id}`)) throw new Error('Index completion was not acknowledged')
    return result.id
  },
}
