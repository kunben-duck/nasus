import { platformApi } from '../platform/api'
import { createdIterationId, verifyIterationInput, verifyIterationInvocation } from './iterationCreation'
import type { IterationCreateAttempt } from './types/delivery'
import { versionDeliveryApi } from './versionDeliveryApi'
import { verifyCreatedIteration } from './versionDeliveryValidation'

export const iterationCreationApi = {
  async execute(attempt: IterationCreateAttempt, mode: 'submit' | 'inspect' | 'confirm', saved: (attempt: IterationCreateAttempt) => void) {
    verifyIterationInput(attempt.input)
    // A resumed confirmation first re-reads the original command. Never confirm an inferred replacement.
    const receipt = attempt.invocation_id
      ? await platformApi.getToolInvocation(attempt.invocation_id)
      : mode === 'submit' ? await platformApi.invokeTool({ tool_id: 'version.create', input: { ...attempt.input }, idempotency_key: attempt.idempotency_key })
        : null
    if (!receipt) throw new Error('Iteration receipt is not available')
    verifyIterationInvocation(receipt, attempt)
    const recorded = { ...attempt, invocation_id: receipt.id }
    saved(recorded)
    const result = mode === 'confirm' && receipt.status === 'waiting_confirmation'
      ? await platformApi.confirmToolInvocation(receipt.id) : receipt
    verifyIterationInvocation(result, recorded)
    if (result.status !== 'completed') return { receipt: result, delivery: null }
    const id = createdIterationId(result, recorded)
    const delivery = await versionDeliveryApi.read(attempt.input.project_id, id, new AbortController().signal)
    verifyCreatedIteration(delivery, attempt.input.image_binding)
    return { receipt: result, delivery }
  },
}
