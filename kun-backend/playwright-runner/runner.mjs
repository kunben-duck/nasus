#!/usr/bin/env node

import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const cliPath = require.resolve('@playwright/test/cli');
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const runnerNodeModules = path.join(__dirname, 'node_modules');

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith('--')) continue;
    const value = argv[i + 1];
    if (value == null || value.startsWith('--')) {
      args[key.slice(2)] = 'true';
      continue;
    }
    args[key.slice(2)] = value;
    i += 1;
  }
  return args;
}

function toSafeBrowser(raw) {
  const normalized = String(raw || 'chromium').trim().toLowerCase();
  if (normalized === 'firefox' || normalized === 'webkit' || normalized === 'chromium') {
    return normalized;
  }
  return 'chromium';
}

function splitLines(text) {
  return String(text || '')
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter(Boolean);
}

function collectSpecs(rootSuite, output = []) {
  if (!rootSuite || typeof rootSuite !== 'object') {
    return output;
  }
  if (Array.isArray(rootSuite.specs)) {
    output.push(...rootSuite.specs);
  }
  if (Array.isArray(rootSuite.suites)) {
    for (const child of rootSuite.suites) {
      collectSpecs(child, output);
    }
  }
  return output;
}

function fileExists(p) {
  try {
    return fs.existsSync(p) && fs.statSync(p).isFile();
  } catch (_err) {
    return false;
  }
}

function safeResolve(baseDir, inputPath) {
  if (!inputPath) return null;
  const resolved = path.isAbsolute(inputPath)
    ? path.normalize(inputPath)
    : path.normalize(path.resolve(baseDir, inputPath));
  return resolved;
}

async function copyAttachments(paths, destinationDir, prefix) {
  const copied = [];
  if (!Array.isArray(paths) || !paths.length) {
    return copied;
  }
  await fsp.mkdir(destinationDir, { recursive: true });
  const dedup = new Set();
  let idx = 1;
  for (const src of paths) {
    if (!src || dedup.has(src) || !fileExists(src)) continue;
    dedup.add(src);
    const ext = path.extname(src) || '.bin';
    const target = path.join(destinationDir, `${prefix}-${String(idx).padStart(2, '0')}${ext}`);
    await fsp.copyFile(src, target);
    copied.push(target);
    idx += 1;
  }
  return copied;
}

