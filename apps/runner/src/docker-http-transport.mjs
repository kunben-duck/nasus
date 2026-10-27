import { execFile } from 'node:child_process'
import { MAX_HTTP_RESPONSE_BYTES } from './http-transport.mjs'
import { ownedTargetFence } from './owned-http-cohort.mjs'

const cleanEnvironment = () => Object.fromEntries(['PATH', 'HOME', 'TMPDIR'].flatMap((key) => process.env[key] ? [[key, process.env[key]]] : []))
const fail = () => { throw new Error('Owned target transport could not be verified.') }

export function dockerCommand(args, { signal, body = null, maxBuffer = 2 * 1024 * 1024 } = {}) {
  return new Promise((resolve, reject) => {
    const child = execFile('docker', args, { env: cleanEnvironment(), signal, timeout: 10000, maxBuffer, encoding: 'buffer' },
      (error, stdout) => error ? reject(new Error('Owned target subprocess failed.')) : resolve(stdout))
    child.stdin.on('error', () => {})
    child.stdin.end(body)
  })
}

export function parseOwnedHttpResponse(wire, limit) {
  const separator = wire.indexOf('\r\n\r\n'), headerBytes = separator + 4
  if (separator < 0 || headerBytes > 16384) fail()
  const lines = wire.subarray(0, separator).toString('latin1').split('\r\n')
  const status = /^HTTP\/1\.[01] ([1-5][0-9]{2})(?: |$)/.exec(lines.shift())
  const body = wire.subarray(headerBytes)
  if (!status || body.length > Math.min(limit, MAX_HTTP_RESPONSE_BYTES)) fail()
  const headers = Object.create(null)
  for (const line of lines) {
    const colon = line.indexOf(':'), name = line.slice(0, colon).toLowerCase(), value = line.slice(colon + 1).trim()
    if (colon < 1 || !/^[a-z0-9-]+$/.test(name) || /[\x00-\x1f\x7f]/.test(value)) fail()
    if (name === 'transfer-encoding') continue // curl has already removed the chunk framing.
    if (name === 'set-cookie') headers[name] = [...(headers[name] ?? []), value]
    else if (headers[name] !== undefined) fail()
    else headers[name] = value
  }
  return { status: Number(status[1]), headers, body }
}

export async function ownedDockerHttpTransport({ containerId, imageId, artifactHash, expectedInventory = null, signal, command = dockerCommand }) {
  const verifyArtifact = await ownedTargetFence({ containerId, imageId, artifactHash, expectedInventory, signal, command })
  const request = async (step, base, _pin, stop, byteLimit) => {
    if (base.origin !== 'http://127.0.0.1:8080') fail()
    stop = AbortSignal.any([signal, stop])
    stop.throwIfAborted()
    const url = new URL(step.path, base)
    if (url.origin !== base.origin || url.hash) fail()
    await verifyArtifact(stop)
    const args = ['exec', '--interactive', containerId, 'curl', '--disable', '--noproxy', '*', '--silent', '--show-error', '--include',
      '--max-time', '5', '--proto', '=http', '--request', step.method, '--url', url.href, '--header', 'Accept-Encoding: identity']
    const headers = JSON.parse(step.headers_json)
    for (const [key, value] of Object.entries(headers)) args.push('--header', key + ': ' + value)
    if (!Object.hasOwn(headers, 'Content-Type')) args.push('--header', 'Content-Type:')
    args.push('--header', 'Expect:', '--user-agent', '')
    if (step.method === 'HEAD') args.push('--head')
    const body = ['GET', 'HEAD'].includes(step.method) ? null : Buffer.from(step.body_json, 'utf8')
    if (body !== null) args.push('--data-binary', '@-')
    const wire = await command(args, { signal: stop, body, maxBuffer: MAX_HTTP_RESPONSE_BYTES + 16384 })
    await verifyArtifact(stop)
    return parseOwnedHttpResponse(wire, byteLimit)
  }
  return { request, verifyArtifact }
}
