import { expect, test } from '@playwright/test'
import * as path from 'node:path'

const apiPort = process.env.PLAYWRIGHT_API_PORT ?? '8000'
const apiUrl = `http://127.0.0.1:${apiPort}`
const adminToken = process.env.NASUS_E2E_ADMIN_TOKEN ?? 'nasus-e2e-platform-admin-token'

async function createBrowserSession(page: import('@playwright/test').Page) {
  const email = `e2e-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`
  const response = await fetch(`${apiUrl}/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      password: 'strong-password-123',
      name: 'E2E Admin',
    }),
  })
  if (!response.ok) {
    throw new Error(`Unable to create E2E auth session: ${response.status} ${await response.text()}`)
  }
  const session = await response.json() as { access_token: string }
  const settingsResponse = await fetch(`${apiUrl}/v1/settings`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ language: 'en' }),
  })
  if (!settingsResponse.ok) {
    throw new Error(`Unable to select E2E language: ${settingsResponse.status} ${await settingsResponse.text()}`)
  }
  await page.addInitScript((token) => {
    window.localStorage.setItem('nasus_api_token', token)
    if (!window.localStorage.getItem('nasus.locale')) window.localStorage.setItem('nasus.locale', 'en')
  }, session.access_token)
  return session
}

async function createPlatformAdminBrowserSession(page: import('@playwright/test').Page) {
  const settingsResponse = await fetch(`${apiUrl}/v1/settings`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${adminToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ language: 'en' }),
  })
  if (!settingsResponse.ok) {
    throw new Error(`Unable to select admin E2E language: ${settingsResponse.status} ${await settingsResponse.text()}`)
  }
  await page.addInitScript((token) => {
    window.localStorage.setItem('nasus_api_token', token)
    if (!window.localStorage.getItem('nasus.locale')) window.localStorage.setItem('nasus.locale', 'en')
  }, adminToken)
}

test('unauthenticated users register with email before entering build', async ({ page }) => {
  const email = `signup-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`

  await page.goto('/welcome')
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
  await expect(page.getByRole('heading', { name: /从这里开始你的质量项目/ })).toBeVisible()
  await expect(page.getByText(/从代码初始化系统画像/)).toBeVisible()
  await expect(page.getByRole('heading', { name: /构建持续演进的系统画像/ })).not.toBeInViewport()
  await page.mouse.wheel(0, 900)
  await expect(page.getByRole('heading', { name: /构建持续演进的系统画像/ })).toBeInViewport({ timeout: 5_000 })

  await page.getByRole('link', { name: /开始使用/ }).first().click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: /登录 Nasus Studio/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /^开始使用$/ })).toHaveCount(0)

  await page.getByRole('link', { name: /^创建账号$/ }).click()
  await expect(page).toHaveURL(/\/register$/)
  await expect(page.getByRole('heading', { name: /创建 Nasus 账号/ })).toBeVisible()

  await page.getByLabel(/姓名/).fill('Signup Admin')
  await page.getByLabel(/邮箱/).fill(email)
  await page.getByLabel(/^密码$/).fill('strong-password-123')
  await page.getByLabel(/确认密码/).fill('strong-password-123')
  await page.getByRole('button', { name: /创建账号/ }).click()

  await expect(page).toHaveURL(/\/build$/)
  await expect(page.getByRole('heading', { name: /用 Nasus 构建质量项目/ })).toBeVisible()
  await expect(page.getByRole('button', { name: new RegExp(email, 'i') })).toBeVisible()

  await page.getByTestId('build-agent-input').fill('帮我创建一个新的质量项目')
  await page.getByTestId('build-agent-submit').click()
  await expect(page.getByTestId('build-conversation')).toContainText(/先给项目起个名字/, { timeout: 10_000 })
})

test('language setting switches immediately and persists after reload', async ({ page, request }) => {
  await createBrowserSession(page)
  const buildConversation = page.getByTestId('build-conversation')
  const welcomeTitle = page.getByRole('heading', { name: /Build quality projects with Nasus|用 Nasus 构建质量项目/ })
  await page.goto('/build')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: /Build quality projects with Nasus/i })).toBeVisible()
  await expect(buildConversation).toHaveCount(0)

  await page.getByRole('button', { name: /^Settings$/ }).click()
  await page.getByRole('button', { name: /Language.*English/ }).click()
  const saveChinese = page.waitForResponse((response) =>
    response.url().endsWith('/v1/settings') && response.request().method() === 'PATCH',
  )
  await page.getByRole('button', { name: /^○ 中文$/ }).click()
  await saveChinese

  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
  await expect(page.getByRole('heading', { name: /用 Nasus 构建质量项目/ })).toBeVisible()
  const remoteSettings = await request.patch(`${apiUrl}/v1/settings`, {
    headers: { Authorization: `Bearer ${adminToken}` }, data: { language: 'en' },
  })
  expect(remoteSettings.ok()).toBeTruthy()
  const refreshedSettings = page.waitForResponse((response) => response.url().endsWith('/v1/settings')
    && response.request().method() === 'GET' && response.ok())
  await page.context().setOffline(true)
  await page.context().setOffline(false)
  await refreshedSettings
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
  await expect(page.getByRole('heading', { name: /用 Nasus 构建质量项目/ })).toBeVisible()

  const localizedProjectName = `Localized Runtime Hub ${Date.now()}`
  const projectPrompt = `Help me create a new project called ${localizedProjectName}`
  await page.getByTestId('build-agent-input').fill(projectPrompt)
  await page.getByTestId('build-agent-submit').click()
  const localizedImageLink = page.getByRole('link', { name: '查看系统画像', exact: true })
  await expect(localizedImageLink).toBeVisible({ timeout: 15_000 })
  await expect(page).toHaveURL(/\/build$/)
  await expect(buildConversation.getByRole('log')).toContainText(projectPrompt)
  await expect(welcomeTitle).toHaveCount(0)
  await page.goto((await localizedImageLink.getAttribute('href'))!.replace(/\/knowledge$/, ''))
  await expect(page).toHaveURL(/\/projects\//, { timeout: 15_000 })
  await expect(page.getByRole('heading', { name: /与 Agent 协同构建/ })).toBeVisible()
  await page.getByTestId('agent-card-system-image-builder').click()
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/准备构建系统画像/, { timeout: 15_000 })
  await expect(page.getByTestId('agent-goal-explanation')).toContainText(/等待采集代码/, { timeout: 15_000 })
  await expect(page.getByTestId('agent-goal-explanation')).toContainText(/单独确认结构分析预算/)
  await expect(page.getByTestId('agent-current-step')).toContainText(/等待代码采集完成/)
  await expect(page.getByTestId('agent-goal-panel')).not.toContainText(/Waiting for captured code|source capture|Add and capture/)
  await expect(page.getByTestId('confirm-agent-goal')).toHaveCount(0)

  await page.goto('/build')
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
  await expect(buildConversation.getByRole('log')).toContainText(projectPrompt)
  await expect(localizedImageLink).toBeVisible()
  await expect(welcomeTitle).toHaveCount(0)

  await page.getByRole('button', { name: /^设置$/ }).click()
  await page.getByRole('button', { name: /语言.*中文/ }).click()
  const saveEnglish = page.waitForResponse((response) =>
    response.url().endsWith('/v1/settings') && response.request().method() === 'PATCH',
  )
  await page.getByRole('button', { name: /^○ English$/ }).click()
  await saveEnglish
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  const imageLink = page.getByRole('link', { name: 'View system image', exact: true })
  await expect(imageLink).toBeVisible()
  await expect(localizedImageLink).toHaveCount(0)
  await expect(buildConversation.getByRole('log')).toContainText(projectPrompt)
  await expect(welcomeTitle).toHaveCount(0)

  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(imageLink).toBeVisible()
  await expect(buildConversation.getByRole('log')).toContainText(projectPrompt)
  await expect(welcomeTitle).toHaveCount(0)
  await page.getByRole('button', { name: 'New build conversation', exact: true }).click()
  await expect(page.getByRole('heading', { name: /Build quality projects with Nasus/i })).toBeVisible()
  await expect(buildConversation).toHaveCount(0)
})

test('build agent feedback renders controlled markdown', async ({ page }) => {
  await createBrowserSession(page)
  let completed = false
  await page.route(/\/v1\/conversations\/[^/?]+$/, async (route) => {
    const response = await route.fetch()
    const conversation = await response.json()
    if (completed) conversation.messages.push({
      id: 'reply-markdown', role: 'assistant', status: 'completed', content_type: 'markdown',
      created_at: new Date().toISOString(), metadata: {},
      blocks: [{ type: 'text', text: 'Create **Payment System** from `main`. <script>unsafe()</script>' }],
    })
    if (completed) conversation.agent_goals = [{
      id: 'legacy-project-setup', conversation_id: conversation.id, goal_template: 'project_setup',
      title: 'Create project workspace', summary: 'Project creation completed.', status: 'completed', steps: [],
    }]
    await route.fulfill({ response, json: conversation })
  })
  await page.route('**/v1/conversations/*/messages', async (route) => {
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        conversation_id: 'conversation-markdown',
        turn_id: 'turn-markdown',
        user_message_id: 'message-markdown',
        status: 'accepted',
        events_url: '/v1/conversations/conversation-markdown/events',
      }),
    })
  })
  await page.route('**/v1/conversations/*/turns/turn-markdown', async (route) => {
    completed = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'turn-markdown',
        conversation_id: 'conversation-markdown',
        user_message_id: 'message-markdown',
        status: 'completed',
        result: {
          clarification: {
            question: 'Create **Payment System** from `main`. <script>unsafe()</script>',
          },
        },
      }),
    })
  })

  await page.goto('/build')
  const welcomeTitle = page.getByRole('heading', { name: 'Build quality projects with Nasus', exact: true })
  await expect(welcomeTitle).toBeVisible()
  const composer = page.locator('.hero-composer')
  await expect(composer.getByRole('button', { name: 'Speech to text', exact: true })).toHaveCount(0)
  await expect(composer.getByRole('button', { name: 'Insert files', exact: true })).toHaveCount(0)
  await expect(composer.getByTestId('build-agent-guess')).toBeVisible()
  await expect(composer.locator('.composer-actions')).toHaveCSS('justify-content', 'flex-end')
  await page.getByTestId('build-agent-input').fill('Create a project')
  await page.getByTestId('build-agent-submit').click()

  const feedback = page.getByTestId('build-conversation')
  await expect(feedback.locator('.markdown-content strong')).toHaveText('Payment System')
  await expect(feedback.locator('.markdown-content code')).toHaveText('main')
  await expect(feedback).not.toContainText('**')
  await expect(feedback.locator('script')).toHaveCount(0)
  await expect(page.getByTestId('build-progress')).toHaveCount(0)
  await expect(page.getByTestId('build-image-status')).toContainText('Completed project setup does not mean the system image is built.')
  await expect(welcomeTitle).toHaveCount(0)
  await page.reload()
  await expect(feedback).toBeVisible()
  await expect(welcomeTitle).toHaveCount(0)
  completed = false
  await page.getByRole('button', { name: 'New build conversation', exact: true }).click()
  await expect(welcomeTitle).toBeVisible()
})

test('agent-first build preserves the original goal through structural candidate review', async ({ page, request }) => {
  test.setTimeout(45_000)
  const projectName = `E2E Quality Hub ${Date.now()}`
  const fixtureRoot = path.resolve(process.cwd(), 'tests/fixtures/system-image')

  const session = await createBrowserSession(page)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  await page.goto('/build')
  await expect(page.getByRole('heading', { name: /Build quality projects with Nasus/i })).toBeVisible()
  await expect(page.getByTestId('backend-status-pill')).toContainText(/Live/i)

  await page.getByTestId('build-agent-input').fill(`Help me create a new project called ${projectName}`)
  await page.getByTestId('build-agent-submit').click()

  const imageLink = page.getByRole('link', { name: 'View system image', exact: true })
  await expect(imageLink).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('heading', { name: /Build quality projects with Nasus/i })).toHaveCount(0)
  await expect(page).toHaveURL(/\/build$/)
  await page.goto((await imageLink.getAttribute('href'))!.replace(/\/knowledge$/, ''))
  await expect(page).toHaveURL(/\/projects\//, { timeout: 15_000 })
  await expect(page.getByRole('heading', { name: /Build with Agents/i })).toBeVisible()
  await expect(page.getByText(projectName).first()).toBeVisible()

  await page.getByTestId('agent-card-system-image-builder').click()
  await expect(page.getByTestId('agent-goal-panel')).toContainText(/Prepare a source-pinned system image/i, { timeout: 15_000 })
  await expect(page.getByTestId('agent-loop-trace')).toContainText(/Think · Act · Observe · Decide/i, { timeout: 15_000 })
  await expect(page.getByTestId('agent-current-step')).toBeVisible()
  await expect(page.getByTestId('agent-thinking-card')).toBeVisible()
  await expect(page.getByTestId('agent-memory-context-panel')).toBeVisible()
  await expect(page.getByTestId('agent-confirmation-gate')).toContainText(/Source bindings required/i, { timeout: 15_000 })
  const projectId = new URL(page.url()).pathname.split('/')[2]
  const get = async (path: string) => {
    const response = await request.get(`${apiUrl}${path}`, { headers })
    expect(response.ok()).toBeTruthy()
    return response.json()
  }
  const [conversation] = await get(`/v1/conversations?space_type=project&space_id=${projectId}`)
  const conversationPath = `/v1/conversations/${conversation.id}`
  const [originalGoal] = (await get(conversationPath)).agent_goals
  expect(originalGoal.pause_reason).toBe('missing_captured_code')

  await expect(page.getByTestId('source-binding-panel')).toBeVisible()
  await page.getByTestId('source-code-input').fill(path.join(fixtureRoot, 'code'))
  await page.getByTestId('source-us-input-file').setInputFiles(
    path.join(fixtureRoot, 'us', 'US-101-checkout.md'),
  )
  await expect(page.getByTestId('source-us-input')).toHaveValue(/^(local-object|s3):\/\//)
  await page.getByTestId('source-tests-input-file').setInputFiles(
    path.join(fixtureRoot, 'tests', 'test_checkout_service.py'),
  )
  await expect(page.getByTestId('source-tests-input')).toHaveValue(/^(local-object|s3):\/\//)
  await page.getByTestId('build-system-image-with-sources').click()
  await expect(page.getByTestId('image-build-execution-budget')).toBeVisible({ timeout: 20_000 })
  const pending = (await get(conversationPath)).agent_goals
  expect(pending).toHaveLength(1)
  expect(pending[0].id).toBe(originalGoal.id)
  const [planRef] = pending[0].target_refs.filter((ref: string) => ref.startsWith('build_plan:'))
  expect(planRef).toBeDefined()
  const planPath = `/v1/projects/${projectId}/system-image/build-plans/${planRef.slice('build_plan:'.length)}`
  const draft = await get(planPath)
  expect(draft.execution_authorizations).toHaveLength(0)
  expect(draft.structural_artifacts).toHaveLength(0)

  await page.getByTestId('confirm-agent-goal').click()
  await expect(page.getByTestId('agent-confirmation-gate')).toContainText('Structural candidate saved', { timeout: 20_000 })
  await expect(page.getByTestId('system-image-strip')).toContainText(/Sources indexed\s*3\/3/i)
  const built = await get(planPath)
  expect(built.proposal).toEqual(draft.proposal)
  expect(built.structural_artifacts).toHaveLength(1)
  expect(built.execution_authorizations).toHaveLength(1)
  expect(built.execution_authorizations[0]).toMatchObject({ goal_id: originalGoal.id, publication_allowed: false })
  const finished = (await get(conversationPath)).agent_goals
  expect(finished).toHaveLength(1)
  expect(finished[0]).toMatchObject({ id: originalGoal.id, status: 'paused', pause_reason: 'structural_candidate_review' })

  await page.getByTestId('project-agent-input').fill('Show me the current system image freshness and baseline status')
  await page.getByTestId('project-agent-submit').click()
  await expect(page.getByText(/source groups are indexed|system image is/i).first()).toBeVisible({ timeout: 15_000 })
})

test('quality agent runs and exposes the release evidence blockers', async ({ page, request }) => {
  test.setTimeout(60_000)
  const session = await createBrowserSession(page)
  const headers = { Authorization: `Bearer ${session.access_token}` }
  const post = async (path: string, data?: object) => {
    const response = await request.post(`${apiUrl}${path}`, { headers, data })
    expect(response.ok(), await response.text()).toBeTruthy()
    return response.json()
  }
  const project = await post('/v1/projects', { name: `E2E Quality Release ${Date.now()}` })
  const conversation = await post('/v1/conversations', { space_type: 'project', space_id: project.id, title: project.name })
  const invoke = (tool_id: string, input = {}) => post('/v1/tool-invocations', {
    conversation_id: conversation.id, tool_id, input: { project_id: project.id, ...input },
  })
  const fixtureRoot = path.resolve(process.cwd(), 'tests/fixtures/system-image')
  const registered = await invoke('system_image.sources.register', { source_specs: [
    { source_type: 'code', source_uri: path.join(fixtureRoot, 'code') },
    { source_type: 'us_doc', source_uri: path.join(fixtureRoot, 'us') },
    { source_type: 'test_asset', source_uri: path.join(fixtureRoot, 'tests') },
  ] })
  expect(registered.status).toBe('completed')
  expect((await invoke('system_image.sources.ingest')).status).toBe('completed')
  const baseline = await invoke('system_image.baseline.initialize')
  expect(baseline.status).toBe('waiting_confirmation')
  expect((await post(`/v1/tool-invocations/${baseline.id}/confirm`)).status).toBe('completed')

  await page.goto(`/projects/${project.id}`)
  await expect(page.getByTestId('agent-card-quality-loop-agent')).toBeEnabled({ timeout: 15_000 })

  await page.getByTestId('agent-card-quality-loop-agent').click()
  const goalPanel = page.getByTestId('agent-goal-panel')
  const goalStatus = goalPanel.locator('.agent-goal-summary .agent-goal-status')
  await expect(goalPanel).toContainText(/Advance quality loop/i, { timeout: 15_000 })
  await expect(goalStatus).toHaveText(/^completed$/i, { timeout: 20_000 })
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/Release Assessment/i, { timeout: 20_000 })
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/ready for review/i)
  await expect(page.getByTestId('quality-loop-state')).toContainText(/in progress/i)
  const readGoals = async () => {
    const response = await request.get(`${apiUrl}/v1/conversations/${conversation.id}`, { headers })
    expect(response.ok()).toBeTruthy()
    return (await response.json()).agent_goals as { id: string; status: string }[]
  }
  const prepared = await readGoals()
  expect(prepared).toHaveLength(1)
  expect(prepared[0].status).toBe('completed')

  await page.getByTestId('project-agent-input').fill(
    'Continue the quality loop against http://example.test and assess release readiness',
  )
  await page.getByTestId('project-agent-submit').click()
  await expect.poll(async () => (await readGoals()).filter((goal) => goal.id !== prepared[0].id)
    .map((goal) => goal.status), { timeout: 25_000 }).toEqual(['completed'])
  await expect(goalStatus).toHaveText(/^completed$/i, { timeout: 20_000 })
  const loop = page.getByTestId('quality-loop-state')
  await expect(loop).toContainText(/Quality loop blocked/i, { timeout: 20_000 })
  await expect(loop).toContainText(/Release score/i)
  await expect(loop).toContainText('System image quality assessment is unknown')
  await expect(loop).toContainText('Required quality assets are not approved: case_set, scenario_set')
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/completed/i)
  await expect(page.getByTestId('quality-asset-panel')).toContainText(/Latest run/i)

  const releaseAssessRequests: string[] = []
  page.on('request', (request) => {
    if (request.method() !== 'POST' || !request.url().endsWith('/v1/tool-invocations')) return
    const body = request.postData() ?? ''
    if (body.includes('"tool_id":"release.assess"')) {
      releaseAssessRequests.push(body)
    }
  })

  await page.getByTestId('tool-release-gate').dblclick()
  await expect(page.getByTestId('tool-invocation-rail')).toContainText(/release\.assess/i, { timeout: 15_000 })
  await expect(page.getByTestId('tool-invocation-rail')).toContainText(/completed/i, { timeout: 15_000 })
  await expect.poll(() => releaseAssessRequests.length, { timeout: 1_000 }).toBe(1)
  await page.waitForTimeout(300)
  expect(releaseAssessRequests).toHaveLength(1)
})

test('studio routes are deep-linkable', async ({ page }) => {
  await createPlatformAdminBrowserSession(page)
  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: /Global quality cockpit/i })).toBeVisible()
  await expect(page.getByTestId('backend-status-pill')).toContainText(/Live/i)
  await expect(page).toHaveURL(/\/dashboard$/)

  await page.goto('/documentation')
  await expect(page.getByRole('heading', { name: /How Nasus works/i })).toBeVisible()
  await expect(page.getByTestId('backend-status-pill')).toContainText(/Live/i)
  await expect(page).toHaveURL(/\/documentation$/)

  await page.goto('/projects/proj_payment')
  await expect(page.getByTestId('agent-workspace')).toBeVisible()
  await expect(page.getByText(/Payment System/i).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: /Build with Agents/i })).toBeVisible()
  await expect(page).toHaveURL(/\/projects\/proj_payment$/)

  const projectDeepLinks = [
    {
      path: '/projects/proj_payment/versions',
      testId: 'project-versions-route',
      heading: /Version Space/i,
    },
    {
      path: '/projects/proj_payment/versions/create',
      testId: 'project-version-create-route',
      heading: /^Create delivery iteration$/i,
    },
    {
      path: '/projects/proj_payment/workspaces/us_123',
      testId: 'project-workspace-route',
      heading: /Saved cards checkout flow/i,
    },
    {
      path: '/projects/proj_payment/knowledge',
      testId: 'project-knowledge-route',
      heading: /System Image Knowledge/i,
    },
    {
      path: '/projects/proj_payment/runs',
      testId: 'project-runs-route',
      heading: /Runs/i,
    },
    {
      path: '/projects/proj_payment/governance',
      testId: 'project-governance-route',
      heading: /Governance/i,
    },
    {
      path: '/projects/proj_payment/release-readiness',
      testId: 'project-release-readiness-route',
      heading: /Release Readiness/i,
    },
  ]

  for (const route of projectDeepLinks) {
    await page.goto(route.path)
    await expect(page.getByTestId(route.testId)).toBeVisible()
    await expect(page.getByRole('heading', { name: route.heading })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`${route.path}$`))
  }
})

test('unknown project deep link disables project-scoped agent actions', async ({ page }) => {
  await createBrowserSession(page)
  await page.goto('/projects/does-not-exist')
  await expect(page.getByTestId('project-not-found')).toBeVisible()
  await expect(page.getByRole('heading', { name: /This project is not available/i })).toBeVisible()
  await expect(page.getByText(/cannot accidentally operate on another project/i)).toBeVisible()
  await expect(page.getByTestId('agent-workspace')).toHaveCount(0)
  await expect(page.getByText(/Payment System/i)).toHaveCount(0)
})
