import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { analysisAccount, analysisApi } from './source-analysis-fixtures'

const revision = 'fe5827f6b76f77ef34918d8b452ee823142332dc'
const repository = 'https://github.com/kunben-duck/exweb.git'

for (const mode of ['local checkout', 'HTTPS and commit SHA', 'HTTPS with review drafts'] as const) test(`Build imports fixed exweb via ${mode} and preserves structural consent`, async ({ page, request }) => {
  const remote = mode !== 'local checkout', withDrafts = mode === 'HTTPS with review drafts'
  test.skip(remote ? process.env.EXWEB_REMOTE_GIT !== '1' : !process.env.EXWEB_FIXTURE_ROOT,
    remote ? 'Opt in to the real GitHub fetch with EXWEB_REMOTE_GIT=1' : 'Opt in with an authorized fixed exweb checkout')
  test.setTimeout(120_000)
  const root = remote ? undefined : resolve(process.env.EXWEB_FIXTURE_ROOT!)
  const verifyCheckout = (path: string) => {
    const git = (...args: string[]) => execFileSync('git', ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', path, ...args],
      { encoding: 'utf8' }).trim()
    expect(git('rev-parse', 'HEAD')).toBe(revision)
    expect(git('status', '--porcelain', '--untracked-files=all')).toBe('')
  }
  if (root) verifyCheckout(root)

  const owner = await analysisAccount(request)
  await page.addInitScript((token) => {
    localStorage.setItem('nasus_api_token', token)
    localStorage.setItem('nasus.locale', 'en')
  }, owner.token)
  await page.goto('/build')
  const prompt = page.getByTestId('build-agent-input')
  const send = async (text: string) => {
    await expect(prompt).toBeEnabled()
    await prompt.fill(text)
    await page.getByTestId('build-agent-submit').click()
    await expect(page.locator('.build-message.user').getByText(text, { exact: true }).last()).toBeVisible()
    await expect(page.getByTestId('build-agent-stop')).toHaveCount(0, { timeout: 75_000 })
  }
  await send('Help me build a system image')
  await send('Project name: exweb fixed-source trial')
  await expect(page).toHaveURL(/\/build$/)
  const projectLink = page.getByRole('link', { name: 'View system image', exact: true })
  const projectId = (await projectLink.getAttribute('href'))!.split('/')[2]
  await send(`Code ${root ?? repository}\ncommit ${revision}`)
  if (withDrafts) {
    const trial = resolve('docs/examples/exweb')
    await page.getByTestId('build-upload-us_doc').setInputFiles(resolve(trial, 'session-isolation-draft.md'))
    await expect(page.getByRole('status').filter({ hasText: 'Uploading sources...' })).toHaveCount(0, { timeout: 30_000 })
    await page.getByTestId('build-upload-test_asset').setInputFiles(resolve(trial, 'session-isolation-cases.csv'))
    await expect(page.getByRole('status').filter({ hasText: 'Uploading sources...' })).toHaveCount(0, { timeout: 30_000 })
  }
  await send('skip optional sources')
  await page.getByTestId('build-intake-confirm').click()
  const gate = page.getByTestId('build-progress')
  await expect(gate.getByTestId('build-goal-continue')).toBeEnabled({ timeout: 75_000 })

  const conversationList = await request.get(`${analysisApi}/v1/conversations?space_type=build&space_id=build`,
    { headers: owner.headers })
  expect(conversationList.ok()).toBeTruthy()
  const conversations = await conversationList.json()
  expect(conversations).toHaveLength(1)
  const conversation = await request.get(`${analysisApi}/v1/conversations/${conversations[0].id}`, { headers: owner.headers })
  expect(conversation.ok()).toBeTruthy()
  const [goal] = (await conversation.json()).agent_goals
  expect(goal).toMatchObject({ goal_template: 'system_image_build', pause_reason: 'waiting_confirmation' })
  const planId = goal.target_refs.find((ref: string) => ref.startsWith('build_plan:')).slice('build_plan:'.length)
  const readPlan = () => request.get(`${analysisApi}/v1/projects/${projectId}/system-image/build-plans/${planId}`,
    { headers: owner.headers })
  const before = await readPlan()
  expect(before.ok()).toBeTruthy()
  const pending = await before.json()
  expect(pending.proposal.intent.sources.map((item: { source_type: string }) => item.source_type).sort())
    .toEqual(withDrafts ? ['code', 'test_asset', 'us_doc'] : ['code'])
  expect(pending.structural_artifacts).toEqual([])
  expect(pending.execution_authorizations).toEqual([])

  await gate.getByTestId('build-goal-continue').click()
  await expect(gate.getByText('Candidate image available. Official publication still requires review.')).toBeVisible({ timeout: 75_000 })
  const after = await readPlan()
  expect(after.ok()).toBeTruthy()
  const saved = await after.json()
  expect(saved.structural_artifacts).toHaveLength(1)
  expect(saved.execution_authorizations).toHaveLength(1)
  expect(saved.execution_authorizations[0]).toMatchObject({ goal_id: goal.id, publication_allowed: false })
  const finalConversation = await (await request.get(`${analysisApi}/v1/conversations/${conversations[0].id}`, { headers: owner.headers })).json()
  for (const tool of ['project.create', 'system_image.sources.register', 'system_image.sources.ingest']) {
    expect(finalConversation.tool_invocations.filter((item: { tool_id: string }) => item.tool_id === tool)).toHaveLength(1)
  }
  await page.reload()
  await expect(gate.getByText('Candidate image available. Official publication still requires review.')).toBeVisible()
  await expect.poll(() => page.locator('.build-message-list').evaluate((node) =>
    node.scrollHeight - node.scrollTop - node.clientHeight)).toBeLessThan(3)
  await expect(page.locator('.project-gallery')).toHaveCount(0)
  if (root) verifyCheckout(root)
  if (remote) {
    const captured = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image?view=working`, { headers: owner.headers })
    expect(captured.ok()).toBeTruthy()
    const working = await captured.json()
    const source = working.sources.find((item: { source_type: string }) => item.source_type === 'code')
    expect(source).toMatchObject({ source_uri: repository, tracked_ref: revision, file_count: 126 })
    expect(source.evidence_refs).toContain(`git:revision:${revision}`)
    if (withDrafts) {
      const capturedKinds = working.source_manifest.members.filter((item: { status: string }) => item.status === 'captured')
        .map((item: { source_type: string }) => item.source_type).sort()
      expect(capturedKinds).toEqual(['code', 'test_asset', 'us_doc'])
    }
  }
})
