import { expect, test, type APIRequestContext, type Locator } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { appendFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { analysisAccount, analysisApi, analysisSource, captureAnalysis } from './source-analysis-fixtures'

async function inspectScrollableDialog(dialog: Locator) {
  const dimensions = await dialog.evaluate((element) => {
    const bounds = element.getBoundingClientRect(), body = element.querySelector('.evidence-inspector-body')!
    return { left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom,
      viewportWidth: innerWidth, viewportHeight: innerHeight, scrollWidth: body.scrollWidth,
      clientWidth: body.clientWidth, scrollbar: getComputedStyle(body).scrollbarWidth,
      webkitScrollbar: getComputedStyle(body, '::-webkit-scrollbar').display }
  })
  expect(dimensions.left).toBeGreaterThanOrEqual(0)
  expect(dimensions.right).toBeLessThanOrEqual(dimensions.viewportWidth)
  expect(dimensions.top).toBeGreaterThanOrEqual(0)
  expect(dimensions.bottom).toBeLessThanOrEqual(dimensions.viewportHeight)
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
  expect(dimensions.scrollbar).toBe('none')
  expect(dimensions.webkitScrollbar).toBe('none')
}

async function fixture(request: APIRequestContext, code: string) {
  const root = mkdtempSync(join(tmpdir(), 'nasus-refresh-browser-'))
  const us = join(root, 'requirements.md'), cases = join(root, 'cases.md')
  writeFileSync(us, '# US-REFRESH Browser protocol fixture\nDescription: Synthetic validation, not business approval.\n')
  writeFileSync(cases, '# TC-REFRESH Browser protocol fixture\nReferences: US-REFRESH\nExpected result: Synthetic validation only.\n')
  const v = await captureAnalysis(request, code)
  expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers,
    data: { theme: 'light', language: 'en' } })).ok()).toBeTruthy()
  await v.invoke('system_image.sources.register', { source_specs: [
    { source_type: 'us_doc', source_uri: us }, { source_type: 'test_asset', source_uri: cases }] })
  await v.invoke('system_image.sources.ingest')
  await v.invoke('system_image.context.materialize')
  const url = `${analysisApi}/v1/projects/${v.projectId}/system-image?view=working`
  const read = async () => {
    const response = await request.get(url, { headers: v.owner.headers })
    expect(response.ok()).toBeTruthy()
    return response.json()
  }
  const before = await read()
  return { ...v, root, us, cases, before, read }
}

for (const [theme, locale] of [['light', 'en'], ['dark', 'zh']]) {
  test(`selected source refresh preserves unselected archives and never builds or publishes in ${theme}/${locale}`, async ({ page, request }) => {
    const code = analysisSource(), v = await fixture(request, code)
    try {
      expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers, data: { theme, language: locale } })).ok()).toBeTruthy()
      await page.addInitScript(({ token, locale }) => {
        localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', locale)
      }, { token: v.owner.token, locale })
      if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 })
      const commands: Record<string, unknown>[] = []
      page.on('request', (sent) => {
        if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) commands.push(sent.postDataJSON())
      })
      await page.goto(`/projects/${v.projectId}/knowledge`)
      const heading = locale === 'en' ? 'Refresh working sources' : '更新工作区来源'
      await page.getByRole('button', { name: heading, exact: true }).click()
      const dialog = page.getByRole('dialog', { name: heading, exact: true })
      const submit = dialog.getByRole('button', { name: locale === 'en' ? 'Refresh selected sources' : '更新选中的来源', exact: true })
      await expect(submit).toBeDisabled()
      await expect(dialog.getByRole('checkbox')).toHaveCount(3)
      expect(commands).toEqual([])
      const selected = v.before.sources.find((item: { source_type: string }) => item.source_type === 'us_doc')
      const unselected = v.before.sources.filter((item: { id: string }) => item.id !== selected.id)
      appendFileSync(v.us, '\nControlled selected-source browser change.\n')
      rmSync(code, { recursive: true, force: true }); rmSync(v.cases)
      await dialog.locator(`[data-source-id="${selected.id}"]`).getByRole('checkbox').check()
      await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
      await expect(dialog.locator(`[data-source-id="${selected.id}"]`).getByRole('checkbox')).toBeChecked()
      const complete = page.waitForResponse((response) => response.request().method() === 'POST'
        && response.url().endsWith('/v1/tool-invocations'))
      await submit.click()
      const response = await complete
      expect(response.ok()).toBeTruthy()
      const command = await response.json()
      expect(command.status).toBe('completed')
      expect(command.input_payload).toMatchObject({ project_id: v.projectId, source_ids: [selected.id],
        expected_manifest_id: v.before.source_manifest.manifest_id, expected_manifest_hash: v.before.source_manifest.content_hash })
      await expect(dialog).toContainText(locale === 'en' ? 'Selected sources were refreshed.' : '所选来源已更新。')
      await expect(dialog.getByRole('checkbox')).toHaveCount(3)
      await expect(submit).toBeDisabled()
      await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
      const after = await v.read()
      expect(after.sources.filter((item: { id: string }) => item.id !== selected.id)).toEqual(unselected)
      expect(after.source_manifest.manifest_id).not.toBe(v.before.source_manifest.manifest_id)
      expect(after.objects).toEqual(v.before.objects)
      expect(after.read_state).toEqual(v.before.read_state)
      expect(commands.map((value) => value.tool_id)).toEqual(['system_image.sources.ingest'])
      expect(JSON.stringify(command.result)).not.toContain(v.root)
      await dialog.getByRole('button', { name: locale === 'en' ? 'Reload working sources' : '重新读取来源', exact: true }).click()
      await expect(dialog.getByRole('checkbox', { checked: true })).toHaveCount(0)
      await expect(submit).toBeDisabled()
      await inspectScrollableDialog(dialog)
      mkdirSync(resolve('output/playwright'), { recursive: true })
      await page.screenshot({ path: resolve(`output/playwright/source-refresh-${theme}-${locale}.png`) })
    } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
  })
}

