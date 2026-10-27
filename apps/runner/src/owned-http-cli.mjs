// Private worker entry point. This transport is not selectable by /v1/jobs.
import { ownedDockerHttpTransport } from './docker-http-transport.mjs'
import { executeHttpJob } from './http-executor.mjs'
import { validateHttpJob } from './http-job.mjs'
import { strictJson } from './strict-json.mjs'
import { fixtureInputHash } from './http-fixture-input.mjs'

try {
  if (process.argv.length !== 3 || process.argv[2] !== '--execute-owned-target-http') throw new Error('Private worker command required.')
  const chunks = []
  let size = 0
  for await (const chunk of process.stdin) {
    size += chunk.length
    if (size > 1024 * 1024) throw new Error('Complete command exceeds its bound.')
    chunks.push(chunk)
  }
  const input = strictJson(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)))
  if (input?.schema !== 'nasus.owned-http-command.v1' || Object.keys(input).sort().join(',') !== 'inventory,schema,wire_body_base64'
    || typeof input.wire_body_base64 !== 'string') throw new Error('Invalid private worker command.')
  const wire = Buffer.from(input.wire_body_base64, 'base64')
  if (!wire.length || wire.length > 512 * 1024 || wire.toString('base64') !== input.wire_body_base64) throw new Error('Invalid original job bytes.')
  const raw = strictJson(new TextDecoder('utf-8', { fatal: true }).decode(wire))
  const job = validateHttpJob(raw), inventory = input.inventory
  if (raw.project_id !== inventory?.project_id || job.base.origin !== 'http://127.0.0.1:8080') throw new Error('Original job scope mismatch.')
  if (job.fixture && (job.fixture.capsule.environment_id !== inventory.environment_id
    || job.fixture.capsule.target_artifact_hash !== inventory.artifact_hash
    || job.fixture.capsule.inventory_hash !== fixtureInputHash(inventory)
    || job.fixture.capsule.operator_policy_digest !== inventory.operator_policy_digest)) throw new Error('Original fixture target epoch mismatch.')
  const signal = AbortSignal.timeout(job.timeoutMs + 10000)
  const transport = await ownedDockerHttpTransport({ containerId: inventory.target.container_id,
    imageId: inventory.target.image_id, artifactHash: inventory.artifact_hash, expectedInventory: inventory, signal })
  const result = await executeHttpJob(raw, { wireBody: wire, signal, requestTransport: transport.request })
  await transport.verifyArtifact()
  process.stdout.write(JSON.stringify(result))
} catch {
  process.stderr.write('Owned HTTP execution or original instance verification failed.\n')
  process.exitCode = 2
}
