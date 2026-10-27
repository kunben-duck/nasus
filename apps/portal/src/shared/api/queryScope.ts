export function requireActiveQueryScope(canRead?: () => boolean, signal?: AbortSignal) {
  signal?.throwIfAborted()
  if (canRead?.() === false) throw new Error('The query scope is no longer active')
}