test('lost refresh response recovers the original canonical command using GET only', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    let posts = 0
    await page.route('**/v1/tool-invocations', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      posts++
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      expect((await response.json()).status).toBe('completed')
      await route.abort('failed')
    })
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    await dialog.getByRole('checkbox').first().check()
    await dialog.getByRole('button', { name: 'Refresh selected sources', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Check the original command; do not resend it.')
    await expect(dialog.getByRole('button', { name: 'Reload working sources', exact: true })).toBeDisabled()
    await dialog.getByRole('button', { name: 'Check original refresh command', exact: true }).click()
    await expect(dialog).toContainText('Selected sources were refreshed.')
    await expect(dialog.getByRole('button', { name: 'Check original refresh command', exact: true })).toHaveCount(0)
    expect(posts).toBe(1)
  } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

test('reload and route changes restore the original refresh pointer without resending or restoring selection consent', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    let posts = 0, discoveries = 0, details = 0, originalId = ''
    page.on('request', (sent) => {
      if (sent.method() === 'GET' && sent.url().includes('/v1/tool-invocations/resolve?')) discoveries++
      if (sent.method() === 'GET' && new URL(sent.url()).pathname === `/v1/tool-invocations/${originalId}`) details++
    })
    await page.route('**/v1/tool-invocations', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      posts++
      const response = await route.fetch(), command = await response.json()
      expect(response.ok()).toBeTruthy(); expect(command.status).toBe('completed')
      originalId = command.id
      await route.abort('failed')
    })
    const open = async () => {
      await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
      return page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    }
    await page.goto(`/projects/${v.projectId}/knowledge`)
    let dialog = await open()
    await expect(dialog.getByRole('checkbox')).toHaveCount(3)
    await dialog.getByRole('checkbox').first().check()
    await dialog.getByRole('button', { name: 'Refresh selected sources', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Check the original command; do not resend it.')
    await page.reload()
    dialog = await open()
    await expect(dialog).toContainText('An earlier refresh request was found in this tab.')
    await expect(dialog.getByRole('button', { name: 'Reload working sources', exact: true })).toBeDisabled()
    await expect(dialog.getByRole('button', { name: 'Refresh selected sources', exact: true })).toBeDisabled()
    expect(posts).toBe(1); expect(discoveries).toBe(0); expect(details).toBe(0)
    await dialog.getByRole('button', { name: 'Check original refresh command', exact: true }).click()
    await expect(dialog).toContainText('Selected sources were refreshed.')
    await expect(dialog).toContainText(originalId)
    expect(discoveries).toBe(1); expect(details).toBe(1)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await page.goto('/build')
    await page.goto(`/projects/${v.projectId}/knowledge`)
    dialog = await open()
    await expect(dialog).toContainText('An earlier refresh request was found in this tab.')
    expect(posts).toBe(1); expect(discoveries).toBe(1); expect(details).toBe(1)
    await dialog.getByRole('button', { name: 'Check original refresh command', exact: true }).click()
    await expect(dialog).toContainText(originalId)
    expect(discoveries).toBe(1); expect(details).toBe(2)
    await dialog.getByRole('button', { name: 'Reload working sources', exact: true }).click()
    await expect(dialog.getByRole('checkbox', { checked: true })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Refresh selected sources', exact: true })).toBeDisabled()
    expect(await page.evaluate(({ actor, project }) => sessionStorage.getItem('nasus.source-refresh.v1:' + JSON.stringify([actor, project])),
      { actor: v.owner.userId, project: v.projectId })).toBeNull()
    expect(posts).toBe(1)
  } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

for (const failure of ['corrupt', 'unavailable']) {
  test(`${failure} recovery storage prevents dispatch and does not invent or delete a request`, async ({ page, request }) => {
    const code = analysisSource(), v = await fixture(request, code)
    try {
      await page.addInitScript(({ token, actor, project, failure }) => {
        localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
        if (failure === 'corrupt') sessionStorage.setItem('nasus.source-refresh.v1:' + JSON.stringify([actor, project]), '{')
        else Object.defineProperty(window, 'sessionStorage', { get: () => { throw new Error('Fixture: storage disabled') } })
      }, { token: v.owner.token, actor: v.owner.userId, project: v.projectId, failure })
      let posts = 0
      page.on('request', (sent) => { if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) posts++ })
      await page.goto(`/projects/${v.projectId}/knowledge`)
      await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
      await expect(dialog.getByRole('alert')).toContainText('The local refresh recovery record could not be verified.')
      await expect(dialog.getByRole('checkbox')).toHaveCount(3)
      for (const checkbox of await dialog.getByRole('checkbox').all()) await expect(checkbox).toBeDisabled()
      await expect(dialog.getByRole('button', { name: 'Refresh selected sources', exact: true })).toBeDisabled()
      await dialog.getByRole('button', { name: 'Reload working sources', exact: true }).click()
      await expect(dialog.getByRole('alert')).toBeVisible()
      expect(posts).toBe(0)
      if (failure === 'corrupt') expect(await page.evaluate(({ actor, project }) =>
        sessionStorage.getItem('nasus.source-refresh.v1:' + JSON.stringify([actor, project])),
      { actor: v.owner.userId, project: v.projectId })).toBe('{')
    } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
  })
}

test('storage quota failure after source selection stops before canonical dispatch', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    let posts = 0
    page.on('request', (sent) => { if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) posts++ })
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    await dialog.getByRole('checkbox').first().check()
    await expect(dialog.getByRole('button', { name: 'Refresh selected sources', exact: true })).toBeEnabled()
    await page.evaluate(() => {
      const original = Storage.prototype.setItem
      Storage.prototype.setItem = function (key: string, value: string) {
        if (key.startsWith('nasus.source-refresh.v1:')) throw new DOMException('Fixture: quota exhausted', 'QuotaExceededError')
        return original.call(this, key, value)
      }
    })
    await dialog.getByRole('button', { name: 'Refresh selected sources', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('No new refresh was sent.')
    await expect(dialog.getByRole('button', { name: 'Refresh selected sources', exact: true })).toBeDisabled()
    expect(posts).toBe(0)
    expect(await page.evaluate(() => Object.keys(sessionStorage).filter((key) => key.startsWith('nasus.source-refresh.v1:')))).toEqual([])
  } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

test('account switching on the same project never restores another account refresh pointer', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  try {
    const member = await analysisAccount(request)
    expect((await request.put(`${analysisApi}/v1/projects/${v.projectId}/members/${member.userId}`, {
      headers: v.owner.headers, data: { role: 'tester' },
    })).ok()).toBeTruthy()
    const requestKey = 'owner-refresh-' + randomUUID(), input = { project_id: v.projectId,
      source_ids: [v.before.sources[0].id], expected_manifest_id: v.before.source_manifest.manifest_id,
      expected_manifest_hash: v.before.source_manifest.content_hash }
    const response = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: v.owner.headers,
      data: { tool_id: 'system_image.sources.ingest', idempotency_key: requestKey, input } })
    expect(response.ok()).toBeTruthy()
    const command = await response.json()
    expect(command.status).toBe('completed')
    const key = 'nasus.source-refresh.v1:' + JSON.stringify([v.owner.userId, v.projectId])
    const raw = JSON.stringify({ schema: 'nasus.source-refresh-recovery.v1', actor_id: v.owner.userId,
      input, requestKey, commandId: command.id })
    await page.addInitScript(({ token, key, raw }) => {
      if (!localStorage.getItem('nasus_api_token')) localStorage.setItem('nasus_api_token', token)
      localStorage.setItem('nasus.locale', 'en')
      if (!sessionStorage.getItem(key)) sessionStorage.setItem(key, raw)
    }, { token: v.owner.token, key, raw })
    let posts = 0, recoveryReads = 0
    page.on('request', (sent) => {
      if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) posts++
      if (sent.method() === 'GET' && sent.url().includes('/v1/tool-invocations')) recoveryReads++
    })
    const open = async () => {
      await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
      return page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    }
    await page.goto(`/projects/${v.projectId}/knowledge`)
    let dialog = await open()
    await expect(dialog).toContainText(requestKey)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await page.evaluate((token) => localStorage.setItem('nasus_api_token', token), member.token)
    await page.reload()
    dialog = await open()
    await expect(dialog.getByRole('checkbox')).toHaveCount(3)
    await expect(dialog.getByRole('checkbox', { checked: true })).toHaveCount(0)
    await expect(dialog).not.toContainText(requestKey)
    await expect(dialog.getByRole('button', { name: 'Check original refresh command', exact: true })).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await page.evaluate((token) => localStorage.setItem('nasus_api_token', token), v.owner.token)
    await page.reload()
    dialog = await open()
    await expect(dialog).toContainText(requestKey)
    expect(await page.evaluate((key) => sessionStorage.getItem(key), key)).toBe(raw)
    expect(posts).toBe(0); expect(recoveryReads).toBe(0)
    await dialog.getByRole('button', { name: 'Check original refresh command', exact: true }).click()
    await expect(dialog).toContainText(command.id)
    expect(recoveryReads).toBe(1); expect(posts).toBe(0)
  } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

test('a saved refresh pointer remains read-only and scrollable in dark Chinese mobile layout', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  try {
    expect((await request.patch(`${analysisApi}/v1/settings`, { headers: v.owner.headers,
      data: { theme: 'dark', language: 'zh' } })).ok()).toBeTruthy()
    const requestKey = 'mobile-refresh-' + randomUUID(), input = { project_id: v.projectId,
      source_ids: [v.before.sources[0].id], expected_manifest_id: v.before.source_manifest.manifest_id,
      expected_manifest_hash: v.before.source_manifest.content_hash }
    const response = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: v.owner.headers,
      data: { tool_id: 'system_image.sources.ingest', idempotency_key: requestKey, input } })
    expect(response.ok()).toBeTruthy()
    const command = await response.json()
    expect(command.status).toBe('completed')
    await page.addInitScript(({ token, actor, project, record }) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'zh')
      sessionStorage.setItem('nasus.source-refresh.v1:' + JSON.stringify([actor, project]), JSON.stringify(record))
    }, { token: v.owner.token, actor: v.owner.userId, project: v.projectId,
      record: { schema: 'nasus.source-refresh-recovery.v1', actor_id: v.owner.userId, input, requestKey, commandId: command.id } })
    await page.setViewportSize({ width: 390, height: 844 })
    let writes = 0
    page.on('request', (sent) => { if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) writes++ })
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: '更新工作区来源', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '更新工作区来源', exact: true })
    await expect(dialog).toContainText('此标签页保留了先前的更新请求。')
    await dialog.getByRole('button', { name: '查询本次更新结果', exact: true }).click()
    await expect(dialog).toContainText(command.id)
    await expect(dialog).toContainText('所选来源已更新。')
    await inspectScrollableDialog(dialog)
    await dialog.getByText('来源清单', { exact: true }).click()
    await page.setViewportSize({ width: 390, height: 568 })
    await inspectScrollableDialog(dialog)
    const scrolled = await dialog.locator('.evidence-inspector-body').evaluate((element) => {
      element.scrollTop = element.scrollHeight
      return { top: element.scrollTop, maximum: element.scrollHeight - element.clientHeight }
    })
    expect(scrolled.maximum).toBeGreaterThan(0); expect(scrolled.top).toBe(scrolled.maximum)
    expect(writes).toBe(0)
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve('output/playwright/source-refresh-recovery-dark-zh.png') })
  } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

