// Validate duplicate keys before parsing; JSON.parse alone silently replaces them.
export function strictJson(source: string, limits: {
  maxContainerDepth?: number
  maxNumberLength?: number
  safeIntegerNumbers?: boolean
} = {}): unknown {
  let offset = 0
  const fail = (): never => { throw new Error('Invalid complete JSON observation') }
  const whitespace = () => { while (/[\t\n\r ]/.test(source[offset] ?? '\0')) offset++ }
  const string = (): string => {
    const start = offset++
    while (offset < source.length) {
      const char = source[offset++]
      if (char === '\\') offset++
      else if (char === '"') {
        try { return JSON.parse(source.slice(start, offset)) as string } catch { return fail() }
      }
    }
    return fail()
  }
  const value = (depth: number): void => {
    whitespace()
    if (depth > 128) fail()
    const char = source[offset]
    if (char === '"') { string(); return }
    if (char === '{' || char === '[') {
      if (limits.maxContainerDepth !== undefined && depth >= limits.maxContainerDepth) fail()
      const object = char === '{', end = object ? '}' : ']', keys = new Set<string>()
      offset++; whitespace()
      if (source[offset] === end) { offset++; return }
      while (offset < source.length) {
        whitespace()
        if (object) {
          if (source[offset] !== '"') fail()
          const key = string()
          if (keys.has(key)) fail()
          keys.add(key); whitespace()
          if (source[offset++] !== ':') fail()
        }
        value(depth + 1); whitespace()
        const next = source[offset++]
        if (next === end) return
        if (next !== ',') fail()
      }
      fail()
    }
    const token = /^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(source.slice(offset))?.[0]
    if (!token) fail()
    if (!['true', 'false', 'null'].includes(token!)) {
      const number = Number(token)
      if (!Number.isFinite(number) || limits.maxNumberLength !== undefined && token!.length > limits.maxNumberLength
        || limits.safeIntegerNumbers && Number.isInteger(number) && !Number.isSafeInteger(number)) fail()
    }
    offset += token!.length
  }
  value(0); whitespace()
  if (offset !== source.length) fail()
  try { return JSON.parse(source) as unknown } catch { return fail() }
}
