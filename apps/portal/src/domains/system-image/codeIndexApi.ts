import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ToolInvocation } from '../platform/types/tool'
import type { CodeIndexCancelReceipt, CodeIndexPage, CodeIndexPin, CodeIndexSelection, CodeIndexStatus, CodeIndexStatusView } from './types/codeIndex'

const root = (project: string) => `/v1/projects/${encodeURIComponent(project)}/system-image/code-indexes`
const digest = (value: unknown) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
const identity = (value: unknown) => typeof value === 'string' && value.length > 0 && value.length <= 128
const count = (value: unknown, max: number) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max
const same = (value: object, expected: object) => !!value && Object.entries(expected).every(([key, item]) => (value as Record<string, unknown>)[key] === item)

function requirePin(pin: CodeIndexPin, project: string, binding: string) {
  if (!pin || pin.project_id !== project || pin.binding_id !== binding
      || ![pin.generation_id, pin.project_id, pin.binding_id, pin.source_revision_id, pin.invocation_id].every(identity)
      || ![pin.content_hash, pin.source_manifest_hash, pin.snapshot_hash, pin.provider_fingerprint].every(digest)) {
    throw new Error('Code index pin could not be verified')
  }
}
function requireStatus(value: CodeIndexStatus, pin: CodeIndexPin) {
  if (!value || !same(value.pin, pin) || !count(value.epoch, Number.MAX_SAFE_INTEGER)
      || !['idle', 'preparing', 'ready', 'degraded', 'cancel_requested', 'cancelled', 'failed'].includes(value.state)
      || !['none', 'active', 'expired'].includes(value.worker_state)
      || ['preparing', 'ready', 'degraded', 'cancel_requested'].includes(value.state) !== (value.worker_state !== 'none')
      || !['pending', 'running', 'waiting_confirmation', 'waiting_approval', 'completed', 'failed', 'cancelled'].includes(value.invocation_status)
      || typeof value.observed_at !== 'string' || !Number.isFinite(Date.parse(value.observed_at))
      || value.scope !== 'durable_projection_metadata_not_native_cache_or_business_authority') throw new Error('Code index status scope mismatch')
  const protocol = value.protocol
  if (protocol !== null && (!protocol || !identity(protocol.provider)
      || !Array.isArray(protocol.gaps) || protocol.gaps.length > 16 || !protocol.gaps.every(identity)
      || new Set(protocol.gaps).size !== protocol.gaps.length)) throw new Error('Code index protocol could not be verified')
  if (protocol?.schema === 'nasus.code-provider-protocol.v1') {
    if (
      protocol.scope !== 'advertised_tool_contract_not_language_or_runtime_completeness'
      || ![protocol.provider, protocol.protocol_version, protocol.server_name, protocol.server_version, protocol.cli_version].every(identity)
      || !digest(protocol.tools_schema_hash) || !count(protocol.tool_count, 128) || protocol.tool_count === 0
      || !Array.isArray(protocol.verified_operations) || !protocol.verified_operations.length || protocol.verified_operations.length > 32
      || !protocol.verified_operations.every(identity) || new Set(protocol.verified_operations).size !== protocol.verified_operations.length) {
      throw new Error('Code index protocol could not be verified')
    }
  } else if (protocol?.schema === 'nasus.code-provider-sdk-contract.v1') {
    if (protocol.scope !== 'exercised_public_sdk_projection_not_language_or_runtime_completeness'
        || protocol.entry_point !== 'package_public_entry' || !identity(protocol.package_version)
        || typeof protocol.package_name !== 'string' || !/^(?:@[a-z0-9_.-]+\/)?[a-z0-9_.-]{1,128}$/.test(protocol.package_name)
        || !digest(protocol.contract_hash) || !digest(protocol.runtime_hash)
        || !Array.isArray(protocol.public_operations) || !protocol.public_operations.length || protocol.public_operations.length > 32
        || !protocol.public_operations.every((item) => typeof item === 'string' && /^[A-Za-z][A-Za-z0-9_.]{0,127}$/.test(item))
        || new Set(protocol.public_operations).size !== protocol.public_operations.length) throw new Error('Code index protocol could not be verified')
  } else if (protocol !== null) throw new Error('Code index protocol could not be verified')
  const projection = [value.projection_hash, value.provider_version, value.entity_count, value.relationship_count]
  if (projection.some((item) => item !== null) && (!protocol || !digest(value.projection_hash)
      || !identity(value.provider_version) || !count(value.entity_count, 100000000) || !count(value.relationship_count, 100000000))) {
    throw new Error('Code index projection is incomplete')
  }
  if (['ready', 'degraded'].includes(value.state) && !protocol) throw new Error('Prepared code index lacks its protocol')
}
function requireCancel(invocation: ToolInvocation, pin: CodeIndexPin, expectedId?: string) {
  const expected = { project_id: pin.project_id, generation_id: pin.generation_id, expected_generation_hash: pin.content_hash }
  if (!invocation || invocation.tool_id !== 'system_image.code_indexes.cancel' || !identity(invocation.id)
      || (expectedId && invocation.id !== expectedId) || !same(invocation.input_payload, expected)) throw new Error('Code index cancellation command mismatch')
  if (invocation.status !== 'completed' || invocation.result?.invocation_id !== invocation.id || invocation.result.status !== 'completed') {
    throw new Error('Code index cancellation was not acknowledged')
  }
  const receipt = invocation.result.code_index as CodeIndexCancelReceipt | undefined
  if (!receipt || !same(receipt.request, expected)
      || !['cancel_requested', 'cancelled', 'already_committed', 'already_terminal'].includes(receipt.outcome)) throw new Error('Code index cancellation receipt mismatch')
  requireStatus(receipt.status, pin)
  if (['cancel_requested', 'cancelled'].includes(receipt.outcome) && receipt.status.state !== receipt.outcome) throw new Error('Code index cancellation state mismatch')
  if ((receipt.outcome === 'already_committed' && receipt.status.invocation_status !== 'completed')
      || (receipt.outcome === 'already_terminal' && !['completed', 'failed', 'cancelled'].includes(receipt.status.invocation_status))) {
    throw new Error('Code index terminal acknowledgement mismatch')
  }
  return receipt
}