test('a source head advanced outside the page clears displayed consent without sending a refresh', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    const commands: string[] = []
    page.on('request', (sent) => { if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) commands.push(sent.postDataJSON().tool_id) })
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    await dialog.getByRole('checkbox').first().check()
    appendFileSync(v.us, '\nExternal source head advancement.\n')
    await v.invoke('system_image.sources.ingest')
    const advanced = await v.read()
    expect(advanced.source_manifest.manifest_id).not.toBe(v.before.source_manifest.manifest_id)
    await expect(dialog).toContainText(advanced.source_manifest.manifest_id)
    await expect(dialog.getByRole('checkbox', { checked: true })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Refresh selected sources', exact: true })).toBeDisabled()
    expect(await v.read()).toEqual(advanced)
    expect(commands).toEqual([])
  } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

test('a source head advanced after refresh dispatch rejects the original selection without retry or recapture', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  let release = () => {}
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    const commands: string[] = []
    page.on('request', (sent) => { if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) commands.push(sent.postDataJSON().tool_id) })
    let started = () => {}
    const dispatched = new Promise<void>((resolve) => { started = resolve })
    const held = new Promise<void>((resolve) => { release = resolve })
    await page.route('**/v1/tool-invocations', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      started()
      await held
      await route.continue()
    })
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    await dialog.getByRole('checkbox').first().check()
    const complete = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/tool-invocations'))
    await dialog.getByRole('button', { name: 'Refresh selected sources', exact: true }).click()
    await dispatched
    appendFileSync(v.us, '\nExternal source head advancement.\n')
    await v.invoke('system_image.sources.ingest')
    const advanced = await v.read()
    expect(advanced.source_manifest.manifest_id).not.toBe(v.before.source_manifest.manifest_id)
    release()
    const command = await (await complete).json()
    expect(command.status).toBe('failed')
    expect(command.result.followup_reason).toBe('source_refresh_scope_changed')
    await expect(dialog).toContainText('Source refresh failed.')
    expect(await v.read()).toEqual(advanced)
    expect(commands).toEqual(['system_image.sources.ingest'])
  } finally { release(); rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

test('closing the inspector aborts acknowledgement recovery without cancelling or resending the completed write', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  let release = () => {}, originalCommandId = '', posts = 0, detailReads = 0
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    await page.route('**/v1/tool-invocations', async (route) => {
      if (route.request().method() !== 'POST') return route.continue()
      posts++
      const response = await route.fetch(), command = await response.json()
      expect(response.ok()).toBeTruthy()
      expect(command.status).toBe('completed')
      originalCommandId = command.id
      await route.abort('failed')
    })
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    await dialog.getByRole('checkbox').first().check()
    await dialog.getByRole('button', { name: 'Refresh selected sources', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('Check the original command; do not resend it.')
    const matcher = /\/v1\/tool-invocations\/resolve\?/
    let started = () => {}
    const discovered = new Promise<void>((resolve) => { started = resolve })
    const held = new Promise<void>((resolve) => { release = resolve })
    await page.route(matcher, async (route) => {
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      started()
      await held
      // Closing cancels the browser read, not the already completed command.
      await route.fulfill({ response }).catch(() => undefined)
    })
    page.on('request', (sent) => {
      if (sent.method() === 'GET' && sent.url().includes(`/v1/tool-invocations/${originalCommandId}`)) detailReads++
    })
    const aborted = page.waitForEvent('requestfailed', (sent) => matcher.test(sent.url()))
    await dialog.getByRole('button', { name: 'Check original refresh command', exact: true }).click()
    await discovered
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    expect((await aborted).failure()?.errorText).toBe('net::ERR_ABORTED')
    release()
    await expect(dialog).toHaveCount(0)
    expect(detailReads).toBe(0)
    expect(posts).toBe(1)
    const persisted = await request.get(`${analysisApi}/v1/tool-invocations/${originalCommandId}`, { headers: v.owner.headers })
    expect(persisted.ok()).toBeTruthy()
    expect((await persisted.json()).status).toBe('completed')
  } finally {
    release()
    rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true })
  }
})

