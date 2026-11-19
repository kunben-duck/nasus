import { isDeepStrictEqual } from 'node:util'

import { requestHash } from './execution-receipt.mjs'
import { strictJson } from './strict-json.mjs'

export const BROWSER_RECEIPT_SCHEMA = 'nasus.runner-browser-execution.v1'
export const BROWSER_DISPATCH_SCHEMA = 'nasus.browser-dispatch.v1'
export const BROWSER_ASSERTIONS = new Set(['assert_text', 'assert_visible', 'assert_url'])
export const BROWSER_MUTATIONS = new Set(['click', 'fill', 'press'])
const fields = {
  goto: ['url'], fill: ['selector', 'value'], click: ['selector'], press: ['selector', 'key'],
  assert_text: ['selector', 'value'], assert_visible: ['selector'], assert_url: ['value'], wait_for: ['selector'],
}
const pinFields = ['plan_digest', 'script_digest', 'case_digest', 'environment_digest', 'browser_digest']
const codes = new Set(['invalid_browser_job', 'private_dispatch_required', 'invalid_browser_dispatch',
  'private_evidence_unavailable', 'credential_unavailable', 'network_policy_rejected', 'redirect_rejected',
  'unknown_write', 'assertion_failed', 'browser_interrupted', 'browser_deadline', 'browser_execution_error'])

export class BrowserPolicyError extends Error {
  constructor(code) {
    super(codes.has(code) ? code : 'browser_execution_error')
    this.code = this.message
  }
}

export function requireBrowser(condition, code = 'invalid_browser_job') {
  if (!condition) throw new BrowserPolicyError(code)
}

export function browserFailureCode(error) {
  return error instanceof BrowserPolicyError && codes.has(error.code) ? error.code : 'browser_execution_error'
}

function object(value, required, optional = [], code = 'invalid_browser_job') {
  requireBrowser(value && typeof value === 'object' && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype
    && required.every((key) => Object.hasOwn(value, key))
    && Object.keys(value).every((key) => [...required, ...optional].includes(key)), code)
}

function text(value, { empty = false, max = 4096 } = {}) {
  requireBrowser(typeof value === 'string' && (empty || value.trim()) && value.length <= max
    && value.isWellFormed() && !/[\x00-\x1f\x7f]/.test(value))
  return value
}

function pins(value, code = 'invalid_browser_job') {
  object(value, pinFields, [], code)
  requireBrowser(pinFields.every((key) => typeof value[key] === 'string' && /^sha256:[a-f0-9]{64}$/.test(value[key])), code)
}

export function browserUrl(value, base) {
  text(value, { max: 2048 })
  requireBrowser(!value.includes('\\') && value === value.trim(), 'network_policy_rejected')
  let url
  try { url = new URL(value, base) } catch { throw new BrowserPolicyError('network_policy_rejected') }
  requireBrowser(['http:', 'https:'].includes(url.protocol) && !url.username && !url.password,
    'network_policy_rejected')
  return url
}

function origin(value) {
  const url = browserUrl(value)
  requireBrowser(url.pathname === '/' && !url.search && !url.hash, 'invalid_browser_dispatch')
  return url.origin
}

export function stepUrl(step, base) {
  return browserUrl(step.action === 'goto' ? step.url : step.value, base).href
}

function relativeUrl(value) {
  text(value, { max: 2048 })
  requireBrowser(value.startsWith('/') && !value.startsWith('//') && !value.includes('\\') && !value.includes('#'))
  requireBrowser(browserUrl(value, 'https://relative.invalid').origin === 'https://relative.invalid')
}

function stableSelector(value) {
  text(value, { max: 256 })
  // No selector engines, combinators, positional fallback, or broad tag/text matching.
  requireBrowser(/^(?:#[A-Za-z][A-Za-z0-9_-]*|(?:input|button|textarea|select)?\[(?:data-testid|data-test|name)="[A-Za-z][A-Za-z0-9_.-]*"\])$/.test(value)
    || /^(?:input|textarea)\[placeholder="[^"\\\[\]]{1,160}"\]$/.test(value)
    || /^(?:input\[type="(?:text|email|password|search|number|checkbox|radio|submit)"\]|button\[type="(?:submit|button|reset)"\])$/.test(value))
}

function freeze(value) {
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) freeze(item)
    Object.freeze(value)
  }
  return value
}

