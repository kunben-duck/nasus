// A private, versioned resource handoff. It never grants target or oracle authority.
import { isDeepStrictEqual } from 'node:util'
import { createExecutionReceipt, HTTP_BINDING_RECEIPT_SCHEMA, requestHash } from './execution-receipt.mjs'
import { captureHttpBinding, pathBindings, resolveHttpPath } from './http-bindings.mjs'
import { HTTP_ASSERTIONS, validateHttpJob } from './http-job.mjs'
import { matchesHttpAssertion } from './http-oracles.mjs'
import { strictJson } from './strict-json.mjs'

export const FIXTURE_INPUT_SCHEMA = 'nasus.runner-http-fixture-input.v1'
const capsuleSchema = 'nasus.run-plan-case-fixture-captures.v1'
const capsuleIds = ['project_id', 'run_plan_id', 'case_id', 'setup_invocation_id', 'fixture_attempt_id', 'environment_id', 'environment_record_id']
const capsuleHashes = ['scope_digest', 'run_plan_artifact_hash', 'plan_digest', 'setup_history_digest', 'data_manifest_hash',
  'target_artifact_hash', 'inventory_hash', 'environment_record_artifact_hash', 'operator_policy_digest', 'setup_request_hash', 'setup_result_hash']
const captureFields = ['binding_id', 'step_index', 'request_id', 'pointer', 'response_hash', 'value', 'value_hash']
const fail = () => { throw new Error('Original fixture resource input could not be verified.') }
const exactKeys = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && isDeepStrictEqual(Object.keys(value).sort(), [...keys].sort())
const digest = (value) => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)
const identifier = (value) => typeof value === 'string' && value.trim() && [...value].length <= 128
  && value.isWellFormed() && !/[\x00-\x1f\x7f]/.test(value)
export const fixtureInputHash = (value) => requestHash(JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item))

function bytes(value, limit = 256 * 1024, empty = false) {
  if (typeof value !== 'string' || value.length > 4 * Math.ceil(limit / 3)) fail()
  const result = Buffer.from(value, 'base64')
  if (!empty && !result.length || result.length > limit || result.toString('base64') !== value) fail()
  return result
}
const object = (body) => strictJson(new TextDecoder('utf-8', { fatal: true }).decode(body))

