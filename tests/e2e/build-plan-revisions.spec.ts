import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'

async function enrichedGoal(request: APIRequestContext, source: string, documents: string) {
  // The fixed-source chain must work without legacy mutable context generation.
  const captured = await captureAnalysis(request, source, { materialize: false })
  const { owner, projectId, conversationId, invoke } = captured
  const image = await (await request.get(`${analysisApi}/v1/projects/${projectId}/system-image`, { headers: owner.headers })).json()
  const proposed = await invoke('system_image.build.plan', { source_manifest_id: image.source_manifest.manifest_id,
    objective: 'Enrich the original goal without transferring execution consent' })
  const planId = proposed.result.object_refs[0].slice('build_plan:'.length)
  const plan = await (await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`, { headers: owner.headers })).json()
  const fixed = { project_id: projectId, plan_id: planId, plan_digest: plan.plan_digest, target_baseline_id: image.baselines[0].id }
  const started = await request.post(`${analysisApi}/v1/agent-goals`, { headers: owner.headers, data: {
    conversation_id: conversationId, project_id: projectId, goal_template: 'system_image_build',
    title: 'Original source enrichment goal', summary: 'Retain original fixed input history', target_refs: [`build_plan:${planId}`],
    steps: [{ id: 'structure', title: 'Build source-pinned structure', phase: 'acting', status: 'pending',
      selected_tool_id: 'system_image.build.structure', tool_input_payload: fixed }],
  } })
  expect(started.ok()).toBeTruthy()
  const initial = await started.json()
  const resumed = await request.post(`${analysisApi}/v1/agent-goals/${initial.id}/resume`, { headers: owner.headers, data: { expected_goal: initial } })
  expect(resumed.ok()).toBeTruthy()
  const goal = await resumed.json()
  expect(goal.pause_reason).toBe('structural_candidate_review')
  const document = join(documents, 'requirements.md')
  writeFileSync(document, '# US-1 Archived controller\n\n## Acceptance criteria\n- Return the documented response.\n')
  await invoke('system_image.sources.register', { source_specs: [{ source_type: 'us_doc', source_uri: document }] })
  await invoke('system_image.sources.ingest')
  const updated = await (await request.get(`${analysisApi}/v1/projects/${projectId}/system-image`, { headers: owner.headers })).json()
  return { ...captured, planId, goal, newManifest: updated.source_manifest.manifest_id }
}

async function openRevision(page: Page, value: Awaited<ReturnType<typeof enrichedGoal>>) {
  await page.addInitScript((token) => {
    localStorage.setItem('nasus_api_token', token)
    localStorage.setItem('nasus.locale', 'en')
  }, value.owner.token)
  await page.goto(`/projects/${value.projectId}/knowledge`)
  await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
  await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(value.planId)
  await dialog.getByText('Revise with captured sources', { exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Original paused build goal' }).selectOption(value.goal.id)
  return dialog
}

async function saveDraftAndOpenPhase(page: Page, value: Awaited<ReturnType<typeof enrichedGoal>>) {
  const dialog = await openRevision(page, value)
  await dialog.getByRole('checkbox', { name: 'Save a revised draft without resuming or executing the goal', exact: true }).check()
  await dialog.getByRole('button', { name: 'Prepare plan revision', exact: true }).click()
  await dialog.getByRole('button', { name: 'Confirm plan revision', exact: true }).click()
  await expect(dialog.getByText('Draft only', { exact: false })).toBeVisible()
  await dialog.getByText('Continue with revised sources', { exact: true }).click()
  await expect(dialog.getByRole('checkbox', { name: 'Prepare the revised phase without executing it', exact: true })).toBeVisible()
  return dialog
}

for (const theme of ['light', 'dark']) {
  test(`revised phase preserves history and requires a separate execution gate in ${theme}`, async ({ page, request }) => {
    const source = analysisSource(), documents = mkdtempSync(join(tmpdir(), 'nasus-phase-documents-'))
    try {
      const value = await enrichedGoal(request, source, documents)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: value.owner.headers, data: { theme } })).ok()).toBeTruthy()
      const rootUrl = `${analysisApi}/v1/projects/${value.projectId}/system-image/build-plans/${value.planId}`
      const oldPlan = await (await request.get(rootUrl, { headers: value.owner.headers })).json()
      const dialog = await saveDraftAndOpenPhase(page, value)
      const consent = dialog.getByRole('checkbox', { name: 'Prepare the revised phase without executing it', exact: true })
      const prepare = dialog.getByRole('button', { name: 'Prepare revised phase', exact: true })
      await expect(prepare).toBeDisabled()
      await consent.check()
      await dialog.getByRole('spinbutton', { name: 'Active time limit (seconds)', exact: true }).fill('600')
      await expect(consent).not.toBeChecked()
      await consent.check()
      const proposed = page.waitForResponse((response) => response.url().endsWith('/v1/tool-invocations') && response.request().method() === 'POST')
      await prepare.click()
      const command = await (await proposed).json()
      expect(command.tool_id).toBe('system_image.build.plan.activate_revision')
      expect(command.status).toBe('waiting_confirmation')
      expect(command.input_payload.expected_goal).toEqual(value.goal)
      expect(command.input_payload.budget).toEqual({ max_tool_calls: 1, max_model_calls: 0, max_active_seconds: 600, max_cost_microusd: 0 })
      await page.setViewportSize({ width: 390, height: 844 })
      await consent.scrollIntoViewIfNeeded()
      expect(await consent.evaluate((element) => getComputedStyle(element).width)).toBe('16px')
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      await dialog.getByRole('button', { name: 'Confirm revised phase', exact: true }).click()
      await expect(dialog.getByText('Revised phase prepared. The goal is still paused.', { exact: true })).toBeVisible()
      const goalUrl = `${analysisApi}/v1/agent-goals/${value.goal.id}`
      const prepared = await (await request.get(goalUrl, { headers: value.owner.headers })).json()
      expect(prepared.id).toBe(value.goal.id)
      expect(prepared.pause_reason).toBe('build_plan_phase_prepared')
      expect(prepared.steps.slice(0, value.goal.steps.length)).toEqual(value.goal.steps)
      const phases = await (await request.get(`${rootUrl}/phases?goal_id=${value.goal.id}`, { headers: value.owner.headers })).json()
      expect(phases).toHaveLength(1)
      const revisedUrl = `${analysisApi}/v1/projects/${value.projectId}/system-image/build-plans/${phases[0].phase.plan_id}`
      const beforeExecution = await (await request.get(revisedUrl, { headers: value.owner.headers })).json()
      expect(beforeExecution.execution_authorizations).toEqual([])
      expect(beforeExecution.structural_artifacts).toEqual([])
      await dialog.getByRole('link', { name: 'Review execution confirmation', exact: true }).click()
      const gate = page.getByTestId('agent-confirmation-gate')
      await expect(gate.getByRole('button', { name: 'Continue revised phase', exact: true })).toBeVisible()
      await page.reload()
      await expect(gate.getByRole('button', { name: 'Continue revised phase', exact: true })).toBeVisible()
      await expect(page.getByTestId('agent-goal-explanation')).toContainText('Review the new build phase')
      const activePending = prepared.steps.slice(value.goal.steps.length).find((step: { status: string }) => step.status === 'pending')
      await expect(page.getByTestId('agent-current-step')).toHaveAttribute('data-step-id', activePending.id)
      const resumed = page.waitForResponse((response) => response.url().endsWith(`/agent-goals/${value.goal.id}/resume`) && response.request().method() === 'POST')
      await gate.getByRole('button', { name: 'Continue revised phase', exact: true }).click()
      const waiting = await (await resumed).json()
      expect(waiting.pause_reason).toBe('waiting_confirmation')
      expect(waiting.steps.slice(0, value.goal.steps.length)).toEqual(value.goal.steps)
      expect(waiting.steps.slice(value.goal.steps.length).filter((step: { status: string; selected_tool_id: string }) => step.status === 'blocked').map((step: { selected_tool_id: string }) => step.selected_tool_id)).toEqual(['system_image.build.authorize'])
      const activeGate = waiting.steps.slice(value.goal.steps.length).find((step: { status: string }) => step.status === 'blocked')
      await expect(page.getByTestId('agent-current-step')).toHaveAttribute('data-step-id', activeGate.id)
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('Structural builds: 1')
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('Model calls: 0')
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('600')
      const stillPending = await (await request.get(revisedUrl, { headers: value.owner.headers })).json()
      expect(stillPending.execution_authorizations).toEqual([])
      expect(stillPending.structural_artifacts).toEqual([])
      await page.reload()
      await expect(gate.getByRole('button', { name: 'Confirm and continue', exact: true })).toBeVisible()
      await gate.scrollIntoViewIfNeeded()
      expect(await gate.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      const bounds = await gate.boundingBox()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await gate.screenshot({ path: resolve(`output/playwright/image-plan-phase-${theme}-mobile-gate.png`) })
      const executed = page.waitForResponse((response) => response.url().endsWith(`/agent-goals/${value.goal.id}/resume`) && response.request().method() === 'POST')
      await gate.getByRole('button', { name: 'Confirm and continue', exact: true }).click()
      const finished = await (await executed).json()
      expect(finished.id).toBe(value.goal.id)
      expect(finished.pause_reason).toBe('structural_candidate_review')
      await expect(page.getByTestId('agent-goal-explanation')).toContainText('Review the structural candidate')
      expect(finished.steps.slice(0, value.goal.steps.length)).toEqual(value.goal.steps)
      expect(finished.model_calls_used).toBe(0)
      const revisedPlan = await (await request.get(revisedUrl, { headers: value.owner.headers })).json()
      expect(revisedPlan.execution_authorizations).toHaveLength(1)
      expect(revisedPlan.execution_authorizations[0].budget.max_active_seconds).toBe(600)
      expect(revisedPlan.structural_artifacts).toHaveLength(1)
      expect(await (await request.get(rootUrl, { headers: value.owner.headers })).json()).toEqual(oldPlan)
    } finally { rmSync(source, { recursive: true, force: true }); rmSync(documents, { recursive: true, force: true }) }
  })
}

test('lost phase confirmation acknowledgement hides controls and recovers the prepared phase without retry', async ({ page, request }) => {
  const source = analysisSource(), documents = mkdtempSync(join(tmpdir(), 'nasus-phase-lost-ack-'))
  try {
    const value = await enrichedGoal(request, source, documents)
    const dialog = await saveDraftAndOpenPhase(page, value)
    await dialog.getByRole('checkbox', { name: 'Prepare the revised phase without executing it', exact: true }).check()
    await dialog.getByRole('button', { name: 'Prepare revised phase', exact: true }).click()
    let confirmations = 0
    await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
      confirmations += 1
      expect((await (await route.fetch()).json()).status).toBe('completed')
      await route.abort('failed')
    })
    await dialog.getByRole('button', { name: 'Confirm revised phase', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    await expect(dialog.getByRole('button', { name: 'Confirm revised phase', exact: true })).toHaveCount(0)
    expect(confirmations).toBe(1)
    const prepared = await (await request.get(`${analysisApi}/v1/agent-goals/${value.goal.id}`, { headers: value.owner.headers })).json()
    expect(prepared.pause_reason).toBe('build_plan_phase_prepared')
    expect(prepared.steps.slice(0, value.goal.steps.length)).toEqual(value.goal.steps)
    await page.unroute('**/v1/tool-invocations/*/confirm')
    await dialog.getByRole('button', { name: 'Reload plans', exact: true }).click()
    await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(value.planId)
    await dialog.getByText('Revise with captured sources', { exact: true }).click()
    await dialog.getByRole('combobox', { name: 'Original paused build goal' }).selectOption(value.goal.id)
    await dialog.getByText('Continue with revised sources', { exact: true }).click()
    await expect(dialog.getByText('Revised phase prepared. The goal is still paused.', { exact: true })).toBeVisible()
    expect(confirmations).toBe(1)
  } finally { rmSync(source, { recursive: true, force: true }); rmSync(documents, { recursive: true, force: true }) }
})

for (const theme of ['light', 'dark']) {
  test(`same-goal plan revisions require explicit confirmation and preserve ${theme} mobile layout`, async ({ page, request }) => {
    const source = analysisSource(), documents = mkdtempSync(join(tmpdir(), 'nasus-plan-documents-'))
    try {
      const value = await enrichedGoal(request, source, documents)
      await request.patch(`${analysisApi}/v1/settings`, { headers: value.owner.headers, data: { theme } })
      const dialog = await openRevision(page, value)
      const checkbox = dialog.getByRole('checkbox', { name: 'Save a revised draft without resuming or executing the goal', exact: true })
      const prepare = dialog.getByRole('button', { name: 'Prepare plan revision', exact: true })
      await expect(prepare).toBeDisabled()
      await checkbox.check()
      const posted = page.waitForResponse((response) => response.url().endsWith('/v1/tool-invocations') && response.request().method() === 'POST')
      await prepare.click()
      const pending = await (await posted).json()
      expect(pending.status).toBe('waiting_confirmation')
      expect(pending.input_payload.expected_goal).toEqual(value.goal)
      expect(pending.input_payload.source_manifest_id).toBe(value.newManifest)
      const confirm = dialog.getByRole('button', { name: 'Confirm plan revision', exact: true })
      await expect(confirm).toBeEnabled()
      const confirmed = page.waitForResponse((response) => response.url().endsWith(`/tool-invocations/${pending.id}/confirm`))
      await confirm.click()
      expect((await (await confirmed).json()).status).toBe('completed')
      await expect(dialog.getByText('Draft only', { exact: false })).toBeVisible()
      await expect(prepare).toBeDisabled()
      const original = await request.get(`${analysisApi}/v1/agent-goals/${value.goal.id}`, { headers: value.owner.headers })
      expect(await original.json()).toEqual(value.goal)
      await page.setViewportSize({ width: 390, height: 844 })
      await checkbox.scrollIntoViewIfNeeded()
      expect(await checkbox.evaluate((element) => getComputedStyle(element).width)).toBe('16px')
      const body = dialog.locator('.evidence-inspector-body')
      expect(await body.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      expect(await body.evaluate((element) => getComputedStyle(element).scrollbarWidth)).toBe('none')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/build-plan-revisions-${theme}-mobile.png`) })
      await page.reload()
      await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
      await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(value.planId)
      await dialog.getByText('Revise with captured sources', { exact: true }).click()
      await dialog.getByRole('combobox', { name: 'Original paused build goal' }).selectOption(value.goal.id)
      await expect(dialog.getByText('Draft only', { exact: false })).toBeVisible()
      await expect(checkbox).not.toBeChecked()
    } finally { rmSync(source, { recursive: true, force: true }); rmSync(documents, { recursive: true, force: true }) }
  })
}