export function validateBrowserJob(raw, wireBody) {
  // Snapshot the wire, not a mutable caller object; bind dispatcher authority to these exact bytes.
  let command, wire
  try {
    wire = wireBody === undefined ? Buffer.from(JSON.stringify(raw)) : Buffer.from(wireBody)
    requireBrowser(wire.length <= 1024 * 1024)
    command = strictJson(new TextDecoder('utf-8', { fatal: true }).decode(wire))
    requireBrowser(isDeepStrictEqual(command, raw))
  } catch { throw new BrowserPolicyError('invalid_browser_job') }
  object(command, ['job_id', 'project_id', 'us_id', 'execution_kind', 'receipt_protocol', 'base_url',
    'timeout_ms', 'reviewed_pins', 'steps'])
  requireBrowser(command.execution_kind === 'browser' && command.receipt_protocol === BROWSER_RECEIPT_SCHEMA)
  for (const key of ['job_id', 'project_id', 'us_id']) {
    requireBrowser(typeof command[key] === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(command[key]))
  }
  const base = browserUrl(command.base_url)
  requireBrowser(base.pathname === '/' && !base.search && !base.hash)
  pins(command.reviewed_pins)
  requireBrowser(Number.isInteger(command.timeout_ms) && command.timeout_ms >= 1000 && command.timeout_ms <= 120000)
  requireBrowser(Array.isArray(command.steps) && command.steps.length >= 1 && command.steps.length <= 100)
  for (const step of command.steps) {
    requireBrowser(step && typeof step.action === 'string' && Object.hasOwn(fields, step.action))
    object(step, ['action', 'source_step_indices', ...fields[step.action]], ['phase', 'timeout_ms'])
    requireBrowser(Array.isArray(step.source_step_indices) && step.source_step_indices.length >= 1
      && step.source_step_indices.length <= 512 && new Set(step.source_step_indices).size === step.source_step_indices.length
      && step.source_step_indices.every((index) => Number.isInteger(index) && index >= 0 && index < 512))
    requireBrowser(step.phase === undefined || ['business', 'verification'].includes(step.phase))
    requireBrowser(step.phase !== 'verification' || !BROWSER_MUTATIONS.has(step.action))
    requireBrowser(step.timeout_ms === undefined || Number.isInteger(step.timeout_ms) && step.timeout_ms >= 100 && step.timeout_ms <= 30000)
    if (step.selector !== undefined) stableSelector(step.selector)
    if (step.value !== undefined) text(step.value, { empty: step.action === 'fill' })
    if (step.action === 'goto' || step.action === 'assert_url') relativeUrl(step.action === 'goto' ? step.url : step.value)
    if (step.action === 'press') requireBrowser(['Enter', 'Tab', 'Escape', 'Space', 'ArrowUp', 'ArrowDown'].includes(step.key))
  }
  freeze(command)
  return { jobId: command.job_id, projectId: command.project_id, usId: command.us_id,
    base, steps: command.steps, timeoutMs: command.timeout_ms, command, inputHash: requestHash(wire) }
}

export function validateBrowserDispatch(grant, job) {
  const code = 'invalid_browser_dispatch'
  object(grant, ['schema', 'request_hash', 'reviewed_pins', 'environment', 'step_permissions', 'evidence'],
    ['credential_bindings', 'resolve_credential'], code)
  requireBrowser(grant.schema === BROWSER_DISPATCH_SCHEMA && grant.request_hash === job.inputHash, code)
  pins(grant.reviewed_pins, code)
  requireBrowser(isDeepStrictEqual(grant.reviewed_pins, job.command.reviewed_pins), code)
  object(grant.environment, ['base_url', 'allowed_origins'], [], code)
  requireBrowser(origin(grant.environment.base_url) === job.base.origin, code)
  requireBrowser(Array.isArray(grant.environment.allowed_origins) && grant.environment.allowed_origins.length > 0
    && grant.environment.allowed_origins.length <= 16, code)
  const allowedOrigins = new Set(grant.environment.allowed_origins.map(origin))
  requireBrowser(allowedOrigins.has(job.base.origin), code)
  requireBrowser(Array.isArray(grant.step_permissions) && grant.step_permissions.length === job.steps.length, code)
  const permissions = grant.step_permissions.map((entry, index) => {
    const step = job.steps[index]
    const hasUrl = ['goto', 'assert_url'].includes(step.action)
    object(entry, ['step_index', 'read_only', 'requests', ...(step.selector === undefined ? [] : ['selector']),
      ...(hasUrl ? ['url'] : [])], [], code)
    requireBrowser(entry.step_index === index && typeof entry.read_only === 'boolean', code)
    requireBrowser(entry.selector === step.selector && (!hasUrl || entry.url === stepUrl(step, job.base)), code)
    requireBrowser(!BROWSER_MUTATIONS.has(step.action) || !entry.read_only, code)
    requireBrowser(!BROWSER_ASSERTIONS.has(step.action) && step.action !== 'wait_for' || entry.read_only, code)
    requireBrowser(step.phase !== 'verification' || entry.read_only, code)
    requireBrowser(Array.isArray(entry.requests) && entry.requests.length <= 256, code)
    const requests = entry.requests.map((request) => {
      object(request, ['method', 'url'], [], code)
      const url = browserUrl(request.url)
      requireBrowser(allowedOrigins.has(url.origin) && !url.hash && request.url === url.href, code)
      requireBrowser(['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'].includes(request.method), code)
      requireBrowser(!entry.read_only || ['GET', 'HEAD'].includes(request.method), code)
      return `${request.method} ${url.href}`
    })
    if (step.action === 'goto') requireBrowser(requests.includes(`GET ${entry.url}`), code)
    return { readOnly: entry.read_only, requests: new Set(requests) }
  })
  const credentials = new Map()
  requireBrowser(grant.credential_bindings === undefined || Array.isArray(grant.credential_bindings)
    && grant.credential_bindings.length <= 32, code)
  for (const binding of grant.credential_bindings ?? []) {
    object(binding, ['step_index', 'credential_ref'], [], code)
    const step = job.steps[binding.step_index]
    requireBrowser(Number.isInteger(binding.step_index) && step?.action === 'fill' && step.value === ''
      && !credentials.has(binding.step_index), code)
    requireBrowser(typeof binding.credential_ref === 'string' && binding.credential_ref.length > 0
      && binding.credential_ref.length <= 1024 && typeof grant.resolve_credential === 'function', code)
    credentials.set(binding.step_index, binding.credential_ref)
  }
  requireBrowser(grant.evidence && typeof grant.evidence.record === 'function' && typeof grant.evidence.seal === 'function',
    'private_evidence_unavailable')
  // Copy data away from the dispatcher; the two private ports are deliberately not serializable.
  return { allowedOrigins, permissions, credentials, resolveCredential: grant.resolve_credential,
    evidence: { record: grant.evidence.record.bind(grant.evidence), seal: grant.evidence.seal.bind(grant.evidence) } }
}