function verifySetup(raw, wire, result, capsule) {
  if (raw.receipt_protocol !== HTTP_BINDING_RECEIPT_SCHEMA) fail()
  const source = validateHttpJob(raw), scope = raw.metadata?.fixture_scope
  const sourceRequests = new Map(), statusAssertions = new Set()
  for (const [index, step] of source.steps.entries()) {
    if (step.action === 'request') {
      if (!['GET', 'HEAD', 'POST'].includes(step.method)) fail()
      if (step.method === 'POST' && (source.steps[index + 1]?.action !== 'capture_json'
        || source.steps[index + 1].request_id !== step.request_id)) fail()
      sourceRequests.set(step.request_id, step)
    } else if (step.action === 'capture_json' && sourceRequests.get(step.request_id)?.method !== 'POST') fail()
    else if (step.action === 'assert_status') statusAssertions.add(step.request_id)
  }
  if (!isDeepStrictEqual([...sourceRequests.keys()].sort(), [...statusAssertions].sort())) fail()
  const scopeFields = ['project_id', 'attempt_id', 'case_id', 'parent_digest', 'data_manifest_hash', 'environment_id', 'artifact_hash', 'inventory_hash', 'timeout_ms']
  const pins = { project_id: capsule.project_id, attempt_id: capsule.fixture_attempt_id, case_id: capsule.case_id,
    parent_digest: capsule.plan_digest, data_manifest_hash: capsule.data_manifest_hash, environment_id: capsule.environment_id,
    artifact_hash: capsule.target_artifact_hash, inventory_hash: capsule.inventory_hash, timeout_ms: raw.timeout_ms }
  if (!exactKeys(raw.metadata, ['fixture_scope', 'fixture_phase', 'business_coverage_verified'])
    || raw.metadata.fixture_phase !== 'setup' || raw.metadata.business_coverage_verified !== false
    || !exactKeys(scope, scopeFields) || !isDeepStrictEqual(scope, pins)
    || source.projectId !== capsule.project_id || source.usId !== capsule.case_id
    || source.jobId !== 'http-fixture-' + fixtureInputHash([fixtureInputHash(scope), 'setup']).slice(7)
    || result?.runner_job_id !== source.jobId || result.status !== 'passed') fail()
  const receipt = result.execution_receipt
  const tracker = createExecutionReceipt(source, requestHash(wire), { schema: HTTP_BINDING_RECEIPT_SCHEMA, assertions: HTTP_ASSERTIONS })
  for (let index = 0; index < source.steps.length; index++) { tracker.start(index); tracker.observe(index, 'passed') }
  if (!exactKeys(receipt, [...Object.keys(tracker.finish('passed')), 'requests', 'bindings'])
    || !isDeepStrictEqual(Object.fromEntries(Object.keys(tracker.finish('passed')).map((key) => [key, receipt[key]])), tracker.finish('passed'))
    || !Array.isArray(receipt.requests) || !Array.isArray(receipt.bindings) || !Array.isArray(result.artifacts)) fail()
  const artifacts = new Map()
  for (const item of result.artifacts) {
    if (!exactKeys(item, ['artifact_type', 'name', 'media_type', 'content_base64']) || artifacts.has(item.name) || item.artifact_type !== 'report') fail()
    artifacts.set(item.name, item)
  }
  const readArtifact = (name, media) => {
    const item = artifacts.get(name)
    if (!item || item.media_type !== media) fail()
    artifacts.delete(name)
    return bytes(item.content_base64, 256 * 1024, media === 'application/octet-stream')
  }
  if (!isDeepStrictEqual(object(readArtifact('http-execution.json', 'application/json')), receipt)) fail()
  const replies = new Map(), bindings = new Map(), captures = []
  let requestIndex = 0
  for (const [index, step] of source.steps.entries()) {
    if (step.action === 'request') {
      const observed = receipt.requests[requestIndex++], path = resolveHttpPath(step.path, bindings)
      const body = readArtifact(`http-response-${step.request_id}.bin`, 'application/octet-stream')
      const metadata = readArtifact(`http-response-${step.request_id}.json`, 'application/json')
      if (!observed || !Number.isInteger(observed.response_status) || observed.response_status < 100 || observed.response_status > 599) fail()
      const expected = { request_id: step.request_id, step_index: index, method: step.method,
        input_hash: requestHash(JSON.stringify([step.method, path, step.headers_json, step.body_json])),
        response_status: observed.response_status, response_byte_count: body.length, response_hash: requestHash(body),
        declared_input_hash: requestHash(JSON.stringify([step.method, step.path, step.headers_json, step.body_json])), path, binding_ids: pathBindings(step.path) }
      if (!isDeepStrictEqual(observed, { ...expected, response_metadata_hash: requestHash(metadata) })) fail()
      const decoded = object(metadata), headers = decoded.headers
      if (!exactKeys(decoded, ['schema', 'headers', ...Object.keys(expected)]) || decoded.schema !== 'nasus.http-response.v2'
        || !headers || typeof headers !== 'object' || Array.isArray(headers)
        || Object.entries(headers).some(([key, value]) => !key || key.length > 128 || key !== key.toLowerCase()
          || !(typeof value === 'string' || Array.isArray(value) && value.every((item) => typeof item === 'string')))
        || !isDeepStrictEqual(decoded, { schema: 'nasus.http-response.v2', ...expected, headers })) fail()
      replies.set(step.request_id, { status: observed.response_status, headers, body })
    } else if (step.action === 'capture_json') {
      const capture = captureHttpBinding(step, replies.get(step.request_id), index)
      captures.push(capture); bindings.set(step.binding_id, capture.value)
    } else if (!matchesHttpAssertion(step, replies.get(step.request_id))) fail()
  }
  if (artifacts.size || requestIndex !== receipt.requests.length || !isDeepStrictEqual(captures, receipt.bindings)
    || !isDeepStrictEqual(captures, capsule.captures)) fail()
  return bindings
}

export function verifyFixtureInput(raw) {
  const input = raw.fixture_input, capsule = input?.capture_set
  if (!exactKeys(input, ['schema', 'capture_set', 'capture_set_digest', 'source_request_body_base64', 'source_result_body_base64'])
    || input.schema !== FIXTURE_INPUT_SCHEMA || !exactKeys(capsule, [...capsuleIds, ...capsuleHashes, 'schema', 'captures'])
    || capsule.schema !== capsuleSchema || capsuleIds.some((key) => !identifier(capsule[key]))
    || capsuleHashes.some((key) => !digest(capsule[key])) || input.capture_set_digest !== fixtureInputHash(capsule)
    || raw.project_id !== capsule.project_id || raw.us_id !== capsule.case_id
    || raw.metadata?.case_id !== capsule.case_id || raw.metadata.plan_digest !== capsule.plan_digest
    || raw.metadata.fixture_capture_digest !== input.capture_set_digest || raw.metadata.fixture_scope_digest !== capsule.scope_digest
    || !Array.isArray(capsule.captures) || capsule.captures.length < 1 || capsule.captures.length > 16
    || new Set(capsule.captures.map((item) => item?.request_id)).size !== capsule.captures.length
    || capsule.captures.some((item) => !exactKeys(item, captureFields))) fail()
  const request = bytes(input.source_request_body_base64), result = bytes(input.source_result_body_base64)
  if (requestHash(request) !== capsule.setup_request_hash || requestHash(result) !== capsule.setup_result_hash) fail()
  const source = object(request)
  if (source.base_url !== raw.base_url) fail()
  return { values: verifySetup(source, request, object(result), capsule), captureDigest: input.capture_set_digest,
    inputHash: fixtureInputHash(input), capsule: structuredClone(capsule) }
}
