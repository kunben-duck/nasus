import { strictJson } from './strict-json.mjs'

const fail = () => { throw new Error('Owned target transport could not be verified.') }
const ownerLabel = 'nasus.target.environment_owner'
const id = (value) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const digest = (value) => typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value)
const nonRoot = (value) => typeof value === 'string' && /^[1-9][0-9]{0,4}:[1-9][0-9]{0,4}$/.test(value) && value.split(':').every((part) => Number(part) <= 65535)
const canonical = (value) => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item)

// Never read Config.Env or trailing JVM arguments, which can contain credentials.
export const OWNED_CONTAINER_FORMAT = '{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},"Running":{{json .State.Running}},"StartedAt":{{json .State.StartedAt}},"User":{{json .Config.User}},"Labels":{{json .Config.Labels}},"Path":{{json .Path}},"Args":{{if and (eq .Path "java") (ge (len .Args) 2)}}{{json (slice .Args 0 2)}}{{else}}[]{{end}},"HostConfig":{"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},"CapDrop":{{json .HostConfig.CapDrop}},"CapAdd":{{json .HostConfig.CapAdd}},"Privileged":{{json .HostConfig.Privileged}},"SecurityOpt":{{json .HostConfig.SecurityOpt}},"NetworkMode":{{json .HostConfig.NetworkMode}},"PortBindings":{{json .HostConfig.PortBindings}},"PidMode":{{json .HostConfig.PidMode}},"IpcMode":{{json .HostConfig.IpcMode}},"UTSMode":{{json .HostConfig.UTSMode}},"Memory":{{json .HostConfig.Memory}},"NanoCpus":{{json .HostConfig.NanoCpus}},"PidsLimit":{{json .HostConfig.PidsLimit}},"Tmpfs":{{json .HostConfig.Tmpfs}}},"Mounts":{{json .Mounts}},"Networks":{{json .NetworkSettings.Networks}},"Ports":{{json .NetworkSettings.Ports}}}'
export const OWNED_NETWORK_FORMAT = '{"Id":{{json .Id}},"Name":{{json .Name}},"Internal":{{json .Internal}},"Driver":{{json .Driver}},"Scope":{{json .Scope}},"Attachable":{{json .Attachable}},"Labels":{{json .Labels}},"Containers":{{json .Containers}}}'

function verifyContainer(value, pin, prefix, networkId) {
  if (!value || Array.isArray(value) || !id(pin.container_id) || !digest(pin.image_id) || !nonRoot(pin.user)
    || value.Id !== pin.container_id || value.Image !== pin.image_id || value.Name !== '/' + prefix + '-' + pin.role
    || value.User !== pin.user || value.Running !== true || typeof pin.started_at !== 'string' || !pin.started_at
    || pin.started_at.length > 64 || value.StartedAt !== pin.started_at || value.Labels?.[ownerLabel] !== prefix.slice(-16)) fail()
  const host = value.HostConfig
  if (!host || host.Privileged !== false || !Array.isArray(host.CapDrop) || !host.CapDrop.includes('ALL')
    || host.CapAdd !== null && (!Array.isArray(host.CapAdd) || host.CapAdd.length !== 0)
    || !Array.isArray(host.SecurityOpt) || !host.SecurityOpt.some((item) => ['no-new-privileges', 'no-new-privileges:true'].includes(item))
    || host.NetworkMode !== prefix || host.PidMode !== '' || host.UTSMode !== '' || host.IpcMode !== 'private'
    || Object.keys(host.PortBindings ?? {}).length
    || [['Memory', 2 * 1024 ** 3], ['NanoCpus', 2_000_000_000], ['PidsLimit', 256]].some(([key, bound]) => !Number.isInteger(host[key]) || host[key] <= 0 || host[key] > bound)
    || value.Ports !== null && (!value.Ports || typeof value.Ports !== 'object' || Object.values(value.Ports).some((bindings) => bindings !== null))
    || !value.Networks || Object.keys(value.Networks).length !== 1 || value.Networks[prefix]?.NetworkID !== networkId) fail()
  const destination = pin.role === 'app' ? '/tmp' : pin.role === 'pg' ? '/var/lib/postgresql/data' : '/data'
  if (!host.Tmpfs || Object.keys(host.Tmpfs).length !== 1 || typeof host.Tmpfs[destination] !== 'string'
    || host.Tmpfs[destination].length > 256 || !host.Tmpfs[destination].split(',').includes('rw') || !Array.isArray(value.Mounts)) fail()
  if (pin.role === 'app') {
    const jars = value.Mounts.filter((item) => item.Destination === '/app/target.jar')
    if (pin.user !== '65534:65534' || host.ReadonlyRootfs !== true || value.Path !== 'java'
      || canonical(value.Args) !== canonical(['-jar', '/app/target.jar'])
      || jars.length !== 1 || jars[0].Type !== 'bind' || jars[0].RW !== false
      || value.Mounts.some((item) => item !== jars[0] && !(item.Type === 'tmpfs' && item.Destination === '/tmp'))) fail()
  } else if (value.Mounts.length > 1 || value.Mounts.some((item) => item.Type !== 'tmpfs' || item.Destination !== destination || item.RW !== true)) fail()
}

