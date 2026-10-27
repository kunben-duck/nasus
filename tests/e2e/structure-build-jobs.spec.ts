import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'

function addCandidateTarget(projectId: string, versionId: string) {
  const database = process.env.NASUS_TEST_DATABASE_URL
  if (!database || database !== process.env.NASUS_E2E_DATABASE_URL) throw new Error('Isolated PostgreSQL is required')
  // This fixture adds a second existing target, not approval or an image head.
  execFileSync(resolve('.venv/bin/python'), ['-c', `
import os, sys
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.engine import make_url
from apps.api.app.infrastructure.persistence.db_models import BaselineRecord, VersionRecord
from apps.api.app.infrastructure.persistence.unit_of_work import session_scope
url = make_url(os.environ['NASUS_DATABASE_URL'])
assert url.get_backend_name() == 'postgresql' and url.host in {'localhost', '127.0.0.1', '::1'}
assert url.database.startswith('nasus_test_'), 'never change developer targets'
with session_scope() as session:
    original = session.scalar(select(BaselineRecord).where(BaselineRecord.project_id == sys.argv[1]))
    assert original is not None
    version = session.get(VersionRecord, sys.argv[2])
    assert version is not None and version.project_id == original.project_id
    session.add(BaselineRecord(id='browser-target-' + uuid4().hex, project_id=original.project_id,
        kind='version_working', status='draft', source_version_id=version.id,
        parent_baseline_id=original.id, fork_strategy='copy_on_write',
        object_count=0, relationship_count=0, metric_snapshot_count=0, updated_at=original.updated_at))
`, projectId, versionId], { env: { ...process.env, NASUS_DATABASE_URL: database }, stdio: 'pipe' })
}

