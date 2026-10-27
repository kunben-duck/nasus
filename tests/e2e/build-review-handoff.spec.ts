import { expect, test, type APIRequestContext } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { analysisAccount, analysisApi, analysisSource, analysisSourcePolicy } from './source-analysis-fixtures'
import { originalStructuralGoal, openInvestigationProject, type InvestigationGoal } from './investigation-goal-fixtures'
import { frozenRevisions } from './image-revision-fixtures'

const exwebCommit = 'fe5827f6b76f77ef34918d8b452ee823142332dc'
function sourceExport() {
  const root = process.env.EXWEB_FIXTURE_ROOT
  if (!root) return analysisSource()
  const git = (...args: string[]) => execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', resolve(root), ...args])
  expect(git('rev-parse', 'HEAD').toString().trim()).toBe(exwebCommit)
  expect(git('status', '--porcelain', '--untracked-files=all').toString().trim()).toBe('')
  const directory = mkdtempSync(join(tmpdir(), 'nasus-build-review-'))
  try {
    const archive = join(directory, 'source.tar')
    git('archive', '--format=tar', `--output=${archive}`, exwebCommit)
    execFileSync('tar', ['-xf', archive, '-C', directory])
    rmSync(archive)
    return directory
  } catch (error) { rmSync(directory, { recursive: true, force: true }); throw error }
}

async function savedFindings(request: APIRequestContext, source: string) {
  const v = await originalStructuralGoal(request, source)
  const resume = async (goal: InvestigationGoal) => {
    const response = await request.post(`${analysisApi}${v.resumePath}`, { headers: v.owner.headers, data: { expected_goal: goal } })
    expect(response.ok()).toBeTruthy()
    return response.json() as Promise<InvestigationGoal>
  }
  const pending = await resume(v.goal)
  expect(pending.pause_reason).toBe('waiting_confirmation')
  const completed = await resume(pending)
  expect(completed.pause_reason).toBe('build_completion_review')
  const step = completed.steps.find((item) => item.selected_tool_id === 'system_image.build.investigate')!
  const command = await request.get(`${analysisApi}/v1/tool-invocations/${step.tool_invocation_id}`, { headers: v.owner.headers })
  expect(command.ok()).toBeTruthy()
  const receipt = (await command.json()).result.investigation
  const reportPath = `/v1/projects/${v.projectId}/system-image/build-investigations/${receipt.revision_id}`
  const response = await request.get(`${analysisApi}${reportPath}`, { headers: v.owner.headers })
  expect(response.ok()).toBeTruthy()
  const report = await response.json()
  expect(report.request.goal_id).toBe(v.goal.id)
  expect(report.revision_hash).toBe(receipt.revision_hash)
  const image = (await frozenRevisions(request, v.projectId, v.owner.headers))
    .find((item) => item.image_revision_id === report.request.image_revision_id)!
  expect(image.artifact_hash).toBe(report.request.image_artifact_hash)
  expect(report.review.publication_allowed).toBe(false)
  return { ...v, completed, step, reportPath, report, image }
}

async function reviewAudit(request: APIRequestContext, projectId: string, conversationId: string, headers: { Authorization: string }) {
  const calls = await request.get(`${analysisApi}/v1/llm-calls`, {
    headers: { Authorization: `Bearer ${process.env.NASUS_E2E_ADMIN_TOKEN ?? 'nasus-e2e-platform-admin-token'}` },
    params: { project_id: projectId, limit: 500 },
  })
  expect(calls.ok()).toBeTruthy()
  const models = await calls.json() as { id: string; model_calls: number }[]
  // A truncated audit cannot prove that navigation created no model calls.
  expect(models.length).toBeLessThan(500)
  const commands = await request.get(`${analysisApi}/v1/tool-invocations`, {
    headers, params: { conversation_id: conversationId },
  })
  expect(commands.ok()).toBeTruthy()
  const tools = await commands.json() as { id: string }[]
  return { models: models.sort((left, right) => left.id.localeCompare(right.id)),
    tools: tools.sort((left, right) => left.id.localeCompare(right.id)) }
}

