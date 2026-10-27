import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const api = `http://127.0.0.1:${process.env.PLAYWRIGHT_API_PORT ?? '8000'}`

async function account(request: APIRequestContext) {
  const response = await request.post(`${api}/v1/auth/register`, { data: {
    email: `evidence-${randomUUID()}@example.com`, password: 'evidence-test-password-123', name: 'Evidence reviewer',
  } })
  expect(response.ok()).toBeTruthy()
  const session = await response.json()
  return { userId: session.user.id as string, token: session.access_token as string,
    headers: { Authorization: `Bearer ${session.access_token}` } }
}

async function prepare(request: APIRequestContext) {
  const owner = await account(request)
  const response = await request.post(`${api}/v1/projects`, {
    headers: owner.headers, data: { name: `Evidence browser ${randomUUID()}` },
  })
  expect(response.ok()).toBeTruthy()
  const projectId = (await response.json()).id as string
  const conversation = await request.post(`${api}/v1/conversations`, {
    headers: owner.headers, data: { space_type: 'project', space_id: projectId, title: 'Evidence browser' },
  })
  expect(conversation.ok()).toBeTruthy()
  const conversationId = (await conversation.json()).id
  const directory = mkdtempSync(join(tmpdir(), 'nasus-evidence-browser-'))
  const path = join(directory, 'evidence_example.py')
  const text = ['class EvidenceExample:', '    markup = "<script>window.evidenceInjected = true</script>"',
    ...Array.from({ length: 120 }, (_, index) => `    value_${index} = ${index}`), ''].join('\n')
  writeFileSync(path, text)
  try {
    for (const [tool, input] of [
      ['system_image.sources.register', { source_specs: [{ source_type: 'code', source_uri: path }] }],
      ['system_image.sources.ingest', {}], ['system_image.context.materialize', {}],
    ] as const) {
      const invoked = await request.post(`${api}/v1/tool-invocations`, { headers: owner.headers, data: {
        conversation_id: conversationId, tool_id: tool, input: { project_id: projectId, ...input },
      } })
      expect(invoked.ok()).toBeTruthy()
      expect((await invoked.json()).status).toBe('completed')
    }
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
  const image = await request.get(`${api}/v1/projects/${projectId}/system-image`, { headers: owner.headers })
  const objects = (await image.json()).objects as { id: string; name: string;
    code_reference: { source_revision_id: string; entity_id: string; entity_revision_id: string } | null }[]
  const object = objects.find((item) => item.name.startsWith('EvidenceExample'))!
  expect(object.code_reference?.source_revision_id).toBeTruthy()
  return { owner, projectId, object }
}

async function signIn(page: Page, token: string) {
  await page.addInitScript((value) => {
    localStorage.setItem('nasus_api_token', value)
    localStorage.setItem('nasus.locale', 'en')
  }, token)
}

function sourcePolicy(projectId: string, readers: string[]) {
  const database = process.env.NASUS_TEST_DATABASE_URL
  if (!database || database !== process.env.NASUS_E2E_DATABASE_URL) {
    throw new Error('Source policy fixture requires the isolated PostgreSQL test runner')
  }
  execFileSync(resolve('.venv/bin/python'), ['-c', `
import os, sys
from sqlalchemy.engine import make_url
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
url = make_url(os.environ['NASUS_DATABASE_URL'])
assert url.get_backend_name() == 'postgresql' and url.host in {'localhost', '127.0.0.1', '::1'}
assert url.database.startswith('nasus_test_'), 'never change developer source policy'
repository = SourceAccessRepository()
snapshot = repository.load_snapshot(sys.argv[1])
assert len(snapshot.bindings) == 1
repository.set_policy(sys.argv[1], snapshot.bindings[0].binding_id, SourceAccessRule('restricted', tuple(sys.argv[2:])),
                      expected_epoch=snapshot.acl_epoch, changed_by='browser-fixture', invocation_id='browser-source-policy')
`, projectId, ...readers], { env: { ...process.env, NASUS_DATABASE_URL: database }, stdio: 'pipe' })
}

async function revalidateImage(page: Page, projectId: string, expectedStatus: number) {
  const updated = page.waitForResponse((response) => response.url().endsWith(`/v1/projects/${projectId}/system-image`)
    && response.request().method() === 'GET' && response.status() === expectedStatus)
  // Refetch in place without interrupting a request already triggered by SSE.
  // Toggling offline can turn the expected authorization response into a
  // transport failure; visibility refresh preserves the open inspector state.
  await expect.poll(() => page.evaluate(() => document.visibilityState)).toBe('visible')
  await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))
  await updated
}

