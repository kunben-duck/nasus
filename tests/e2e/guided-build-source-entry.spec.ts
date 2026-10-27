import { expect, test } from '@playwright/test'
import { mkdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { randomUUID } from 'node:crypto'
import { analysisAccount, analysisApi, analysisSource } from './source-analysis-fixtures'

for (const [theme, locale] of [['light', 'en'], ['dark', 'zh']]) {
  test(`guided ${locale} code-only sources create one pinned candidate under independent consent in ${theme}`, async ({ page, request }) => {
    const source = analysisSource()
    try {
      const owner = await analysisAccount(request)
      const created = await request.post(`${analysisApi}/v1/projects`, { headers: owner.headers,
        data: { name: `Guided sources ${randomUUID()}` } })
      expect(created.ok()).toBeTruthy()
      const projectId = (await created.json()).id
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme, language: locale } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => {
        localStorage.setItem('nasus_api_token', token)
        localStorage.setItem('nasus.locale', locale)
      }, { token: owner.token, locale })
      const commands: string[] = []
      page.on('request', (sent) => {
        if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) commands.push(sent.postDataJSON().tool_id)
      })
      await page.goto(`/projects/${projectId}`)
      await page.getByTestId('agent-card-system-image-builder').click()
      const panel = page.getByTestId('source-binding-panel')
      await expect(panel).toBeVisible()
      const conversationList = await (await request.get(`${analysisApi}/v1/conversations?space_type=project&space_id=${projectId}`,
        { headers: owner.headers })).json()
      const originalConversationId = conversationList[0].id
      await expect.poll(async () => {
        const state = await (await request.get(`${analysisApi}/v1/conversations/${originalConversationId}`, { headers: owner.headers })).json()
        return state.agent_goals[0]?.pause_reason
      }).toBe('missing_captured_code')
      const initial = await (await request.get(`${analysisApi}/v1/conversations/${originalConversationId}`, { headers: owner.headers })).json()
      const waiting = initial.agent_goals[0]
      expect(waiting.active_runtime_ms).toBeGreaterThanOrEqual(0)
      expect(waiting.active_started_at).toBeNull()
      expect(waiting.target_refs).toHaveLength(3)
      const explanation = page.getByTestId('agent-goal-explanation')
      await expect(explanation).toContainText(locale === 'en' ? 'Waiting for captured code' : '等待采集代码')
      await expect(explanation).toContainText(locale === 'en' ? 'confirm the structural budget separately' : '单独确认结构分析预算')
      await expect(page.getByTestId('confirm-agent-goal')).toHaveCount(0)
      await panel.getByTestId('source-code-input').fill(source)
      await panel.getByTestId('source-us-input').fill('')
      await panel.getByTestId('source-tests-input').fill('')
      await panel.getByTestId('build-system-image-with-sources').click()
      await expect(panel.getByTestId('build-system-image-with-sources')).toBeDisabled()
      const gate = page.getByTestId('agent-confirmation-gate')
      // Acquisition and the asynchronous turn finish before the budget gate exists.
      await expect(gate.getByTestId('image-build-execution-budget')).toBeVisible({ timeout: 30_000 })
      const conversations = await (await request.get(`${analysisApi}/v1/conversations?space_type=project&space_id=${projectId}`,
        { headers: owner.headers })).json()
      const conversationId = conversations[0].id
      const current = await (await request.get(`${analysisApi}/v1/conversations/${conversationId}`, { headers: owner.headers })).json()
      expect(current.agent_goals).toHaveLength(1)
      const goal = current.agent_goals[0]
      expect(goal.pause_reason).toBe('waiting_confirmation')
      expect(goal.id).toBe(waiting.id)
      expect(goal.started_at).toBe(waiting.started_at)
      expect(goal.active_runtime_ms).toBeGreaterThanOrEqual(waiting.active_runtime_ms)
      expect(goal.active_started_at).toBeNull()
      expect(conversationId).toBe(originalConversationId)
      expect(goal.target_refs).toHaveLength(7)
      expect(goal.target_refs).toContain(waiting.target_refs[2])
      const originalRead = goal.steps.find((step: { selected_tool_id: string }) => step.selected_tool_id === 'query.system_image.status')
      const waitingRead = waiting.steps.find((step: { selected_tool_id: string }) => step.selected_tool_id === 'query.system_image.status')
      expect(originalRead.tool_invocation_id).toBe(waitingRead.tool_invocation_id)
      expect(originalRead.tool_input_payload).toEqual(waitingRead.tool_input_payload)
      const planId = goal.target_refs.find((ref: string) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
      const planUrl = `${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`
      const before = await (await request.get(planUrl, { headers: owner.headers })).json()
      expect(before.proposal.intent.sources).toHaveLength(1)
      expect(before.proposal.intent.sources[0].source_type).toBe('code')
      expect(before.structural_artifacts).toEqual([])
      expect(before.execution_authorizations).toEqual([])
      expect(commands).toEqual(['system_image.sources.register', 'system_image.sources.ingest'])
      rmSync(source, { recursive: true, force: true })
      const resumeFinished = page.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().endsWith(`/v1/agent-goals/${goal.id}/resume`))
      await gate.getByTestId('confirm-agent-goal').click()
      const resumed = await resumeFinished
      expect(resumed.status()).toBe(200)
      expect((await resumed.json()).pause_reason).toBe('structural_candidate_review')
      await expect(gate.getByTestId('continue-structural-investigation')).toBeVisible()
      await expect(explanation).toContainText(locale === 'en' ? 'Review the structural candidate' : '审阅结构候选')
      await expect(explanation).toContainText(locale === 'en' ? 'Confirm the investigation budget separately' : '调查预算需单独确认')
      const after = await (await request.get(planUrl, { headers: owner.headers })).json()
      expect(after.structural_artifacts).toHaveLength(1)
      expect(after.execution_authorizations).toHaveLength(1)
      expect(after.execution_authorizations[0].goal_id).toBe(goal.id)
      expect(after.execution_authorizations[0].publication_allowed).toBe(false)
      expect(after.execution_authorizations[0].budget.max_model_calls).toBe(0)
      const pinned = await (await request.get(`${analysisApi}/v1/conversations/${conversationId}`, { headers: owner.headers })).json()
      expect(pinned.agent_goals).toHaveLength(1)
      expect(pinned.agent_goals[0].id).toBe(goal.id)
      expect(pinned.agent_goals[0].pause_reason).toBe('structural_candidate_review')
      expect(pinned.agent_goals[0].active_runtime_ms).toBeGreaterThanOrEqual(goal.active_runtime_ms)
      expect(pinned.agent_goals[0].active_started_at).toBeNull()
      await panel.getByTestId('build-system-image-with-sources').click()
      await expect(panel.getByRole('alert')).toContainText(locale === 'en' ? 'already has fixed sources' : '已固定资料版本')
      expect(commands).toEqual(['system_image.sources.register', 'system_image.sources.ingest'])
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await gate.screenshot({ path: resolve(`output/playwright/guided-source-entry-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      await gate.screenshot({ path: resolve(`output/playwright/guided-source-entry-${theme}-mobile.png`) })
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}
