class ExactJsonNumber {
  constructor(source) {
    const [, sign, integer, fraction = '', exponent = '0'] = source.match(/^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/)
    const digits = (integer + fraction).replace(/^0+/, '')
    const significant = digits.replace(/0+$/, '')
    this.decimal = significant ? `${sign}${significant}e${BigInt(exponent) - BigInt(fraction.length) + BigInt(digits.length - significant.length)}` : '0'
    Object.freeze(this)
  }
}

// Exact decimal identities prevent rounded response numbers from passing an oracle.
export function strictJson(text, { exactNumbers = false } = {}) {
  if (typeof text !== 'string') throw new Error('HTTP operands require JSON text.')
  const tokens = text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]/g) ?? []
  const stack = []
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index]
    if (token === '{' || token === '[') {
      stack.push(token === '{' ? new Set() : null)
      if (stack.length > 64) throw new Error('HTTP JSON nesting exceeds its bound.')
    } else if (token === '}' || token === ']') stack.pop()
    else if (token.startsWith('"') && tokens[index + 1] === ':' && stack.at(-1) instanceof Set) {
      let key
      try { key = JSON.parse(token) } catch { throw new Error('HTTP JSON key cannot be decoded.') }
      const keys = stack.at(-1)
      if (keys.has(key)) throw new Error('HTTP JSON contains duplicate keys.')
      keys.add(key)
    }
  }
  let value
  try {
    value = JSON.parse(text, (_key, item, context) => {
      if (typeof item !== 'number') return item
      if (typeof context?.source !== 'string' || context.source.length > 256) throw new Error('HTTP numeric operand exceeds its bound.')
      if (!Number.isFinite(item) || Number.isInteger(item) && !Number.isSafeInteger(item)) {
        throw new Error('HTTP JSON numeric value cannot be represented safely.')
      }
      if (!exactNumbers) return item
      if (typeof context?.source !== 'string') throw new Error('HTTP JSON requires exact numeric parsing support.')
      return new ExactJsonNumber(context.source)
    })
  } catch {
    throw new Error('HTTP operand is not strict safely representable JSON.')
  }
  return value
}

export function jsonPointer(value, pointer) {
  if (pointer === '') return value
  if (!pointer.startsWith('/') || /~(?![01])/.test(pointer)) throw new Error('Invalid HTTP JSON pointer.')
  let current = value
  for (const raw of pointer.slice(1).split('/')) {
    const key = raw.replaceAll('~1', '/').replaceAll('~0', '~')
    if (current === null || current instanceof ExactJsonNumber || typeof current !== 'object' || !Object.hasOwn(current, key)
      || Array.isArray(current) && !/^(0|[1-9][0-9]*)$/.test(key)) throw new Error('HTTP JSON pointer is absent.')
    current = current[key]
  }
  return current
}
