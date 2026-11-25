import { expect, test } from '@playwright/test'
import { rmSync } from 'node:fs'
import { analysisAccount, analysisApi, analysisSource } from './source-analysis-fixtures'

test('Build inbox filters private conversations and restores the exact legacy or named chat without a write', async ({ page, request }) => {
  const owner = await analysisAccount(request), other = await analysisAccount(request)
  const chats = analysisApi + '/v1/conversations'
  const create = async (title: string, space: string, project?: string, headers = owner.headers) => {
    const res = await request.post(chats, { headers, data: { space_type: 'build', space_id: space, title, project_id: project } })
    expect(res.ok()).toBeTruthy()
    return (await res.json()).id as string
  }
  const projects = []
  for (const name of ['Catalog A', 'Catalog B']) {
    const project = await request.post(analysisApi + '/v1/projects', { headers: owner.headers, data: { name } })
    expect(project.ok()).toBeTruthy()
    projects.push((await project.json()).id as string)
  }
  const one = await create('First task', 'build-first', projects[0])
  await create('Second task', 'build-second', projects[1])
  await create('Loose notes', 'build')
  await create('Private outsider', 'build', undefined, other.headers)
  const writes: string[] = []
  page.on('request', r => { if (r.method() === 'POST' && /\/v1\/(conversations|tool-invocations)/.test(r.url())) writes.push(r.url()) })
  await page.addInitScript(token => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, owner.token)
  await page.goto('/build')
  const rows = page.locator('.build-inbox li a')
  await expect(rows).toHaveCount(3)
  await page.getByRole('combobox', { name: 'Filter by project' }).selectOption(projects[0])
  await expect(rows).toHaveCount(1)
  await rows.click()
  await expect(page).toHaveURL(new RegExp('conversation=' + one + '$'))
  await expect(page.getByTestId('build-agent-input')).toBeEnabled()
  await page.reload()
  await expect(page.getByTestId('build-agent-input')).toBeEnabled()
  await page.getByRole('link', { name: 'My conversations' }).click()
  await page.getByRole('searchbox').fill('second')
  await expect(rows).toHaveText(/Second task/)
  await page.getByRole('searchbox').fill('')
  await page.getByRole('combobox', { name: 'Filter by project' }).selectOption('unbound')
  await expect(rows).toHaveText(/Loose notes/)
  await rows.click()
  await expect(page.getByTestId('build-agent-input')).toBeEnabled()
  expect(writes).toEqual([])
})

test('Build accepts a browser code directory and restores the pending source review', async ({ page, request }) => {
  test.setTimeout(120_000)
  const source = analysisSource(), owner = await analysisAccount(request)
  try {
    await page.addInitScript(token => { localStorage.setItem('nasus_api_token', token); localStorage.setItem('nasus.locale', 'en') }, owner.token)
    await page.goto('/build')
    await page.getByRole('button', { name: 'New build conversation' }).click()
    const prompt = page.getByTestId('build-agent-input')
    const send = async (text: string) => {
      await expect(prompt).toBeEnabled()
      await prompt.fill(text)
      await page.getByTestId('build-agent-submit').click()
      await expect(page.locator('.build-message.user').getByText(text, { exact: true }).last()).toBeVisible()
      await expect(prompt).toBeEnabled()
    }
    await send('Help me build a system image')
    await send('Project name: Directory trial')
    await page.getByTestId('code-directory-input').setInputFiles(source)
    const uploaded = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/source-files'))
    await page.getByRole('button', { name: 'Upload snapshot' }).click()
    const result = await uploaded
    expect(result.ok()).toBeTruthy()
    const { source_uri } = await result.json()
    await expect(page.locator('.build-message.user').last()).toContainText(source_uri)
    await send('skip optional sources')
    await expect(page.getByTestId('build-intake-confirm')).toBeEnabled()
    await page.reload()
    await expect(page.getByTestId('build-intake-confirm')).toBeEnabled()
    await expect(page.locator('.build-message.assistant').last()).toContainText(source_uri)
    await expect(page.getByTestId('build-progress')).toHaveCount(0)
  } finally { rmSync(source, { recursive: true, force: true }) }
})
