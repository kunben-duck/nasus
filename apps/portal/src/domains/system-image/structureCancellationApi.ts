import { request } from '../../shared/api/client'
import { platformApi } from '../platform/api'
import type { ToolInvocation } from '../platform/types/tool'

export interface StructureCancelPin {
  project_id: string
  original_invocation_id: string
  plan_id: string
  plan_digest: string
  target_baseline_id: string
}
export interface StructureCancelStatus {
  request: StructureCancelPin
  original_status: ToolInvocation['status']
  cancellation_requested: boolean
  candidate_committed: boolean
  can_cancel: boolean
}
export interface StructureCancelReceipt {
  request: StructureCancelPin
  outcome: 'cancel_requested' | 'cancelled' | 'already_requested' | 'already_committed' | 'already_terminal'
  original_status: ToolInvocation['status']
}
const states = ['pending', 'running', 'waiting_confirmation', 'waiting_approval', 'completed', 'failed', 'cancelled']
const terminal = (value: string) => ['completed', 'failed', 'cancelled'].includes(value)
const same = (value: StructureCancelPin | Record<string, unknown>, expected: StructureCancelPin) => !!value
  && Object.entries(expected).every(([key, item]) => (value as Record<string, unknown>)[key] === item)

export function validateStructureCancelStatus(value: StructureCancelStatus, pin: StructureCancelPin) {
  if (!value || !same(value.request, pin) || !states.includes(value.original_status)
      || [value.can_cancel, value.cancellation_requested, value.candidate_committed].some((item) => typeof item !== 'boolean')
      || (value.can_cancel && (terminal(value.original_status) || value.cancellation_requested || value.candidate_committed))) {
    throw new Error('Structural cancellation status mismatch')
  }
  return value
}
export function validateStructureCancelCommand(value: ToolInvocation, pin: StructureCancelPin, id?: string) {
  if (!value || !value.id || (id && value.id !== id) || value.tool_id !== 'system_image.build.structure.cancel'
      || value.id === pin.original_invocation_id || !same(value.input_payload, pin)
      || !['waiting_confirmation', 'completed'].includes(value.status)
      || (value.status === 'waiting_confirmation' && value.result != null)) {
    throw new Error('Structural cancellation command mismatch')
  }
  if (value.status === 'completed') {
    const receipt = value.result?.structure_cancel as StructureCancelReceipt | undefined
    if (value.result?.invocation_id !== value.id || value.result.status !== 'completed' || !receipt
        || !same(receipt.request, pin) || !states.includes(receipt.original_status)
        || !['cancel_requested', 'cancelled', 'already_requested', 'already_committed', 'already_terminal'].includes(receipt.outcome)
        || (receipt.outcome === 'cancelled' && receipt.original_status !== 'cancelled')
        || (receipt.outcome === 'already_terminal' && !terminal(receipt.original_status))
        || (['cancel_requested', 'already_requested'].includes(receipt.outcome) && receipt.original_status !== 'running')) {
      throw new Error('Structural cancellation acknowledgement mismatch')
    }
  }
  return value
}
export const structureCancellationApi = {
  async status(pin: StructureCancelPin, signal?: AbortSignal) {
    const root = `/v1/projects/${encodeURIComponent(pin.project_id)}/system-image/build-plans/${encodeURIComponent(pin.plan_id)}/structure-commands/${encodeURIComponent(pin.original_invocation_id)}/status`
    return validateStructureCancelStatus(await request<StructureCancelStatus>(`${root}?${new URLSearchParams({
      plan_digest: pin.plan_digest, target_baseline_id: pin.target_baseline_id })}`, { signal, cache: 'no-store' }), pin)
  },
  async cancel(view: StructureCancelStatus, key: string) {
    const current = await structureCancellationApi.status(view.request)
    if (!key || !view.can_cancel || !current.can_cancel || current.original_status !== view.original_status) {
      throw new Error('Structural command changed; reload before confirming stop')
    }
    const pin = view.request
    const pending = validateStructureCancelCommand(await platformApi.invokeTool({
      tool_id: 'system_image.build.structure.cancel', idempotency_key: key, input: { ...pin },
    }), pin)
    if (pending.input_payload.idempotency_key !== key) throw new Error('Structural cancellation request key mismatch')
    if (pending.status === 'completed') return pending
    const completed = validateStructureCancelCommand(await platformApi.confirmToolInvocation(pending.id), pin, pending.id)
    if (completed.status !== 'completed' || completed.input_payload.idempotency_key !== key) {
      throw new Error('Structural cancellation was not acknowledged')
    }
    return completed
  },
}
