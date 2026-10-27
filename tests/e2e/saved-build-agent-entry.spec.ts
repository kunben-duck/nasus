import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'

async function savedIntent(request: APIRequestContext, source: string) {
  const captured = await captureAnalysis(request, source, { materialize: false })
  const { owner, projectId, invoke } = captured
  const image = await (await request.get(`${analysisApi}/v1/projects/${projectId}/system-image`, { headers: owner.headers })).json()
  const targetResponse = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-targets/${image.baselines[0].id}`, { headers: owner.headers })
  expect(targetResponse.ok()).toBeTruthy()
  const target = await targetResponse.json()
  const command = await invoke('system_image.build.plan', { target, source_manifest_id: image.source_manifest.manifest_id,
    objective: 'Use the shared agent compiler with fixed inputs and separate consent' })
  const planId = command.result.object_refs[0].slice('build_plan:'.length)
  const planResponse = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`, { headers: owner.headers })
  expect(planResponse.ok()).toBeTruthy()
  return { ...captured, planId, target, plan: await planResponse.json() }
}

async function openEntry(page: Page, value: Awaited<ReturnType<typeof savedIntent>>) {
  await page.addInitScript((token) => {
    localStorage.setItem('nasus_api_token', token)
    localStorage.setItem('nasus.locale', 'en')
  }, value.owner.token)
  await page.goto(`/projects/${value.projectId}/knowledge`)
  await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
  await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(value.planId)
  const entry = dialog.getByTestId('saved-build-agent-entry')
  await expect(entry.getByRole('button', { name: 'Start from this saved plan', exact: true })).toBeHidden()
  await entry.getByText('Build with the agent', { exact: true }).click()
  return { dialog, entry }
}

