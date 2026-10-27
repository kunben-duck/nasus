import { platformApi } from '../platform/api'
import type { ToolInvocation } from '../platform/types/tool'

export interface StructureCommandPin {
  project_id: string
  plan_id: string
  plan_digest: string
  target_baseline_id: string
  idempotency_key?: string
}

export interface StructureBuildRequest extends StructureCommandPin {
  idempotency_key: string
}

export function validateStructureCommand(value: ToolInvocation, input: StructureCommandPin, id?: string) {
  if (!value || typeof value.id !== 'string' || !value.id || (id !== undefined && value.id !== id)
      || value.tool_id !== 'system_image.build.structure' || !value.input_payload
      || !['pending', 'running', 'waiting_confirmation', 'waiting_approval', 'completed', 'failed', 'cancelled'].includes(value.status)
      || Object.entries(input).some(([key, expected]) => value.input_payload[key] !== expected)
      || (value.result && (value.result.invocation_id !== value.id || value.result.status !== value.status))) {
    throw new Error('Structural command scope mismatch')
  }
  if (value.status === 'completed' && !value.result) throw new Error('Structural result is missing')
  return value
}

export const structureBuildApi = {
  async prepare(input: StructureBuildRequest) {
    if (typeof input.idempotency_key !== 'string' || !input.idempotency_key) throw new Error('Structural request key is missing')
    return validateStructureCommand(await platformApi.invokeTool({
      tool_id: 'system_image.build.structure', idempotency_key: input.idempotency_key, input: { ...input },
    }), input)
  },
  async confirm(input: StructureCommandPin, id: string) {
    return validateStructureCommand(await platformApi.confirmToolInvocation(id), input, id)
  },
  async read(input: StructureCommandPin, id: string, signal?: AbortSignal) {
    return validateStructureCommand(await platformApi.getToolInvocation(id, { signal }), input, id)
  },
}