export const codeIndexApi = {
  async list(project: string, binding: string, after: string, signal: AbortSignal) {
    const expected: CodeIndexSelection = { project_id: project, binding_id: binding, after_id: after, limit: 10 }
    const params = new URLSearchParams({ binding_id: binding, after_id: after, limit: '10' })
    const page = await request<CodeIndexPage>(`${root(project)}?${params}`, { signal, cache: 'no-store' })
    if (!page || !same(page.request, expected) || page.scope !== 'source_authorized_generation_discovery_not_execution_authorization'
        || !Array.isArray(page.items) || page.items.length > 10) throw new Error('Code index discovery scope mismatch')
    let previous = after
    for (const pin of page.items) {
      requirePin(pin, project, binding)
      if (pin.generation_id <= previous) throw new Error('Code index discovery order mismatch')
      previous = pin.generation_id
    }
    if (page.next_after_id !== null && (page.items.length !== 10 || page.next_after_id !== previous)) throw new Error('Code index discovery cursor mismatch')
    return page
  },
  async status(pin: CodeIndexPin, signal?: AbortSignal) {
    requirePin(pin, pin.project_id, pin.binding_id)
    const view = await request<CodeIndexStatusView>(`${root(pin.project_id)}/${encodeURIComponent(pin.generation_id)}`, { signal, cache: 'no-store' })
    if (!view || !same(view.request, { project_id: pin.project_id, generation_id: pin.generation_id })
        || typeof view.can_cancel !== 'boolean') throw new Error('Code index observation scope mismatch')
    requireStatus(view.status, pin)
    if (view.can_cancel && (view.status.invocation_status !== 'running' || ['cancel_requested', 'cancelled', 'failed'].includes(view.status.state))) {
      throw new Error('Terminal code index cannot authorize cancellation')
    }
    return view
  },
  async cancel(view: CodeIndexStatusView, attemptKey: string) {
    const pin = view.status.pin
    const current = await codeIndexApi.status(pin)
    if (!view.can_cancel || !current.can_cancel || current.status.epoch !== view.status.epoch) throw new Error('Code index changed; reload before confirming')
    const expected = { project_id: pin.project_id, generation_id: pin.generation_id, expected_generation_hash: pin.content_hash }
    const pending = await platformApi.invokeTool({ tool_id: 'system_image.code_indexes.cancel', idempotency_key: attemptKey, input: expected })
    if (pending.status === 'completed') return requireCancel(pending, pin)
    if (pending.status !== 'waiting_confirmation' || pending.tool_id !== 'system_image.code_indexes.cancel'
        || !identity(pending.id) || !same(pending.input_payload, expected)) throw new Error('Exact code index confirmation required')
    return requireCancel(await platformApi.confirmToolInvocation(pending.id), pin, pending.id)
  },
}