test('lost revision confirmation acknowledgement hides controls and never automatically retries', async ({ page, request }) => {
  const source = analysisSource(), documents = mkdtempSync(join(tmpdir(), 'nasus-plan-documents-'))
  try {
    const value = await enrichedGoal(request, source, documents)
    const dialog = await openRevision(page, value)
    await dialog.getByRole('checkbox', { name: 'Save a revised draft without resuming or executing the goal' }).check()
    await dialog.getByRole('button', { name: 'Prepare plan revision', exact: true }).click()
    let confirmations = 0
    await page.route('**/v1/tool-invocations/*/confirm', async (route) => {
      confirmations += 1
      const response = await route.fetch()
      expect((await response.json()).status).toBe('completed')
      await route.abort('failed')
    })
    await dialog.getByRole('button', { name: 'Confirm plan revision', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    await expect(dialog.getByRole('button', { name: 'Confirm plan revision', exact: true })).toHaveCount(0)
    expect(confirmations).toBe(1)
    await page.unroute('**/v1/tool-invocations/*/confirm')
    await dialog.getByRole('button', { name: 'Reload plans', exact: true }).click()
    await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(value.planId)
    await dialog.getByText('Revise with captured sources', { exact: true }).click()
    await dialog.getByRole('combobox', { name: 'Original paused build goal' }).selectOption(value.goal.id)
    await expect(dialog.getByText('Draft only', { exact: false })).toBeVisible()
    expect(confirmations).toBe(1)
    expect(await (await request.get(`${analysisApi}/v1/agent-goals/${value.goal.id}`, { headers: value.owner.headers })).json()).toEqual(value.goal)
  } finally { rmSync(source, { recursive: true, force: true }); rmSync(documents, { recursive: true, force: true }) }
})
