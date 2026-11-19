const assert = require('node:assert/strict')
const { fork } = require('node:child_process')
const { once } = require('node:events')
const { mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, truncateSync } = require('node:fs')
const { tmpdir } = require('node:os')
const { basename, join } = require('node:path')
const { test } = require('node:test')

const api = import('../../scripts/realworld-retained-budget.mjs')
const dollar = 1_000_000_000
const request = (operationId = 'op') => ({ operationId, route: 'bound-provider-request', requestDigest: 'a'.repeat(64) })

// Only the test authority issues claims. A caller-supplied object/amount is
// not proof. There is deliberately no production verifier or price fallback.
function authority(dir) {
  const proofs = new Map()
  const issue = (kind, ref, usdNanos, fields) => {
    const proof = Symbol()
    proofs.set(proof, { acceptanceId: basename(dir), currency: 'USD', kind, ref, usdNanos, ...fields })
    return proof
  }
  return {
    verify: (_kind, proof) => proofs.get(proof),
    opening: (paid = 0, fields) => issue('reconciled-opening', 'opening', paid, { unresolvedCalls: 0, ...fields }),
    quote: (req, max, fields) => issue('binding-ceiling', 'q:' + req.operationId, max, { ...req, ...fields }),
    bill: (req, paid, fields) => issue('final-charge', 'b:' + req.operationId, paid, { ...req, ...fields }),
  }
}

