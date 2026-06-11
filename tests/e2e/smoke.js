const { chromium } = require('@playwright/test')

const portalUrl = process.env.PORTAL_URL || 'http://127.0.0.1:4173'

async function expectVisible(locator, label, timeout = 15000) {
  await locator.waitFor({ state: 'visible', timeout })
  console.log(`ok: ${label}`)
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()

  try {
    await page.goto(`${portalUrl}/build`, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByRole('heading', { name: /^Build$/i }), 'build page loaded')

    const buildInput = page.getByPlaceholder(/create a project|创建项目/i)
    await buildInput.fill('Help me create a new project called Loyalty Hub')
    await page.locator('.send-btn').click()
    await page.goto(`${portalUrl}/dashboard`, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByRole('heading', { name: /^Dashboard$|^全局仪表盘$/i }), 'dashboard loaded')
    await expectVisible(page.getByText(/Loyalty Hub/i), 'new project visible on dashboard')

    await page.locator('[data-action="open_project"][data-project="proj_payment"]').click()
    await expectVisible(page.getByText(/Payment System/i).first(), 'project overview loaded')

    await page.locator('[data-action="open_workspace"][data-us="us_123"]').first().click()
    await expectVisible(page.getByText(/Saved cards checkout flow/i).first(), 'workspace loaded')
    await page.getByRole('button', { name: /Generate Scenarios|生成测试场景/i }).first().click()
    await expectVisible(page.getByText(/Scenario generation is complete/i).first(), 'scenario generation completed')

    await page.goto(`${portalUrl}/projects/proj_payment/knowledge/OBJ-CHECKOUT`, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByRole('heading', { name: /Checkout Flow .*Object Detail/i }), 'knowledge detail loaded')

    await page.goto(`${portalUrl}/projects/proj_payment/runs/run_9021`, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByText(/checkout confirm selector changed/i).first(), 'run detail loaded')

    await page.goto(`${portalUrl}/projects/proj_payment/governance/approval_442`, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByText(/Version Shared promotion is allowed/i).first(), 'approval detail loaded')

    await page.goto(`${portalUrl}/projects/proj_payment/release-readiness`, { waitUntil: 'domcontentloaded' })
    await expectVisible(page.getByText(/Conditionally Ready/i), 'release readiness loaded')

    console.log('smoke: success')
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error('smoke: failed')
  console.error(error)
  process.exit(1)
})
