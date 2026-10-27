// Test-only protocol transport specimen. Never invoke a developer or target HTTP service.
import { executeHttpJob } from '../../runner/src/http-executor.mjs'
import { strictJson } from '../../runner/src/strict-json.mjs'

const parts = []
for await (const part of process.stdin) parts.push(part)
const wire = Buffer.concat(parts), visits = []
try {
  const raw = strictJson(new TextDecoder('utf-8', { fatal: true }).decode(wire))
  const result = await executeHttpJob(raw, { wireBody: wire, requestTransport: async (step) => {
    visits.push({ method: step.method, path: step.path })
    return { status: 200, headers: { 'content-type': 'application/json' }, body: Buffer.from('{"status":"ACTIVE"}') }
  } })
  process.stdout.write(JSON.stringify({ accepted: true, visits, result }))
} catch {
  process.stdout.write(JSON.stringify({ accepted: false, visits }))
}
