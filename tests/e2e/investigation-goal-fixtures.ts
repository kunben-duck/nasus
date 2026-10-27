import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { realpathSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname } from 'node:path'
import { analysisApi, captureAnalysis } from './source-analysis-fixtures'

export type InvestigationGoal = { id: string; status: string; pause_reason: string; max_steps: number; model_calls_used: number; steps: {
  id: string; phase: string; status: string; selected_tool_id: string; tool_invocation_id: string; tool_input_payload: Record<string, unknown>
}[] }

export async function originalStructuralGoal(request: APIRequestContext, source: string) {
  const disposable = realpathSync(source)
  if (dirname(disposable) !== realpathSync(tmpdir())
    || !['nasus-analysis-browser-', 'nasus-build-review-'].some((prefix) => basename(disposable).startsWith(prefix))) {
    throw new Error('This fixture requires a disposable source export, never a shared checkout')
  }
  const captured = await captureAnalysis(request, source, { materialize: false })
  const { owner, projectId, conversationId, invoke } = captured
  const response = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image`, { headers: owner.headers })
  expect(response.ok()).toBeTruthy()
  const image = await response.json()
  const targetResponse = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-targets/${image.baselines[0].id}`, { headers: owner.headers })
  expect(targetResponse.ok()).toBeTruthy()
  const target = await targetResponse.json()
  expect(target).toMatchObject({ project_id: projectId, target_baseline_id: image.baselines[0].id,
    target_version_id: null, expected_head_id: null, expected_head_hash: null })
  const plan = await invoke('system_image.build.plan', {
    source_manifest_id: image.source_manifest.manifest_id, objective: 'Investigate the archived candidate and its explicit gaps',
    target,
  })
  const planId = plan.result.object_refs.find((ref: string) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
  const detail = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`, { headers: owner.headers })
  expect(detail.ok()).toBeTruthy()
  const saved = await detail.json()
  expect(saved.proposal.policy_version).toBe('nasus.image-investigation-plan.v3')
  expect(saved.proposal.intent.target).toEqual(target)
  const fixed = { project_id: projectId, plan_id: planId, plan_digest: saved.plan_digest,
    target_baseline_id: image.baselines[0].id }
  const created = await request.post(`${analysisApi}/v1/agent-goals`, { headers: owner.headers, data: {
    conversation_id: conversationId, project_id: projectId, goal_template: 'system_image_build',
    title: 'Investigate the saved structural candidate', summary: 'Continue the same original goal', target_refs: [`build_plan:${planId}`],
    steps: [
      { id: 'grant', title: 'Authorize structure', phase: 'acting', status: 'pending', selected_tool_id: 'system_image.build.authorize',
        tool_input_payload: { ...fixed, budget: { max_tool_calls: 1, max_model_calls: 0, max_active_seconds: 1200, max_cost_microusd: 0 } } },
      { id: 'structure', title: 'Build structure', phase: 'acting', status: 'pending', selected_tool_id: 'system_image.build.structure', tool_input_payload: fixed },
    ],
  } })
  expect(created.ok()).toBeTruthy()
  const initial = await created.json() as InvestigationGoal
  expect(initial.pause_reason).toBe('waiting_confirmation')
  const resumed = await request.post(`${analysisApi}/v1/agent-goals/${initial.id}/resume`, { headers: owner.headers, data: { expected_goal: initial } })
  expect(resumed.ok()).toBeTruthy()
  const goal = await resumed.json() as InvestigationGoal
  expect(goal.pause_reason).toBe('structural_candidate_review')
  const structureId = goal.steps.find((step) => step.selected_tool_id === 'system_image.build.structure')!.tool_invocation_id
  const read = async () => {
    const value = await request.get(`${analysisApi}/v1/agent-goals/${goal.id}`, { headers: owner.headers })
    expect(value.ok()).toBeTruthy()
    return value.json() as Promise<InvestigationGoal>
  }
  // Only callers' disposable exports are accepted here, never a shared checkout.
  rmSync(disposable, { recursive: true, force: true })
  return { ...captured, goal, read, structureId, resumePath: `/v1/agent-goals/${goal.id}/resume` }
}

export async function openInvestigationProject(page: Page, projectId: string, token: string) {
  await page.addInitScript((value) => {
    localStorage.setItem('nasus_api_token', value)
    localStorage.setItem('nasus.locale', 'en')
  }, token)
  await page.goto(`/projects/${projectId}`)
  return page.getByTestId('agent-confirmation-gate')
}
