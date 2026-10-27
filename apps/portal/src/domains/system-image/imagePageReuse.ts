export function imagePagePlaceholder<T>(previousData: T | undefined, previousKey: readonly unknown[] | undefined,
  currentKey: readonly unknown[]): T | undefined {
  if (!previousKey || previousKey.length !== 6 || currentKey.length !== 6
    || currentKey[0] !== 'system-image' || currentKey[2] !== 'image-page'
    || ![1, 3, 4].every((index) => typeof currentKey[index] === 'string' && currentKey[index] !== '')
    || !currentKey.slice(0, 5).every((value, index) => value === previousKey[index])) return undefined
  return previousData
}
