(() => {
  'use strict';

  const STORAGE_KEYS = {
    accessToken: 'autotest_access_token',
    refreshToken: 'autotest_refresh_token',
    user: 'autotest_user',
    settings: 'autotest_settings'
  };

  const DEFAULT_SETTINGS = {
    apiBase: '/api',
    defaultBrowser: 'chromium',
    defaultEnvironment: 'staging',
    defaultTargetUrl: 'https://example.com',
    theme: 'dark',
    language: 'zh-CN',
    timezone: 'Asia/Shanghai',
    autoSave: true,
    notifications: true,
    telemetry: false,
    modelProvider: 'OPENAI',
    modelBaseUrl: 'https://api.openai.com/v1',
    modelApiKey: '',
    modelName: 'gpt-4o-mini',
    modelTemperature: 0.7
  };
  const DEFAULT_TIMEZONE = DEFAULT_SETTINGS.timezone;
  const DATE_TIME_FORMATTER_CACHE = new Map();

  let authModalPromise = null;
  let authModalResolver = null;
  let authModalRejecter = null;
  let profileModalState = null;
  let confirmModalNode = null;
  let confirmModalResolver = null;
  let confirmModalEscHandler = null;
  let globalSearchModalNode = null;
  let globalSearchEscHandler = null;
  let globalSearchShortcutBound = false;
  let globalTopActionsOutsideClickBound = false;
  let globalTopActionsObserver = null;
  let globalTopActionsObserverFramePending = false;
  let globalTopActionsRetryTimers = [];
  let globalNotificationCache = {
    timestamp: 0,
    items: [],
    unreadCount: 0
  };
  let notificationSelectedIds = new Set();
  let notificationPollTimer = null;
  let notificationSeenStorageKey = '';
  let notificationSeenIds = new Set();
  let notificationPollInitialized = false;

  const PROFILE_MAX_AVATAR_LENGTH = 58000;
  const PROFILE_EMOJI_AVATARS = ['🐼', '🦊', '🐯', '🦁', '🐨', '🐶', '🐱', '🐸', '🐧', '🦉', '🐰', '🐻'];
  const GLOBAL_NOTIFICATION_CACHE_MS = 8000;
  const NOTIFICATION_POLL_INTERVAL_MS = 7000;
  const NOTIFICATION_PAGE_SIZE = 20;
  const NOTIFICATION_SEEN_STORAGE_PREFIX = 'autotest_notification_seen';
  const SIDEBAR_COLLAPSE_STORAGE_KEY = 'autotest_sidebar_collapsed';
  const SIDEBAR_EXPANDED_WIDTH = '15rem';
  const SIDEBAR_COLLAPSED_WIDTH = '5rem';

  function toSvgDataUrl(svgMarkup) {
    return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svgMarkup)}`;
  }

  function createGalleryAvatar(label, fromColor, toColor) {
    const safeLabel = String(label || '').slice(0, 2).toUpperCase();
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
        <defs>
          <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="${fromColor}" />
            <stop offset="100%" stop-color="${toColor}" />
          </linearGradient>
        </defs>
        <rect width="120" height="120" rx="28" fill="url(#bg)"/>
        <circle cx="60" cy="60" r="36" fill="rgba(255,255,255,0.18)"/>
        <text x="60" y="70" text-anchor="middle" font-size="30" font-family="Inter,Arial,sans-serif" fill="#ffffff" font-weight="700">${safeLabel}</text>
      </svg>
    `;
    return toSvgDataUrl(svg);
  }

  const PROFILE_GALLERY_AVATARS = [
    { key: 'a1', label: 'AI', value: createGalleryAvatar('AI', '#00d4ff', '#7c3aed') },
    { key: 'q1', label: 'QA', value: createGalleryAvatar('QA', '#22d3ee', '#2563eb') },
    { key: 'tm', label: 'TM', value: createGalleryAvatar('TM', '#34d399', '#0ea5e9') },
    { key: 'td', label: 'TD', value: createGalleryAvatar('TD', '#f59e0b', '#ef4444') },
    { key: 'sa', label: 'SA', value: createGalleryAvatar('SA', '#a78bfa', '#ec4899') },
    { key: 'ux', label: 'UX', value: createGalleryAvatar('UX', '#14b8a6', '#6366f1') }
  ];

  function safeJsonParse(raw, fallback) {
    if (!raw) return fallback;
    try {
      return JSON.parse(raw);
    } catch (_err) {
      return fallback;
    }
  }

  function getSettings() {
    const parsed = safeJsonParse(localStorage.getItem(STORAGE_KEYS.settings), {});
    const merged = { ...DEFAULT_SETTINGS, ...parsed };
    merged.timezone = normalizeTimeZone(merged.timezone);
    return merged;
  }

  function saveSettings(nextSettings) {
    const merged = { ...getSettings(), ...(nextSettings || {}) };
    localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(merged));
    return merged;
  }

  function getAccessToken() {
    return localStorage.getItem(STORAGE_KEYS.accessToken);
  }

  function getRefreshToken() {
    return localStorage.getItem(STORAGE_KEYS.refreshToken);
  }

  function setAuth(payload) {
    localStorage.setItem(STORAGE_KEYS.accessToken, payload.accessToken || '');
    localStorage.setItem(STORAGE_KEYS.refreshToken, payload.refreshToken || '');
    if (payload.user) {
      localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(payload.user));
    }
  }

  function clearAuth() {
    localStorage.removeItem(STORAGE_KEYS.accessToken);
    localStorage.removeItem(STORAGE_KEYS.refreshToken);
    localStorage.removeItem(STORAGE_KEYS.user);
  }

  function getUserCache() {
    return safeJsonParse(localStorage.getItem(STORAGE_KEYS.user), null);
  }

  function setUserCache(user) {
    if (!user) return;
    localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(user));
  }

  function resolveApiBase() {
    const settings = getSettings();
    const base = (settings.apiBase || '/api').trim();
    if (base.startsWith('http://') || base.startsWith('https://')) return base.replace(/\/$/, '');
    const normalized = base.startsWith('/') ? base : `/${base}`;
    return normalized.replace(/\/$/, '');
  }

  function normalizeErrorMessage(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload === 'string') return payload;
    if (payload.message) return payload.message;
    if (payload.error) return payload.error;
    return fallback;
  }

  async function refreshAccessToken() {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return false;

    const url = `${resolveApiBase()}/auth/refresh`;
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json'
      },
      body: JSON.stringify({ refreshToken })
    });

    const payload = await parseResponsePayload(response);
    if (!response.ok || !payload?.success || !payload?.data?.accessToken) {
      clearAuth();
      return false;
    }

    localStorage.setItem(STORAGE_KEYS.accessToken, payload.data.accessToken);
    localStorage.setItem(STORAGE_KEYS.refreshToken, payload.data.refreshToken || refreshToken);
    return true;
  }

  async function parseResponsePayload(response) {
    const contentType = response.headers.get('content-type') || '';
    if (response.status === 204) return null;
    if (!contentType.includes('application/json')) {
      const text = await response.text();
      return text || null;
    }
    try {
      return await response.json();
    } catch (_err) {
      return null;
    }
  }

  async function api(path, options = {}) {
    const {
      method = 'GET',
      body,
      headers = {},
      auth = true,
      raw = false,
      retry = true
    } = options;

    const endpoint = path.startsWith('http://') || path.startsWith('https://')
      ? path
      : `${resolveApiBase()}${path.startsWith('/') ? path : `/${path}`}`;

    const requestHeaders = {
      Accept: 'application/json',
      ...headers
    };

    let payloadBody;
    if (body !== undefined && body !== null) {
      if (typeof body === 'string' || body instanceof FormData) {
        payloadBody = body;
      } else {
        requestHeaders['Content-Type'] = 'application/json';
        payloadBody = JSON.stringify(body);
      }
    }

    if (auth) {
      const token = getAccessToken();
      if (token) {
        requestHeaders.Authorization = `Bearer ${token}`;
      }
    }

    const response = await fetch(endpoint, {
      method,
      headers: requestHeaders,
      body: payloadBody
    });

    if (response.status === 401 && auth && retry) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        return api(path, { ...options, retry: false });
      }
    }

    const payload = await parseResponsePayload(response);

    if (!response.ok) {
      const message = normalizeErrorMessage(payload, `请求失败: ${response.status}`);
      throw new Error(message);
    }

    if (raw) return payload;

    if (payload && typeof payload === 'object' && 'success' in payload) {
      if (!payload.success) {
        throw new Error(normalizeErrorMessage(payload, '请求失败'));
      }
      return payload.data;
    }

    return payload;
  }

  function toast(message, type = 'info', duration = 3200) {
    let container = document.getElementById('app-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'app-toast-container';
      container.style.cssText = [
        'position: fixed',
        'right: 16px',
        'bottom: 16px',
        'display: grid',
        'gap: 8px',
        'z-index: 11050'
      ].join(';');
      document.body.appendChild(container);
    }

    const color = type === 'success'
      ? '#10b981'
      : type === 'error'
        ? '#ef4444'
        : type === 'warning'
          ? '#f59e0b'
          : '#00d4ff';

    const item = document.createElement('div');
    item.style.cssText = [
      'min-width: 240px',
      'max-width: 460px',
      'padding: 10px 14px',
      'border-radius: 10px',
      'border: 1px solid rgba(255,255,255,0.12)',
      'backdrop-filter: blur(14px)',
      'background: rgba(18,18,26,0.92)',
      'color: #fff',
      'box-shadow: 0 8px 20px rgba(0,0,0,0.35)',
      'font-size: 13px',
      `border-left: 4px solid ${color}`
    ].join(';');
    item.textContent = message;
    container.appendChild(item);

    window.setTimeout(() => {
      item.remove();
    }, duration);
  }

  function closeConfirmDialog(result = false) {
    if (confirmModalNode) {
      confirmModalNode.classList.add('hidden');
    }
    if (typeof confirmModalResolver === 'function') {
      const resolver = confirmModalResolver;
      confirmModalResolver = null;
      resolver(Boolean(result));
    }
  }

  function ensureConfirmDialog() {
    if (confirmModalNode) return confirmModalNode;

    confirmModalNode = document.createElement('div');
    confirmModalNode.className = 'hidden fixed inset-0 z-[11100] bg-black/70 backdrop-blur-sm';
    confirmModalNode.innerHTML = `
      <div class="absolute inset-0 flex items-center justify-center p-4">
        <div class="w-full max-w-md rounded-2xl border border-white/10 bg-[#18181f] shadow-2xl overflow-hidden">
          <div class="px-5 py-4 border-b border-white/10">
            <h3 id="app-confirm-title" class="text-base font-semibold text-white">确认操作</h3>
          </div>
          <div class="px-5 py-4">
            <p id="app-confirm-message" class="text-sm text-[#e4e4e7] leading-relaxed"></p>
          </div>
          <div class="px-5 py-4 border-t border-white/10 flex items-center justify-end gap-2">
            <button id="app-confirm-cancel" class="px-3 py-1.5 text-sm rounded bg-white/10 text-[#d4d4d8] hover:bg-white/20">取消</button>
            <button id="app-confirm-ok" class="px-3 py-1.5 text-sm rounded bg-[#ef4444]/25 text-[#fecaca] hover:bg-[#ef4444]/35">确认</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(confirmModalNode);

    confirmModalNode.querySelector('#app-confirm-cancel')?.addEventListener('click', () => {
      closeConfirmDialog(false);
    });
    confirmModalNode.querySelector('#app-confirm-ok')?.addEventListener('click', () => {
      closeConfirmDialog(true);
    });
    confirmModalNode.addEventListener('click', (event) => {
      if (event.target === confirmModalNode) {
        closeConfirmDialog(false);
      }
    });

    if (!confirmModalEscHandler) {
      confirmModalEscHandler = (event) => {
        if (event.key !== 'Escape' || !confirmModalNode) return;
        if (!confirmModalNode.classList.contains('hidden')) {
          closeConfirmDialog(false);
        }
      };
      document.addEventListener('keydown', confirmModalEscHandler);
    }

    return confirmModalNode;
  }

  function confirm(options = {}) {
    const modal = ensureConfirmDialog();
    const titleNode = modal.querySelector('#app-confirm-title');
    const messageNode = modal.querySelector('#app-confirm-message');
    const okButton = modal.querySelector('#app-confirm-ok');
    const cancelButton = modal.querySelector('#app-confirm-cancel');
    const tone = String(options.tone || 'danger').toLowerCase();

    if (titleNode) {
      titleNode.textContent = String(options.title || '确认操作');
    }
    if (messageNode) {
      messageNode.textContent = String(options.message || '');
    }
    if (cancelButton) {
      cancelButton.textContent = String(options.cancelText || '取消');
    }
    if (okButton) {
      okButton.textContent = String(options.confirmText || '确认');
      if (tone === 'primary') {
        okButton.className = 'px-3 py-1.5 text-sm rounded bg-[#0ea5e9]/25 text-[#7dd3fc] hover:bg-[#0ea5e9]/35';
      } else {
        okButton.className = 'px-3 py-1.5 text-sm rounded bg-[#ef4444]/25 text-[#fecaca] hover:bg-[#ef4444]/35';
      }
    }

    if (typeof confirmModalResolver === 'function') {
      const previousResolver = confirmModalResolver;
      confirmModalResolver = null;
      previousResolver(false);
    }

    modal.classList.remove('hidden');
    return new Promise((resolve) => {
      confirmModalResolver = resolve;
    });
  }

  function escapeHtml(input) {
    return String(input ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function buildInitials(name) {
    const normalized = String(name || '').trim();
    if (!normalized) return 'U';
    const words = normalized.split(/\s+/).filter(Boolean);
    if (words.length >= 2) {
      return `${words[0][0] || ''}${words[1][0] || ''}`.toUpperCase();
    }
    return normalized.slice(0, 2).toUpperCase();
  }

  function isAvatarImageValue(value) {
    const normalized = String(value || '').trim();
    if (!normalized) return false;
    return /^data:image\//i.test(normalized)
      || /^https?:\/\//i.test(normalized)
      || normalized.startsWith('/');
  }

  function applyAvatarNode(node, avatarValue, fallbackText) {
    if (!node) return;
    const normalized = String(avatarValue || '').trim();
    const textNode = node.querySelector('#user-initials') || node.querySelector('span');

    node.style.backgroundImage = '';
    node.style.backgroundSize = '';
    node.style.backgroundPosition = '';
    node.style.backgroundRepeat = '';
    node.style.background = 'linear-gradient(135deg, #00d4ff 0%, #7c3aed 100%)';

    if (isAvatarImageValue(normalized)) {
      node.style.backgroundImage = `url("${normalized.replace(/"/g, '\\"')}")`;
      node.style.backgroundSize = 'cover';
      node.style.backgroundPosition = 'center';
      node.style.backgroundRepeat = 'no-repeat';
      if (textNode) {
        textNode.textContent = '';
        textNode.style.display = 'none';
      } else {
        node.textContent = '';
      }
      return;
    }

    const displayText = normalized || fallbackText;
    if (textNode) {
      textNode.textContent = displayText;
      textNode.style.display = '';
    } else {
      node.textContent = displayText;
    }
  }

  function unwrapPageItems(data) {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (Array.isArray(data.content)) return data.content;
    return [];
  }

  function sortByLatest(items, field = 'createdAt') {
    return [...(items || [])].sort((a, b) => {
      const aTime = new Date(a?.[field] || 0).getTime();
      const bTime = new Date(b?.[field] || 0).getTime();
      return bTime - aTime;
    });
  }

  async function imageFileToAvatarDataUrl(file, targetSize = 192) {
    const fileReader = new FileReader();
    const rawDataUrl = await new Promise((resolve, reject) => {
      fileReader.onload = () => resolve(String(fileReader.result || ''));
      fileReader.onerror = () => reject(new Error('读取头像文件失败'));
      fileReader.readAsDataURL(file);
    });

    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error('头像图片格式无效'));
      image.src = rawDataUrl;
    });

    const cropSize = Math.min(image.width, image.height);
    const sx = Math.max(0, Math.floor((image.width - cropSize) / 2));
    const sy = Math.max(0, Math.floor((image.height - cropSize) / 2));

    const canvas = document.createElement('canvas');
    canvas.width = targetSize;
    canvas.height = targetSize;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('头像处理失败');
    ctx.drawImage(image, sx, sy, cropSize, cropSize, 0, 0, targetSize, targetSize);

    return canvas.toDataURL('image/jpeg', 0.86);
  }

  function closePossibleUserMenus() {
    const topMenu = document.getElementById('user-menu');
    if (topMenu) topMenu.classList.add('hidden');

    const sidebarDropdown = document.querySelector('.sidebar-footer #user-dropdown');
    if (sidebarDropdown) sidebarDropdown.classList.add('hidden');

    const globalUserMenu = document.getElementById('app-global-user-menu');
    if (globalUserMenu) globalUserMenu.classList.add('hidden');

    const globalNotificationsPanel = document.getElementById('app-global-notifications-panel');
    if (globalNotificationsPanel) globalNotificationsPanel.classList.add('hidden');

    const dashboardNotificationsPanel = document.getElementById('notifications-panel');
    if (dashboardNotificationsPanel) dashboardNotificationsPanel.classList.add('hidden');
  }

  function syncUserDisplay(user) {
    if (!user) return;
    const displayName = user.fullName || user.username || 'User';
    const tenantSuffix = user.activeTenantName ? ` · ${user.activeTenantName}` : '';
    const role = `${user.roleDisplayName || user.role || '用户'}${tenantSuffix}`;
    const avatar = String(user.avatar || '').trim();
    const shortName = buildInitials(displayName);

    const sidebarName = document.getElementById('user-name');
    if (sidebarName) sidebarName.textContent = displayName;

    const sidebarRole = document.getElementById('user-role');
    if (sidebarRole) sidebarRole.textContent = role;

    const topNameNodes = Array.from(document.querySelectorAll('#user-dropdown .text-sm.font-medium, #user-menu .text-sm.font-medium, #app-global-user-menu .text-sm.font-medium, #app-global-user-trigger .text-sm.font-medium'));
    topNameNodes.forEach((node) => {
      node.textContent = displayName;
    });

    const topRoleNodes = Array.from(document.querySelectorAll('#user-dropdown .text-xs, #user-menu .text-xs, #app-global-user-menu .text-xs, #app-global-user-trigger .text-xs'));
    topRoleNodes.forEach((node) => {
      node.textContent = role;
    });

    const avatarNodes = [
      ...Array.from(document.querySelectorAll('#user-dropdown .w-8.h-8.rounded-full')),
      ...Array.from(document.querySelectorAll('#user-menu .w-8.h-8.rounded-full')),
      ...Array.from(document.querySelectorAll('#app-global-user-menu .w-8.h-8.rounded-full')),
      ...Array.from(document.querySelectorAll('#app-global-user-trigger .w-8.h-8.rounded-full')),
      ...Array.from(document.querySelectorAll('#user-menu-trigger .sidebar-user-avatar'))
    ];
    Array.from(new Set(avatarNodes)).forEach((node) => {
      applyAvatarNode(node, avatar, shortName);
    });
  }

  function resolveAppPagePath(pageKey) {
    const inPages = /\/pages\//.test(window.location.pathname || '');
    const pages = {
      index: inPages ? '../index.html' : './index.html',
      'us-management': inPages ? './us-management.html' : './pages/us-management.html',
      'test-cases': inPages ? './test-cases.html' : './pages/test-cases.html',
      'script-studio': inPages ? './script-studio.html' : './pages/script-studio.html',
      'execution-hub': inPages ? './execution-hub.html' : './pages/execution-hub.html',
      reports: inPages ? './reports.html' : './pages/reports.html',
      settings: inPages ? './settings.html' : './pages/settings.html'
    };
    return pages[pageKey] || pages.index;
  }

  function hasDedicatedPageSearchInput() {
    const main = document.querySelector('main');
    if (!main) return false;
    const candidates = Array.from(main.querySelectorAll('input[type="search"], input[placeholder*="搜索"]'));
    return candidates.some((node) => {
      if (!(node instanceof HTMLInputElement)) return false;
      if (node.id === 'app-global-search-input') return false;
      return !node.disabled && node.offsetParent !== null;
    });
  }

  function shouldShowGlobalSearchButton() {
    const path = (window.location.pathname || '').toLowerCase();
    if (/\/index\.html$/.test(path) || path === '/' || path === '') {
      return false;
    }
    return !hasDedicatedPageSearchInput();
  }

  function closeGlobalSearchModal() {
    if (!globalSearchModalNode) return;
    if (globalSearchEscHandler) {
      document.removeEventListener('keydown', globalSearchEscHandler);
      globalSearchEscHandler = null;
    }
    globalSearchModalNode.remove();
    globalSearchModalNode = null;
    document.body.style.overflow = '';
  }

  function openGlobalSearchModal() {
    if (globalSearchModalNode) return;

    const entries = [
      { label: '仪表盘', keywords: 'dashboard 首页 概览', href: resolveAppPagePath('index'), icon: 'layout-dashboard' },
      { label: 'US需求管理', keywords: 'us 需求 story', href: resolveAppPagePath('us-management'), icon: 'file-text' },
      { label: '测试用例', keywords: 'case 用例 tc', href: resolveAppPagePath('test-cases'), icon: 'check-square' },
      { label: '脚本工作室', keywords: 'script studio 脚本', href: resolveAppPagePath('script-studio'), icon: 'code-2' },
      { label: '执行中心', keywords: 'execution 执行 run', href: resolveAppPagePath('execution-hub'), icon: 'play-circle' },
      { label: '报告中心', keywords: 'report 报告', href: resolveAppPagePath('reports'), icon: 'bar-chart-3' },
      { label: '系统设置', keywords: 'settings 配置', href: resolveAppPagePath('settings'), icon: 'settings' }
    ];

    const overlay = document.createElement('div');
    overlay.id = 'app-global-search-modal';
    overlay.className = 'fixed inset-0 z-[11090] bg-black/70 backdrop-blur-sm';
    overlay.innerHTML = `
      <div class="absolute inset-0 flex items-start justify-center p-4 sm:p-8">
        <div id="app-global-search-panel" class="w-full max-w-2xl rounded-2xl border border-white/10 bg-[#18181f] shadow-2xl overflow-hidden mt-10">
          <div class="px-4 py-3 border-b border-white/10 flex items-center gap-3">
            <i data-lucide="search" class="w-4 h-4 text-[#71717a]"></i>
            <input id="app-global-search-input" type="text" placeholder="搜索页面（如：用例、执行、报告）" class="flex-1 bg-transparent text-sm text-white placeholder-[#71717a] focus:outline-none" />
            <button id="app-global-search-close" type="button" class="px-2 py-1 rounded-md text-xs text-[#a1a1aa] hover:bg-white/5 hover:text-white">Esc</button>
          </div>
          <div id="app-global-search-list" class="max-h-[55vh] overflow-auto p-2"></div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    globalSearchModalNode = overlay;

    const input = overlay.querySelector('#app-global-search-input');
    const list = overlay.querySelector('#app-global-search-list');
    const closeBtn = overlay.querySelector('#app-global-search-close');
    const panel = overlay.querySelector('#app-global-search-panel');

    const renderEntries = (keyword = '') => {
      const normalized = String(keyword || '').trim().toLowerCase();
      const matched = normalized
        ? entries.filter((item) => {
          const text = `${item.label} ${item.keywords}`.toLowerCase();
          return text.includes(normalized);
        })
        : entries;
      list.innerHTML = matched.length
        ? matched.map((item) => `
            <a href="${item.href}" class="flex items-center justify-between gap-3 rounded-lg px-3 py-2 hover:bg-white/5 transition-colors">
              <div class="flex items-center gap-3 min-w-0">
                <i data-lucide="${item.icon}" class="w-4 h-4 text-[#00d4ff]"></i>
                <span class="text-sm text-[#e4e4e7] truncate">${escapeHtml(item.label)}</span>
              </div>
              <span class="text-xs text-[#71717a]">进入</span>
            </a>
          `).join('')
        : '<p class="px-3 py-4 text-sm text-[#71717a]">没有匹配页面</p>';
      if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
      }
    };

    overlay.addEventListener('click', (event) => {
      if (!panel || !(event.target instanceof Node)) return;
      if (!panel.contains(event.target)) closeGlobalSearchModal();
    });
    closeBtn.addEventListener('click', closeGlobalSearchModal);
    input.addEventListener('input', () => renderEntries(input.value));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeGlobalSearchModal();
        return;
      }
      if (event.key !== 'Enter') return;
      const first = list.querySelector('a[href]');
      if (first) {
        window.location.href = first.getAttribute('href');
      }
    });

    globalSearchEscHandler = (event) => {
      if (event.key === 'Escape') closeGlobalSearchModal();
    };
    document.addEventListener('keydown', globalSearchEscHandler);

    renderEntries('');
    input.focus();
  }

  function focusCurrentPageSearchInput() {
    const inputs = Array.from(document.querySelectorAll('main input[type="search"], main input[placeholder*="搜索"]'))
      .filter((node) => node instanceof HTMLElement && !node.disabled && node.offsetParent !== null);
    const target = inputs[0];
    if (!target) return false;

    target.focus();
    if (typeof target.select === 'function') {
      target.select();
    }

    const previousOutline = target.style.outline;
    const previousOutlineOffset = target.style.outlineOffset;
    target.style.outline = '1px solid #00d4ff';
    target.style.outlineOffset = '1px';
    window.setTimeout(() => {
      target.style.outline = previousOutline;
      target.style.outlineOffset = previousOutlineOffset;
    }, 1200);
    return true;
  }

  function handleUnifiedSearchTrigger() {
    if (focusCurrentPageSearchInput()) {
      toast('已定位到当前页面搜索框', 'info', 1600);
      return;
    }
    openGlobalSearchModal();
  }

  function bindDashboardSearchTrigger() {
    const path = (window.location.pathname || '').toLowerCase();
    if (!(/\/index\.html$/.test(path) || path === '/' || path === '')) return;

    let trigger = document.getElementById('dashboard-search-trigger');
    if (!trigger) {
      const candidates = Array.from(document.querySelectorAll('main > header button'));
      trigger = candidates.find((button) => {
        if (!(button instanceof HTMLElement)) return false;
        return !!button.querySelector('[data-lucide="search"]');
      }) || null;
      if (trigger && !trigger.id) {
        trigger.id = 'dashboard-search-trigger';
      }
    }
    if (!trigger || trigger.dataset.searchBound === '1') return;

    trigger.dataset.searchBound = '1';
    trigger.addEventListener('click', (event) => {
      event.preventDefault();
      handleUnifiedSearchTrigger();
    });
  }

  function bindGlobalSearchShortcut() {
    if (globalSearchShortcutBound) return;
    globalSearchShortcutBound = true;

    document.addEventListener('keydown', (event) => {
      const key = String(event.key || '').toLowerCase();
      const withCommand = event.metaKey || event.ctrlKey;
      if (!withCommand || key !== 'k') return;

      event.preventDefault();
      if (globalSearchModalNode) {
        closeGlobalSearchModal();
        return;
      }
      handleUnifiedSearchTrigger();
    });
  }

  function resolveNotificationSeenStorageKey() {
    const user = getUserCache();
    const userId = Number(user?.id || 0);
    const tenantId = Number(user?.activeTenantId || 0);
    return `${NOTIFICATION_SEEN_STORAGE_PREFIX}:${userId}:${tenantId}`;
  }

  function ensureNotificationSeenState() {
    const key = resolveNotificationSeenStorageKey();
    if (key === notificationSeenStorageKey) return;
    notificationSeenStorageKey = key;
    const raw = localStorage.getItem(key);
    const parsed = safeJsonParse(raw, []);
    notificationSeenIds = new Set(Array.isArray(parsed) ? parsed.map((id) => String(id)) : []);
    notificationPollInitialized = false;
  }

  function persistNotificationSeenState() {
    if (!notificationSeenStorageKey) return;
    const ids = Array.from(notificationSeenIds).slice(-200);
    localStorage.setItem(notificationSeenStorageKey, JSON.stringify(ids));
  }

  function markNotificationIdsAsSeen(ids) {
    ensureNotificationSeenState();
    (Array.isArray(ids) ? ids : []).forEach((id) => {
      const normalized = String(id || '').trim();
      if (normalized) notificationSeenIds.add(normalized);
    });
    persistNotificationSeenState();
  }

  function mapNotificationMeta(type, level) {
    const normalizedType = String(type || '').toUpperCase();
    const normalizedLevel = String(level || '').toUpperCase();
    if (normalizedType === 'US_ANALYSIS_SUCCEEDED') return { icon: 'file-check', color: '#10b981' };
    if (normalizedType === 'US_ANALYSIS_FAILED') return { icon: 'file-warning', color: '#ef4444' };
    if (normalizedType === 'CASE_GENERATION_SUCCEEDED') return { icon: 'list-checks', color: '#00d4ff' };
    if (normalizedType === 'CASE_GENERATION_FAILED') return { icon: 'alert-triangle', color: '#ef4444' };
    if (normalizedType === 'SCRIPT_GENERATION_SUCCEEDED') return { icon: 'file-code-2', color: '#22d3ee' };
    if (normalizedType === 'SCRIPT_GENERATION_FAILED') return { icon: 'file-x-2', color: '#ef4444' };
    if (normalizedLevel === 'SUCCESS') return { icon: 'check-circle-2', color: '#10b981' };
    if (normalizedLevel === 'ERROR') return { icon: 'alert-circle', color: '#ef4444' };
    if (normalizedLevel === 'WARNING') return { icon: 'alert-triangle', color: '#f59e0b' };
    return { icon: 'bell', color: '#3b82f6' };
  }

  function normalizeNotificationItem(item) {
    const id = String(item?.id || '').trim();
    const type = String(item?.type || '').toUpperCase();
    const level = String(item?.level || '').toUpperCase();
    const meta = mapNotificationMeta(type, level);
    const read = Boolean(item?.read);
    return {
      id,
      type,
      level,
      icon: meta.icon,
      color: meta.color,
      title: item?.title || '系统消息',
      detail: item?.content || '',
      time: formatDateTime(item?.createdAt),
      createdAt: item?.createdAt || null,
      read
    };
  }

  async function fetchGlobalNotifications(force = false, options = {}) {
    const unreadOnly = Boolean(options.unreadOnly);
    const now = Date.now();
    if (!force && !unreadOnly && now - globalNotificationCache.timestamp < GLOBAL_NOTIFICATION_CACHE_MS) {
      return {
        items: globalNotificationCache.items,
        unreadCount: globalNotificationCache.unreadCount
      };
    }

    const feed = await api(`/notifications?page=0&size=${NOTIFICATION_PAGE_SIZE}&unreadOnly=${unreadOnly ? 'true' : 'false'}`);
    const page = feed?.page || {};
    const rawItems = Array.isArray(page.content) ? page.content : [];
    const items = rawItems.map((item) => normalizeNotificationItem(item)).filter((item) => item.id);
    const unreadCount = Number(feed?.unreadCount ?? items.filter((item) => !item.read).length) || 0;

    if (!unreadOnly) {
      globalNotificationCache = {
        timestamp: now,
        items,
        unreadCount
      };
    }
    return { items, unreadCount };
  }

  function updateNotificationBadges(unreadCount) {
    const count = Math.max(0, Number(unreadCount) || 0);
    const dots = Array.from(document.querySelectorAll('#app-global-notification-dot, #notification-dropdown .app-notification-dot'));
    dots.forEach((dot) => {
      if (!(dot instanceof HTMLElement)) return;
      dot.classList.toggle('hidden', count <= 0);
      dot.setAttribute('title', count > 0 ? `${count} 条未读消息` : '暂无未读消息');
    });
  }

  function normalizeNotificationId(value) {
    return String(value || '').trim();
  }

  function getCurrentNotificationIds(items = globalNotificationCache.items) {
    const source = Array.isArray(items) ? items : [];
    return source.map((item) => normalizeNotificationId(item?.id)).filter(Boolean);
  }

  function pruneSelectedNotifications(items = globalNotificationCache.items) {
    const currentIds = new Set(getCurrentNotificationIds(items));
    notificationSelectedIds = new Set(
      Array.from(notificationSelectedIds).filter((id) => currentIds.has(id))
    );
  }

  function getSelectedNotificationIds(items = globalNotificationCache.items) {
    const currentIds = getCurrentNotificationIds(items);
    return currentIds.filter((id) => notificationSelectedIds.has(id));
  }

  function syncNotificationSelectionCheckboxes() {
    const checkboxes = Array.from(document.querySelectorAll('[data-notification-select]'));
    checkboxes.forEach((checkbox) => {
      if (!(checkbox instanceof HTMLInputElement)) return;
      const id = normalizeNotificationId(checkbox.dataset.notificationSelect);
      checkbox.checked = Boolean(id && notificationSelectedIds.has(id));
    });
  }

  function syncNotificationBatchActions(items = globalNotificationCache.items) {
    const totalCount = getCurrentNotificationIds(items).length;
    const selectedCount = getSelectedNotificationIds(items).length;
    const allSelected = totalCount > 0 && selectedCount === totalCount;
    const actionMappings = [
      ['#app-global-notification-select-all', '#app-global-notification-batch-delete'],
      ['#dashboard-notification-select-all', '#dashboard-notification-batch-delete']
    ];

    actionMappings.forEach(([selectAllSelector, deleteSelector]) => {
      const selectAllButton = document.querySelector(selectAllSelector);
      const deleteButton = document.querySelector(deleteSelector);

      if (selectAllButton instanceof HTMLButtonElement) {
        selectAllButton.disabled = totalCount <= 0;
        selectAllButton.classList.toggle('opacity-40', totalCount <= 0);
        selectAllButton.classList.toggle('cursor-not-allowed', totalCount <= 0);
        selectAllButton.textContent = allSelected ? '取消全选' : '全选';
      }

      if (deleteButton instanceof HTMLButtonElement) {
        deleteButton.disabled = selectedCount <= 0;
        deleteButton.classList.toggle('opacity-40', selectedCount <= 0);
        deleteButton.classList.toggle('cursor-not-allowed', selectedCount <= 0);
        deleteButton.textContent = selectedCount > 0 ? `批量删除(${selectedCount})` : '批量删除';
      }
    });
  }

  function clearNotificationSelection(items = globalNotificationCache.items) {
    notificationSelectedIds.clear();
    syncNotificationSelectionCheckboxes();
    syncNotificationBatchActions(items);
  }

  function toggleSelectAllNotifications(items = globalNotificationCache.items) {
    const ids = getCurrentNotificationIds(items);
    if (!ids.length) {
      clearNotificationSelection(items);
      return;
    }
    const allSelected = ids.every((id) => notificationSelectedIds.has(id));
    if (allSelected) {
      ids.forEach((id) => notificationSelectedIds.delete(id));
    } else {
      ids.forEach((id) => notificationSelectedIds.add(id));
    }
    syncNotificationSelectionCheckboxes();
    syncNotificationBatchActions(items);
  }

  async function deleteSelectedNotifications(loadNotifications) {
    const selectedIds = getSelectedNotificationIds();
    if (!selectedIds.length) {
      toast('请先选择要删除的消息', 'warning', 1800);
      return;
    }
    const confirmed = await confirm({
      title: '批量删除消息',
      message: `确认删除已选中的 ${selectedIds.length} 条消息？删除后不可恢复。`,
      confirmText: '确认删除',
      tone: 'danger'
    });
    if (!confirmed) return;
    const normalizedIds = selectedIds
      .map((id) => Number(id))
      .filter((id) => Number.isFinite(id) && id > 0);
    if (!normalizedIds.length) {
      toast('选中的消息ID无效，请刷新后重试', 'error');
      return;
    }
    try {
      const result = await api('/notifications/batch-delete', {
        method: 'POST',
        body: { ids: normalizedIds }
      });
      const deletedCount = Math.max(0, Number(result?.deletedCount) || normalizedIds.length);
      markNotificationIdsAsSeen(selectedIds);
      clearNotificationSelection();
      if (typeof loadNotifications === 'function') {
        await loadNotifications(true);
      } else {
        await refreshNotificationPanels(true);
      }
      toast(`已删除 ${deletedCount} 条消息`, 'success', 1800);
    } catch (error) {
      toast(error.message || '批量删除失败', 'error');
    }
  }

  function bindNotificationListActions(node) {
    if (!node || node.dataset.notificationBound === '1') return;
    node.dataset.notificationBound = '1';
    node.addEventListener('change', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const selectInput = target.closest('[data-notification-select]');
      if (!(selectInput instanceof HTMLInputElement)) return;
      const id = normalizeNotificationId(selectInput.dataset.notificationSelect);
      if (!id) return;
      if (selectInput.checked) {
        notificationSelectedIds.add(id);
      } else {
        notificationSelectedIds.delete(id);
      }
      syncNotificationBatchActions();
    });

    node.addEventListener('click', async (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;

      const selectWrap = target.closest('[data-notification-select-wrap]');
      if (selectWrap) {
        event.stopPropagation();
        return;
      }

      const deleteButton = event.target.closest('[data-notification-delete]');
      if (deleteButton) {
        event.preventDefault();
        event.stopPropagation();
        const id = Number(deleteButton.dataset.notificationDelete);
        if (!id) return;
        try {
          const confirmed = await confirm({
            title: '删除消息',
            message: '确认删除这条消息？删除后不可恢复。',
            confirmText: '确认删除',
            tone: 'danger'
          });
          if (!confirmed) return;
          await api(`/notifications/${id}`, { method: 'DELETE' });
          notificationSelectedIds.delete(String(id));
          markNotificationIdsAsSeen([String(id)]);
          await refreshNotificationPanels(true);
          toast('消息已删除', 'success', 1600);
        } catch (error) {
          toast(error.message || '删除消息失败', 'error');
        }
        return;
      }

      const item = event.target.closest('[data-notification-id]');
      if (!item) return;
      const id = Number(item.dataset.notificationId);
      if (!id) return;
      try {
        await api(`/notifications/${id}/read`, { method: 'PATCH' });
        markNotificationIdsAsSeen([String(id)]);
        await refreshNotificationPanels(true);
      } catch (error) {
        toast(error.message || '消息状态更新失败', 'error');
      }
    });
  }

  function renderGlobalNotifications(node, items) {
    if (!node) return;
    bindNotificationListActions(node);
    node.innerHTML = Array.isArray(items) && items.length
      ? items.map((item) => `
          <div data-notification-id="${escapeHtml(item.id || '')}" class="p-3 rounded-lg ${item.read ? 'bg-white/5 hover:bg-white/10' : 'bg-[#00d4ff]/10 hover:bg-[#00d4ff]/15'} transition-colors cursor-pointer border border-white/5">
            <div class="flex items-start gap-2">
              <label data-notification-select-wrap class="mt-0.5 flex items-center justify-center">
                <input
                  type="checkbox"
                  data-notification-select="${escapeHtml(item.id || '')}"
                  ${notificationSelectedIds.has(normalizeNotificationId(item.id)) ? 'checked' : ''}
                  class="h-3.5 w-3.5 rounded border-white/30 bg-black/20"
                  style="accent-color:#00d4ff;"
                  title="选择消息"
                />
              </label>
              <i data-lucide="${item.icon}" class="w-4 h-4 mt-0.5" style="color:${item.color};"></i>
              <div class="min-w-0 flex-1">
                <div class="flex items-start justify-between gap-2">
                  <div class="flex items-center gap-2 min-w-0">
                    <p class="text-sm text-white truncate">${escapeHtml(item.title || '-')}</p>
                    ${item.read ? '' : '<span class="w-2 h-2 rounded-full bg-[#ef4444]"></span>'}
                  </div>
                  <button
                    type="button"
                    data-notification-delete="${escapeHtml(item.id || '')}"
                    class="px-2 py-0.5 text-[11px] rounded bg-[#ef4444]/20 text-[#fca5a5] hover:bg-[#ef4444]/30 shrink-0"
                    title="删除消息"
                  >删除</button>
                </div>
                ${item.detail ? `<p class="text-xs text-[#a1a1aa] mt-1">${escapeHtml(item.detail)}</p>` : ''}
                <p class="text-xs text-[#71717a] mt-1">${escapeHtml(item.time || '-')}</p>
              </div>
            </div>
          </div>
        `).join('')
      : '<p class="text-xs text-[#71717a]">暂无消息</p>';
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }

  async function refreshNotificationPanels(force = false) {
    const feed = await fetchGlobalNotifications(force, { unreadOnly: false });
    pruneSelectedNotifications(feed.items);
    updateNotificationBadges(feed.unreadCount);
    const listNodes = [
      document.getElementById('app-global-notifications-list'),
      document.getElementById('dashboard-notifications-list')
    ].filter(Boolean);
    listNodes.forEach((node) => renderGlobalNotifications(node, feed.items));
    syncNotificationSelectionCheckboxes();
    syncNotificationBatchActions(feed.items);
    return feed;
  }

  function toastNewNotifications(unreadItems) {
    ensureNotificationSeenState();
    const unread = Array.isArray(unreadItems) ? unreadItems : [];
    if (!notificationPollInitialized) {
      markNotificationIdsAsSeen(unread.map((item) => item.id));
      notificationPollInitialized = true;
      return;
    }
    const incoming = unread.filter((item) => item.id && !notificationSeenIds.has(item.id));
    if (!incoming.length) return;
    incoming.slice(0, 3).forEach((item) => {
      const detail = String(item.detail || '').trim();
      const text = detail ? `${item.title}：${detail}` : item.title;
      toast(text, item.level === 'ERROR' ? 'error' : (item.level === 'SUCCESS' ? 'success' : 'info'), 4200);
    });
    markNotificationIdsAsSeen(incoming.map((item) => item.id));
  }

  async function pollNotifications() {
    try {
      const unreadFeed = await fetchGlobalNotifications(true, { unreadOnly: true });
      updateNotificationBadges(unreadFeed.unreadCount);
      toastNewNotifications(unreadFeed.items);

      const globalPanel = document.getElementById('app-global-notifications-panel');
      const dashboardPanel = document.getElementById('notifications-panel');
      const panelVisible = Boolean(
        (globalPanel && !globalPanel.classList.contains('hidden'))
        || (dashboardPanel && !dashboardPanel.classList.contains('hidden'))
      );
      if (panelVisible) {
        await refreshNotificationPanels(true);
      }
    } catch (_error) {
      // Ignore polling errors to avoid noisy UI interruptions.
    }
  }

  function stopNotificationPolling() {
    if (notificationPollTimer) {
      window.clearInterval(notificationPollTimer);
      notificationPollTimer = null;
    }
    notificationPollInitialized = false;
  }

  function startNotificationPolling() {
    if (notificationPollTimer) return;
    void pollNotifications();
    notificationPollTimer = window.setInterval(() => {
      void pollNotifications();
    }, NOTIFICATION_POLL_INTERVAL_MS);
  }

  function isLoginPagePath(path = window.location.pathname || '') {
    return /\/login\.html$/i.test(path);
  }

  function resolveSidebarElements() {
    const sidebar = document.querySelector('body > aside');
    const main = document.querySelector('body > main');
    if (!(sidebar instanceof HTMLElement) || !(main instanceof HTMLElement)) {
      return null;
    }
    return { sidebar, main };
  }

  function resolveSidebarToggleMount(sidebar) {
    if (!(sidebar instanceof HTMLElement)) return null;
    const logoInner = sidebar.querySelector(':scope > div:first-child > div');
    if (logoInner instanceof HTMLElement) return logoInner;
    const logoRow = sidebar.querySelector(':scope > div:first-child');
    if (logoRow instanceof HTMLElement) return logoRow;
    return null;
  }

  function ensureGlobalSidebarStyle() {
    if (document.getElementById('app-global-sidebar-style')) return;
    const style = document.createElement('style');
    style.id = 'app-global-sidebar-style';
    style.textContent = `
      :root { --app-sidebar-width: ${SIDEBAR_EXPANDED_WIDTH}; }
      body.app-sidebar-collapsed { --app-sidebar-width: ${SIDEBAR_COLLAPSED_WIDTH}; }
      body[data-app-sidebar="1"] > aside {
        width: var(--app-sidebar-width) !important;
        transition: width .22s ease;
        overflow: hidden;
      }
      body[data-app-sidebar="1"] > main {
        margin-left: var(--app-sidebar-width) !important;
        transition: margin-left .22s ease;
      }
      body[data-app-sidebar="1"] > aside > div:first-child {
        overflow: visible;
      }
      body[data-app-sidebar="1"] > aside > div:first-child > div {
        width: calc(100% - .5rem);
        padding-left: .35rem;
        padding-right: .35rem;
        justify-content: center;
        transition: width .22s ease, padding .22s ease, gap .22s ease;
      }
      body[data-app-sidebar="1"] > aside > div:first-child > div > :first-child,
      body[data-app-sidebar="1"] > aside #app-global-sidebar-toggle {
        flex-shrink: 0;
      }
      body[data-app-sidebar="1"] > aside nav a > svg {
        width: 1.25rem !important;
        height: 1.25rem !important;
        min-width: 1.25rem !important;
        flex: 0 0 1.25rem !important;
      }
      body[data-app-sidebar="1"] > aside nav a > span:first-of-type,
      body[data-app-sidebar="1"] > aside > div:first-child > div > span,
      body[data-app-sidebar="1"] > aside > div:last-child span,
      body[data-app-sidebar="1"] > aside > div:last-child p,
      body[data-app-sidebar="1"] > aside .text-lg,
      body[data-app-sidebar="1"] > aside .text-sm,
      body[data-app-sidebar="1"] > aside .text-xs {
        display: inline-block;
        max-width: 14rem;
        opacity: 1;
        transform: translateX(0);
        overflow: hidden;
        white-space: nowrap;
        transition: max-width .24s ease, opacity .18s ease, transform .24s ease, margin .24s ease;
        will-change: max-width, opacity, transform;
      }
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside nav a {
        justify-content: center;
        padding-left: .75rem !important;
        padding-right: .75rem !important;
        gap: .5rem !important;
      }
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside > div:first-child > div {
        width: calc(100% - .1rem);
        padding-left: .55rem;
        padding-right: .35rem;
        gap: .35rem !important;
      }
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside > div:first-child > div > span {
        display: none !important;
      }
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside nav a > span:first-of-type,
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside > div:last-child span,
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside > div:last-child p,
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside .text-lg,
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside .text-sm,
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside .text-xs {
        opacity: 0;
        max-width: 0 !important;
        margin: 0 !important;
        overflow: hidden;
        pointer-events: none;
        white-space: nowrap;
        transform: translateX(-8px);
      }
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside nav a > span:not(:first-of-type) {
        display: none !important;
      }
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside .glass-card {
        padding: .5rem !important;
      }
      body.app-sidebar-collapsed[data-app-sidebar="1"] > aside > div:last-child {
        display: none !important;
      }
      body.app-sidebar-collapsed .studio-palette {
        left: calc(${SIDEBAR_COLLAPSED_WIDTH} + 1rem) !important;
      }
    `;
    document.head.appendChild(style);
  }

  function readSidebarCollapsedState() {
    return localStorage.getItem(SIDEBAR_COLLAPSE_STORAGE_KEY) === '1';
  }

  function writeSidebarCollapsedState(collapsed) {
    localStorage.setItem(SIDEBAR_COLLAPSE_STORAGE_KEY, collapsed ? '1' : '0');
  }

  function updateSidebarToggleButtonState(collapsed) {
    const button = document.getElementById('app-global-sidebar-toggle');
    if (!(button instanceof HTMLButtonElement)) return;
    button.setAttribute('title', collapsed ? '展开导航栏' : '收起导航栏');
    button.setAttribute('aria-label', collapsed ? '展开导航栏' : '收起导航栏');
    button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    button.classList.toggle('text-white', collapsed);
    button.classList.toggle('text-[#a1a1aa]', !collapsed);
    button.classList.toggle('rotate-90', collapsed);
  }

  function applySidebarCollapsedState(collapsed, options = {}) {
    const { persist = false } = options;
    const elements = resolveSidebarElements();
    if (!elements) return false;

    ensureGlobalSidebarStyle();
    document.body.dataset.appSidebar = '1';
    document.body.classList.toggle('app-sidebar-collapsed', collapsed);
    if (persist) {
      writeSidebarCollapsedState(collapsed);
    }
    updateSidebarToggleButtonState(collapsed);
    return true;
  }

  function ensureGlobalSidebarToggle() {
    if (isLoginPagePath()) return false;
    const elements = resolveSidebarElements();
    if (!elements) return false;

    const mount = resolveSidebarToggleMount(elements.sidebar);
    if (!(mount instanceof HTMLElement)) return false;

    // Remove page-local sidebar toggle to avoid duplicated controls.
    const legacyToggle = document.getElementById('sidebar-toggle-btn');
    if (legacyToggle) legacyToggle.remove();

    let toggleButton = document.getElementById('app-global-sidebar-toggle');
    if (!(toggleButton instanceof HTMLButtonElement)) {
      toggleButton = document.createElement('button');
      toggleButton.id = 'app-global-sidebar-toggle';
      toggleButton.type = 'button';
      toggleButton.className = 'p-1.5 rounded-lg text-[#a1a1aa] hover:text-white hover:bg-white/5 transition-colors transition-transform duration-200 shrink-0';
      // Use inline SVG to avoid repeated lucide DOM replacement loops under MutationObserver.
      toggleButton.innerHTML = [
        '<svg xmlns="http://www.w3.org/2000/svg" class="w-5 h-5" viewBox="0 0 24 24" fill="none" ',
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">',
        '<path d="M4 6h16"></path><path d="M4 12h16"></path><path d="M4 18h16"></path>',
        '</svg>'
      ].join('');
      toggleButton.addEventListener('click', () => {
        const collapsed = document.body.classList.contains('app-sidebar-collapsed');
        applySidebarCollapsedState(!collapsed, { persist: true });
      });
      mount.append(toggleButton);
    } else if (toggleButton.parentElement !== mount) {
      mount.append(toggleButton);
    }

    updateSidebarToggleButtonState(document.body.classList.contains('app-sidebar-collapsed'));
    return true;
  }

  function initializeGlobalSidebarCollapse() {
    const elements = resolveSidebarElements();
    if (!elements || isLoginPagePath()) return;
    applySidebarCollapsedState(readSidebarCollapsedState(), { persist: false });
    ensureGlobalSidebarToggle();
  }

  function resolveGlobalTopHeader() {
    return document.querySelector('main > header');
  }

  function resolveGlobalActionsContainer(header) {
    const children = Array.from(header.children).filter((node) => node.nodeType === Node.ELEMENT_NODE);
    let actionContainer = children.length > 1 ? children[1] : null;
    if (!(actionContainer instanceof HTMLElement)) {
      actionContainer = document.createElement('div');
      actionContainer.className = 'flex items-center gap-3 ml-auto';
      header.appendChild(actionContainer);
    } else {
      actionContainer.classList.add('flex', 'items-center');
      if (!actionContainer.classList.contains('gap-3')) {
        actionContainer.classList.add('gap-3');
      }
    }
    actionContainer.classList.add('justify-end', 'min-w-0');
    return actionContainer;
  }

  function bindGlobalTopActionsOutsideClick() {
    if (globalTopActionsOutsideClickBound) return;
    globalTopActionsOutsideClickBound = true;
    document.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const notificationsPanel = document.getElementById('app-global-notifications-panel');
      const userMenu = document.getElementById('app-global-user-menu');
      if (!target.closest('#app-global-notification-dropdown') && notificationsPanel) {
        notificationsPanel.classList.add('hidden');
      }
      if (!target.closest('#app-global-user-dropdown') && userMenu) {
        userMenu.classList.add('hidden');
      }
    });
  }

  function ensureGlobalTopActions() {
    const path = window.location.pathname || '';
    if (/\/login\.html$/i.test(path)) return false;

    const header = resolveGlobalTopHeader();
    if (!header) return false;
    if (header.querySelector('#app-global-top-actions')) return true;
    if (header.querySelector('#user-dropdown') || header.querySelector('#notification-dropdown')) {
      return false;
    }

    const actionContainer = resolveGlobalActionsContainer(header);

    const showSearchButton = shouldShowGlobalSearchButton();
    const searchMarkup = showSearchButton
      ? `
      <button id="app-global-search-trigger" type="button" class="p-2 text-[#a1a1aa] hover:text-white hover:bg-white/5 rounded-lg transition-colors" title="搜索">
        <i data-lucide="search" class="w-5 h-5"></i>
      </button>
      `
      : '';

    const globalActions = document.createElement('div');
    globalActions.id = 'app-global-top-actions';
    globalActions.className = 'flex items-center gap-2 pl-2 border-l border-white/10 shrink-0';
    globalActions.innerHTML = `
      ${searchMarkup}
      <div id="app-global-notification-dropdown" class="relative">
        <button id="app-global-notification-trigger" type="button" class="p-2 text-[#a1a1aa] hover:text-white hover:bg-white/5 rounded-lg transition-colors relative" title="消息中心">
          <i data-lucide="bell" class="w-5 h-5"></i>
          <span id="app-global-notification-dot" class="app-notification-dot hidden absolute top-1 right-1 w-2 h-2 bg-[#ef4444] rounded-full"></span>
        </button>
        <div id="app-global-notifications-panel" class="hidden absolute right-0 top-full mt-2 w-80 glass-card rounded-xl p-4 z-50">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-medium">消息中心</h3>
            <div class="flex items-center gap-2 flex-wrap justify-end">
              <button id="app-global-notification-mark-read" type="button" class="text-xs text-[#a1a1aa] hover:text-white hover:underline">全部已读</button>
              <button id="app-global-notification-select-all" type="button" class="text-xs text-[#a1a1aa] hover:text-white hover:underline">全选</button>
              <button id="app-global-notification-batch-delete" type="button" class="text-xs text-[#fca5a5] hover:text-[#fecaca] hover:underline disabled:opacity-40 disabled:cursor-not-allowed">批量删除</button>
              <button id="app-global-notification-refresh" type="button" class="text-xs text-[#00d4ff] hover:underline">刷新</button>
            </div>
          </div>
          <div id="app-global-notifications-list" class="space-y-2">
            <p class="text-xs text-[#71717a]">加载中...</p>
          </div>
        </div>
      </div>
      <div id="app-global-user-dropdown" class="relative">
        <button id="app-global-user-trigger" type="button" class="flex items-center gap-2 p-2 rounded-lg hover:bg-white/5 transition-colors">
          <div class="w-8 h-8 rounded-full bg-gradient-to-br from-[#00d4ff] to-[#7c3aed] flex items-center justify-center text-sm font-medium">
            <span>AU</span>
          </div>
          <div class="text-left hidden md:block">
            <p class="text-sm font-medium">Admin</p>
            <p class="text-xs text-[#71717a]">管理员</p>
          </div>
          <i data-lucide="chevron-down" class="w-4 h-4 text-[#71717a]"></i>
        </button>
        <div id="app-global-user-menu" class="hidden absolute right-0 top-full mt-2 w-56 glass-card rounded-xl p-2 z-50">
          <a href="#profile" data-action="profile-settings" class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/5 transition-colors text-sm">
            <i data-lucide="user" class="w-4 h-4"></i>
            <span>个人设置</span>
          </a>
          <a href="${resolveAppPagePath('settings')}" class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/5 transition-colors text-sm">
            <i data-lucide="settings" class="w-4 h-4"></i>
            <span>系统设置</span>
          </a>
          <div class="my-1 h-px bg-white/10"></div>
          <a href="#" data-action="logout" class="flex items-center gap-3 px-3 py-2 rounded-lg text-[#ef4444] hover:bg-[#ef4444]/10 transition-colors text-sm">
            <i data-lucide="log-out" class="w-4 h-4"></i>
            <span>退出登录</span>
          </a>
        </div>
      </div>
    `;
    actionContainer.appendChild(globalActions);

    const searchTrigger = globalActions.querySelector('#app-global-search-trigger');
    const notificationTrigger = globalActions.querySelector('#app-global-notification-trigger');
    const notificationsPanel = globalActions.querySelector('#app-global-notifications-panel');
    const notificationsList = globalActions.querySelector('#app-global-notifications-list');
    const notificationsRefresh = globalActions.querySelector('#app-global-notification-refresh');
    const notificationsMarkRead = globalActions.querySelector('#app-global-notification-mark-read');
    const notificationsSelectAll = globalActions.querySelector('#app-global-notification-select-all');
    const notificationsBatchDelete = globalActions.querySelector('#app-global-notification-batch-delete');
    const userTrigger = globalActions.querySelector('#app-global-user-trigger');
    const userMenu = globalActions.querySelector('#app-global-user-menu');

    const loadNotifications = async (force = false) => {
      if (!notificationsList) return;
      notificationsList.innerHTML = '<p class="text-xs text-[#71717a]">加载中...</p>';
      try {
        await refreshNotificationPanels(force);
      } catch (error) {
        notificationsList.innerHTML = `<p class="text-xs text-[#ef4444]">${escapeHtml(error.message || '消息加载失败')}</p>`;
      }
    };

    searchTrigger?.addEventListener('click', () => {
      handleUnifiedSearchTrigger();
    });

    notificationTrigger?.addEventListener('click', async (event) => {
      event.stopPropagation();
      closePossibleUserMenus();
      if (!notificationsPanel) return;
      notificationsPanel.classList.remove('hidden');
      await loadNotifications(false);
    });

    notificationsRefresh?.addEventListener('click', async (event) => {
      event.stopPropagation();
      await loadNotifications(true);
    });

    notificationsSelectAll?.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleSelectAllNotifications();
    });

    notificationsBatchDelete?.addEventListener('click', async (event) => {
      event.stopPropagation();
      await deleteSelectedNotifications(loadNotifications);
    });

    notificationsMarkRead?.addEventListener('click', async (event) => {
      event.stopPropagation();
      try {
        await api('/notifications/read-all', { method: 'PATCH' });
        toast('已全部标记为已读', 'success', 1800);
        await loadNotifications(true);
      } catch (error) {
        toast(error.message || '标记已读失败', 'error');
      }
    });

    userTrigger?.addEventListener('click', (event) => {
      event.stopPropagation();
      if (!userMenu) return;
      const shouldShow = userMenu.classList.contains('hidden');
      closePossibleUserMenus();
      if (shouldShow) {
        userMenu.classList.remove('hidden');
      }
    });
    bindGlobalTopActionsOutsideClick();

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }

    const cachedUser = getUserCache();
    if (cachedUser) {
      syncUserDisplay(cachedUser);
    }
    void refreshNotificationPanels(true).catch(() => {});
    return true;
  }

  function bindDashboardNotifications() {
    const dropdown = document.getElementById('notification-dropdown');
    const panel = document.getElementById('notifications-panel');
    if (!dropdown || !panel) return false;

    const trigger = dropdown.querySelector('button');
    if (!trigger) return false;

    const dot = trigger.querySelector('span');
    if (dot) {
      dot.classList.add('app-notification-dot');
      dot.classList.add('hidden');
    }

    if (panel.dataset.dashboardNotificationReady !== '1') {
      panel.dataset.dashboardNotificationReady = '1';
      panel.innerHTML = `
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-medium">消息中心</h3>
          <div class="flex items-center gap-2 flex-wrap justify-end">
            <button id="dashboard-notification-mark-read" type="button" class="text-xs text-[#a1a1aa] hover:text-white hover:underline">全部已读</button>
            <button id="dashboard-notification-select-all" type="button" class="text-xs text-[#a1a1aa] hover:text-white hover:underline">全选</button>
            <button id="dashboard-notification-batch-delete" type="button" class="text-xs text-[#fca5a5] hover:text-[#fecaca] hover:underline disabled:opacity-40 disabled:cursor-not-allowed">批量删除</button>
            <button id="dashboard-notification-refresh" type="button" class="text-xs text-[#00d4ff] hover:underline">刷新</button>
          </div>
        </div>
        <div id="dashboard-notifications-list" class="space-y-2">
          <p class="text-xs text-[#71717a]">加载中...</p>
        </div>
      `;
    }

    const listNode = panel.querySelector('#dashboard-notifications-list');
    const refreshBtn = panel.querySelector('#dashboard-notification-refresh');
    const markReadBtn = panel.querySelector('#dashboard-notification-mark-read');
    const selectAllBtn = panel.querySelector('#dashboard-notification-select-all');
    const batchDeleteBtn = panel.querySelector('#dashboard-notification-batch-delete');

    const loadDashboardNotifications = async (force = false) => {
      if (listNode) {
        listNode.innerHTML = '<p class="text-xs text-[#71717a]">加载中...</p>';
      }
      try {
        await refreshNotificationPanels(force);
      } catch (error) {
        if (listNode) {
          listNode.innerHTML = `<p class="text-xs text-[#ef4444]">${escapeHtml(error.message || '消息加载失败')}</p>`;
        }
      }
    };

    if (refreshBtn && refreshBtn.dataset.notificationBound !== '1') {
      refreshBtn.dataset.notificationBound = '1';
      refreshBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        await loadDashboardNotifications(true);
      });
    }

    if (markReadBtn && markReadBtn.dataset.notificationBound !== '1') {
      markReadBtn.dataset.notificationBound = '1';
      markReadBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        try {
          await api('/notifications/read-all', { method: 'PATCH' });
          toast('已全部标记为已读', 'success', 1800);
          await loadDashboardNotifications(true);
        } catch (error) {
          toast(error.message || '标记已读失败', 'error');
        }
      });
    }

    if (selectAllBtn && selectAllBtn.dataset.notificationBound !== '1') {
      selectAllBtn.dataset.notificationBound = '1';
      selectAllBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleSelectAllNotifications();
      });
    }

    if (batchDeleteBtn && batchDeleteBtn.dataset.notificationBound !== '1') {
      batchDeleteBtn.dataset.notificationBound = '1';
      batchDeleteBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        await deleteSelectedNotifications(loadDashboardNotifications);
      });
    }

    window.toggleNotifications = async () => {
      const shouldOpen = panel.classList.contains('hidden');
      closePossibleUserMenus();
      if (!shouldOpen) {
        panel.classList.add('hidden');
        return;
      }
      panel.classList.remove('hidden');
      await loadDashboardNotifications(false);
    };

    return true;
  }

  function clearGlobalTopActionsRetryTimers() {
    globalTopActionsRetryTimers.forEach((timer) => window.clearTimeout(timer));
    globalTopActionsRetryTimers = [];
  }

  function scheduleGlobalTopActionsEnsure() {
    clearGlobalTopActionsRetryTimers();
    const retries = [0, 160, 480, 1200];
    retries.forEach((delay) => {
      const timer = window.setTimeout(() => {
        ensureGlobalSidebarToggle();
        ensureGlobalTopActions();
        bindDashboardNotifications();
      }, delay);
      globalTopActionsRetryTimers.push(timer);
    });
  }

  function bindGlobalTopActionsObserver() {
    if (globalTopActionsObserver || typeof MutationObserver !== 'function') return;
    const main = document.querySelector('main');
    if (!main) return;
    globalTopActionsObserver = new MutationObserver(() => {
      if (globalTopActionsObserverFramePending) return;
      globalTopActionsObserverFramePending = true;
      const run = () => {
        globalTopActionsObserverFramePending = false;
        const header = resolveGlobalTopHeader();
        if (!header) return;
        ensureGlobalSidebarToggle();
        if (!header.querySelector('#app-global-top-actions')) {
          ensureGlobalTopActions();
        }
      };
      if (typeof window.requestAnimationFrame === 'function') {
        window.requestAnimationFrame(run);
      } else {
        window.setTimeout(run, 0);
      }
    });
    globalTopActionsObserver.observe(main, { childList: true, subtree: true });
  }

  function showJsonModal(title, payload) {
    const existing = document.getElementById('app-json-modal');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'app-json-modal';
    overlay.style.cssText = [
      'position: fixed',
      'inset: 0',
      'background: rgba(0,0,0,0.78)',
      'backdrop-filter: blur(4px)',
      'display: flex',
      'align-items: center',
      'justify-content: center',
      'padding: 16px',
      'z-index: 9998'
    ].join(';');

    const modal = document.createElement('div');
    modal.style.cssText = [
      'width: min(960px, 100%)',
      'max-height: 86vh',
      'overflow: auto',
      'border-radius: 12px',
      'background: #10131a',
      'border: 1px solid rgba(255,255,255,0.16)',
      'padding: 14px'
    ].join(';');

    modal.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;">
        <h3 style="margin:0;font-size:16px;color:#fff;">${escapeHtml(title)}</h3>
        <button id="app-json-close" style="border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.05);color:#fff;border-radius:8px;padding:6px 10px;cursor:pointer;">关闭</button>
      </div>
      <pre style="margin:0;white-space:pre-wrap;word-break:break-word;color:#d1d5db;font-size:12px;line-height:1.6;">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    modal.querySelector('#app-json-close').addEventListener('click', close);
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) close();
    });
  }

  function normalizeTimeZone(value) {
    const candidate = String(value || '').trim();
    if (!candidate) return DEFAULT_TIMEZONE;
    try {
      Intl.DateTimeFormat('en-US', { timeZone: candidate }).format(new Date());
      return candidate;
    } catch (_error) {
      return DEFAULT_TIMEZONE;
    }
  }

  function resolveFormatterForTimezone(timezone) {
    const normalizedTimezone = normalizeTimeZone(timezone);
    const cacheKey = `${normalizedTimezone}|zh-CN`;
    if (!DATE_TIME_FORMATTER_CACHE.has(cacheKey)) {
      DATE_TIME_FORMATTER_CACHE.set(
        cacheKey,
        new Intl.DateTimeFormat('zh-CN', {
          timeZone: normalizedTimezone,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false
        })
      );
    }
    return DATE_TIME_FORMATTER_CACHE.get(cacheKey);
  }

  function parseDateTimeValue(value) {
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) return new Date(value.getTime());
    if (typeof value === 'number') return new Date(value);
    if (typeof value === 'string') {
      const normalized = value.trim();
      if (!normalized) return null;
      const hasTimezone = /(?:[zZ]|[+-]\d{2}:\d{2})$/.test(normalized);
      const isIsoLike = /^\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?)?$/.test(normalized);
      const candidate = isIsoLike && !hasTimezone
        ? normalized.replace(' ', 'T') + 'Z'
        : normalized;
      return new Date(candidate);
    }
    return new Date(value);
  }

  function formatDateTime(value) {
    const date = parseDateTimeValue(value);
    if (!date || Number.isNaN(date.getTime())) return '-';
    const settings = getSettings();
    const formatter = resolveFormatterForTimezone(settings.timezone);
    const parts = formatter.formatToParts(date);
    const partMap = {};
    parts.forEach((part) => {
      if (part.type !== 'literal') partMap[part.type] = part.value;
    });
    const y = partMap.year || '0000';
    const m = partMap.month || '00';
    const d = partMap.day || '00';
    const hh = partMap.hour || '00';
    const mm = partMap.minute || '00';
    const ss = partMap.second || '00';
    return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
  }

  function formatDurationMs(ms) {
    if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '-';
    const total = Math.max(0, Math.floor(Number(ms) / 1000));
    const min = Math.floor(total / 60);
    const sec = total % 60;
    return `${min}m ${String(sec).padStart(2, '0')}s`;
  }

  function downloadJson(filename, payload) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function closeAuthModal() {
    const modal = document.getElementById('app-auth-modal');
    if (modal) modal.remove();
  }

  function getCurrentReturnPath() {
    return `${window.location.pathname}${window.location.search}${window.location.hash}`;
  }

  function resolveLoginPath(options = {}) {
    const { includeReturn = true } = options;
    const path = window.location.pathname || '/';
    const isInPages = /\/pages\//.test(path);
    const base = isInPages ? './login.html' : './pages/login.html';
    if (!includeReturn) return base;

    const current = getCurrentReturnPath();
    if (/\/pages\/login\.html$/.test(path)) return base;
    const separator = base.includes('?') ? '&' : '?';
    return `${base}${separator}redirect=${encodeURIComponent(current)}`;
  }

  function buildAuthModal() {
    const wrapper = document.createElement('div');
    wrapper.id = 'app-auth-modal';
    wrapper.style.cssText = [
      'position: fixed',
      'inset: 0',
      'display: flex',
      'align-items: center',
      'justify-content: center',
      'background: rgba(0,0,0,0.75)',
      'backdrop-filter: blur(4px)',
      'z-index: 10000',
      'padding: 14px'
    ].join(';');

    wrapper.innerHTML = `
      <div style="width:min(420px,100%);background:#111722;border:1px solid rgba(255,255,255,0.14);border-radius:14px;padding:18px;color:#fff;">
        <h3 style="margin:0 0 6px;font-size:20px;">登录 AutoTest</h3>
        <p style="margin:0 0 14px;color:#9ca3af;font-size:13px;">需要登录后才能访问当前功能</p>
        <form id="app-auth-form" style="display:grid;gap:10px;">
          <label style="display:grid;gap:5px;font-size:13px;">
            <span style="color:#9ca3af;">用户名</span>
            <input id="app-auth-username" type="text" value="admin" required style="padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.18);background:#0b1320;color:#fff;" />
          </label>
          <label style="display:grid;gap:5px;font-size:13px;">
            <span style="color:#9ca3af;">密码</span>
            <input id="app-auth-password" type="password" value="admin123" required style="padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.18);background:#0b1320;color:#fff;" />
          </label>
          <p id="app-auth-error" style="min-height:18px;margin:0;color:#ef4444;font-size:12px;"></p>
          <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button type="button" id="app-auth-goto-login" style="padding:8px 12px;border-radius:8px;border:1px solid rgba(0,212,255,0.35);background:rgba(0,212,255,0.08);color:#00d4ff;cursor:pointer;">登录页</button>
            <button type="button" id="app-auth-cancel" style="padding:8px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.05);color:#fff;cursor:pointer;">取消</button>
            <button type="submit" style="padding:8px 12px;border-radius:8px;border:0;background:linear-gradient(135deg,#00d4ff,#7c3aed);color:#fff;font-weight:600;cursor:pointer;">登录</button>
          </div>
        </form>
      </div>
    `;

    return wrapper;
  }

  async function login(username, password) {
    const data = await api('/auth/login', {
      method: 'POST',
      auth: false,
      body: { username, password }
    });

    setAuth(data);
    setUserCache(data.user);
    toast(`登录成功: ${data.user?.username || username}`, 'success');
    return data.user;
  }

  function openLoginModal() {
    if (authModalPromise) return authModalPromise;

    const modal = buildAuthModal();
    document.body.appendChild(modal);

    const form = modal.querySelector('#app-auth-form');
    const errorNode = modal.querySelector('#app-auth-error');
    const cancelBtn = modal.querySelector('#app-auth-cancel');
    const gotoLoginBtn = modal.querySelector('#app-auth-goto-login');

    authModalPromise = new Promise((resolve, reject) => {
      authModalResolver = resolve;
      authModalRejecter = reject;
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      errorNode.textContent = '';
      const username = modal.querySelector('#app-auth-username').value.trim();
      const password = modal.querySelector('#app-auth-password').value;

      try {
        const user = await login(username, password);
        closeAuthModal();
        const resolver = authModalResolver;
        authModalPromise = null;
        authModalResolver = null;
        authModalRejecter = null;
        resolver(user);
      } catch (error) {
        errorNode.textContent = error.message || '登录失败';
      }
    });

    cancelBtn.addEventListener('click', () => {
      closeAuthModal();
      const rejecter = authModalRejecter;
      authModalPromise = null;
      authModalResolver = null;
      authModalRejecter = null;
      rejecter(new Error('用户取消登录'));
    });

    if (gotoLoginBtn) {
      gotoLoginBtn.addEventListener('click', () => {
        window.location.href = resolveLoginPath({ includeReturn: true });
      });
    }

    return authModalPromise;
  }

  async function ensureAuth(options = {}) {
    const { silent = false } = options;
    const token = getAccessToken();

    if (!token) {
      if (silent) return null;
      return openLoginModal();
    }

    try {
      const user = await api('/auth/me');
      setUserCache(user);
      return user;
    } catch (_error) {
      clearAuth();
      if (silent) return null;
      return openLoginModal();
    }
  }

  async function hydrateUser() {
    try {
      return await ensureAuth({ silent: true });
    } catch (_error) {
      return null;
    }
  }

  function logout(options = {}) {
    const { reload = true, redirect = true } = options;
    stopNotificationPolling();
    clearAuth();
    toast('已退出登录', 'info');
    if (redirect !== false) {
      window.setTimeout(() => {
        window.location.href = resolveLoginPath({ includeReturn: false });
      }, 120);
      return;
    }
    if (reload !== false) {
      window.setTimeout(() => window.location.reload(), 120);
    }
  }

  function closeProfileSettingsModal() {
    if (!profileModalState) return;
    const { overlay, onKeydown, originalOverflow } = profileModalState;
    document.removeEventListener('keydown', onKeydown);
    if (overlay && overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
    document.body.style.overflow = originalOverflow || '';
    profileModalState = null;
  }

  function renderResourceList(title, items, itemRenderer, emptyMessage) {
    const total = Array.isArray(items) ? items.length : 0;
    return `
      <div style="border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:12px;background:rgba(255,255,255,0.03);">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;">
          <h4 style="margin:0;font-size:14px;color:#fff;">${escapeHtml(title)}</h4>
          <span style="font-size:11px;color:#a1a1aa;">${total} 条</span>
        </div>
        ${total
    ? `<ul style="list-style:none;padding:0;margin:0;display:grid;gap:8px;">${items.map(itemRenderer).join('')}</ul>`
    : `<p style="margin:0;color:#71717a;font-size:12px;">${escapeHtml(emptyMessage)}</p>`}
      </div>
    `;
  }

  async function fetchPersonalResources(user) {
    const userId = Number(user?.id || 0);
    const username = String(user?.username || '').toLowerCase();
    const failed = [];

    const [storyRes, caseRes, scriptRes, execRes] = await Promise.allSettled([
      api('/user-stories?page=0&size=100'),
      api('/test-cases?page=0&size=100'),
      api('/test-scripts?page=0&size=100'),
      api('/executions?page=0&size=100')
    ]);

    const extract = (result, name) => {
      if (result.status !== 'fulfilled') {
        failed.push(name);
        return [];
      }
      return unwrapPageItems(result.value);
    };

    const storiesAll = sortByLatest(
      extract(storyRes, 'US需求').filter((item) => {
        const ownerId = Number(item?.createdBy?.id || 0);
        const ownerName = String(item?.createdBy?.username || '').toLowerCase();
        return (userId && ownerId === userId) || (!!username && ownerName === username);
      })
    );

    const casesAll = sortByLatest(
      extract(caseRes, '测试用例').filter((item) => {
        const ownerId = Number(item?.createdBy?.id || 0);
        const ownerName = String(item?.createdBy?.username || '').toLowerCase();
        return (userId && ownerId === userId) || (!!username && ownerName === username);
      })
    );

    const scriptsAll = sortByLatest(
      extract(scriptRes, '测试脚本').filter((item) => {
        const caseOwnerId = Number(item?.testCase?.createdBy?.id || 0);
        const caseOwnerName = String(item?.testCase?.createdBy?.username || '').toLowerCase();
        return (userId && caseOwnerId === userId) || (!!username && caseOwnerName === username);
      })
    );

    const executionsAll = sortByLatest(
      extract(execRes, '执行记录').filter((item) => {
        const owner = String(item?.executedBy || '').toLowerCase();
        return !!username && owner === username;
      })
    );

    return {
      failed,
      totals: {
        stories: storiesAll.length,
        cases: casesAll.length,
        scripts: scriptsAll.length,
        executions: executionsAll.length
      },
      stories: storiesAll.slice(0, 5),
      cases: casesAll.slice(0, 5),
      scripts: scriptsAll.slice(0, 5),
      executions: executionsAll.slice(0, 5)
    };
  }

  async function openProfileSettingsModal() {
    const user = await ensureAuth();
    if (!user) return null;
    closeProfileSettingsModal();

    const cachedUser = getUserCache() || user;
    let selectedAvatar = String(cachedUser.avatar || '').trim();
    const galleryByKey = PROFILE_GALLERY_AVATARS.reduce((acc, item) => {
      acc[item.key] = item.value;
      return acc;
    }, {});

    const galleryButtonsHtml = PROFILE_GALLERY_AVATARS.map((item) => `
      <button
        type="button"
        data-avatar-gallery="${item.key}"
        title="${escapeHtml(item.label)}"
        style="width:52px;height:52px;border-radius:12px;border:1px solid rgba(255,255,255,0.1);background-color:rgba(255,255,255,0.05);background-image:url('${item.value}');background-size:cover;background-position:center;cursor:pointer;"
      ></button>
    `).join('');

    const emojiButtonsHtml = PROFILE_EMOJI_AVATARS.map((emoji) => `
      <button
        type="button"
        data-avatar-emoji="${emoji}"
        title="${emoji}"
        style="width:44px;height:44px;border-radius:12px;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.05);color:#fff;font-size:24px;line-height:1;cursor:pointer;"
      >${emoji}</button>
    `).join('');

    const overlay = document.createElement('div');
    overlay.id = 'app-profile-settings-modal';
    overlay.style.cssText = [
      'position:fixed',
      'inset:0',
      'display:flex',
      'align-items:center',
      'justify-content:center',
      'padding:16px',
      'background:rgba(0,0,0,0.75)',
      'backdrop-filter:blur(4px)',
      'z-index:10001'
    ].join(';');

    overlay.innerHTML = `
      <div style="width:min(980px,100%);max-height:90vh;overflow:hidden;border-radius:16px;background:rgba(15,18,26,0.96);border:1px solid rgba(255,255,255,0.14);box-shadow:0 18px 48px rgba(0,0,0,0.45);display:flex;flex-direction:column;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:16px 18px;border-bottom:1px solid rgba(255,255,255,0.08);">
          <div>
            <h3 style="margin:0;font-size:20px;color:#fff;">个人设置</h3>
            <p style="margin:4px 0 0;color:#9ca3af;font-size:12px;">个人资料与个人资源统一管理，不影响系统配置。</p>
          </div>
          <button id="app-profile-close" type="button" style="border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.05);color:#fff;border-radius:10px;padding:8px 12px;cursor:pointer;">关闭</button>
        </div>
        <div style="display:flex;gap:8px;padding:0 18px;border-bottom:1px solid rgba(255,255,255,0.06);">
          <button id="app-profile-tab-profile" type="button" data-tab="profile" style="padding:12px 4px;font-size:14px;color:#00d4ff;background:none;border:0;border-bottom:2px solid #00d4ff;cursor:pointer;">个人资料</button>
          <button id="app-profile-tab-assets" type="button" data-tab="assets" style="padding:12px 4px;font-size:14px;color:#a1a1aa;background:none;border:0;border-bottom:2px solid transparent;cursor:pointer;">个人资源</button>
          <button id="app-profile-tab-tenant" type="button" data-tab="tenant" style="padding:12px 4px;font-size:14px;color:#a1a1aa;background:none;border:0;border-bottom:2px solid transparent;cursor:pointer;">租户设置</button>
        </div>
        <div style="padding:16px 18px;overflow:auto;">
          <section id="app-profile-panel-profile">
            <div style="display:grid;grid-template-columns:minmax(220px,260px) minmax(0,1fr);gap:18px;">
              <div style="display:grid;gap:10px;align-content:start;">
                <div id="app-profile-avatar-preview" style="width:132px;height:132px;border-radius:18px;display:flex;align-items:center;justify-content:center;font-size:38px;font-weight:700;color:#fff;border:1px solid rgba(255,255,255,0.12);"></div>
                <div style="font-size:12px;color:#a1a1aa;">
                  <p id="app-profile-display-name" style="margin:0;color:#fff;font-size:14px;font-weight:600;">${escapeHtml(cachedUser.fullName || cachedUser.username || '未设置姓名')}</p>
                  <p style="margin:4px 0 0;">支持默认图库、动物 Emoji 或本地图片上传。</p>
                </div>
                <button id="app-profile-avatar-clear" type="button" style="width:max-content;padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.16);background:rgba(255,255,255,0.05);color:#fff;cursor:pointer;font-size:12px;">恢复默认头像</button>
              </div>
              <div style="display:grid;gap:14px;align-content:start;">
                <div>
                  <label style="display:block;color:#a1a1aa;font-size:12px;margin-bottom:6px;">姓名</label>
                  <input id="app-profile-fullname" type="text" value="${escapeHtml(cachedUser.fullName || cachedUser.username || '')}" style="width:100%;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,0.14);background:rgba(255,255,255,0.05);color:#fff;font-size:14px;" />
                </div>
                <div>
                  <p style="margin:0 0 6px;color:#a1a1aa;font-size:12px;">默认图库头像</p>
                  <div style="display:flex;flex-wrap:wrap;gap:8px;">${galleryButtonsHtml}</div>
                </div>
                <div>
                  <p style="margin:0 0 6px;color:#a1a1aa;font-size:12px;">常用动物 Emoji</p>
                  <div style="display:flex;flex-wrap:wrap;gap:8px;">${emojiButtonsHtml}</div>
                </div>
                <div style="display:flex;align-items:center;gap:10px;">
                  <label for="app-profile-avatar-upload" style="padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.16);background:rgba(255,255,255,0.05);color:#fff;font-size:12px;cursor:pointer;">上传头像</label>
                  <input id="app-profile-avatar-upload" type="file" accept="image/*" style="display:none;" />
                  <span style="font-size:12px;color:#71717a;">建议小于 5MB</span>
                </div>
                <div style="display:flex;justify-content:flex-end;">
                  <button id="app-profile-save" type="button" style="padding:9px 14px;border:0;border-radius:10px;background:linear-gradient(135deg,#00d4ff,#7c3aed);color:#fff;font-weight:600;cursor:pointer;">保存个人资料</button>
                </div>
              </div>
            </div>
          </section>
          <section id="app-profile-panel-assets" style="display:none;">
            <div id="app-profile-resources-content" style="display:grid;gap:12px;color:#a1a1aa;font-size:13px;">加载个人资源中...</div>
          </section>
          <section id="app-profile-panel-tenant" style="display:none;">
            <div id="app-profile-tenant-content" style="display:grid;gap:12px;color:#a1a1aa;font-size:13px;">加载租户信息中...</div>
          </section>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closePossibleUserMenus();
    syncUserDisplay(cachedUser);

    const onKeydown = (event) => {
      if (event.key === 'Escape') closeProfileSettingsModal();
    };
    document.addEventListener('keydown', onKeydown);
    profileModalState = { overlay, onKeydown, originalOverflow };

    const closeButton = overlay.querySelector('#app-profile-close');
    const profileTabButton = overlay.querySelector('#app-profile-tab-profile');
    const assetTabButton = overlay.querySelector('#app-profile-tab-assets');
    const tenantTabButton = overlay.querySelector('#app-profile-tab-tenant');
    const profilePanel = overlay.querySelector('#app-profile-panel-profile');
    const assetPanel = overlay.querySelector('#app-profile-panel-assets');
    const tenantPanel = overlay.querySelector('#app-profile-panel-tenant');
    const resourcesContainer = overlay.querySelector('#app-profile-resources-content');
    const tenantContainer = overlay.querySelector('#app-profile-tenant-content');
    const avatarPreview = overlay.querySelector('#app-profile-avatar-preview');
    const displayNameNode = overlay.querySelector('#app-profile-display-name');
    const fullNameInput = overlay.querySelector('#app-profile-fullname');
    const saveButton = overlay.querySelector('#app-profile-save');

    let resourcesLoaded = false;
    let tenantLoaded = false;

    function setTab(tabKey) {
      const activeTab = tabKey === 'assets' || tabKey === 'tenant' ? tabKey : 'profile';
      profilePanel.style.display = activeTab === 'profile' ? '' : 'none';
      assetPanel.style.display = activeTab === 'assets' ? '' : 'none';
      tenantPanel.style.display = activeTab === 'tenant' ? '' : 'none';

      profileTabButton.style.color = activeTab === 'profile' ? '#00d4ff' : '#a1a1aa';
      profileTabButton.style.borderBottomColor = activeTab === 'profile' ? '#00d4ff' : 'transparent';
      assetTabButton.style.color = activeTab === 'assets' ? '#00d4ff' : '#a1a1aa';
      assetTabButton.style.borderBottomColor = activeTab === 'assets' ? '#00d4ff' : 'transparent';
      tenantTabButton.style.color = activeTab === 'tenant' ? '#00d4ff' : '#a1a1aa';
      tenantTabButton.style.borderBottomColor = activeTab === 'tenant' ? '#00d4ff' : 'transparent';

      if (activeTab === 'assets' && !resourcesLoaded) {
        void loadResources();
      }
      if (activeTab === 'tenant' && !tenantLoaded) {
        void loadTenantContext();
      }
    }

    function refreshAvatarSelectionUI() {
      const galleryButtons = Array.from(overlay.querySelectorAll('button[data-avatar-gallery]'));
      galleryButtons.forEach((button) => {
        const value = galleryByKey[button.dataset.avatarGallery] || '';
        const active = selectedAvatar && selectedAvatar === value;
        button.style.borderColor = active ? '#00d4ff' : 'rgba(255,255,255,0.1)';
        button.style.backgroundColor = active ? 'rgba(0,212,255,0.14)' : 'rgba(255,255,255,0.05)';
        button.style.boxShadow = active ? '0 0 0 1px rgba(0,212,255,0.45)' : 'none';
      });

      const emojiButtons = Array.from(overlay.querySelectorAll('button[data-avatar-emoji]'));
      emojiButtons.forEach((button) => {
        const value = button.dataset.avatarEmoji || '';
        const active = selectedAvatar && selectedAvatar === value;
        button.style.borderColor = active ? '#00d4ff' : 'rgba(255,255,255,0.1)';
        button.style.backgroundColor = active ? 'rgba(0,212,255,0.14)' : 'rgba(255,255,255,0.05)';
        button.style.boxShadow = active ? '0 0 0 1px rgba(0,212,255,0.45)' : 'none';
      });
    }

    function refreshProfilePreview() {
      const currentName = fullNameInput.value.trim() || cachedUser.username || 'User';
      displayNameNode.textContent = fullNameInput.value.trim() || '未设置姓名';
      applyAvatarNode(avatarPreview, selectedAvatar, buildInitials(currentName));
    }

    async function loadResources() {
      resourcesContainer.innerHTML = '加载个人资源中...';
      try {
        const payload = await fetchPersonalResources(getUserCache() || cachedUser);
        resourcesLoaded = true;

        const warningText = payload.failed.length
          ? `<p style="margin:0;color:#f59e0b;font-size:12px;">部分资源加载失败：${escapeHtml(payload.failed.join('、'))}</p>`
          : '';

        resourcesContainer.innerHTML = `
          ${warningText}
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;">
            <div style="padding:10px;border-radius:10px;background:rgba(0,212,255,0.12);border:1px solid rgba(0,212,255,0.28);">
              <p style="margin:0;color:#a1a1aa;font-size:12px;">我的 US</p>
              <p style="margin:4px 0 0;color:#fff;font-size:20px;font-weight:700;">${payload.totals.stories}</p>
            </div>
            <div style="padding:10px;border-radius:10px;background:rgba(59,130,246,0.12);border:1px solid rgba(59,130,246,0.28);">
              <p style="margin:0;color:#a1a1aa;font-size:12px;">我的用例</p>
              <p style="margin:4px 0 0;color:#fff;font-size:20px;font-weight:700;">${payload.totals.cases}</p>
            </div>
            <div style="padding:10px;border-radius:10px;background:rgba(124,58,237,0.12);border:1px solid rgba(124,58,237,0.28);">
              <p style="margin:0;color:#a1a1aa;font-size:12px;">我的脚本</p>
              <p style="margin:4px 0 0;color:#fff;font-size:20px;font-weight:700;">${payload.totals.scripts}</p>
            </div>
            <div style="padding:10px;border-radius:10px;background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.28);">
              <p style="margin:0;color:#a1a1aa;font-size:12px;">我的执行</p>
              <p style="margin:4px 0 0;color:#fff;font-size:20px;font-weight:700;">${payload.totals.executions}</p>
            </div>
          </div>
          <div style="display:grid;gap:10px;">
            ${renderResourceList(
    '我创建的 US',
    payload.stories,
    (item) => `<li style="display:flex;justify-content:space-between;gap:10px;font-size:12px;color:#d4d4d8;"><span>${escapeHtml(`${item.usNumber || '-'} · ${item.title || ''}`)}</span><span style="color:#71717a;">${escapeHtml(formatDateTime(item.createdAt))}</span></li>`,
    '暂无我创建的 US 记录'
  )}
            ${renderResourceList(
    '我创建的测试用例',
    payload.cases,
    (item) => `<li style="display:flex;justify-content:space-between;gap:10px;font-size:12px;color:#d4d4d8;"><span>${escapeHtml(`${item.caseNumber || '-'} · ${item.title || ''}`)}</span><span style="color:#71717a;">${escapeHtml(formatDateTime(item.createdAt))}</span></li>`,
    '暂无我创建的测试用例'
  )}
            ${renderResourceList(
    '我创建的测试脚本',
    payload.scripts,
    (item) => `<li style="display:flex;justify-content:space-between;gap:10px;font-size:12px;color:#d4d4d8;"><span>${escapeHtml(`${item.name || '-'} · ${item.scriptType || '-'}`)}</span><span style="color:#71717a;">${escapeHtml(formatDateTime(item.createdAt))}</span></li>`,
    '暂无我创建的测试脚本'
  )}
            ${renderResourceList(
    '我的执行记录',
    payload.executions,
    (item) => `<li style="display:flex;justify-content:space-between;gap:10px;font-size:12px;color:#d4d4d8;"><span>${escapeHtml(`${item.executionId || '-'} · ${item.status || '-'}`)}</span><span style="color:#71717a;">${escapeHtml(formatDateTime(item.createdAt))}</span></li>`,
    '暂无我的执行记录'
  )}
          </div>
        `;
      } catch (error) {
        resourcesContainer.innerHTML = `<p style="margin:0;color:#ef4444;">个人资源加载失败：${escapeHtml(error.message || '未知错误')}</p>`;
      }
    }

    async function loadTenantContext() {
      tenantContainer.innerHTML = '加载租户信息中...';
      try {
        const payload = await api('/users/me/tenant-context');
        const available = Array.isArray(payload?.availableTenants) ? payload.availableTenants : [];
        tenantLoaded = true;

        const currentTenantId = Number(payload?.currentTenantId || 0) || null;
        const optionsHtml = available.length
          ? available.map((item) => `
              <option value="${item.tenantId}" ${Number(item.tenantId) === currentTenantId ? 'selected' : ''}>
                ${escapeHtml(`${item.tenantName || '-'} (${item.tenantCode || '-'})`)}
              </option>
            `).join('')
          : '<option value="">暂无可用租户</option>';

        tenantContainer.innerHTML = `
          <div style="border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:14px;background:rgba(255,255,255,0.03);display:grid;gap:10px;">
            <div>
              <p style="margin:0;color:#a1a1aa;font-size:12px;">当前租户</p>
              <p style="margin:4px 0 0;color:#fff;font-size:16px;font-weight:600;">${escapeHtml(payload?.currentTenantName || '-')}</p>
              <p style="margin:4px 0 0;color:#71717a;font-size:12px;">租户编码：${escapeHtml(payload?.currentTenantCode || '-')}</p>
            </div>
            <div style="display:grid;gap:8px;">
              <label style="display:block;color:#a1a1aa;font-size:12px;">切换当前作业租户</label>
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <select id="app-profile-tenant-select" style="flex:1;min-width:220px;padding:10px 12px;border-radius:10px;border:1px solid rgba(255,255,255,0.14);background:rgba(255,255,255,0.05);color:#fff;font-size:13px;">
                  ${optionsHtml}
                </select>
                <button id="app-profile-tenant-switch" type="button" style="padding:10px 14px;border:0;border-radius:10px;background:linear-gradient(135deg,#00d4ff,#7c3aed);color:#fff;font-weight:600;cursor:pointer;">切换租户</button>
              </div>
            </div>
            <div style="display:grid;gap:6px;">
              <p style="margin:0;color:#a1a1aa;font-size:12px;">我可访问的租户</p>
              ${available.length
    ? `<ul style="list-style:none;padding:0;margin:0;display:grid;gap:6px;">${available.map((item) => `<li style=\"display:flex;justify-content:space-between;gap:10px;font-size:12px;color:#d4d4d8;\"><span>${escapeHtml(`${item.tenantName || '-'} (${item.tenantCode || '-'})`)}</span><span style=\"color:#71717a;\">${escapeHtml(item.roleDisplayName || item.role || '-')}</span></li>`).join('')}</ul>`
    : '<p style="margin:0;color:#71717a;font-size:12px;">暂无可访问租户</p>'}
            </div>
          </div>
        `;

        const switchButton = tenantContainer.querySelector('#app-profile-tenant-switch');
        const selectNode = tenantContainer.querySelector('#app-profile-tenant-select');
        if (switchButton && selectNode && available.length) {
          switchButton.addEventListener('click', async () => {
            const tenantId = Number(selectNode.value || 0);
            if (!tenantId) {
              toast('请选择目标租户', 'warning');
              return;
            }
            if (tenantId === currentTenantId) {
              toast('当前已在该租户下', 'info');
              return;
            }

            const previous = switchButton.textContent;
            switchButton.disabled = true;
            switchButton.textContent = '切换中...';
            try {
              await api('/users/me/tenant-context', {
                method: 'PUT',
                body: { tenantId }
              });
              const refreshedUser = await api('/auth/me');
              setUserCache(refreshedUser);
              syncUserDisplay(refreshedUser);
              toast('租户切换成功，正在刷新页面', 'success');
              window.setTimeout(() => {
                window.location.reload();
              }, 220);
            } catch (error) {
              toast(error.message || '租户切换失败', 'error');
              switchButton.disabled = false;
              switchButton.textContent = previous;
            }
          });
        }
      } catch (error) {
        tenantContainer.innerHTML = `<p style="margin:0;color:#ef4444;">租户信息加载失败：${escapeHtml(error.message || '未知错误')}</p>`;
      }
    }

    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) closeProfileSettingsModal();
    });
    closeButton.addEventListener('click', closeProfileSettingsModal);
    profileTabButton.addEventListener('click', () => setTab('profile'));
    assetTabButton.addEventListener('click', () => setTab('assets'));
    tenantTabButton.addEventListener('click', () => setTab('tenant'));

    fullNameInput.addEventListener('input', refreshProfilePreview);

    Array.from(overlay.querySelectorAll('button[data-avatar-gallery]')).forEach((button) => {
      button.addEventListener('click', () => {
        selectedAvatar = galleryByKey[button.dataset.avatarGallery] || '';
        refreshAvatarSelectionUI();
        refreshProfilePreview();
      });
    });

    Array.from(overlay.querySelectorAll('button[data-avatar-emoji]')).forEach((button) => {
      button.addEventListener('click', () => {
        selectedAvatar = button.dataset.avatarEmoji || '';
        refreshAvatarSelectionUI();
        refreshProfilePreview();
      });
    });

    overlay.querySelector('#app-profile-avatar-clear').addEventListener('click', () => {
      selectedAvatar = '';
      refreshAvatarSelectionUI();
      refreshProfilePreview();
    });

    overlay.querySelector('#app-profile-avatar-upload').addEventListener('change', async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      if (!String(file.type || '').startsWith('image/')) {
        toast('仅支持图片文件', 'warning');
        event.target.value = '';
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        toast('图片不能超过 5MB', 'warning');
        event.target.value = '';
        return;
      }

      try {
        selectedAvatar = await imageFileToAvatarDataUrl(file, 192);
        refreshAvatarSelectionUI();
        refreshProfilePreview();
        toast('头像已加载，点击“保存个人资料”生效', 'info');
      } catch (error) {
        toast(error.message || '头像处理失败', 'error');
      } finally {
        event.target.value = '';
      }
    });

    saveButton.addEventListener('click', async () => {
      const fullName = fullNameInput.value.trim();
      if (!fullName) {
        toast('姓名不能为空', 'warning');
        return;
      }
      const avatar = String(selectedAvatar || '').trim();
      if (avatar.length > PROFILE_MAX_AVATAR_LENGTH) {
        toast('头像内容过大，请选择更小图片', 'warning');
        return;
      }

      const previousText = saveButton.textContent;
      saveButton.disabled = true;
      saveButton.textContent = '保存中...';
      try {
        const updated = await api('/users/me/profile', {
          method: 'PUT',
          body: { fullName, avatar }
        });
        setUserCache(updated);
        syncUserDisplay(updated);
        selectedAvatar = String(updated.avatar || '').trim();
        fullNameInput.value = String(updated.fullName || '').trim();
        refreshAvatarSelectionUI();
        refreshProfilePreview();
        toast('个人资料已保存', 'success');
      } catch (error) {
        toast(error.message || '个人资料保存失败', 'error');
      } finally {
        saveButton.disabled = false;
        saveButton.textContent = previousText;
      }
    });

    refreshAvatarSelectionUI();
    refreshProfilePreview();
    setTab('profile');

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }

    return overlay;
  }

  function bindGlobalProfileSettings() {
    document.addEventListener('click', (event) => {
      const target = event.target.closest('a,button');
      if (!target) return;

      const action = String(target.dataset.action || '').trim();
      const text = String(target.textContent || '').trim();
      const href = String(target.getAttribute('href') || '').trim().toLowerCase();
      const inUserMenu = !!target.closest('#user-menu')
        || !!target.closest('#app-global-user-menu')
        || !!target.closest('#app-global-user-dropdown')
        || !!target.closest('.sidebar-footer #user-dropdown')
        || !!target.closest('#user-dropdown');

      const isLegacyProfileHref = href.includes('settings.html#profile') || href === '#profile';
      const isProfileLabel = inUserMenu && (text === '个人设置' || text === '个人资料');
      if (action !== 'profile-settings' && !isLegacyProfileHref && !isProfileLabel) return;

      event.preventDefault();
      closePossibleUserMenus();
      openProfileSettingsModal().catch((error) => {
        toast(error.message || '打开个人设置失败', 'error');
      });
    });
  }

  function bindGlobalLogout() {
    document.addEventListener('click', (event) => {
      const target = event.target.closest('a,button');
      if (!target) return;
      const text = (target.textContent || '').trim();
      if (text.includes('退出登录') || target.dataset.action === 'logout') {
        event.preventDefault();
        logout();
      }
    });
  }

  bindGlobalProfileSettings();
  bindGlobalLogout();

  const bootstrapGlobalTopActions = async () => {
    initializeGlobalSidebarCollapse();
    scheduleGlobalTopActionsEnsure();
    bindGlobalTopActionsObserver();
    bindDashboardSearchTrigger();
    bindGlobalSearchShortcut();
    bindDashboardNotifications();
    try {
      const user = await hydrateUser();
      if (user) {
        syncUserDisplay(user);
        ensureNotificationSeenState();
        await refreshNotificationPanels(true).catch(() => {});
        startNotificationPolling();
      } else {
        stopNotificationPolling();
      }
    } catch (_error) {
      // Ignore user hydration errors here to avoid blocking page bootstrap.
      stopNotificationPolling();
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      void bootstrapGlobalTopActions();
    }, { once: true });
  } else {
    void bootstrapGlobalTopActions();
  }

  window.AppRuntime = {
    STORAGE_KEYS,
    DEFAULT_SETTINGS,
    getSettings,
    saveSettings,
    getAccessToken,
    getRefreshToken,
    getUserCache,
    setUserCache,
    clearAuth,
    api,
    ensureAuth,
    hydrateUser,
    login,
    logout,
    openProfileSettingsModal,
    closeProfileSettingsModal,
    syncUserDisplay,
    resolveLoginPath,
    toast,
    confirm,
    showJsonModal,
    formatDateTime,
    formatDurationMs,
    downloadJson,
    escapeHtml
  };
})();
