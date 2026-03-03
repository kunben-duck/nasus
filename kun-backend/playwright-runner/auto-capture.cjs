'use strict';

const fs = require('node:fs');
const Module = require('node:module');
const path = require('node:path');

const screenshotDir = process.env.KUN_CAPTURE_SCREENSHOT_DIR
  ? path.resolve(process.env.KUN_CAPTURE_SCREENSHOT_DIR)
  : '';
const videoDir = process.env.KUN_CAPTURE_VIDEO_DIR
  ? path.resolve(process.env.KUN_CAPTURE_VIDEO_DIR)
  : '';
const metaFile = process.env.KUN_CAPTURE_META_FILE
  ? path.resolve(process.env.KUN_CAPTURE_META_FILE)
  : '';
const videoWidth = Number.parseInt(process.env.KUN_CAPTURE_VIDEO_WIDTH || '1440', 10) || 1440;
const videoHeight = Number.parseInt(process.env.KUN_CAPTURE_VIDEO_HEIGHT || '900', 10) || 900;
const imageType = String(process.env.KUN_CAPTURE_IMAGE_TYPE || 'jpeg').trim().toLowerCase() === 'png'
  ? 'png'
  : 'jpeg';
const imageQuality = Number.parseInt(process.env.KUN_CAPTURE_IMAGE_QUALITY || '68', 10);
const useFullPageCapture = String(process.env.KUN_CAPTURE_FULLPAGE || '').trim().toLowerCase() === 'true';

if (screenshotDir) {
  fs.mkdirSync(screenshotDir, { recursive: true });
}
if (videoDir) {
  fs.mkdirSync(videoDir, { recursive: true });
}
if (metaFile) {
  fs.mkdirSync(path.dirname(metaFile), { recursive: true });
}

let actionCounter = 0;

function safeRequire(moduleId) {
  try {
    return require(moduleId);
  } catch (_err) {
    return null;
  }
}

function safeRequirePackageInternal(packageName, relativeFile) {
  try {
    const packageJsonPath = require.resolve(`${packageName}/package.json`);
    const packageRoot = path.dirname(packageJsonPath);
    const targetPath = path.join(packageRoot, relativeFile);
    if (!fs.existsSync(targetPath)) return null;
    return require(targetPath);
  } catch (_err) {
    return null;
  }
}

