const { test, expect } = require('@playwright/test');

const baseUrl = process.env.FRONTEND_URL || 'http://localhost:3000';

async function loginIfNeeded(page) {
  const modal = page.locator('#app-auth-modal');
  if (await modal.isVisible().catch(() => false)) {
    await page.fill('#app-auth-username', 'admin');
    await page.fill('#app-auth-password', 'admin123');
    await page.click('#app-auth-form button[type="submit"]');
    await expect(modal).toBeHidden({ timeout: 15000 });
  }
}

test.describe('UI smoke flows', () => {
  test.setTimeout(180000);

  test('all pages core actions are usable', async ({ page }) => {
    page.on('dialog', async (dialog) => {
      await dialog.dismiss();
    });

    await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' });
    await expect(page.locator('#stat-projects')).toBeVisible();

    await page.goto(`${baseUrl}/pages/us-management.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await expect(page.locator('button[data-action="analyze"]').first()).toBeVisible({ timeout: 15000 });

    await page.click('button:has-text("新建 US")');
    await page.fill('#parse-modal textarea', '登录需求\n用户输入账号密码后应登录成功\n支持错误提示');
    await page.click('#parse-modal button:has-text("开始解析")');

    await page.click('button[data-action="analyze"]');
    await expect(page.locator('#app-json-modal')).toBeVisible({ timeout: 15000 });
    await page.click('#app-json-close');

    await page.click('button[data-action="generate"]');

    await page.goto(`${baseUrl}/pages/test-cases.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await expect(page.locator('button[data-action="generate"]').first()).toBeVisible({ timeout: 15000 });
    await page.click('button[data-action="generate"]');
    await page.click('#generate-modal button:has-text("生成脚本")');

    await page.goto(`${baseUrl}/pages/script-studio.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await expect(page.locator('#studio-test-case')).toBeVisible({ timeout: 15000 });
    await page.click('#studio-ai-generate');
    await page.click('header .flex.items-center.gap-4 button:has-text("保存")');
    await page.click('header .flex.items-center.gap-4 button:has-text("运行")');

    await page.waitForURL(/execution-hub\.html/, { timeout: 20000 });
    await loginIfNeeded(page);
    await expect(page.locator('#status-text')).toBeVisible({ timeout: 15000 });

    if (await page.locator('#start-btn').isVisible().catch(() => false)) {
      await page.click('#start-btn');
    }
    if (await page.locator('#stop-btn').isVisible().catch(() => false)) {
      await page.click('#stop-btn');
    }

    await page.goto(`${baseUrl}/pages/reports.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await expect(page.locator('tr[data-report-id]').first()).toBeVisible({ timeout: 15000 });
    await page.click('tr[data-report-id]');
    await expect(page.locator('#report-modal')).toBeVisible();
    await page.click('#report-close-btn');

    await page.goto(`${baseUrl}/pages/settings.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await expect(page.locator('#settings-dynamic-host')).toBeVisible({ timeout: 15000 });
    await page.click('button:has-text("集成配置")');
    await page.click('#settings-test-conn');
    await page.click('button:has-text("执行配置")');
    await page.click('#exec-save');

    await expect(page.locator('#settings-dynamic-host')).toBeVisible();
  });
});
