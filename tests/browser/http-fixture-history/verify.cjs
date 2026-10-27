const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { execFileSync } = require('node:child_process'), { chromium } = require('playwright')
const ts = require('../../../apps/portal/node_modules/typescript')
const repo = path.resolve(__dirname, '../../..'), output = path.join(repo, 'output/playwright')
const origin = process.env.NASUS_BROWSER_CONTRACT_ORIGIN ?? 'http://127.0.0.1:4207'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const specimen = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-m', 'tests.browser.http-fixture-history.specimen'], { cwd: repo }).toString())
const messages = { exports: {} }
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(repo, 'apps/portal/src/shared/i18n/messages.ts'), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, messages)
async function eventually(check, text) {
  const end = Date.now() + 10000
  do { if (await check()) return; await new Promise((resolve) => setTimeout(resolve, 30)) } while (Date.now() < end)
  throw new Error(text)
}
async function run(browser, { theme, locale, width, cancelled = false, corrupt = false }) {
  const context = await browser.newContext({ viewport: { width, height: 900 } }), page = await context.newPage()
  const sample = structuredClone(cancelled ? specimen.cancelled : specimen.running)
  const reads = [], writes = [], unexpected = [], egress = [], errors = []
  let reject = false, damage = corrupt, release
  const label = (key, values = {}) => Object.entries(values).reduce((text, [name, value]) => text.replace('{' + name + '}', value),
    locale === 'zh' ? messages.exports.zhCN[key] ?? key : key)
  const button = (key, values) => page.getByRole('button', { name: label(key, values), exact: true })
  page.on('pageerror', (error) => errors.push(error.message))
  await context.route('**/*', async (route) => {
    if (new URL(route.request().url()).origin === origin) return route.continue()
    egress.push(route.request().url()); await route.abort('blockedbyclient')
  })
  await page.route('**/v1/**', async (route) => {
    const request = route.request(), url = new URL(request.url()), parts = url.pathname.split('/')
    const answer = (body, status = 200) => route.fulfill({ status, contentType: 'application/json',
      headers: { 'Cache-Control': 'private, no-store' }, body: JSON.stringify(body) })
    if (request.method() !== 'GET') { writes.push(url.pathname); return answer({ message: 'No writes allowed' }, 500) }
    reads.push(url.pathname)
    if (reject) return answer({ detail: { error: { code: 'source_access_denied', message: 'Explicit transport revocation' } } }, 403)
    if (url.pathname === '/v1/projects/p/quality/http-fixture-operations') return answer(sample.page)
    const id = parts[6], item = sample.page.items.find((value) => value.invocation_id === id)
    if (item && parts.length === 7) return answer(item)
    if (item && parts.length === 8 && parts[7] === 'observation') {
      const value = structuredClone(sample.observations[id])
      await new Promise((resolve) => { release = resolve })
      if (damage) value.business_coverage_verified = true
      return answer(value)
    }
    unexpected.push(url.pathname); return answer({ message: 'Unexpected protected API' }, 500)
  })
  const inspect = async () => {
    await button('Find original test data operations').click()
    await button('Inspect original command {id}', { id: '002-execute' }).click()
    await page.getByTestId('fixture-history-metadata').waitFor({ state: 'visible' })
    await button('Inspect persisted operation phases').click()
    await eventually(async () => release && await page.getByTestId('fixture-history-metadata').count() === 0, 'Old metadata must be hidden while reading journal')
    release(); release = undefined
  }
  try {
    await page.goto(`${origin}/tests/browser/http-fixture-history/index.html?theme=${theme}&locale=${locale}`)
    await button('Find original test data operations').waitFor({ state: 'visible' })
    assert.deepEqual(reads, [], 'Folded history must perform no protected reads')
    await inspect()
    if (damage) {
      await page.getByRole('alert').waitFor({ state: 'visible' })
      assert.equal(await page.getByTestId('fixture-original-observation').count(), 0)
      assert.equal(await page.getByTestId('fixture-history-metadata').count(), 0)
      assert.equal(await button('Inspect original command {id}', { id: '002-execute' }).count(), 0)
    } else {
      await page.getByTestId('fixture-original-observation').waitFor({ state: 'visible' })
      await page.getByText(label('The effect of the original operation is unknown. Do not resend it; cancellation does not prove rollback.'), { exact: true }).waitFor()
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      assert.equal(await page.evaluate(() => sessionStorage.length), 0, 'Cross-browser reads must not require/create recovery keys')
      assert.equal(await page.getByRole('checkbox').count(), 0, 'Inspection must never reuse or create confirmation')
      await page.screenshot({ path: path.join(output, `fixture-history-${theme}-${locale}-${width}-${cancelled ? 'cancelled' : 'unknown'}.png`), fullPage: true })
      if (!cancelled) {
        await page.reload(); await button('Find original test data operations').waitFor()
        await inspect(); await page.getByTestId('fixture-original-observation').waitFor({ state: 'visible' })
      }
    }
    reject = true
    await button('Reload test data history').click()
    await page.getByRole('alert').waitFor({ state: 'visible' })
    assert.equal(await page.getByTestId('fixture-original-observation').count(), 0)
    assert.equal(await page.getByTestId('fixture-history-metadata').count(), 0)
    assert.deepEqual(writes, []); assert.deepEqual(unexpected, []); assert.deepEqual(egress, []); assert.deepEqual(errors, [])
    return { theme, locale, width, cancelled, corrupt, reads: reads.length, writes, unexpected, egress, errors }
  } catch (error) {
    await page.screenshot({ path: path.join(output, `fixture-history-${theme}-${locale}-${width}-FAILED.png`), fullPage: true }).catch(() => {})
    fs.writeFileSync(path.join(output, `fixture-history-${theme}-${locale}-${width}-FAILED.txt`), `${error.stack}\n${await page.locator('body').innerText()}\n${JSON.stringify({ reads, writes, unexpected, egress, errors }, null, 2)}`)
    throw error
  } finally { if (release) release(); await context.close() }
}
;(async () => {
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  try {
    const results = []
    results.push(await run(browser, { theme: 'light', locale: 'en', width: 1280 }))
    results.push(await run(browser, { theme: 'dark', locale: 'zh', width: 390, cancelled: true }))
    results.push(await run(browser, { theme: 'light', locale: 'zh', width: 390, corrupt: true }))
    const report = { scope: 'Production component and real React Query with intercepted transport. Not real auth, full route, PG, Temporal, exweb or business gold.', results }
    fs.writeFileSync(path.join(output, 'fixture-history-browser-contract-20261013.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report, null, 2))
  } finally { await browser.close() }
})().catch((error) => { console.error(error.stack); process.exitCode = 1 })