test('an unverified working source response hides the list and cannot dispatch a write', async ({ page, request }) => {
  const code = analysisSource(), v = await fixture(request, code)
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    // Explicit client protocol corruption, not evidence of a backend ACL bypass.
    await page.route('**/system-image?view=working', async (route) => route.fulfill({ json: {
      ...v.before, source_manifest: { ...v.before.source_manifest, project_id: 'foreign' } } }))
    let writes = 0
    page.on('request', (sent) => { if (sent.method() === 'POST' && sent.url().endsWith('/v1/tool-invocations')) writes++ })
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    await expect(dialog.getByRole('alert')).toContainText('Previous content is hidden')
    await expect(dialog.getByRole('checkbox')).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Refresh selected sources', exact: true })).toHaveCount(0)
    expect(writes).toBe(0)
  } finally { rmSync(code, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})

test('fixed exweb Git export refreshes its selected source through the real browser without changing its image', async ({ page, request }) => {
  test.skip(!process.env.EXWEB_SOURCE_REFRESH_GIT_ROOT, 'Explicit reviewed fixed Git export is required')
  test.setTimeout(120_000)
  const root = mkdtempSync(join(tmpdir(), 'nasus-refresh-exweb-browser-')), code = join(root, 'code')
  mkdirSync(code)
  const exported = JSON.parse(execFileSync(resolve('.venv/bin/python'), ['-c', `
import base64, json, sys
from pathlib import Path
from apps.api.tests.exweb_git_trees import AFTER, read_git_tree
files, tree_hash, _ = read_git_tree(Path(sys.argv[1]), AFTER)
print(json.dumps({"commit": AFTER, "tree_hash": tree_hash, "files": [[name, base64.b64encode(body).decode("ascii")] for name, body in files]}))
`, process.env.EXWEB_SOURCE_REFRESH_GIT_ROOT!], { encoding: 'utf8', maxBuffer: 1024 * 1024 }))
  expect(exported.files).toHaveLength(126)
  for (const [name, body] of exported.files) {
    const destination = resolve(code, name)
    expect(destination.startsWith(code + '/')).toBe(true)
    mkdirSync(resolve(destination, '..'), { recursive: true })
    writeFileSync(destination, Buffer.from(body, 'base64'))
  }
  const v = await fixture(request, code)
  try {
    await page.addInitScript((token) => {
      localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en')
    }, v.owner.token)
    const selected = v.before.sources.find((item: { source_type: string }) => item.source_type === 'code')
    expect(selected.file_count).toBe(126)
    appendFileSync(join(code, 'README.md'), '\nControlled Nasus browser refresh verification, not an upstream change.\n')
    rmSync(v.us); rmSync(v.cases)
    await page.goto(`/projects/${v.projectId}/knowledge`)
    await page.getByRole('button', { name: 'Refresh working sources', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Refresh working sources', exact: true })
    await dialog.locator(`[data-source-id="${selected.id}"]`).getByRole('checkbox').check()
    const complete = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/tool-invocations'))
    await dialog.getByRole('button', { name: 'Refresh selected sources', exact: true }).click()
    const command = await (await complete).json()
    expect(command.status).toBe('completed')
    await expect(dialog).toContainText('Selected sources were refreshed.')
    const after = await v.read()
    expect(after.sources.filter((item: { id: string }) => item.id !== selected.id)).toEqual(v.before.sources.filter((item: { id: string }) => item.id !== selected.id))
    expect(after.objects).toEqual(v.before.objects)
    expect(after.source_manifest.manifest_id).not.toBe(v.before.source_manifest.manifest_id)
    await inspectScrollableDialog(dialog)
    const scrolled = await dialog.locator('.evidence-inspector-body').evaluate((element) => {
      element.scrollTop = element.scrollHeight
      return { top: element.scrollTop, maximum: element.scrollHeight - element.clientHeight }
    })
    expect(scrolled.maximum).toBeGreaterThan(0)
    expect(scrolled.top).toBe(scrolled.maximum)
    const report = { repository: 'https://github.com/kunben-duck/exweb.git', commit: exported.commit,
      tree_hash: exported.tree_hash, file_count: exported.files.length, project_id: v.projectId,
      invocation_id: command.id, request_key: command.input_payload.idempotency_key,
      before_manifest: v.before.source_manifest, after_manifest: after.source_manifest,
      unselected_optional_sources_unchanged: true, image_objects_unchanged: true,
      controlled_change_not_upstream_commit: true, external_model_called: false, target_executed: false }
    if (process.env.EXWEB_SOURCE_REFRESH_BROWSER_REPORT) writeFileSync(process.env.EXWEB_SOURCE_REFRESH_BROWSER_REPORT, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' })
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve('output/playwright/source-refresh-exweb.png') })
  } finally { rmSync(root, { recursive: true, force: true }); rmSync(v.root, { recursive: true, force: true }) }
})