function directory(t) {
  const root = mkdtempSync(join(tmpdir(), 'retained-budget-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const dir = join(root, 'run-one')
  mkdirSync(dir, { mode: 0o700 })
  return dir
}

async function setup(t, paid = 0) {
  const dir = directory(t)
  const { initializeBudget, openBudget } = await api
  const auth = authority(dir)
  initializeBudget(dir, auth.opening(paid), auth.verify)
  const open = () => {
    const db = openBudget(dir, auth.verify)
    t.after(db.close)
    return db
  }
  return { dir, db: open(), open, ...auth }
}

if (process.argv[2] === 'budget-worker') {
  ;(async () => {
    const [, , , dir, op, action] = process.argv
    const a = authority(dir)
    const db = (await api).openBudget(dir, a.verify)
    process.send('ready')
    await once(process, 'message')
    const req = request(op)
    try {
      if (action === 'crash-in-transaction') {
        const { DatabaseSync } = require('node:sqlite')
        const raw = new DatabaseSync(join(dir, 'retained-budget-v1', 'ledger.sqlite'))
        raw.exec('BEGIN IMMEDIATE')
        raw.prepare("UPDATE calls SET paid=0, receiptRef='uncommitted' WHERE operationId=?").run(op)
        process.kill(process.pid, 'SIGKILL')
      } else if (action === 'settle') db.settle(op, a.bill(req, 123))
      else {
        const fresh = db.reserve(req, a.quote(req, 4 * dollar)).dispatch
        if (action === 'lose-ack') process.exit(fresh ? 21 : 22)
        if (!fresh) process.exit(2)
      }
      process.exit(0)
    } catch (e) {
      if (/budget blocked or insufficient/.test(e.message)) process.exit(3)
      throw e
    }
  })().catch(e => { console.error(e); process.exit(1) })
} else if (process.argv[2] === 'm2-plan') {
  // Invoked by the Python adapter test with the actual planner's synthetic
  // bytes. Issue independent test proofs; a manifest is never a proof.
  ;(async () => {
    const [, , , dir, requestDigest] = process.argv
    const a = authority(dir), { initializeBudget, openBudget } = await api
    const manifest = readFileSync(join(dir, 'unit-manifest')), wire = readFileSync(join(dir, 'unit-wire'))
    const actual = { method: 'POST', url: 'https://unit.invalid/v1/chat/completions', contentType: 'application/json',
      configId: 'saved-unit', configDigest: 'sha256:' + 'a'.repeat(64), body: wire }
    const m = JSON.parse(manifest), max = m.reservation.reserved_cost_nanos
    const req = { operationId: m.operationId, route: 'm2-exact-wire-v1', requestDigest }
    initializeBudget(dir, a.opening(5 * dollar - max), a.verify)
    const db = openBudget(dir, a.verify), quote = a.quote(req, max)
    try {
      assert.throws(() => db.reserve(req, quote), /Blocked/)
      assert.throws(() => db.reserveM2(manifest, actual, m.reservation), /evidence/)
      for (const drift of [{ body: Buffer.concat([wire, Buffer.from(' ')]) }, { configId: 'other' },
        { configDigest: 'sha256:' + 'f'.repeat(64) }, { url: 'https://elsewhere.invalid/' },
        { method: 'GET' }, { contentType: 'application/octet-stream' }])
        assert.throws(() => db.reserveM2(manifest, { ...actual, ...drift }, quote), /do not match/)
      assert.throws(() => db.reserveM2(manifest, actual, a.quote(req, max - 1)), /evidence/)
      const changed = Buffer.from(JSON.stringify({ ...m, binding: { ...m.binding, config_digest: 'sha256:' + 'f'.repeat(64) } }))
      assert.throws(() => db.reserveM2(changed, { ...actual, configDigest: 'sha256:' + 'f'.repeat(64) }, quote), /evidence/)
      assert.equal(db.lookup(req.operationId), null)
      assert.deepEqual(db.reserveM2(manifest, actual, quote), { dispatch: true })
      assert.deepEqual(db.reserveM2(manifest, actual, quote), { dispatch: false })
      assert.equal(db.status().availableUsdNanos, 0)
      assert.throws(() => db.settle(req.operationId, m.reservation), /evidence/)
      assert.equal(db.lookup(req.operationId).paid, null)
    } finally { db.close() }
  })().catch(e => { console.error(e); process.exitCode = 1 })
} else {
  async function race(t, dir, ops, action) {
    const children = ops.map(op => fork(__filename, ['budget-worker', dir, op, action], { silent: true }))
    t.after(() => children.forEach(p => { if (p.exitCode === null) p.kill() }))
    const exited = children.map(p => once(p, 'exit'))
    await Promise.all(children.map((p, i) => Promise.race([
      once(p, 'message').then(([msg]) => assert.equal(msg, 'ready')),
      exited[i].then(() => { throw new Error('Worker failed before reaching barrier') }),
    ])))
    children.forEach(p => p.send('go'))
    return (await Promise.all(exited)).map(([code, signal]) => signal ?? code).sort()
  }

  test('bootstrap requires a reconciled USD opening, even for zero; open never bootstraps', async t => {
    const dir = directory(t)
    const { initializeBudget, openBudget } = await api
    const a = authority(dir)
    assert.throws(() => openBudget(dir), /ENOENT/)
    for (const proof of [undefined, 0, {}, a.opening(0, { unresolvedCalls: 1 }), a.opening(NaN),
      a.opening(-1), a.opening(0, { currency: 'CNY' }), a.opening(0, { acceptanceId: 'other' }),
      a.opening(5 * dollar + 1)]) {
      assert.throws(() => initializeBudget(dir, proof, a.verify))
    }
    initializeBudget(dir, a.opening(50), a.verify)
    assert.throws(() => initializeBudget(dir, a.opening(), a.verify), /EEXIST/)
    const db = openBudget(dir)
    t.after(db.close)
    assert.equal(db.status().paidUsdNanos, 50)
    assert.throws(() => db.reserve(request(), a.quote(request(), 1)), /Verified evidence required/)
  })

  test('existing live routes and non-binding/mismatched evidence cannot reserve', async t => {
    const { db, quote, bill } = await setup(t)
    const req = request()
    for (const route of ['build-intake', 'm2-live', 'unknown']) {
      const live = { ...req, route }
      assert.throws(() => db.reserve(live, quote(live, 0)), /no binding pre-dispatch/)
    }
    for (const proof of [undefined, { usdNanos: 0 }, bill(req, 0), quote(req, 1, { ref: '' }),
      quote(req, 1, { acceptanceId: 'run-two' }), quote(req, 1, { requestDigest: 'b'.repeat(64) }),
      quote(req, 1, { currency: 'CNY' }), quote(req, 1, { operationId: 'other' }),
      ...[-1, 0.5, '1', null, Infinity, 2 ** 53].map(v => quote(req, v))]) {
      assert.throws(() => db.reserve(req, proof))
    }
    assert.equal(db.lookup(req.operationId), null)
  })

  test('integer cap includes prior spend and all unsettled calls; receipts can return change', async t => {
    const { db, quote, bill } = await setup(t, dollar)
    const a = request(), b = request('next')
    assert.deepEqual(db.reserve(a, quote(a, 4 * dollar)), { dispatch: true })
    assert.throws(() => db.reserve(b, quote(b, 1)), /insufficient/)
    assert.deepEqual(db.reserve(a, quote(a, 4 * dollar)), { dispatch: false })
    assert.throws(() => db.reserve(a, quote(a, 3)), /Conflicting reservation/)
    assert.throws(() => db.reserve(b, quote(b, 0, { ref: 'q:op' })), /UNIQUE/)
    const snapshot = db.settle('op', bill(a, dollar - 1))
    assert.deepEqual(snapshot, { paidUsdNanos: 2 * dollar - 1, reservedUsdNanos: 0,
      availableUsdNanos: 3 * dollar + 1, blocked: false })
    assert.deepEqual(db.settle('op', bill(a, dollar - 1)), snapshot)
    assert.deepEqual(db.reserve(a, quote(a, 4 * dollar)), { dispatch: false })
    assert.equal(db.reserve(b, quote(b, 3 * dollar + 1)).dispatch, true)
    assert.equal(db.status().availableUsdNanos, 0)
  })

  test('lost commit acknowledgement: recover hold, never resend or infer zero', async t => {
    const { dir, open, quote, bill } = await setup(t)
    assert.deepEqual(await race(t, dir, ['op'], 'lose-ack'), [21])
    const db = open(), req = request()
    assert.equal(db.lookup('op').paid, null)
    assert.equal(db.reserve(req, quote(req, 4 * dollar)).dispatch, false)
    for (const proof of [undefined, { mode: 'fallback', model_calls: 0 }, { input_tokens: 0, output_tokens: 0 },
      quote(req, 0), bill(req, 0, { operationId: 'not-op' }), bill(req, 1, { currency: 'EUR' })]) {
      assert.throws(() => db.settle('op', proof))
      assert.equal(db.status().reservedUsdNanos, 4 * dollar)
    }
    assert.throws(() => db.settle('missing', bill(req, 0)), /No reservation/)
    assert.equal(db.settle('op', bill(req, 0)).reservedUsdNanos, 0)
    assert.equal(open().lookup('op').receiptRef, 'b:op')
  })

  test('over-ceiling final bill is recorded in full and permanently fences new calls', async t => {
    const { db, open, quote, bill } = await setup(t)
    const a = request(), b = request('b')
    db.reserve(a, quote(a, 1))
    assert.deepEqual(db.settle('op', bill(a, 2)), { paidUsdNanos: 2, reservedUsdNanos: 0,
      availableUsdNanos: 0, blocked: true })
    assert.throws(() => open().reserve(b, quote(b, 0)), /blocked/)
  })

  test('one final receipt cannot pay for two operations; disputed hold survives reopen', async t => {
    const { db, open, quote, bill } = await setup(t)
    const a = request(), b = request('next')
    for (const r of [a, b]) db.reserve(r, quote(r, dollar))
    db.settle('op', bill(a, 100))
    assert.throws(() => db.settle('next', bill(b, 100, { ref: 'b:op' })), /ledger fenced/)
    assert.throws(() => db.settle('op', bill(a, 99)), /ledger fenced/)
    assert.deepEqual(open().status(), { paidUsdNanos: 100, reservedUsdNanos: dollar,
      availableUsdNanos: 0, blocked: true })
  })

  test('independent writers: last capacity has one winner', async t => {
    const { dir, db } = await setup(t)
    assert.deepEqual(await race(t, dir, ['one', 'two'], 'reserve'), [0, 3])
    assert.equal(db.status().reservedUsdNanos, 4 * dollar)
  })

  test('killed writer cannot leave an uncommitted refund or a stale lock', async t => {
    const { dir, db, open, quote, bill } = await setup(t)
    const req = request()
    db.reserve(req, quote(req, 5 * dollar))
    assert.deepEqual(await race(t, dir, ['op'], 'crash-in-transaction'), ['SIGKILL'])
    const recovered = open()
    assert.equal(recovered.status().reservedUsdNanos, 5 * dollar)
    assert.equal(recovered.lookup('op').receiptRef, null)
    assert.equal(recovered.settle('op', bill(req, 101)).paidUsdNanos, 101)
  })

  test('independent workers racing a replay: one send, then one final charge', async t => {
    const { dir, db } = await setup(t)
    assert.deepEqual(await race(t, dir, ['same', 'same'], 'reserve'), [0, 2])
    assert.deepEqual(await race(t, dir, ['same', 'same'], 'settle'), [0, 0])
    assert.equal(db.status().paidUsdNanos, 123)
    assert.equal(db.status().reservedUsdNanos, 0)
  })

  test('wrong acceptance, truncated or missing ledger never reset the budget', async t => {
    const dir = directory(t), other = join(dir, '..', 'run-two')
    const { initializeBudget, openBudget } = await api
    const a = authority(dir)
    initializeBudget(dir, a.opening(dollar), a.verify)
    renameSync(dir, other)
    assert.throws(() => openBudget(other), /mismatched opening/)
    renameSync(other, dir)
    const file = join(dir, 'retained-budget-v1', 'ledger.sqlite')
    truncateSync(file)
    assert.throws(() => openBudget(dir))
    rmSync(file)
    assert.throws(() => openBudget(dir), /ENOENT/)
    assert.throws(() => initializeBudget(dir, a.opening(), a.verify), /EEXIST/)
  })
}
