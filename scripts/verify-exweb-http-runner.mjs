// Internal operator probe only. The Runner HTTP API cannot choose this transport.
import { ownedDockerHttpTransport } from '../apps/runner/src/docker-http-transport.mjs'
import { executeHttpJob } from '../apps/runner/src/http-executor.mjs'
import { validateHttpJob } from '../apps/runner/src/http-job.mjs'
import { strictJson } from '../apps/runner/src/strict-json.mjs'

try {
  const [flag, containerId, imageId, artifactHash, ...extra] = process.argv.slice(2)
  if (flag !== '--execute-owned-exweb-http' || extra.length) throw new Error('Explicit owned target execution is required.')
  const chunks = []
  let size = 0
  for await (const chunk of process.stdin) {
    size += chunk.length
    if (size > 512 * 1024) throw new Error('Complete original HTTP job exceeds the probe bound.')
    chunks.push(chunk)
  }
  const wire = Buffer.concat(chunks)
  const raw = strictJson(new TextDecoder('utf-8', { fatal: true }).decode(wire))
  const job = validateHttpJob(raw)
  if (job.base.origin !== 'http://127.0.0.1:8080') throw new Error('Owned loopback target is required.')
  const signal = AbortSignal.timeout(job.timeoutMs + 10000)
  const transport = await ownedDockerHttpTransport({ containerId, imageId, artifactHash, signal })
  const result = await executeHttpJob(raw, { wireBody: wire, signal, requestTransport: transport.request })
  await transport.verifyArtifact()
  process.stdout.write(JSON.stringify(result))
} catch {
  process.stderr.write('Owned target execution or artifact verification failed.\n')
  process.exitCode = 2
}
