import { createExecutionReceipt, HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA, requestHash } from './execution-receipt.mjs'
import { captureHttpBinding, pathBindings, resolveHttpPath } from './http-bindings.mjs'
import { HTTP_ASSERTIONS, validateHttpJob } from './http-job.mjs'
import { pinHttpTarget, requestHttp } from './http-transport.mjs'
import { matchesHttpAssertion } from './http-oracles.mjs'

const TOTAL_RESPONSE_BYTES = 16 * 1024 * 1024
class HttpAssertionFailed extends Error {}
const artifact = (name, body, media = 'application/octet-stream') => ({ artifact_type: 'report', name,
  media_type: media, content_base64: body.toString('base64') })

export async function executeHttpJob(raw, { wireBody, signal, requestTransport = requestHttp } = {}) {
  const job = validateHttpJob(raw), startedAt = new Date().toISOString()
  const deadline = AbortSignal.timeout(job.timeoutMs), stop = signal ? AbortSignal.any([signal, deadline]) : deadline
  const tracker = createExecutionReceipt(job, requestHash(wireBody ?? Buffer.from(JSON.stringify(raw))),
    { schema: job.receiptProtocol, assertions: HTTP_ASSERTIONS })
  const replies = new Map(), requests = [], artifacts = [], timeline = []
  const bindings = new Map(), bindingObservations = [], fixtureObservations = []
  const withFixture = job.receiptProtocol === HTTP_FIXTURE_RECEIPT_SCHEMA
  const withBindings = withFixture || job.receiptProtocol === HTTP_BINDING_RECEIPT_SCHEMA
  let total = 0, status = 'error', failure = ''
  try {
    const pin = await pinHttpTarget(job.base, stop)
    for (let index = 0; index < job.steps.length; index++) {
      stop.throwIfAborted(); tracker.start(index)
      const step = job.steps[index]
      if (step.action === 'request') {
        const resolved = withBindings ? { ...step, path: resolveHttpPath(step.path, bindings) } : step
        const response = await requestTransport(resolved, job.base, pin, stop, TOTAL_RESPONSE_BYTES - total)
        stop.throwIfAborted(); total += response.body.length
        replies.set(step.request_id, response)
        const observed = { request_id: step.request_id, step_index: index, method: step.method,
          input_hash: requestHash(JSON.stringify([resolved.method, resolved.path, resolved.headers_json, resolved.body_json])),
          response_status: response.status, response_byte_count: response.body.length, response_hash: requestHash(response.body) }
        if (withBindings) Object.assign(observed, { declared_input_hash: requestHash(JSON.stringify([step.method, step.path, step.headers_json, step.body_json])),
          path: resolved.path, binding_ids: pathBindings(step.path) })
        const metadata = Buffer.from(JSON.stringify({ schema: withBindings ? 'nasus.http-response.v2' : 'nasus.http-response.v1', ...observed, headers: response.headers }))
        requests.push({ ...observed, response_metadata_hash: requestHash(metadata) })
        artifacts.push(artifact(`http-response-${step.request_id}.bin`, response.body))
        artifacts.push(artifact(`http-response-${step.request_id}.json`, metadata, 'application/json'))
      } else if (step.action === 'use_fixture_binding') {
        const value = job.fixture.values.get(step.binding_id)
        bindings.set(step.binding_id, value)
        fixtureObservations.push({ step_index: index, binding_id: step.binding_id,
          capture_digest: job.fixture.captureDigest, value_hash: requestHash(JSON.stringify(value)) })
      } else if (step.action === 'capture_json') {
        const observed = captureHttpBinding(step, replies.get(step.request_id), index)
        bindings.set(step.binding_id, observed.value)
        bindingObservations.push(observed)
      } else {
        const response = replies.get(step.request_id)
        const matches = matchesHttpAssertion(step, response)
        if (!matches) { tracker.observe(index, 'failed'); throw new HttpAssertionFailed('HTTP oracle did not match the actual response.') }
      }
      tracker.observe(index, 'passed'); timeline.push(`Step ${index + 1}/${job.steps.length}: ${step.action}`)
    }
    status = 'passed'
  } catch (error) {
    status = deadline.aborted ? 'timed_out' : error instanceof HttpAssertionFailed ? 'failed' : 'error'
    failure = status === 'timed_out' ? 'HTTP execution deadline reached.' : error instanceof HttpAssertionFailed
      ? error.message : 'HTTP execution was interrupted or rejected by its transport policy.'
  }
  const receipt = { ...tracker.finish(status), requests, ...(withBindings ? { bindings: bindingObservations } : {}),
    ...(withFixture ? { fixture_input_hash: job.fixture.inputHash, fixture_capture_digest: job.fixture.captureDigest,
      fixture_bindings: fixtureObservations } : {}) }
  artifacts.push(artifact('http-execution.json', Buffer.from(JSON.stringify(receipt)), 'application/json'))
  return { runner_job_id: job.jobId, status, summary: `HTTP execution completed with status ${status}.`, failure_summary: failure,
    started_at: startedAt, completed_at: new Date().toISOString(), timeline, artifacts,
    failure_fingerprint: status === 'passed' ? null : requestHash(JSON.stringify([job.jobId, status, failure])), execution_receipt: receipt }
}
