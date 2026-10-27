import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { analysisApi, captureAnalysis, openAnalysis, selectAnalysis } from './source-analysis-fixtures'
import { selectImageRevision } from './image-revision-fixtures'

test('fixed exweb source shows all reviewed annotation routes in the real inspector', async ({ page, request }) => {
  test.skip(!process.env.EXWEB_FIXTURE_ROOT, 'Opt in with an authorized fixed exweb checkout')
  test.setTimeout(120_000)
  const root = resolve(process.env.EXWEB_FIXTURE_ROOT!)
  const gold = JSON.parse(readFileSync(resolve('tests/fixtures/system-image/exweb-controller-routes.json'), 'utf8'))
  const git = (...args: string[]) => execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', root, ...args], { encoding: 'utf8' }).trim()
  expect(git('rev-parse', 'HEAD')).toBe(gold.revision)
  expect(git('status', '--porcelain', '--untracked-files=all')).toBe('')
  // Parse authorized source only; do not run exweb, Maven, hooks or dependencies.
  const { owner, projectId, conversationId, revision } = await captureAnalysis(request, root)
  const queryImage = async (operation: string, input: Record<string, unknown>) => {
    const response = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: owner.headers, data: {
      tool_id: `query.system_image.revisions.${operation}`, conversation_id: conversationId,
      input: { project_id: projectId, ...input }, initiator_surface: 'agent_loop', initiator_actor: 'agent',
    } })
    expect(response.ok()).toBeTruthy()
    const invocation = await response.json()
    expect(invocation.status).toBe('completed')
    expect(invocation.result.image_query.schema_version).toBe('nasus.image-query.v1')
    expect(JSON.stringify(invocation)).not.toContain('public class ChatController')
    const expanded = await request.get(`${analysisApi}/v1/tool-invocations/${invocation.id}/image-query`, { headers: owner.headers })
    expect(expanded.ok()).toBeTruthy()
    expect(expanded.headers()['cache-control']).toBe('private, no-store')
    return expanded.json()
  }
  const candidateUrl = `${analysisApi}/v1/projects/${projectId}/system-image/revisions`
  const candidateResponse = await request.get(candidateUrl, { headers: owner.headers })
  expect(candidateResponse.ok()).toBeTruthy()
  expect(candidateResponse.headers()['cache-control']).toBe('private, no-store')
  const candidates = (await candidateResponse.json()).items
  expect(candidates).toHaveLength(1)
  expect(candidates[0]).toMatchObject({ status: 'candidate', object_count: 725, code_member_count: 725,
    relationship_count: 1219,
    publication: 'blocked_pending_revision_governance' })
  expect((await queryImage('list', {})).items).toEqual(candidates)
  const inputResponse = await request.get(`${candidateUrl}/${candidates[0].image_revision_id}?section=source_members`, { headers: owner.headers })
  expect(inputResponse.ok()).toBeTruthy()
  expect((await inputResponse.json()).items).toEqual([
    expect.objectContaining({ source_type: 'code', source_revision_id: revision, status: 'captured' }),
  ])
  await openAnalysis(page, projectId, owner.token)
  const dialog = await selectAnalysis(page, revision)
  await expect(dialog).toContainText('126 matching observations')
  await expect(dialog.locator('.analysis-counts > div').filter({ hasText: /^Parsed120$/ })).toHaveCount(1)
  await expect(dialog.locator('.analysis-counts > div').filter({ hasText: /^Unsupported6$/ })).toHaveCount(1)
  await dialog.getByRole('button', { name: 'Structure', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Structure kind', exact: true }).selectOption('route')
  const list = dialog.getByRole('list', { name: 'Analysis observations' })
  await expect(list.locator(':scope > li')).toHaveCount(13)
  for (const controller of gold.controllers) {
    for (const route of controller.routes) {
      const row = list.locator(':scope > li').filter({ has: page.getByText(`${route.method} ${route.path}`, { exact: true }) })
      await expect(row).toHaveCount(1)
      await expect(row.locator('.analysis-location')).toHaveText(`${gold.source_root}${controller.file}:${route.line}-${route.line}`)
      await row.getByText('Observation details', { exact: true }).click()
      await expect(row).toContainText(`${controller.file}:${controller.controller_line}-${controller.controller_line}`)
      await expect(row).toContainText(`${controller.file}:${controller.class_mapping_line}-${controller.class_mapping_line}`)
    }
  }
  await dialog.getByText('Report provenance', { exact: true }).click()
  await expect(dialog).toContainText('sha256:')
  await dialog.getByRole('combobox', { name: 'Captured code revision', exact: true }).scrollIntoViewIfNeeded()
  mkdirSync(resolve('output/playwright'), { recursive: true })
  await page.screenshot({ path: resolve('output/playwright/exweb-analysis.png') })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
  const image = await selectImageRevision(page, candidates[0].image_revision_id)
  // No synthetic System object or its 725 display-only membership edges.
  await expect(image).toContainText('725 objects · 725 code entities · 1219 inferred relationships')
  const records = image.getByRole('list', { name: 'Frozen image records' })
  let found = false
  for (let offset = 0; offset < candidates[0].object_count; offset += 25) {
    const frozenPage = await queryImage('read', { image_revision_id: candidates[0].image_revision_id, section: 'objects', offset, limit: 25 })
    expect(frozenPage.revision.artifact_hash).toBe(candidates[0].artifact_hash)
    const items = frozenPage.items as { id: string; name: string; type: string; code_reference?: { source_revision_id: string } }[]
    expect(items.every((item) => item.type !== 'System' && item.code_reference?.source_revision_id === revision)).toBe(true)
    await expect(records.locator(':scope > li').first()).toHaveAttribute('data-object-id', items[0].id)
    const controller = items.find((item) => item.name.startsWith('ChatController (') && item.type === 'CodeClass' && item.code_reference)
    if (controller) {
      expect(controller.code_reference!.source_revision_id).toBe(revision)
      const row = records.locator(`[data-object-id="${controller.id}"]`)
      await row.getByRole('button', { name: 'Inspect frozen evidence', exact: true }).click()
      const code = row.getByRole('region', { name: 'Archived source code' })
      await expect(code).toContainText('public class ChatController')
      await expect(row.locator('.image-evidence-location')).toHaveText(`${gold.source_root}chat/ChatController.java:20-45`)
      const members = await queryImage('read', { image_revision_id: candidates[0].image_revision_id, section: 'members', offset, limit: 25 })
      const member = members.items.find((item: { object_id: string }) => item.object_id === controller.id)
      expect(member.evidence_ids.length).toBeGreaterThan(0)
      const evidence = await queryImage('evidence', { image_revision_id: candidates[0].image_revision_id,
        object_id: controller.id, evidence_id: member.evidence_ids[0] })
      expect(evidence).toMatchObject({ start_line: 20, end_line: 45, integrity: 'verified', evidence: { source_revision_id: revision } })
      expect(evidence.content).toContain('public class ChatController')
      await code.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve('output/playwright/exweb-image-revision-evidence.png') })
      found = true
      break
    }
    await image.getByRole('button', { name: 'Next page', exact: true }).click()
  }
  expect(found, 'the frozen image must retain the reviewed ChatController entity and exact source').toBe(true)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
  const plans = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
  await plans.getByRole('button', { name: 'Propose investigation' }).click()
  await plans.getByRole('textbox', { name: 'Investigation objective' }).fill('Investigate exweb chat, document upload and tool gateway structure')
  await plans.getByRole('combobox', { name: 'Build intent target' }).selectOption(candidates[0].baseline_id)
  await expect(plans.getByRole('button', { name: 'Save investigation draft' })).toBeEnabled()
  await plans.getByRole('button', { name: 'Save investigation draft' }).click()
  const draft = plans.getByRole('region', { name: 'Investigation draft' })
  await expect(draft).toContainText(candidates[0].manifest_id)
  await expect(draft).toContainText('execution_authorization_required')
  await expect(draft).not.toContainText('captured_code_required')
  await draft.getByText('Pinned source revisions', { exact: true }).click()
  await expect(draft).toContainText(revision)
  await draft.getByRole('heading', { name: 'Investigate exweb chat, document upload and tool gateway structure' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve('output/playwright/exweb-build-plan.png') })
  const targets = plans.getByRole('combobox', { name: 'Candidate target baseline' })
  await expect(targets).toHaveValue(candidates[0].baseline_id)
  await expect(targets).toBeDisabled()
  await plans.getByRole('button', { name: 'Prepare structural build' }).click()
  const built = page.waitForResponse((response) => response.url().endsWith('/confirm') && response.request().method() === 'POST')
  await plans.getByRole('button', { name: 'Confirm structural build' }).click()
  const result = await (await built).json()
  expect(result.status).toBe('completed')
  const builtRevision = result.result.object_refs[1].slice('image_revision:'.length)
  await expect(plans.getByRole('region', { name: 'Recent structural candidates' })).toContainText(builtRevision)
  const frozen = await queryImage('read', { image_revision_id: builtRevision, section: 'source_members' })
  expect(frozen.revision).toMatchObject({ manifest_id: candidates[0].manifest_id, code_member_count: 725, status: 'candidate' })
  expect(frozen.items).toEqual([expect.objectContaining({ source_revision_id: revision })])
  await plans.getByRole('heading', { name: 'Build pinned structure' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve('output/playwright/exweb-structure-build.png') })

  const planId = result.result.object_refs[0].slice('build_plan:'.length)
  const planResponse = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`, { headers: owner.headers })
  expect(planResponse.ok()).toBeTruthy()
  const fixedPlan = await planResponse.json()
  const readTool = 'query.system_image.build_plans.read'
  const authorizeTool = 'system_image.build.authorize'
  const goalResponse = await request.post(`${analysisApi}/v1/agent-goals`, { headers: owner.headers, data: {
    conversation_id: conversationId, project_id: projectId, title: 'Build source-pinned exweb image',
    summary: 'Authorize the fixed investigation budget and execute its reserved structural work', goal_template: 'system_image_build',
    target_refs: [`build_plan:${planId}`], steps: [
      { id: 'read', title: 'Read fixed plan', phase: 'acting', status: 'pending', selected_tool_id: readTool,
        tool_input_payload: { project_id: projectId, plan_id: planId } },
      { id: 'authorize', title: 'Authorize fixed build', phase: 'acting', status: 'pending', selected_tool_id: authorizeTool,
        tool_input_payload: { project_id: projectId, plan_id: planId, plan_digest: fixedPlan.plan_digest,
          target_baseline_id: candidates[0].baseline_id,
          budget: { max_tool_calls: 1, max_model_calls: 0, max_active_seconds: 1200, max_cost_microusd: 0 } } },
      { id: 'structure', title: 'Build fixed structure', phase: 'acting', status: 'pending', selected_tool_id: 'system_image.build.structure',
        tool_input_payload: { project_id: projectId, plan_id: planId, plan_digest: fixedPlan.plan_digest,
          target_baseline_id: candidates[0].baseline_id } },
    ],
  } })
  expect(goalResponse.ok()).toBeTruthy()
  const goal = await goalResponse.json()
  expect(goal).toMatchObject({ status: 'paused', pause_reason: 'waiting_confirmation' })
  const acting = goal.steps.filter((step: { phase: string }) => step.phase === 'acting')
  expect(acting.map((step: { selected_tool_id: string }) => step.selected_tool_id)).toEqual([readTool, authorizeTool, 'system_image.build.structure'])
  const invocationResponse = await request.get(`${analysisApi}/v1/tool-invocations/${acting[0].tool_invocation_id}`, { headers: owner.headers })
  expect(invocationResponse.ok()).toBeTruthy()
  const readInvocation = await invocationResponse.json()
  expect(readInvocation.result.build_plan_query).toMatchObject({ plan_digest: fixedPlan.plan_digest,
    source_manifest_id: candidates[0].manifest_id, authorization_state: 'not_granted', execution_ready: false })
  expect(JSON.stringify(readInvocation.result)).not.toContain('public class ChatController')
  const resumedResponse = await request.post(`${analysisApi}/v1/agent-goals/${goal.id}/resume`, { headers: owner.headers, data: { expected_goal: goal } })
  expect(resumedResponse.ok()).toBeTruthy()
  const resumed = await resumedResponse.json()
  expect(resumed).toMatchObject({ status: 'paused', pause_reason: 'structural_candidate_review' })
  const authorizationResponse = await request.get(`${analysisApi}/v1/tool-invocations/${acting[1].tool_invocation_id}`, { headers: owner.headers })
  const authorization = await authorizationResponse.json()
  expect(authorization.status).toBe('completed')
  expect(authorization.result.object_refs[0]).toMatch(/^build_authorization:/)
  const structureStep = resumed.steps.find((step: { selected_tool_id?: string }) => step.selected_tool_id === 'system_image.build.structure')
  const workResponse = await request.get(`${analysisApi}/v1/tool-invocations/${structureStep.tool_invocation_id}`, { headers: owner.headers })
  expect(workResponse.ok()).toBeTruthy()
  const work = await workResponse.json()
  expect(work.status).toBe('completed')
  expect(work.input_payload.confirmed_by_user).toBeUndefined()
  const agentRevision = work.result.object_refs[1].slice('image_revision:'.length)
  const agentCandidate = await queryImage('read', { image_revision_id: agentRevision, section: 'source_members' })
  expect(agentCandidate.revision).toMatchObject({ code_member_count: 725, manifest_id: candidates[0].manifest_id,
    status: 'candidate', publication: 'blocked_pending_revision_governance' })
  expect(agentCandidate.items).toEqual([expect.objectContaining({ source_revision_id: revision })])
  const restored = await request.get(`${analysisApi}/v1/agent-goals/${goal.id}`, { headers: owner.headers })
  expect((await restored.json()).pause_reason).toBe('structural_candidate_review')
  await page.reload()
  await page.getByRole('button', { name: 'Investigation plans', exact: true }).click()
  const restoredPlans = page.getByRole('dialog', { name: 'Investigation plans', exact: true })
  await restoredPlans.getByRole('combobox', { name: 'Saved investigation plan', exact: true }).selectOption(planId)
  const consent = restoredPlans.getByRole('region', { name: 'Saved execution consent', exact: true })
  await consent.getByText('Saved execution consent', { exact: true }).click()
  await expect(consent).toContainText(goal.id)
  await expect(consent).toContainText('1 tool calls · 0 model calls · 1200 seconds')
  await expect(consent).toContainText('Model egress and publication remain unapproved.')
  await consent.scrollIntoViewIfNeeded()
  await page.screenshot({ path: resolve('output/playwright/exweb-build-authorization.png') })
})
