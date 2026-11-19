// Retained Portal acceptance. Each write has an exclusive, durable intent;
// subsequent invocations reconcile the original scope instead of re-sending.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { chromium } from 'playwright'

const [id, step] = process.argv.slice(2)
const steps = ['create', 'sources', 'requirements', 'tests', 'capture', 'structure', 'propose', 'iteration', 'requirement-draft', 'inspect', 'reopen']
if (!/^m3-\d{8}-\d{4}$/.test(id ?? '') || !steps.includes(step)) throw Error('Expected: m3-YYYYMMDD-HHMM ' + steps.join('|'))
const operator = 'output/realworld/m3-20261118'
const dir = path.resolve('output/realworld', id)
if (step === 'create') await fs.mkdir(dir, { recursive: true, mode: 0o700 })
else {
  // Opening an unused Build session would create a conversation. Inspection
  // is allowed only after an existing create intent or completion proof.
  await fs.access(path.join(dir, step === 'inspect' ? 'create.intent.json' : 'create.verified.json'))
}
const journal = async (kind, data) => fs.writeFile(path.join(dir, Date.now() + '-' + randomUUID() + '.json'),
  JSON.stringify({ acceptance_id: id, step, kind, at: new Date().toISOString(), ...data }, null, 2), { flag: 'wx', mode: 0o600 })
