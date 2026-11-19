import { isDeepStrictEqual } from 'node:util'
import { jsonPointer, strictJson } from './strict-json.mjs'

export const HTTP_READBACK_SCHEMA = 'nasus.runner-http-execution.v4'
export const SNAPSHOT_ACTIONS = new Set(['capture_snapshot', 'assert_unchanged'])

export function readbackProjection(steps) {
  const snapshots = new Map()
  const requests = new Map()
  let mutationSeen = false
  return steps.map((step) => {
    const item = structuredClone(step)
    if (step?.action === 'request') {
      if (!['exercise', 'readback'].includes(step.phase) || step.phase === 'readback' && !['GET', 'HEAD'].includes(step.method)) {
        throw new Error('HTTP readback requires an explicitly reviewed GET or HEAD.')
      }
      delete item.phase
      requests.set(step.request_id, { method: step.method, phase: step.phase })
      mutationSeen ||= !['GET', 'HEAD', 'OPTIONS'].includes(step.method)
    } else if (SNAPSHOT_ACTIONS.has(step?.action)) {
      if (Object.keys(step).some((key) => !['action', 'request_id', 'pointer', 'snapshot_id', 'source_step_indices'].includes(key))
        || typeof step.snapshot_id !== 'string' || !/^[A-Za-z0-9_]{1,64}$/.test(step.snapshot_id)) throw new Error('Invalid HTTP snapshot operands.')
      if (step.action === 'capture_snapshot') {
        if (mutationSeen || requests.get(step.request_id)?.method !== 'GET') throw new Error('HTTP before-state snapshots require a GET before any mutation.')
        if (snapshots.has(step.snapshot_id) || snapshots.size >= 32) throw new Error('HTTP snapshots are bounded single assignments.')
        snapshots.set(step.snapshot_id, step.request_id)
      } else {
        if (!snapshots.has(step.snapshot_id)) throw new Error('HTTP unchanged assertion needs a preceding snapshot.')
        if (requests.get(step.request_id)?.method !== 'GET' || requests.get(step.request_id)?.phase !== 'readback'
          || step.request_id === snapshots.get(step.snapshot_id)) throw new Error('HTTP unchanged assertions require a subsequent GET.')
      }
      delete item.snapshot_id
      Object.assign(item, { action: 'assert_json', value_json: 'null' })
    }
    return item
  })
}

export function readbackStepAllowed(step, failed, replies) {
  if (!failed) return true
  if (step.action === 'request') return step.phase === 'readback' && ['GET', 'HEAD'].includes(step.method)
  return step.action.startsWith('assert_') && replies.has(step.request_id)
}

export function snapshotValue(step, response) {
  return jsonPointer(strictJson(new TextDecoder('utf-8', { fatal: true }).decode(response.body), { exactNumbers: true }), step.pointer)
}

export function matchesUnchanged(step, response, snapshots) {
  try {
    return response.status >= 200 && response.status < 300 && snapshots.has(step.snapshot_id)
      && isDeepStrictEqual(snapshots.get(step.snapshot_id), snapshotValue(step, response))
  } catch { return false }
}
