import type { SourceRefreshAttempt } from './sourceRefreshApi'

type RecoveryStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
type RecoveryRead = { status: 'saved'; attempt: SourceRefreshAttempt }
  | { status: 'missing' | 'invalid' | 'unavailable' }
const schema = 'nasus.source-refresh-recovery.v1'
const prefix = 'nasus.source-refresh.v1:'
const id = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 128
  && value.trim() === value && !Array.from(value).some((character) => character.charCodeAt(0) < 32
    || (character.charCodeAt(0) >= 127 && character.charCodeAt(0) <= 159))
const keys = (value: object, required: string[], optional: string[] = []) =>
  required.every((key) => Object.hasOwn(value, key)) && Object.keys(value).every((key) => required.includes(key) || optional.includes(key))

export const isSourceRefreshCommandId = (value: unknown): value is string => id(value) && /^[A-Za-z0-9_-]+$/.test(value)

export function requireSourceRefreshAttempt(attempt: SourceRefreshAttempt): SourceRefreshAttempt {
  const input = attempt?.input
  if (!attempt || !keys(attempt, ['input', 'requestKey'], ['commandId']) || !id(attempt.requestKey)
      || (Object.hasOwn(attempt, 'commandId') && !isSourceRefreshCommandId(attempt.commandId)) || !input
      || !keys(input, ['project_id', 'source_ids', 'expected_manifest_id', 'expected_manifest_hash'])
      || !id(input.project_id) || !id(input.expected_manifest_id)
      || typeof input.expected_manifest_hash !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(input.expected_manifest_hash)
      || !Array.isArray(input.source_ids) || !input.source_ids.length || input.source_ids.length > 100
      || new Set(input.source_ids).size !== input.source_ids.length || input.source_ids.some((value) => !id(value))) {
    throw new Error('Invalid source refresh attempt')
  }
  return { input: { project_id: input.project_id, source_ids: [...input.source_ids],
    expected_manifest_id: input.expected_manifest_id, expected_manifest_hash: input.expected_manifest_hash },
    requestKey: attempt.requestKey, ...(attempt.commandId ? { commandId: attempt.commandId } : {}) }
}

export function createSourceRefreshRecovery(storage: () => RecoveryStorage) {
  function key(actor: string, project: string) {
    if (!id(actor) || !id(project)) throw new Error('Invalid source refresh recovery scope')
    return prefix + JSON.stringify([actor, project])
  }
  function read(actor: string, project: string): RecoveryRead {
    let storageKey: string, raw: string | null
    try { storageKey = key(actor, project) } catch { return { status: 'invalid' } }
    try { raw = storage().getItem(storageKey) } catch { return { status: 'unavailable' } }
    if (raw === null) return { status: 'missing' }
    try {
      if (raw.length > 32768) throw new Error('Oversized source refresh recovery record')
      const record = JSON.parse(raw)
      if (!record || !keys(record, ['schema', 'actor_id', 'input', 'requestKey'], ['commandId'])
          || record.schema !== schema || record.actor_id !== actor || record.input?.project_id !== project) {
        throw new Error('Source refresh recovery scope mismatch')
      }
      const attempt = requireSourceRefreshAttempt({ input: record.input, requestKey: record.requestKey,
        ...(Object.hasOwn(record, 'commandId') ? { commandId: record.commandId } : {}) })
      return { status: 'saved', attempt }
    } catch { return { status: 'invalid' } }
  }
  function write(actor: string, attempt: SourceRefreshAttempt) {
    const raw = JSON.stringify({ schema, actor_id: actor, ...attempt }), storageKey = key(actor, attempt.input.project_id)
    storage().setItem(storageKey, raw)
    if (storage().getItem(storageKey) !== raw) throw new Error('Source refresh recovery record was not saved')
  }
  function existing(actor: string, attempt: SourceRefreshAttempt) {
    const current = read(actor, attempt.input.project_id)
    if (current.status !== 'saved' || current.attempt.requestKey !== attempt.requestKey
        || JSON.stringify(current.attempt.input) !== JSON.stringify(attempt.input)) {
      throw new Error('Original source refresh recovery record could not be verified')
    }
    return current.attempt
  }
  return {
    read,
    save(actor: string, value: SourceRefreshAttempt) {
      const attempt = requireSourceRefreshAttempt(value)
      if (read(actor, attempt.input.project_id).status !== 'missing' || attempt.commandId) {
        throw new Error('An original source refresh record must not be replaced')
      }
      write(actor, attempt)
    },
    acknowledge(actor: string, value: SourceRefreshAttempt) {
      const attempt = requireSourceRefreshAttempt(value), prior = existing(actor, attempt)
      if (!attempt.commandId || (prior.commandId && prior.commandId !== attempt.commandId)) {
        throw new Error('Source refresh acknowledgement differs from its original record')
      }
      write(actor, attempt)
    },
    clear(actor: string, value: SourceRefreshAttempt) {
      const attempt = requireSourceRefreshAttempt(value), prior = existing(actor, attempt)
      if (prior.commandId !== attempt.commandId) throw new Error('Source refresh acknowledgement changed')
      const storageKey = key(actor, attempt.input.project_id)
      storage().removeItem(storageKey)
      if (storage().getItem(storageKey) !== null) throw new Error('Source refresh recovery record was not cleared')
    },
  }
}

export const sourceRefreshRecovery = createSourceRefreshRecovery(() => window.sessionStorage)
