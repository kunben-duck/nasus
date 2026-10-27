const assert = require('node:assert/strict')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const { chromium } = require('playwright')
const ts = require('../../../apps/portal/node_modules/typescript')
const protocol = require('./protocol.cjs')
const repo = path.resolve(__dirname, '../../..'), output = path.join(repo, 'output/playwright')
const messages = { exports: {} }
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(repo, 'apps/portal/src/shared/i18n/messages.ts'), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, messages)
const results = []
const runTag = process.env.NASUS_BROWSER_CONTRACT_RUN ?? String(Date.now())
const origin = process.env.NASUS_BROWSER_CONTRACT_ORIGIN ?? 'http://127.0.0.1:4197'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)

async function eventually(check, description) {
  const end = Date.now() + 15000
  do { if (await check()) return; await new Promise((resolve) => setTimeout(resolve, 50)) } while (Date.now() < end)
  throw new Error('Browser contract did not converge: ' + description)
}
async function run(browser, { theme, locale, width, scenario }) {
  const context = await browser.newContext({ viewport: { width, height: 900 } }), page = await context.newPage()
  const egress = []
  await context.route('**/*', async (route) => {
    if (new URL(route.request().url()).origin === origin) return route.continue()
    egress.push(route.request().url()); await route.abort('blockedbyclient')
  })
  const label = (key) => locale === 'zh' ? messages.exports.zhCN[key] ?? key : key
  const button = (key) => page.getByRole('button', { name: label(key), exact: true })
  const enabled = (key, value = true) => eventually(async () => await button(key).count() === 1 && await button(key).isEnabled() === value, key)
  const visible = (key) => page.getByText(label(key), { exact: true }).waitFor({ state: 'visible' })
  const check = () => page.getByRole('checkbox').check()
  try {
    await protocol.install(page)
    await page.goto(`${origin}/tests/browser/http-fixture/index.html?theme=${theme}&locale=${locale}`)
    await button('Prepare or clean up test data').waitFor({ state: 'visible' })
    assert.equal(protocol.summary().reads, 0, 'Folded panel must perform no protected API reads')
    await button('Prepare or clean up test data').click()
    await page.getByRole('textbox', { name: label('Original environment command ID'), exact: true }).fill('environment-command')
    await page.getByRole('textbox', { name: label('Fixture attempt ID'), exact: true }).fill('browser-original-attempt')
    await button('Verify original environment for this operation').click()
    await enabled('Record independent fixture permission', false)
    assert.equal(protocol.state().reads.filter((url) => url.includes('/native-builds/')).length, 2, 'All original native build members must be verified')
    assert.equal(await page.getByRole('checkbox').isChecked(), false)

    if (scenario === 'lost-ack-cancel') {
      await check(); await enabled('Record independent fixture permission')
      await page.getByRole('spinbutton', { name: label('Operation timeout (ms)'), exact: true }).fill('11000')
      assert.equal(await page.getByRole('checkbox').count(), 0, 'Changed fields invalidate the exact prepared request')
      await button('Verify original environment for this operation').click(); await enabled('Record independent fixture permission', false)
      await check(); protocol.configure({ loseCreate: 'grant', denyResolve: true })
      await button('Record independent fixture permission').click()
      await page.getByRole('alert').first().waitFor({ state: 'visible' })
      assert.deepEqual(protocol.summary().writes, ['grant']); assert.deepEqual(protocol.summary().confirms, [])
      protocol.configure({ denyResolve: false })
      await enabled('Reload original fixture operation'); await button('Reload original fixture operation').click()
      await enabled('Confirm original fixture command', false)
      assert.equal(await page.getByRole('checkbox').isChecked(), false)
      await check(); await enabled('Confirm original fixture command'); await button('Confirm original fixture command').click()
      await enabled('Execute confirmed fixture operation', false)
      assert.deepEqual(protocol.summary().writes, ['grant']); assert.deepEqual(protocol.summary().confirms, ['grant'])
    } else {
      await check(); await enabled('Record independent fixture permission'); await button('Record independent fixture permission').click()
      await enabled('Execute confirmed fixture operation', false)
    }
    assert.equal(await page.getByRole('checkbox').isChecked(), false, 'Permission confirmation cannot authorize execution')
    await check(); await enabled('Execute confirmed fixture operation')
    if (scenario === 'lost-ack-cancel') protocol.configure({ loseConfirm: 'execute' })
    await button('Execute confirmed fixture operation').dblclick()
    if (scenario === 'lost-ack-cancel') {
      await eventually(async () => !await button('Reload original fixture operation').isDisabled(), 'unknown execute acknowledgement settled')
      await button('Reload original fixture operation').click()
    }
    await enabled('Cancel original fixture operation', false)
    await visible('The original command is still in preparation or stopped before binding. No target observation is recorded.')
    assert.deepEqual(protocol.summary().writes, ['grant', 'execute'], 'Double-click cannot create a second execution')
    assert.deepEqual(protocol.summary().confirms, ['grant', 'execute'])
    assert.equal(await page.getByRole('checkbox').isChecked(), false, 'Execution confirmation cannot authorize cancellation')
    const before = protocol.summary()
    await page.reload(); await button('Prepare or clean up test data').click()
    await enabled('Cancel original fixture operation', false)
    assert.deepEqual(protocol.summary().writes, before.writes); assert.deepEqual(protocol.summary().confirms, before.confirms)
    assert.equal(await button('Prepare the next independently confirmed operation').count(), 0)

    if (scenario === 'lost-ack-cancel') {
      await check(); await enabled('Cancel original fixture operation'); await button('Cancel original fixture operation').click()
      await visible('Cancellation is recorded and awaiting delivery. Do not start a replacement operation.')
      assert.equal(await button('Prepare the next independently confirmed operation').count(), 0)
      assert.deepEqual(protocol.summary().writes, ['grant', 'execute', 'cancel'])
      assert.deepEqual(protocol.summary().confirms, ['grant', 'execute', 'cancel'])
      await button('Reload original fixture operation').click()
      await visible('Cancellation is recorded and awaiting delivery. Do not start a replacement operation.')
      assert.equal(protocol.summary().writes.length, 3)
    } else if (scenario === 'completed-cleanup-revocation') {
      protocol.finishExecution(); await button('Reload original fixture operation').click()
      await enabled('Prepare the next independently confirmed operation')
      await page.getByTestId('original-fixture-operation').getByText('failed', { exact: true }).waitFor({ state: 'visible' })
      assert.equal(protocol.state().jobs.values().next().value.business_coverage_verified, false)
      await button('Prepare the next independently confirmed operation').click()
      assert.equal(await page.getByRole('textbox', { name: label('Fixture attempt ID'), exact: true }).inputValue(), 'browser-original-attempt')
      assert.equal(await page.getByRole('combobox', { name: label('Fixture operation'), exact: true }).inputValue(), 'cleanup')
      assert.equal(await page.getByRole('checkbox').count(), 0)
      assert.deepEqual(protocol.summary().writes, ['grant', 'execute'])
      await button('Verify original environment for this operation').click(); await enabled('Record independent fixture permission', false)
      assert.equal(await page.getByRole('checkbox').isChecked(), false)
      await page.getByRole('region', { name: label('Independent fixture operations') }).scrollIntoViewIfNeeded()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
      assert.equal(overflow, false, 'Narrow viewport must not overflow horizontally')
      await page.screenshot({ path: path.join(output, `fixture-operation-${theme}-${locale}-${width}-cleanup.png`), fullPage: true })
      protocol.configure({ revokeEnvironment: true })
      await button('Reload original fixture operation').click()
      await page.getByTestId('parent-protection').waitFor({ state: 'visible' })
      assert.equal(await page.getByTestId('original-fixture-grant').count(), 0)
      assert.deepEqual(protocol.summary().writes, ['grant', 'execute'], 'Revocation must not dispatch cleanup')
    } else {
      protocol.unknownExecution(); await button('Reload original fixture operation').click()
      await visible('This request has an unknown outcome. Automatic resending and new operation shortcuts are blocked.')
      await enabled('Cancel original fixture operation', false)
      assert.equal(await button('Prepare the next independently confirmed operation').count(), 0)
      await page.screenshot({ path: path.join(output, `fixture-operation-${theme}-${locale}-${width}-unknown.png`), fullPage: true })
      protocol.configure({ corruptJob: true }); await button('Reload original fixture operation').click()
      await page.getByTestId('parent-protection').waitFor({ state: 'visible' })
      assert.equal(await page.getByTestId('original-fixture-operation').count(), 0)
      assert.deepEqual(protocol.summary().writes, ['grant', 'execute'], 'Corrupt observations cannot trigger recovery writes or promote coverage')
    }
    assert.deepEqual(egress, [], 'No API, model or target request may leave the owned browser-contract origin')
    assert.equal(protocol.state().mutationErrors.length, scenario === 'lost-ack-cancel' ? 2 : 0,
      'Only the two intentionally lost acknowledgements may fail a mutation')
    await page.screenshot({ path: path.join(output, `fixture-operation-${theme}-${locale}-${width}-${scenario}.png`), fullPage: true })
    results.push({ theme, locale, width, scenario, ...protocol.summary() })
  } catch (error) {
    await page.screenshot({ path: path.join(output, `fixture-operation-${runTag}-${theme}-${locale}-${width}-FAILED.png`), fullPage: true }).catch(() => {})
    fs.writeFileSync(path.join(output, `fixture-operation-${runTag}-${theme}-${locale}-${width}-FAILED.txt`), `${error.stack}\n${await page.locator('body').innerText()}\n${JSON.stringify(protocol.summary(), null, 2)}\n${JSON.stringify(protocol.state().mutationErrors, null, 2)}`)
    throw error
  } finally { await context.close() }
}
;(async () => {
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  try {
    await run(browser, { theme: 'light', locale: 'en', width: 1280, scenario: 'lost-ack-cancel' })
    await run(browser, { theme: 'dark', locale: 'zh', width: 390, scenario: 'completed-cleanup-revocation' })
    await run(browser, { theme: 'light', locale: 'zh', width: 390, scenario: 'unknown-job-protection' })
    const report = { scope: 'Production component and real React Query with intercepted transport. Not full-route, PG, Temporal, exweb execution or business gold.', results }
    fs.writeFileSync(path.join(output, 'fixture-operation-browser-contract-20261013.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report, null, 2))
  } finally { await browser.close() }
})().catch((error) => { console.error(error); process.exitCode = 1 })