for (const theme of ['light', 'dark']) {
  test(`original build findings hand off to separate knowledge publication in ${theme}`, async ({ page, request }) => {
    test.setTimeout(240_000)
    const source = sourceExport()
    try {
      const v = await savedFindings(request, source)
      if (process.env.EXWEB_FIXTURE_ROOT) expect(v.image.code_member_count).toBe(725)
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
      await page.addInitScript(() => {
        const reads: { location: string; stack?: string }[] = []
        Object.assign(window, { buildReviewImageReads: reads })
        const fetch = window.fetch.bind(window)
        window.fetch = (input, init) => {
          const url = input instanceof Request ? input.url : String(input)
          if (new URL(url, location.href).pathname.endsWith('/system-image')) {
            reads.push({ location: location.pathname + location.search, stack: new Error().stack })
            if (reads.length > 30) reads.shift()
          }
          return fetch(input, init)
        }
      })
      const gate = await openInvestigationProject(page, v.projectId, v.owner.token)
      const link = gate.getByTestId('review-saved-build-findings')
      await expect(link).toBeVisible()
      const href = await link.getAttribute('href')
      const pointer = new URL(href!, 'http://localhost')
      expect(pointer.searchParams.get('build_review_goal')).toBe(v.goal.id)
      expect(pointer.searchParams.get('build_review_invocation')).toBe(v.step.tool_invocation_id)
      let writes = 0, reports = 0, wholeImageReads = 0, detailReads = 0, transitionWholeImageReads = 0
      page.on('request', (sent) => {
        if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(sent.method())) writes += 1
        const path = new URL(sent.url()).pathname
        if (path === v.reportPath) reports += 1
        const location = new URL(page.url())
        // The outgoing workspace can refresh while Playwright scrolls the link
        // into view. Count reads initiated by the exact review route, not that
        // old observer; all writes remain forbidden throughout navigation.
        const reviewing = location.pathname === pointer.pathname
          && location.searchParams.get('build_review_goal') === v.goal.id
          && location.searchParams.get('build_review_invocation') === v.step.tool_invocation_id
        if (path === `/v1/projects/${v.projectId}/system-image`) {
          if (reviewing) wholeImageReads += 1
          else transitionWholeImageReads += 1
        }
        if (reviewing && /\/agent-memory\/context$|\/agent-goals\/[^/]+\/explanation$|\/agent-swarms$/.test(path)) detailReads += 1
      })
      await page.evaluate(() => {
        const push = history.pushState.bind(history)
        history.pushState = (...args) => {
          push(...args)
          // Revalidation can run after the URL changes, before React retires
          // the outgoing query observers. Exercise that transition explicitly.
          if (new URLSearchParams(location.search).has('build_review_goal')) {
            window.dispatchEvent(new Event('visibilitychange'))
          }
        }
      })
      await link.click()
      await expect(page).toHaveURL(new RegExp(`/projects/${v.projectId}/knowledge\\?`))
      let dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
      await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
      await expect(dialog).toContainText(v.image.image_revision_id)
      await expect(dialog).toContainText(v.image.artifact_hash)
      await expect(dialog).toContainText('Remaining investigation gaps')
      await expect(dialog.getByRole('combobox', { name: 'Frozen image revision', exact: true })).toHaveCount(0)
      expect(writes).toBe(0)
      if (wholeImageReads) await test.info().attach('unexpected-review-image-reads', {
        body: JSON.stringify(await page.evaluate(() => Reflect.get(window, 'buildReviewImageReads')), null, 2),
        contentType: 'application/json',
      })
      expect(wholeImageReads).toBe(0)
      expect(await v.read()).toEqual(v.completed)

      await page.reload()
      await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
      await expect(dialog).toContainText(v.image.artifact_hash)
      const previousReads = reports
      await dialog.getByRole('button', { name: 'Reload revisions', exact: true }).click()
      await expect.poll(() => reports).toBeGreaterThan(previousReads)
      await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
      expect(writes).toBe(0)
      expect(wholeImageReads).toBe(0)
      expect(detailReads).toBe(0)
      const navigationWrites = writes
      expect(await v.read()).toEqual(v.completed)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/build-review-handoff-${theme}.png`) })
      await page.setViewportSize({ width: 390, height: 844 })
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
      await page.screenshot({ path: resolve(`output/playwright/build-review-handoff-${theme}-mobile.png`) })

      const panel = dialog.getByRole('region', { name: 'Image publication', exact: true })
      await panel.getByRole('button', { name: 'Inspect image publication', exact: true }).click()
      const targets = panel.getByRole('combobox', { name: 'Publication target baseline', exact: true })
      await expect(targets.locator('option')).toHaveCount(2)
      await expect(targets.locator('option').last()).toHaveText(`Original build target · ${v.image.baseline_id}`)
      await targets.selectOption(v.image.baseline_id)
      const record = panel.getByRole('button', { name: 'Record publication review', exact: true })
      await expect(record).toBeDisabled()
      await panel.getByRole('textbox', { name: 'Review reason', exact: true }).fill('Explicit static knowledge review, not business acceptance or execution coverage')
      await panel.getByRole('checkbox', { name: 'I confirm this exact image, target baseline, current head and review decision.', exact: true }).check()
      const reviewed = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/confirm'))
      await record.click()
      expect((await (await reviewed).json()).status).toBe('completed')
      await expect(panel).toContainText('Publication approved')
      const publish = panel.getByRole('button', { name: 'Publish knowledge snapshot', exact: true })
      await expect(publish).toBeDisabled()
      await panel.getByRole('checkbox', { name: 'I confirm moving this baseline head to the reviewed image. This does not approve a release.', exact: true }).check()
      const published = page.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().endsWith('/v1/tool-invocations') && response.request().postDataJSON()?.tool_id === 'baseline.promote')
      await publish.click()
      const result = await (await published).json()
      expect(result.status).toBe('completed')
      expect(result.input_payload).toMatchObject({ image_revision_id: v.image.image_revision_id,
        image_artifact_hash: v.image.artifact_hash, target_baseline_id: v.image.baseline_id, expected_head_id: null })
      await expect(panel).toContainText('This exact image is the published knowledge head, not a quality approval.')
      const heads = await request.get(`${analysisApi}/v1/projects/${v.projectId}/system-image/publications`, {
        headers: v.owner.headers, params: { baseline_id: v.image.baseline_id },
      })
      expect(heads.ok()).toBeTruthy()
      const state = await heads.json()
      expect(state.items).toHaveLength(1)
      expect(state.head).toMatchObject({ image_revision_id: v.image.image_revision_id, image_artifact_hash: v.image.artifact_hash,
        quality_generation_authorized: false, release_authorized: false })
      expect(await v.read()).toEqual(v.completed)
      await page.reload()
      dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
      await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
      await expect(dialog).toContainText(v.image.image_revision_id)
      await expect(dialog).toContainText(v.image.artifact_hash)
      expect(wholeImageReads).toBe(0)
      expect(detailReads).toBe(0)
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      expect(new URL(page.url()).searchParams.has('build_review_goal')).toBe(false)
      expect(new URL(page.url()).searchParams.has('build_review_invocation')).toBe(false)
      if (process.env.EXWEB_FIXTURE_ROOT) writeFileSync(resolve(`output/playwright/exweb-build-review-handoff-${theme}.json`), JSON.stringify({
        repository: 'https://github.com/kunben-duck/exweb.git', commit: exwebCommit, adapter: 'tree_sitter_static',
        verified_at: new Date().toISOString(), goal_id: v.goal.id, command_id: v.step.tool_invocation_id,
        report_revision_id: v.report.revision_id, report_hash: v.report.revision_hash,
        image: v.image, publication: state.head, source_export_removed_before_investigation: true,
        navigation_writes: navigationWrites, target_executed: false, business_gold: false,
        review_whole_image_reads: wholeImageReads, review_runtime_detail_reads: detailReads,
        outgoing_workspace_whole_image_reads: transitionWholeImageReads,
        original_goal_unchanged: true, separate_review_and_publication_confirmed: true,
      }, null, 2))
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('exact saved review and reload preserve persistent model and tool audit', async ({ page, request }) => {
  test.setTimeout(180_000)
  const source = sourceExport()
  try {
    const v = await savedFindings(request, source)
    if (process.env.EXWEB_FIXTURE_ROOT) expect(v.image.code_member_count).toBe(725)
    expect((await request.patch(`${analysisApi}/v1/settings`, {
      headers: v.owner.headers, data: { theme: 'light', language: 'en' },
    })).ok()).toBeTruthy()
    const before = await reviewAudit(request, v.projectId, v.conversationId, v.owner.headers)
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token)
      localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    let writes = 0, wholeImageReads = 0, detailReads = 0, reports = 0
    page.on('request', (sent) => {
      if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(sent.method())) writes += 1
      const path = new URL(sent.url()).pathname
      if (path === v.reportPath) reports += 1
      if (path === `/v1/projects/${v.projectId}/system-image`) wholeImageReads += 1
      if (/\/agent-memory\/context$|\/agent-goals\/[^/]+\/explanation$|\/agent-swarms$/.test(path)) detailReads += 1
    })
    await page.goto(`/projects/${v.projectId}/knowledge?${new URLSearchParams({
      build_review_goal: v.goal.id, build_review_invocation: v.step.tool_invocation_id!,
    })}`)
    const dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
    await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
    await expect(dialog).toContainText(v.image.image_revision_id)
    await expect(dialog).toContainText(v.image.artifact_hash)
    await page.reload()
    await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
    const previousReports = reports
    await dialog.getByRole('button', { name: 'Reload revisions', exact: true }).click()
    await expect.poll(() => reports).toBeGreaterThan(previousReports)
    await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
    const after = await reviewAudit(request, v.projectId, v.conversationId, v.owner.headers)
    expect(after).toEqual(before)
    expect(writes).toBe(0)
    expect(wholeImageReads).toBe(0)
    expect(detailReads).toBe(0)
    const currentGoal = await v.read()
    expect(currentGoal).toEqual(v.completed)
    if (process.env.EXWEB_FIXTURE_ROOT) writeFileSync(resolve('output/playwright/exweb-build-review-read-only-audit.json'), JSON.stringify({
      repository: 'https://github.com/kunben-duck/exweb.git', commit: exwebCommit, adapter: 'tree_sitter_static',
      verified_at: new Date().toISOString(), goal_id: v.goal.id, image_revision_id: v.image.image_revision_id,
      image_artifact_hash: v.image.artifact_hash, code_member_count: v.image.code_member_count,
      audit_before: before, audit_after: after, navigation_writes: writes,
      navigation_model_calls: after.models.reduce((total, call) => total + call.model_calls, 0)
        - before.models.reduce((total, call) => total + call.model_calls, 0),
      navigation_llm_audit_records: after.models.length - before.models.length,
      navigation_tool_commands: after.tools.length - before.tools.length,
      review_whole_image_reads: wholeImageReads, review_runtime_detail_reads: detailReads,
      original_goal_unchanged: JSON.stringify(currentGoal) === JSON.stringify(v.completed),
      source_export_removed_before_investigation: true, target_executed: false, business_gold: false,
    }, null, 2))
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('denied original report hides findings and reload never falls back to another candidate', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const v = await savedFindings(request, source)
    const viewer = await analysisAccount(request)
    expect((await request.put(`${analysisApi}/v1/projects/${v.projectId}/members/${viewer.userId}`, {
      headers: v.owner.headers, data: { role: 'viewer' },
    })).ok()).toBeTruthy()
    analysisSourcePolicy(v.projectId, [viewer.userId])
    const gate = await openInvestigationProject(page, v.projectId, viewer.token)
    await gate.getByTestId('review-saved-build-findings').click()
    const dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
    await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
    let writes = 0
    page.on('request', (sent) => { if (sent.method() !== 'GET') writes += 1 })
    // A real source policy change is applied only to this private test database.
    analysisSourcePolicy(v.projectId, [])
    await dialog.getByRole('button', { name: 'Reload revisions', exact: true }).click()
    await expect(page.getByTestId('saved-build-review')).toHaveCount(0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    // The exact handoff independently rechecks current source permission.
    await expect(page.getByRole('alert').filter({ hasText: /could not be verified/ }).first()).toBeVisible()
    expect(writes).toBe(0)
    analysisSourcePolicy(v.projectId, [viewer.userId])
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('Chinese exact build review uses the same private reads and original target', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const v = await savedFindings(request, source)
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme: 'dark', language: 'zh' } })).ok()).toBeTruthy()
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token)
      localStorage.setItem('nasus.locale', 'zh')
    }, v.owner.token)
    let writes = 0, wholeImageReads = 0
    page.on('request', (sent) => {
      if (sent.method() !== 'GET') writes += 1
      if (new URL(sent.url()).pathname === `/v1/projects/${v.projectId}/system-image`) wholeImageReads += 1
    })
    await page.goto(`/projects/${v.projectId}/knowledge?${new URLSearchParams({
      build_review_goal: v.goal.id, build_review_invocation: v.step.tool_invocation_id!,
    })}`)
    const dialog = page.getByRole('dialog', { name: '画像版本', exact: true })
    await expect(dialog.getByTestId('saved-build-review')).toBeVisible()
    await expect(dialog).toContainText('尚待补齐的信息与证据')
    await expect(dialog).toContainText('本次调查没有提供受控环境中的实际执行证据。')
    await expect(dialog).toContainText(v.image.artifact_hash)
    await dialog.getByRole('button', { name: '查看画像发布状态', exact: true }).click()
    const targets = dialog.getByRole('combobox', { name: '发布目标基线', exact: true })
    await expect(targets.locator('option')).toHaveCount(2)
    await expect(targets.locator('option').last()).toHaveText(`原构建目标 · ${v.image.baseline_id}`)
    expect(writes).toBe(0)
    expect(wholeImageReads).toBe(0)
    expect(await v.read()).toEqual(v.completed)
    await page.screenshot({ path: resolve('output/playwright/build-review-handoff-zh-dark.png') })
  } finally { rmSync(source, { recursive: true, force: true }) }
})

test('wrong command, image or current target pins reveal no protected review', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const v = await savedFindings(request, source)
    const gate = await openInvestigationProject(page, v.projectId, v.owner.token)
    const href = await gate.getByTestId('review-saved-build-findings').getAttribute('href')
    const wrong = new URL(href!, 'http://localhost')
    wrong.searchParams.set('build_review_invocation', v.structureId)
    let writes = 0
    page.on('request', (sent) => { if (sent.method() !== 'GET') writes += 1 })
    await page.goto(wrong.pathname + wrong.search)
    await expect(page.getByTestId('build-review-handoff-unverified')).toBeVisible()
    await expect(page.getByTestId('saved-build-review')).toHaveCount(0)
    const path = `/v1/projects/${v.projectId}/system-image/revisions/${v.image.image_revision_id}`
    await page.route(`**${path}?*`, async (route) => {
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      const data = await response.json()
      data.revision.artifact_hash = 'sha256:' + 'f'.repeat(64)
      await route.fulfill({ response, json: data })
    })
    await page.goto(href!)
    await expect(page.getByTestId('build-review-handoff-unverified')).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.unroute(`**${path}?*`)
    const targetPath = `/v1/projects/${v.projectId}/system-image/build-targets/${v.image.baseline_id}`
    await page.route(`**${targetPath}`, async (route) => {
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      await route.fulfill({ response, json: { ...(await response.json()), target_version_id: 'different-version' } })
    })
    await page.goto(href!)
    await expect(page.getByTestId('build-review-handoff-unverified')).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(writes).toBe(0)
    expect(await v.read()).toEqual(v.completed)
  } finally { rmSync(source, { recursive: true, force: true }) }
})

for (const theme of ['light', 'dark']) {
  test(`explicit build completion assessment replays the exact report in ${theme}`, async ({ page, request }) => {
    test.setTimeout(240_000)
    const source = sourceExport()
    try {
      const v = await savedFindings(request, source)
      const locale = theme === 'light' ? 'zh' : 'en'
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, language }) => {
        localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', language)
      }, { token: v.owner.token, language: locale })
      const url = `/projects/${v.projectId}/knowledge?${new URLSearchParams({
        build_review_goal: v.goal.id, build_review_invocation: v.step.tool_invocation_id!,
      })}`
      let writes = 0
      page.on('request', (sent) => { if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(sent.method())) writes += 1 })
      const before = await reviewAudit(request, v.projectId, v.conversationId, v.owner.headers)
      await page.goto(url)
      const dialog = page.getByRole('dialog')
      const panel = dialog.getByRole('region', { name: locale === 'zh' ? '构建交付条件' : 'Build completion conditions', exact: true })
      await expect(panel).toBeVisible()
      expect(writes).toBe(0)
      const submitted = page.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().endsWith('/v1/tool-invocations')
        && response.request().postDataJSON()?.tool_id === 'query.system_image.build_completion.read')
      await panel.getByRole('button', { name: locale === 'zh' ? '核验交付条件' : 'Verify completion conditions', exact: true }).click()
      const response = await submitted
      expect(response.ok()).toBeTruthy()
      const command = await response.json()
      expect(command.status).toBe('completed')
      expect(command.input_payload).toMatchObject({ project_id: v.projectId, investigation_revision_id: v.report.revision_id,
        investigation_revision_hash: v.report.revision_hash, analysis_policy: 'committed_build', analyses: [] })
      expect(command.input_payload.expected_goal).toEqual(v.completed)
      await expect(panel.getByTestId('build-completion-report')).toBeVisible({ timeout: 60_000 })
      const reportPath = `/v1/projects/${v.projectId}/system-image/build-completions/${command.id}`
      const privateRead = await request.get(`${analysisApi}${reportPath}`, { headers: v.owner.headers })
      expect(privateRead.ok()).toBeTruthy()
      expect(privateRead.headers()['cache-control']).toBe('private, no-store')
      const report = await privateRead.json()
      expect(report).toMatchObject({ schema: 'nasus.image-build-completion.v2', state: 'blocked', candidate_ready: false,
        goal_completed: false, publication_authorized: false, execution_authorized: false,
        investigation_revision_id: v.report.revision_id, image_revision_id: v.image.image_revision_id })
      expect(report.code_analyses).not.toHaveLength(0)
      expect(report.code_analyses.every((analysis: { build_lineage_verified: boolean }) => analysis.build_lineage_verified)).toBe(true)
      expect(report.build_lineages).toHaveLength(1)
      expect(report.budget.cost_microusd).toBeNull()
      expect(report.critical_conflicts.count).toBeNull()
      await expect(panel).toContainText(locale === 'zh' ? '尚未满足候选交付条件' : 'Candidate delivery is blocked')
      await expect(panel).toContainText('full_plan_budget_unverified')
      await expect.poll(() => new URL(page.url()).searchParams.get('build_completion_invocation')).toBe(command.id)
      expect(writes).toBe(1)
      expect(await v.read()).toEqual(v.completed)

      await page.reload()
      await expect(panel.getByTestId('build-completion-report')).toBeVisible({ timeout: 60_000 })
      await panel.getByRole('button', { name: locale === 'zh' ? '重新核验原评估' : 'Reload completion assessment', exact: true }).click()
      await expect(panel.getByTestId('build-completion-report')).toBeVisible({ timeout: 60_000 })
      expect(writes).toBe(1)
      const after = await reviewAudit(request, v.projectId, v.conversationId, v.owner.headers)
      expect(after.models).toEqual(before.models)
      expect(after.tools.filter((tool) => !before.tools.some((old) => old.id === tool.id)).map((tool) => tool.id)).toEqual([command.id])
      expect(await v.read()).toEqual(v.completed)
      await page.setViewportSize({ width: 390, height: 844 })
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
      await panel.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/build-completion-panel-${theme}-mobile.png`) })
      const responsibilities = panel.getByRole('region', { name: locale === 'zh' ? '构建缺口责任' : 'Build gap responsibilities', exact: true })
      await expect(responsibilities.getByTestId('build-gap-responsibilities')).toBeVisible()
      await responsibilities.getByRole('button', { name: locale === 'zh' ? '登记或调整负责人' : 'Assign or reassign owners', exact: true }).click()
      const owners = responsibilities.getByRole('combobox', { name: locale === 'zh' ? '缺口负责人' : 'Gap owner', exact: true })
      const reasons = responsibilities.getByRole('textbox', { name: locale === 'zh' ? '责任登记说明' : 'Responsibility reason', exact: true })
      expect(await owners.count()).toBeGreaterThan(0)
      const prepare = responsibilities.getByRole('button', { name: locale === 'zh' ? '准备责任确认' : 'Prepare responsibility confirmation', exact: true })
      await expect(prepare).toBeDisabled()
      for (let i = 0; i < await owners.count(); i += 1) {
        await expect(owners.nth(i)).toBeEnabled()
        await owners.nth(i).selectOption(v.owner.userId)
        await reasons.nth(i).fill('Explicit responsibility for this original unresolved exweb build gap; no claim of resolution.')
      }
      // Lose the prepare acknowledgement in one theme and the confirmation
      // acknowledgement in the other. Both must recover by original key/ID.
      await page.route('**/v1/tool-invocations', async (route) => {
        if (locale !== 'zh' || route.request().method() !== 'POST'
            || route.request().postDataJSON()?.tool_id !== 'system_image.build.gaps.assign') return route.continue()
        const prepared = await route.fetch()
        expect(prepared.ok()).toBeTruthy()
        expect((await prepared.json()).status).toBe('waiting_confirmation')
        await route.abort('failed')
      })
      const preparedRequest = page.waitForEvent(locale === 'zh' ? 'requestfailed' : 'requestfinished', {
        predicate: (sent) => sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')
          && sent.postDataJSON()?.tool_id === 'system_image.build.gaps.assign',
      })
      await prepare.click()
      await preparedRequest
      const confirm = responsibilities.getByRole('button', { name: locale === 'zh' ? '确认缺口责任' : 'Confirm gap responsibilities', exact: true })
      if (locale === 'zh') {
        await expect(responsibilities.getByRole('alert')).toBeVisible()
        const recovered = page.waitForResponse((response) => response.request().method() === 'GET'
          && /\/v1\/tool-invocations\/[^/?]+$/.test(response.url()))
        await responsibilities.getByRole('button', { name: '重新核验责任记录', exact: true }).click()
        await recovered
      }
      await expect(confirm).toBeVisible()
      expect(writes).toBe(2)
      const ownershipPath = `${reportPath}/gap-ownership`
      expect((await (await request.get(`${analysisApi}${ownershipPath}`, { headers: v.owner.headers })).json()).history).toHaveLength(0)
      await page.reload()
      await expect(confirm).toBeVisible({ timeout: 60_000 })
      expect(writes).toBe(2)
      const assignmentId = new URL(page.url()).searchParams.get('build_gap_assignment_invocation')
      expect(assignmentId).toBeTruthy()
      if (locale === 'en') await page.route(`**/v1/tool-invocations/${assignmentId}/confirm`, async (route) => {
        const saved = await route.fetch()
        expect(saved.ok()).toBeTruthy()
        expect((await saved.json()).status).toBe('completed')
        await route.abort('failed')
      })
      const confirmedRequest = page.waitForEvent(locale === 'en' ? 'requestfailed' : 'requestfinished', {
        predicate: (sent) => sent.method() === 'POST' && sent.url().endsWith(`/v1/tool-invocations/${assignmentId}/confirm`),
      })
      await confirm.click()
      await confirmedRequest
      if (locale === 'en') {
        await expect(responsibilities.getByRole('alert')).toBeVisible()
        const recovered = page.waitForResponse((response) => response.request().method() === 'GET'
          && response.url().endsWith(`/v1/tool-invocations/${assignmentId}`))
        await responsibilities.getByRole('button', { name: 'Reload responsibilities', exact: true }).click()
        await recovered
      }
      await expect(responsibilities).toContainText(locale === 'zh' ? '责任已登记，原有缺口仍未解决。' : 'Responsibilities saved; all original gaps remain unresolved.')
      expect(writes).toBe(3)
      await page.reload()
      await expect(responsibilities).toContainText(locale === 'zh' ? '责任已登记，原有缺口仍未解决。' : 'Responsibilities saved; all original gaps remain unresolved.', { timeout: 60_000 })
      expect(writes).toBe(3)
      const ownershipRead = await request.get(`${analysisApi}${ownershipPath}`, { headers: v.owner.headers })
      expect(ownershipRead.ok()).toBeTruthy()
      const ownership = await ownershipRead.json()
      expect(ownership.history).toHaveLength(1)
      expect(ownership.gaps.every((gap: { owner_actor_id: string; ownership_status: string; resolution_status: string }) =>
        gap.owner_actor_id === v.owner.userId && gap.ownership_status === 'confirmed' && gap.resolution_status === 'unresolved')).toBe(true)
      expect(await (await request.get(`${analysisApi}${reportPath}`, { headers: v.owner.headers })).json()).toEqual(report)
      expect(await v.read()).toEqual(v.completed)
      const responsibilityAudit = await reviewAudit(request, v.projectId, v.conversationId, v.owner.headers)
      expect(responsibilityAudit.models).toEqual(before.models)
      expect(responsibilityAudit.tools.filter((tool) => !before.tools.some((old) => old.id === tool.id)).map((tool) => tool.id).sort())
        .toEqual([command.id, assignmentId].sort())
      const ownedPanel = responsibilities.getByRole('region', { name: locale === 'zh'
        ? '结合已确认责任的交付评估' : 'Completion with confirmed responsibilities', exact: true })
      await expect(ownedPanel).toBeVisible()
      let ownedCommandId = ''
      await page.route('**/v1/tool-invocations', async (route) => {
        if (route.request().method() !== 'POST' || !route.request().postDataJSON()?.input?.ownership_pin) return route.continue()
        const assessed = await route.fetch()
        expect(assessed.ok()).toBeTruthy()
        const submitted = await assessed.json()
        expect(submitted.status).toBe('completed')
        expect(submitted.input_payload.ownership_pin).toEqual({ completion_invocation_id: command.id,
          completion_report_hash: command.result.build_completion.report_hash,
          revision_id: ownership.revision_id, revision_hash: ownership.revision_hash })
        ownedCommandId = submitted.id
        if (locale === 'zh') await route.abort('failed')
        else await route.fulfill({ response: assessed })
      })
      const ownedSettled = page.waitForEvent(locale === 'zh' ? 'requestfailed' : 'requestfinished', {
        predicate: (sent) => sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')
          && Boolean(sent.postDataJSON()?.input?.ownership_pin),
      })
      await ownedPanel.getByRole('button', { name: locale === 'zh'
        ? '按这份责任记录重新评估' : 'Assess with this responsibility revision', exact: true }).click()
      await ownedSettled
      if (locale === 'zh') {
        await expect(ownedPanel.getByRole('alert')).toBeVisible()
        await ownedPanel.getByRole('button', { name: '重新核验原责任评估', exact: true }).click()
      }
      await expect(ownedPanel.getByTestId('owned-build-completion-report')).toBeVisible({ timeout: 60_000 })
      const ownedPath = `/v1/projects/${v.projectId}/system-image/build-completions/${ownedCommandId}`
      const ownedRead = await request.get(`${analysisApi}${ownedPath}`, { headers: v.owner.headers })
      expect(ownedRead.ok()).toBeTruthy()
      const ownedReport = await ownedRead.json()
      expect(ownedReport).toMatchObject({ schema: 'nasus.image-build-completion.v3', state: 'blocked',
        candidate_ready: false, goal_completed: false, execution_authorized: false, publication_authorized: false,
        ownership: { revision_id: ownership.revision_id, revision_hash: ownership.revision_hash } })
      expect(ownedReport.blockers).not.toContain('gap_ownership_unassigned')
      expect(ownedReport.blockers).toContain('full_plan_budget_unverified')
      expect(ownedReport.blockers).toContain('critical_conflicts_unverified')
      expect(ownedReport.gaps.every((gap: { owner_actor_id: string; resolution_status: string }) =>
        gap.owner_actor_id === v.owner.userId && gap.resolution_status === 'unresolved')).toBe(true)
      for (const key of ['source_scans', 'code_analyses', 'build_lineages', 'readiness', 'budget', 'goal_checkpoint']) {
        expect(ownedReport[key]).toEqual(report[key])
      }
      expect(writes).toBe(4)
      await page.reload()
      await expect(ownedPanel.getByTestId('owned-build-completion-report')).toBeVisible({ timeout: 60_000 })
      await ownedPanel.getByRole('button', { name: locale === 'zh'
        ? '重新核验原责任评估' : 'Reload responsibility-pinned assessment', exact: true }).click()
      await expect(ownedPanel.getByTestId('owned-build-completion-report')).toBeVisible({ timeout: 60_000 })
      expect(writes).toBe(4)
      expect(await v.read()).toEqual(v.completed)
      expect(await (await request.get(`${analysisApi}${reportPath}`, { headers: v.owner.headers })).json()).toEqual(report)
      const ownedAudit = await reviewAudit(request, v.projectId, v.conversationId, v.owner.headers)
      expect(ownedAudit.models).toEqual(before.models)
      expect(ownedAudit.tools.filter((tool) => !before.tools.some((old) => old.id === tool.id)).map((tool) => tool.id).sort())
        .toEqual([command.id, assignmentId, ownedCommandId].sort())
      await ownedPanel.scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(`output/playwright/owned-build-completion-${theme}-mobile.png`) })
      await responsibilities.scrollIntoViewIfNeeded()
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
      await page.screenshot({ path: resolve(`output/playwright/build-gap-ownership-${theme}-mobile.png`) })
      if (process.env.EXWEB_FIXTURE_ROOT) writeFileSync(resolve(`output/playwright/exweb-build-completion-panel-${theme}.json`), JSON.stringify({
        repository: 'https://github.com/kunben-duck/exweb.git', commit: exwebCommit, adapter: 'tree_sitter_static',
        goal_id: v.goal.id, report, receipt: command.result.build_completion, assessment_command_id: command.id,
        verified_at: new Date().toISOString(), locale, theme, viewport_width: 390, assessment_posts: 1,
        responsibility_posts: 2, ownership, responsibility_command_id: assignmentId,
        owned_assessment_posts: 1, owned_report: ownedReport, owned_assessment_command_id: ownedCommandId,
        original_goal_unchanged: true, replay_new_model_calls: 0, target_executed: false, business_gold: false,
      }, null, 2))
      // Denial on a later private read must hide the already-rendered report.
      await page.route(`**${reportPath}`, (route) => route.fulfill({ status: 403,
        contentType: 'application/json', body: JSON.stringify({ error: { message: 'Source access denied' } }) }))
      await panel.getByRole('button', { name: locale === 'zh' ? '重新核验原评估' : 'Reload completion assessment', exact: true }).click()
      await expect(panel.getByRole('alert')).toBeVisible()
      await expect(panel.getByTestId('build-completion-report')).toHaveCount(0)
      expect(writes).toBe(4)
      await dialog.getByRole('button', { name: locale === 'zh' ? '关闭' : 'Close', exact: true }).click()
      expect(new URL(page.url()).searchParams.has('build_completion_request')).toBe(false)
      expect(new URL(page.url()).searchParams.has('build_completion_invocation')).toBe(false)
      expect(new URL(page.url()).searchParams.has('build_gap_assignment_request')).toBe(false)
      expect(new URL(page.url()).searchParams.has('build_gap_assignment_invocation')).toBe(false)
      expect(new URL(page.url()).searchParams.has('build_owned_completion_request')).toBe(false)
      expect(new URL(page.url()).searchParams.has('build_owned_completion_invocation')).toBe(false)
    } finally { rmSync(source, { recursive: true, force: true }) }
  })
}