export async function ownedTargetFence({ containerId, imageId, artifactHash, expectedInventory = null, signal, command }) {
  if (!id(containerId) || !digest(imageId) || !digest(artifactHash)) fail()
  const inspect = async (kind, format, ident, stop = signal) => {
    stop.throwIfAborted()
    const body = await command([kind, 'inspect', '--format', format, ident], { signal: stop, maxBuffer: 256 * 1024 })
    stop.throwIfAborted()
    const value = strictJson(new TextDecoder('utf-8', { fatal: true }).decode(body))
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail()
    return value
  }
  const first = await inspect('container', OWNED_CONTAINER_FORMAT, containerId)
  const match = /^\/(nasus-(?:exweb|target)-[a-f0-9]{16})-app$/.exec(first.Name ?? '')
  if (!match) fail()
  const prefix = match[1], networkId = first.Networks?.[prefix]?.NetworkID
  if (!id(networkId)) fail()
  let expected = expectedInventory
  if (expected !== null) {
    if (expected.schema !== 'nasus.owned-target-environment.v1' || expected.artifact_hash !== artifactHash
      || expected.namespace_origin !== 'http://127.0.0.1:8080' || expected.network_id !== networkId
      || expected.target?.container_id !== containerId || expected.target?.image_id !== imageId
      || !Array.isArray(expected.dependency_instances) || expected.dependency_instances.length !== 2) fail()
  } else {
    const network = await inspect('network', OWNED_NETWORK_FORMAT, networkId)
    const dependencies = []
    for (const role of ['pg', 'redis']) {
      const members = Object.entries(network.Containers ?? {}).filter(([, member]) => member.Name === prefix + '-' + role)
      if (members.length !== 1 || !id(members[0][0])) fail()
      const item = await inspect('container', OWNED_CONTAINER_FORMAT, members[0][0])
      dependencies.push({ role, container_id: item.Id, image_id: item.Image, user: item.User, started_at: item.StartedAt })
    }
    expected = { target: { container_id: containerId, image_id: imageId, user: first.User, started_at: first.StartedAt }, dependency_instances: dependencies }
  }
  if (new Set(expected.dependency_instances.map((item) => item.role)).size !== 2
    || !expected.dependency_instances.some((item) => item.role === 'pg') || !expected.dependency_instances.some((item) => item.role === 'redis')) fail()
  const snapshot = async (stop = signal) => {
    const values = []
    for (const pin of [{ ...expected.target, role: 'app' }, ...expected.dependency_instances]) {
      const item = await inspect('container', OWNED_CONTAINER_FORMAT, pin.container_id, stop)
      verifyContainer(item, pin, prefix, networkId)
      values.push(item)
    }
    const network = await inspect('network', OWNED_NETWORK_FORMAT, networkId, stop)
    if (network.Id !== networkId || network.Name !== prefix || network.Internal !== true || network.Attachable !== false
      || network.Driver !== 'bridge' || network.Scope !== 'local' || network.Labels?.[ownerLabel] !== prefix.slice(-16)
      || !network.Containers || canonical(Object.keys(network.Containers).sort()) !== canonical(values.map((item) => item.Id).sort())
      || new Set(values.map((item) => item.Id)).size !== 3) fail()
    return canonical({ values, network })
  }
  const original = await snapshot()
  const verify = async (stop = signal) => {
    if (await snapshot(stop) !== original) fail()
    const output = await command(['exec', containerId, 'sha256sum', '/app/target.jar'], { signal: stop, maxBuffer: 256 })
    stop.throwIfAborted()
    if (output.toString('ascii').trim() !== artifactHash.slice(7) + '  /app/target.jar' || await snapshot(stop) !== original) fail()
  }
  await verify()
  return verify
}
