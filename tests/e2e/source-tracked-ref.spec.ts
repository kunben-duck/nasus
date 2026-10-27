import { expect, test } from '@playwright/test'
import { execFileSync, spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { analysisAccount, analysisApi } from './source-analysis-fixtures'

async function trackedOrigin() {
  const root = mkdtempSync(join(tmpdir(), 'nasus-tracked-ref-browser-'))
  const repository = join(root, 'repo')
  mkdirSync(repository)
  const env = { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' }
  const git = (...args: string[]) => execFileSync('git', ['-c', 'core.hooksPath=/dev/null',
    '-c', 'commit.gpgsign=false', '-C', repository, ...args], { env, encoding: 'utf8' }).trim()
  git('init')
  git('branch', '-M', 'main')
  writeFileSync(join(repository, 'checkout.py'), 'def checkout():\n    return "release"\n')
  writeFileSync(join(repository, 'README.md'), '# Controlled branch browser fixture\n')
  git('add', '.')
  git('-c', 'user.name=Nasus Test', '-c', 'user.email=nasus-test@example.com', 'commit', '-m', 'release fixture')
  const releaseCommit = git('rev-parse', 'HEAD')
  git('branch', 'release')
  writeFileSync(join(repository, 'main-only.txt'), 'Not part of the selected release branch.\n')
  git('add', '.')
  git('-c', 'user.name=Nasus Test', '-c', 'user.email=nasus-test@example.com', 'commit', '-m', 'default branch fixture')
  const mainCommit = git('rev-parse', 'HEAD')
  const reservation = createServer()
  await new Promise<void>((resolve, reject) => {
    reservation.once('error', reject)
    reservation.listen(0, '127.0.0.1', resolve)
  })
  const address = reservation.address()
  if (!address || typeof address === 'string') throw new Error('Private Git fixture port unavailable')
  await new Promise<void>((resolve, reject) => reservation.close((error) => error ? reject(error) : resolve()))
  const daemon = spawn('git', ['daemon', '--export-all', '--reuseaddr', '--listen=127.0.0.1',
    `--port=${address.port}`, `--base-path=${root}`, root], { env, stdio: 'ignore' })
  const uri = `git://127.0.0.1:${address.port}/repo`
  const close = async () => {
    if (daemon.exitCode === null && daemon.signalCode === null) {
      const exited = new Promise<void>((resolve) => daemon.once('exit', () => resolve()))
      daemon.kill('SIGTERM')
      await exited
    }
    rmSync(root, { recursive: true, force: true })
  }
  try {
    await expect.poll(() => {
      try { return git('ls-remote', uri, 'refs/heads/release').split(/\s/)[0] } catch { return '' }
    }, { timeout: 10_000 }).toBe(releaseCommit)
  } catch (error) { await close(); throw error }
  return { uri, releaseCommit, mainCommit, close }
}

for (const [theme, locale] of [['light', 'en'], ['dark', 'zh']]) {
  test(`tracked branch input captures the nondefault commit through the original goal in ${theme}/${locale}`, async ({ page, request }) => {
    const origin = await trackedOrigin()
    try {
      const owner = await analysisAccount(request)
      const created = await request.post(`${analysisApi}/v1/projects`, { headers: owner.headers,
        data: { name: `Tracked source ${randomUUID()}` } })
      expect(created.ok()).toBeTruthy()
      const projectId = (await created.json()).id
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: owner.headers, data: { theme, language: locale } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => {
        localStorage.setItem('nasus_api_token', token)
        localStorage.setItem('nasus.locale', locale)
      }, { token: owner.token, locale })
      if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 })
      const commands: { tool_id: string; input: { source_specs?: { tracked_ref?: string }[] } }[] = []
      page.on('request', (sent) => {
        if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) commands.push(sent.postDataJSON())
      })
      await page.goto(`/projects/${projectId}`)
      await page.getByTestId('agent-card-system-image-builder').click()
      const panel = page.getByTestId('source-binding-panel')
      await expect(panel).toBeVisible()
      const ref = panel.getByTestId('source-code-tracked-ref')
      await expect(ref).toHaveValue('')
      await expect(ref).toHaveAttribute('placeholder', 'refs/heads/main')
      await panel.getByTestId('source-code-input').fill(origin.uri)
      await ref.fill('refs/heads/release')
      await panel.getByTestId('source-us-input').fill('')
      await panel.getByTestId('source-tests-input').fill('')
      expect(await ref.evaluate((element) => {
        const field = getComputedStyle(element), body = getComputedStyle(document.body)
        return { themeBackground: field.backgroundColor === body.backgroundColor,
          themeText: field.color === body.color, themeFont: field.fontFamily === body.fontFamily,
          stackedLabel: getComputedStyle(element.parentElement!).display === 'grid' }
      })).toEqual({ themeBackground: true, themeText: true, themeFont: true, stackedLabel: true })
      expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      const before = await (await request.get(`${analysisApi}/v1/conversations?space_type=project&space_id=${projectId}`,
        { headers: owner.headers })).json()
      await expect.poll(async () => {
        const snapshot = await (await request.get(`${analysisApi}/v1/conversations/${before[0].id}`, { headers: owner.headers })).json()
        return snapshot.agent_goals[0]?.pause_reason
      }).toBe('missing_captured_code')
      const waiting = (await (await request.get(`${analysisApi}/v1/conversations/${before[0].id}`, { headers: owner.headers })).json()).agent_goals[0]
      expect(waiting.pause_reason).toBe('missing_captured_code')
      await panel.getByTestId('build-system-image-with-sources').click()
      await expect(page.getByTestId('image-build-execution-budget')).toBeVisible({ timeout: 30_000 })
      expect(commands.map((item) => item.tool_id)).toEqual(['system_image.sources.register', 'system_image.sources.ingest'])
      expect(commands[0].input.source_specs).toEqual([{ source_type: 'code', source_uri: origin.uri,
        label: 'Code repository', tracked_ref: 'refs/heads/release' }])
      const sourceResponse = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image?view=working`, { headers: owner.headers })
      expect(sourceResponse.ok()).toBeTruthy()
      const allSources = (await sourceResponse.json()).sources
      const sources = allSources.filter((item: { source_type: string }) => item.source_type === 'code')
      expect(sources).toHaveLength(1)
      expect(allSources.filter((item: { source_type: string }) => item.source_type !== 'code')).toHaveLength(2)
      expect(allSources.filter((item: { source_type: string }) => item.source_type !== 'code')
        .every((item: { registered_at: string | null; ingestion_status: string; content_ref: string | null }) =>
          item.registered_at === null && item.ingestion_status === 'pending' && item.content_ref === null)).toBe(true)
      expect(sources[0].tracked_ref).toBe('refs/heads/release')
      expect(sources[0].file_count).toBe(2)
      expect(sources[0].evidence_refs).toContain(`git:revision:${origin.releaseCommit}`)
      expect(sources[0].evidence_refs).not.toContain(`git:revision:${origin.mainCommit}`)
      expect(readdirSync(join(process.env.NASUS_E2E_STATE_DIR!, 'source-cache', 'git'))
        .filter((entry) => /^[a-f0-9]{64}$/.test(entry)).length).toBeGreaterThan(0)
      const current = await (await request.get(`${analysisApi}/v1/conversations/${before[0].id}`, { headers: owner.headers })).json()
      expect(current.agent_goals).toHaveLength(1)
      expect(current.agent_goals[0].id).toBe(waiting.id)
      expect(current.agent_goals[0].pause_reason).toBe('waiting_confirmation')
      await expect(ref).toHaveValue('refs/heads/release')
      expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await panel.screenshot({ path: resolve(`output/playwright/source-tracked-ref-${theme}-${locale}.png`) })
    } finally { await origin.close() }
  })
}
