import { lookup } from 'node:dns/promises'
import http from 'node:http'
import https from 'node:https'
import net from 'node:net'

export const MAX_HTTP_RESPONSE_BYTES = 1024 * 1024
export async function pinHttpTarget(base, signal) {
  const host = base.hostname.replace(/^\[|\]$/g, '').toLowerCase()
  const configured = (process.env.NASUS_RUNNER_ALLOWED_HOSTS ?? '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean)
  const allowed = configured.length ? configured : process.env.NASUS_ENV !== 'production' ? ['localhost', '127.0.0.1', '::1'] : []
  if (!allowed.includes(host)) throw new Error('HTTP target needs an exact operator-approved host.')
  signal.throwIfAborted()
  let abort
  const interrupted = new Promise((_resolve, reject) => {
    abort = () => reject(signal.reason); signal.addEventListener('abort', abort, { once: true })
  })
  let addresses
  try {
    addresses = net.isIP(host) ? [{ address: host, family: net.isIP(host) }]
      : await Promise.race([lookup(host, { all: true, verbatim: true }), interrupted])
  } finally { signal.removeEventListener('abort', abort) }
  signal.throwIfAborted()
  if (!addresses.length || addresses.length > 16 || addresses.some(({ address, family }) => {
    const normalized = address.toLowerCase()
    return ![4, 6].includes(family) || net.isIP(address) !== family || /^(0\.|169\.254\.)/.test(normalized)
      || normalized === '::' || normalized.startsWith('::ffff:') || normalized === 'fd00:ec2::254'
      || normalized === '100.100.100.200' || /^(22[4-9]|23[0-9]|255)\./.test(normalized)
      || /^fe[89ab][0-9a-f]:|^ff/.test(normalized)
      || !configured.length && !['127.0.0.1', '::1'].includes(normalized)
  })) throw new Error('HTTP target resolution is unsafe or outside its reviewed bound.')
  // Every request uses this one pinned resolution; redirects and DNS retries are disabled.
  return { host, address: addresses[0] }
}
export function requestHttp(step, base, pin, signal, byteLimit) {
  const url = new URL(step.path, base)
  const body = ['GET', 'HEAD'].includes(step.method) ? null : Buffer.from(step.body_json, 'utf8')
  const headers = JSON.parse(step.headers_json)
  if (body !== null) headers['Content-Length'] = String(body.length)
  return new Promise((resolve, reject) => {
    const transport = url.protocol === 'https:' ? https : http
    const request = transport.request({ hostname: pin.host, port: url.port || undefined, path: url.pathname + url.search,
      method: step.method, headers, signal, agent: false, family: pin.address.family,
      autoSelectFamily: false, lookup: (_host, _options, callback) => callback(null, pin.address.address, pin.address.family),
      rejectUnauthorized: true, maxHeaderSize: 16384 }, (response) => {
      const chunks = []; let size = 0
      response.on('data', (chunk) => {
        size += chunk.length
        if (size > Math.min(MAX_HTTP_RESPONSE_BYTES, byteLimit)) response.destroy(new Error('HTTP response exceeded its byte budget.'))
        else chunks.push(chunk)
      })
      response.on('error', reject)
      response.on('aborted', () => reject(new Error('HTTP response was interrupted.')))
      response.on('end', () => {
        if (!response.complete) return reject(new Error('HTTP response is incomplete.'))
        resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) })
      })
    })
    request.on('error', reject)
    request.end(body)
  })
}