// The API persists real candidates in isolated PostgreSQL. Only browser delivery
// is delayed here; real Temporal recovery is verified in the backend native test.
for (const theme of ['light', 'dark']) {
test(`structural command keeps its identity through lost acknowledgements and queued status (${theme})`, async ({ page, request }) => {
  const source = analysisSource()
  try {
    const { owner, projectId, invoke } = await captureAnalysis(request, source)
    const version = await invoke('version.create', { name: 'Structural browser target' })
    const versionId = version.result.object_refs.find((ref: string) => ref.startsWith('version:')).slice('version:'.length)
    addCandidateTarget(projectId, versionId)
    await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })
    const image = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image`, { headers: owner.headers })
    expect(image.ok()).toBeTruthy()
    const manifest = (await image.json()).source_manifest
    const draft = await invoke('system_image.build.plan', { source_manifest_id: manifest.manifest_id,
      objective: 'Browser structural lifecycle', purpose: 'structure', mode: 'initialize' })
    const planId = draft.result.object_refs.find((ref: string) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token)
      localStorage.setItem('nasus.locale', 'en')
    }, owner.token)
    const keys: string[] = [], ids: string[] = []
    let originalId = '', completed: Record<string, unknown> | null = null
    let releaseCompletion = false, failStatus = false, confirms = 0, statusReads = 0
    await page.route('**/v1/tool-invocations', async (route) => {
      const payload = route.request().postDataJSON()
      if (route.request().method() !== 'POST' || payload?.tool_id !== 'system_image.build.structure') return route.continue()
      expect(payload.idempotency_key).toBe(payload.input.idempotency_key)
      keys.push(payload.idempotency_key)
      const response = await route.fetch(), value = await response.json()
      ids.push(value.id); originalId = value.id
      if (keys.length === 1) return route.abort('failed')
      await route.fulfill({ response })
    })
    await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
      if (!route.request().url().endsWith(`/${originalId}/confirm`)) return route.continue()
      confirms++
      const response = await route.fetch()
      completed = await response.json()
      expect(completed!.status).toBe('completed')
      await route.fulfill({ response, json: { ...completed, status: 'running', result: null } })
    })
    await page.route('**/v1/tool-invocations/*', async (route) => {
      if (route.request().method() !== 'GET' || !route.request().url().endsWith(`/${originalId}`)) return route.continue()
      statusReads++
      if (failStatus) { failStatus = false; return route.fulfill({ status: 503, json: { detail: 'Held status read' } }) }
      if (completed && !releaseCompletion) return route.fulfill({ json: { ...completed, status: 'running', result: null } })
      await route.continue()
    })
    await page.goto(`/projects/${projectId}/knowledge`)
    await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
    await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(planId)
    const targets = dialog.getByRole('combobox', { name: 'Candidate target baseline' })
    const baseline = await targets.locator('option').nth(1).getAttribute('value')
    await targets.selectOption(baseline!)
    const prepare = dialog.getByRole('button', { name: 'Prepare structural build', exact: true })
    await prepare.click()
    await expect(dialog.getByRole('alert')).toContainText('Structural command was not acknowledged.')
    await expect(targets).toBeDisabled()
    await expect(prepare).toBeEnabled()
    await prepare.click()
    const confirm = dialog.getByRole('button', { name: 'Confirm structural build', exact: true })
    await expect(confirm).toBeEnabled()
    expect(keys).toHaveLength(2)
    expect(new Set(keys).size).toBe(1)
    expect(new Set(ids).size).toBe(1)
    // Discard every React ref and query cache; recover the pending command from PG.
    await page.reload()
    await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
    await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(planId)
    await expect(confirm).toBeEnabled()
    await expect(targets).toHaveValue(baseline!)
    await expect(targets).toBeDisabled()
    expect(keys).toHaveLength(2)
    expect(confirms).toBe(0)
    await confirm.click()
    await expect(dialog.getByRole('button', { name: 'Building structure...', exact: true })).toBeDisabled()
    await expect(dialog.getByRole('alert')).toHaveCount(0)
    await expect(targets).toBeDisabled()
    failStatus = true
    await expect(dialog.getByRole('alert')).toContainText('Structural command status could not be verified.')
    await expect(prepare).toBeDisabled()
    expect(confirms).toBe(1)
    const readsBeforeReload = statusReads
    await dialog.getByRole('button', { name: 'Reload structural status', exact: true }).click()
    await expect(dialog.getByRole('button', { name: 'Building structure...', exact: true })).toBeDisabled()
    expect(statusReads).toBeGreaterThan(readsBeforeReload)
    releaseCompletion = true
    await expect(dialog.getByRole('region', { name: 'Recent structural candidates' })).toContainText('Candidate only')
    await expect(targets).toBeEnabled()
    await expect(prepare).toBeEnabled()
    expect(keys).toHaveLength(2)
    expect(confirms).toBe(1)
    // A new acknowledged-terminal action may pick another target and obtain new consent.
    const options = await targets.locator('option').count()
    expect(options).toBeGreaterThan(2)
    await targets.selectOption({ index: 2 })
    await prepare.click()
    await expect(confirm).toBeEnabled()
    expect(keys).toHaveLength(3)
    expect(keys[2]).not.toBe(keys[0])
    expect(ids[2]).not.toBe(ids[0])
  } finally { rmSync(source, { recursive: true, force: true }) }
})
test(`structural discovery blocks new writes on failure and requires choosing among unfinished commands (${theme})`, async ({ page, request }) => {
  const source = analysisSource()
  try {
    const { owner, projectId, invoke } = await captureAnalysis(request, source)
    await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })
    const image = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image`, { headers: owner.headers })
    const manifest = (await image.json()).source_manifest
    const draft = await invoke('system_image.build.plan', { source_manifest_id: manifest.manifest_id,
      objective: 'Discover original pending commands', purpose: 'structure', mode: 'initialize' })
    const planId = draft.result.object_refs.find((ref: string) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
    const root = `${analysisApi}/v1/projects/${projectId}/system-image`
    const plan = await (await request.get(`${root}/build-plans/${planId}`, { headers: owner.headers })).json()
    const state = await (await request.get(`${root}`, { headers: owner.headers })).json()
    const target = state.baselines[0].id
    const commands: string[] = []
    for (let i = 0; i < 2; i++) {
      const key = crypto.randomUUID()
      const response = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: owner.headers, data: {
        tool_id: 'system_image.build.structure', idempotency_key: key,
        input: { project_id: projectId, plan_id: planId, plan_digest: plan.plan_digest, target_baseline_id: target, idempotency_key: key },
      } })
      expect(response.ok()).toBeTruthy()
      const command = await response.json()
      expect(command.status).toBe('waiting_confirmation')
      commands.push(command.id)
    }
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token)
      localStorage.setItem('nasus.locale', 'en')
    }, owner.token)
    let unavailable = true, writes = 0, confirms = 0
    await page.route('**/structure-commands?*', (route) => unavailable
      ? route.fulfill({ status: 503, json: { detail: 'Held discovery read' } }) : route.continue())
    await page.route('**/v1/tool-invocations', (route) => {
      if (route.request().method() === 'POST' && route.request().postDataJSON()?.tool_id === 'system_image.build.structure') writes++
      return route.continue()
    })
    await page.route('**/v1/tool-invocations/*/confirm', (route) => { confirms++; return route.continue() })
    await page.goto(`/projects/${projectId}/knowledge`)
    await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
    await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(planId)
    await expect(dialog.getByRole('alert')).toContainText('Structural command status could not be verified.')
    await expect(dialog.getByRole('button', { name: 'Prepare structural build', exact: true })).toBeDisabled()
    unavailable = false
    await dialog.getByRole('button', { name: 'Reload structural status', exact: true }).click()
    const choices = dialog.getByRole('combobox', { name: 'Unfinished structural command' })
    await expect(choices).toBeVisible()
    await expect(choices.locator('option')).toHaveCount(3)
    await expect(dialog.getByRole('button', { name: 'Prepare structural build', exact: true })).toBeDisabled()
    await choices.selectOption(commands[1])
    await expect(dialog.getByRole('button', { name: 'Confirm structural build', exact: true })).toBeEnabled()
    await expect(dialog.getByRole('combobox', { name: 'Candidate target baseline' })).toHaveValue(target)
    expect(writes).toBe(0)
    expect(confirms).toBe(0)
    await page.screenshot({ path: `output/playwright/structure-discovery-${theme}.png`, fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await dialog.getByRole('button', { name: 'Confirm structural build', exact: true }).scrollIntoViewIfNeeded()
    const bounds = await dialog.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
    expect(writes).toBe(0)
    expect(confirms).toBe(0)
    await page.screenshot({ path: `output/playwright/structure-discovery-${theme}-mobile.png`, fullPage: true })
  } finally { rmSync(source, { recursive: true, force: true }) }
})
test(`stopping a saved structural command needs fresh explicit consent and survives refresh (${theme})`, async ({ page, request }) => {
  const source = analysisSource()
  try {
    const { owner, projectId, invoke } = await captureAnalysis(request, source)
    await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })
    const root = `${analysisApi}/v1/projects/${projectId}/system-image`
    const state = await (await request.get(root, { headers: owner.headers })).json()
    const draft = await invoke('system_image.build.plan', { source_manifest_id: state.source_manifest.manifest_id,
      objective: 'Stop one original pending structural command', purpose: 'structure', mode: 'initialize' })
    const planId = draft.result.object_refs.find((ref: string) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
    const plan = await (await request.get(`${root}/build-plans/${planId}`, { headers: owner.headers })).json()
    const key = crypto.randomUUID()
    const pending = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: owner.headers, data: {
      tool_id: 'system_image.build.structure', idempotency_key: key,
      input: { project_id: projectId, plan_id: planId, plan_digest: plan.plan_digest,
        target_baseline_id: state.baselines[0].id, idempotency_key: key },
    } })
    expect(pending.ok()).toBeTruthy()
    const original = await pending.json()
    expect(original.status).toBe('waiting_confirmation')
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token)
      localStorage.setItem('nasus.locale', 'en')
    }, owner.token)
    let stopWrites = 0, confirms = 0, held = true
    await page.route('**/structure-commands/*/status?*', (route) => held
      ? route.fulfill({ status: 503, json: { detail: 'Held stop authority read' } }) : route.continue())
    await page.route('**/v1/tool-invocations', (route) => {
      if (route.request().method() === 'POST' && route.request().postDataJSON()?.tool_id === 'system_image.build.structure.cancel') {
        const payload = route.request().postDataJSON()
        expect(payload.input.original_invocation_id).toBe(original.id)
        expect(payload.idempotency_key).not.toBe(key)
        expect(payload.input.confirmed_by_user).toBeUndefined()
        stopWrites++
      }
      return route.continue()
    })
    await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
      expect(route.request().url()).not.toContain(`/${original.id}/confirm`)
      confirms++
      if (theme === 'light') {
        const response = await route.fetch()
        expect((await response.json()).status).toBe('completed')
        return route.abort('failed')
      }
      return route.continue()
    })
    const open = async () => {
      await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
      await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(planId)
      return dialog
    }
    await page.goto(`/projects/${projectId}/knowledge`)
    let dialog = await open()
    await expect(dialog.getByRole('alert')).toContainText('Stop outcome could not be verified.')
    await expect(dialog.getByRole('button', { name: 'Stop structural build', exact: true })).toBeDisabled()
    expect(stopWrites).toBe(0); expect(confirms).toBe(0)
    held = false
    await dialog.getByRole('button', { name: 'Reload stop status', exact: true }).click()
    const consent = dialog.getByRole('checkbox', { name: 'Confirm stopping this exact structural command', exact: true })
    await expect(consent).toBeEnabled()
    await consent.check()
    await expect(dialog.getByRole('button', { name: 'Stop structural build', exact: true })).toBeEnabled()
    // Consent is not durable execution authority and must not survive page reload.
    await page.reload()
    dialog = await open()
    await expect(consent).toBeVisible()
    await expect(consent).not.toBeChecked()
    await expect(dialog.getByRole('button', { name: 'Stop structural build', exact: true })).toBeDisabled()
    expect(stopWrites).toBe(0); expect(confirms).toBe(0)
    await page.setViewportSize({ width: 390, height: 844 })
    await consent.check()
    const bounds = await consent.boundingBox()
    expect(bounds!.width).toBe(16)
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
    await page.screenshot({ path: `output/playwright/structure-stop-consent-${theme}-mobile.png`, fullPage: true })
    await dialog.getByRole('button', { name: 'Stop structural build', exact: true }).click()
    await expect(dialog.getByRole('status').filter({ hasText: 'Structural build was cancelled.' })).toBeVisible()
    await expect(dialog.getByRole('alert')).toHaveCount(0)
    expect(stopWrites).toBe(1); expect(confirms).toBe(1)
    const final = await request.get(`${analysisApi}/v1/tool-invocations/${original.id}`, { headers: owner.headers })
    expect((await final.json()).status).toBe('cancelled')
    await page.screenshot({ path: `output/playwright/structure-stop-${theme}-mobile.png`, fullPage: true })
  } finally { rmSync(source, { recursive: true, force: true }) }
})
}
