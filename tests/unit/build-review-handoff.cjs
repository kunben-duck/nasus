const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../apps/portal/node_modules/typescript')

const root = path.resolve(__dirname, '../../apps/portal/src')
function load(relative, overrides = {}) {
  const file = path.resolve(root, relative)
  const context = { exports: {}, URLSearchParams, require: (name) => {
    if (Object.hasOwn(overrides, name)) return overrides[name]
    return load(path.relative(root, path.resolve(path.dirname(file), `${name}.ts`)), overrides)
  } }
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return context.exports
}
const model = load('domains/system-image/buildReviewHandoff.ts')
const hash = 'sha256:' + 'a'.repeat(64)
const clone = (value) => JSON.parse(JSON.stringify(value))

function fixture() {
  const body = { project_id: 'project', goal_id: 'goal', plan_id: 'plan', plan_digest: hash,
    image_revision_id: 'image', image_artifact_hash: hash, evidence_selection: [] }
  const step = { id: 'investigate-step', phase: 'acting', status: 'completed',
    selected_tool_id: 'system_image.build.investigate', tool_invocation_id: 'invocation', tool_input_payload: body }
  const goal = { id: 'goal', project_id: 'project', conversation_id: 'conversation', status: 'paused',
    goal_template: 'system_image_build', pause_reason: 'build_completion_review', target_refs: [], steps: [step] }
  const command = { id: 'invocation', conversation_id: 'conversation', tool_id: 'system_image.build.investigate',
    status: 'completed', input_payload: { ...body, agent_goal_id: 'goal',
      agent_loop_iteration_id: 'goal:investigate-step:0', idempotency_key: 'agent-goal:goal:step:investigate-step:attempt:0',
      confirmed_at: 'time', confirmed_by_user: 'owner', confirmed_actor_id: 'owner' },
    result: { invocation_id: 'invocation', status: 'completed', object_refs: ['image_investigation:report'],
      investigation: { kind: 'investigation_revision', project_id: 'project', revision_id: 'report', revision_hash: hash } } }
  const report = { revision_id: 'report', revision_hash: hash,
    request: { ...body, parent_revision_id: null, parent_revision_hash: null },
    review: { image_revision_id: 'image', image_artifact_hash: hash,
      policy_version: 'nasus.image-investigation-revision.v1', publication_allowed: false,
      gaps: [{ code: 'runtime_evidence_unresolved', reason: 'No run', required_action: 'Bind an independent RunPlan' }] } }
  const target = { project_id: 'project', target_baseline_id: 'baseline', target_version_id: null,
    expected_head_id: null, expected_head_hash: null }
  const plan = { plan_digest: hash, proposal: { intent: { source_manifest_id: 'manifest', source_manifest_hash: hash,
    target: clone(target) } } }
  const image = { project_id: 'project', image_revision_id: 'image', artifact_hash: hash,
    baseline_id: 'baseline', manifest_id: 'manifest', manifest_hash: hash }
  const calls = [], controller = new AbortController(), signal = controller.signal
  let goalReads = 0
  const value = { goal, step, command, report, plan, image, target, calls, signal, controller }
  const api = load('domains/system-image/buildReviewHandoffApi.ts', {
    '../../shared/api/client': { request: async (url, options) => {
      calls.push({ url, options })
      assert.equal(options.cache, 'no-store')
      assert.equal(options.signal, signal)
      assert.equal(options.method, undefined)
      if (url === value.deniedUrl) throw new Error('403 Source access denied')
      if (url === '/v1/agent-goals/goal') return clone(goalReads++ ? value.currentGoal ?? goal : goal)
      if (url === '/v1/tool-invocations/invocation') return clone(command)
      if (url === '/v1/projects/project/system-image/build-investigations/report') return clone(report)
      throw new Error('Unexpected private read ' + url)
    } },
    './buildPlanApi': { buildPlanApi: { read: async (project, id, received) => {
      calls.push({ kind: 'plan', project, id }); assert.equal(received, signal); return clone(plan)
    }, target: async (project, id, received) => {
      calls.push({ kind: 'target', project, id }); assert.equal(received, signal)
      if (value.deniedTarget) throw new Error('403 Target access denied')
      return clone(target)
    } } },
    './imageRevisionApi': { imageRevisionApi: { page: async (project, id, selection, received, limit) => {
      calls.push({ kind: 'image', project, id, selection, limit }); assert.equal(received, signal)
      return { revision: clone(image) }
    } } },
  })
  value.read = () => api.readBuildReviewHandoff('project', { goalId: 'goal', invocationId: 'invocation' }, signal)
  return value
}

