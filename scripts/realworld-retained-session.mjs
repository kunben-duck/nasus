// Retained acceptance account setup through the real UI, never database writes.
import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import { chromium } from 'playwright'

const args = process.argv.slice(2)
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback
const id = option('--acceptance-id', '')
const role = option('--role', 'operator')
const origin = new URL(option('--portal', 'http://localhost:5173'))
if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(id) || !['operator', 'reviewer'].includes(role)
    || origin.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(origin.hostname)
    || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) {
  throw new Error('Select an acceptance ID, role, and local development Portal origin.')
}
const directory = path.resolve('output/realworld', id)
await fs.mkdir(directory, { recursive: true, mode: 0o700 })
await fs.chmod(directory, 0o700)
const credentialsPath = path.join(directory, `${role}-credentials.private.json`)
let credentials
try {
  credentials = JSON.parse(await fs.readFile(credentialsPath, 'utf8'))
} catch (error) {
  if (error.code !== 'ENOENT') throw error
  credentials = { email: `nasus-${id}-${role}@example.test`, password: crypto.randomBytes(24).toString('base64url') }
  await fs.writeFile(credentialsPath, JSON.stringify(credentials), { mode: 0o600, flag: 'wx' })
}
const statePath = path.join(directory, `${role}-state.private.json`)
const browser = await chromium.launch({ headless: !args.includes('--headed') })
const context = await browser.newContext()
const page = await context.newPage()
const report = { acceptance_id: id, role, portal: origin.origin, full_m3_verified: false, data_retained: true }
try {
  await page.goto(`${origin.origin}/login`)
  await page.getByRole('textbox', { name: /^(邮箱|Email)$/ }).fill(credentials.email)
  await page.getByRole('textbox', { name: /^(密码|Password)$/ }).fill(credentials.password)
  const loginResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/v1/auth/login'
    && response.request().method() === 'POST')
  await page.getByRole('button', { name: /^(登录|Sign in|Log in)$/ }).click()
  const login = await loginResponse
  if (login.status() === 401) {
    await page.goto(`${origin.origin}/register`)
    await page.getByRole('textbox', { name: /^(姓名|Name)$/ }).fill(`M3 Acceptance ${role}`)
    await page.getByRole('textbox', { name: /^(邮箱|Email)$/ }).fill(credentials.email)
    await page.getByRole('textbox', { name: /^(密码|Password)$/ }).fill(credentials.password)
    await page.getByRole('textbox', { name: /^(确认密码|Confirm password)$/ }).fill(credentials.password)
    await page.getByRole('button', { name: /^(创建账号|Create account)$/ }).click()
  } else if (!login.ok()) throw new Error('Login failed; do not infer that the account is absent')
  await page.waitForURL('**/build', { timeout: 30000 })
  await context.storageState({ path: statePath })
  await fs.chmod(statePath, 0o600)
  report.status = 'account_ready'
  report.page_url = page.url()
  await page.screenshot({ path: path.join(directory, `${role}-build.png`), fullPage: true })
  console.log(JSON.stringify(report))
} catch (error) {
  report.status = 'blocked'
  report.reason = error.name
  report.page_url = page.url()
  console.error(JSON.stringify(report))
  process.exitCode = 1
} finally {
  await fs.writeFile(path.join(directory, `${role}-session.json`), JSON.stringify(report, null, 2), { mode: 0o600 })
  await browser.close()
}
