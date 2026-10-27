import { expect, test } from '@playwright/test'
import { ApiRequestError } from '../../apps/portal/src/shared/api/errors'
import { isImagePageSizeError, readImagePair } from '../../apps/portal/src/domains/system-image/imageReadPair'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('joined reads start together and cannot publish only the object result', async () => {
  const object = deferred<string>(); const member = deferred<string>()
  const started: string[] = []
  let published = false
  const result = readImagePair(() => { started.push('objects'); return object.promise },
    () => { started.push('members'); return member.promise }, new AbortController().signal)
  const completed = result.then((value) => { published = true; return value })
  await Promise.resolve()
  expect(started).toEqual(['objects', 'members'])
  object.resolve('object-window')
  await Promise.resolve()
  expect(published).toBe(false)
  member.resolve('member-window')
  expect(await completed).toEqual(['object-window', 'member-window'])
})

for (const [status, code] of [[401, 'unauthorized'], [403, 'source_access_denied'], [409, 'source_access_changed'],
  [502, 'image_integrity_failed'], [503, 'image_artifact_unavailable'], [413, 'unrelated_size_error']] as const) {
  test(`a simultaneous page budget error cannot hide ${code}`, async () => {
    const large = new ApiRequestError('Smaller window required', 413, 'image_page_too_large')
    const failure = new ApiRequestError('Protected read failed', status, code)
    for (const first of [true, false]) {
      const objects = first ? large : failure; const members = first ? failure : large
      await expect(readImagePair(async () => { throw objects }, async () => { throw members },
        new AbortController().signal)).rejects.toBe(failure)
    }
    expect(isImagePageSizeError(failure)).toBe(false)
  })
}

test('live denial takes precedence over another protected read failure', async () => {
  const unavailable = new ApiRequestError('Unavailable', 503, 'image_artifact_unavailable')
  const denied = new ApiRequestError('Revoked', 403, 'source_access_denied')
  await expect(readImagePair(async () => { throw unavailable }, async () => { throw denied },
    new AbortController().signal)).rejects.toBe(denied)
})

test('a failed window drains its other read before the caller can shrink it', async () => {
  const member = deferred<string>()
  const large = new ApiRequestError('Smaller window required', 413, 'image_page_too_large')
  let settled = false
  const result = readImagePair(async () => { throw large }, () => member.promise, new AbortController().signal)
    .catch((error: unknown) => { settled = true; return error })
  await Promise.resolve(); await Promise.resolve()
  expect(settled).toBe(false)
  member.resolve('verified-member-window')
  expect(await result).toBe(large)
  expect(isImagePageSizeError(large)).toBe(true)
})

test('closing a read cannot publish a late pair and an already aborted read starts nothing', async () => {
  const controller = new AbortController()
  const object = deferred<string>(); const member = deferred<string>()
  let calls = 0
  const result = readImagePair(() => { calls++; return object.promise }, () => { calls++; return member.promise }, controller.signal)
  await Promise.resolve()
  object.resolve('objects')
  controller.abort(new Error('Closed inspector'))
  member.resolve('members')
  await expect(result).rejects.toThrow('Closed inspector')
  expect(calls).toBe(2)
  await expect(readImagePair(async () => { calls++; return 'objects' }, async () => { calls++; return 'members' },
    controller.signal)).rejects.toThrow('Closed inspector')
  expect(calls).toBe(2)
})

test('structural read errors are not mistaken for a transport size budget', async () => {
  const malformed = new Error('Frozen membership mismatch')
  const large = new ApiRequestError('Smaller window required', 413, 'image_page_too_large')
  await expect(readImagePair(async () => { throw large }, async () => { throw malformed },
    new AbortController().signal)).rejects.toBe(malformed)
  expect(isImagePageSizeError(malformed)).toBe(false)
})
