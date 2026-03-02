import { chromium } from 'playwright';

const baseUrl = process.env.FRONTEND_URL || 'http://localhost:3000';

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loginIfNeeded(page) {
  const modal = page.locator('#app-auth-modal');
  try {
    await modal.waitFor({ state: 'visible', timeout: 1500 });
  } catch (_err) {
    return;
  }

  await page.fill('#app-auth-username', 'admin');
  await page.fill('#app-auth-password', 'admin123');
  await page.click('#app-auth-form button[type="submit"]');
  await modal.waitFor({ state: 'detached', timeout: 15000 });
}

async function safeClick(page, selector, timeout = 8000) {
  await page.waitForSelector(selector, { timeout });
  await page.click(selector);
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  const findings = [];

  page.on('pageerror', (err) => {
    findings.push(`pageerror: ${err.message}`);
  });

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      findings.push(`console.error: ${msg.text()}`);
    }
  });

  try {
    await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#stat-projects', { timeout: 15000 });

    await page.goto(`${baseUrl}/pages/us-management.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await page.waitForSelector('button[data-action="analyze"]', { timeout: 15000 });

    await safeClick(page, 'button:has-text("新建 US")');
    await page.fill('#parse-modal textarea', `登录需求\n用户输入账号密码后应登录成功\n支持错误提示`);
    await safeClick(page, '#parse-modal button:has-text("开始解析")');
    await sleep(1200);

    await safeClick(page, 'button[data-action="analyze"]');
    await page.waitForSelector('#app-json-modal', { timeout: 15000 });
    await safeClick(page, '#app-json-close');

    await safeClick(page, 'button[data-action="generate"]');
    await sleep(1500);

    await page.goto(`${baseUrl}/pages/test-cases.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await page.waitForSelector('button[data-action="generate"]', { timeout: 15000 });
    await safeClick(page, 'button[data-action="generate"]');
    await page.waitForSelector('#generate-modal', { timeout: 10000 });
    await safeClick(page, '#generate-modal button:has-text("生成脚本")');
    await sleep(1500);

    await page.goto(`${baseUrl}/pages/script-studio.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await page.waitForSelector('#studio-test-case', { timeout: 15000 });
    await safeClick(page, '#studio-ai-generate');
    await sleep(1500);
    await safeClick(page, 'header .flex.items-center.gap-4 button:has-text("保存")');
    await sleep(1200);

    await safeClick(page, 'header .flex.items-center.gap-4 button:has-text("运行")');
    await page.waitForURL(/execution-hub\.html/, { timeout: 20000 });
    await loginIfNeeded(page);

    await page.waitForSelector('#status-text', { timeout: 15000 });
    const startVisible = await page.locator('#start-btn').isVisible().catch(() => false);
    if (startVisible) {
      await safeClick(page, '#start-btn');
      await sleep(2000);
    }

    const stopVisible = await page.locator('#stop-btn').isVisible().catch(() => false);
    if (stopVisible) {
      await safeClick(page, '#stop-btn');
      await sleep(1200);
    }

    await page.goto(`${baseUrl}/pages/reports.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await page.waitForSelector('tr[data-report-id]', { timeout: 15000 });
    await safeClick(page, 'tr[data-report-id]');
    await page.waitForSelector('#report-modal:not(.hidden)', { timeout: 10000 });
    await safeClick(page, '#report-close-btn');

    await page.goto(`${baseUrl}/pages/settings.html`, { waitUntil: 'networkidle' });
    await loginIfNeeded(page);
    await page.waitForSelector('#settings-dynamic-host', { timeout: 15000 });
    await safeClick(page, 'button:has-text("集成配置")');
    await safeClick(page, '#settings-test-conn');
    await safeClick(page, 'button:has-text("执行配置")');
    await safeClick(page, '#exec-save');

    if (findings.length) {
      console.log('UI_SMOKE_WARNINGS');
      findings.forEach((line) => console.log(line));
    }

    console.log('UI_SMOKE_PASS');
  } finally {
    await context.close();
    await browser.close();
  }
}

run().catch((error) => {
  console.error('UI_SMOKE_FAIL');
  console.error(error);
  process.exit(1);
});