for (const theme of ['light', 'dark']) {
  test(`saved plan starts one shared goal without execution consent in ${theme}`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const value = await savedIntent(request, source)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: value.owner.headers, data: { theme } })).ok()).toBeTruthy()
      const { entry } = await openEntry(page, value)
      const response = page.waitForResponse((response) => response.url().endsWith('/v1/agent-goals') && response.request().method() === 'POST')
      await entry.getByRole('button', { name: 'Start from this saved plan', exact: true }).click()
      const created = await response
      expect(created.ok()).toBeTruthy()
      const goal = await created.json()
      expect(goal.pause_reason).toBe('waiting_confirmation')
      expect(goal.target_refs).toEqual([`project:${value.projectId}`, `build_plan:${value.planId}`, `build_plan_digest:${value.plan.plan_digest}`])
      expect(created.request().postDataJSON().steps).toBeUndefined()
      expect(goal.steps.filter((step: { phase: string }) => step.phase === 'acting').map((step: { selected_tool_id: string }) => step.selected_tool_id))
        .toEqual(['query.system_image.build_plans.read', 'system_image.build.authorize', 'system_image.build.structure'])
      const current = await (await request.get(`${analysisApi}/v1/projects/${value.projectId}/system-image/build-plans/${value.planId}`, { headers: value.owner.headers })).json()
      expect(current.execution_authorizations).toEqual([])
      expect(current.structural_artifacts).toEqual([])
      await expect(entry.getByRole('status')).toContainText('Execution still requires separate confirmation.')
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await entry.screenshot({ path: resolve(`output/playwright/saved-build-entry-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      expect(await entry.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      await entry.screenshot({ path: resolve(`output/playwright/saved-build-entry-${theme}-mobile.png`) })
      await entry.getByRole('link', { name: 'Review execution confirmation', exact: true }).click()
      const gate = page.getByTestId('agent-confirmation-gate')
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('Structural builds: 1')
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('Model calls: 0')
      await expect(gate.getByRole('button', { name: 'Confirm and continue', exact: true })).toBeVisible()
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('lost start acknowledgement survives refresh and only reads the original conversation', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const value = await savedIntent(request, source)
    let posts = 0, originalGoal = ''
    page.on('request', (sent) => { if (sent.url().endsWith('/v1/agent-goals') && sent.method() === 'POST') posts++ })
    await page.route('**/v1/agent-goals', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      const created = await route.fetch()
      expect(created.ok()).toBeTruthy()
      const goal = await created.json()
      originalGoal = goal.id
      expect(goal.pause_reason).toBe('waiting_confirmation')
      await route.abort('failed')
    }, { times: 1 })
    const { entry } = await openEntry(page, value)
    await entry.getByRole('button', { name: 'Start from this saved plan', exact: true }).click()
    await expect(entry.getByRole('alert')).toContainText('no automatic retry was sent')
    expect(posts).toBe(1)
    await page.reload()
    await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
    await dialog.getByRole('combobox', { name: 'Saved investigation plan' }).selectOption(value.planId)
    const recovered = dialog.getByTestId('saved-build-agent-entry')
    await recovered.getByText('Build with the agent', { exact: true }).click()
    await expect(recovered.getByRole('button', { name: 'Start from this saved plan', exact: true })).toHaveCount(0)
    await recovered.getByRole('button', { name: 'Read existing build goal', exact: true }).click()
    await expect(recovered.getByRole('status')).toContainText('Execution still requires separate confirmation.')
    expect(posts).toBe(1)
    const goal = await (await request.get(`${analysisApi}/v1/agent-goals/${originalGoal}`, { headers: value.owner.headers })).json()
    expect(goal.pause_reason).toBe('waiting_confirmation')
    const plan = await (await request.get(`${analysisApi}/v1/projects/${value.projectId}/system-image/build-plans/${value.planId}`, { headers: value.owner.headers })).json()
    expect(plan.execution_authorizations).toEqual([])
    expect(plan.structural_artifacts).toEqual([])
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('two tabs keep one saved-plan goal and neither grants execution', async ({ page, request }) => {
  const source = analysisSource()
  const otherPage = await page.context().newPage()
  try {
    const value = await savedIntent(request, source)
    const first = await openEntry(page, value)
    const second = await openEntry(otherPage, value)
    const receipts = [page, otherPage].map((tab) => tab.waitForResponse((response) =>
      response.url().endsWith('/v1/agent-goals') && response.request().method() === 'POST'))
    await Promise.all([first, second].map(({ entry }) =>
      entry.getByRole('button', { name: 'Start from this saved plan', exact: true }).click()))
    const responses = await Promise.all(receipts)
    expect(responses.every((response) => response.ok())).toBe(true)
    const goals = await Promise.all(responses.map((response) => response.json()))
    expect(new Set(goals.map((goal) => goal.id)).size).toBe(1)
    for (const { entry } of [first, second]) {
      await expect(entry.getByRole('status')).toContainText('Execution still requires separate confirmation.')
      await expect(entry.getByRole('link', { name: 'Review execution confirmation', exact: true })).toBeVisible()
    }
    const conversation = await (await request.get(`${analysisApi}/v1/conversations/${goals[0].conversation_id}`,
      { headers: value.owner.headers })).json()
    expect(conversation.agent_goals.map((goal: { id: string }) => goal.id)).toEqual([goals[0].id])
    expect(conversation.agent_goals[0].pause_reason).toBe('waiting_confirmation')
    const plan = await (await request.get(`${analysisApi}/v1/projects/${value.projectId}/system-image/build-plans/${value.planId}`,
      { headers: value.owner.headers })).json()
    expect(plan.execution_authorizations).toEqual([])
    expect(plan.structural_artifacts).toEqual([])
  } finally {
    await otherPage.close()
    rmSync(source, { recursive: true, force: true })
  }
})

for (const kind of ['extra', 'duplicate']) {
  test(`a ${kind} target ref in the start acknowledgement requires read-only recovery`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const value = await savedIntent(request, source)
      let posts = 0, originalGoal = ''
      page.on('request', (sent) => { if (sent.url().endsWith('/v1/agent-goals') && sent.method() === 'POST') posts++ })
      // Alter only the wire acknowledgement, not the genuine persisted goal.
      await page.route('**/v1/agent-goals', async (route) => {
        if (route.request().method() !== 'POST') return route.continue()
        const created = await route.fetch()
        expect(created.ok()).toBeTruthy()
        const goal = await created.json()
        originalGoal = goal.id
        const refs = [...goal.target_refs, kind === 'extra' ? 'project:foreign' : goal.target_refs[0]]
        await route.fulfill({ response: created, json: { ...goal, target_refs: refs } })
      }, { times: 1 })
      const { entry } = await openEntry(page, value)
      await entry.getByRole('button', { name: 'Start from this saved plan', exact: true }).click()
      await expect(entry.getByRole('alert')).toContainText('no automatic retry was sent')
      await expect(entry.getByRole('link', { name: 'Review execution confirmation', exact: true })).toHaveCount(0)
      expect(posts).toBe(1)
      await entry.getByRole('button', { name: 'Read existing build goal', exact: true }).click()
      await expect(entry.getByRole('status')).toContainText('Execution still requires separate confirmation.')
      expect(posts).toBe(1)
      const goal = await (await request.get(`${analysisApi}/v1/agent-goals/${originalGoal}`, { headers: value.owner.headers })).json()
      expect(goal.pause_reason).toBe('waiting_confirmation')
      expect(goal.target_refs).toEqual([`project:${value.projectId}`, `build_plan:${value.planId}`, `build_plan_digest:${value.plan.plan_digest}`])
      const plan = await (await request.get(`${analysisApi}/v1/projects/${value.projectId}/system-image/build-plans/${value.planId}`, { headers: value.owner.headers })).json()
      expect(plan.execution_authorizations).toEqual([])
      expect(plan.structural_artifacts).toEqual([])
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

for (const theme of ['light', 'dark']) {
  test(`natural chat and saved-plan UI share one fixed goal and distinct consent in ${theme}`, async ({ page, request }) => {
    test.setTimeout(90_000)
    const source = analysisSource()
    try {
      const captured = await captureAnalysis(request, source, { materialize: false })
      const { projectId, owner, conversationId } = captured
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme } })).ok()).toBeTruthy()
      await page.addInitScript((token) => {
        localStorage.setItem('nasus_api_token', token)
        localStorage.setItem('nasus.locale', 'en')
      }, owner.token)
      await page.goto(`/projects/${projectId}`)
      const message = theme === 'light'
        ? 'Build the official system image from code, US docs, and tests'
        : '基于代码、需求文档和测试用例构建当前项目的系统画像。'
      await page.getByTestId('project-agent-input').fill(message)
      const accepted = page.waitForResponse((response) => response.url().endsWith(`/v1/conversations/${conversationId}/messages`)
        && response.request().method() === 'POST')
      await page.getByTestId('project-agent-submit').click()
      const acceptedResponse = await accepted
      expect(acceptedResponse.status()).toBe(202)
      expect(acceptedResponse.request().postDataJSON().content).toBe(message)
      expect(acceptedResponse.request().postDataJSON().canonical_action_id).toBeUndefined()
      const acceptedTurn = await acceptedResponse.json()
      // A 202 acknowledges the turn, not its asynchronous goal or confirmation.
      await expect.poll(async () => {
        const turn = await request.get(`${analysisApi}/v1/conversations/${conversationId}/turns/${acceptedTurn.turn_id}`,
          { headers: owner.headers })
        expect(turn.ok()).toBeTruthy()
        return (await turn.json()).status
      }, { timeout: 30_000 }).toBe('completed')
      const gate = page.getByTestId('agent-confirmation-gate')
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('Model calls: 0')
      const current = await (await request.get(`${analysisApi}/v1/conversations/${conversationId}`, { headers: owner.headers })).json()
      expect(current.agent_goals).toHaveLength(1)
      const original = current.agent_goals[0]
      expect(original.pause_reason).toBe('waiting_confirmation')
      expect(original.target_refs).toHaveLength(6)
      const planId = original.target_refs.find((ref: string) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
      const plan = await (await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`,
        { headers: owner.headers })).json()
      expect(plan.execution_authorizations).toEqual([])
      expect(plan.structural_artifacts).toEqual([])
      // The source is gone before consent; only the captured archive is usable.
      rmSync(source, { recursive: true, force: true })
      const value = { ...captured, planId, plan, target: plan.proposal.intent.target }
      const { entry } = await openEntry(page, value)
      const reused = page.waitForResponse((response) => response.url().endsWith('/v1/agent-goals') && response.request().method() === 'POST')
      await entry.getByRole('button', { name: 'Start from this saved plan', exact: true }).click()
      expect((await (await reused).json()).id).toBe(original.id)
      await expect(entry.getByRole('status')).toContainText('Execution still requires separate confirmation.')
      await entry.getByRole('link', { name: 'Review execution confirmation', exact: true }).click()
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('Structural builds: 1')
      await page.reload()
      await expect(gate.getByTestId('image-build-execution-budget')).toContainText('Model calls: 0')
      const path = `/v1/agent-goals/${original.id}/resume`
      const builtResponse = page.waitForResponse((response) => new URL(response.url()).pathname === path && response.request().method() === 'POST')
      await gate.getByRole('button', { name: 'Confirm and continue', exact: true }).click()
      const built = await (await builtResponse).json()
      expect(built.id).toBe(original.id)
      expect(built.pause_reason).toBe('structural_candidate_review')
      await expect(gate.getByRole('button', { name: 'Continue evidence investigation', exact: true })).toBeVisible()
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await gate.screenshot({ path: resolve(`output/playwright/natural-build-entry-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      expect(await gate.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      await gate.screenshot({ path: resolve(`output/playwright/natural-build-entry-${theme}-mobile.png`) })
      const finalPlan = await (await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`,
        { headers: owner.headers })).json()
      expect(finalPlan.structural_artifacts).toHaveLength(1)
      expect(finalPlan.execution_authorizations).toHaveLength(1)
      expect(finalPlan.execution_authorizations[0].publication_allowed).toBe(false)
      expect((await (await request.get(`${analysisApi}/v1/conversations/${conversationId}`, { headers: owner.headers })).json()).agent_goals)
        .toHaveLength(1)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('project chat waits for its original conversation before sending a build request', async ({ page, request }) => {
  test.setTimeout(90_000)
  const source = analysisSource()
  let release!: () => void, started!: () => void
  const held = new Promise<void>((resolve) => { release = resolve })
  const intercepted = new Promise<void>((resolve) => { started = resolve })
  try {
    const value = await captureAnalysis(request, source, { materialize: false })
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token)
      localStorage.setItem('nasus.locale', 'en')
    }, value.owner.token)
    await page.route('**/v1/conversations', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      expect(route.request().postDataJSON().space_id).toBe(value.projectId)
      started()
      await held
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      expect((await response.json()).id).toBe(value.conversationId)
      await route.fulfill({ response })
    }, { times: 1 })
    const posts: string[] = []
    page.on('request', (sent) => {
      if (sent.method() === 'POST' && new URL(sent.url()).pathname.endsWith('/messages')) posts.push(new URL(sent.url()).pathname)
    })
    await page.goto(`/projects/${value.projectId}`)
    await intercepted
    const input = page.getByTestId('project-agent-input'), send = page.getByTestId('project-agent-submit')
    await expect(input).toBeDisabled()
    await expect(send).toBeDisabled()
    expect(posts).toEqual([])
    release()
    await expect(input).toBeEnabled()
    await expect(send).toBeEnabled()
    await input.fill('构建系统画像')
    const accepted = page.waitForResponse((response) => new URL(response.url()).pathname ===
      `/v1/conversations/${value.conversationId}/messages` && response.request().method() === 'POST')
    await send.click()
    expect((await accepted).status()).toBe(202)
    expect(posts).toEqual([`/v1/conversations/${value.conversationId}/messages`])
    const image = await (await request.get(`${analysisApi}/v1/projects/${value.projectId}/system-image`,
      { headers: value.owner.headers })).json()
    expect(image.source_manifest.members.filter((member: { status: string; source_type: string }) =>
      member.status === 'captured' && member.source_type === 'code')).toHaveLength(1)
  } finally {
    release()
    rmSync(source, { recursive: true, force: true })
  }
})
