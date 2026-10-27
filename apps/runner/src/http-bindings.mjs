import { requestHash } from './execution-receipt.mjs'
import { jsonPointer, strictJson } from './strict-json.mjs'

export const BINDING_ID = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/
export const RESOURCE_ID = /^[A-Za-z0-9_-]{1,128}$/

export function pathBindings(path) {
  const [pathname, ...query] = path.split('?')
  if (query.join('?').match(/[{}]/)) throw new Error('HTTP bindings cannot change query operands.')
  const ids = []
  for (const segment of pathname.split('/')) {
    const match = segment.match(/^\{\{([A-Za-z][A-Za-z0-9_-]{0,63})\}\}$/)
    if (match) ids.push(match[1])
    else if (/[{}]/.test(segment)) throw new Error('HTTP bindings require complete path segments.')
  }
  return [...new Set(ids)]
}

export function resolveHttpPath(path, bindings) {
  pathBindings(path)
  return path.replace(/\{\{([A-Za-z][A-Za-z0-9_-]{0,63})\}\}/g, (_token, id) => {
    const value = bindings.get(id)
    if (typeof value !== 'string' || !RESOURCE_ID.test(value)) throw new Error('HTTP resource binding is unavailable.')
    return value
  })
}

export function captureHttpBinding(step, response, stepIndex) {
  if (!response || response.status < 200 || response.status >= 300) throw new Error('HTTP binding requires a successful original response.')
  const value = jsonPointer(strictJson(new TextDecoder('utf-8', { fatal: true }).decode(response.body)), step.pointer)
  if (typeof value !== 'string' || !RESOURCE_ID.test(value)) throw new Error('HTTP binding requires a bounded resource identity.')
  return { binding_id: step.binding_id, step_index: stepIndex, request_id: step.request_id, pointer: step.pointer,
    response_hash: requestHash(response.body), value, value_hash: requestHash(JSON.stringify(value)) }
}
