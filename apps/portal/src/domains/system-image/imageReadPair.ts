import { ApiRequestError } from '../../shared/api/errors'

export function isImagePageSizeError(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError && error.status === 413 && error.code === 'image_page_too_large'
}

export async function readImagePair<T, U>(objects: () => Promise<T>, members: () => Promise<U>, signal: AbortSignal) {
  signal.throwIfAborted()
  // Drain both reads before reducing a window; never overlap retry generations.
  const [objectReply, memberReply] = await Promise.allSettled([
    Promise.resolve().then(objects), Promise.resolve().then(members),
  ])
  signal.throwIfAborted()
  const failures: unknown[] = []
  if (objectReply.status === 'rejected') failures.push(objectReply.reason)
  if (memberReply.status === 'rejected') failures.push(memberReply.reason)
  if (failures.length) {
    const denied = failures.find((error) => error instanceof ApiRequestError
      && (error.status === 401 || error.status === 403 || error.code === 'source_access_changed'))
    throw denied ?? failures.find((error) => !isImagePageSizeError(error)) ?? failures[0]
  }
  if (objectReply.status !== 'fulfilled' || memberReply.status !== 'fulfilled') throw new Error('Incomplete frozen image read')
  return [objectReply.value, memberReply.value] as const
}