for (const theme of ['light', 'dark']) {
  test(`pinned source evidence is readable and paginated in ${theme} desktop and mobile`, async ({ page, request }) => {
    const { owner, projectId, object } = await prepare(request)
    expect(object.id).toBe(`CODE-${object.code_reference!.entity_id}`)
    const revisions = await request.get(`${api}/v1/projects/${projectId}/system-image/revisions`, { headers: owner.headers })
    expect(revisions.ok()).toBeTruthy()
    const revision = (await revisions.json()).items[0]
    const identity = await request.get(`${api}/v1/projects/${projectId}/system-image/revisions/${revision.image_revision_id}/objects/${object.id}/identity`,
      { headers: owner.headers })
    expect(identity.ok()).toBeTruthy()
    expect(identity.headers()['cache-control']).toBe('private, no-store')
    expect(await identity.json()).toMatchObject({ project_id: projectId, image_revision_id: revision.image_revision_id,
      image_artifact_hash: revision.artifact_hash, canonical_object_id: object.id, frozen_object_id: object.id,
      entity_revision_id: object.code_reference!.entity_revision_id, source_revision_id: object.code_reference!.source_revision_id })
    expect(await identity.text()).not.toContain('EvidenceExample')
    await request.patch(`${api}/v1/settings`, { headers: owner.headers, data: { language: 'en', theme } })
    await signIn(page, owner.token)
    await page.goto(`/projects/${projectId}/knowledge`)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const trigger = page.getByTestId(`knowledge-card-${object.id}`).getByRole('button', { name: 'Inspect evidence' })
    await trigger.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText(object.code_reference!.source_revision_id)
    await expect(dialog.getByRole('status')).toHaveText('Verified against archived file and snippet hashes')
    const source = dialog.getByRole('region', { name: 'Archived source code' })
    await expect(source).toContainText('class EvidenceExample:')
    await expect(source).toContainText('<script>window.evidenceInjected = true</script>')
    await expect(source.locator('script')).toHaveCount(0)
    await expect(source.locator('.evidence-source-line')).toHaveCount(100)
    await dialog.getByRole('button', { name: 'Load more lines' }).click()
    await expect(source).toContainText('value_119 = 119')
    await expect(dialog.getByRole('button', { name: 'Load more lines' })).toHaveCount(0)
    await dialog.getByText('Integrity details', { exact: true }).click()
    await expect(dialog).toContainText('sha256:')
    await dialog.getByLabel('Source location', { exact: true }).scrollIntoViewIfNeeded()
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/evidence-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    const bounds = await dialog.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.width + bounds!.x).toBeLessThanOrEqual(390)
    expect(bounds!.height + bounds!.y).toBeLessThanOrEqual(844)
    await page.screenshot({ path: resolve(`output/playwright/evidence-${theme}-mobile.png`) })
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(trigger).toBeFocused()
  })

  test(`explicit legacy protocol observation cannot invent source evidence in ${theme}`, async ({ page, request }) => {
    const { owner, projectId } = await prepare(request)
    const legacyId = `LEGACY-${randomUUID()}`
    // The current code-only pipeline has no invented placeholder objects. This
    // separate legacy DTO fixture exercises compatibility, not captured facts.
    await page.route((url) => url.pathname === `/v1/projects/${projectId}/system-image`, async (route) => {
      const response = await route.fetch()
      expect(response.ok()).toBeTruthy()
      const image = await response.json()
      await route.fulfill({ response, json: { ...image, objects: [...image.objects, {
        id: legacyId, name: 'Legacy unverified observation', type: 'legacy_observation', branch: 'legacy',
        confidence: 'unknown', relations: [], evidence: [], freshness: 'legacy_unverified',
        code_reference: null, document_reference: null,
      }] } })
    })
    expect((await request.patch(`${api}/v1/settings`, { headers: owner.headers, data: { language: 'en', theme } })).ok()).toBeTruthy()
    await signIn(page, owner.token)
    await page.goto(`/projects/${projectId}/knowledge`)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const evidenceReads: string[] = []
    page.on('request', (sent) => {
      if (new URL(sent.url()).pathname.includes(`/projects/${projectId}/system-image/evidence`)) evidenceReads.push(sent.url())
    })
    const trigger = page.getByTestId(`knowledge-card-${legacyId}`).getByRole('button', { name: 'Inspect evidence' })
    await trigger.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('No pinned source evidence. Rebuild this source to establish verifiable references.')
    await expect(dialog.getByRole('region', { name: 'Archived source code' })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: 'Load more lines' })).toHaveCount(0)
    expect(evidenceReads).toEqual([])
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(trigger).toBeFocused()
  })
}