const portal = 'http://localhost:5173'
const name = 'RealWorld M3 ' + id.slice(3).replace('-', ' ')
const repos = [
  ['https://github.com/c4ffein/realworld-django-ninja', '87dd078c883a046f5ff20269df2fb004d8b5f83f'],
  ['https://github.com/realworld-apps/vue-realworld-example-app', 'db749e3bb1a45755e0a3f4065abaf7346f004f36'],
]
const spec = '25588846c314b15a5e427ffe816e6b4af7be68c7'
const desktop = JSON.parse(await fs.readFile(path.join(operator, 'operator-state.private.json'), 'utf8'))
const token = desktop.origins.find(e => e.origin === portal)?.localStorage.find(e => e.name === 'nasus_api_token')?.value
assert.ok(token, 'missing existing operator login')
const get = async resource => {
  const response = await fetch('http://127.0.0.1:8000/v1/' + resource, { headers: { Authorization: 'Bearer ' + token }, redirect: 'error' })
  assert.equal(response.status, 200, 'authenticated project read failed')
  return response.json()
}
assert.equal((await get('auth/me')).email, 'nasus-m3-20261118-operator@example.test')
const browser = await chromium.launch()
let cid
try {
  const page = await (await browser.newContext(step === 'reopen' ? {} : { storageState: desktop })).newPage()
  const build = '/build?session=' + id
  if (step === 'reopen') {
    const credentials = JSON.parse(await fs.readFile(path.join(operator, 'operator-credentials.private.json'), 'utf8'))
    await page.goto(portal + '/login')
    await page.getByRole('textbox', {name:/^(邮箱|Email)$/}).fill(credentials.email)
    await page.getByRole('textbox', {name:/^(密码|Password)$/}).fill(credentials.password)
    await page.getByRole('button', {name:/^(登录|Sign in|Log in)$/}).click()
    await page.waitForURL('**/build')
  }
  const freshSnapshot = page.waitForResponse(r => r.request().method() === 'GET' && r.ok()
    && /^\/v1\/conversations\/conv_[a-z0-9]+$/.test(new URL(r.url()).pathname))
  await page.goto(portal + build)
  const first = await (await freshSnapshot).json()
  assert.equal(first.space_type, 'build')
  assert.equal(first.space_id, 'build-' + id)
  cid = first.id
  assert.match(cid, /^conv_[a-z0-9]+$/)
  const state = s => s.messages.findLast(m => m.role === 'assistant' && m.metadata?.system_image_intake)?.metadata.system_image_intake
  const delivery = s => s.messages.findLast(m => m.role === 'assistant' && m.metadata?.delivery_intake)?.metadata.delivery_intake
  const sprint = 'Sprint 1'
  const receipts = s => s.tool_invocations.map(t => ({ id: t.id, tool: t.tool_id, status: t.status }))
  const isProject = s => s.project_id && state(s)?.project_id === s.project_id && state(s).project_name === name
    && s.tool_invocations.some(t => t.tool_id === 'project.create' && t.status === 'completed' && t.input_payload.name === name)
  const hasSources = s => state(s)?.code === repos[0][0] && state(s)?.code_ref === repos[0][1]
    && state(s)?.additional_code_sources?.length === 1 && state(s).additional_code_sources[0].code === repos[1][0]
    && state(s).additional_code_sources[0].code_ref === repos[1][1]
  const hasUpload = (s, kind) => {
    const uri = state(s)?.[kind]
    if (!uri || !URL.canParse(uri)) return false
    const u = new URL(uri)
    return u.protocol === 's3:' && !u.username && !u.password && !u.search && !u.hash
      && u.pathname.startsWith('/source-uploads/' + s.project_id + '/' + (kind === 'tests' ? 'test_asset' : 'us_doc') + '/')
  }
  const done = s => ({
    inspect: true, reopen: isProject(s), create: isProject(s), sources: hasSources(s), requirements: hasUpload(s, 'requirements'), tests: hasUpload(s, 'tests'),
    capture: ['system_image.sources.register','system_image.sources.ingest'].every(tool => receipts(s).some(t => t.tool === tool && t.status === 'completed')),
    structure: s.tool_invocations.some(t => t.tool_id === 'system_image.build.structure' && t.status === 'completed'
      && t.input_payload.project_id === s.project_id && t.result?.object_refs?.some(ref => ref.startsWith('image_revision:'))),
    propose: ['confirmation','created'].includes(delivery(s)?.stage) && delivery(s).name === sprint,
    iteration: delivery(s)?.stage === 'created' && delivery(s).name === sprint && delivery(s).version_id,
    'requirement-draft': s.tool_invocations.some(t => t.tool_id === 'quality.requirement.revise' && t.status === 'completed'
      && t.input_payload.version_id === delivery(s)?.version_id && t.input_payload.text === 'US-001 文章编辑与权限：支持修改文章'),
  })[step]
  let current = first
  if (step !== 'create' && step !== 'inspect') {
    const created = JSON.parse(await fs.readFile(path.join(dir, 'create.verified.json'), 'utf8'))
    assert.ok(isProject(current) && current.project_id === created.project_id && cid === created.conversation_id, 'project identity not verified')
  }
  const requireStages = { tests: ['requirements'], requirements: ['sources'], capture: ['tests'], structure: ['capture'],
    propose:['structure'], iteration:['propose'], 'requirement-draft':['iteration'] }
  if (requireStages[step] && !done(current)) {
    for (const prior of requireStages[step]) await fs.access(path.join(dir, prior + '.verified.json'))
  }
  if (!done(current)) {
    if (step === 'create') {
      assert.ok(!first.project_id && !first.messages.length, 'existing conversation; inspect original result')
      assert.ok(!(await get('projects')).some(p => p.name === name), 'project with this name already exists')
    }
    if (step === 'capture' || step === 'structure') {
      assert.ok(hasSources(current) && hasUpload(current, 'requirements') && hasUpload(current, 'tests'), 'source scope changed')
    }
    const input = page.getByTestId('build-agent-input')
    let action
    if (step === 'create' || step === 'sources') {
      await input.fill(step === 'create' ? '创建项目\n项目名称：' + name : repos.map(([url,sha]) => '仓库 ' + url + ' 提交 ' + sha).join('\n'))
      action = () => input.press('Enter')
    } else if (step === 'requirements' || step === 'tests') {
      const specFile = file => ({ name: path.basename(file), mimeType: 'application/octet-stream',
        buffer: execFileSync('git', ['-C','.nasus/validation/realworld-spec','show',spec + ':' + file], { maxBuffer: 8 * 1024 * 1024 }) })
      const us = await fs.readFile(path.join(operator, 'US-001.md'))
      assert.equal(createHash('sha256').update(us).digest('hex'), '24582adc0c6fdfdf4bca35d0ca27466f47aa8ffa34d49ec75081adf051861a2c')
      const files = step === 'requirements' ? [{ name:'US-001.md', mimeType:'text/markdown', buffer:us }, specFile('specs/api/openapi.yml')]
        : ['specs/api/hurl/articles.hurl','specs/api/hurl/errors_articles.hurl','specs/api/hurl/errors_authorization.hurl','specs/e2e/articles.spec.ts'].map(specFile)
      const field = page.getByTestId('build-upload-' + (step === 'requirements' ? 'us_doc' : 'test_asset'))
      action = () => field.setInputFiles(files)
    } else if (step === 'capture') {
      assert.equal(state(current).stage, 'review')
      action = () => page.getByTestId('build-intake-confirm').click()
    } else if (step === 'structure') {
      const card = page.getByTestId('build-progress')
      const details = JSON.parse(await card.locator('pre').textContent())
      const b = details.budget
      assert.ok(details.project_id === first.project_id && b.max_model_calls === 0 && b.max_cost_microusd === 0
        && b.max_tool_calls === 1 && b.max_active_seconds > 0 && b.max_active_seconds <= 1200, 'not the approved structural budget')
      assert.match(await card.innerText(), /Authorize Fixed Build Plan/)
      action = () => card.getByTestId('build-goal-continue').click()
    } else if (step === 'propose' || step === 'iteration' || step === 'requirement-draft') {
      const ref = current.tool_invocations.find(t => t.tool_id === 'system_image.build.structure' && t.status === 'completed')
        ?.result?.object_refs?.find(r => r.startsWith('image_revision:'))?.slice('image_revision:'.length)
      assert.match(ref ?? '', /^[0-9a-f-]{36}$/)
      const root = 'projects/' + current.project_id + '/'
      const { revision } = await get(root + 'system-image/revisions/' + ref + '?limit=1')
      const { head } = await get(root + 'system-image/publications?baseline_id=' + encodeURIComponent(revision.baseline_id))
      assert.ok(head && head.image_revision_id === ref && head.image_artifact_hash === revision.artifact_hash
        && head.project_id === current.project_id && head.sequence === 1 && head.approval_id, 'approved exact initial publication required')
      if (step === 'iteration') {
        const proposal = delivery(current)
        assert.ok(proposal?.stage === 'confirmation' && proposal.name === sprint && proposal.image_binding?.publication_id === head.publication_id
          && proposal.image_binding?.image_artifact_hash === revision.artifact_hash, 'changed iteration proposal')
      }
      if (step === 'requirement-draft') {
        const d = await get(root + 'versions/' + encodeURIComponent(delivery(current).version_id) + '/delivery')
        assert.ok(d.stage === 'image_pinned' && d.baseline?.publication_id === head.publication_id
          && d.iteration_image?.image_artifact_hash === revision.artifact_hash && d.code_revisions?.length === 2
          && repos.every(([url,sha]) => d.code_revisions.some(r => r.repository === url && r.commit_sha === sha)), 'invalid iteration binding')
      }
      const text = step === 'propose' ? '创建迭代 ' + sprint + '，使用画像发布 ' + head.publication_id
        : step === 'iteration' ? '确认创建迭代' : '需求：US-001 文章编辑与权限：支持修改文章'
      await input.fill(text)
      action = () => input.press('Enter')
    }
    // Do not dispatch on a duplicate intent, even after a timeout or crash.
    await fs.writeFile(path.join(dir, step + '.intent.json'), JSON.stringify({ cid, project_id: first.project_id, name, repos, spec }),
      { flag: 'wx', mode: 0o600 })
    await action()
    const deadline = Date.now() + (step === 'structure' ? 1_200_000 : 180_000)
    while (Date.now() < deadline) {
      current = await get('conversations/' + cid)
      if (done(current)) break
      await delay(1000)
    }
    assert.ok(done(current), 'original operation not yet verified; inspect without redispatch')
  }
  const report = { project_id:current.project_id, conversation_id:cid, build_url:portal + build,
    project_url:current.project_id ? portal + '/projects/' + current.project_id + '/knowledge' : null,
    stage:state(current)?.stage, version_id:delivery(current)?.version_id, receipts:receipts(current), full_m3_verified:false }
  const candidate = current.tool_invocations.find(t => t.tool_id === 'system_image.build.structure' && t.status === 'completed')
    ?.result?.object_refs?.find(ref => ref.startsWith('image_revision:'))?.slice('image_revision:'.length)
  if (candidate) {
    assert.match(candidate, /^[a-f0-9-]{36}$/)
    const { revision, total } = await get('projects/' + current.project_id + '/system-image/revisions/' + candidate + '?section=source_members')
    assert.ok(revision.project_id === current.project_id && revision.image_revision_id === candidate && total === 4)
    report.candidate = Object.fromEntries(['image_revision_id','artifact_hash','baseline_id','manifest_id','manifest_hash',
      'object_count','relationship_count','code_member_count','status'].map(k => [k,revision[k]]))
  }
  await journal('observed', report)
  if (step !== 'inspect') {
    assert.ok(isProject(current), 'scope changed')
    await page.reload()
    await page.locator('a[href="/projects/' + current.project_id + '/knowledge"]').first().waitFor()
    const again = await get('conversations/' + cid)
    assert.ok(isProject(again) && done(again), 'original operation not restored')
    if (step === 'reopen') {
      await page.locator('a[href="/projects/' + current.project_id + '/knowledge"]').first().click()
      await page.getByText(name, {exact:true}).first().waitFor()
      await page.screenshot({path:path.join(dir,'reopened-project.png')})
    }
    await fs.writeFile(path.join(dir, step + '.verified.json'), JSON.stringify(report,null,2), { flag:'wx', mode:0o600 })
      .catch(e => { if (e.code !== 'EEXIST') throw e })
  }
  console.log(JSON.stringify(report))
} catch (e) {
  const reason = e.name === 'AssertionError' ? e.message.split('\n')[0] : (e.code || e.name)
  await journal('blocked', { conversation_id:cid, reason })
  console.error('Not verified:', reason)
  process.exitCode = 2
} finally { await browser.close() }
