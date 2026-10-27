import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

export const analysisApi = `http://127.0.0.1:${process.env.PLAYWRIGHT_API_PORT ?? '8000'}`

export async function analysisAccount(request: APIRequestContext) {
  const response = await request.post(`${analysisApi}/v1/auth/register`, { data: {
    email: `analysis-${randomUUID()}@example.com`, password: 'analysis-test-password-123', name: 'Analysis reviewer',
  } })
  expect(response.ok()).toBeTruthy()
  const session = await response.json()
  return { userId: session.user.id as string, token: session.access_token as string,
    headers: { Authorization: `Bearer ${session.access_token}` } }
}

export function analysisSource() {
  const directory = mkdtempSync(join(tmpdir(), 'nasus-analysis-browser-'))
  for (let index = 0; index < 26; index++) {
    writeFileSync(join(directory, `Controller${String(index).padStart(2, '0')}.java`), [
      'package example;', 'import org.springframework.web.bind.annotation.RestController;',
      'import org.springframework.web.bind.annotation.GetMapping;', '@RestController',
      `class Controller${index} {`, `    @GetMapping("/example/${index}/<img onerror=alert(1)>")`,
      '    public String find() { return "example"; }', '}', '',
    ].join('\n'))
  }
  writeFileSync(join(directory, 'README.md'), '# Parser browser fixture\n')
  return directory
}

export async function captureAnalysis(request: APIRequestContext, source: string, options: { materialize?: boolean } = {}) {
  const owner = await analysisAccount(request)
  const created = await request.post(`${analysisApi}/v1/projects`, {
    headers: owner.headers, data: { name: `Analysis browser ${randomUUID()}` },
  })
  expect(created.ok()).toBeTruthy()
  const projectId = (await created.json()).id as string
  const conversation = await request.post(`${analysisApi}/v1/conversations`, {
    headers: owner.headers, data: { space_type: 'project', space_id: projectId, title: 'Analysis browser' },
  })
  expect(conversation.ok()).toBeTruthy()
  const conversationId = (await conversation.json()).id
  const invoke = async (tool: string, input = {}, status = 'completed') => {
    const response = await request.post(`${analysisApi}/v1/tool-invocations`, { headers: owner.headers, data: {
      conversation_id: conversationId, tool_id: tool, input: { project_id: projectId, ...input },
    } })
    expect(response.ok()).toBeTruthy()
    const invocation = await response.json()
    expect(invocation.status).toBe(status)
    return invocation
  }
  await invoke('system_image.sources.register', { source_specs: [{ source_type: 'code', source_uri: source }] })
  await invoke('system_image.sources.ingest')
  if (options.materialize !== false) await invoke('system_image.context.materialize')
  const revisions = async () => {
    const response = await request.get(`${analysisApi}/v1/projects/${projectId}/system-image/code-source-revisions`, { headers: owner.headers })
    expect(response.ok()).toBeTruthy()
    return (await response.json()).items as { source_revision_id: string; binding_id: string }[]
  }
  return { owner, projectId, conversationId, invoke, revisions, revision: (await revisions())[0].source_revision_id }
}

export async function openAnalysis(page: Page, projectId: string, token: string) {
  await page.addInitScript((value) => {
    localStorage.setItem('nasus_api_token', value)
    localStorage.setItem('nasus.locale', 'en')
  }, token)
  await page.goto(`/projects/${projectId}/knowledge`)
  await page.getByRole('button', { name: 'Source analyses', exact: true }).click()
  return page.getByRole('dialog', { name: 'Source analyses', exact: true })
}

export async function selectAnalysis(page: Page, revision: string) {
  const dialog = page.getByRole('dialog', { name: 'Source analyses', exact: true })
  await dialog.getByRole('combobox', { name: 'Captured code revision', exact: true }).selectOption(revision)
  const reports = dialog.getByRole('combobox', { name: 'Analysis report', exact: true })
  await expect(reports.locator('option')).toHaveCount(2)
  await reports.selectOption({ index: 1 })
  await expect(dialog.getByRole('list', { name: 'Analysis observations' })).toBeVisible()
  return dialog
}

export function analysisSourcePolicy(projectId: string, readers: string[]) {
  const database = process.env.NASUS_TEST_DATABASE_URL
  if (!database || database !== process.env.NASUS_E2E_DATABASE_URL) throw new Error('Isolated PostgreSQL is required')
  execFileSync(resolve('.venv/bin/python'), ['-c', `
import os, sys
from sqlalchemy.engine import make_url
from apps.api.app.domain.system_image.source_access import SourceAccessRule
from apps.api.app.infrastructure.persistence.source_access_repository import SourceAccessRepository
url = make_url(os.environ['NASUS_DATABASE_URL'])
assert url.get_backend_name() == 'postgresql' and url.host in {'localhost', '127.0.0.1', '::1'}
assert url.database.startswith('nasus_test_'), 'never change developer source policy'
repo = SourceAccessRepository()
snapshot = repo.load_snapshot(sys.argv[1])
assert len(snapshot.bindings) == 1
repo.set_policy(sys.argv[1], snapshot.bindings[0].binding_id, SourceAccessRule('restricted', tuple(sys.argv[2:])),
                expected_epoch=snapshot.acl_epoch, changed_by='browser-fixture', invocation_id='analysis-browser-policy')
`, projectId, ...readers], { env: { ...process.env, NASUS_DATABASE_URL: database }, stdio: 'pipe' })
}