test('a lost completion acknowledgement is recovered without another POST, even after refresh', async ({ page, request }) => {
  const source = analysisSource()
  try {
    const v = await savedFindings(request, source)
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    let posts = 0
    page.on('request', (sent) => { if (sent.method() === 'POST') posts += 1 })
    await page.route('**/v1/tool-invocations', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      expect(route.request().postDataJSON().tool_id).toBe('query.system_image.build_completion.read')
      const result = await route.fetch()
      expect(result.ok()).toBeTruthy()
      expect((await result.json()).status).toBe('completed')
      await route.abort('failed')
    })
    await page.goto(`/projects/${v.projectId}/knowledge?${new URLSearchParams({
      build_review_goal: v.goal.id, build_review_invocation: v.step.tool_invocation_id!,
    })}`)
    const panel = page.getByRole('region', { name: 'Build completion conditions', exact: true })
    await panel.getByRole('button', { name: 'Verify completion conditions', exact: true }).click()
    await expect(panel.getByTestId('build-completion-report')).toBeVisible()
    expect(posts).toBe(1)
    const id = new URL(page.url()).searchParams.get('build_completion_invocation')
    expect(id).toBeTruthy()
    await page.reload()
    await expect(panel.getByTestId('build-completion-report')).toBeVisible()
    expect(new URL(page.url()).searchParams.get('build_completion_invocation')).toBe(id)
    expect(posts).toBe(1)
    expect(await v.read()).toEqual(v.completed)
  } finally { rmSync(source, { recursive: true, force: true }) }
})
