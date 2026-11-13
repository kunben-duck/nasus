import { expect, test } from '@playwright/test'
import { createServer } from 'node:http'
import { rmSync } from 'node:fs'
import { analysisAccount, analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'
import { frozenRevisions } from './image-revision-fixtures'

// A named HTTP provider fixture tests the real UI/API/persistence chain. Live
// semantic quality is separately verified by verify:realworld-m2.
for (const theme of ['light', 'dark']) test(`M2 review, clarify and independent confirmation (${theme})`, async ({ page, request, browser }) => {
  test.setTimeout(240_000)
  let calls = 0
  const server = createServer(async (req, res) => {
    const chunks: Buffer[] = []
    for await (const chunk of req) chunks.push(Buffer.from(chunk))
    const body = JSON.parse(Buffer.concat(chunks).toString()), text = body.messages?.find((m: { role: string }) => m.role === 'user')?.content ?? ''
    let content = 'OK'
    if (text.includes('"requirement_hash"')) {
      const payload = JSON.parse(text.split('Conversation input:\n')[1].split('\n\nWorkspace context:')[0])
      const ref = payload.evidence[0].ref, answered = payload.evidence.some((item: { kind: string }) => item.kind === 'user_answer')
      calls++
      content = JSON.stringify({ summary: 'Explicit browser provider fixture',
        checks: ['roles', 'preconditions', 'inputs_outputs', 'errors', 'verifiability', 'conflicts'].map((dimension) => ({ dimension, assessment: 'Fixture check', refs: [ref] })),
        questions: answered ? [] : [{ question: 'Who may edit the article?', rationale: 'The role is not defined.', blocking: true, refs: [ref] }],
        suggestions: ['Specify who owns the article.'], criteria: [{ title: 'Reject another user', refs: [ref], oracle: {
          preconditions: 'Article belongs to A', action: 'B updates it', observation: 'Response and readback', expected_result: '403 and no change',
        } }] })
    }
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content }, finish_reason: 'stop' }], usage: { prompt_tokens: 100, completion_tokens: 100 } }))
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Provider fixture did not bind')
  const admin = { Authorization: `Bearer ${process.env.NASUS_E2E_ADMIN_TOKEN ?? 'nasus-e2e-platform-admin-token'}` }
  const old = await (await request.get(`${analysisApi}/v1/settings/model-configs?route=chat`, { headers: admin })).json()
  const source = analysisSource()
  try {
    const config = { model_route: 'chat', display_name: `M2 ${theme} fixture`, custom_provider_kind: 'openai_compatible',
      custom_base_url: `http://127.0.0.1:${address.port}/v1`, custom_model_name: `m2-${theme}-fixture`, custom_api_key: 'explicit-local-test-key' }
    const connection = await (await request.post(`${analysisApi}/v1/settings/model-configs/test`, { headers: admin, data: config })).json()
    expect(connection.ok).toBe(true)
    const saved = await request.post(`${analysisApi}/v1/settings/model-configs`, { headers: admin, data: { ...config, test_token: connection.test_token } })
    expect(saved.ok()).toBe(true)
    const settings = await saved.json()
    const model = settings.model_configurations.chat.configurations.find((item: { model_name: string }) => item.model_name === config.custom_model_name)
    expect((await request.post(`${analysisApi}/v1/settings/model-configs/${model.config_id}/activate`, { headers: admin })).ok()).toBe(true)
    await request.patch(`${analysisApi}/v1/settings`, { headers: admin, data: { theme } })
    const v = await captureAnalysis(request, source), reviewer = await analysisAccount(request)
    expect((await request.put(`${analysisApi}/v1/projects/${v.projectId}/members/${reviewer.userId}`, { headers: v.owner.headers, data: { role: 'project_admin' } })).ok()).toBe(true)
    const image = (await frozenRevisions(request, v.projectId, v.owner.headers))[0]
    const root = `${analysisApi}/v1/projects/${v.projectId}/system-image/publications`
    const params = { image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash, target_baseline_id: image.baseline_id }
    const preview = await (await request.get(`${root}/preview`, { headers: v.owner.headers, params })).json()
    const review = await v.invoke('system_image.revisions.review_publication', { ...preview.target,
      expected_preview_digest: preview.preview_digest, expected_review_id: null, decision: 'approve', reason: 'Fixture publication review' }, 'waiting_confirmation')
    expect((await (await request.post(`${analysisApi}/v1/tool-invocations/${review.id}/confirm`, { headers: v.owner.headers })).json()).status).toBe('completed')
    const approved = await (await request.get(`${root}/preview`, { headers: v.owner.headers, params })).json()
    await v.invoke('baseline.promote', { ...approved.target, expected_preview_digest: approved.preview_digest, approval_id: approved.review.review_id })
    const { head } = await (await request.get(root, { headers: v.owner.headers, params: { baseline_id: image.baseline_id } })).json()
    const creation = await v.invoke('version.create', { name: 'M2 browser sprint', image_binding: {
      publication_id: head.publication_id, image_revision_id: image.image_revision_id, image_artifact_hash: image.artifact_hash, expected_head_id: head.publication_id } })
    const version = creation.result.object_refs.find((ref: string) => ref.startsWith('version:')).slice(8)
    await page.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, v.owner.token)
    const path = `/projects/${v.projectId}/versions?version_id=${version}`
    await page.goto(path)
    const intake = page.getByTestId('requirement-intake'), panel = page.getByTestId('requirement-review')
    await intake.getByRole('textbox', { name: 'Requirement title', exact: true }).fill('Article editing')
    await intake.getByRole('textbox', { name: 'Requirement description', exact: true }).fill('Support editing articles')
    await intake.getByRole('button', { name: 'Save draft revision', exact: true }).click()
    async function evaluate() {
      await panel.getByRole('button', { name: 'Review and confirm requirement', exact: true }).click()
      await panel.getByRole('button', { name: 'Prepare model review', exact: true }).click()
      await expect(panel.getByText('Send the requirement, answers and selected evidence to the model.', { exact: false })).toBeVisible()
      await panel.getByRole('button', { name: 'Confirm and start review', exact: true }).click()
    }
    await evaluate()
    await expect(panel.getByText('clarification required', { exact: true })).toBeVisible()
    await panel.getByRole('textbox', { name: /Who may edit the article/ }).fill('Only the author may edit; others receive 403 and no data change.')
    await panel.getByRole('button', { name: 'Save answers as a new revision', exact: true }).click()
    await expect(intake.locator('.requirement-draft')).toContainText('Only the author may edit')
    await page.reload()
    await evaluate()
    await expect(panel.getByText('awaiting confirmation', { exact: true })).toBeVisible()
    await expect(panel.getByRole('button', { name: 'Approve these criteria and confirm requirement' })).toHaveCount(0)
    const context = await browser.newContext({ baseURL: test.info().project.use.baseURL })
    try {
      await context.addInitScript((token) => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, reviewer.token)
      const other = await context.newPage()
      await other.goto(path)
      const approval = other.getByTestId('requirement-review')
      await approval.getByRole('button', { name: 'Review and confirm requirement', exact: true }).click()
      await approval.getByRole('textbox', { name: 'Confirmation reason', exact: true }).fill('Independent reviewer checked the displayed expectations.')
      await approval.getByRole('button', { name: 'Approve these criteria and confirm requirement', exact: true }).click()
      await expect(approval.getByText('confirmed', { exact: true })).toBeVisible({ timeout: 20_000 })
      await other.reload()
      await expect(other.getByTestId('iteration-delivery')).toContainText('Requirements independently confirmed')
      await other.setViewportSize({ width: 390, height: 844 })
      expect(await other.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await other.screenshot({ path: `output/playwright/m2-review-${theme}.png`, fullPage: true })
    } finally { await context.close() }
    expect(calls).toBe(2)
  } finally {
    await request.post(`${analysisApi}/v1/settings/model-configs/${old.active_source === 'custom' ? old.active_config_id + '/activate' : 'chat/use-system-default'}`, { headers: admin })
    await new Promise<void>((resolve) => server.close(() => resolve()))
    rmSync(source, { recursive: true, force: true })
  }
})