test('completion navigation pins the original goal and investigation without granting consent', () => {
  const v = fixture()
  const href = model.buildReviewHref(v.goal)
  const url = new URL(href, 'http://localhost')
  assert.equal(url.pathname, '/projects/project/knowledge')
  assert.deepEqual(clone(model.parseBuildReviewSelection(url.searchParams)), { goalId: 'goal', invocationId: 'invocation' })
  assert.equal(url.searchParams.size, 2)
  assert.deepEqual(v.calls, [])
})

for (const change of ['running', 'cancelled', 'failed', 'candidate', 'pending-work', 'no-command', 'wrong-template', 'bad-phase']) {
  test(`a ${change} checkpoint has no completion review navigation`, () => {
    const v = fixture()
    if (['running', 'cancelled', 'failed'].includes(change)) v.goal.status = change
    if (change === 'candidate') v.goal.pause_reason = 'structural_candidate_review'
    if (change === 'pending-work') v.goal.steps.push({ phase: 'acting', status: 'pending' })
    if (change === 'no-command') v.step.tool_invocation_id = ''
    if (change === 'wrong-template') v.goal.goal_template = 'quality_loop'
    if (change === 'bad-phase') v.goal.target_refs = ['build_plan_phase:missing']
    assert.equal(model.buildReviewHref(v.goal), undefined)
  })
}

test('a new phase selects only its own investigation, never a completed historical one', () => {
  const v = fixture()
  v.goal.target_refs = ['build_plan_phase:new']
  v.goal.steps.push({ id: 'build_plan_phase:new', status: 'completed' })
  assert.equal(model.buildReviewHref(v.goal), undefined)
  v.goal.steps.push({ ...v.step, id: 'new-investigate', tool_invocation_id: 'new-command' })
  assert.match(model.buildReviewHref(v.goal), /build_review_invocation=new-command/)
})

for (const query of ['build_review_goal=goal', 'build_review_invocation=invocation',
  'build_review_goal=goal&build_review_goal=other&build_review_invocation=invocation',
  'build_review_goal=goal&build_review_invocation=invocation&build_review_invocation=other',
  'build_review_goal=&build_review_invocation=invocation',
  'build_review_goal=%0Agoal&build_review_invocation=invocation']) {
  test(`invalid review pointer ${query} does not select a candidate`, () => {
    assert.throws(() => model.parseBuildReviewSelection(new URLSearchParams(query)))
  })
}
test('ordinary knowledge navigation has no review pointer', () => {
  assert.equal(model.parseBuildReviewSelection(new URLSearchParams('other=value')), null)
})

test('handoff verifies original command, report, plan, image and final goal without a write', async () => {
  const v = fixture(), result = await v.read()
  assert.equal(result.image.image_revision_id, 'image')
  assert.equal(result.investigation.review.publication_allowed, false)
  assert.equal(result.investigation.review.gaps[0].code, 'runtime_evidence_unresolved')
  assert.equal(v.calls.length, 7)
  assert.equal(v.calls[4].limit, 1)
  assert.equal(v.calls[5].kind, 'target')
  assert.deepEqual(clone(result.targetBaseline), { project_id: 'project', id: 'baseline' })
})

test('v2 investigation handoff preserves completed reference reads without granting relation approval', async () => {
  const v = fixture()
  v.report.review.policy_version = 'nasus.image-investigation-revision.v2'
  v.goal.steps.push({ id: 'references', phase: 'acting', status: 'completed',
    selected_tool_id: 'system_image.links.propose_references', tool_invocation_id: 'reference-command' },
  { id: 'references-read', phase: 'acting', status: 'completed',
    selected_tool_id: 'query.system_image.references.read', tool_invocation_id: 'reference-read' })
  const result = await v.read()
  assert.equal(result.investigation.review.policy_version, v.report.review.policy_version)
  assert.equal(result.investigation.review.publication_allowed, false)
  assert.match(model.buildReviewHref(v.goal), /build_review_invocation=invocation/)
})

test('unknown investigation policies fail closed rather than upgrading historical reports', async () => {
  const v = fixture()
  v.report.review.policy_version = 'nasus.image-investigation-revision.v999'
  await assert.rejects(v.read(), /report changed/)
})

