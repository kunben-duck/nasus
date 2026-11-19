// Observe the real Portal without confirmation clicks, fixture insertion or cleanup.
import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import { chromium } from 'playwright'

const args = process.argv.slice(2), option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback
const id = option('--acceptance-id', '')
if (!/^[a-z0-9][a-z0-9-]{1,63}$/.test(id)) throw new Error('Choose the existing retained acceptance ID')
const directory = path.resolve('output/realworld', id)
const binding = JSON.parse(await fs.readFile(path.join(directory, 'acceptance.json'), 'utf8'))
const portal = new URL(binding.portal)
if (binding.schema !== 'nasus.realworld-retained-session.v1' || binding.acceptance_id !== id
    || portal.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(portal.hostname)
    || portal.username || portal.password || portal.pathname !== '/' || portal.search || portal.hash
    || !/^proj_[a-zA-Z0-9_-]{1,120}$/.test(binding.project_id) || !/^conv_[a-zA-Z0-9_-]{1,120}$/.test(binding.conversation_id)
    || typeof binding.project_name !== 'string' || !binding.project_name
    || binding.build_path !== '/build' || !Array.isArray(binding.source_commits) || binding.source_commits.length !== 2
    || !binding.source_commits.every(commit => /^[0-9a-f]{40}$/.test(commit))) throw new Error('Invalid retained session binding')
await fs.chmod(directory, 0o700)
const stateFile = path.join(directory, 'operator-state.private.json')
await fs.access(stateFile); await fs.chmod(stateFile, 0o600)
const observation = crypto.randomUUID(), artifactDir = path.resolve('output/playwright', id, observation)
await fs.mkdir(artifactDir, { recursive: true, mode: 0o700 })
const report = { schema: 'nasus.realworld-m3-retained-observation.v1', acceptance_id: id, observation_id: observation,
  observed_at: new Date().toISOString(), mode: 'retained', full_m3_verified: false, status: 'blocked',
  project_id: binding.project_id, conversation_id: binding.conversation_id, project_url: `${portal.origin}/projects/${binding.project_id}/knowledge`,
  build_url: `${portal.origin}${binding.build_path}`, source_commits: binding.source_commits,
  assertions: { project_visible: false, conversation_restored_after_refresh: false, source_confirmation_visible: false,
    structure_confirmation_visible: false },
  target_execution_verified: false, snapshots_restore_verified: false, data_deleted: false, confirmation_clicked: false,
  artifacts: [], limitations: ['observation_only_not_product_acceptance', 'each_formal_action_requires_human_confirmation',
    'live_scope_generation_not_verified', 'controlled_roles_and_snapshot_lifecycle_incomplete', 'formal_browser_runplan_incomplete'] }
const browser = await chromium.launch({ headless: !args.includes('--headed') })
try {
  const context = await browser.newContext({ storageState: stateFile })
  const page = await context.newPage()
  await page.goto(report.project_url)
  await page.getByText(binding.project_name, { exact: true }).first().waitFor()
  report.assertions.project_visible = true
  const projectScreenshot = path.join(artifactDir, 'project.png')
  await page.screenshot({ path: projectScreenshot, fullPage: true }); report.artifacts.push(projectScreenshot)
  await page.goto(report.build_url)
  const log = page.getByRole('log', { name: /构建对话|Build conversation/ })
  await log.getByText(binding.source_commits[1], { exact: false }).first().waitFor()
  await page.reload()
  await log.getByText(binding.source_commits[0], { exact: false }).first().waitFor()
  await log.getByText(binding.source_commits[1], { exact: false }).first().waitFor()
  await page.locator(`a[href="/projects/${binding.project_id}/knowledge"]`).first().waitFor()
  // Wait for the lazy Markdown renderer, not its unformatted Suspense fallback.
  await log.locator('li').filter({ hasText: binding.source_commits[1] }).first().waitFor()
  report.assertions.conversation_restored_after_refresh = true
  report.assertions.source_confirmation_visible = await page.getByRole('button', { name: /^(确认接入并构建|Confirm sources and build)$/ }).isVisible()
  const structureButton = page.getByTestId('build-goal-continue')
  report.assertions.structure_confirmation_visible = await structureButton.isVisible()
    && /^(确认并继续|Confirm and continue)$/.test(await structureButton.innerText())
    && await page.getByTestId('image-build-execution-budget').isVisible()
    && (await page.getByTestId('build-progress').innerText()).includes('Authorize Fixed Build Plan')
  report.stage = report.assertions.source_confirmation_visible ? 'source_confirmation'
    : report.assertions.structure_confirmation_visible ? 'structure_confirmation' : 'unclassified_observation'
  report.status = report.stage !== 'unclassified_observation' ? 'awaiting_human_confirmation' : 'observed_not_accepted'
  const buildScreenshot = path.join(artifactDir, 'build-after-refresh.png')
  await page.screenshot({ path: buildScreenshot, fullPage: true }); report.artifacts.push(buildScreenshot)
} catch (error) {
  // Browser errors can contain request headers, URLs or input values. Keep them out of reports.
  report.reason = error.name === 'TimeoutError' ? 'expected_project_or_conversation_not_visible' : 'portal_observation_failed'
} finally {
  await browser.close()
  const reportPath = path.join(directory, `observation-${observation}.json`)
  await fs.writeFile(reportPath, JSON.stringify(report, null, 2), { mode: 0o600, flag: 'wx' })
  console.log(JSON.stringify({ ...report, report_path: reportPath }, null, 2))
  process.exitCode = 2 // An observed retained project is not a completed HTTP + UI acceptance.
}
