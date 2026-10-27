import assert from 'node:assert/strict'
import test from 'node:test'
import { ownedDockerHttpTransport, parseOwnedHttpResponse } from '../src/docker-http-transport.mjs'
import { executeHttpJob } from '../src/http-executor.mjs'
import { OWNED_CONTAINER_FORMAT, OWNED_NETWORK_FORMAT } from '../src/owned-http-cohort.mjs'

const containerId = 'a'.repeat(64), imageId = 'sha256:' + 'b'.repeat(64), artifactHash = 'sha256:' + 'c'.repeat(64)
const name = 'nasus-exweb-' + 'd'.repeat(16) + '-app'
for (const fault of ['container', 'image', 'name', 'stopped', 'rootfs', 'capabilities', 'added-capabilities', 'root-user', 'unnamed-user', 'privileges', 'network', 'ports', 'published', 'writable', 'command']) {
  test(`owned target admission rejects ${fault} before HTTP`, async () => {
    const calls = [], cohort = cohortSpecimen(), target = cohort.containers[containerId]
    if (fault === 'container') target.Id = 'other'
    if (fault === 'image') target.Image = 'other'
    if (fault === 'name') target.Name = '/unowned-app'
    if (fault === 'stopped') target.Running = false
    if (fault === 'rootfs') target.HostConfig.ReadonlyRootfs = false
    if (fault === 'capabilities') target.HostConfig.CapDrop = []
    if (fault === 'added-capabilities') target.HostConfig.CapAdd = ['SYS_ADMIN']
    if (fault === 'root-user') target.User = '0:0'
    if (fault === 'unnamed-user') target.User = ''
    if (fault === 'privileges') target.HostConfig.Privileged = true
    if (fault === 'network') target.HostConfig.NetworkMode = 'host'
    if (fault === 'ports') target.HostConfig.PortBindings = { '8080/tcp': [{ HostPort: '8080' }] }
    if (fault === 'published') target.Ports['8080/tcp'] = [{ HostPort: '8080' }]
    if (fault === 'writable') target.Mounts[0].RW = true
    if (fault === 'command') target.Args = ['unreviewed']
    await assert.rejects(() => ownedDockerHttpTransport({ containerId, imageId, artifactHash, expectedInventory: cohort.inventory,
      signal: AbortSignal.timeout(5000), command: specimenCommand(calls, { cohort }) }), /verified/)
    assert.equal(calls.some(({ args }) => args.includes('curl')), false)
  })
}

test('curl observations preserve body bytes, non-2xx status and empty responses', () => {
  const body = Buffer.from('{"message":"\u4e2d\u6587","value":0.10000000000000001}', 'utf8')
  const response = parseOwnedHttpResponse(Buffer.concat([Buffer.from('HTTP/1.1 500 Error\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n'), body]), 1024)
  assert.equal(response.status, 500); assert.deepEqual(response.body, body)
  assert.equal(response.headers['content-type'], 'application/json')
  assert.equal(response.headers['transfer-encoding'], undefined)
  assert.equal(parseOwnedHttpResponse(Buffer.from('HTTP/1.1 204 No Content\r\n\r\n'), 0).body.length, 0)
  for (const wire of ['HTTP/1.1 200 OK\r\nX-Key: first\r\nX-Key: second\r\n\r\n', 'not-http', 'HTTP/1.1 200 OK\r\n\r\nlarge']) {
    assert.throws(() => parseOwnedHttpResponse(Buffer.from(wire), 2), /verified/)
  }
})

