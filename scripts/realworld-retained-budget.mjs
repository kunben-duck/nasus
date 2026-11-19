// Local, single-host ledger. One canonical private acceptance directory per run;
// never replace, copy back, or delete its ledger to recover missing evidence.
import { closeSync, fsyncSync, lstatSync, mkdirSync, openSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { createHash } from 'node:crypto'

export const LIMIT_USD_NANOS = 5_000_000_000
const id = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/.test(value)
const digest = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
const pinned = value => typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value)

function paths(directory) {
  const parent = resolve(directory)
  const acceptanceId = basename(parent)
  if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(acceptanceId) || !lstatSync(parent).isDirectory())
    throw new Error('Expected an existing retained acceptance directory')
  const dir = join(parent, 'retained-budget-v1')
  return { parent, acceptanceId, dir, file: join(dir, 'ledger.sqlite') }
}

// verify(kind, evidence) is a TRUSTED, synchronous adapter, not an identity
// function on user input. It authenticates issuer, coverage, and finality:
// reconciled-opening covers ALL pre-cutover charges, no outstanding attempts;
// binding-ceiling covers the exact immutable wire request and all billable
// dimensions, enforceable by the sender even on quote expiry; final-charge is
// a final USD bill (or authoritative usage with fully binding rates), not a
// token estimate. Return {kind, acceptanceId, currency:'USD', ref, usdNanos}
// plus {unresolvedCalls:0} for opening or {operationId, route, requestDigest}
// for either per-call claim. Persist opaque refs, not evidence.
function claim(verify, kind, evidence, expected) {
  if (evidence == null || typeof verify !== 'function') throw new Error('Verified evidence required: ' + kind)
  const c = verify(kind, evidence)
  if (c?.kind !== kind || c.currency !== 'USD' || !id(c.ref)
      || !Number.isSafeInteger(c.usdNanos) || c.usdNanos < 0
      || !Object.entries(expected).every(([k, v]) => c[k] === v))
    throw new Error('Invalid or mismatched evidence: ' + kind)
  return c
}

const schema = `
  CREATE TABLE opening (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1), acceptanceId TEXT NOT NULL,
    ref TEXT NOT NULL, paid INTEGER NOT NULL CHECK(paid BETWEEN 0 AND ${LIMIT_USD_NANOS}),
    disputed INTEGER NOT NULL DEFAULT 0 CHECK(disputed IN (0,1))
  ) STRICT;
  CREATE TABLE calls (
    operationId TEXT PRIMARY KEY, route TEXT NOT NULL, requestDigest TEXT NOT NULL,
    quoteRef TEXT NOT NULL UNIQUE, ceiling INTEGER NOT NULL CHECK(ceiling BETWEEN 0 AND ${LIMIT_USD_NANOS}),
    receiptRef TEXT UNIQUE, paid INTEGER CHECK(paid >= 0),
    CHECK ((paid IS NULL) = (receiptRef IS NULL))
  ) STRICT;`

function connect(file) {
  const db = new DatabaseSync(file)
  try {
    db.exec('PRAGMA busy_timeout=3000; PRAGMA fullfsync=ON; PRAGMA synchronous=EXTRA')
    return db
  } catch (e) { db.close(); throw e }
}

function write(db, fn) {
  db.exec('BEGIN IMMEDIATE')
  try {
    const result = fn()
    db.exec('COMMIT')
    return result
  } catch (e) {
    try { db.exec('ROLLBACK') } catch { db.close() }
    throw e
  }
}

// Explicit one-time bootstrap. A failed/interrupted bootstrap cannot silently
// initialize a fresh balance on the next open. Quiesce old writers at cutover.
export function initializeBudget(directory, evidence, verify) {
  const { parent, acceptanceId, dir, file } = paths(directory)
  const c = claim(verify, 'reconciled-opening', evidence, { acceptanceId, unresolvedCalls: 0 })
  if (c.usdNanos > LIMIT_USD_NANOS) throw new Error('Opening balance exceeds retained limit')
  mkdirSync(dir, { mode: 0o700 })
  const parentFd = openSync(parent, 'r')
  try { fsyncSync(parentFd) } finally { closeSync(parentFd) }
  closeSync(openSync(file, 'wx', 0o600))
  const db = connect(file)
  try {
    write(db, () => {
      db.exec(schema)
      db.prepare('INSERT INTO opening (singleton,acceptanceId,ref,paid) VALUES (1, ?, ?, ?)').run(acceptanceId, c.ref, c.usdNanos)
    })
  } finally { db.close() }
}