function toRelative(baseDir, absolutePath) {
  const rel = path.relative(baseDir, absolutePath);
  return rel.split(path.sep).join('/');
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const scriptPath = args.script ? path.resolve(args.script) : '';
  const outputDir = args.output ? path.resolve(args.output) : '';
  const browser = toSafeBrowser(args.browser);
  const resultFile = args.result ? path.resolve(args.result) : path.join(outputDir, 'result.json');
  const timeoutMs = Number.isFinite(Number(args.timeoutMs)) ? Number(args.timeoutMs) : 180_000;

  if (!scriptPath || !outputDir) {
    throw new Error('Missing required arguments: --script --output');
  }
  if (!fileExists(scriptPath)) {
    throw new Error(`Script file not found: ${scriptPath}`);
  }

  await fsp.mkdir(outputDir, { recursive: true });
  const sourceExt = path.extname(scriptPath).toLowerCase();
  const runScriptExt = sourceExt === '.ts' || sourceExt === '.tsx' ? '.spec.ts' : '.spec.js';
  const runScriptPath = path.join(outputDir, `generated${runScriptExt}`);
  await fsp.copyFile(scriptPath, runScriptPath);
  const reportFile = path.join(outputDir, 'playwright-report.json');
  const testOutputDir = path.join(outputDir, 'test-output');
  const configFile = path.join(outputDir, 'playwright.config.cjs');
  const screenshotsDir = path.join(outputDir, 'screenshots');
  const videosDir = path.join(outputDir, 'videos');
  const tracesDir = path.join(outputDir, 'traces');

  const config = `
module.exports = {
  timeout: ${Math.max(30_000, timeoutMs)},
  workers: 1,
  retries: 0,
  reporter: [['json', { outputFile: ${JSON.stringify(reportFile)} }]],
  outputDir: ${JSON.stringify(testOutputDir)},
  use: {
    browserName: ${JSON.stringify(browser)},
    headless: true,
    viewport: { width: 1440, height: 900 },
    video: 'on',
    screenshot: 'on',
    trace: 'retain-on-failure'
  }
};
`;
  await fsp.writeFile(configFile, config, 'utf8');

  const command = [
    cliPath,
    'test',
    runScriptPath,
    '--config',
    configFile,
    '--workers=1'
  ];
  const env = {
    ...process.env,
    CI: '1',
    NODE_PATH: [runnerNodeModules, process.env.NODE_PATH]
      .filter(Boolean)
      .join(path.delimiter)
  };

  const child = spawn('node', command, {
    cwd: outputDir,
    env,
    stdio: ['ignore', 'pipe', 'pipe']
  });

  const stdoutLines = [];
  const stderrLines = [];

  child.stdout.on('data', (chunk) => {
    const lines = splitLines(chunk.toString('utf8'));
    for (const line of lines) {
      stdoutLines.push(line);
      console.log(`[PW] ${line}`);
    }
  });

  child.stderr.on('data', (chunk) => {
    const lines = splitLines(chunk.toString('utf8'));
    for (const line of lines) {
      stderrLines.push(line);
      console.log(`[PWERR] ${line}`);
    }
  });

  const exitCode = await new Promise((resolve) => {
    child.on('close', (code) => resolve(typeof code === 'number' ? code : 1));
  });

  const report = fileExists(reportFile)
    ? JSON.parse(await fsp.readFile(reportFile, 'utf8'))
    : null;

  const tests = [];
  const screenshotSource = [];
  const videoSource = [];
  const traceSource = [];

  if (report && Array.isArray(report.suites)) {
    const specs = [];
    for (const suite of report.suites) {
      collectSpecs(suite, specs);
    }
    for (const spec of specs) {
      const title = String(spec?.title || spec?.ok || 'Playwright Test');
      const testEntries = Array.isArray(spec?.tests) ? spec.tests : [];
      for (const testEntry of testEntries) {
        const results = Array.isArray(testEntry?.results) ? testEntry.results : [];
        const latest = results.length ? results[results.length - 1] : {};
        const status = String(latest?.status || testEntry?.outcome || 'unknown');
        const durationMs = Number.isFinite(Number(latest?.duration)) ? Number(latest.duration) : 0;
        let error = '';
        if (latest?.error?.message) {
          error = String(latest.error.message);
        } else if (latest?.errors && Array.isArray(latest.errors) && latest.errors.length) {
          error = String(latest.errors[0]?.message || '');
        }

        tests.push({
          title,
          status,
          durationMs,
          error
        });

        const attachments = Array.isArray(latest?.attachments) ? latest.attachments : [];
        for (const attachment of attachments) {
          const attachmentPath = safeResolve(testOutputDir, attachment?.path);
          if (!attachmentPath || !fileExists(attachmentPath)) continue;
          const contentType = String(attachment?.contentType || '').toLowerCase();
          const name = String(attachment?.name || '').toLowerCase();
          const ext = path.extname(attachmentPath).toLowerCase();
          if (contentType.includes('image') || ext === '.png' || ext === '.jpg' || ext === '.jpeg') {
            screenshotSource.push(attachmentPath);
          } else if (contentType.includes('video') || ext === '.webm' || ext === '.mp4') {
            videoSource.push(attachmentPath);
          } else if (ext === '.zip' || name.includes('trace')) {
            traceSource.push(attachmentPath);
          }
        }
      }
    }
  }

  const screenshotFiles = await copyAttachments(screenshotSource, screenshotsDir, 'shot');
  const videoFiles = await copyAttachments(videoSource, videosDir, 'video');
  const traceFiles = await copyAttachments(traceSource, tracesDir, 'trace');

  const passedCount = tests.filter((item) => String(item.status).toLowerCase() === 'passed').length;
  const failedCount = tests.filter((item) => {
    const status = String(item.status).toLowerCase();
    return status === 'failed' || status === 'timedout' || status === 'interrupted';
  }).length;
  const skippedCount = tests.filter((item) => String(item.status).toLowerCase() === 'skipped').length;
  const totalDuration = tests.reduce((sum, item) => sum + (Number(item.durationMs) || 0), 0);

  let errorMessage = '';
  if (failedCount > 0) {
    const firstFailed = tests.find((item) => String(item.status).toLowerCase() !== 'passed');
    errorMessage = String(firstFailed?.error || '存在失败断言').trim();
  } else if (exitCode !== 0) {
    errorMessage = stderrLines.slice(-5).join(' | ') || stdoutLines.slice(-5).join(' | ') || `Runner exited with code ${exitCode}`;
  }

  const success = failedCount === 0 && exitCode === 0;
  const summary = {
    success,
    status: success ? 'PASSED' : 'FAILED',
    durationMs: totalDuration,
    errorMessage,
    reportFile: fileExists(reportFile) ? toRelative(outputDir, reportFile) : '',
    videoFiles: videoFiles.map((item) => toRelative(outputDir, item)),
    screenshotFiles: screenshotFiles.map((item) => toRelative(outputDir, item)),
    traceFiles: traceFiles.map((item) => toRelative(outputDir, item)),
    tests,
    passedCount,
    failedCount,
    skippedCount
  };

  await fsp.writeFile(resultFile, JSON.stringify(summary, null, 2), 'utf8');
  console.log(`PW_RESULT ${JSON.stringify(summary)}`);
  process.exit(success ? 0 : 1);
}

main().catch(async (error) => {
  const message = String(error?.message || error || 'Unknown runner error');
  const fallback = {
    success: false,
    status: 'ERROR',
    durationMs: 0,
    errorMessage: message,
    reportFile: '',
    videoFiles: [],
    screenshotFiles: [],
    traceFiles: [],
    tests: [],
    passedCount: 0,
    failedCount: 0,
    skippedCount: 0
  };
  try {
    const args = parseArgs(process.argv.slice(2));
    const resultFile = args.result ? path.resolve(args.result) : '';
    if (resultFile) {
      await fsp.mkdir(path.dirname(resultFile), { recursive: true });
      await fsp.writeFile(resultFile, JSON.stringify(fallback, null, 2), 'utf8');
    }
  } catch (_ignored) {
    // ignore
  }
  console.error(`PW_FATAL ${message}`);
  process.exit(1);
});
