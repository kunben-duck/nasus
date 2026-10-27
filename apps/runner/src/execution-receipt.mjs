import crypto from 'node:crypto'

export const RECEIPT_SCHEMA = 'nasus.runner-execution.v1'
export const HTTP_RECEIPT_SCHEMA = 'nasus.runner-http-execution.v1'
export const HTTP_BINDING_RECEIPT_SCHEMA = 'nasus.runner-http-execution.v2'
export const HTTP_FIXTURE_RECEIPT_SCHEMA = 'nasus.runner-http-execution.v3'
const assertionActions = new Set(['assert_text', 'assert_visible', 'assert_url'])

export function requestHash(body) {
  return `sha256:${crypto.createHash('sha256').update(body).digest('hex')}`
}

export function createExecutionReceipt(job, inputHash, { schema = RECEIPT_SCHEMA, assertions = assertionActions } = {}) {
  const steps = job.steps.map((step, index) => ({
    step_index: index,
    action: step.action,
    kind: assertions.has(step.action) ? 'assertion' : 'action',
    status: 'not_executed',
  }))
  let active = null
  let sealed = false
  return {
    stopped() {
      return sealed
    },
    start(index) {
      if (!sealed) active = index
    },
    observe(index, status) {
      if (sealed || active !== index) return
      steps[index].status = status
      active = null
    },
    finish(status) {
      // Late browser failures after a deadline must not rewrite the receipt.
      if (!sealed && active !== null) steps[active].status = 'interrupted'
      sealed = true
      const assertions = steps.filter((step) => step.kind === 'assertion')
      return {
        schema,
        runner_job_id: job.jobId,
        project_id: job.projectId,
        us_id: job.usId,
        request_hash: inputHash,
        execution_status: status,
        step_count: steps.length,
        steps: structuredClone(steps),
        assertion_count: assertions.length,
        observed_assertion_count: assertions.filter((step) => ['passed', 'failed'].includes(step.status)).length,
        passed_assertion_count: assertions.filter((step) => step.status === 'passed').length,
        failed_assertion_count: assertions.filter((step) => step.status === 'failed').length,
        target_build_verified: false,
        business_coverage_verified: false,
      }
    },
  }
}
