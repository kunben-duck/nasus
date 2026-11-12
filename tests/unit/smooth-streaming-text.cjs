const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

function mount(content, streaming, reducedMotion = false) {
  const slots = [], effects = [], frames = new Map()
  let cursor = 0, nextFrame = 0, time = 0, result
  const react = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = initial
      return [slots[index], (value) => { slots[index] = value }]
    },
    useRef(initial) {
      const index = cursor++
      return slots[index] ??= { current: initial }
    },
    useEffect(effect, deps) {
      const index = cursor++, previous = slots[index]
      if (previous && deps.every((value, i) => Object.is(value, previous.deps[i]))) return
      effects.push(() => {
        previous?.cleanup?.()
        slots[index] = { deps, cleanup: effect() }
      })
    },
  }
  const context = { exports: {}, require: () => react, matchMedia: () => ({ matches: reducedMotion }),
    requestAnimationFrame(callback) { frames.set(++nextFrame, callback); return nextFrame },
    cancelAnimationFrame(id) { frames.delete(id) },
  }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname,
    '../../apps/portal/src/shared/ui/useSmoothStreamingText.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  const render = () => {
    cursor = 0
    result = context.exports.useSmoothStreamingText(content, streaming)
    effects.splice(0).forEach((effect) => effect())
    return result
  }
  render()
  return {
    get value() { return result },
    update(text, active) { content = text; streaming = active; return render() },
    tick() {
      time += 24
      const pending = [...frames.values()]
      frames.clear()
      pending.forEach((callback) => callback(time))
      return render()
    },
    drain() {
      for (let i = 0; frames.size && i < 1000; i++) this.tick()
      assert.equal(frames.size, 0)
      return result
    },
    unmount() { slots.forEach((slot) => slot?.cleanup?.()); assert.equal(frames.size, 0) },
  }
}

for (const streaming of [false, true]) {
  test(`mounted ${streaming ? 'in-progress' : 'completed'} history is visible before the first frame`, () => {
    const text = 'Saved **Markdown** with a long persisted answer. '.repeat(20)
    const hook = mount(text, streaming)
    assert.equal(hook.value.visibleText, text)
    assert.equal(hook.value.animating, false)
    assert.equal(hook.tick().visibleText, text)
    hook.unmount()
  })
}

test('only new live text animates after restoring an unfinished reply', () => {
  const hook = mount('Saved prefix. ', true)
  const target = 'Saved prefix. Newly arriving tokens.'
  hook.update(target, true)
  assert.equal(hook.value.visibleText, 'Saved prefix. ')
  const frame = hook.tick()
  assert.ok(frame.visibleText.startsWith('Saved prefix. '))
  assert.ok(frame.visibleText.length > 'Saved prefix. '.length)
  assert.ok(frame.visibleText.length < target.length)
  assert.equal(frame.animating, true)
  hook.update(target, false)
  assert.equal(hook.drain().visibleText, target)
  assert.equal(hook.value.animating, false)
  hook.unmount()
})

test('fresh replies keep smooth typing and finish any buffered suffix', () => {
  const hook = mount('', true)
  const text = 'A fresh answer arriving as a chunk.'
  hook.update(text, true)
  assert.equal(hook.value.visibleText, '')
  assert.ok(hook.tick().visibleText.length < text.length)
  hook.update(text, false)
  assert.equal(hook.drain().visibleText, text)
  assert.equal(hook.value.animating, false)
  hook.unmount()
})

test('non-streaming updates and reduced motion skip typing', () => {
  for (const [streaming, reducedMotion] of [[false, false], [true, true]]) {
    const hook = mount('Saved', streaming, reducedMotion)
    hook.update('Saved with additional text', streaming)
    assert.equal(hook.tick().visibleText, 'Saved with additional text')
    assert.equal(hook.value.animating, false)
    hook.unmount()
  }
})
