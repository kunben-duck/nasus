import { isDeepStrictEqual } from 'node:util'
import { jsonPointer, strictJson } from './strict-json.mjs'

export function matchesHttpAssertion(step, response) {
  try {
    if (step.action === 'assert_status') return response.status === Number(step.value)
    if (step.action === 'assert_header') return response.headers[step.name.toLowerCase()] === step.value
    const text = new TextDecoder('utf-8', { fatal: true }).decode(response.body)
    if (step.action === 'assert_body') return text.includes(step.value)
    if (step.action === 'assert_json') return isDeepStrictEqual(
      jsonPointer(strictJson(text, { exactNumbers: true }), step.pointer),
      strictJson(step.value_json, { exactNumbers: true }))
  } catch { return false }
  return false
}