function sanitizeToken(value, fallback = 'na') {
  const normalized = String(value || '').trim().toLowerCase();
  const safe = normalized.replace(/[^a-z0-9_-]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
  if (!safe) return fallback;
  return safe.slice(0, 48);
}

function appendMeta(entry) {
  if (!metaFile) return;
  try {
    fs.appendFileSync(metaFile, `${JSON.stringify(entry)}\n`, 'utf8');
  } catch (_err) {
    // ignore metadata flush failures
  }
}

function describeArgument(value) {
  if (typeof value === 'string') return value;
  if (value == null) return '';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `list-${value.length}`;
  if (typeof value === 'object') {
    if (typeof value.name === 'string' && value.name) return value.name;
    if (typeof value.url === 'string' && value.url) return value.url;
    return 'object';
  }
  return '';
}

function resolvePage(target) {
  if (!target) return null;
  if (typeof target.screenshot === 'function') return target;
  if (typeof target.page === 'function') {
    try {
      const page = target.page();
      if (page && typeof page.screenshot === 'function') return page;
    } catch (_err) {
      return null;
    }
  }
  return null;
}

function describeTargetFromContext(target) {
  if (!target) return '';
  try {
    if (typeof target.toString === 'function') {
      const value = String(target.toString()).trim();
      if (value && value !== '[object Object]') return value;
    }
  } catch (_err) {
    return '';
  }
  return '';
}

function shouldCaptureAction(action, targetText) {
  const normalizedAction = String(action || '').trim().toLowerCase();
  const normalizedTarget = String(targetText || '').trim();
  if (!normalizedAction) return false;
  if (!normalizedTarget && normalizedAction !== 'goto') return false;
  if (normalizedAction === 'fill' || normalizedAction === 'type') {
    const looksSelector = /[#.\[:>]|^https?:\/\/|^locator\(|^framelocator\(/i.test(normalizedTarget);
    if (!looksSelector) return false;
  }
  return true;
}

async function captureActionScreenshot(target, action, args, phase) {
  const page = resolvePage(target);
  if (!page || !screenshotDir) return;
  if (typeof page.isClosed === 'function' && page.isClosed()) return;
  actionCounter += 1;
  const argTarget = args.length > 0 ? describeArgument(args[0]) : '';
  const rawTarget = argTarget || describeTargetFromContext(target);
  if (!shouldCaptureAction(action, rawTarget)) return;
  const normalizedTarget = sanitizeToken(rawTarget, 'target');
  const extension = imageType === 'png' ? 'png' : 'jpg';
  const fileName = [
    'act',
    String(actionCounter).padStart(4, '0'),
    sanitizeToken(action, 'action'),
    normalizedTarget
  ].join('-') + `.${extension}`;
  const filePath = path.join(screenshotDir, fileName);

  try {
    const screenshotOptions = {
      path: filePath,
      type: imageType,
      fullPage: useFullPageCapture,
      timeout: 10_000
    };
    if (imageType === 'jpeg' && Number.isFinite(imageQuality)) {
      screenshotOptions.quality = Math.min(100, Math.max(1, imageQuality));
    }
    await page.screenshot(screenshotOptions);
    appendMeta({
      stepNumber: actionCounter,
      action,
      target: rawTarget,
      phase,
      file: filePath,
      createdAt: new Date().toISOString()
    });
  } catch (_err) {
    appendMeta({
      stepNumber: actionCounter,
      action,
      target: rawTarget,
      phase,
      file: filePath,
      failed: true,
      createdAt: new Date().toISOString()
    });
  }
}

function wrapActionMethod(proto, methodName) {
  if (!proto) return;
  const original = proto[methodName];
  if (typeof original !== 'function') return;
  if (original.__kunAutoCaptureWrapped) return;
  const wrapped = async function wrappedActionMethod(...args) {
    const result = await original.apply(this, args);
    await captureActionScreenshot(this, methodName, args, 'after');
    return result;
  };
  wrapped.__kunAutoCaptureWrapped = true;
  proto[methodName] = wrapped;
}

function patchActionPrototype(proto, methods) {
  if (!proto || !Array.isArray(methods)) return;
  methods.forEach((methodName) => wrapActionMethod(proto, methodName));
}

function patchBrowserInstance(browser) {
  if (!browser || typeof browser.newContext !== 'function') return browser;
  const original = browser.newContext;
  if (original.__kunAutoCaptureWrapped) return browser;
  browser.newContext = async function patchedNewContext(options = {}, ...rest) {
    const merged = { ...(options || {}) };
    const current = merged.recordVideo && typeof merged.recordVideo === 'object'
      ? merged.recordVideo
      : {};
    if (videoDir) {
      merged.recordVideo = {
        dir: current.dir || videoDir,
        size: current.size || { width: videoWidth, height: videoHeight }
      };
    }
    return original.call(this, merged, ...rest);
  };
  browser.newContext.__kunAutoCaptureWrapped = true;
  return browser;
}

function patchBrowserPrototype(proto) {
  if (!proto || typeof proto.newContext !== 'function') return;
  const original = proto.newContext;
  if (original.__kunAutoCaptureWrapped) return;
  proto.newContext = async function patchedPrototypeNewContext(options = {}, ...rest) {
    const merged = { ...(options || {}) };
    const current = merged.recordVideo && typeof merged.recordVideo === 'object'
      ? merged.recordVideo
      : {};
    if (videoDir) {
      merged.recordVideo = {
        dir: current.dir || videoDir,
        size: current.size || { width: videoWidth, height: videoHeight }
      };
    }
    return original.call(this, merged, ...rest);
  };
  proto.newContext.__kunAutoCaptureWrapped = true;
}

function patchBrowserType(browserType) {
  if (!browserType || typeof browserType.launch !== 'function') return;
  const original = browserType.launch;
  if (original.__kunAutoCaptureWrapped) return;
  browserType.launch = async function patchedLaunch(...args) {
    const browser = await original.apply(this, args);
    return patchBrowserInstance(browser);
  };
  browserType.launch.__kunAutoCaptureWrapped = true;
}

function patchPlaywrightLikeModule(mod) {
  if (!mod || typeof mod !== 'object') return;

  // Browser-level video enforcement for custom scripts.
  patchBrowserType(mod.chromium);
  patchBrowserType(mod.firefox);
  patchBrowserType(mod.webkit);
  patchBrowserType(mod.BrowserType && mod.BrowserType.prototype);

  // Action-level screenshot capture.
  const pageMethods = [
    'goto',
    'click',
    'dblclick',
    'fill',
    'type',
    'press',
    'check',
    'uncheck',
    'selectOption',
    'setInputFiles',
    'tap',
    'dragAndDrop'
  ];
  const locatorMethods = [
    'click',
    'dblclick',
    'fill',
    'type',
    'press',
    'check',
    'uncheck',
    'selectOption',
    'setInputFiles',
    'tap',
    'dragTo'
  ];

  patchActionPrototype(mod.Page && mod.Page.prototype, pageMethods);
  patchActionPrototype(mod.Locator && mod.Locator.prototype, locatorMethods);
  patchBrowserPrototype(mod.Browser && mod.Browser.prototype);
}

function patchInternalPlaywrightModules() {
  const candidates = [
    'playwright',
    '@playwright/test',
    'playwright-core'
  ];
  candidates.forEach((moduleId) => {
    const mod = safeRequire(moduleId);
    if (mod) {
      patchPlaywrightLikeModule(mod);
    }
  });

  [
    'lib/client/page.js',
    'lib/client/locator.js',
    'lib/client/frame.js',
    'lib/client/browser.js',
    'lib/client/browserType.js',
    'lib/client/playwright.js'
  ].forEach((relativeFile) => {
    const coreModule = safeRequirePackageInternal('playwright-core', relativeFile);
    if (coreModule) {
      patchPlaywrightLikeModule(coreModule);
    }
    const playwrightModule = safeRequirePackageInternal('playwright', relativeFile);
    if (playwrightModule) {
      patchPlaywrightLikeModule(playwrightModule);
    }
  });
}

const originalModuleLoad = Module._load;
Module._load = function kunPatchedModuleLoad(request, parent, isMain) {
  const loaded = originalModuleLoad.apply(this, arguments);
  if (typeof request === 'string' && request.includes('playwright')) {
    patchPlaywrightLikeModule(loaded);
  }
  return loaded;
};

patchInternalPlaywrightModules();