test('revoking project access stops pagination and removes previously rendered source', async ({ page, request }) => {
  const { owner, projectId, object } = await prepare(request)
  const viewer = await account(request)
  const memberUrl = `${api}/v1/projects/${projectId}/members/${viewer.userId}`
  expect((await request.put(memberUrl, { headers: owner.headers, data: { role: 'viewer' } })).ok()).toBeTruthy()
  await request.patch(`${api}/v1/settings`, { headers: owner.headers, data: { language: 'en' } })
  await signIn(page, viewer.token)
  await page.goto(`/projects/${projectId}/knowledge`)
  await page.getByTestId(`knowledge-card-${object.id}`).getByRole('button', { name: 'Inspect evidence' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('region', { name: 'Archived source code' })).toContainText('class EvidenceExample:')
  // Revoke after the user requests the next page, before the real API reads it.
  // This also works when background snapshot revalidation closes the inspector.
  const nextPage = (url: URL) => url.pathname.includes(`/projects/${projectId}/system-image/evidence/`)
    && url.searchParams.has('start_line')
  let deniedStatus: number | null = null
  await page.route(nextPage, async (route) => {
    expect((await request.delete(memberUrl, { headers: owner.headers })).ok()).toBeTruthy()
    // Forward the actual response unchanged. A parallel snapshot 403 may
    // cancel the browser request, but the API denial must still be verified.
    const response = await route.fetch()
    deniedStatus = response.status()
    await route.fulfill({ response })
  }, { times: 1 })
  await dialog.getByRole('button', { name: 'Load more lines' }).click()
  await expect.poll(() => deniedStatus).toBe(403)
  await expect(page.getByRole('alert').filter({ hasText: /Source verification failed or access was revoked\.|System image could not be verified\./ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Archived source code' })).toHaveCount(0)
})

for (const theme of ['light', 'dark']) {
  test(`source-filtered knowledge is honest and revalidated in ${theme}`, async ({ page, request }) => {
    const { owner, projectId, object } = await prepare(request)
    const viewer = await account(request)
    const memberUrl = `${api}/v1/projects/${projectId}/members/${viewer.userId}`
    expect((await request.put(memberUrl, { headers: owner.headers, data: { role: 'viewer' } })).ok()).toBeTruthy()
    sourcePolicy(projectId, [viewer.userId])
    await request.patch(`${api}/v1/settings`, { headers: owner.headers, data: { language: 'en', theme } })
    await signIn(page, viewer.token)
    await page.goto(`/projects/${projectId}/knowledge`)
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    const notice = page.getByTestId('source-visibility-notice').first()
    await expect(notice).toContainText('Only authorized source-local facts are shown.')
    await expect(page.getByText('Visible objects', { exact: true })).toBeVisible()
    await expect(page.locator('.knowledge-summary')).toContainText('Authorized code objects')
    await expect(page.locator('.knowledge-summary')).not.toContainText('Only authorized source-local facts')
    await expect(page.getByText('Unavailable', { exact: true }).first()).toBeVisible()
    const card = page.getByTestId(`knowledge-card-${object.id}`)
    await expect(card).toContainText('Relationships unavailable')
    await expect(card).not.toContainText('0 relations')
    mkdirSync(resolve('output/playwright'), { recursive: true })
    await page.screenshot({ path: resolve(`output/playwright/source-filtered-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    const bounds = await notice.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
    for (const element of await page.locator('.knowledge-heading, .knowledge-summary, .metric-mini strong').all()) {
      const box = await element.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(390)
    }
    await page.screenshot({ path: resolve(`output/playwright/source-filtered-${theme}-mobile.png`) })
    await card.getByRole('button', { name: 'Inspect evidence' }).click()
    await expect(page.getByRole('dialog').getByRole('region', { name: 'Archived source code' })).toContainText('class EvidenceExample:')

    sourcePolicy(projectId, [])
    await revalidateImage(page, projectId, 200)
    await expect(page.locator('[data-testid^="knowledge-card-"]')).toHaveCount(0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(notice).toBeVisible()

    sourcePolicy(projectId, [viewer.userId])
    await revalidateImage(page, projectId, 200)
    await expect(card).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto(`/projects/${projectId}`)
    const strip = page.getByTestId('system-image-strip')
    await expect(strip.getByTestId('source-visibility-notice')).toBeVisible()
    await expect(strip.getByText('Unavailable', { exact: true })).toHaveCount(2)
    await expect(strip.locator('.system-image-stage-bar')).toHaveCount(0)
    await expect(strip).not.toContainText('visibility limited')
    await page.getByRole('button', { name: 'Sources', exact: true }).click()
    await expect(page.getByTestId('source-binding-panel')).toHaveCount(0)
    await strip.evaluate((element) => element.scrollIntoView({ block: 'center' }))
    await strip.screenshot({ path: resolve(`output/playwright/source-overview-${theme}.png`) })
    await page.setViewportSize({ width: 390, height: 844 })
    for (const element of await strip.locator('.metric-mini strong').all()) {
      const box = await element.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(390)
    }
    await strip.evaluate((element) => element.scrollIntoView({ block: 'center' }))
    await strip.screenshot({ path: resolve(`output/playwright/source-overview-${theme}-mobile.png`) })
    await page.goto(`/projects/${projectId}/knowledge`)
    await card.getByRole('button', { name: 'Inspect evidence' }).click()
    await expect(page.getByRole('dialog').getByRole('region', { name: 'Archived source code' })).toBeVisible()
    expect((await request.delete(memberUrl, { headers: owner.headers })).ok()).toBeTruthy()
    await revalidateImage(page, projectId, 403)
    await expect(page.getByRole('alert')).toContainText('previous knowledge is hidden')
    await expect(page.locator('[data-testid^="knowledge-card-"]')).toHaveCount(0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect((await request.put(memberUrl, { headers: owner.headers, data: { role: 'viewer' } })).ok()).toBeTruthy()
    await revalidateImage(page, projectId, 200)
    await expect(card).toBeVisible()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })
}
