import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { analysisApi } from './source-analysis-fixtures'

export async function frozenRevisions(request: APIRequestContext, projectId: string, headers: Record<string, string>) {
  const response = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/revisions`, { headers })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).items as { image_revision_id: string; manifest_id: string; artifact_hash: string;
    object_count: number; code_member_count: number; baseline_id: string; manifest_hash: string }[]
}

export async function openImageRevisions(page: Page, projectId: string, token: string) {
  await page.addInitScript((value) => {
    localStorage.setItem('nasus_api_token', value)
    localStorage.setItem('nasus.locale', 'en')
  }, token)
  await page.goto(`/projects/${projectId}/knowledge`)
  await page.getByRole('button', { name: 'Image revisions', exact: true }).click()
  return page.getByRole('dialog', { name: 'Image revisions', exact: true })
}

export async function selectImageRevision(page: Page, revisionId: string) {
  const dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
  await dialog.getByRole('combobox', { name: 'Frozen candidate revision', exact: true }).selectOption(revisionId)
  await expect(dialog.getByRole('list', { name: 'Frozen image records' })).toBeVisible()
  return dialog
}

async function verifiedImageMove(page: Page, projectId: string, revisionId: string, offset: number, move: () => Promise<unknown>) {
  const dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
  const path = `/v1/projects/${encodeURIComponent(projectId)}/system-image/revisions/${encodeURIComponent(revisionId)}`
  const responseFor = (section: string) => page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET' && url.pathname === path
      && url.searchParams.get('section') === section && url.searchParams.get('offset') === String(offset)
      && url.searchParams.get('limit') === '25'
  }, { timeout: 5000 })
  // Register both listeners before clicking; assertion backoff is not page latency.
  const [objects, members] = await Promise.all([
    responseFor('objects'), responseFor('members'),
    move(),
  ])
  for (const response of [objects, members]) {
    expect(response.status()).toBe(200)
    expect(await response.finished()).toBeNull()
  }
  await expect(dialog.getByRole('list', { name: 'Frozen image records', exact: true })).toBeVisible()
}

export async function nextFrozenImagePage(page: Page, projectId: string, revisionId: string, offset: number) {
  const dialog = page.getByRole('dialog', { name: 'Image revisions', exact: true })
  await verifiedImageMove(page, projectId, revisionId, offset, () =>
    dialog.getByRole('group', { name: 'Revision content pages', exact: true })
      .getByRole('button', { name: 'Next page', exact: true }).click())
}

export async function jumpToFrozenImageRecord(page: Page, projectId: string, revisionId: string, offset: number) {
  const navigation = page.getByRole('dialog', { name: 'Image revisions', exact: true })
    .getByRole('form', { name: 'Record navigation', exact: true })
  await navigation.getByRole('spinbutton', { name: 'Start at record', exact: true }).fill(String(offset + 1))
  await verifiedImageMove(page, projectId, revisionId, offset, () =>
    navigation.getByRole('button', { name: 'Go to record', exact: true }).click())
}