export function cohortSpecimen() {
  const prefix = name.slice(0, -4), networkId = 'e'.repeat(64)
  const containers = {}
  for (const [role, ident, image, user] of [['app', containerId, imageId, '65534:65534'],
    ['pg', 'f'.repeat(64), 'sha256:' + '1'.repeat(64), '999:999'], ['redis', '2'.repeat(64), 'sha256:' + '3'.repeat(64), '999:999']]) {
    const destination = role === 'app' ? '/tmp' : role === 'pg' ? '/var/lib/postgresql/data' : '/data'
    containers[ident] = { Id: ident, Image: image, Name: '/' + prefix + '-' + role, User: user, Running: true,
      StartedAt: '2026-10-11T00:00:00Z', Labels: { 'nasus.target.environment_owner': 'd'.repeat(16) },
      Path: role === 'app' ? 'java' : role, Args: role === 'app' ? ['-jar', '/app/target.jar'] : [],
      HostConfig: { ReadonlyRootfs: role === 'app', CapDrop: ['ALL'], CapAdd: null, SecurityOpt: ['no-new-privileges:true'],
        Privileged: false, NetworkMode: prefix, PortBindings: null, PidMode: '', IpcMode: 'private', UTSMode: '',
        Memory: 512 * 1024 ** 2, NanoCpus: 1_000_000_000, PidsLimit: 128, Tmpfs: { [destination]: 'rw,size=128m' } },
      Networks: { [prefix]: { NetworkID: networkId } }, Ports: { '8080/tcp': null },
      Mounts: role === 'app' ? [{ Type: 'bind', Destination: '/app/target.jar', RW: false }] : [] }
  }
  const network = { Id: networkId, Name: prefix, Internal: true, Driver: 'bridge', Scope: 'local', Attachable: false,
    Labels: { 'nasus.target.environment_owner': 'd'.repeat(16) },
    Containers: Object.fromEntries(Object.values(containers).map((item) => [item.Id, { Name: item.Name.slice(1) }])) }
  const pin = (item) => ({ container_id: item.Id, image_id: item.Image, user: item.User, started_at: item.StartedAt })
  const inventory = { schema: 'nasus.owned-target-environment.v1', artifact_hash: artifactHash, namespace_origin: 'http://127.0.0.1:8080',
    target: pin(containers[containerId]), network_id: networkId,
    dependency_instances: ['pg', 'redis'].map((role) => ({ role, ...pin(Object.values(containers).find((item) => item.Name.endsWith('-' + role))) })) }
  return { containers, network, inventory }
}

function specimenCommand(calls, { changedArtifact = false, externalNetwork = false, cohort = cohortSpecimen(), after = () => {} } = {}) {
  return async (args, options) => {
    calls.push({ args, options })
    options.signal.throwIfAborted()
    after(args, cohort)
    if (args[0] === 'container') {
      assert.equal(args[3], OWNED_CONTAINER_FORMAT)
      return Buffer.from(JSON.stringify(cohort.containers[args.at(-1)]))
    }
    if (args[0] === 'network') {
      assert.equal(args[3], OWNED_NETWORK_FORMAT)
      return Buffer.from(JSON.stringify({ ...cohort.network, Internal: !externalNetwork }))
    }
    if (args[2] === 'sha256sum') return Buffer.from((changedArtifact ? 'e'.repeat(64) : artifactHash.slice(7)) + '  /app/target.jar\n')
    return Buffer.from('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{"value":true}')
  }
}

test('owned transport uses exact container loopback and raw POST, never host ports or redirects', async () => {
  const calls = [], signal = AbortSignal.timeout(5000)
  const transport = await ownedDockerHttpTransport({ containerId, imageId, artifactHash, signal, command: specimenCommand(calls) })
  const raw = { job_id: 'owned-protocol-job', project_id: 'explicit-fixture', us_id: 'explicit-case',
    base_url: 'http://127.0.0.1:8080', timeout_ms: 5000, execution_kind: 'http', receipt_protocol: 'nasus.runner-http-execution.v1',
    steps: [{ action: 'request', request_id: 'original', method: 'POST', path: '/original', headers_json: '{"Content-Type":"application/json"}', body_json: '{ "original": true }' },
      { action: 'assert_json', request_id: 'original', pointer: '/value', value_json: 'true' }] }
  const result = await executeHttpJob(raw, { requestTransport: transport.request })
  assert.equal(result.status, 'passed'); assert.equal(result.execution_receipt.business_coverage_verified, false)
  const request = calls.find(({ args }) => args.includes('curl'))
  assert.deepEqual(request.args.slice(0, 4), ['exec', '--interactive', containerId, 'curl'])
  assert.equal(request.args[request.args.indexOf('--url') + 1], 'http://127.0.0.1:8080/original')
  assert.equal(request.options.body.toString(), raw.steps[0].body_json)
  assert.equal(request.args.includes('--location'), false)
  await transport.verifyArtifact()
  await assert.rejects(() => transport.request(raw.steps[0], new URL('http://localhost:8000'), null, signal, 1024), /verified/)
})

