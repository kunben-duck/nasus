import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const cli = fileURLToPath(new URL('../src/owned-http-cli.mjs', import.meta.url))
function run(args, body) {
  return new Promise((resolve) => {
    const child = execFile(process.execPath, [cli, ...args], { timeout: 5000, maxBuffer: 65536 },
      (error, stdout, stderr) => resolve({ code: error?.code ?? 0, stdout, stderr }))
    child.stdin.on('error', () => {})
    child.stdin.end(body)
  })
}

for (const [label, args, body] of [
  ['missing opt-in', [], '{}'], ['extra Docker argument', ['--execute-owned-target-http', 'untrusted-id'], '{}'],
  ['malformed JSON', ['--execute-owned-target-http'], '{'], ['duplicate key', ['--execute-owned-target-http'], '{"schema":1,"schema":2}'],
  ['invalid UTF8', ['--execute-owned-target-http'], Buffer.from([255])],
  ['oversized stdin', ['--execute-owned-target-http'], Buffer.alloc(1024 * 1024 + 1)],
  ['noncanonical base64', ['--execute-owned-target-http'], JSON.stringify({ schema: 'nasus.owned-http-command.v1', inventory: {}, wire_body_base64: 'e30=\n' })],
  ['extra selector', ['--execute-owned-target-http'], JSON.stringify({ schema: 'nasus.owned-http-command.v1', inventory: {}, wire_body_base64: 'e30=', container_id: 'untrusted' })],
]) test(`private owned CLI rejects ${label} without exposing original bytes`, async () => {
  const result = await run(args, body)
  assert.equal(result.code, 2)
  assert.equal(result.stdout, '')
  assert.equal(result.stderr, 'Owned HTTP execution or original instance verification failed.\n')
})
