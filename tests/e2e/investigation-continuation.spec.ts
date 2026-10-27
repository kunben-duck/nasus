import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource } from './source-analysis-fixtures'
import { originalStructuralGoal, openInvestigationProject as openProject, type InvestigationGoal as Goal } from './investigation-goal-fixtures'

for (const theme of ['light', 'dark']) {
  test(`the original goal uses distinct continuation and confirmation gates in ${theme}`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const value = await originalStructuralGoal(request, source)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: value.owner.headers, data: { theme } })).ok()).toBeTruthy()
      const gate = await openProject(page, value.projectId, value.owner.token)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await expect(gate.getByRole('button', { name: 'Continue evidence investigation', exact: true })).toBeVisible()
      await expect(gate).toContainText('A separate confirmation follows')
      await expect(gate.getByTestId('confirm-agent-goal')).toHaveCount(0)
      await expect(page.getByTestId('agent-goal-explanation')).toContainText('Review the structural candidate')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await gate.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/investigation-continuation-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      await gate.scrollIntoViewIfNeeded()
      expect(await gate.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      const bounds = await gate.boundingBox()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
      await gate.screenshot({ path: resolve(`output/playwright/investigation-continuation-${theme}-mobile-gate.png`) })
      await page.screenshot({ path: resolve(`output/playwright/investigation-continuation-${theme}-mobile.png`) })

      const continued = page.waitForResponse((response) => new URL(response.url()).pathname === value.resumePath && response.request().method() === 'POST')
      await gate.getByTestId('continue-structural-investigation').click()
      const pending = await (await continued).json() as Goal
      expect(pending.id).toBe(value.goal.id)
      expect(pending.pause_reason).toBe('waiting_confirmation')
      const blocked = pending.steps.find((step) => step.phase === 'acting' && step.status === 'blocked')!
      expect(blocked.selected_tool_id).toBe('system_image.build.investigate')
      expect(blocked.tool_input_payload.goal_id).toBe(value.goal.id)
      expect(pending.steps.find((step) => step.selected_tool_id === 'system_image.build.structure')!.tool_invocation_id).toBe(value.structureId)
      await expect(gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true })).toBeVisible()
      await page.reload()
      await expect(gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true })).toBeVisible()
      expect((await value.read()).steps.find((step) => step.status === 'blocked')!.tool_invocation_id).toBe(blocked.tool_invocation_id)

      const confirmed = page.waitForResponse((response) => new URL(response.url()).pathname === value.resumePath && response.request().method() === 'POST')
      await gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true }).click()
      const reviewed = await (await confirmed).json() as Goal
      expect(reviewed.id).toBe(value.goal.id)
      expect(reviewed.status).toBe('paused')
      expect(reviewed.pause_reason).toBe('build_completion_review')
      expect(reviewed.model_calls_used).toBe(0)
      expect(reviewed.steps.filter((step) => step.phase === 'acting').every((step) => step.status === 'completed')).toBe(true)
      await expect(gate).toContainText('This is not a completed or published system image.')
      await expect(page.getByTestId('agent-goal-explanation')).toContainText('Review findings before publication')
      await expect(page.getByTestId('agent-goal-explanation')).toContainText('Publication requires an independent review and approval')
      await expect(gate.getByRole('button')).toHaveCount(0)
      const command = await request.get(`${analysisApi}/v1/tool-invocations/${blocked.tool_invocation_id}`, { headers: value.owner.headers })
      expect(command.ok()).toBeTruthy()
      const revisionId = (await command.json()).result.investigation.revision_id
      const report = await request.get(`${analysisApi}/v1/projects/${value.projectId}/system-image/build-investigations/${revisionId}`, { headers: value.owner.headers })
      expect(report.ok()).toBeTruthy()
      expect(report.headers()['cache-control']).toBe('private, no-store')
      const saved = await report.json()
      expect(saved.request.goal_id).toBe(value.goal.id)
      const actual = reviewed.steps.filter((step) => step.phase === 'acting').slice(3)
      expect(actual.map((step) => step.selected_tool_id)).toEqual(saved.review.work_items.map((task: { tool_id: string }) => task.tool_id))
      await page.reload()
      await expect(gate).toContainText('This is not a completed or published system image.')
      expect((await value.read()).steps.map((step) => step.tool_invocation_id)).toEqual(reviewed.steps.map((step) => step.tool_invocation_id))
      await gate.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/investigation-review-${theme}-mobile.png`) })
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('a lost continuation acknowledgement re-reads the goal without confirming its next command', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const value = await originalStructuralGoal(request, source)
    const gate = await openProject(page, value.projectId, value.owner.token)
    let posts = 0
    page.on('request', (sent) => { if (new URL(sent.url()).pathname === value.resumePath && sent.method() === 'POST') posts += 1 })
    await page.route(`**${value.resumePath}`, async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      expect(route.request().postDataJSON()).toEqual({ expected_goal: value.goal })
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      expect((await response.json()).pause_reason).toBe('waiting_confirmation')
      await route.abort('failed')
    }, { times: 1 })
    await gate.getByTestId('continue-structural-investigation').click()
    await expect(gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true })).toBeVisible()
    const pending = await value.read()
    expect(pending.pause_reason).toBe('waiting_confirmation')
    const commandId = pending.steps.find((step) => step.status === 'blocked')!.tool_invocation_id
    const command = await request.get(`${analysisApi}/v1/tool-invocations/${commandId}`, { headers: value.owner.headers })
    const stored = await command.json()
    expect(stored.status).toBe('waiting_confirmation')
    expect(stored.input_payload.confirmed_by_user).toBeUndefined()
    expect(stored.result).toBeNull()
    expect(posts).toBe(1)
    await page.reload()
    await expect(gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true })).toBeVisible()
    expect(posts).toBe(1)
    const confirmed = page.waitForResponse((response) => new URL(response.url()).pathname === value.resumePath && response.request().method() === 'POST')
    await gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true }).click()
    expect((await (await confirmed).json()).pause_reason).toBe('build_completion_review')
    expect(posts).toBe(2)
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('a held auxiliary project refresh does not lock a recovered investigation checkpoint', async ({ page, request }) => {
  const source = analysisSource()
  let releaseProject: () => void = () => {}
  const projectRefresh = new Promise<void>((resolve) => { releaseProject = resolve })
  try {
    const value = await originalStructuralGoal(request, source)
    const gate = await openProject(page, value.projectId, value.owner.token)
    await expect(gate.getByTestId('continue-structural-investigation')).toBeEnabled()
    let heldReads = 0, posts = 0
    page.on('request', (sent) => {
      if (new URL(sent.url()).pathname === value.resumePath && sent.method() === 'POST') posts += 1
    })
    await page.route(`**/v1/projects/${value.projectId}`, async (route) => {
      if (route.request().method() === 'GET') {
        heldReads += 1
        await projectRefresh
      }
      await route.continue()
    })
    await page.route(`**${value.resumePath}`, async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      expect(route.request().postDataJSON()).toEqual({ expected_goal: value.goal })
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      expect((await response.json()).pause_reason).toBe('waiting_confirmation')
      await route.abort('failed')
    }, { times: 1 })
    await gate.getByTestId('continue-structural-investigation').click()
    const confirm = gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true })
    await expect(confirm).toBeEnabled()
    await expect.poll(() => heldReads).toBeGreaterThan(0)
    const pending = await value.read()
    expect(pending.id).toBe(value.goal.id)
    expect(pending.pause_reason).toBe('waiting_confirmation')
    const blocked = pending.steps.find((step) => step.status === 'blocked')!
    expect(blocked.selected_tool_id).toBe('system_image.build.investigate')
    const stored = await request.get(`${analysisApi}/v1/tool-invocations/${blocked.tool_invocation_id}`, { headers: value.owner.headers })
    expect(stored.ok()).toBeTruthy()
    const command = await stored.json()
    expect(command.status).toBe('waiting_confirmation')
    expect(command.input_payload.confirmed_by_user).toBeUndefined()
    expect(command.result).toBeNull()
    expect(posts).toBe(1)

    // The independent user confirmation also completes while auxiliary reads remain held.
    const confirmed = page.waitForResponse((response) => new URL(response.url()).pathname === value.resumePath
      && response.request().method() === 'POST')
    await confirm.click()
    expect((await (await confirmed).json()).pause_reason).toBe('build_completion_review')
    await expect(gate).toContainText('This is not a completed or published system image.')
    await expect(gate.getByRole('button')).toHaveCount(0)
    expect(posts).toBe(2)
    releaseProject()
    await page.unrouteAll({ behavior: 'wait' })
  } finally {
    releaseProject()
    rmSync(source, { recursive: true, force: true })
  }
})

test('a goal change between the browser read and POST rejects the original displayed checkpoint', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const value = await originalStructuralGoal(request, source)
    const gate = await openProject(page, value.projectId, value.owner.token)
    await expect(gate.getByTestId('continue-structural-investigation')).toBeVisible()
    let changed: Goal | undefined
    await page.route(`**${value.resumePath}`, async (route) => {
      expect(route.request().method()).toBe('POST')
      expect(route.request().postDataJSON()).toEqual({ expected_goal: value.goal })
      const response = await request.patch(`${analysisApi}/v1/agent-goals/${value.goal.id}/budget`, {
        headers: value.owner.headers, data: { max_steps: value.goal.max_steps + 1 },
      })
      expect(response.ok()).toBeTruthy()
      changed = await response.json() as Goal
      await route.continue()
    }, { times: 1 })
    const rejected = page.waitForResponse((response) => new URL(response.url()).pathname === value.resumePath
      && response.request().method() === 'POST')
    await gate.getByTestId('continue-structural-investigation').click()
    const response = await rejected
    expect(response.status()).toBe(409)
    expect((await response.json()).error.code).toBe('agent_checkpoint_changed')
    expect(await value.read()).toEqual(changed)
    expect(changed!.pause_reason).toBe('structural_candidate_review')
    expect(changed!.steps.some((step) => step.selected_tool_id === 'system_image.build.investigate')).toBe(false)
    await page.reload()
    await expect(gate.getByTestId('continue-structural-investigation')).toBeEnabled()
    const continued = page.waitForResponse((next) => new URL(next.url()).pathname === value.resumePath
      && next.request().method() === 'POST')
    await gate.getByTestId('continue-structural-investigation').click()
    const fresh = await continued
    expect(fresh.request().postDataJSON()).toEqual({ expected_goal: changed })
    expect(fresh.ok()).toBeTruthy()
    expect((await fresh.json()).pause_reason).toBe('waiting_confirmation')
    await expect(gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true })).toBeVisible()
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('chat confirms only the exact pending investigation and keeps the same original goal', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const value = await originalStructuralGoal(request, source)
    const continued = await request.post(`${analysisApi}${value.resumePath}`, {
      headers: value.owner.headers, data: { expected_goal: value.goal },
    })
    expect(continued.ok()).toBeTruthy()
    const pending = await continued.json() as Goal
    expect(pending.pause_reason).toBe('waiting_confirmation')
    const commandId = pending.steps.find((step) => step.phase === 'acting' && step.status === 'blocked')!.tool_invocation_id
    const gate = await openProject(page, value.projectId, value.owner.token)
    await expect(gate.getByRole('button', { name: 'Confirm evidence investigation', exact: true })).toBeVisible()
    let browserResumePosts = 0
    page.on('request', (sent) => {
      if (new URL(sent.url()).pathname === value.resumePath && sent.method() === 'POST') browserResumePosts += 1
    })
    await page.getByTestId('project-agent-input').fill(`confirm ${commandId}`)
    const submitted = page.waitForResponse((response) => new URL(response.url()).pathname
      === `/v1/conversations/${value.conversationId}/messages` && response.request().method() === 'POST')
    await page.getByTestId('project-agent-submit').click()
    const accepted = await submitted
    expect(accepted.status()).toBe(202)
    expect(accepted.request().postDataJSON().content).toBe(`confirm ${commandId}`)
    await expect(gate).toContainText('This is not a completed or published system image.')
    const final = await value.read()
    expect(final.id).toBe(value.goal.id)
    expect(final.pause_reason).toBe('build_completion_review')
    expect(final.steps.find((step) => step.selected_tool_id === 'system_image.build.structure')!.tool_invocation_id).toBe(value.structureId)
    expect(final.steps.find((step) => step.selected_tool_id === 'system_image.build.investigate')!.tool_invocation_id).toBe(commandId)
    expect(browserResumePosts).toBe(0)
    const stored = await request.get(`${analysisApi}/v1/tool-invocations/${commandId}`, { headers: value.owner.headers })
    expect(stored.ok()).toBeTruthy()
    expect((await stored.json()).status).toBe('completed')
    await page.reload()
    await expect(gate).toContainText('This is not a completed or published system image.')
    expect((await value.read()).id).toBe(value.goal.id)
    expect(browserResumePosts).toBe(0)
  } finally { rmSync(source, { recursive: true, force: true }) }
})
