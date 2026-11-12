const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { execFileSync } = require('node:child_process'), { chromium } = require('playwright')
const ts = require('../../../apps/portal/node_modules/typescript')
const repo = path.resolve(__dirname, '../../..'), output = path.join(repo, 'output/playwright/runs-fixture-history')
const origin = process.env.NASUS_BROWSER_CONTRACT_ORIGIN ?? 'http://127.0.0.1:4207'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const specimen = JSON.parse(execFileSync(path.join(repo, '.venv/bin/python'), ['-m', 'tests.browser.http-fixture-history.specimen'], {
  cwd: repo, encoding: 'utf8', env: { ...process.env,
    NASUS_DATABASE_URL: 'postgresql+psycopg://contract@127.0.0.1:1/nasus_case_contract', NASUS_AUTO_CREATE_TABLES: 'false' },
}))
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
    await page.getByRole('heading', { name: label('Runs'), exact: true }).waitFor({ state: 'visible' })
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
async function runSetupPicker(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 } }), page = await context.newPage()
  const original = specimen.running.page, [grant, execution] = original.items
  const row = (id, overrides = {}) => ({ ...execution, invocation_id: id, original_execution_id: id, status: 'completed', ...overrides })
  const first = { ...original, total: 5, next_after_id: '003-cleanup', items: [grant, execution, row('003-cleanup', { operation: 'cleanup' })] }
  const second = { ...original, request: { ...original.request, after_id: '003-cleanup' }, total: 5, next_after_id: null,
    items: [row('004-other-plan', { run_plan_id: 'other-plan' }), row('005-matching-setup')] }
  const reads = [], writes = [], unexpected = [], errors = []
  let reject = false
  page.on('pageerror', (error) => errors.push(error.message))
  await context.route('**/*', async (route) => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== origin) { unexpected.push(url.origin); return route.abort('blockedbyclient') }
    if (!url.pathname.startsWith('/v1/')) return route.continue()
    if (request.method() !== 'GET') { writes.push(url.pathname); return route.abort('blockedbyclient') }
    if (url.pathname !== '/v1/projects/p/quality/http-fixture-operations') {
      unexpected.push(url.pathname); return route.abort('blockedbyclient')
    }
    const after = url.searchParams.get('after_id'); reads.push(after)
    if (url.searchParams.get('limit') !== '3' || !['', '003-cleanup'].includes(after)) unexpected.push(url.search)
    return route.fulfill({ status: reject ? 403 : 200, contentType: 'application/json',
      headers: { 'Cache-Control': 'private, no-store' }, body: JSON.stringify(reject ? { detail: 'Source access denied' } : after ? second : first) })
  })
  const button = (key) => page.getByRole('button', { name: messages.exports.zhCN[key] ?? key, exact: true })
  try {
    await page.goto(`${origin}/tests/browser/http-fixture-history/index.html?locale=zh&setupPlanHash=${encodeURIComponent(execution.run_plan_artifact_hash)}`)
    await button('Find setup commands for this plan').waitFor()
    assert.deepEqual(reads, [], 'Collapsed setup picker must not read protected history')
    const reference = page.getByRole('textbox', { name: 'Setup reference', exact: true })
    await reference.fill('manual-reference')
    await button('Find setup commands for this plan').click()
    await page.getByText(messages.exports.zhCN['No matching setup commands on the pages loaded. You can enter a command ID directly.'], { exact: true }).waitFor()
    assert.equal(await reference.inputValue(), 'manual-reference')
    await button('Load more test data operations').click()
    const picker = page.getByRole('combobox', { name: messages.exports.zhCN['Choose a saved setup for {case}'].replace('{case}', 'case:0'), exact: true })
    await picker.waitFor()
    assert.deepEqual(await picker.locator('option').evaluateAll((options) => options.map((option) => option.value)), ['', '005-matching-setup'])
    await picker.selectOption('005-matching-setup')
    assert.equal(await reference.inputValue(), '005-matching-setup')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: path.join(output, 'case-setup-picker-zh-390.png'), fullPage: true })
    reject = true
    await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))
    await page.getByRole('alert').waitFor()
    assert.equal(await picker.count(), 0)
    assert.deepEqual(writes, []); assert.deepEqual(unexpected, []); assert.deepEqual(errors, [])
    return { reads, writes, unexpected, errors }
  } finally { await context.close() }
}
async function runCaseHistory(browser) {
  const context = await browser.newContext({ viewport: { width: 390, height: 900 } }), page = await context.newPage()
  const sample = specimen.case_execution, { state, observations } = sample.view.history
  const base = `/v1/projects/${sample.input.project_id}/quality`
  const commandPath = `/v1/tool-invocations/${sample.command.id}`
  const planPath = `${base}/run-plans/${sample.input.run_plan_id}`
  const historyPath = `${base}/run-plan-case-executions/${sample.command.id}`
  const reads = [], writes = [], unexpected = [], errors = []
  let mode = 'original', releaseFault
  const pauseFault = () => new Promise((resolve) => { releaseFault = resolve })
  const label = (key, values = {}) => (messages.exports.zhCN[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => String(values[name]))
  const panel = page.locator('.case-history-lookup')
  const summary = panel.getByRole('list', { name: label('Case result summary'), exact: true })
  const submit = panel.getByRole('button', { name: label('Find execution results'), exact: true })
  page.on('pageerror', (error) => errors.push(error.message))
  await context.route('**/*', async (route) => {
    const request = route.request(), url = new URL(request.url())
    if (url.origin !== origin) { unexpected.push(url.origin); return route.abort('blockedbyclient') }
    if (!url.pathname.startsWith('/v1/')) return route.continue()
    if (request.method() !== 'GET') { writes.push(url.pathname); return route.abort('blockedbyclient') }
    reads.push(url.pathname)
    const answer = (body, status = 200) => route.fulfill({ status, contentType: 'application/json',
      headers: { 'Cache-Control': 'private, no-store' }, body: JSON.stringify(body) })
    if (url.pathname === commandPath) {
      if (mode !== 'revoked') return answer(sample.command)
      await pauseFault()
      return answer({ detail: 'Access denied' }, 403)
    }
    if (url.pathname === planPath) return answer(sample.plan)
    if (url.pathname === historyPath) {
      const result = structuredClone(sample.view)
      if (mode === 'tampered') {
        result.history.observations[0].runner_receipt.requests[0].response_status = 599
        await pauseFault()
      }
      return answer(result)
    }
    unexpected.push(url.pathname); return route.abort('blockedbyclient')
  })
  try {
    await page.goto(`${origin}/tests/browser/http-fixture-history/index.html?theme=dark&locale=zh`)
    await panel.getByText(label('Find a past execution by command ID'), { exact: true }).click()
    const field = panel.getByRole('textbox', { name: label('Original execution command ID'), exact: true })
    await field.fill(sample.command.id)
    assert.deepEqual(reads, [], 'Opening the lookup or typing an ID must not read protected records')
    await submit.click()
    await summary.getByText(label('Failed: {count}', { count: state.case_count }), { exact: true }).waitFor()
    await summary.getByText(label('Passed: {count}', { count: 0 }), { exact: true }).waitFor()
    await panel.getByText(label('completed'), { exact: true }).waitFor()
    await panel.getByText(label('These are original execution observations, not formal coverage or release evidence. Completed does not mean every test passed.'), { exact: true }).waitFor()
    const first = observations[0], failed = first.oracles.find((item) => item.status === 'failed')
    const script = sample.plan.artifact.plan.proposal.scripts.find((item) => item.case_id === first.case_id)
    const assertion = script.assertions.find((item) => item.row_id === failed.row_id)
    const requestId = script.actions[assertion.action_index].request_id
    const wire = first.runner_receipt.requests.find((item) => item.request_id === requestId)
    const detail = panel.locator('.case-observation-list details').first()
    await detail.locator('summary').click()
    await detail.getByText(label('Expected: {result}', { result: assertion.oracle.expected_result }), { exact: true }).waitFor()
    await detail.getByText(label('Observed HTTP status: {status}', { status: wire.response_status }), { exact: true }).first().waitFor()
    assert.equal(await panel.locator('.case-observation-list details').count(), state.case_count)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth || sessionStorage.length !== 0), false)
    assert.deepEqual(reads, [commandPath, planPath, historyPath])
    await page.screenshot({ path: path.join(output, 'original-case-results-zh-390.png'), fullPage: true })
    for (const fault of ['revoked', 'tampered']) {
      mode = fault
      await submit.click()
      await eventually(() => releaseFault, 'The selected fault response must belong to the current request')
      await panel.getByRole('status').waitFor()
      assert.equal(await summary.count(), 0)
      releaseFault(); releaseFault = undefined
      await panel.getByRole('alert').waitFor()
      assert.equal(await summary.count(), 0)
      assert.equal(await detail.count(), 0)
    }
    assert.deepEqual(reads, [commandPath, planPath, historyPath, commandPath, commandPath, planPath, historyPath])
    assert.deepEqual(writes, []); assert.deepEqual(unexpected, []); assert.deepEqual(errors, [])
    return { caseCount: state.case_count, failureCount: observations.filter((item) => item.status === 'failed').length,
      firstObservedHttpStatus: wire.response_status, reads, writes, unexpected, errors }
  } finally { if (releaseFault) releaseFault(); await context.close() }
}
;(async () => {
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  try {
    const results = []
    results.push(await run(browser, { theme: 'light', locale: 'en', width: 1280 }))
    results.push(await run(browser, { theme: 'dark', locale: 'zh', width: 390, cancelled: true }))
    results.push(await run(browser, { theme: 'light', locale: 'zh', width: 390, corrupt: true }))
    const setupPicker = await runSetupPicker(browser)
    const caseHistory = await runCaseHistory(browser)
    const report = { scope: 'Production Runs section, setup picker and real React Query with intercepted transport. Not real auth, full route, PG, Temporal, exweb or business gold.', results, setupPicker, caseHistory }
    fs.writeFileSync(path.join(output, 'browser-contract.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report, null, 2))
  } finally { await browser.close() }
})().catch((error) => { console.error(error.stack); process.exitCode = 1 })