for (const change of ['app-restart', 'dependency-restart', 'dependency-image', 'dependency-root', 'owner', 'network-replacement', 'extra-member',
  'extra-network', 'host-volume', 'ports', 'capabilities', 'privileges', 'pid', 'memory', 'jar-command']) {
  test(`original owned cohort rejects ${change} before HTTP`, async () => {
    const calls = [], cohort = cohortSpecimen(), original = structuredClone(cohort.inventory)
    const app = cohort.containers[containerId], pg = cohort.containers['f'.repeat(64)]
    if (change === 'app-restart') app.StartedAt = '2026-10-11T01:00:00Z'
    if (change === 'dependency-restart') pg.StartedAt = '2026-10-11T01:00:00Z'
    if (change === 'dependency-image') pg.Image = imageId
    if (change === 'dependency-root') pg.User = '0:0'
    if (change === 'owner') pg.Labels['nasus.target.environment_owner'] = 'other'
    if (change === 'network-replacement') cohort.network.Id = '4'.repeat(64)
    if (change === 'extra-member') cohort.network.Containers['4'.repeat(64)] = { Name: 'foreign' }
    if (change === 'extra-network') app.Networks.other = { NetworkID: '4'.repeat(64) }
    if (change === 'host-volume') pg.Mounts.push({ Type: 'bind', Destination: '/data', RW: false })
    if (change === 'ports') app.Ports['8080/tcp'] = [{ HostPort: '8080' }]
    if (change === 'capabilities') app.HostConfig.CapAdd = ['SYS_ADMIN']
    if (change === 'privileges') app.HostConfig.Privileged = true
    if (change === 'pid') app.HostConfig.PidMode = 'host'
    if (change === 'memory') app.HostConfig.Memory = 0
    if (change === 'jar-command') app.Args = ['-jar', '/app/other.jar']
    await assert.rejects(() => ownedDockerHttpTransport({ containerId, imageId, artifactHash, expectedInventory: original,
      signal: AbortSignal.timeout(5000), command: specimenCommand(calls, { cohort }) }), /verified/)
    assert.equal(calls.some(({ args }) => args.includes('curl')), false)
  })
}

for (const phase of ['before-request', 'after-request']) test(`restart ${phase} cannot yield a verified response`, async () => {
  const calls = [], cohort = cohortSpecimen()
  const signal = AbortSignal.timeout(5000)
  const command = specimenCommand(calls, { cohort, after: (args) => {
    if (phase === 'after-request' && args.includes('curl')) cohort.containers[containerId].StartedAt = 'restarted'
  } })
  const transport = await ownedDockerHttpTransport({ containerId, imageId, artifactHash, expectedInventory: cohort.inventory, signal, command })
  if (phase === 'before-request') cohort.containers[containerId].StartedAt = 'restarted'
  await assert.rejects(() => transport.request({ method: 'GET', path: '/original', headers_json: '{}', body_json: 'null' },
    new URL('http://127.0.0.1:8080'), null, signal, 1024), /verified/)
  assert.equal(calls.filter(({ args }) => args.includes('curl')).length, phase === 'before-request' ? 0 : 1)
  assert.ok(calls.filter(({ args }) => args[0] === 'container').every(({ args }) => !args.includes('Config.Env')))
})

test('cancelled owned work cannot send an HTTP request', async () => {
  const calls = [], signal = AbortSignal.timeout(5000), stop = new AbortController()
  const transport = await ownedDockerHttpTransport({ containerId, imageId, artifactHash, signal, command: specimenCommand(calls) })
  stop.abort()
  await assert.rejects(() => transport.request({ path: '/original' }, new URL('http://127.0.0.1:8080'), null, stop.signal, 1024), { name: 'AbortError' })
  assert.equal(calls.some(({ args }) => args.includes('curl')), false)
})

for (const fault of ['artifact', 'network']) test(`owned ${fault} mismatch cannot dispatch HTTP`, async () => {
  const calls = []
  await assert.rejects(() => ownedDockerHttpTransport({ containerId, imageId, artifactHash, signal: AbortSignal.timeout(5000),
    command: specimenCommand(calls, { changedArtifact: fault === 'artifact', externalNetwork: fault === 'network' }) }), /verified/)
  assert.equal(calls.some(({ args }) => args.includes('curl')), false)
})