// Reserve only at the egress boundary, with a stable ID per logical attempt
// and digest covering endpoint/account/model, final payload and enforced limits.
// Only dispatch on a fresh {dispatch:true}. Disable retries/hidden extra calls.
// A timeout, crash or lost ACK needs NO write: the full hold already exists.
export function openBudget(directory, verify) {
  const { acceptanceId, dir, file } = paths(directory)
  if (!lstatSync(dir).isDirectory() || !lstatSync(file).isFile()) throw new Error('Invalid retained ledger')
  const db = connect(file)
  try {
    if (db.prepare('PRAGMA integrity_check').get().integrity_check !== 'ok') throw new Error('Damaged retained ledger')
    const opening = db.prepare('SELECT * FROM opening WHERE singleton=1').get()
    if (opening?.acceptanceId !== acceptanceId) throw new Error('Missing or mismatched opening balance')
    const byId = db.prepare('SELECT * FROM calls WHERE operationId=?')
    const totals = db.prepare(`SELECT
      (SELECT disputed FROM opening WHERE singleton=1) AS disputed, COALESCE(SUM(paid), 0) AS paid,
      COALESCE(SUM(CASE WHEN paid IS NULL THEN ceiling ELSE 0 END), 0) AS reserved,
      COALESCE(MAX(paid > ceiling), 0) AS breached FROM calls`)
    const status = () => {
      const s = totals.get()
      const paidUsdNanos = opening.paid + s.paid
      const used = paidUsdNanos + s.reserved
      if (!Number.isSafeInteger(used)) throw new Error('Unrepresentable ledger total')
      const blocked = Boolean(s.disputed || s.breached) || used > LIMIT_USD_NANOS
      return { paidUsdNanos, reservedUsdNanos: s.reserved, blocked,
        availableUsdNanos: blocked ? 0 : LIMIT_USD_NANOS - used }
    }
    function reserveVerified({ operationId, route, requestDigest }, evidence, amounts = {}) {
      if (!id(operationId) || !digest(requestDigest)) throw new Error('Invalid request binding')
      const c = claim(verify, 'binding-ceiling', evidence, { acceptanceId, operationId, route, requestDigest, ...amounts })
      return write(db, () => {
        const old = byId.get(operationId)
        if (old) {
          if (old.route !== route || old.requestDigest !== requestDigest || old.quoteRef !== c.ref || old.ceiling !== c.usdNanos)
            throw new Error('Conflicting reservation for operation')
          return { dispatch: false }
        }
        const s = status()
        if (s.blocked || c.usdNanos > s.availableUsdNanos) throw new Error('Retained budget blocked or insufficient')
        db.prepare('INSERT INTO calls (operationId,route,requestDigest,quoteRef,ceiling) VALUES (?,?,?,?,?)')
          .run(operationId, route, requestDigest, c.ref, c.usdNanos)
        return { dispatch: true }
      })
    }
    return {
      status, lookup: operationId => byId.get(operationId) ?? null, close: () => db.close(),
      reserve(req, evidence) {
        if (req.route !== 'bound-provider-request')
          throw new Error('Blocked: no binding pre-dispatch USD ceiling on this route')
        return reserveVerified(req, evidence)
      },
      // For a future exact-config sender, NOT the current M2 chat gateway.
      // Verify must independently authenticate the ceiling for the digest of
      // this entire manifest (including account/config, policy, and wire hash).
      // actual is a public projection of the FINAL outbound request and its
      // freshly resolved saved config, not data copied from the preview. Keep
      // the credential/headers in the sender. Re-enter at EVERY physical send.
      reserveM2(manifest, actual, evidence) {
        const wire = actual?.body
        if (!Buffer.isBuffer(manifest) || manifest.length > 32768 || !Buffer.isBuffer(wire) || wire.length > 4 * 1024 * 1024)
          throw new Error('Expected exact M2 manifest and wire bytes')
        let m, body
        try { m = JSON.parse(manifest); body = JSON.parse(wire) } catch { throw new Error('Invalid M2 JSON') }
        if (m?.schema !== 'nasus.m2-exact-wire.v1' || m.acceptanceId !== acceptanceId
            || m.method !== 'POST' || m.maxAttempts !== 1 || m.followRedirects !== false || m.fallback !== false
            || !pinned(m.policyDigest) || !pinned(m.binding?.config_digest) || !id(m.binding.config_id)
            || !['openai', 'openai_compatible'].includes(m.binding.provider)
            || m.contentType !== 'application/json' || m.url !== m.binding.base_url + '/chat/completions'
            || actual.method !== m.method || actual.url !== m.url || actual.contentType !== m.contentType
            || actual.configId !== m.binding.config_id || actual.configDigest !== m.binding.config_digest
            || body?.stream !== false || !body.model || body.model !== m.binding.model_name
            || !Number.isSafeInteger(body.max_tokens) || body.max_tokens < 1 || body.max_tokens > 16384
            || m.limits?.max_calls !== 1 || m.limits.currency !== 'USD' || body.max_tokens !== m.limits.max_output_tokens_per_call
            || m.reservation?.currency !== 'USD' || m.reservation.call_count !== 1
            || body.max_tokens !== m.reservation.max_output_tokens_per_call
            || wire.length !== m.bodyBytes || sha256(wire) !== m.bodySha256)
          throw new Error('M2 manifest or exact request bytes do not match')
        return reserveVerified({ operationId: m.operationId, route: 'm2-exact-wire-v1', requestDigest: sha256(manifest) },
          evidence, { usdNanos: m.reservation.reserved_cost_nanos })
      },
      settle(operationId, evidence) {
        const dispute = write(db, () => {
          const old = byId.get(operationId)
          if (!old) throw new Error('No reservation for operation')
          const expected = { acceptanceId, operationId: old.operationId, route: old.route, requestDigest: old.requestDigest }
          const c = claim(verify, 'final-charge', evidence, expected)
          if (c.ref === opening.ref || db.prepare('SELECT 1 FROM calls WHERE receiptRef=? AND operationId<>?').get(c.ref, operationId)
              || (old.paid !== null && (old.paid !== c.usdNanos || old.receiptRef !== c.ref))) {
            db.exec('UPDATE opening SET disputed=1 WHERE singleton=1')
            return true
          }
          if (old.paid === null)
            db.prepare('UPDATE calls SET paid=?, receiptRef=? WHERE operationId=?').run(c.usdNanos, c.ref, operationId)
        })
        if (dispute) throw new Error('Conflicting final charge; ledger fenced')
        // A broken upstream guarantee is a real charge, not a reason to
        // truncate the bill. Record it and fence ALL further dispatch.
        return status()
      },
    }
  } catch (e) { db.close(); throw e }
}