test('a historical build review remains readable after a separately authorized head change', async () => {
  const v = fixture()
  v.target.expected_head_id = 'new-publication'
  v.target.expected_head_hash = 'sha256:' + 'b'.repeat(64)
  const result = await v.read()
  assert.equal(result.image.image_revision_id, 'image')
  assert.equal(v.plan.proposal.intent.target.expected_head_id, null)
  assert.equal(result.targetBaseline.id, 'baseline')
})

test('current target denial cannot reuse cached baseline options', async () => {
  const v = fixture(); v.deniedTarget = true
  await assert.rejects(v.read(), /Target access denied/)
  assert.equal(v.calls.length, 6)
})

test('object field order does not change the identity of the archived request or goal', async () => {
  const v = fixture()
  const reverse = (value) => Object.fromEntries(Object.entries(value).reverse())
  v.report.request = reverse(v.report.request)
  v.command.input_payload = reverse(v.command.input_payload)
  v.currentGoal = reverse(clone(v.goal))
  assert.equal((await v.read()).image.image_revision_id, 'image')
})

test('a matching explicit runtime step identity can accompany the canonical command', async () => {
  const v = fixture()
  v.command.input_payload.agent_step_id = v.step.id
  assert.equal((await v.read()).selection.invocationId, 'invocation')
})

test('permission denial cannot reuse the saved report or open an alternative image', async () => {
  const v = fixture()
  v.deniedUrl = '/v1/projects/project/system-image/build-investigations/report'
  await assert.rejects(v.read(), /Source access denied/)
  assert.equal(v.calls.length, 3)
})

test('an aborted navigation never returns protected findings', async () => {
  const v = fixture()
  v.controller.abort()
  await assert.rejects(v.read(), { name: 'AbortError' })
})

const corruptions = {
  'wrong project': (v) => { v.goal.project_id = 'other' },
  'old phase command': (v) => { v.step.tool_invocation_id = 'other' },
  'wrong conversation': (v) => { v.command.conversation_id = 'other' },
  'unfinished command': (v) => { v.command.status = 'running' },
  'wrong result command': (v) => { v.command.result.invocation_id = 'other' },
  'wrong runtime goal': (v) => { v.command.input_payload.agent_goal_id = 'other' },
  'missing runtime goal': (v) => { delete v.command.input_payload.agent_goal_id },
  'wrong runtime step': (v) => { v.command.input_payload.agent_step_id = 'other' },
  'unknown coordination field': (v) => { v.command.input_payload.agent_unknown_envelope = true },
  'wrong command input': (v) => { v.command.input_payload.goal_id = 'other' },
  'extra command input': (v) => { v.command.input_payload.publish = true },
  'wrong report project': (v) => { v.report.request.project_id = 'other' },
  'wrong report goal': (v) => { v.report.request.goal_id = 'other' },
  'wrong report receipt hash': (v) => { v.report.revision_hash = 'sha256:' + 'b'.repeat(64) },
  'report claims publication': (v) => { v.report.review.publication_allowed = true },
  'report image differs': (v) => { v.report.review.image_revision_id = 'other' },
  'wrong plan digest': (v) => { v.plan.plan_digest = 'sha256:' + 'b'.repeat(64) },
  'missing fixed target': (v) => { delete v.plan.proposal.intent.target },
  'wrong fixed target project': (v) => { v.plan.proposal.intent.target.project_id = 'other' },
  'wrong current target project': (v) => { v.target.project_id = 'other' },
  'wrong current target baseline': (v) => { v.target.target_baseline_id = 'other' },
  'wrong current target version': (v) => { v.target.target_version_id = 'other' },
  'wrong image hash': (v) => { v.image.artifact_hash = 'sha256:' + 'b'.repeat(64) },
  'wrong image project': (v) => { v.image.project_id = 'other' },
  'wrong image identity': (v) => { v.image.image_revision_id = 'other' },
  'wrong image manifest': (v) => { v.image.manifest_id = 'other' },
  'wrong image baseline': (v) => { v.image.baseline_id = 'other' },
  'goal changed during reads': (v) => { v.currentGoal = { ...clone(v.goal), pause_reason: 'build_plan_phase_prepared' } },
}
for (const [name, change] of Object.entries(corruptions)) {
  test(`${name} cannot open another candidate or send a mutation`, async () => {
    const v = fixture(); change(v)
    await assert.rejects(v.read())
    assert.ok(v.calls.filter((item) => item.options).every((item) => item.options.method === undefined))
  })
}
