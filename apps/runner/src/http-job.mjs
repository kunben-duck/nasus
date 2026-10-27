import { HTTP_RECEIPT_SCHEMA, HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA } from './execution-receipt.mjs'
import { BINDING_ID, pathBindings } from './http-bindings.mjs'
import { verifyFixtureInput } from './http-fixture-input.mjs'
import { strictJson } from './strict-json.mjs'

export const HTTP_ASSERTIONS = new Set(['assert_status', 'assert_json', 'assert_header', 'assert_body'])
const fields = {
  request: ['request_id', 'method', 'path', 'headers_json', 'body_json'],
  assert_status: ['request_id', 'value'], assert_json: ['request_id', 'pointer', 'value_json'],
  assert_header: ['request_id', 'name', 'value'], assert_body: ['request_id', 'value'],
}
function text(value, { empty = false, length = 4096 } = {}) {
  if (typeof value !== 'string' || (!empty && !value.trim()) || value.length > length || !value.isWellFormed() || /[\x00-\x1f\x7f]/.test(value)) {
    throw new Error('HTTP job requires bounded explicit operands.')
  }
  return value
}
export function validateHttpJob(raw) {
  const withFixture = raw?.receipt_protocol === HTTP_FIXTURE_RECEIPT_SCHEMA
  const keys = ['job_id', 'project_id', 'us_id', 'base_url', 'steps', 'timeout_ms', 'metadata', 'receipt_protocol', 'execution_kind',
    ...(withFixture ? ['fixture_input'] : [])]
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).some((key) => !keys.includes(key))
    || raw.execution_kind !== 'http' || ![HTTP_RECEIPT_SCHEMA, HTTP_BINDING_RECEIPT_SCHEMA, HTTP_FIXTURE_RECEIPT_SCHEMA].includes(raw.receipt_protocol)) throw new Error('Unsupported HTTP execution protocol.')
  const base = new URL(text(raw.base_url, { length: 2048 }))
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash
    || base.pathname !== '/' || /\\/.test(raw.base_url)) throw new Error('HTTP target must be a credential-free origin.')
  if (!Array.isArray(raw.steps) || !raw.steps.length || raw.steps.length > 100) throw new Error('HTTP job needs 1..100 steps.')
  if (!Number.isInteger(raw.timeout_ms) || raw.timeout_ms < 1000 || raw.timeout_ms > 120000) throw new Error('HTTP deadline must be 1000..120000ms.')
  const fixture = withFixture ? verifyFixtureInput(raw) : null
  const seen = new Set(), bindings = new Set()
  const withBindings = withFixture || raw.receipt_protocol === HTTP_BINDING_RECEIPT_SCHEMA
  const steps = raw.steps.map((step) => {
    if (withFixture && step?.action === 'use_fixture_binding') {
      if (Object.keys(step).some((key) => !['action', 'binding_id', 'source_step_indices'].includes(key))
        || !BINDING_ID.test(step.binding_id) || !fixture.values.has(step.binding_id) || bindings.has(step.binding_id) || bindings.size >= 32
        || step.source_step_indices !== undefined && (!Array.isArray(step.source_step_indices) || !step.source_step_indices.length
          || step.source_step_indices.length > 512 || new Set(step.source_step_indices).size !== step.source_step_indices.length
          || step.source_step_indices.some((i) => !Number.isInteger(i) || i < 0 || i >= 512))) throw new Error('Invalid original fixture binding declaration.')
      bindings.add(step.binding_id)
      return structuredClone(step)
    }
    const required = withBindings && step?.action === 'capture_json' ? ['request_id', 'pointer', 'binding_id']
      : typeof step?.action === 'string' && Object.hasOwn(fields, step.action) ? fields[step.action] : undefined
    if (!required || !step || Object.keys(step).some((key) => !['action', 'source_step_indices', ...required].includes(key))
      || required.some((key) => !Object.hasOwn(step, key))) throw new Error('Unsupported HTTP action fields.')
    for (const key of required) text(step[key], { empty: key === 'pointer' })
    if (!/^[\p{L}\p{N}_-]{1,128}$/u.test(step.request_id)) throw new Error('Invalid HTTP request identity.')
    if (step.source_step_indices !== undefined && (!Array.isArray(step.source_step_indices) || !step.source_step_indices.length
      || step.source_step_indices.length > 512 || new Set(step.source_step_indices).size !== step.source_step_indices.length
      || step.source_step_indices.some((i) => !Number.isInteger(i) || i < 0 || i >= 512))) throw new Error('Invalid original HTTP step indices.')
    if (step.action === 'request') {
      if (seen.has(step.request_id) || !['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].includes(step.method)) throw new Error('HTTP requests require distinct identities and methods.')
      if (withBindings && pathBindings(step.path).some((id) => !bindings.has(id))) throw new Error('HTTP binding must precede its path use.')
      const target = new URL(step.path, base)
      if (!step.path.startsWith('/') || step.path.startsWith('//') || step.path.includes('\\') || target.hash || target.origin !== base.origin) throw new Error('HTTP path must stay on the exact target origin.')
      const headers = strictJson(step.headers_json), body = strictJson(step.body_json)
      if (!headers || typeof headers !== 'object' || Array.isArray(headers) || Object.keys(headers).length > 2
        || Object.entries(headers).some(([key, value]) => !['Accept', 'Content-Type'].includes(key)
          || typeof value !== 'string' || !value.trim() || value.length > 256 || /[\x00-\x1f\x7f]/.test(value))) throw new Error('HTTP headers cannot bind credentials or routing.')
      if (['GET', 'HEAD'].includes(step.method) && body !== null) throw new Error('GET and HEAD cannot carry fixture bodies.')
      seen.add(step.request_id)
    } else {
      if (!seen.has(step.request_id)) throw new Error('HTTP observation must refer to a preceding request.')
      if (step.action === 'capture_json') {
        if (!BINDING_ID.test(step.binding_id) || bindings.has(step.binding_id) || bindings.size >= 32) throw new Error('HTTP bindings require distinct bounded identities.')
        bindings.add(step.binding_id)
      }
      if (step.action === 'assert_status' && !/^[1-5][0-9]{2}$/.test(step.value)) throw new Error('Invalid HTTP status oracle.')
      if (step.action === 'assert_header' && !/^[A-Za-z0-9-]{1,128}$/.test(step.name)) throw new Error('Invalid HTTP response header name.')
      if (step.action === 'assert_json' || step.action === 'capture_json') {
        if (step.pointer && (!step.pointer.startsWith('/') || /~(?![01])/.test(step.pointer))) throw new Error('Invalid HTTP JSON pointer.')
        if (step.action === 'assert_json') strictJson(step.value_json)
      }
    }
    return structuredClone(step)
  })
  return { jobId: text(raw.job_id, { length: 128 }), projectId: text(raw.project_id, { length: 128 }),
    usId: text(raw.us_id, { length: 128 }), base, steps, timeoutMs: raw.timeout_ms, receiptProtocol: raw.receipt_protocol,
    ...(withFixture ? { fixture } : {}) }
}
