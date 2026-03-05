(() => {
  'use strict';

  const R = window.AppRuntime;
  if (!R) return;

  const US_STATUS_LABEL = {
    DRAFT: '待分析',
    ANALYZING: '分析中',
    READY: '待生成用例',
    IN_PROGRESS: '待采纳',
    PENDING_EXECUTION: '待执行',
    DONE: '执行完毕',
    ARCHIVED: '已归档'
  };
  const US_STATUS_OPTIONS = ['DRAFT', 'ANALYZING', 'READY', 'IN_PROGRESS', 'PENDING_EXECUTION', 'DONE', 'ARCHIVED'];

  const US_PRIORITY_LABEL = {
    LOW: '低',
    MEDIUM: '中',
    HIGH: '高',
    CRITICAL: '紧急'
  };

  const CASE_STATUS_LABEL = {
    DRAFT: '草稿',
    REVIEW: '评审中',
    READY: '就绪',
    DEPRECATED: '废弃',
    ARCHIVED: '归档'
  };

  const CASE_TYPE_LABEL = {
    FUNCTIONAL: '功能',
    UI: 'UI',
    API: 'API',
    PERFORMANCE: '性能',
    SECURITY: '安全',
    COMPATIBILITY: '兼容'
  };

  const CASE_PRIORITY_LABEL = {
    LOW: 'L3',
    MEDIUM: 'L2',
    HIGH: 'L1',
    CRITICAL: 'L0'
  };

  const SCRIPT_TYPE_LABEL = {
    PLAYWRIGHT: 'Playwright',
    SELENIUM: 'Selenium',
    CYPRESS: 'Cypress',
    APPIUM: 'Appium',
    REST_ASSURED: 'RestAssured'
  };

  const EXEC_STATUS_LABEL = {
    PENDING: '待执行',
    QUEUED: '排队中',
    RUNNING: '执行中',
    PAUSED: '已暂停',
    COMPLETED: '已完成',
    CANCELLED: '已取消',
    FAILED: '失败',
    TIMEOUT: '超时'
  };

  const EXEC_RESULT_LABEL = {
    PASS: '通过',
    FAIL: '失败',
    SKIP: '跳过',
    ERROR: '错误',
    WARNING: '警告'
  };

  const $ = (selector, root = document) => (root || document).querySelector(selector);
  const $$ = (selector, root = document) => Array.from((root || document).querySelectorAll(selector));

  function unwrapPage(data) {
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (Array.isArray(data.content)) return data.content;
    return [];
  }

  function debounce(fn, wait = 280) {
    let timer = null;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), wait);
    };
  }

  function statusBadge(status) {
    const value = String(status || '').toUpperCase();
    const color = value === 'DONE' || value === 'READY' || value === 'COMPLETED' || value === 'PASS'
      ? 'background:rgba(16,185,129,0.2);color:#10b981;'
      : value === 'FAILED' || value === 'FAIL' || value === 'ERROR'
        ? 'background:rgba(239,68,68,0.2);color:#ef4444;'
        : value === 'RUNNING' || value === 'ANALYZING' || value === 'IN_PROGRESS'
          ? 'background:rgba(59,130,246,0.2);color:#3b82f6;'
          : 'background:rgba(255,255,255,0.09);color:#a1a1aa;';

    return `<span style="${color}padding:2px 8px;border-radius:999px;font-size:11px;white-space:nowrap;">${R.escapeHtml(value)}</span>`;
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

  function updateUserHeader(user) {
    if (!user) return;
    const name = user.fullName || user.username || 'User';
    const shortName = buildInitials(name);
    const avatarValue = user.avatar || '';
    const tenantSuffix = user.activeTenantName ? ` · ${user.activeTenantName}` : '';
    const roleText = `${user.roleDisplayName || user.role || '用户'}${tenantSuffix}`;

    const sidebarName = $('#user-name');
    if (sidebarName) sidebarName.textContent = name;

    const sidebarRole = $('#user-role');
    if (sidebarRole) sidebarRole.textContent = roleText;

    const fallbackNameNodes = $$('p.text-sm.font-medium').filter((node) => {
      const text = (node.textContent || '').trim();
      return text === 'Admin' || text === 'Administrator' || text === 'Admin User';
    });
    fallbackNameNodes.forEach((node) => {
      node.textContent = name;
    });

    const sidebarAvatar = $('#user-menu-trigger .sidebar-user-avatar');
    applyAvatarNode(sidebarAvatar, avatarValue, shortName);

    const avatarNodes = $$('div.w-8.h-8.rounded-full').filter((node) => {
      const text = (node.textContent || '').trim();
      return text.length <= 2;
    });
    avatarNodes.forEach((node) => {
      applyAvatarNode(node, avatarValue, shortName);
    });
  }

  function updateUsNavBadgeNodes(total) {
    const normalized = Math.max(0, Number(total) || 0);
    const display = normalized > 999 ? '999+' : String(normalized);
    $$('#us-nav-count-badge').forEach((node) => {
      node.textContent = display;
    });
    if (typeof window.updateNavBadge === 'function') {
      window.updateNavBadge('us-badge', normalized);
    }
  }

  function updateCaseNavBadgeNodes(total) {
    const normalized = Math.max(0, Number(total) || 0);
    const display = normalized > 999 ? '999+' : String(normalized);

    $$('#tc-nav-count-badge, #test-cases-badge, #tc-badge').forEach((node) => {
      node.textContent = display;
    });

    const links = $$('a[href$="test-cases.html"], a[href*="/test-cases.html"]');
    links.forEach((link) => {
      const title = link.querySelector('span.flex-1');
      if (!title || !String(title.textContent || '').includes('测试用例')) return;
      const candidate = [...link.querySelectorAll('span.rounded-full')]
        .find((node) => !node.classList.contains('w-2') && !node.classList.contains('h-2'));
      if (candidate) candidate.textContent = display;
    });

    if (typeof window.updateNavBadge === 'function') {
      window.updateNavBadge('test-cases-badge', normalized);
      window.updateNavBadge('tc-badge', normalized);
    }
  }

  function updateTestCaseHeaderBadge(total) {
    const normalized = Math.max(0, Number(total) || 0);
    const explicit = $('#tc-total-count-badge');
    if (explicit) {
      explicit.textContent = String(normalized);
      return;
    }
    const header = $('main header');
    if (!header) return;
    const title = $('h1', header);
    if (!title || String(title.textContent || '').trim() !== '测试用例') return;
    const fallback = title.parentElement?.querySelector('span.rounded-full');
    if (fallback) fallback.textContent = String(normalized);
  }

  async function refreshGlobalUsCounters() {
    try {
      const stats = await R.api('/dashboard/statistics');
      const storyTotal = Math.max(0, Number(stats?.totalUserStories ?? 0) || 0);
      const caseTotal = Math.max(0, Number(stats?.totalTestCases ?? 0) || 0);

      updateUsNavBadgeNodes(storyTotal);
      updateCaseNavBadgeNodes(caseTotal);

      const headerBadge = $('#us-total-count-badge');
      if (headerBadge) headerBadge.textContent = String(storyTotal);
    } catch (_error) {
      // Ignore nav badge refresh failures to avoid blocking page render.
    }
  }

  async function initializeDashboardPage() {
    const user = await R.hydrateUser();
    if (user) updateUserHeader(user);

    const trendRangeSelect = $('#dashboard-trend-range');
    const allowedTrendDays = [7, 30, 90];

    function resolveTrendDays() {
      const days = Number(trendRangeSelect?.value || 30);
      return allowedTrendDays.includes(days) ? days : 30;
    }

    async function fetchDashboardData() {
      const trendDays = resolveTrendDays();
      return R.api(`/dashboard?trendDays=${trendDays}`);
    }

    function renderStatistics(stats) {
      const projectNode = $('#stat-projects');
      if (projectNode) projectNode.textContent = String(stats.totalProjects ?? 0);

      const usNode = $('#stat-us');
      if (usNode) usNode.textContent = String(stats.totalUserStories ?? 0);

      const caseNode = $('#stat-cases');
      if (caseNode) caseNode.textContent = String(stats.totalTestCases ?? 0);

      const passRateNode = $('#stat-passrate');
      if (passRateNode) passRateNode.textContent = `${Number(stats.successRate || 0).toFixed(1)}%`;
    }

    function renderTrend(charts) {
      const trendContainer = $('#dashboard-trend-bars');
      if (!trendContainer) return;

      const rawTrend = Array.isArray(charts.executionTrend) ? charts.executionTrend : [];
      const trend = aggregateTrendPoints(rawTrend);
      trendContainer.style.gap = trend.length > 12 ? '0.25rem' : '0.75rem';
      const max = Math.max(1, ...trend.map((item) => Number(item.value || 0)));
      trendContainer.innerHTML = trend.length
        ? trend.map((item) => {
          const value = Number(item.value || 0);
          const height = Math.max(8, Math.round((value / max) * 200));
          const bucketSize = Number(item.bucketSize || 1);
          const tooltip = bucketSize > 1
            ? `${item.label} | 共 ${value} 次（${bucketSize} 天）`
            : String(value);
          return `
            <div class="min-w-0 flex-1 flex flex-col items-center gap-2">
              <div class="w-full bg-gradient-to-t from-[#00d4ff] to-[#7c3aed] rounded-t-lg chart-bar" style="height:${height}px;" title="${R.escapeHtml(tooltip)}"></div>
              <span class="block w-full text-center text-[10px] text-[#71717a] truncate">${R.escapeHtml(item.label || '-')}</span>
            </div>
          `;
        }).join('')
        : '<div class="w-full h-full flex items-end"><span class="text-xs text-[#71717a]">暂无执行趋势数据</span></div>';
    }

    function aggregateTrendPoints(source) {
      const trend = Array.isArray(source) ? source : [];
      const total = trend.length;
      if (total <= 14) {
        return trend.map((item) => ({
          label: item.label,
          value: Number(item.value || 0),
          color: item.color || '#00d4ff',
          bucketSize: 1
        }));
      }

      const targetBars = total <= 45 ? 12 : 15;
      const bucketSize = Math.max(1, Math.ceil(total / targetBars));
      const buckets = [];
      for (let start = 0; start < total; start += bucketSize) {
        const slice = trend.slice(start, start + bucketSize);
        const first = slice[0] || {};
        const last = slice[slice.length - 1] || first;
        const sum = slice.reduce((acc, item) => acc + Number(item.value || 0), 0);
        buckets.push({
          label: compactTrendLabel(first.label, last.label),
          value: sum,
          color: first.color || '#00d4ff',
          bucketSize: slice.length
        });
      }
      return buckets;
    }

    function compactTrendLabel(startLabel, endLabel) {
      const start = String(startLabel || '').trim();
      const end = String(endLabel || '').trim();
      if (!start) return end || '-';
      if (!end || start === end) return start;

      const startParts = start.split('-');
      const endParts = end.split('-');
      if (startParts.length === 2 && endParts.length === 2 && startParts[0] === endParts[0]) {
        return `${startParts[0]}-${startParts[1]}~${endParts[1]}`;
      }
      return `${start}~${end}`;
    }

    function renderExecutionResults(charts) {
      const donutNode = $('#dashboard-status-donut');
      const legendNode = $('#dashboard-status-legend');
      if (!donutNode || !legendNode) return;

      const resultRows = Array.isArray(charts.executionResults) ? charts.executionResults : [];
      const normalized = resultRows.map((item) => {
        const key = String(item.label || '').toUpperCase();
        const map = {
          PASS: { label: '通过', color: '#10b981' },
          FAIL: { label: '失败', color: '#ef4444' },
          ERROR: { label: '错误', color: '#f59e0b' },
          SKIP: { label: '跳过', color: '#3b82f6' }
        };
        const preset = map[key] || { label: item.label || '其他', color: item.color || '#71717a' };
        return {
          label: preset.label,
          value: Number(item.value || 0),
          color: preset.color
        };
      });
      const total = normalized.reduce((sum, item) => sum + item.value, 0);
      const radius = 40;
      const circumference = 2 * Math.PI * radius;
      let offset = 0;
      const circles = normalized.map((item) => {
        const portion = total > 0 ? (item.value / total) : 0;
        const dash = Math.max(0, portion * circumference);
        const node = `<circle cx="50" cy="50" r="${radius}" fill="none" stroke="${item.color}" stroke-width="12" stroke-dasharray="${dash} ${circumference}" stroke-dashoffset="${-offset}"></circle>`;
        offset += dash;
        return node;
      }).join('');

      donutNode.innerHTML = `
        <svg viewBox="0 0 100 100" class="w-full h-full -rotate-90">
          ${circles}
        </svg>
        <div class="absolute inset-0 flex flex-col items-center justify-center">
          <span class="text-2xl font-bold">${R.escapeHtml(String(total))}</span>
          <span class="text-xs text-[#71717a]">总执行</span>
        </div>
      `;

      legendNode.innerHTML = normalized.map((item) => {
        const percent = total > 0 ? ((item.value / total) * 100).toFixed(1) : '0.0';
        return `
          <div class="flex items-center gap-2">
            <div class="w-3 h-3 rounded-full" style="background:${item.color};"></div>
            <span class="text-xs text-[#a1a1aa]">${R.escapeHtml(item.label)} (${percent}%)</span>
          </div>
        `;
      }).join('');
    }

    function renderRecentActivities(activities) {
      const activityNode = $('#dashboard-recent-activities');
      if (!activityNode) return;

      const recentExecutions = Array.isArray(activities.recentExecutions) ? activities.recentExecutions : [];
      const recentUserStories = Array.isArray(activities.recentUserStories) ? activities.recentUserStories : [];
      const recentScripts = Array.isArray(activities.recentScripts) ? activities.recentScripts : [];
      const merged = [...recentExecutions, ...recentUserStories, ...recentScripts]
        .sort((a, b) => new Date(b.timestamp || 0).getTime() - new Date(a.timestamp || 0).getTime())
        .slice(0, 6);

      activityNode.innerHTML = merged.length
        ? merged.map((item) => {
          const type = String(item.type || '').toLowerCase();
          const meta = type === 'execution'
            ? { icon: 'play', iconBg: 'rgba(16,185,129,0.2)', iconColor: '#10b981' }
            : type === 'userstory'
              ? { icon: 'file-text', iconBg: 'rgba(0,212,255,0.2)', iconColor: '#00d4ff' }
              : { icon: 'code-2', iconBg: 'rgba(124,58,237,0.2)', iconColor: '#7c3aed' };
          return `
            <div class="flex items-start gap-3 p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors">
              <div class="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style="background-color:${meta.iconBg};">
                <i data-lucide="${meta.icon}" class="w-4 h-4" style="color:${meta.iconColor};"></i>
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm">${R.escapeHtml(item.title || '-')}</p>
                <p class="text-xs text-[#71717a] mt-1">${R.escapeHtml(R.formatDateTime(item.timestamp))}</p>
              </div>
            </div>
          `;
        }).join('')
        : '<p class="text-xs text-[#71717a]">暂无最近活动</p>';
    }

    function renderNotifications(activities) {
      const panel = $('#notifications-panel .space-y-2');
      if (!panel) return;

      const items = Array.isArray(activities?.recentExecutions) ? activities.recentExecutions.slice(0, 3) : [];
      panel.innerHTML = items.length > 0
        ? items.map((item) => `
          <div class="p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors cursor-pointer">
            <div class="flex items-center gap-2">
              <div class="w-2 h-2 rounded-full ${item.status === 'COMPLETED' ? 'bg-[#10b981]' : item.status === 'FAILED' ? 'bg-[#ef4444]' : 'bg-[#3b82f6]'}"></div>
              <p class="font-medium text-sm">${R.escapeHtml(item.title || item.id || '执行记录')}</p>
            </div>
            <p class="text-xs text-[#a1a1aa] mt-1">状态: ${R.escapeHtml(item.status || '-')}</p>
            <p class="text-xs text-[#71717a] mt-1">${R.escapeHtml(item.timestamp || '-')}</p>
          </div>
        `).join('')
        : '<p class="text-xs text-[#71717a]">暂无最近执行记录</p>';
    }

    function renderDashboard(data) {
      const stats = data?.statistics || {};
      const charts = data?.charts || {};
      const activities = data?.recentActivities || {};

      renderStatistics(stats);
      renderTrend(charts);
      renderExecutionResults(charts);
      renderRecentActivities(activities);
      renderNotifications(activities);
      if (window.lucide) window.lucide.createIcons();
    }

    renderDashboard(await fetchDashboardData());

    trendRangeSelect?.addEventListener('change', async () => {
      try {
        renderDashboard(await fetchDashboardData());
      } catch (error) {
        R.toast(error.message || '加载执行趋势失败', 'error');
      }
    });
  }

  async function initializeUserStoriesPage() {
    const user = await R.ensureAuth();
    updateUserHeader(user);

    const main = $('main .p-6');
    const filterCard = $('main .p-6 > .glass-card');
    const tableCard = $('main .p-6 > .glass-card.overflow-hidden');
    const tableBody = $('tbody');
    const parseModal = $('#parse-modal');
    const importModal = $('#import-modal');

    if (!main || !filterCard || !tableCard || !tableBody || !parseModal || !importModal) return;

    const searchInput = $('input[placeholder*="搜索 US"]', filterCard);
    const filterSelects = $$('select', filterCard);
    const statusSelect = filterSelects[0];
    const sprintSelect = filterSelects[1];
    const navCountBadge = $('#us-nav-count-badge');
    const headerCountBadge = $('#us-total-count-badge');
    const selectAllStoriesCheckbox = $('#us-select-all', tableCard);
    const batchStoryActionsButton = $('#us-batch-actions-button');
    const batchStoryActionsMenu = $('#us-batch-actions-menu');
    if (!searchInput || !statusSelect || !sprintSelect) return;

    statusSelect.innerHTML = [
      '<option value="">全部状态</option>',
      '<option value="DRAFT">待分析</option>',
      '<option value="ANALYZING">分析中</option>',
      '<option value="READY">待生成用例</option>',
      '<option value="IN_PROGRESS">待采纳</option>',
      '<option value="PENDING_EXECUTION">待执行</option>',
      '<option value="DONE">执行完毕</option>',
      '<option value="ARCHIVED">已归档</option>'
    ].join('');

    const legacyPaginationBar = $('.flex.items-center.justify-between.mt-4.animate-fade-in-up.stagger-3', main);
    if (legacyPaginationBar) legacyPaginationBar.remove();

    let paginationBar = $('#us-pagination-bar');
    if (paginationBar) paginationBar.remove();
    paginationBar = document.createElement('div');
    paginationBar.id = 'us-pagination-bar';
    paginationBar.className = 'glass-card mt-4 px-4 py-3 flex flex-wrap items-center justify-between gap-3';
    paginationBar.innerHTML = `
      <div id="us-page-summary" class="text-xs text-[#a1a1aa]">共 0 条，显示 0-0</div>
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2 text-xs text-[#a1a1aa]">
          <span>每页</span>
          <select id="us-page-size" class="px-2 py-1 bg-white/5 border border-white/10 rounded text-xs focus:outline-none focus:border-[#00d4ff]">
            <option value="10">10</option>
            <option value="20" selected>20</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </label>
        <button id="us-page-prev" class="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-xs disabled:opacity-50 disabled:cursor-not-allowed" type="button">上一页</button>
        <span id="us-page-info" class="text-xs text-[#d4d4d8] min-w-[72px] text-center">0 / 0</span>
        <button id="us-page-next" class="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-xs disabled:opacity-50 disabled:cursor-not-allowed" type="button">下一页</button>
      </div>
    `;
    tableCard.insertAdjacentElement('afterend', paginationBar);

    const pageSummary = $('#us-page-summary', paginationBar);
    const pageSizeSelect = $('#us-page-size', paginationBar);
    const prevPageButton = $('#us-page-prev', paginationBar);
    const nextPageButton = $('#us-page-next', paginationBar);
    const pageInfo = $('#us-page-info', paginationBar);

    const state = {
      items: [],
      keyword: '',
      status: '',
      sprint: '',
      sprintOptions: [],
      page: 0,
      size: 20,
      totalElements: 0,
      totalPages: 0,
      first: true,
      last: true,
      sprintsLoaded: false,
      importSource: 'JIRA',
      expandedStoryId: null,
      expandedStoryDetail: null,
      analyzingStoryIds: new Set(),
      generatingStoryIds: new Set(),
      generationMetaByStory: new Map(),
      trackingGenerationTasks: new Map(),
      selectedStoryIds: new Set()
    };

    const pageSizeOptions = [10, 20, 50, 100];
    const defaultSprintOptions = ['Sprint 1', 'Sprint 2', 'Sprint 3', 'Sprint 4'];

    function renderUserStoryCounters(totalElements) {
      const total = Math.max(0, Number(totalElements) || 0);
      updateUsNavBadgeNodes(total);
      if (navCountBadge) {
        navCountBadge.textContent = total > 999 ? '999+' : String(total);
      }
      if (headerCountBadge) {
        headerCountBadge.textContent = String(total);
      }
    }

    async function refreshUserStoryCounters() {
      let total = Number(state.totalElements) || 0;
      const hasFilters = Boolean(state.keyword || state.status || state.sprint);
      if (hasFilters) {
        try {
          const allData = await R.api('/user-stories?page=0&size=1');
          total = Number(allData?.totalElements ?? total) || total;
        } catch (_error) {
          // Keep current page total as fallback when total query fails.
        }
      }
      renderUserStoryCounters(total);
    }

    function renderPagination() {
      if (!pageSummary || !pageInfo || !pageSizeSelect || !prevPageButton || !nextPageButton) return;
      const totalElements = Number(state.totalElements) || 0;
      const totalPages = Number(state.totalPages) || 0;
      const pageNumber = Number(state.page) || 0;
      const hasData = totalElements > 0 && totalPages > 0;
      const start = hasData ? (pageNumber * state.size) + 1 : 0;
      const end = hasData ? Math.min((pageNumber + 1) * state.size, totalElements) : 0;
      const current = hasData ? (pageNumber + 1) : 0;

      pageSummary.textContent = `共 ${totalElements} 条，显示 ${start}-${end}`;
      pageInfo.textContent = `${current} / ${totalPages}`;
      pageSizeSelect.value = String(state.size);
      prevPageButton.disabled = !hasData || pageNumber <= 0;
      nextPageButton.disabled = !hasData || pageNumber >= (totalPages - 1);
    }

    function getCurrentPageStoryIds() {
      return state.items
        .map((item) => Number(item?.id))
        .filter((id) => Number.isInteger(id) && id > 0);
    }

    function pruneStorySelectionToCurrentPage() {
      const visibleIds = new Set(getCurrentPageStoryIds());
      [...state.selectedStoryIds].forEach((id) => {
        if (!visibleIds.has(id)) {
          state.selectedStoryIds.delete(id);
        }
      });
    }

    function syncStorySelectionControls() {
      const rowCheckboxes = $$('input[data-action="select-story"]', tableBody);
      let checkedCount = 0;
      rowCheckboxes.forEach((checkbox) => {
        const id = Number(checkbox.dataset.id);
        const checked = Number.isInteger(id) && state.selectedStoryIds.has(id);
        checkbox.checked = checked;
        if (checked) checkedCount += 1;
      });

      const totalCount = rowCheckboxes.length;
      if (selectAllStoriesCheckbox) {
        selectAllStoriesCheckbox.disabled = totalCount <= 0;
        selectAllStoriesCheckbox.checked = totalCount > 0 && checkedCount === totalCount;
        selectAllStoriesCheckbox.indeterminate = checkedCount > 0 && checkedCount < totalCount;
      }

      const hasSelection = checkedCount > 0;
      if (batchStoryActionsButton) {
        batchStoryActionsButton.disabled = !hasSelection;
      }
      if (!hasSelection && batchStoryActionsMenu) {
        batchStoryActionsMenu.classList.add('hidden');
      }
    }

    async function loadSprintOptions(force = false) {
      if (!force && state.sprintsLoaded) return;
      const sprints = await R.api('/user-stories/sprints');
      const dynamicItems = Array.isArray(sprints)
        ? sprints.map((item) => String(item || '').trim()).filter(Boolean)
        : [];
      const items = Array.from(new Set([
        ...defaultSprintOptions,
        ...dynamicItems
      ]));
      if (state.sprint && !items.includes(state.sprint)) {
        items.push(state.sprint);
      }
      state.sprintOptions = items;
      sprintSelect.innerHTML = [
        '<option value="">全部 Sprint</option>',
        ...items.map((s) => `<option value="${R.escapeHtml(s)}">${R.escapeHtml(s)}</option>`)
      ].join('');
      sprintSelect.value = state.sprint;
      state.sprintsLoaded = true;
    }

    function formatUsDate(value) {
      if (!value) return '-';
      return R.formatDateTime(value);
    }

    function renderValidationPointList(detail) {
      const points = Array.isArray(detail?.validationPoints)
        ? detail.validationPoints.filter(Boolean)
        : [];
      if (!points.length) {
        const count = Number(detail?.validationPointCount || 0);
        const countText = count > 0 ? `（当前统计 ${count} 条）` : '';
        return `<p class="text-xs text-[#71717a]">暂无验证点明细${countText}</p>`;
      }

      return `
        <ul class="space-y-2">
          ${points.map((point, index) => {
            const priority = String(point.priority || 'MEDIUM').toUpperCase();
            const vpStatus = String(point.status || 'PENDING').toUpperCase();
            return `
              <li class="p-3 rounded-lg bg-white/5 border border-white/10">
                <div class="flex items-center justify-between gap-2">
                  <p class="text-sm text-[#f5f5f5]">${index + 1}. ${R.escapeHtml(point.description || '-')}</p>
                  <div class="flex items-center gap-2 shrink-0">
                    <span class="px-2 py-0.5 rounded text-[11px] bg-[#7c3aed]/20 text-[#c4b5fd]">${R.escapeHtml(priority)}</span>
                    <span class="px-2 py-0.5 rounded text-[11px] bg-white/10 text-[#a1a1aa]">${R.escapeHtml(vpStatus)}</span>
                  </div>
                </div>
                <p class="text-xs text-[#a1a1aa] mt-1">期望结果：${R.escapeHtml(point.expectedResult || '-')}</p>
              </li>
            `;
          }).join('')}
        </ul>
      `;
    }

    function normalizeUsStatus(statusRaw) {
      const normalized = String(statusRaw || '').toUpperCase();
      return US_STATUS_OPTIONS.includes(normalized) ? normalized : 'DRAFT';
    }

    function resolveUsStatusBadgeClass(statusRaw) {
      const status = normalizeUsStatus(statusRaw);
      if (status === 'DONE' || status === 'READY' || status === 'PENDING_EXECUTION') {
        return 'bg-[#10b981]/20 text-[#6ee7b7]';
      }
      if (status === 'IN_PROGRESS' || status === 'ANALYZING') {
        return 'bg-[#3b82f6]/20 text-[#93c5fd]';
      }
      if (status === 'ARCHIVED') {
        return 'bg-white/10 text-[#a1a1aa]';
      }
      return 'bg-white/10 text-[#d4d4d8]';
    }

    function buildDetailRow(us) {
      if (state.expandedStoryId !== us.id) return '';
      const detail = state.expandedStoryDetail && state.expandedStoryDetail.id === us.id
        ? state.expandedStoryDetail
        : us;
      const title = R.escapeHtml(detail.title || '');
      const description = R.escapeHtml(detail.description || '');
      const acceptanceCriteria = R.escapeHtml(detail.acceptanceCriteria || '');
      const validationPointsHtml = renderValidationPointList(detail);

      return `
        <tr class="border-b border-white/5 bg-white/[0.03]" data-detail-row="${us.id}">
          <td colspan="8" class="px-4 py-4">
            <div class="rounded-xl border border-white/10 bg-white/[0.02] p-4 space-y-4">
              <div class="flex items-center justify-between gap-3">
                <h4 class="text-sm font-semibold text-[#e4e4e7]">US 详情与编辑</h4>
                <span class="text-xs text-[#71717a]">${R.escapeHtml(detail.usNumber || `US-${us.id}`)}</span>
              </div>
              <div>
                <label class="block text-xs text-[#a1a1aa] mb-1">标题</label>
                <input data-field="title" type="text" value="${title}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
              </div>
              <div>
                <label class="block text-xs text-[#a1a1aa] mb-1">描述（As / I want / So that）</label>
                <textarea data-field="description" rows="4" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff] resize-y" placeholder="AS ...&#10;I want ...&#10;So that ...">${description}</textarea>
              </div>
              <div>
                <label class="block text-xs text-[#a1a1aa] mb-1">验收标准（Given / When / Then）</label>
                <textarea data-field="acceptanceCriteria" rows="5" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff] resize-y" placeholder="Given: ...&#10;When: ...&#10;Then: ...">${acceptanceCriteria}</textarea>
              </div>
              <div>
                <label class="block text-xs text-[#a1a1aa] mb-2">验证点</label>
                ${validationPointsHtml}
              </div>
              <div class="flex justify-end gap-2">
                <button data-action="collapse-detail" data-id="${us.id}" class="px-3 py-1.5 text-xs rounded bg-white/10 text-[#d4d4d8] hover:bg-white/20">收起</button>
                <button data-action="save-detail" data-id="${us.id}" class="px-3 py-1.5 text-xs rounded bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90">保存详情</button>
              </div>
            </div>
          </td>
        </tr>
      `;
    }

    function renderRows(items) {
      if (!items.length) {
        tableBody.innerHTML = '<tr><td colspan="8" class="px-4 py-10 text-center text-sm text-[#71717a]">暂无 US 数据</td></tr>';
        syncStorySelectionControls();
        return;
      }

      tableBody.innerHTML = items.map((us) => {
        const sprintValue = String(us.sprint || '').trim();
        const sprintCandidates = Array.from(new Set([
          ...state.sprintOptions,
          sprintValue
        ].filter(Boolean)));
        const sprintOptionsHtml = [
          `<option value="" ${sprintValue ? '' : 'selected'}>未设置</option>`,
          ...sprintCandidates.map((sprint) =>
            `<option value="${R.escapeHtml(sprint)}" ${sprint === sprintValue ? 'selected' : ''}>${R.escapeHtml(sprint)}</option>`
          )
        ].join('');
        const updatedTime = formatUsDate(us.updatedAt || us.createdAt);
        const isExpanded = state.expandedStoryId === us.id;
        const currentStatus = normalizeUsStatus(us.status);
        const isAnalyzing = state.analyzingStoryIds.has(us.id) || currentStatus === 'ANALYZING';
        const generationMeta = state.generationMetaByStory.get(us.id) || {};
        const generationStatus = String(generationMeta.status || '').toUpperCase();
        const isGenerating = generationStatus === 'RUNNING' || generationStatus === 'QUEUED' || state.generatingStoryIds.has(us.id);
        const hasGeneratedDraft = Boolean(
          generationMeta.hasDraft
          || (generationMeta.result && Array.isArray(generationMeta.result.draftCases) && generationMeta.result.draftCases.length)
        );
        const caseCount = Number(us.testCaseCount ?? 0) || 0;
        const canGenerateCases = currentStatus !== 'ARCHIVED';
        const canOpenGenerationPanel = canGenerateCases || hasGeneratedDraft || isGenerating;
        const generateDisabled = !canOpenGenerationPanel;
        const generateBlockedLabel = '已归档';
        const generateButtonLabel = isGenerating
          ? '生成中...'
          : (hasGeneratedDraft ? '查看生成' : (canGenerateCases ? '生成用例' : generateBlockedLabel));
        const generateButtonClass = generateDisabled
          ? 'px-2 py-1 text-xs rounded bg-white/10 text-[#71717a] cursor-not-allowed opacity-70'
          : (isGenerating
              ? 'px-2 py-1 text-xs rounded bg-[#10b981]/30 text-[#6ee7b7] hover:bg-[#10b981]/40'
              : 'px-2 py-1 text-xs rounded bg-[#10b981]/20 text-[#10b981] hover:bg-[#10b981]/30');
        const generateButtonTitle = generateDisabled
          ? '已归档 US 不支持生成用例'
          : (isGenerating ? '点击查看生成过程' : '');
        const deleteDisabled = isAnalyzing || isGenerating;
        const deleteButtonClass = deleteDisabled
          ? 'px-2 py-1 text-xs rounded bg-white/10 text-[#71717a] cursor-not-allowed opacity-70'
          : 'px-2 py-1 text-xs rounded bg-[#ef4444]/20 text-[#ef4444] hover:bg-[#ef4444]/30';
        const deleteButtonTitle = deleteDisabled
          ? (isGenerating ? 'US 生成用例中，暂不允许删除' : 'US 分析中，暂不允许删除')
          : '';
        const statusLabel = US_STATUS_LABEL[currentStatus] || currentStatus;
        const statusClass = resolveUsStatusBadgeClass(currentStatus);
        const analyzeDisabled = currentStatus === 'ARCHIVED';
        const analyzeButtonClass = analyzeDisabled
          ? 'px-2 py-1 text-xs rounded bg-[#3b82f6]/20 text-[#60a5fa] opacity-60 cursor-not-allowed'
          : (isAnalyzing
              ? 'px-2 py-1 text-xs rounded bg-[#3b82f6]/30 text-[#93c5fd] hover:bg-[#3b82f6]/40'
              : 'px-2 py-1 text-xs rounded bg-[#3b82f6]/20 text-[#3b82f6] hover:bg-[#3b82f6]/30');
        const analyzeButtonTitle = analyzeDisabled
          ? '已归档 US 不支持分析'
          : (isAnalyzing ? '点击查看分析过程' : '');
        const archiveEnabled = currentStatus === 'DONE';
        const archiveCompleted = currentStatus === 'ARCHIVED';
        const archiveButtonLabel = archiveCompleted ? '已归档' : '归档';
        const archiveDisabled = !archiveEnabled;
        const archiveButtonClass = archiveDisabled
          ? 'px-2 py-1 text-xs rounded bg-white/10 text-[#71717a] cursor-not-allowed opacity-70'
          : 'px-2 py-1 text-xs rounded bg-[#f59e0b]/20 text-[#fbbf24] hover:bg-[#f59e0b]/30';
        const archiveButtonTitle = archiveCompleted
          ? '该 US 已归档'
          : (archiveEnabled ? '归档后将无法继续分析和生成用例' : '仅执行完毕后可归档');
        const selected = state.selectedStoryIds.has(us.id);
        const baseRow = `
          <tr class="border-b border-white/5 hover:bg-white/5 transition-colors">
            <td class="px-4 py-3 text-sm">
              <input type="checkbox" data-action="select-story" data-id="${us.id}" class="rounded border-white/20 bg-white/5" ${selected ? 'checked' : ''}>
            </td>
            <td class="px-4 py-3 text-sm font-mono">
              <button data-action="toggle-detail" data-id="${us.id}" class="text-[#00d4ff] hover:underline">${R.escapeHtml(us.usNumber || '-')}</button>
            </td>
            <td class="px-4 py-3 text-sm">${R.escapeHtml(us.title || '-')}</td>
            <td class="px-4 py-3">
              <select data-action="change-sprint" data-id="${us.id}" class="px-2 py-1 text-xs rounded bg-white/5 border border-white/10 focus:outline-none focus:border-[#00d4ff] max-w-[140px] text-[#d4d4d8]">
                ${sprintOptionsHtml}
              </select>
            </td>
            <td class="px-4 py-3 text-sm">
              <button data-action="view-cases" data-id="${us.id}" class="text-[#22d3ee] hover:underline">${caseCount}</button>
            </td>
            <td class="px-4 py-3">
              <span class="inline-flex items-center px-2 py-1 rounded text-xs ${statusClass}">${R.escapeHtml(statusLabel)}</span>
            </td>
            <td class="px-4 py-3 text-sm text-[#71717a]">${R.escapeHtml(updatedTime)}</td>
            <td class="px-4 py-3">
              <div class="flex flex-wrap gap-1">
                <button data-action="analyze" data-id="${us.id}" ${analyzeDisabled ? 'disabled' : ''} class="${analyzeButtonClass}" title="${R.escapeHtml(analyzeButtonTitle)}">${isAnalyzing ? '分析中...' : '分析'}</button>
                <button data-action="generate" data-id="${us.id}" ${generateDisabled ? 'disabled' : ''} class="${generateButtonClass}" title="${R.escapeHtml(generateButtonTitle)}">${generateButtonLabel}</button>
                <button data-action="archive" data-id="${us.id}" ${archiveDisabled ? 'disabled' : ''} class="${archiveButtonClass}" title="${R.escapeHtml(archiveButtonTitle)}">${archiveButtonLabel}</button>
                <button data-action="delete" data-id="${us.id}" ${deleteDisabled ? 'disabled' : ''} class="${deleteButtonClass}" title="${R.escapeHtml(deleteButtonTitle)}">删除</button>
              </div>
            </td>
          </tr>
        `;
        return `${baseRow}${buildDetailRow(us)}`;
      }).join('');
      syncStorySelectionControls();
      if (window.lucide) window.lucide.createIcons();
    }

    let linkedCasesPanelNode = null;
    let linkedCasesPanelBody = null;
    let linkedCasesPanelTitle = null;
    let linkedCaseDetailModalNode = null;
    let linkedCaseDetailModalBody = null;
    let linkedCaseDetailModalTitle = null;
    let analysisPanelNode = null;
    let analysisPanelBody = null;
    let analysisPanelTitle = null;
    let analysisPanelApplyButton = null;
    let analysisPanelReanalyzeButton = null;
    let caseGenerationPanelNode = null;
    let caseGenerationPanelBody = null;
    let caseGenerationPanelTitle = null;
    let caseGenerationPanelAdoptButton = null;
    let caseGenerationPanelRegenerateButton = null;
    let caseGenerationDraftDetailModalNode = null;
    let caseGenerationDraftDetailModalBody = null;
    let caseGenerationDraftDetailModalTitle = null;
    const analysisContext = {
      userStoryId: null,
      analysis: null,
      detail: null,
      activeTaskId: null
    };
    const caseGenerationContext = {
      userStoryId: null,
      detail: null,
      activeTaskId: null,
      latestSnapshot: null,
      selectedDraftIds: new Set(),
      selectedRecordId: null,
      activeDraftId: null,
      recordPage: 0,
      recordPageSize: 5,
      recordDraftExpanded: true
    };
    const caseGenerationRecordPageSizeOptions = [5, 10, 20, 50];

    function closeLinkedCaseDetailModal() {
      if (linkedCaseDetailModalNode) linkedCaseDetailModalNode.classList.add('hidden');
    }

    function closeLinkedCasesPanel() {
      closeLinkedCaseDetailModal();
      if (linkedCasesPanelNode) linkedCasesPanelNode.classList.add('hidden');
    }

    function renderLinkedCaseDetailContent(testCase) {
      const steps = Array.isArray(testCase?.steps) ? testCase.steps.filter(Boolean) : [];
      const sortedSteps = steps.slice().sort((a, b) => (Number(a?.stepOrder) || 0) - (Number(b?.stepOrder) || 0));
      const statusText = CASE_STATUS_LABEL[testCase?.status] || testCase?.status || '-';
      const priorityText = CASE_PRIORITY_LABEL[testCase?.priority] || testCase?.priority || '-';
      const typeText = CASE_TYPE_LABEL[testCase?.testType] || testCase?.testType || '-';
      const preconditions = String(testCase?.preconditions || '').trim() || '-';
      const tags = String(testCase?.tags || '').trim() || '-';
      const description = String(testCase?.description || '').trim() || '-';
      const caseNumber = testCase?.caseNumber || (testCase?.id ? `TC-${testCase.id}` : '-');
      const updatedAt = testCase?.updatedAt ? R.formatDateTime(testCase.updatedAt) : '-';
      const stepHtml = sortedSteps.length
        ? sortedSteps.map((step, index) => {
          const order = Number(step?.stepOrder) || index + 1;
          return `
            <li class="rounded-lg border border-white/10 bg-white/[0.03] p-3">
              <p class="text-xs font-mono text-[#93c5fd]">Step ${order}</p>
              <p class="text-sm text-[#f5f5f5] mt-2"><span class="text-[#a1a1aa]">动作：</span>${R.escapeHtml(step?.action || '-')}</p>
              <p class="text-sm text-[#f5f5f5] mt-1"><span class="text-[#a1a1aa]">预期：</span>${R.escapeHtml(step?.expectedResult || '-')}</p>
              <p class="text-sm text-[#f5f5f5] mt-1"><span class="text-[#a1a1aa]">测试数据：</span>${R.escapeHtml(step?.testData || '-')}</p>
            </li>
          `;
        }).join('')
        : '<li class="text-sm text-[#71717a]">暂无步骤</li>';

      return `
        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div class="flex flex-wrap items-center gap-2">
            <span class="px-2 py-0.5 rounded text-xs bg-[#00d4ff]/20 text-[#7dd3fc]">${R.escapeHtml(caseNumber)}</span>
            <span class="px-2 py-0.5 rounded text-xs bg-[#7c3aed]/20 text-[#c4b5fd]">${R.escapeHtml(typeText)}</span>
            <span class="px-2 py-0.5 rounded text-xs bg-white/10 text-[#d4d4d8]">${R.escapeHtml(priorityText)}</span>
            <span class="px-2 py-0.5 rounded text-xs bg-[#10b981]/20 text-[#6ee7b7]">${R.escapeHtml(statusText)}</span>
          </div>
          <h4 class="text-base font-semibold text-white mt-3">${R.escapeHtml(testCase?.title || '-')}</h4>
          <p class="text-sm text-[#a1a1aa] mt-2 whitespace-pre-wrap">${R.escapeHtml(description)}</p>
          <p class="text-xs text-[#71717a] mt-3">最近更新：${R.escapeHtml(updatedAt)}</p>
        </section>

        <section class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h5 class="text-sm font-semibold text-[#e4e4e7] mb-2">前置条件</h5>
            <p class="text-sm text-[#d4d4d8] whitespace-pre-wrap">${R.escapeHtml(preconditions)}</p>
          </div>
          <div class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h5 class="text-sm font-semibold text-[#e4e4e7] mb-2">标签</h5>
            <p class="text-sm text-[#d4d4d8] whitespace-pre-wrap">${R.escapeHtml(tags)}</p>
          </div>
        </section>

        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <h5 class="text-sm font-semibold text-[#e4e4e7] mb-2">测试步骤</h5>
          <ol class="space-y-2">${stepHtml}</ol>
        </section>
      `;
    }

    function ensureLinkedCaseDetailModal() {
      if (linkedCaseDetailModalNode) return linkedCaseDetailModalNode;

      linkedCaseDetailModalNode = document.createElement('div');
      linkedCaseDetailModalNode.className = 'hidden fixed inset-0 z-[95] bg-black/75 backdrop-blur-sm';
      linkedCaseDetailModalNode.innerHTML = `
        <div class="absolute inset-0 flex items-center justify-center p-4">
          <div class="w-full max-w-4xl max-h-[88vh] overflow-hidden rounded-2xl border border-white/10 bg-[#12121a] shadow-2xl flex flex-col">
            <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
              <h3 id="us-linked-case-detail-title" class="text-base font-semibold text-white">测试用例详情</h3>
              <button id="us-linked-case-detail-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
            </div>
            <div id="us-linked-case-detail-body" class="flex-1 overflow-y-auto p-5 space-y-5"></div>
            <div class="px-5 py-4 border-t border-white/10 flex items-center justify-end">
              <button id="us-linked-case-detail-cancel" class="px-3 py-1.5 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(linkedCaseDetailModalNode);
      linkedCaseDetailModalBody = $('#us-linked-case-detail-body', linkedCaseDetailModalNode);
      linkedCaseDetailModalTitle = $('#us-linked-case-detail-title', linkedCaseDetailModalNode);
      $('#us-linked-case-detail-close', linkedCaseDetailModalNode)?.addEventListener('click', closeLinkedCaseDetailModal);
      $('#us-linked-case-detail-cancel', linkedCaseDetailModalNode)?.addEventListener('click', closeLinkedCaseDetailModal);
      linkedCaseDetailModalNode.addEventListener('click', (event) => {
        if (event.target === linkedCaseDetailModalNode) closeLinkedCaseDetailModal();
      });
      return linkedCaseDetailModalNode;
    }

    async function openLinkedCaseDetail(caseId) {
      const id = Number(caseId);
      if (!id) {
        R.toast('无效的测试用例', 'warning');
        return;
      }

      const modal = ensureLinkedCaseDetailModal();
      if (linkedCaseDetailModalTitle) {
        linkedCaseDetailModalTitle.textContent = `测试用例 #${id} 详情`;
      }
      if (linkedCaseDetailModalBody) {
        linkedCaseDetailModalBody.innerHTML = '<p class="text-sm text-[#71717a]">加载中...</p>';
      }
      modal.classList.remove('hidden');

      const detail = await R.api(`/test-cases/${id}`);
      if (linkedCaseDetailModalTitle) {
        linkedCaseDetailModalTitle.textContent = `${detail?.caseNumber || `TC-${id}`} 详情`;
      }
      if (linkedCaseDetailModalBody) {
        linkedCaseDetailModalBody.innerHTML = renderLinkedCaseDetailContent(detail || {});
      }
    }

    function ensureLinkedCasesPanel() {
      if (linkedCasesPanelNode) return linkedCasesPanelNode;

      linkedCasesPanelNode = document.createElement('div');
      linkedCasesPanelNode.className = 'hidden fixed inset-0 z-[80] bg-black/70 backdrop-blur-sm';
      linkedCasesPanelNode.innerHTML = `
        <div class="absolute inset-y-0 right-0 w-full max-w-2xl bg-[#12121a] border-l border-white/10 shadow-2xl flex flex-col">
          <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between">
            <h3 id="us-linked-cases-title" class="text-base font-semibold text-white">关联测试用例</h3>
            <button id="us-linked-cases-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
          </div>
          <div id="us-linked-cases-body" class="flex-1 overflow-y-auto p-5 space-y-3"></div>
        </div>
      `;
      document.body.appendChild(linkedCasesPanelNode);
      linkedCasesPanelBody = $('#us-linked-cases-body', linkedCasesPanelNode);
      linkedCasesPanelTitle = $('#us-linked-cases-title', linkedCasesPanelNode);

      $('#us-linked-cases-close', linkedCasesPanelNode)?.addEventListener('click', closeLinkedCasesPanel);
      linkedCasesPanelNode.addEventListener('click', (event) => {
        if (event.target === linkedCasesPanelNode) closeLinkedCasesPanel();
      });
      linkedCasesPanelBody?.addEventListener('click', async (event) => {
        const button = event.target.closest('button[data-action="view-linked-case-detail"]');
        if (!button) return;
        const caseId = Number(button.dataset.caseId);
        if (!caseId) return;
        try {
          await openLinkedCaseDetail(caseId);
        } catch (error) {
          R.toast(error.message || '加载测试用例详情失败', 'error');
        }
      });
      return linkedCasesPanelNode;
    }

    async function openLinkedCasesPanel(id) {
      const panel = ensureLinkedCasesPanel();
      const us = state.items.find((item) => item.id === id);
      if (linkedCasesPanelTitle) {
        linkedCasesPanelTitle.textContent = `${us?.usNumber || `US-${id}`} 关联测试用例`;
      }
      if (linkedCasesPanelBody) {
        linkedCasesPanelBody.innerHTML = '<p class="text-sm text-[#71717a]">加载中...</p>';
      }
      panel.classList.remove('hidden');

      const list = await R.api(`/test-cases/user-story/${id}`);
      const cases = Array.isArray(list) ? list : [];
      if (!linkedCasesPanelBody) return;

      if (!cases.length) {
        linkedCasesPanelBody.innerHTML = '<p class="text-sm text-[#71717a]">该 US 暂无关联测试用例</p>';
        return;
      }

      linkedCasesPanelBody.innerHTML = cases.map((item) => {
        const caseStatus = CASE_STATUS_LABEL[item.status] || item.status || '-';
        const casePriority = CASE_PRIORITY_LABEL[item.priority] || item.priority || '-';
        const caseNumber = item.caseNumber || `TC-${item.id}`;
        const title = item.title || '-';
        const caseId = Number(item.id) || 0;
        const detailDisabled = caseId <= 0;
        return `
          <div class="rounded-lg border border-white/10 bg-white/5 p-4">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <button
                  data-action="view-linked-case-detail"
                  data-case-id="${caseId}"
                  ${detailDisabled ? 'disabled' : ''}
                  class="text-sm font-mono text-[#00d4ff] hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                >${R.escapeHtml(caseNumber)}</button>
                <button
                  data-action="view-linked-case-detail"
                  data-case-id="${caseId}"
                  ${detailDisabled ? 'disabled' : ''}
                  class="block text-left text-sm mt-1 text-[#f5f5f5] hover:text-[#c7d2fe] disabled:opacity-80 disabled:cursor-not-allowed"
                >${R.escapeHtml(title)}</button>
                <p class="text-xs mt-1 text-[#a1a1aa]">${R.escapeHtml(item.description || '-')}</p>
              </div>
              <div class="shrink-0 flex flex-col items-end gap-1">
                <span class="px-2 py-0.5 rounded text-xs bg-[#7c3aed]/20 text-[#c4b5fd]">${R.escapeHtml(casePriority)}</span>
                <span class="text-xs text-[#71717a]">${R.escapeHtml(caseStatus)}</span>
                <button
                  data-action="view-linked-case-detail"
                  data-case-id="${caseId}"
                  ${detailDisabled ? 'disabled' : ''}
                  class="mt-1 px-2 py-0.5 rounded text-xs bg-white/10 text-[#d4d4d8] hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed"
                >查看详情</button>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    function closeAnalysisPanel() {
      if (analysisPanelNode) analysisPanelNode.classList.add('hidden');
    }

    function normalizeScore(score) {
      const parsed = Number(score);
      if (!Number.isFinite(parsed)) return 0;
      return Math.max(0, Math.min(100, Math.round(parsed)));
    }

    function qualityScoreTheme(score) {
      if (score >= 85) return { label: '优秀', tone: 'text-[#10b981]', bar: 'from-[#10b981] to-[#22c55e]' };
      if (score >= 70) return { label: '良好', tone: 'text-[#22d3ee]', bar: 'from-[#22d3ee] to-[#3b82f6]' };
      if (score >= 50) return { label: '一般', tone: 'text-[#f59e0b]', bar: 'from-[#f59e0b] to-[#f97316]' };
      return { label: '待改进', tone: 'text-[#ef4444]', bar: 'from-[#ef4444] to-[#f97316]' };
    }

    function issueSeverityTheme(severity) {
      const value = String(severity || 'MEDIUM').toUpperCase();
      if (value === 'HIGH') return 'bg-[#ef4444]/20 text-[#fca5a5]';
      if (value === 'LOW') return 'bg-[#10b981]/20 text-[#86efac]';
      return 'bg-[#f59e0b]/20 text-[#fcd34d]';
    }

    function ensureAnalysisPanel() {
      if (analysisPanelNode) return analysisPanelNode;

      analysisPanelNode = document.createElement('div');
      analysisPanelNode.className = 'hidden fixed inset-0 z-[90] bg-black/70 backdrop-blur-sm';
      analysisPanelNode.innerHTML = `
        <div class="absolute inset-y-0 right-0 w-full max-w-4xl bg-[#12121a] border-l border-white/10 shadow-2xl flex flex-col">
          <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
            <h3 id="us-analysis-title" class="text-base font-semibold text-white">US 质量分析</h3>
            <button id="us-analysis-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
          </div>
          <div id="us-analysis-body" class="flex-1 overflow-y-auto p-5 space-y-5"></div>
          <div class="px-5 py-4 border-t border-white/10 flex items-center justify-end gap-2">
            <button id="us-analysis-cancel" class="px-3 py-1.5 text-sm rounded bg-white/10 hover:bg-white/20">取消</button>
            <button id="us-analysis-reanalyze" class="px-3 py-1.5 text-sm rounded bg-[#0ea5e9]/20 text-[#7dd3fc] hover:bg-[#0ea5e9]/30">重新分析</button>
            <button id="us-analysis-apply-save" class="px-3 py-1.5 text-sm rounded bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90">一键写回并保存</button>
          </div>
        </div>
      `;
      document.body.appendChild(analysisPanelNode);
      analysisPanelBody = $('#us-analysis-body', analysisPanelNode);
      analysisPanelTitle = $('#us-analysis-title', analysisPanelNode);
      analysisPanelApplyButton = $('#us-analysis-apply-save', analysisPanelNode);
      analysisPanelReanalyzeButton = $('#us-analysis-reanalyze', analysisPanelNode);

      $('#us-analysis-close', analysisPanelNode)?.addEventListener('click', closeAnalysisPanel);
      $('#us-analysis-cancel', analysisPanelNode)?.addEventListener('click', closeAnalysisPanel);
      analysisPanelNode.addEventListener('click', (event) => {
        if (event.target === analysisPanelNode) closeAnalysisPanel();
      });
      analysisPanelReanalyzeButton?.addEventListener('click', () => {
        reanalyzeCurrentStory().catch((error) => R.toast(error.message || '重新分析失败', 'error'));
      });
      analysisPanelApplyButton?.addEventListener('click', () => {
        applyAnalysisWriteback().catch((error) => R.toast(error.message || '写回失败', 'error'));
      });
      return analysisPanelNode;
    }

    function renderAnalysisPendingPanel(us, detail, taskId) {
      const panel = ensureAnalysisPanel();
      analysisContext.userStoryId = us?.id || null;
      analysisContext.detail = detail || null;
      analysisContext.analysis = null;
      analysisContext.activeTaskId = taskId || null;

      if (analysisPanelTitle) {
        analysisPanelTitle.textContent = `${us?.usNumber || `US-${us?.id || '-'}`} 质量分析`;
      }
      if (analysisPanelBody) {
        analysisPanelBody.innerHTML = `
          <section class="rounded-xl border border-[#3b82f6]/30 bg-[#3b82f6]/10 p-4">
            <p class="text-sm text-[#93c5fd]">kun dark 正在分析该 US，请稍候...</p>
            <p class="text-xs text-[#bfdbfe] mt-2">你可以留在此面板等待结果，系统会自动刷新分析结论。</p>
            ${taskId ? `<p class="text-[11px] text-[#93c5fd] mt-3 font-mono">任务ID: ${R.escapeHtml(taskId)}</p>` : ''}
          </section>
        `;
      }
      if (analysisPanelReanalyzeButton) {
        analysisPanelReanalyzeButton.disabled = true;
        analysisPanelReanalyzeButton.classList.add('opacity-50', 'cursor-not-allowed');
      }
      if (analysisPanelApplyButton) {
        analysisPanelApplyButton.disabled = true;
        analysisPanelApplyButton.classList.add('opacity-50', 'cursor-not-allowed');
      }
      panel.classList.remove('hidden');
    }

    function renderAnalysisFailurePanel(us, detail, message) {
      const panel = ensureAnalysisPanel();
      analysisContext.userStoryId = us?.id || null;
      analysisContext.detail = detail || null;
      analysisContext.analysis = null;
      analysisContext.activeTaskId = null;

      if (analysisPanelTitle) {
        analysisPanelTitle.textContent = `${us?.usNumber || `US-${us?.id || '-'}`} 质量分析`;
      }
      if (analysisPanelBody) {
        analysisPanelBody.innerHTML = `
          <section class="rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-4">
            <p class="text-sm text-[#fecaca]">分析失败</p>
            <p class="text-xs text-[#fecaca] mt-2">${R.escapeHtml(message || 'AI 分析暂时不可用，请稍后重试')}</p>
          </section>
        `;
      }
      if (analysisPanelReanalyzeButton) {
        analysisPanelReanalyzeButton.disabled = !analysisContext.userStoryId;
        analysisPanelReanalyzeButton.classList.toggle('opacity-50', !analysisContext.userStoryId);
        analysisPanelReanalyzeButton.classList.toggle('cursor-not-allowed', !analysisContext.userStoryId);
      }
      if (analysisPanelApplyButton) {
        analysisPanelApplyButton.disabled = true;
        analysisPanelApplyButton.classList.add('opacity-50', 'cursor-not-allowed');
      }
      panel.classList.remove('hidden');
    }

    function renderAnalysisPanel(us, detail, analysis) {
      const panel = ensureAnalysisPanel();
      const score = normalizeScore(analysis?.qualityScore);
      const scoreTheme = qualityScoreTheme(score);
      const summary = String(analysis?.analysisSummary || 'AI 分析已完成').trim();
      const issues = Array.isArray(analysis?.qualityIssues) ? analysis.qualityIssues.filter(Boolean) : [];
      const validationPoints = Array.isArray(analysis?.validationPoints) ? analysis.validationPoints.filter(Boolean) : [];
      const suggestedCases = Array.isArray(analysis?.suggestedTestCases) ? analysis.suggestedTestCases.filter(Boolean) : [];
      const optimizedTitle = String(analysis?.optimizedTitle || detail?.title || us?.title || '').trim();
      const optimizedDescription = String(analysis?.optimizedDescription || detail?.description || '').trim();
      const optimizedAcceptanceCriteria = String(analysis?.optimizedAcceptanceCriteria || detail?.acceptanceCriteria || '').trim();

      analysisContext.userStoryId = us?.id || null;
      analysisContext.detail = detail || null;
      analysisContext.analysis = {
        ...analysis,
        qualityScore: score,
        optimizedTitle,
        optimizedDescription,
        optimizedAcceptanceCriteria
      };
      analysisContext.activeTaskId = null;

      if (analysisPanelTitle) {
        analysisPanelTitle.textContent = `${us?.usNumber || `US-${us?.id || '-'}`} 质量分析`;
      }

      if (analysisPanelBody) {
        const issuesHtml = issues.length
          ? issues.map((item, index) => `
              <div class="rounded-lg border border-white/10 bg-white/5 p-3">
                <div class="flex items-center justify-between gap-2">
                  <p class="text-sm text-[#f5f5f5]">${index + 1}. ${R.escapeHtml(item.message || '存在待改进问题')}</p>
                  <div class="flex items-center gap-2 shrink-0">
                    <span class="px-2 py-0.5 rounded text-[11px] bg-white/10 text-[#d4d4d8]">${R.escapeHtml(String(item.type || 'GENERAL').toUpperCase())}</span>
                    <span class="px-2 py-0.5 rounded text-[11px] ${issueSeverityTheme(item.severity)}">${R.escapeHtml(String(item.severity || 'MEDIUM').toUpperCase())}</span>
                  </div>
                </div>
                <p class="text-xs text-[#a1a1aa] mt-1">建议：${R.escapeHtml(item.suggestion || '补充更明确的可测试描述')}</p>
              </div>
            `).join('')
          : '<p class="text-xs text-[#71717a]">未识别到明显质量问题。</p>';

        const validationHtml = validationPoints.length
          ? validationPoints.map((item, index) => `
              <li class="rounded-lg border border-white/10 bg-white/5 p-3">
                <p class="text-sm text-[#e4e4e7]">${index + 1}. ${R.escapeHtml(item.description || '-')}</p>
                <p class="text-xs text-[#a1a1aa] mt-1">期望结果：${R.escapeHtml(item.expectedResult || '-')}</p>
              </li>
            `).join('')
          : '<p class="text-xs text-[#71717a]">暂无验证点建议。</p>';

        const testCaseHtml = suggestedCases.length
          ? suggestedCases.map((item, index) => `
              <li class="rounded-lg border border-white/10 bg-white/5 p-3">
                <p class="text-sm text-[#e4e4e7]">${index + 1}. ${R.escapeHtml(item.title || 'AI 建议用例')}</p>
                <p class="text-xs text-[#a1a1aa] mt-1">${R.escapeHtml(item.description || '-')}</p>
              </li>
            `).join('')
          : '<p class="text-xs text-[#71717a]">暂无测试用例建议。</p>';

        analysisPanelBody.innerHTML = `
          <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div class="flex items-end justify-between gap-4">
              <div>
                <p class="text-xs text-[#a1a1aa]">US 质量评分</p>
                <p class="text-3xl font-semibold ${scoreTheme.tone} leading-none mt-1">${score}<span class="text-base text-[#71717a]"> / 100</span></p>
              </div>
              <p class="text-sm ${scoreTheme.tone}">${scoreTheme.label}</p>
            </div>
            <div class="mt-3 h-2 rounded bg-white/10 overflow-hidden">
              <div class="h-full bg-gradient-to-r ${scoreTheme.bar}" style="width:${score}%"></div>
            </div>
            <p class="text-xs text-[#a1a1aa] mt-3">${R.escapeHtml(summary)}</p>
          </section>

          <section>
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">问题清单</h4>
            <div class="space-y-2">${issuesHtml}</div>
          </section>

          <section>
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">建议改写（将写回详情）</h4>
            <div class="space-y-3">
              <div>
                <p class="text-xs text-[#a1a1aa] mb-1">标题</p>
                <p class="text-sm text-[#f5f5f5] rounded-lg border border-white/10 bg-white/5 px-3 py-2">${R.escapeHtml(optimizedTitle || '-')}</p>
              </div>
              <div>
                <p class="text-xs text-[#a1a1aa] mb-1">描述（As / I want / So that）</p>
                <pre class="text-xs text-[#d4d4d8] whitespace-pre-wrap rounded-lg border border-white/10 bg-white/5 px-3 py-2">${R.escapeHtml(optimizedDescription || '-')}</pre>
              </div>
              <div>
                <p class="text-xs text-[#a1a1aa] mb-1">验收标准（Given / When / Then）</p>
                <pre class="text-xs text-[#d4d4d8] whitespace-pre-wrap rounded-lg border border-white/10 bg-white/5 px-3 py-2">${R.escapeHtml(optimizedAcceptanceCriteria || '-')}</pre>
              </div>
            </div>
          </section>

          <section>
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">验证点建议</h4>
            <ul class="space-y-2">${validationHtml}</ul>
          </section>

          <section>
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">建议测试用例</h4>
            <ul class="space-y-2">${testCaseHtml}</ul>
          </section>
        `;
      }

      if (analysisPanelApplyButton) {
        analysisPanelApplyButton.disabled = !analysisContext.userStoryId;
        analysisPanelApplyButton.classList.toggle('opacity-50', !analysisContext.userStoryId);
        analysisPanelApplyButton.classList.toggle('cursor-not-allowed', !analysisContext.userStoryId);
      }
      if (analysisPanelReanalyzeButton) {
        analysisPanelReanalyzeButton.disabled = !analysisContext.userStoryId;
        analysisPanelReanalyzeButton.classList.toggle('opacity-50', !analysisContext.userStoryId);
        analysisPanelReanalyzeButton.classList.toggle('cursor-not-allowed', !analysisContext.userStoryId);
      }

      panel.classList.remove('hidden');
    }

    async function applyAnalysisWriteback() {
      const id = Number(analysisContext.userStoryId);
      if (!id) {
        R.toast('未找到可写回的 US', 'warning');
        return;
      }

      const us = state.items.find((item) => item.id === id);
      const current = analysisContext.detail && analysisContext.detail.id === id
        ? analysisContext.detail
        : await R.api(`/user-stories/${id}`);

      const analysis = analysisContext.analysis || {};
      const nextTitle = String(analysis.optimizedTitle || current.title || us?.title || '').trim();
      const nextDescription = String(analysis.optimizedDescription || current.description || us?.description || '').trim();
      const nextAcceptanceCriteria = String(analysis.optimizedAcceptanceCriteria || current.acceptanceCriteria || us?.acceptanceCriteria || '').trim();

      if (!nextTitle) {
        R.toast('AI 改写未返回标题，无法写回', 'warning');
        return;
      }

      const confirmTitle = nextTitle.length > 80 ? `${nextTitle.slice(0, 80)}...` : nextTitle;
      const confirmWriteback = await R.confirm({
        title: '写回 AI 建议',
        message: `确认将 AI 建议写回并保存 US ${current.usNumber || id}？标题：${confirmTitle}`,
        confirmText: '确认保存',
        tone: 'primary'
      });
      if (!confirmWriteback) return;

      const updated = await R.api(`/user-stories/${id}`, {
        method: 'PUT',
        body: {
          title: nextTitle,
          description: nextDescription,
          acceptanceCriteria: nextAcceptanceCriteria,
          priority: current.priority || 'MEDIUM',
          status: current.status || 'DRAFT',
          sprint: current.sprint || '',
          epic: current.epic || '',
          storyPoints: current.storyPoints || ''
        }
      });

      state.expandedStoryId = id;
      state.expandedStoryDetail = updated;
      state.items = state.items.map((item) => (item.id === updated.id ? { ...item, ...updated } : item));
      analysisContext.detail = updated;
      renderRows(state.items);
      closeAnalysisPanel();
      R.toast('AI 建议已写回并保存到 US 详情', 'success');
    }

    function buildListQuery() {
      const params = new URLSearchParams();
      params.set('page', String(state.page));
      params.set('size', String(state.size));
      if (state.keyword) params.set('keyword', state.keyword);
      if (state.status) params.set('status', state.status);
      if (state.sprint) params.set('sprint', state.sprint);
      return params.toString();
    }

    async function refreshCaseGenerationStatuses(items) {
      const list = Array.isArray(items) ? items : [];
      if (!list.length) return;

      const snapshots = await Promise.all(list.map(async (us) => {
        try {
          const snapshot = await fetchLatestCaseGenerationSnapshot(us.id);
          return [us.id, snapshot];
        } catch (_error) {
          return [us.id, null];
        }
      }));

      snapshots.forEach(([id, snapshot]) => {
        if (!snapshot) {
          state.generationMetaByStory.delete(id);
          state.generatingStoryIds.delete(id);
          return;
        }
        state.generationMetaByStory.set(id, snapshot);
        if (snapshot.status === 'RUNNING' || snapshot.status === 'QUEUED') {
          state.generatingStoryIds.add(id);
        } else {
          state.generatingStoryIds.delete(id);
        }
      });
      renderRows(state.items);
    }

    async function loadUserStories(options = {}) {
      if (options.refreshSprints || !state.sprintsLoaded) {
        await loadSprintOptions(Boolean(options.refreshSprints));
      }

      const data = await R.api(`/user-stories?${buildListQuery()}`);
      const page = data && typeof data === 'object' ? data : {};
      const list = unwrapPage(page);

      state.items = list;
      pruneStorySelectionToCurrentPage();
      state.totalElements = Number(page.totalElements ?? list.length) || 0;
      state.totalPages = Number(page.totalPages ?? (state.totalElements ? Math.ceil(state.totalElements / state.size) : 0)) || 0;
      state.page = Number(page.pageNumber ?? state.page) || 0;
      state.first = Boolean(page.first ?? state.page <= 0);
      state.last = Boolean(page.last ?? (state.totalPages === 0 || state.page >= state.totalPages - 1));
      await refreshUserStoryCounters();

      if (state.totalPages === 0 && state.page !== 0) {
        state.page = 0;
      }
      if (state.totalPages > 0 && state.page >= state.totalPages) {
        state.page = Math.max(state.totalPages - 1, 0);
        return loadUserStories(options);
      }

      const visibleIds = new Set(list.map((item) => item.id));
      [...state.generationMetaByStory.keys()].forEach((storyId) => {
        if (!visibleIds.has(storyId)) {
          state.generationMetaByStory.delete(storyId);
          state.generatingStoryIds.delete(storyId);
        }
      });

      renderRows(list);
      renderPagination();
      refreshCaseGenerationStatuses(list).catch(() => {});
    }

    const US_PARSE_TEMPLATE = [
      '标题：',
      '',
      'As ...',
      'I want ...',
      'So that ...',
      '',
      'Given ...',
      'When ...',
      'Then ...'
    ].join('\n');

    function isUsTemplatePlaceholderLine(line) {
      const normalized = String(line || '').trim();
      if (!normalized) return true;
      return /^(标题|title)\s*[:：]?\s*(\.{3}|…)?$/i.test(normalized)
        || /^(as|i want|so that|given|when|then)\s*[:：]?\s*(\.{3}|…)?$/i.test(normalized);
    }

    function hasMeaningfulUsParseInput(raw) {
      const lines = String(raw || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      if (!lines.length) return false;
      return lines.some((line) => !isUsTemplatePlaceholderLine(line));
    }

    function parseUsDraftFromText(raw) {
      const lines = String(raw || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);

      let title = '';
      let mode = 'description';
      const descriptionLines = [];
      const acceptanceLines = [];

      lines.forEach((line) => {
        if (/^(标题|title)\s*[:：]/i.test(line)) {
          title = line.replace(/^(标题|title)\s*[:：]\s*/i, '').trim();
          return;
        }
        if (/^(描述|description)\s*[:：]?$/i.test(line)) {
          mode = 'description';
          return;
        }
        if (/^(验收标准|acceptance\s*criteria)\s*[:：]?$/i.test(line)) {
          mode = 'acceptance';
          return;
        }
        if (/^(given|when|then)\b/i.test(line)) {
          if (!isUsTemplatePlaceholderLine(line)) {
            acceptanceLines.push(line);
          }
          mode = 'acceptance';
          return;
        }
        if (isUsTemplatePlaceholderLine(line)) return;
        if (mode === 'acceptance') {
          acceptanceLines.push(line);
        } else {
          descriptionLines.push(line);
        }
      });

      if (!title) {
        const asLine = descriptionLines.find((line) => /^as\b/i.test(line));
        if (asLine) {
          title = asLine.replace(/^as\b[:：]?\s*/i, '').trim();
        }
      }

      if (!title) {
        const firstMeaningful = [...descriptionLines, ...acceptanceLines, ...lines]
          .map((line) => line.replace(/^(as|i want|so that|given|when|then)\b[:：]?\s*/i, '').trim())
          .find((line) => Boolean(line));
        title = firstMeaningful || '';
      }

      const description = descriptionLines.join('\n').trim() || String(raw || '').trim();
      const acceptanceCriteria = acceptanceLines.join('\n').trim() || description;

      return {
        title: (title || `US ${Date.now()}`).slice(0, 120),
        description,
        acceptanceCriteria
      };
    }

    async function waitUntilStoryNotAnalyzing(id, options = {}) {
      const pollInterval = Math.max(1000, Number(options.pollIntervalMs) || 2000);
      const timeoutMs = Math.max(15000, Number(options.timeoutMs) || 300000);
      const startedAt = Date.now();

      while (Date.now() - startedAt <= timeoutMs) {
        const latest = await R.api(`/user-stories/${id}`);
        const status = normalizeUsStatus(latest?.status);
        if (status !== 'ANALYZING') {
          return latest;
        }
        await new Promise((resolve) => setTimeout(resolve, pollInterval));
      }
      throw new Error('等待分析完成超时，请稍后在列表中继续操作');
    }

    async function triggerAutoGenerationForCreatedStory(story, options = {}) {
      const id = Number(story?.id);
      if (!id) return;

      const autoValidation = Boolean(options.autoValidation);
      const autoCases = Boolean(options.autoCases);
      if (!autoValidation && !autoCases) return;

      const usLabel = story?.usNumber || `US-${id}`;
      let detail = story;
      let analysisDone = false;

      if (autoValidation) {
        try {
          if (!detail || detail.id !== id) {
            detail = await R.api(`/user-stories/${id}`);
          }
          setStoryAnalyzing(id, true);
          const task = await submitAnalyzeTask(id, detail);
          const taskId = String(task?.taskId || '').trim();
          const pollInterval = Number(task?.pollIntervalMs) || 2000;
          R.toast(`${usLabel} 已开始自动生成验证点`, 'info');
          if (taskId) {
            await waitForAnalyzeTask(taskId, { pollIntervalMs: pollInterval, timeoutMs: 300000 });
          } else {
            await waitUntilStoryNotAnalyzing(id, { pollIntervalMs: pollInterval, timeoutMs: 300000 });
          }
          analysisDone = true;
          R.toast(`${usLabel} 验证点生成完成`, 'success');
        } catch (error) {
          R.toast(`${usLabel} 自动生成验证点失败：${error.message || '未知错误'}`, 'error');
        } finally {
          setStoryAnalyzing(id, false);
          detail = await refreshStorySnapshot(id).catch(() => detail);
        }
      }

      if (autoCases) {
        try {
          if (autoValidation && !analysisDone) {
            detail = await waitUntilStoryNotAnalyzing(id, { pollIntervalMs: 2000, timeoutMs: 300000 }).catch(() => detail);
          }
          const task = await submitCaseGenerationTask(id, { count: 3 });
          const pending = normalizeCaseGenerationSnapshot({
            ...task,
            status: task?.status || 'QUEUED'
          });
          setStoryGenerationSnapshot(id, pending);
          R.toast(`${usLabel} 已开始自动生成测试用例`, 'info');
        } catch (error) {
          R.toast(`${usLabel} 自动生成测试用例失败：${error.message || '未知错误'}`, 'error');
        } finally {
          await refreshStorySnapshot(id).catch(() => {});
          fetchLatestCaseGenerationSnapshot(id)
            .then((latest) => setStoryGenerationSnapshot(id, latest))
            .catch(() => {});
        }
      }
    }

    async function createFromParseModal() {
      const textarea = $('#us-parse-content', parseModal) || $('textarea', parseModal);
      const autoValidationCheckbox = $('#us-parse-auto-vp', parseModal);
      const autoCasesCheckbox = $('#us-parse-auto-cases', parseModal);
      const raw = (textarea?.value || '').trim();
      if (!raw || !hasMeaningfulUsParseInput(raw)) {
        R.toast('请填写有效的 US 内容', 'warning');
        return;
      }

      const parsed = parseUsDraftFromText(raw);
      const usNumber = `US-${String(Date.now()).slice(-6)}`;
      const autoValidation = autoValidationCheckbox ? autoValidationCheckbox.checked : true;
      const autoCases = autoCasesCheckbox ? autoCasesCheckbox.checked : true;

      const created = await R.api('/user-stories', {
        method: 'POST',
        body: {
          usNumber,
          title: parsed.title,
          description: parsed.description,
          acceptanceCriteria: parsed.acceptanceCriteria,
          priority: 'MEDIUM',
          sprint: 'Sprint 1',
          epic: 'General',
          storyPoints: '3'
        }
      });

      R.toast(`已创建 ${usNumber}`, 'success');
      parseModal.classList.add('hidden');
      if (textarea) textarea.value = US_PARSE_TEMPLATE;
      state.page = 0;
      await loadUserStories({ refreshSprints: true });

      if (created?.id && (autoValidation || autoCases)) {
        triggerAutoGenerationForCreatedStory(created, { autoValidation, autoCases }).catch((error) => {
          R.toast(error.message || '自动生成任务触发失败', 'error');
        });
      }
    }

    async function waitForAnalyzeTask(taskId, options = {}) {
      const pollInterval = Math.max(1000, Number(options.pollIntervalMs) || 2000);
      const timeoutMs = Math.max(15000, Number(options.timeoutMs) || 300000);
      const startedAt = Date.now();

      while (Date.now() - startedAt <= timeoutMs) {
        const task = await R.api(`/user-stories/analysis-tasks/${encodeURIComponent(taskId)}`);
        const status = String(task?.status || '').toUpperCase();
        if (status === 'SUCCEEDED') {
          if (!task.result) throw new Error('分析任务已完成，但未返回结果');
          return task.result;
        }
        if (status === 'FAILED') {
          throw new Error(task.errorMessage || '分析任务执行失败');
        }
        await new Promise((resolve) => setTimeout(resolve, pollInterval));
      }
      throw new Error('分析超时，请稍后重试');
    }

    function setStoryAnalyzing(id, analyzing) {
      if (analyzing) {
        state.analyzingStoryIds.add(id);
      } else {
        state.analyzingStoryIds.delete(id);
      }
      renderRows(state.items);
    }

    async function refreshStorySnapshot(id) {
      const storyId = Number(id);
      if (!storyId) return null;
      const latest = await R.api(`/user-stories/${storyId}`);
      state.items = state.items.map((item) => (item.id === latest.id ? { ...item, ...latest } : item));
      if (state.expandedStoryId === storyId) {
        state.expandedStoryDetail = latest;
      }
      if (analysisContext.detail && analysisContext.detail.id === storyId) {
        analysisContext.detail = { ...analysisContext.detail, ...latest };
      }
      if (caseGenerationContext.detail && caseGenerationContext.detail.id === storyId) {
        caseGenerationContext.detail = { ...caseGenerationContext.detail, ...latest };
      }
      renderRows(state.items);
      return latest;
    }

    async function fetchLatestAnalysisSnapshot(id) {
      const snapshot = await R.api(`/user-stories/${id}/analysis/latest`);
      const status = String(snapshot?.status || 'NONE').toUpperCase();
      return {
        ...snapshot,
        status,
        taskId: String(snapshot?.taskId || '').trim(),
        pollIntervalMs: Number(snapshot?.pollIntervalMs) || 2000
      };
    }

    async function trackAnalyzeTask(id, us, detail, taskInfo = {}) {
      const taskId = String(taskInfo?.taskId || '').trim();
      if (!taskId) {
        throw new Error('分析任务提交成功但未返回任务ID');
      }

      setStoryAnalyzing(id, true);
      renderAnalysisPendingPanel({ ...us, ...detail }, detail, taskId);
      try {
        const analysis = await waitForAnalyzeTask(taskId, {
          pollIntervalMs: taskInfo?.pollIntervalMs || 2000,
          timeoutMs: 300000
        });
        if (analysisContext.activeTaskId && analysisContext.activeTaskId !== taskId) {
          return null;
        }
        renderAnalysisPanel({ ...us, ...detail }, detail, analysis);
        return analysis;
      } catch (error) {
        renderAnalysisFailurePanel({ ...us, ...detail }, detail, error.message || 'AI 分析失败');
        throw error;
      } finally {
        setStoryAnalyzing(id, false);
        await refreshStorySnapshot(id).catch(() => {});
      }
    }

    async function submitAnalyzeTask(id, detail) {
      return R.api(`/user-stories/${id}/analyze`, {
        method: 'POST',
        body: {
          description: detail.description || '',
          acceptanceCriteria: detail.acceptanceCriteria || ''
        }
      });
    }

    async function analyzeUserStory(id, options = {}) {
      const forceNew = Boolean(options.forceNew);
      const us = state.items.find((item) => item.id === id) || { id };
      const detail = state.expandedStoryId === id && state.expandedStoryDetail?.id === id
        ? state.expandedStoryDetail
        : await R.api(`/user-stories/${id}`);

      try {
        if (!forceNew) {
          const latest = await fetchLatestAnalysisSnapshot(id);
          if (latest.status === 'SUCCEEDED' && latest.result) {
            renderAnalysisPanel({ ...us, ...detail }, detail, latest.result);
            return;
          }
          if ((latest.status === 'RUNNING' || latest.status === 'QUEUED') && latest.taskId) {
            await trackAnalyzeTask(id, us, detail, latest);
            return;
          }
          if (latest.status === 'FAILED') {
            renderAnalysisFailurePanel({ ...us, ...detail }, detail, latest.errorMessage || '上次分析失败，请尝试重新分析');
            return;
          }
        }

        const submitResult = await submitAnalyzeTask(id, detail);
        await refreshStorySnapshot(id).catch(() => {});
        await trackAnalyzeTask(id, us, detail, submitResult);
      } catch (error) {
        if (!analysisPanelNode || analysisPanelNode.classList.contains('hidden')) {
          renderAnalysisFailurePanel({ ...us, ...detail }, detail, error.message || 'AI 分析失败');
        }
        throw error;
      }
    }

    async function reanalyzeCurrentStory() {
      const id = Number(analysisContext.userStoryId);
      if (!id) {
        R.toast('未找到可重新分析的 US', 'warning');
        return;
      }
      await analyzeUserStory(id, { forceNew: true });
    }

    function closeCaseGenerationPanel() {
      if (caseGenerationPanelNode) caseGenerationPanelNode.classList.add('hidden');
      closeCaseGenerationDraftDetailModal();
      caseGenerationContext.activeTaskId = null;
      caseGenerationContext.selectedRecordId = null;
      caseGenerationContext.recordPage = 0;
      caseGenerationContext.recordDraftExpanded = true;
    }

    function normalizeCaseGenerationSnapshot(snapshot) {
      const status = String(snapshot?.status || 'NONE').toUpperCase();
      const taskId = String(snapshot?.taskId || '').trim();
      const pollIntervalMs = Number(snapshot?.pollIntervalMs) || 1500;
      const result = snapshot?.result && typeof snapshot.result === 'object' ? snapshot.result : null;
      const events = Array.isArray(snapshot?.events) ? snapshot.events.filter(Boolean) : [];
      const hasDraft = Boolean(
        snapshot?.hasDraft
        || (result && Array.isArray(result.draftCases) && result.draftCases.length > 0)
      );
      return {
        ...(snapshot || {}),
        status,
        taskId,
        pollIntervalMs,
        result,
        events,
        hasDraft
      };
    }

    function resolveCaseGenerationRecords(snapshot) {
      const normalized = normalizeCaseGenerationSnapshot(snapshot || {});
      const session = normalized.result || {};
      const records = Array.isArray(session.generationRecords)
        ? session.generationRecords.filter((item) => item && Array.isArray(item.draftCases) && item.draftCases.length > 0)
        : [];

      if (records.length) {
        return records.slice().sort((a, b) => {
          const aTime = Date.parse(a?.generatedAt || '') || 0;
          const bTime = Date.parse(b?.generatedAt || '') || 0;
          if (bTime !== aTime) return bTime - aTime;
          const aVersion = Number(a?.version) || 0;
          const bVersion = Number(b?.version) || 0;
          return bVersion - aVersion;
        });
      }
      if (Array.isArray(session.draftCases) && session.draftCases.length > 0) {
        return [{
          recordId: 'GEN-LEGACY',
          version: session.version || 1,
          summary: session.summary || '历史生成记录',
          feedback: '',
          generatedAt: session.updatedAt || normalized.generatedAt,
          conversation: Array.isArray(session.conversation) ? session.conversation : [],
          draftCases: session.draftCases
        }];
      }
      return [];
    }

    function resolveActiveCaseGenerationRecord(snapshot) {
      const records = resolveCaseGenerationRecords(snapshot);
      if (!records.length) return null;
      const selectedRecordId = String(caseGenerationContext.selectedRecordId || '').trim();
      if (selectedRecordId) {
        const matched = records.find((item) => String(item?.recordId || '').trim() === selectedRecordId);
        if (matched) return matched;
      }
      return records[0] || null;
    }

    function resolveCaseGenerationRecordPagination(records) {
      const total = Array.isArray(records) ? records.length : 0;
      const normalizedSize = caseGenerationRecordPageSizeOptions.includes(Number(caseGenerationContext.recordPageSize))
        ? Number(caseGenerationContext.recordPageSize)
        : 5;
      caseGenerationContext.recordPageSize = normalizedSize;

      if (!total) {
        caseGenerationContext.recordPage = 0;
        return {
          total: 0,
          page: 0,
          pageSize: normalizedSize,
          totalPages: 0,
          start: 0,
          end: 0,
          items: []
        };
      }

      let page = Number(caseGenerationContext.recordPage) || 0;
      const totalPages = Math.max(1, Math.ceil(total / normalizedSize));
      page = Math.max(0, Math.min(page, totalPages - 1));

      caseGenerationContext.recordPage = page;
      const start = page * normalizedSize;
      const end = Math.min(start + normalizedSize, total);
      return {
        total,
        page,
        pageSize: normalizedSize,
        totalPages,
        start,
        end,
        items: records.slice(start, end)
      };
    }

    function resolveCurrentCaseGenerationDrafts() {
      const activeRecord = resolveActiveCaseGenerationRecord(caseGenerationContext.latestSnapshot);
      if (activeRecord && Array.isArray(activeRecord.draftCases)) {
        return activeRecord.draftCases.filter(Boolean);
      }
      const snapshot = normalizeCaseGenerationSnapshot(caseGenerationContext.latestSnapshot || {});
      return Array.isArray(snapshot.result?.draftCases) ? snapshot.result.draftCases.filter(Boolean) : [];
    }

    function findCaseGenerationDraftById(draftId) {
      const targetId = String(draftId || '').trim();
      if (!targetId) return null;
      return resolveCurrentCaseGenerationDrafts()
        .find((item) => String(item?.draftId || '').trim() === targetId) || null;
    }

    function closeCaseGenerationDraftDetailModal() {
      if (caseGenerationDraftDetailModalNode) {
        caseGenerationDraftDetailModalNode.classList.add('hidden');
      }
      caseGenerationContext.activeDraftId = null;
    }

    function isSystemGenerationConversationMessage(content) {
      const text = String(content || '').trim();
      if (!text) return true;
      return /^已根据你的反馈重新生成\s*\d+\s*条候选用例草稿/.test(text)
        || /^已生成\s*\d+\s*条候选用例草稿/.test(text);
    }

    function ensureCaseGenerationDraftDetailModal() {
      if (caseGenerationDraftDetailModalNode) return caseGenerationDraftDetailModalNode;

      caseGenerationDraftDetailModalNode = document.createElement('div');
      caseGenerationDraftDetailModalNode.className = 'hidden fixed inset-0 z-[99] bg-black/75 backdrop-blur-sm';
      caseGenerationDraftDetailModalNode.innerHTML = `
        <div class="absolute inset-0 flex items-center justify-center p-4">
          <div class="w-full max-w-4xl max-h-[88vh] overflow-hidden rounded-2xl border border-white/10 bg-[#12121a] shadow-2xl flex flex-col">
            <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
              <h3 id="us-case-draft-detail-title" class="text-base font-semibold text-white">候选用例详情</h3>
              <button id="us-case-draft-detail-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
            </div>
            <div id="us-case-draft-detail-body" class="flex-1 overflow-y-auto p-5 space-y-5"></div>
            <div class="px-5 py-4 border-t border-white/10 flex items-center justify-end gap-2">
              <button id="us-case-draft-detail-cancel" class="px-3 py-1.5 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
              <button id="us-case-draft-detail-adopt" class="px-3 py-1.5 text-sm rounded bg-gradient-to-r from-[#10b981] to-[#059669] hover:opacity-90">采纳当前草稿</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(caseGenerationDraftDetailModalNode);

      caseGenerationDraftDetailModalTitle = $('#us-case-draft-detail-title', caseGenerationDraftDetailModalNode);
      caseGenerationDraftDetailModalBody = $('#us-case-draft-detail-body', caseGenerationDraftDetailModalNode);

      $('#us-case-draft-detail-close', caseGenerationDraftDetailModalNode)?.addEventListener('click', closeCaseGenerationDraftDetailModal);
      $('#us-case-draft-detail-cancel', caseGenerationDraftDetailModalNode)?.addEventListener('click', closeCaseGenerationDraftDetailModal);
      $('#us-case-draft-detail-adopt', caseGenerationDraftDetailModalNode)?.addEventListener('click', () => {
        adoptCurrentDraftFromDetail().catch((error) => R.toast(error.message || '采纳失败', 'error'));
      });
      caseGenerationDraftDetailModalNode.addEventListener('click', (event) => {
        if (event.target === caseGenerationDraftDetailModalNode) {
          closeCaseGenerationDraftDetailModal();
        }
      });

      return caseGenerationDraftDetailModalNode;
    }

    function renderCaseGenerationDraftDetailContent(draft, usLabel) {
      const steps = Array.isArray(draft?.steps) ? draft.steps.filter(Boolean) : [];
      const orderedSteps = steps.slice().sort((a, b) => (Number(a?.stepOrder) || 0) - (Number(b?.stepOrder) || 0));
      const priorityText = CASE_PRIORITY_LABEL[String(draft?.priority || '').toUpperCase()] || String(draft?.priority || '-');
      const typeText = CASE_TYPE_LABEL[String(draft?.testType || '').toUpperCase()] || String(draft?.testType || '-');
      const tagsText = String(draft?.tags || '').trim() || '-';
      const descriptionText = String(draft?.description || '').trim() || '-';
      const preconditionsText = String(draft?.preconditions || '').trim() || '-';

      const stepsHtml = orderedSteps.length
        ? orderedSteps.map((step, index) => {
            const order = Number(step?.stepOrder) || index + 1;
            return `
              <li class="rounded-lg border border-white/10 bg-white/5 p-3">
                <div class="flex items-start justify-between gap-3">
                  <p class="text-xs font-mono text-[#93c5fd]">Step ${order}</p>
                </div>
                <p class="text-sm text-[#f5f5f5] mt-2"><span class="text-[#a1a1aa]">动作：</span>${R.escapeHtml(step?.action || '-')}</p>
                <p class="text-sm text-[#f5f5f5] mt-1"><span class="text-[#a1a1aa]">预期：</span>${R.escapeHtml(step?.expectedResult || '-')}</p>
                <p class="text-sm text-[#f5f5f5] mt-1"><span class="text-[#a1a1aa]">测试数据：</span>${R.escapeHtml(step?.testData || '-')}</p>
              </li>
            `;
          }).join('')
        : '<p class="text-xs text-[#71717a]">暂无步骤明细</p>';

      return `
        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div class="flex flex-wrap items-center gap-2">
            <span class="px-2 py-0.5 rounded text-xs bg-[#0ea5e9]/20 text-[#7dd3fc]">${R.escapeHtml(usLabel || '-')}</span>
            <span class="px-2 py-0.5 rounded text-xs bg-[#7c3aed]/20 text-[#c4b5fd]">${R.escapeHtml(typeText)}</span>
            <span class="px-2 py-0.5 rounded text-xs bg-white/10 text-[#d4d4d8]">${R.escapeHtml(priorityText)}</span>
            <span class="px-2 py-0.5 rounded text-xs bg-[#10b981]/20 text-[#6ee7b7]">草稿ID: ${R.escapeHtml(draft?.draftId || '-')}</span>
          </div>
          <h4 class="text-base font-semibold text-white mt-3">${R.escapeHtml(draft?.title || 'AI 生成草稿')}</h4>
          <p class="text-sm text-[#a1a1aa] mt-2 whitespace-pre-wrap">${R.escapeHtml(descriptionText)}</p>
        </section>

        <section class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h5 class="text-sm font-semibold text-[#e4e4e7] mb-2">前置条件</h5>
            <p class="text-sm text-[#d4d4d8] whitespace-pre-wrap">${R.escapeHtml(preconditionsText)}</p>
          </div>
          <div class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h5 class="text-sm font-semibold text-[#e4e4e7] mb-2">标签</h5>
            <p class="text-sm text-[#d4d4d8] whitespace-pre-wrap">${R.escapeHtml(tagsText)}</p>
          </div>
        </section>

        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <h5 class="text-sm font-semibold text-[#e4e4e7] mb-2">步骤明细</h5>
          <ul class="space-y-2">${stepsHtml}</ul>
        </section>
      `;
    }

    function openCaseGenerationDraftDetail(draftId) {
      const draft = findCaseGenerationDraftById(draftId);
      if (!draft) {
        R.toast('未找到该草稿详情，请刷新后重试', 'warning');
        return;
      }

      const modal = ensureCaseGenerationDraftDetailModal();
      const usLabel = caseGenerationContext.detail?.usNumber
        || caseGenerationContext.latestSnapshot?.userStoryNumber
        || (caseGenerationContext.userStoryId ? `US-${caseGenerationContext.userStoryId}` : '-');

      if (caseGenerationDraftDetailModalTitle) {
        caseGenerationDraftDetailModalTitle.textContent = `${usLabel} 候选用例详情`;
      }
      if (caseGenerationDraftDetailModalBody) {
        caseGenerationDraftDetailModalBody.innerHTML = renderCaseGenerationDraftDetailContent(draft, usLabel);
      }
      caseGenerationContext.activeDraftId = String(draft?.draftId || '').trim();
      const adoptButton = $('#us-case-draft-detail-adopt', caseGenerationDraftDetailModalNode);
      const adopted = new Set(
        Array.isArray(caseGenerationContext.latestSnapshot?.result?.adoptedDraftIds)
          ? caseGenerationContext.latestSnapshot.result.adoptedDraftIds
          : []
      );
      const alreadyAdopted = adopted.has(caseGenerationContext.activeDraftId);
      const currentUsStatus = normalizeUsStatus(
        caseGenerationContext.detail?.status
        || state.items.find((item) => item.id === caseGenerationContext.userStoryId)?.status
      );
      const canAdoptCurrent = currentUsStatus !== 'ARCHIVED' && currentUsStatus !== 'ANALYZING';
      if (adoptButton) {
        const disabled = alreadyAdopted || !canAdoptCurrent;
        adoptButton.disabled = disabled;
        adoptButton.textContent = alreadyAdopted
          ? '该草稿已采纳'
          : (canAdoptCurrent ? '采纳当前草稿' : '当前状态不可采纳');
        adoptButton.classList.toggle('opacity-50', disabled);
        adoptButton.classList.toggle('cursor-not-allowed', disabled);
      }
      modal.classList.remove('hidden');
    }

    async function adoptCurrentDraftFromDetail() {
      const draftId = String(caseGenerationContext.activeDraftId || '').trim();
      if (!draftId) {
        R.toast('未找到可采纳的草稿', 'warning');
        return;
      }
      await adoptCaseGenerationDrafts([draftId], { closeDetailAfterAdopt: true });
    }

    function rerenderCurrentCaseGenerationPanel() {
      const id = Number(caseGenerationContext.userStoryId);
      if (!id) return;
      const us = state.items.find((item) => item.id === id) || { id };
      const detail = caseGenerationContext.detail && caseGenerationContext.detail.id === id
        ? caseGenerationContext.detail
        : us;
      renderCaseGenerationPanel({ ...us, ...detail }, detail, caseGenerationContext.latestSnapshot || {});
    }

    function setStoryGenerationSnapshot(id, snapshot) {
      if (!id) return;
      const normalized = normalizeCaseGenerationSnapshot(snapshot);
      state.generationMetaByStory.set(id, normalized);
      if (normalized.status === 'RUNNING' || normalized.status === 'QUEUED') {
        state.generatingStoryIds.add(id);
      } else {
        state.generatingStoryIds.delete(id);
      }
      renderRows(state.items);
    }

    function ensureCaseGenerationPanel() {
      if (caseGenerationPanelNode) return caseGenerationPanelNode;

      caseGenerationPanelNode = document.createElement('div');
      caseGenerationPanelNode.className = 'hidden fixed inset-0 z-[95] bg-black/70 backdrop-blur-sm';
      caseGenerationPanelNode.innerHTML = `
        <div class="absolute inset-y-0 right-0 w-full max-w-5xl bg-[#12121a] border-l border-white/10 shadow-2xl flex flex-col">
          <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
            <h3 id="us-case-generation-title" class="text-base font-semibold text-white">US 用例生成</h3>
            <button id="us-case-generation-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
          </div>
          <div id="us-case-generation-body" class="flex-1 overflow-y-auto p-5 space-y-5"></div>
          <div class="px-5 py-4 border-t border-white/10 flex items-center justify-end gap-2">
            <button id="us-case-generation-cancel" class="px-3 py-1.5 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
            <button id="us-case-generation-regenerate" class="px-3 py-1.5 text-sm rounded bg-[#0ea5e9]/20 text-[#7dd3fc] hover:bg-[#0ea5e9]/30">重新生成</button>
            <button id="us-case-generation-adopt" class="px-3 py-1.5 text-sm rounded bg-gradient-to-r from-[#10b981] to-[#059669] hover:opacity-90">采纳选中</button>
          </div>
        </div>
      `;
      document.body.appendChild(caseGenerationPanelNode);
      caseGenerationPanelBody = $('#us-case-generation-body', caseGenerationPanelNode);
      caseGenerationPanelTitle = $('#us-case-generation-title', caseGenerationPanelNode);
      caseGenerationPanelAdoptButton = $('#us-case-generation-adopt', caseGenerationPanelNode);
      caseGenerationPanelRegenerateButton = $('#us-case-generation-regenerate', caseGenerationPanelNode);

      $('#us-case-generation-close', caseGenerationPanelNode)?.addEventListener('click', closeCaseGenerationPanel);
      $('#us-case-generation-cancel', caseGenerationPanelNode)?.addEventListener('click', closeCaseGenerationPanel);
      caseGenerationPanelNode.addEventListener('click', (event) => {
        if (event.target === caseGenerationPanelNode) closeCaseGenerationPanel();
      });
      caseGenerationPanelRegenerateButton?.addEventListener('click', () => {
        regenerateCurrentCaseGeneration().catch((error) => R.toast(error.message || '重新生成失败', 'error'));
      });
      caseGenerationPanelAdoptButton?.addEventListener('click', () => {
        adoptCaseGenerationDrafts().catch((error) => R.toast(error.message || '采纳失败', 'error'));
      });
      caseGenerationPanelBody?.addEventListener('change', (event) => {
        const pageSizeSelect = event.target.closest('select[data-action="set-generation-record-page-size"]');
        if (pageSizeSelect) {
          const nextSize = Number(pageSizeSelect.value) || 5;
          caseGenerationContext.recordPageSize = caseGenerationRecordPageSizeOptions.includes(nextSize) ? nextSize : 5;
          caseGenerationContext.recordPage = 0;
          rerenderCurrentCaseGenerationPanel();
          return;
        }

        const input = event.target.closest('input[data-draft-id]');
        if (!input) return;
        const draftId = String(input.dataset.draftId || '').trim();
        if (!draftId) return;
        if (input.checked) {
          caseGenerationContext.selectedDraftIds.add(draftId);
        } else {
          caseGenerationContext.selectedDraftIds.delete(draftId);
        }
        refreshCaseGenerationActionButtons();
      });
      caseGenerationPanelBody?.addEventListener('click', (event) => {
        const prevButton = event.target.closest('button[data-action="generation-record-page-prev"]');
        if (prevButton) {
          if (caseGenerationContext.recordPage > 0) {
            caseGenerationContext.recordPage -= 1;
            rerenderCurrentCaseGenerationPanel();
          }
          return;
        }

        const nextButton = event.target.closest('button[data-action="generation-record-page-next"]');
        if (nextButton) {
          caseGenerationContext.recordPage += 1;
          rerenderCurrentCaseGenerationPanel();
          return;
        }

        const deleteRecordButton = event.target.closest('button[data-action="delete-generation-record"]');
        if (deleteRecordButton) {
          const recordId = String(deleteRecordButton.dataset.recordId || '').trim();
          if (!recordId) return;
          deleteCaseGenerationRecord(recordId).catch((error) => R.toast(error.message || '删除记录失败', 'error'));
          return;
        }

        const toggleDraftsButton = event.target.closest('button[data-action="toggle-generation-record-drafts"]');
        if (toggleDraftsButton) {
          const recordId = String(toggleDraftsButton.dataset.recordId || '').trim();
          if (!recordId) return;
          if (recordId === caseGenerationContext.selectedRecordId) {
            caseGenerationContext.recordDraftExpanded = !caseGenerationContext.recordDraftExpanded;
          } else {
            caseGenerationContext.selectedRecordId = recordId;
            caseGenerationContext.recordDraftExpanded = true;
          }
          rerenderCurrentCaseGenerationPanel();
          return;
        }

        const recordButton = event.target.closest('button[data-action="switch-generation-record"]');
        if (recordButton) {
          const recordId = String(recordButton.dataset.recordId || '').trim();
          if (recordId) {
            caseGenerationContext.selectedRecordId = recordId;
            caseGenerationContext.recordDraftExpanded = true;
            rerenderCurrentCaseGenerationPanel();
          }
          return;
        }

        const recordCard = event.target.closest('[data-action="select-generation-record"]');
        if (recordCard) {
          if (!event.target.closest('button, input, textarea, select, a, label')) {
            const recordId = String(recordCard.dataset.recordId || '').trim();
            if (!recordId) return;
            if (recordId === caseGenerationContext.selectedRecordId) {
              caseGenerationContext.recordDraftExpanded = !caseGenerationContext.recordDraftExpanded;
            } else {
              caseGenerationContext.selectedRecordId = recordId;
              caseGenerationContext.recordDraftExpanded = true;
            }
            rerenderCurrentCaseGenerationPanel();
            return;
          }
        }

        const button = event.target.closest('button[data-action="view-draft-detail"]');
        if (!button) return;
        const draftId = String(button.dataset.draftId || '').trim();
        if (!draftId || button.disabled) return;
        openCaseGenerationDraftDetail(draftId);
      });

      return caseGenerationPanelNode;
    }

    function refreshCaseGenerationActionButtons() {
      const snapshot = normalizeCaseGenerationSnapshot(caseGenerationContext.latestSnapshot || {});
      const status = snapshot.status;
      const running = status === 'RUNNING' || status === 'QUEUED';
      const currentUsStatus = normalizeUsStatus(
        caseGenerationContext.detail?.status
        || state.items.find((item) => item.id === caseGenerationContext.userStoryId)?.status
      );
      const canRegenerate = currentUsStatus !== 'ARCHIVED' && currentUsStatus !== 'ANALYZING';
      const canAdopt = currentUsStatus !== 'ARCHIVED' && currentUsStatus !== 'ANALYZING';
      const drafts = resolveCurrentCaseGenerationDrafts();
      const adopted = new Set(Array.isArray(snapshot.result?.adoptedDraftIds) ? snapshot.result.adoptedDraftIds : []);
      const selectable = drafts
        .map((item) => String(item?.draftId || '').trim())
        .filter((draftId) => draftId && !adopted.has(draftId));
      const hasSelectable = selectable.length > 0;
      const selected = selectable.filter((draftId) => caseGenerationContext.selectedDraftIds.has(draftId));

      if (caseGenerationPanelRegenerateButton) {
        const disabled = running || !caseGenerationContext.userStoryId || !canRegenerate;
        caseGenerationPanelRegenerateButton.disabled = disabled;
        caseGenerationPanelRegenerateButton.classList.toggle('opacity-50', disabled);
        caseGenerationPanelRegenerateButton.classList.toggle('cursor-not-allowed', disabled);
        caseGenerationPanelRegenerateButton.title = disabled
          ? (running ? '生成任务进行中，请稍后重试' : (!canRegenerate ? '当前状态不可重新生成' : '未找到可操作的 US'))
          : '';
      }

      if (caseGenerationPanelAdoptButton) {
        const disabled = running || selected.length === 0 || !canAdopt;
        caseGenerationPanelAdoptButton.disabled = disabled;
        caseGenerationPanelAdoptButton.classList.toggle('opacity-50', disabled);
        caseGenerationPanelAdoptButton.classList.toggle('cursor-not-allowed', disabled);
        caseGenerationPanelAdoptButton.title = disabled
          ? (
              running
                ? '生成任务进行中，请稍后采纳'
                : (!canAdopt
                    ? '当前状态不可采纳'
                    : (!hasSelectable
                        ? '当前记录草稿已全部采纳，可点击“重新生成”获取新草稿'
                        : '请先勾选要采纳的草稿'))
            )
          : '';
      }
    }

    function renderCaseGenerationEvents(events) {
      const list = Array.isArray(events) ? events.filter(Boolean) : [];
      if (!list.length) {
        return '<p class="text-xs text-[#71717a]">暂无过程日志</p>';
      }
      return `
        <ul class="space-y-2">
          ${list.slice(-12).map((item) => `
            <li class="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
              <p class="text-xs text-[#93c5fd]">${R.escapeHtml(String(item.stage || '-').toUpperCase())}</p>
              <p class="text-sm text-[#e4e4e7] mt-1">${R.escapeHtml(item.message || '-')}</p>
              <p class="text-[11px] text-[#71717a] mt-1">${R.escapeHtml(R.formatDateTime(item.occurredAt))}</p>
            </li>
          `).join('')}
        </ul>
      `;
    }

    function bindCaseGenerationFeedbackAction() {
      const sendButton = $('#us-case-feedback-send', caseGenerationPanelBody);
      sendButton?.addEventListener('click', () => {
        submitCaseGenerationFeedback().catch((error) => R.toast(error.message || '发送失败', 'error'));
      });
    }

    function renderCaseGenerationPendingPanel(us, detail, snapshot) {
      const panel = ensureCaseGenerationPanel();
      closeCaseGenerationDraftDetailModal();
      const normalized = normalizeCaseGenerationSnapshot(snapshot);
      caseGenerationContext.userStoryId = us?.id || null;
      caseGenerationContext.detail = detail || null;
      caseGenerationContext.activeTaskId = normalized.taskId || null;
      caseGenerationContext.latestSnapshot = normalized;
      caseGenerationContext.selectedRecordId = null;
      caseGenerationContext.recordPage = 0;
      caseGenerationContext.recordDraftExpanded = true;
      caseGenerationContext.selectedDraftIds.clear();

      if (caseGenerationPanelTitle) {
        caseGenerationPanelTitle.textContent = `${us?.usNumber || `US-${us?.id || '-'}`} 用例生成`;
      }
      if (caseGenerationPanelBody) {
        caseGenerationPanelBody.innerHTML = `
          <section class="rounded-xl border border-[#10b981]/30 bg-[#10b981]/10 p-4">
            <p class="text-sm text-[#6ee7b7]">kun dark 正在生成测试用例，请稍候...</p>
            <p class="text-xs text-[#a7f3d0] mt-2">你可以留在该面板查看过程日志，也可以先离开，稍后再次点击“生成中...”继续查看。</p>
            ${normalized.taskId ? `<p class="text-[11px] text-[#6ee7b7] mt-3 font-mono">任务ID: ${R.escapeHtml(normalized.taskId)}</p>` : ''}
          </section>
          <section>
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">生成过程</h4>
            ${renderCaseGenerationEvents(normalized.events)}
          </section>
          <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">历史记录</h4>
            <p class="text-xs text-[#71717a]">当前任务执行中，完成后可继续自然语言修复并二次生成。</p>
          </section>
        `;
      }
      refreshCaseGenerationActionButtons();
      panel.classList.remove('hidden');
    }

    function renderCaseGenerationFailurePanel(us, detail, snapshot, message) {
      const panel = ensureCaseGenerationPanel();
      closeCaseGenerationDraftDetailModal();
      const normalized = normalizeCaseGenerationSnapshot({
        ...(snapshot || {}),
        status: 'FAILED',
        errorMessage: message || snapshot?.errorMessage || '用例生成失败'
      });
      caseGenerationContext.userStoryId = us?.id || null;
      caseGenerationContext.detail = detail || null;
      caseGenerationContext.activeTaskId = null;
      caseGenerationContext.latestSnapshot = normalized;
      caseGenerationContext.selectedRecordId = null;
      caseGenerationContext.recordPage = 0;
      caseGenerationContext.recordDraftExpanded = true;
      caseGenerationContext.selectedDraftIds.clear();

      if (caseGenerationPanelTitle) {
        caseGenerationPanelTitle.textContent = `${us?.usNumber || `US-${us?.id || '-'}`} 用例生成`;
      }
      if (caseGenerationPanelBody) {
        caseGenerationPanelBody.innerHTML = `
          <section class="rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-4">
            <p class="text-sm text-[#fecaca]">生成失败</p>
            <p class="text-xs text-[#fecaca] mt-2">${R.escapeHtml(normalized.errorMessage || '模型调用失败，请稍后重试')}</p>
          </section>
          <section>
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">过程日志</h4>
            ${renderCaseGenerationEvents(normalized.events)}
          </section>
          <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">修复建议</h4>
            <textarea id="us-case-feedback-input" rows="3" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#10b981] resize-y" placeholder="例如：请补充边界值、异常分支、接口鉴权失败场景..."></textarea>
            <div class="flex justify-end mt-3">
              <button id="us-case-feedback-send" class="px-3 py-1.5 text-xs rounded bg-[#10b981]/20 text-[#6ee7b7] hover:bg-[#10b981]/30">二次优化</button>
            </div>
          </section>
        `;
        bindCaseGenerationFeedbackAction();
      }
      refreshCaseGenerationActionButtons();
      panel.classList.remove('hidden');
    }

    function renderCaseGenerationPanel(us, detail, snapshot) {
      const panel = ensureCaseGenerationPanel();
      const normalized = normalizeCaseGenerationSnapshot(snapshot);
      const session = normalized.result || {};
      const adopted = new Set(Array.isArray(session.adoptedDraftIds) ? session.adoptedDraftIds : []);
      const generationRecords = resolveCaseGenerationRecords(normalized);

      caseGenerationContext.userStoryId = us?.id || null;
      caseGenerationContext.detail = detail || null;
      caseGenerationContext.activeTaskId = null;
      caseGenerationContext.latestSnapshot = normalized;
      let activeRecord = resolveActiveCaseGenerationRecord(normalized);
      if (activeRecord) {
        const nextRecordId = String(activeRecord.recordId || '').trim();
        if (nextRecordId && nextRecordId !== caseGenerationContext.selectedRecordId) {
          caseGenerationContext.recordDraftExpanded = true;
        }
        caseGenerationContext.selectedRecordId = nextRecordId || caseGenerationContext.selectedRecordId;
      }
      activeRecord = resolveActiveCaseGenerationRecord(normalized);

      const drafts = Array.isArray(activeRecord?.draftCases)
        ? activeRecord.draftCases.filter(Boolean)
        : (Array.isArray(session.draftCases) ? session.draftCases.filter(Boolean) : []);

      const selectableIds = drafts
        .map((item) => String(item?.draftId || '').trim())
        .filter((draftId) => draftId && !adopted.has(draftId));
      const activeRecordAllAdopted = drafts.length > 0 && selectableIds.length === 0;
      const retained = new Set([...caseGenerationContext.selectedDraftIds].filter((draftId) => selectableIds.includes(draftId)));
      if (!retained.size) {
        selectableIds.forEach((draftId) => retained.add(draftId));
      }
      caseGenerationContext.selectedDraftIds = retained;

      if (caseGenerationPanelTitle) {
        caseGenerationPanelTitle.textContent = `${us?.usNumber || `US-${us?.id || '-'}`} 用例生成`;
      }
      if (caseGenerationPanelBody) {
        const renderDraftRows = (recordDrafts = []) => {
          const list = Array.isArray(recordDrafts) ? recordDrafts.filter(Boolean) : [];
          if (!list.length) {
            return `
              <li class="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-[#71717a]">
                当前记录暂无可用草稿
              </li>
            `;
          }
          return list.map((item, index) => {
            const draftId = String(item?.draftId || '').trim();
            const disabled = adopted.has(draftId);
            const checked = !disabled && caseGenerationContext.selectedDraftIds.has(draftId);
            const steps = Array.isArray(item?.steps) ? item.steps : [];
            const detailDisabled = !draftId;
            return `
              <li class="rounded-lg border border-white/10 bg-white/5 p-3">
                <div class="flex items-start justify-between gap-3">
                  <label class="flex items-start gap-2 min-w-0">
                    <input type="checkbox" data-draft-id="${R.escapeHtml(draftId)}" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''} class="mt-1 rounded border-white/20 bg-white/5">
                    <div class="min-w-0">
                      <p class="text-sm text-[#f5f5f5]">${index + 1}. ${R.escapeHtml(item?.title || 'AI 生成草稿')}</p>
                      <p class="text-xs text-[#a1a1aa] mt-1">${R.escapeHtml(item?.description || '-')}</p>
                      <p class="text-[11px] text-[#71717a] mt-1">步骤数: ${steps.length} | 优先级: ${R.escapeHtml(item?.priority || 'MEDIUM')} | 类型: ${R.escapeHtml(item?.testType || 'FUNCTIONAL')}</p>
                    </div>
                  </label>
                  <div class="shrink-0 flex items-center gap-2">
                    <button
                      data-action="view-draft-detail"
                      data-draft-id="${R.escapeHtml(draftId)}"
                      ${detailDisabled ? 'disabled' : ''}
                      class="px-2 py-1 text-xs rounded bg-white/10 text-[#d1d5db] hover:bg-white/20 ${detailDisabled ? 'opacity-50 cursor-not-allowed hover:bg-white/10' : ''}"
                    >查看详情</button>
                    ${disabled ? '<span class="px-2 py-0.5 rounded text-[11px] bg-[#10b981]/20 text-[#6ee7b7]">已采纳</span>' : ''}
                  </div>
                </div>
              </li>
            `;
          }).join('');
        };

        const messagesSource = Array.isArray(activeRecord?.conversation) && activeRecord.conversation.length
          ? activeRecord.conversation
          : (Array.isArray(session.conversation) ? session.conversation : []);
        const messages = messagesSource
          .filter(Boolean)
          .filter((msg) => !isSystemGenerationConversationMessage(msg?.content));
        const messagesHtml = messages.length
          ? messages.map((msg) => {
              const role = String(msg.role || 'assistant').toLowerCase();
              const roleLabel = role === 'user' ? '你' : 'kun dark';
              const bubbleClass = role === 'user'
                ? 'bg-[#0ea5e9]/20 text-[#bae6fd]'
                : 'bg-white/10 text-[#e4e4e7]';
              return `
                <div class="rounded-lg ${bubbleClass} px-3 py-2">
                  <p class="text-[11px] opacity-80 mb-1">${R.escapeHtml(roleLabel)}</p>
                  <p class="text-xs whitespace-pre-wrap">${R.escapeHtml(msg.content || '')}</p>
                </div>
              `;
            }).join('')
          : '<p class="text-xs text-[#71717a]">暂无对话记录。</p>';

        const activeVersion = Number(activeRecord?.version || session.version || 1) || 1;
        const activeUpdatedAt = activeRecord?.generatedAt || session.updatedAt || normalized.generatedAt;
        const activeSummary = String(activeRecord?.summary || session.summary || '用例草稿生成完成').trim();
        const activeFeedback = String(activeRecord?.feedback || '').trim();
        const activeRecordId = String(activeRecord?.recordId || '').trim();
        const activeRecordLabel = activeRecordId
          ? `当前记录：v${activeVersion}（${R.escapeHtml(activeRecordId)}）`
          : `当前记录：v${activeVersion}`;
        const recordPager = resolveCaseGenerationRecordPagination(generationRecords);
        const recordsHtml = recordPager.items.length
          ? recordPager.items.map((record, index) => {
              const recordId = String(record?.recordId || '').trim();
              const isActive = recordId && recordId === caseGenerationContext.selectedRecordId;
              const isExpanded = isActive && caseGenerationContext.recordDraftExpanded;
              const versionText = Number(record?.version || (recordPager.start + index + 1)) || (recordPager.start + index + 1);
              const generatedAtText = R.formatDateTime(record?.generatedAt || session.updatedAt || normalized.generatedAt);
              const recordSummary = String(record?.summary || `第 ${versionText} 轮生成`).trim();
              const feedbackText = String(record?.feedback || '').trim();
              const recordDrafts = Array.isArray(record?.draftCases) ? record.draftCases.filter(Boolean) : [];
              const toggleButtonLabel = isExpanded ? '收起用例' : '查看用例';
              return `
                <div data-action="select-generation-record" data-record-id="${R.escapeHtml(recordId)}" class="rounded-lg border px-3 py-3 cursor-pointer transition ${isActive ? 'border-[#0ea5e9]/60 bg-[#0ea5e9]/15' : 'border-white/10 bg-white/5 hover:bg-white/10'}">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <p class="text-xs ${isActive ? 'text-[#7dd3fc]' : 'text-[#a1a1aa]'}">v${R.escapeHtml(String(versionText))} · ${R.escapeHtml(generatedAtText)}</p>
                      <p class="text-sm mt-1 ${isActive ? 'text-[#e0f2fe]' : 'text-[#e4e4e7]'}">${R.escapeHtml(recordSummary)}</p>
                      ${feedbackText ? `<p class="text-xs mt-2 text-[#93c5fd]">修复意见：${R.escapeHtml(feedbackText)}</p>` : ''}
                    </div>
                    ${isActive ? '<span class="px-2 py-0.5 rounded text-[11px] bg-[#0ea5e9]/25 text-[#7dd3fc]">当前</span>' : ''}
                  </div>
                  <div class="mt-3 flex flex-wrap gap-2">
                    <button data-action="toggle-generation-record-drafts" data-record-id="${R.escapeHtml(recordId)}" class="px-2.5 py-1 text-xs rounded bg-white/10 text-[#d1d5db] hover:bg-white/20">${toggleButtonLabel}</button>
                    <button data-action="delete-generation-record" data-record-id="${R.escapeHtml(recordId)}" class="px-2.5 py-1 text-xs rounded bg-[#ef4444]/20 text-[#fca5a5] hover:bg-[#ef4444]/30">删除记录</button>
                  </div>
                  ${isExpanded ? `
                    <div class="mt-3 pt-3 border-t border-white/10">
                      <p class="text-xs text-[#a1a1aa] mb-2">关联候选用例（${recordDrafts.length}）</p>
                      <ul class="space-y-2">${renderDraftRows(recordDrafts)}</ul>
                    </div>
                  ` : ''}
                </div>
              `;
            }).join('')
          : '<p class="text-xs text-[#71717a]">暂无历史记录</p>';
        const recordPageSummary = recordPager.total
          ? `共 ${recordPager.total} 条记录，显示 ${recordPager.start + 1}-${recordPager.end}`
          : '共 0 条记录，显示 0-0';
        const recordPageInfo = recordPager.totalPages
          ? `${recordPager.page + 1} / ${recordPager.totalPages}`
          : '0 / 0';
        const recordPageSizeOptionsHtml = caseGenerationRecordPageSizeOptions.map((size) => (
          `<option value="${size}" ${recordPager.pageSize === size ? 'selected' : ''}>${size}</option>`
        )).join('');

        caseGenerationPanelBody.innerHTML = `
          <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div class="flex items-center justify-between gap-3">
              <p class="text-sm text-[#e4e4e7]">${R.escapeHtml(activeSummary || '用例草稿生成完成')}</p>
              <span class="text-[11px] text-[#71717a]">版本 v${R.escapeHtml(String(activeVersion))}</span>
            </div>
            <p class="text-xs text-[#71717a] mt-2">更新时间：${R.escapeHtml(R.formatDateTime(activeUpdatedAt))}</p>
            <p class="text-xs text-[#71717a] mt-1">${activeRecordLabel}</p>
            ${activeFeedback ? `<p class="text-xs text-[#93c5fd] mt-2">本轮修复意见：${R.escapeHtml(activeFeedback)}</p>` : ''}
          </section>

          <section>
            <h4 class="text-sm font-semibold text-[#e4e4e7] mb-2">生成过程</h4>
            ${renderCaseGenerationEvents(normalized.events)}
          </section>

          <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
              <h4 class="text-sm font-semibold text-[#e4e4e7]">历史记录</h4>
              <span class="text-[11px] text-[#71717a]">点击记录即可选中并展开当次用例，支持收起与删除</span>
            </div>
            <div class="space-y-2">${recordsHtml}</div>
            ${activeRecordAllAdopted ? `
              <p class="mt-3 text-xs text-[#fbbf24] bg-[#f59e0b]/10 border border-[#f59e0b]/30 rounded px-3 py-2">
                当前记录的候选草稿已全部采纳，可点击右下角“重新生成”获取新草稿。
              </p>
            ` : ''}
            <div class="mt-3 flex flex-wrap items-center justify-between gap-2">
              <p class="text-[11px] text-[#71717a]">${R.escapeHtml(recordPageSummary)}</p>
              <div class="flex flex-wrap items-center gap-2">
                <label class="flex items-center gap-2 text-[11px] text-[#a1a1aa]">
                  <span>每页</span>
                  <select data-action="set-generation-record-page-size" class="px-2 py-1 bg-white/5 border border-white/10 rounded text-[11px] focus:outline-none focus:border-[#10b981]">
                    ${recordPageSizeOptionsHtml}
                  </select>
                </label>
                <button data-action="generation-record-page-prev" ${recordPager.page <= 0 ? 'disabled' : ''} class="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-[11px] disabled:opacity-50 disabled:cursor-not-allowed">上一页</button>
                <span class="text-[11px] text-[#d4d4d8] min-w-[64px] text-center">${R.escapeHtml(recordPageInfo)}</span>
                <button data-action="generation-record-page-next" ${!recordPager.totalPages || recordPager.page >= (recordPager.totalPages - 1) ? 'disabled' : ''} class="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-[11px] disabled:opacity-50 disabled:cursor-not-allowed">下一页</button>
              </div>
            </div>
            <div class="mt-4">
              <div class="space-y-2">${messagesHtml}</div>
            </div>
            <textarea id="us-case-feedback-input" rows="3" class="w-full mt-3 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#10b981] resize-y" placeholder="例如：请把步骤拆得更细，并补充接口异常码 401/403 的验证"></textarea>
            <div class="flex justify-end mt-3">
              <button id="us-case-feedback-send" class="px-3 py-1.5 text-xs rounded bg-[#10b981]/20 text-[#6ee7b7] hover:bg-[#10b981]/30">二次优化</button>
            </div>
          </section>
        `;
        bindCaseGenerationFeedbackAction();
      }

      refreshCaseGenerationActionButtons();
      panel.classList.remove('hidden');
    }

    async function fetchLatestCaseGenerationSnapshot(id) {
      const snapshot = await R.api(`/user-stories/${id}/case-generation/latest`);
      return normalizeCaseGenerationSnapshot(snapshot);
    }

    async function waitForCaseGenerationTask(taskId, options = {}) {
      const pollInterval = Math.max(1000, Number(options.pollIntervalMs) || 1500);
      const timeoutMs = Math.max(15000, Number(options.timeoutMs) || 300000);
      const startedAt = Date.now();

      while (Date.now() - startedAt <= timeoutMs) {
        const task = await R.api(`/user-stories/case-generation-tasks/${encodeURIComponent(taskId)}`);
        const normalized = normalizeCaseGenerationSnapshot(task);
        if (typeof options.onProgress === 'function') {
          options.onProgress(normalized);
        }
        if (normalized.status === 'SUCCEEDED') {
          return normalized;
        }
        if (normalized.status === 'FAILED') {
          throw new Error(normalized.errorMessage || '用例生成任务执行失败');
        }
        await new Promise((resolve) => setTimeout(resolve, pollInterval));
      }
      throw new Error('用例生成超时，请稍后重试');
    }

    async function trackCaseGenerationTask(id, us, detail, taskInfo = {}) {
      const taskId = String(taskInfo?.taskId || '').trim();
      if (!taskId) {
        throw new Error('用例生成任务提交成功但未返回任务ID');
      }

      if (state.trackingGenerationTasks.has(taskId)) {
        const existing = state.trackingGenerationTasks.get(taskId);
        const pending = normalizeCaseGenerationSnapshot({
          ...taskInfo,
          status: taskInfo?.status || 'RUNNING',
          taskId
        });
        renderCaseGenerationPendingPanel({ ...us, ...detail }, detail, pending);
        return existing;
      }

      const pendingSnapshot = normalizeCaseGenerationSnapshot({
        ...taskInfo,
        status: taskInfo?.status || 'RUNNING',
        taskId
      });
      setStoryGenerationSnapshot(id, pendingSnapshot);
      renderCaseGenerationPendingPanel({ ...us, ...detail }, detail, pendingSnapshot);

      const trackingPromise = (async () => {
        try {
          const taskResult = await waitForCaseGenerationTask(taskId, {
            pollIntervalMs: pendingSnapshot.pollIntervalMs || 1500,
            timeoutMs: 300000,
            onProgress: (progress) => {
              setStoryGenerationSnapshot(id, progress);
              if (caseGenerationContext.activeTaskId !== taskId) return;
              if (!caseGenerationPanelNode || caseGenerationPanelNode.classList.contains('hidden')) return;
              renderCaseGenerationPendingPanel({ ...us, ...detail }, detail, progress);
            }
          });

          if (caseGenerationContext.activeTaskId !== taskId) {
            return taskResult;
          }
          if (!caseGenerationPanelNode || caseGenerationPanelNode.classList.contains('hidden')) {
            return taskResult;
          }

          const latest = await fetchLatestCaseGenerationSnapshot(id).catch(() => taskResult);
          setStoryGenerationSnapshot(id, latest);
          renderCaseGenerationPanel({ ...us, ...detail }, detail, latest);
          await refreshStorySnapshot(id).catch(() => {});
          return latest;
        } catch (error) {
          const failedSnapshot = await fetchLatestCaseGenerationSnapshot(id).catch(() => normalizeCaseGenerationSnapshot({
            ...pendingSnapshot,
            status: 'FAILED',
            errorMessage: error.message || '用例生成失败'
          }));
          setStoryGenerationSnapshot(id, failedSnapshot);
          await refreshStorySnapshot(id).catch(() => {});
          if (caseGenerationContext.activeTaskId === taskId && caseGenerationPanelNode && !caseGenerationPanelNode.classList.contains('hidden')) {
            renderCaseGenerationFailurePanel({ ...us, ...detail }, detail, failedSnapshot, error.message || failedSnapshot.errorMessage);
          }
          throw error;
        } finally {
          state.trackingGenerationTasks.delete(taskId);
        }
      })();

      state.trackingGenerationTasks.set(taskId, trackingPromise);
      return trackingPromise;
    }

    function submitCaseGenerationTask(id, payload = {}) {
      return R.api(`/user-stories/${id}/generate-test-cases`, {
        method: 'POST',
        body: {
          count: Number(payload.count) || 3,
          feedback: payload.feedback || ''
        }
      });
    }

    function submitCaseGenerationRefine(id, feedback, count = 3) {
      return R.api(`/user-stories/${id}/case-generation/refine`, {
        method: 'POST',
        body: {
          count,
          feedback
        }
      });
    }

    async function openCaseGenerationPanel(id, options = {}) {
      const forceNew = Boolean(options.forceNew);
      const us = state.items.find((item) => item.id === id) || { id };
      const detail = state.expandedStoryId === id && state.expandedStoryDetail?.id === id
        ? state.expandedStoryDetail
        : await R.api(`/user-stories/${id}`);

      if (!forceNew) {
        const latest = await fetchLatestCaseGenerationSnapshot(id);
        setStoryGenerationSnapshot(id, latest);

        if (latest.status === 'SUCCEEDED' && latest.result) {
          renderCaseGenerationPanel({ ...us, ...detail }, detail, latest);
          return latest;
        }
        if ((latest.status === 'RUNNING' || latest.status === 'QUEUED') && latest.taskId) {
          return trackCaseGenerationTask(id, us, detail, latest);
        }
        if (latest.status === 'FAILED') {
          renderCaseGenerationFailurePanel({ ...us, ...detail }, detail, latest, latest.errorMessage || '上次生成失败，请重新生成');
          return latest;
        }
      }

      const submitted = await submitCaseGenerationTask(id, { count: Number(options.count) || 3 });
      return trackCaseGenerationTask(id, us, detail, submitted);
    }

    async function regenerateCurrentCaseGeneration() {
      const id = Number(caseGenerationContext.userStoryId);
      if (!id) {
        R.toast('未找到可重新生成的 US', 'warning');
        return;
      }
      await openCaseGenerationPanel(id, { forceNew: true, count: 3 });
    }

    async function submitCaseGenerationFeedback() {
      const id = Number(caseGenerationContext.userStoryId);
      if (!id) {
        R.toast('未找到可对话的 US', 'warning');
        return;
      }
      const input = $('#us-case-feedback-input', caseGenerationPanelBody);
      const feedback = String(input?.value || '').trim();
      if (!feedback) {
        R.toast('请输入修复意见', 'warning');
        return;
      }

      const us = state.items.find((item) => item.id === id) || { id };
      const detail = caseGenerationContext.detail && caseGenerationContext.detail.id === id
        ? caseGenerationContext.detail
        : await R.api(`/user-stories/${id}`);

      const task = await submitCaseGenerationRefine(id, feedback, 3);
      if (input) input.value = '';
      await trackCaseGenerationTask(id, us, detail, task);
    }

    async function deleteCaseGenerationRecord(recordId) {
      const id = Number(caseGenerationContext.userStoryId);
      if (!id) {
        R.toast('未找到可操作的 US', 'warning');
        return;
      }
      const normalizedRecordId = String(recordId || '').trim();
      if (!normalizedRecordId) {
        R.toast('记录ID无效', 'warning');
        return;
      }
      const confirmed = await R.confirm({
        title: '删除生成记录',
        message: '确认删除该条历史记录？删除后不可恢复。',
        confirmText: '确认删除',
        tone: 'danger'
      });
      if (!confirmed) return;

      const updatedSession = await R.api(`/user-stories/${id}/case-generation/records/${encodeURIComponent(normalizedRecordId)}`, {
        method: 'DELETE'
      });
      R.toast('记录已删除', 'success');
      closeCaseGenerationDraftDetailModal();

      const immediateSnapshot = normalizeCaseGenerationSnapshot({
        status: 'SUCCEEDED',
        result: updatedSession || null,
        generatedAt: updatedSession?.updatedAt || new Date().toISOString(),
        hasDraft: Array.isArray(updatedSession?.draftCases) && updatedSession.draftCases.length > 0,
        events: []
      });
      setStoryGenerationSnapshot(id, immediateSnapshot);
      caseGenerationContext.latestSnapshot = immediateSnapshot;
      rerenderCurrentCaseGenerationPanel();

      fetchLatestCaseGenerationSnapshot(id).then((latest) => {
        setStoryGenerationSnapshot(id, latest);
        caseGenerationContext.latestSnapshot = latest;
        rerenderCurrentCaseGenerationPanel();
      }).catch(() => {
        // ignore refresh failure, immediate snapshot already applied
      });
    }

    async function adoptCaseGenerationDrafts(overrideDraftIds = null, options = {}) {
      const id = Number(caseGenerationContext.userStoryId);
      if (!id) {
        R.toast('未找到可采纳的 US', 'warning');
        return;
      }
      const selectedDraftIds = Array.isArray(overrideDraftIds) && overrideDraftIds.length
        ? [...new Set(overrideDraftIds.map((item) => String(item || '').trim()).filter(Boolean))]
        : [...caseGenerationContext.selectedDraftIds];
      if (!selectedDraftIds.length) {
        R.toast('请先勾选要采纳的草稿', 'warning');
        return;
      }

      const created = await R.api(`/user-stories/${id}/case-generation/adopt`, {
        method: 'POST',
        body: { draftIds: selectedDraftIds }
      });
      R.toast(`已采纳并创建 ${Array.isArray(created) ? created.length : 0} 条测试用例`, 'success');

      const latest = await fetchLatestCaseGenerationSnapshot(id);
      setStoryGenerationSnapshot(id, latest);
      const us = state.items.find((item) => item.id === id) || { id };
      const detail = caseGenerationContext.detail && caseGenerationContext.detail.id === id
        ? caseGenerationContext.detail
        : await R.api(`/user-stories/${id}`);
      renderCaseGenerationPanel({ ...us, ...detail }, detail, latest);
      await loadUserStories();
      if (options.closeDetailAfterAdopt) {
        closeCaseGenerationDraftDetailModal();
      }
    }

    async function generateCases(id) {
      await openCaseGenerationPanel(id);
    }

    async function toggleUsDetail(id) {
      if (state.expandedStoryId === id) {
        state.expandedStoryId = null;
        state.expandedStoryDetail = null;
        renderRows(state.items);
        return;
      }

      state.expandedStoryId = id;
      state.expandedStoryDetail = await R.api(`/user-stories/${id}`);
      renderRows(state.items);
    }

    async function saveUsDetail(id, detailRow) {
      if (!detailRow) return;
      const current = state.expandedStoryDetail && state.expandedStoryDetail.id === id
        ? state.expandedStoryDetail
        : await R.api(`/user-stories/${id}`);
      const titleInput = $('[data-field="title"]', detailRow);
      const descriptionInput = $('[data-field="description"]', detailRow);
      const acceptanceInput = $('[data-field="acceptanceCriteria"]', detailRow);

      const title = String(titleInput?.value || '').trim();
      const description = String(descriptionInput?.value || '').trim();
      const acceptanceCriteria = String(acceptanceInput?.value || '').trim();
      if (!title) {
        R.toast('标题不能为空', 'warning');
        return;
      }

      const confirmTitle = title.length > 80 ? `${title.slice(0, 80)}...` : title;
      const confirmSave = await R.confirm({
        title: '保存 US 详情',
        message: `确认保存 US ${current.usNumber || id} 的详情修改？标题：${confirmTitle}`,
        confirmText: '确认保存',
        tone: 'primary'
      });
      if (!confirmSave) return;

      const updated = await R.api(`/user-stories/${id}`, {
        method: 'PUT',
        body: {
          title,
          description,
          acceptanceCriteria,
          priority: current.priority || 'MEDIUM',
          status: current.status || 'DRAFT',
          sprint: current.sprint || '',
          epic: current.epic || '',
          storyPoints: current.storyPoints || ''
        }
      });

      state.expandedStoryDetail = updated;
      state.items = state.items.map((item) => (item.id === updated.id ? { ...item, ...updated } : item));
      renderRows(state.items);
      R.toast('US 详情已保存', 'success');
    }

    async function archiveUserStory(id) {
      const cached = state.items.find((item) => item.id === id);
      const current = state.expandedStoryDetail && state.expandedStoryDetail.id === id
        ? state.expandedStoryDetail
        : cached || await R.api(`/user-stories/${id}`);
      const currentStatus = normalizeUsStatus(current?.status);

      if (currentStatus === 'ARCHIVED') {
        R.toast('US 已归档', 'info');
        renderRows(state.items);
        return;
      }
      if (currentStatus !== 'DONE') {
        R.toast('仅执行完毕后可归档', 'warning');
        renderRows(state.items);
        return;
      }

      const confirmed = await R.confirm({
        title: '归档 US',
        message: `确认归档 US ${current.usNumber || id}？归档后将无法继续分析和生成用例。`,
        confirmText: '确认归档',
        tone: 'danger'
      });
      if (!confirmed) {
        renderRows(state.items);
        return;
      }

      const updated = await R.api(`/user-stories/${id}`, {
        method: 'PUT',
        body: {
          status: 'ARCHIVED'
        }
      });

      state.items = state.items.map((item) => (item.id === updated.id ? { ...item, ...updated } : item));
      if (state.expandedStoryId === id) {
        state.expandedStoryDetail = updated;
      }
      if (analysisContext.detail && analysisContext.detail.id === id) {
        analysisContext.detail = { ...analysisContext.detail, ...updated };
      }
      renderRows(state.items);
      R.toast('US 已归档，后续无法继续分析和生成用例', 'success');
    }

    async function updateUserStorySprint(id, nextSprintRaw) {
      const nextSprint = String(nextSprintRaw || '').trim();
      const cached = state.items.find((item) => item.id === id);
      const current = state.expandedStoryDetail && state.expandedStoryDetail.id === id
        ? state.expandedStoryDetail
        : cached || await R.api(`/user-stories/${id}`);
      const currentSprint = String(current?.sprint || '').trim();

      if (currentSprint === nextSprint) {
        renderRows(state.items);
        return;
      }

      const fromLabel = currentSprint || '未设置';
      const toLabel = nextSprint || '未设置';
      const confirmed = await R.confirm({
        title: '更新 Sprint',
        message: `确认将 US ${current.usNumber || id} 的 Sprint 从“${fromLabel}”改为“${toLabel}”？`,
        confirmText: '确认更新',
        tone: 'primary'
      });
      if (!confirmed) {
        renderRows(state.items);
        return;
      }

      const updated = await R.api(`/user-stories/${id}`, {
        method: 'PUT',
        body: {
          sprint: nextSprint
        }
      });

      state.items = state.items.map((item) => (item.id === updated.id ? { ...item, ...updated } : item));
      if (state.expandedStoryId === id) {
        state.expandedStoryDetail = updated;
      }
      if (analysisContext.detail && analysisContext.detail.id === id) {
        analysisContext.detail = { ...analysisContext.detail, ...updated };
      }
      if (nextSprint) {
        state.sprintOptions = Array.from(new Set([...state.sprintOptions, nextSprint]));
      }
      try {
        await loadSprintOptions(true);
      } catch (_error) {
        // Keep local sprint options when refresh fails.
      }
      renderRows(state.items);
      R.toast(`Sprint 已更新为${toLabel}`, 'success');
    }

    function resolveStoryBusyState(storyId, story) {
      const id = Number(storyId);
      const current = story || state.items.find((item) => item.id === id);
      const currentStatus = normalizeUsStatus(current?.status);
      const isAnalyzing = state.analyzingStoryIds.has(id) || currentStatus === 'ANALYZING';
      const generationMeta = state.generationMetaByStory.get(id) || {};
      const generationStatus = String(generationMeta.status || '').toUpperCase();
      const isGenerating = generationStatus === 'RUNNING' || generationStatus === 'QUEUED' || state.generatingStoryIds.has(id);
      return { isAnalyzing, isGenerating };
    }

    function getSelectedStoryIds() {
      return [...state.selectedStoryIds]
        .map((id) => Number(id))
        .filter((id) => Number.isInteger(id) && id > 0);
    }

    async function batchAnalyzeUserStories() {
      const selectedIds = getSelectedStoryIds();
      if (!selectedIds.length) {
        R.toast('请先勾选要分析的 US', 'warning');
        return;
      }

      const skippedIds = [];
      const analyzableIds = [];
      selectedIds.forEach((id) => {
        const story = state.items.find((item) => item.id === id);
        const status = normalizeUsStatus(story?.status);
        const busy = resolveStoryBusyState(id, story);
        if (status === 'ARCHIVED' || busy.isAnalyzing) {
          skippedIds.push(id);
        } else {
          analyzableIds.push(id);
        }
      });

      if (!analyzableIds.length) {
        R.toast('所选 US 不可分析（已归档或分析中）', 'warning');
        return;
      }

      const message = skippedIds.length
        ? `已选 ${selectedIds.length} 条 US，其中 ${skippedIds.length} 条不可分析（已归档/分析中），确认提交其余 ${analyzableIds.length} 条分析任务？`
        : `确认批量分析选中的 ${analyzableIds.length} 条 US？`;
      const confirmed = await R.confirm({
        title: '批量分析 US',
        message,
        confirmText: '确认提交',
        tone: 'primary'
      });
      if (!confirmed) return;

      let successCount = 0;
      const failedIds = [];
      for (const storyId of analyzableIds) {
        try {
          const cached = state.items.find((item) => item.id === storyId) || {};
          const detail = (cached.description && cached.acceptanceCriteria)
            ? cached
            : await R.api(`/user-stories/${storyId}`);
          await submitAnalyzeTask(storyId, detail);
          setStoryAnalyzing(storyId, true);
          successCount += 1;
        } catch (_error) {
          failedIds.push(storyId);
        }
      }

      if (successCount > 0) {
        R.toast(`批量分析任务已提交：${successCount}/${analyzableIds.length}，可在消息中心查看完成通知`, 'success');
      }
      if (skippedIds.length > 0) {
        R.toast(`已跳过 ${skippedIds.length} 条不可分析 US`, 'info');
      }
      if (failedIds.length > 0) {
        R.toast(`提交失败 ${failedIds.length} 条，请稍后重试`, 'warning');
      }
      await loadUserStories();
    }

    async function batchGenerateUserStories() {
      const selectedIds = getSelectedStoryIds();
      if (!selectedIds.length) {
        R.toast('请先勾选要生成用例的 US', 'warning');
        return;
      }

      const skippedIds = [];
      const generatableIds = [];
      selectedIds.forEach((id) => {
        const story = state.items.find((item) => item.id === id);
        const status = normalizeUsStatus(story?.status);
        const busy = resolveStoryBusyState(id, story);
        if (status === 'ARCHIVED' || busy.isGenerating) {
          skippedIds.push(id);
        } else {
          generatableIds.push(id);
        }
      });

      if (!generatableIds.length) {
        R.toast('所选 US 不可生成（已归档或生成中）', 'warning');
        return;
      }

      const message = skippedIds.length
        ? `已选 ${selectedIds.length} 条 US，其中 ${skippedIds.length} 条不可生成（已归档/生成中），确认提交其余 ${generatableIds.length} 条生成任务？`
        : `确认批量生成选中的 ${generatableIds.length} 条 US 用例？`;
      const confirmed = await R.confirm({
        title: '批量生成用例',
        message,
        confirmText: '确认提交',
        tone: 'primary'
      });
      if (!confirmed) return;

      let successCount = 0;
      const failedIds = [];
      for (const storyId of generatableIds) {
        try {
          const submitted = await submitCaseGenerationTask(storyId, { count: 3 });
          setStoryGenerationSnapshot(storyId, submitted);
          successCount += 1;
        } catch (_error) {
          failedIds.push(storyId);
        }
      }

      if (successCount > 0) {
        R.toast(`批量生成任务已提交：${successCount}/${generatableIds.length}，可在消息中心查看完成通知`, 'success');
      }
      if (skippedIds.length > 0) {
        R.toast(`已跳过 ${skippedIds.length} 条不可生成 US`, 'info');
      }
      if (failedIds.length > 0) {
        R.toast(`提交失败 ${failedIds.length} 条，请稍后重试`, 'warning');
      }
      await loadUserStories();
    }

    async function batchArchiveUserStories() {
      const selectedIds = getSelectedStoryIds();
      if (!selectedIds.length) {
        R.toast('请先勾选要归档的 US', 'warning');
        return;
      }

      const blockedIds = [];
      const alreadyArchivedIds = [];
      const notDoneIds = [];
      const archivableIds = [];
      selectedIds.forEach((id) => {
        const story = state.items.find((item) => item.id === id);
        const status = normalizeUsStatus(story?.status);
        const busy = resolveStoryBusyState(id, story);
        if (busy.isAnalyzing || busy.isGenerating) {
          blockedIds.push(id);
          return;
        }
        if (status === 'ARCHIVED') {
          alreadyArchivedIds.push(id);
          return;
        }
        if (status !== 'DONE') {
          notDoneIds.push(id);
          return;
        }
        archivableIds.push(id);
      });

      if (!archivableIds.length) {
        R.toast('所选 US 中没有可归档项（仅执行完毕可归档）', 'warning');
        return;
      }

      const skippedCount = blockedIds.length + alreadyArchivedIds.length + notDoneIds.length;
      const message = skippedCount
        ? `已选 ${selectedIds.length} 条 US，其中 ${skippedCount} 条将跳过（分析/生成中、已归档或未执行完毕），确认归档其余 ${archivableIds.length} 条？`
        : `确认归档选中的 ${archivableIds.length} 条 US？归档后将无法继续分析和生成用例。`;
      const confirmed = await R.confirm({
        title: '批量归档 US',
        message,
        confirmText: '确认归档',
        tone: 'danger'
      });
      if (!confirmed) return;

      let successCount = 0;
      const failedIds = [];
      for (const storyId of archivableIds) {
        try {
          await R.api(`/user-stories/${storyId}`, {
            method: 'PUT',
            body: {
              status: 'ARCHIVED'
            }
          });
          successCount += 1;
        } catch (_error) {
          failedIds.push(storyId);
        }
      }

      if (successCount > 0) {
        R.toast(`批量归档完成：成功 ${successCount} 条`, 'success');
      }
      if (skippedCount > 0) {
        R.toast(`已跳过 ${skippedCount} 条不满足归档条件的 US`, 'info');
      }
      if (failedIds.length > 0) {
        R.toast(`归档失败 ${failedIds.length} 条，请稍后重试`, 'warning');
      }
      await loadUserStories();
    }

    async function batchDeleteUserStories() {
      const selectedIds = getSelectedStoryIds();
      if (!selectedIds.length) {
        R.toast('请先勾选要删除的 US', 'warning');
        return;
      }

      const blockedIds = [];
      const deletableIds = [];
      selectedIds.forEach((id) => {
        const busy = resolveStoryBusyState(id);
        if (busy.isAnalyzing || busy.isGenerating) {
          blockedIds.push(id);
        } else {
          deletableIds.push(id);
        }
      });

      if (!deletableIds.length) {
        R.toast('所选 US 正在分析或生成中，暂不允许删除', 'warning');
        return;
      }

      const message = blockedIds.length
        ? `已选 ${selectedIds.length} 条 US，其中 ${blockedIds.length} 条分析/生成中将跳过，确认删除其余 ${deletableIds.length} 条？`
        : `确认删除选中的 ${deletableIds.length} 条 US？删除后不可恢复。`;
      const confirmed = await R.confirm({
        title: '批量删除 US',
        message,
        confirmText: '确认删除',
        tone: 'danger'
      });
      if (!confirmed) return;

      let successCount = 0;
      const failedIds = [];
      for (const storyId of deletableIds) {
        try {
          await R.api(`/user-stories/${storyId}`, { method: 'DELETE' });
          successCount += 1;
          state.selectedStoryIds.delete(storyId);
          if (state.expandedStoryId === storyId) {
            state.expandedStoryId = null;
            state.expandedStoryDetail = null;
          }
        } catch (_error) {
          failedIds.push(storyId);
        }
      }

      if (successCount > 0) {
        R.toast(`批量删除完成：成功 ${successCount} 条`, 'success');
      }
      if (blockedIds.length > 0) {
        R.toast(`已跳过 ${blockedIds.length} 条分析/生成中的 US`, 'info');
      }
      if (failedIds.length > 0) {
        R.toast(`删除失败 ${failedIds.length} 条，请稍后重试`, 'warning');
      }

      if (state.page > 0 && successCount >= state.items.length) {
        state.page -= 1;
      }
      await loadUserStories();
    }

    async function deleteUserStory(id) {
      const busy = resolveStoryBusyState(id);
      if (busy.isAnalyzing || busy.isGenerating) {
        R.toast(busy.isGenerating ? 'US 生成用例中，暂不允许删除' : 'US 分析中，暂不允许删除', 'warning');
        return;
      }
      const confirmed = await R.confirm({
        title: '删除 US',
        message: `确认删除 US #${id}？删除后不可恢复。`,
        confirmText: '确认删除',
        tone: 'danger'
      });
      if (!confirmed) return;
      await R.api(`/user-stories/${id}`, { method: 'DELETE' });
      R.toast('US 已删除', 'success');
      state.selectedStoryIds.delete(id);
      if (state.expandedStoryId === id) {
        state.expandedStoryId = null;
        state.expandedStoryDetail = null;
      }
      if (state.page > 0 && state.items.length <= 1) {
        state.page -= 1;
      }
      await loadUserStories();
    }

    tableBody.addEventListener('click', async (event) => {
      const button = event.target.closest('button[data-action]');
      if (!button) return;
      const id = Number(button.dataset.id);
      if (!id) return;

      try {
        if (button.dataset.action === 'analyze') await analyzeUserStory(id);
        if (button.dataset.action === 'generate') await generateCases(id);
        if (button.dataset.action === 'toggle-detail') await toggleUsDetail(id);
        if (button.dataset.action === 'collapse-detail') await toggleUsDetail(id);
        if (button.dataset.action === 'save-detail') {
          const detailRow = button.closest('tr[data-detail-row]');
          await saveUsDetail(id, detailRow);
        }
        if (button.dataset.action === 'archive') await archiveUserStory(id);
        if (button.dataset.action === 'view-cases') await openLinkedCasesPanel(id);
        if (button.dataset.action === 'delete') await deleteUserStory(id);
      } catch (error) {
        R.toast(error.message || '操作失败', 'error');
      }
    });

    tableBody.addEventListener('change', async (event) => {
      const rowCheckbox = event.target.closest('input[data-action="select-story"]');
      if (rowCheckbox) {
        const id = Number(rowCheckbox.dataset.id);
        if (!id) return;
        if (rowCheckbox.checked) {
          state.selectedStoryIds.add(id);
        } else {
          state.selectedStoryIds.delete(id);
        }
        syncStorySelectionControls();
        return;
      }

      const select = event.target.closest('select[data-action]');
      if (!select) return;
      const id = Number(select.dataset.id);
      if (!id) return;
      const action = select.dataset.action;
      if (action !== 'change-sprint') return;

      try {
        select.disabled = true;
        await updateUserStorySprint(id, select.value);
      } catch (error) {
        renderRows(state.items);
        const message = error.message || 'Sprint 更新失败';
        R.toast(message, 'error');
      } finally {
        select.disabled = false;
      }
    });

    selectAllStoriesCheckbox?.addEventListener('change', () => {
      const visibleIds = getCurrentPageStoryIds();
      if (selectAllStoriesCheckbox.checked) {
        visibleIds.forEach((id) => state.selectedStoryIds.add(id));
      } else {
        visibleIds.forEach((id) => state.selectedStoryIds.delete(id));
      }
      syncStorySelectionControls();
    });

    function closeUsBatchActionsMenu() {
      batchStoryActionsMenu?.classList.add('hidden');
    }

    batchStoryActionsMenu?.addEventListener('click', async (event) => {
      const item = event.target.closest('a[data-action]');
      if (!item) return;
      event.preventDefault();
      closeUsBatchActionsMenu();
      const action = String(item.dataset.action || '').trim();
      try {
        if (action === 'analyze') {
          await batchAnalyzeUserStories();
          return;
        }
        if (action === 'generate') {
          await batchGenerateUserStories();
          return;
        }
        if (action === 'archive') {
          await batchArchiveUserStories();
          return;
        }
        if (action === 'delete') {
          await batchDeleteUserStories();
        }
      } catch (error) {
        R.toast(error.message || '批量操作失败', 'error');
      }
    });

    window.toggleUsBatchActionsMenu = () => {
      if (!batchStoryActionsMenu || !batchStoryActionsButton || batchStoryActionsButton.disabled) return;
      batchStoryActionsMenu.classList.toggle('hidden');
    };

    document.addEventListener('click', (event) => {
      if (!event.target.closest('#us-batch-actions-menu') && !event.target.closest('#us-batch-actions-button')) {
        closeUsBatchActionsMenu();
      }
    });

    searchInput.addEventListener('input', debounce(async (event) => {
      state.keyword = event.target.value.trim();
      state.page = 0;
      try {
        await loadUserStories();
      } catch (error) {
        R.toast(error.message || '加载失败', 'error');
      }
    }));

    statusSelect.addEventListener('change', async (event) => {
      state.status = event.target.value;
      state.page = 0;
      try {
        await loadUserStories();
      } catch (error) {
        R.toast(error.message || '加载失败', 'error');
      }
    });

    sprintSelect.addEventListener('change', async () => {
      state.sprint = sprintSelect.value;
      state.page = 0;
      try {
        await loadUserStories();
      } catch (error) {
        R.toast(error.message || '加载失败', 'error');
      }
    });

    pageSizeSelect?.addEventListener('change', async () => {
      const nextSize = Number(pageSizeSelect.value) || 20;
      state.size = pageSizeOptions.includes(nextSize) ? nextSize : 20;
      state.page = 0;
      try {
        await loadUserStories();
      } catch (error) {
        R.toast(error.message || '分页查询失败', 'error');
      }
    });

    prevPageButton?.addEventListener('click', async () => {
      if (state.page <= 0) return;
      state.page -= 1;
      try {
        await loadUserStories();
      } catch (error) {
        R.toast(error.message || '分页查询失败', 'error');
      }
    });

    nextPageButton?.addEventListener('click', async () => {
      if (state.totalPages && state.page >= state.totalPages - 1) return;
      state.page += 1;
      try {
        await loadUserStories();
      } catch (error) {
        R.toast(error.message || '分页查询失败', 'error');
      }
    });

    const parseTextArea = $('#us-parse-content', parseModal) || $('textarea', parseModal);
    if (parseTextArea) {
      parseTextArea.placeholder = US_PARSE_TEMPLATE;
    }

    const importSourceButtons = $$('[data-import-source]', importModal);
    const importServerInput = $('#us-import-server-url', importModal);
    const importProjectInput = $('#us-import-project-key', importModal);
    const importTokenInput = $('#us-import-token', importModal);
    const importContentInput = $('#us-import-content', importModal);
    const importMaxCountInput = $('#us-import-max-count', importModal);
    const importStartBtn = $('#us-import-start-btn', importModal);
    const importTestBtn = $('#us-import-test-btn', importModal);

    function setImportSource(source) {
      state.importSource = source;
      importSourceButtons.forEach((btn) => {
        const active = btn.dataset.importSource === source;
        btn.classList.toggle('bg-[#00d4ff]/20', active);
        btn.classList.toggle('text-[#00d4ff]', active);
        if (active) {
          btn.classList.remove('bg-white/5');
        } else {
          btn.classList.add('bg-white/5');
          btn.classList.remove('text-[#00d4ff]');
        }
      });

      const sourceHints = {
        JIRA: '输入 JIRA issue keys（每行一个，如 ECOM-1001），或直接点击开始导入使用项目占位导入',
        CSV: '每行一个记录，格式：标题,描述,验收标准',
        EXCEL: '每行一个记录，使用 Tab 分隔：标题<TAB>描述<TAB>验收标准',
        TEXT: '每行一条需求描述，系统将按行导入'
      };
      if (importContentInput) {
        importContentInput.placeholder = sourceHints[source] || sourceHints.TEXT;
      }
    }

    function buildImportRequest() {
      return {
        sourceType: state.importSource,
        serverUrl: importServerInput?.value?.trim() || '',
        projectKey: importProjectInput?.value?.trim() || '',
        apiToken: importTokenInput?.value?.trim() || '',
        content: importContentInput?.value || '',
        maxCount: Number(importMaxCountInput?.value || 20) || 20
      };
    }

    importSourceButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        setImportSource(btn.dataset.importSource || 'TEXT');
      });
    });
    setImportSource(state.importSource);

    if (importTestBtn) {
      importTestBtn.addEventListener('click', async () => {
        try {
          const result = await R.api('/user-stories/import/test-connection', {
            method: 'POST',
            body: buildImportRequest()
          });
          const ok = result?.reachable !== false;
          R.toast(ok ? '连接测试成功' : `连接失败: ${result?.message || '未知错误'}`, ok ? 'success' : 'warning');
        } catch (error) {
          R.toast(error.message || '连接测试失败', 'error');
        }
      });
    }

    if (importStartBtn) {
      importStartBtn.addEventListener('click', async () => {
        try {
          const created = await R.api('/user-stories/import', {
            method: 'POST',
            body: buildImportRequest()
          });
          const count = Array.isArray(created) ? created.length : 0;
          R.toast(`导入完成，共创建 ${count} 条 US`, 'success');
          importModal.classList.add('hidden');
          if (importContentInput) importContentInput.value = '';
          state.page = 0;
          await loadUserStories({ refreshSprints: true });
        } catch (error) {
          R.toast(error.message || '导入失败', 'error');
        }
      });
    }

    window.openParseModal = () => {
      if (parseTextArea && !String(parseTextArea.value || '').trim()) {
        parseTextArea.value = US_PARSE_TEMPLATE;
      }
      parseModal.classList.remove('hidden');
      parseTextArea?.focus();
    };
    window.closeParseModal = () => parseModal.classList.add('hidden');
    window.openImportModal = () => importModal.classList.remove('hidden');
    window.closeImportModal = () => importModal.classList.add('hidden');
    window.startParsing = () => createFromParseModal().catch((error) => R.toast(error.message || '创建失败', 'error'));

    await loadUserStories({ refreshSprints: true });
  }

  async function initializeTestCasesPage() {
    const user = await R.ensureAuth();
    updateUserHeader(user);

    const filterCard = $('main .p-6 > .glass-card');
    const cardsContainer = $('main .p-6 > .space-y-4');
    const generateModal = $('#generate-modal');
    const generateMenu = $('#generate-menu');
    const batchActionsButton = $('#tc-batch-actions-button');
    const batchActionsMenu = $('#tc-batch-actions-menu');

    if (!filterCard || !cardsContainer || !generateModal || !generateMenu) return;

    const searchInput = $('input[placeholder*="搜索用例"]', filterCard);
    const prioritySelect = $('#tc-priority-select', filterCard);
    const statusSelect = $('#tc-status-select', filterCard);
    const typeSelect = $('#tc-type-select', filterCard);

    if (!searchInput || !prioritySelect || !statusSelect || !typeSelect) return;

    let paginationBar = $('#tc-pagination-bar');
    if (paginationBar) paginationBar.remove();
    paginationBar = document.createElement('div');
    paginationBar.id = 'tc-pagination-bar';
    paginationBar.className = 'glass-card mt-4 px-4 py-3 flex flex-wrap items-center justify-between gap-3';
    paginationBar.innerHTML = `
      <div id="tc-page-summary" class="text-xs text-[#a1a1aa]">共 0 条，显示 0-0</div>
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2 text-xs text-[#a1a1aa]">
          <span>每页</span>
          <select id="tc-page-size" class="px-2 py-1 bg-white/5 border border-white/10 rounded text-xs focus:outline-none focus:border-[#00d4ff]">
            <option value="10">10</option>
            <option value="20" selected>20</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </label>
        <button id="tc-page-prev" class="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-xs disabled:opacity-50 disabled:cursor-not-allowed" type="button">上一页</button>
        <span id="tc-page-info" class="text-xs text-[#d4d4d8] min-w-[72px] text-center">0 / 0</span>
        <button id="tc-page-next" class="px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-xs disabled:opacity-50 disabled:cursor-not-allowed" type="button">下一页</button>
      </div>
    `;
    cardsContainer.insertAdjacentElement('afterend', paginationBar);

    const pageSummary = $('#tc-page-summary', paginationBar);
    const pageSizeSelect = $('#tc-page-size', paginationBar);
    const prevPageButton = $('#tc-page-prev', paginationBar);
    const nextPageButton = $('#tc-page-next', paginationBar);
    const pageInfo = $('#tc-page-info', paginationBar);

    prioritySelect.innerHTML = [
      '<option value="">全部级别</option>',
      '<option value="CRITICAL">L0</option>',
      '<option value="HIGH">L1</option>',
      '<option value="MEDIUM">L2</option>',
      '<option value="LOW">L3</option>'
    ].join('');

    statusSelect.innerHTML = [
      '<option value="">全部状态</option>',
      '<option value="DRAFT">草稿</option>',
      '<option value="REVIEW">评审中</option>',
      '<option value="READY">就绪</option>',
      '<option value="DEPRECATED">废弃</option>',
      '<option value="ARCHIVED">归档</option>'
    ].join('');

    typeSelect.innerHTML = [
      '<option value="">全部类型</option>',
      '<option value="FUNCTIONAL">功能</option>',
      '<option value="UI">UI</option>',
      '<option value="API">API</option>',
      '<option value="PERFORMANCE">性能</option>',
      '<option value="SECURITY">安全</option>',
      '<option value="COMPATIBILITY">兼容</option>'
    ].join('');

    const state = {
      items: [],
      keyword: '',
      status: '',
      type: '',
      priority: '',
      page: 0,
      size: 20,
      totalElements: 0,
      totalPages: 0,
      first: true,
      last: true,
      selectedCaseId: null,
      selectedScriptType: 'PLAYWRIGHT',
      scriptGenerationMetaByCase: new Map(),
      generatingCaseIds: new Set()
    };

    const pageSizeOptions = [10, 20, 50, 100];

    function setCaseScriptGenerationSnapshot(caseId, snapshot) {
      const id = Number(caseId);
      if (!id) return null;

      if (!snapshot) {
        state.scriptGenerationMetaByCase.delete(id);
        state.generatingCaseIds.delete(id);
        return null;
      }

      const normalized = normalizeScriptGenerationSnapshot(snapshot);
      state.scriptGenerationMetaByCase.set(id, normalized);
      const running = normalized.status === 'RUNNING' || normalized.status === 'QUEUED';
      if (running) {
        state.generatingCaseIds.add(id);
      } else {
        state.generatingCaseIds.delete(id);
      }
      return normalized;
    }

    function resolveScriptGenerateActionMeta(caseId) {
      const id = Number(caseId);
      const meta = state.scriptGenerationMetaByCase.get(id) || {};
      const status = String(meta.status || '').toUpperCase();
      const isGenerating = status === 'RUNNING' || status === 'QUEUED' || state.generatingCaseIds.has(id);
      const hasHistory = Boolean(meta.hasRecord || meta.result?.latestRecord);

      if (isGenerating) {
        return {
          label: '脚本生成中...',
          title: '点击查看生成过程',
          className: 'px-2 py-1 text-xs rounded bg-[#10b981]/30 text-[#6ee7b7] hover:bg-[#10b981]/40'
        };
      }

      if (hasHistory) {
        return {
          label: '查看生成',
          title: '点击查看生成记录',
          className: 'px-2 py-1 text-xs rounded bg-[#38bdf8]/25 text-[#7dd3fc] hover:bg-[#38bdf8]/35'
        };
      }

      return {
        label: '生成脚本',
        title: '点击开始生成脚本',
        className: 'px-2 py-1 text-xs rounded bg-[#00d4ff]/20 text-[#00d4ff] hover:bg-[#00d4ff]/30'
      };
    }

    function syncScriptGenerateButtonState(caseId) {
      const id = Number(caseId);
      if (!id) return;
      const meta = resolveScriptGenerateActionMeta(id);
      const selector = `button[data-action="generate"][data-id="${id}"]`;
      const nodes = $$(selector, cardsContainer);
      nodes.forEach((node) => {
        node.className = meta.className;
        node.textContent = meta.label;
        node.title = meta.title;
      });
    }

    function getSelectedCaseIds() {
      return $$('input[data-case-id]:checked', cardsContainer)
        .map((node) => Number(node.dataset.caseId))
        .filter((id) => Number.isInteger(id) && id > 0);
    }

    function syncBatchActionControls() {
      const selectedCount = getSelectedCaseIds().length;
      const hasSelection = selectedCount > 0;
      if (batchActionsButton) {
        batchActionsButton.disabled = !hasSelection;
      }
      if (!hasSelection && batchActionsMenu) {
        batchActionsMenu.classList.add('hidden');
      }
    }

    function renderPagination() {
      if (!pageSummary || !pageInfo || !pageSizeSelect || !prevPageButton || !nextPageButton) return;

      const totalElements = Number(state.totalElements) || 0;
      const totalPages = Number(state.totalPages) || 0;
      const pageNumber = Number(state.page) || 0;
      const hasData = totalElements > 0 && totalPages > 0;
      const start = hasData ? (pageNumber * state.size) + 1 : 0;
      const end = hasData ? Math.min((pageNumber + 1) * state.size, totalElements) : 0;
      const current = hasData ? (pageNumber + 1) : 0;

      pageSummary.textContent = `共 ${totalElements} 条，显示 ${start}-${end}`;
      pageInfo.textContent = `${current} / ${totalPages}`;
      pageSizeSelect.value = String(state.size);

      prevPageButton.disabled = !hasData || pageNumber <= 0;
      nextPageButton.disabled = !hasData || pageNumber >= (totalPages - 1);
    }

    function renderCards(list) {
      if (!list.length) {
        cardsContainer.innerHTML = '<div class="glass-card p-8 text-center text-sm text-[#71717a]">暂无测试用例</div>';
        syncBatchActionControls();
        return;
      }

      cardsContainer.innerHTML = list.map((tc) => {
        const detailId = `tc-detail-${tc.id}`;
        const steps = Array.isArray(tc.steps) ? tc.steps : [];
        const statusText = CASE_STATUS_LABEL[tc.status] || tc.status || '-';
        const typeText = CASE_TYPE_LABEL[tc.testType] || tc.testType || '-';
        const scriptActionMeta = resolveScriptGenerateActionMeta(tc.id);
        return `
          <div class="glass-card p-4">
            <div class="flex items-start gap-4">
              <input type="checkbox" data-case-id="${tc.id}" class="mt-1 rounded border-white/20 bg-white/5">
              <div class="flex-1">
                <div class="flex flex-wrap items-center gap-2 mb-2">
                  <span class="px-2 py-0.5 text-xs rounded font-medium ${tc.priority === 'CRITICAL' ? 'bg-[#ef4444]/20 text-[#ef4444]' : tc.priority === 'HIGH' ? 'bg-[#f59e0b]/20 text-[#f59e0b]' : tc.priority === 'MEDIUM' ? 'bg-[#3b82f6]/20 text-[#3b82f6]' : 'bg-white/10 text-[#a1a1aa]'}">${R.escapeHtml(CASE_PRIORITY_LABEL[tc.priority] || tc.priority || '-')}</span>
                  <button data-action="expand" data-id="${tc.id}" data-target="${detailId}" class="font-medium text-left hover:text-[#7dd3fc] hover:underline">${R.escapeHtml(tc.caseNumber || '')}: ${R.escapeHtml(tc.title || '-')}</button>
                  <span class="px-2 py-0.5 text-xs rounded bg-[#00d4ff]/20 text-[#00d4ff]">${R.escapeHtml(typeText)}</span>
                  <span class="px-2 py-0.5 text-xs rounded bg-white/10 text-[#d1d5db]">${R.escapeHtml(statusText)}</span>
                  <span class="text-xs text-[#71717a]">US: ${R.escapeHtml(tc.userStory?.usNumber || '-')}</span>
                </div>
                <p class="text-sm text-[#a1a1aa] mb-3">${R.escapeHtml(tc.description || '无描述')}</p>
                <div class="flex items-center gap-4 text-xs text-[#71717a]">
                  <span>步骤: ${steps.length}</span>
                  <span>标签: ${R.escapeHtml(tc.tags || '-')}</span>
                  <span>更新: ${R.escapeHtml(R.formatDateTime(tc.updatedAt))}</span>
                </div>
              </div>
              <div class="flex flex-wrap items-center gap-2 justify-end">
                <button data-action="expand" data-id="${tc.id}" data-target="${detailId}" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20">详情</button>
                <button data-action="generate" data-id="${tc.id}" class="${scriptActionMeta.className}" title="${R.escapeHtml(scriptActionMeta.title)}">${scriptActionMeta.label}</button>
                <button data-action="edit" data-id="${tc.id}" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20">编辑</button>
                <button data-action="delete" data-id="${tc.id}" class="px-2 py-1 text-xs rounded bg-[#ef4444]/20 text-[#ef4444] hover:bg-[#ef4444]/30">删除</button>
              </div>
            </div>
            <div id="${detailId}" class="expandable-content mt-4 pt-4 border-t border-white/5">
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <h4 class="text-sm font-medium mb-2">前置条件</h4>
                  <p class="text-sm text-[#a1a1aa] whitespace-pre-line">${R.escapeHtml(tc.preconditions || '-')}</p>
                </div>
                <div>
                  <h4 class="text-sm font-medium mb-2">测试数据 / 标签</h4>
                  <p class="text-sm text-[#a1a1aa] whitespace-pre-line">${R.escapeHtml(tc.tags || '-')}</p>
                </div>
              </div>
              <div class="mt-4">
                <h4 class="text-sm font-medium mb-2">测试步骤</h4>
                <ol class="text-sm text-[#a1a1aa] space-y-1 list-decimal list-inside">
                  ${steps.length ? steps.map((step) => `<li>${R.escapeHtml(step.action || '-')} -> ${R.escapeHtml(step.expectedResult || '-')}</li>`).join('') : '<li>暂无步骤</li>'}
                </ol>
              </div>
            </div>
          </div>
        `;
      }).join('');
      syncBatchActionControls();
      if (window.lucide) window.lucide.createIcons();
    }

    function buildListQuery() {
      const params = new URLSearchParams();
      params.set('page', String(state.page));
      params.set('size', String(state.size));
      if (state.keyword) params.set('keyword', state.keyword);
      if (state.status) params.set('status', state.status);
      if (state.type) params.set('type', state.type);
      if (state.priority) params.set('priority', state.priority);
      return params.toString();
    }

    async function refreshScriptGenerationStatuses(items) {
      const list = Array.isArray(items) ? items : [];
      if (!list.length) return;

      const snapshots = await Promise.all(list.map(async (tc) => {
        try {
          const snapshot = await fetchLatestScriptGenerationSnapshot(tc.id);
          return [tc.id, snapshot];
        } catch (_error) {
          return [tc.id, null];
        }
      }));

      const visibleIds = new Set((state.items || []).map((item) => item.id));
      snapshots.forEach(([id, snapshot]) => {
        if (!visibleIds.has(id)) return;
        setCaseScriptGenerationSnapshot(id, snapshot);
        syncScriptGenerateButtonState(id);
      });
    }

    async function loadTestCases() {
      const data = await R.api(`/test-cases?${buildListQuery()}`);
      const page = data && typeof data === 'object' ? data : {};
      const list = unwrapPage(page);

      state.items = list;
      state.totalElements = Number(page.totalElements ?? list.length) || 0;
      state.totalPages = Number(page.totalPages ?? (state.totalElements ? Math.ceil(state.totalElements / state.size) : 0)) || 0;
      state.page = Number(page.pageNumber ?? state.page) || 0;
      state.first = Boolean(page.first ?? state.page <= 0);
      state.last = Boolean(page.last ?? (state.totalPages === 0 || state.page >= state.totalPages - 1));

      if (state.totalPages === 0 && state.page !== 0) {
        state.page = 0;
      }

      if (state.totalPages > 0 && state.page >= state.totalPages) {
        state.page = Math.max(state.totalPages - 1, 0);
        return loadTestCases();
      }

      const visibleIds = new Set(list.map((item) => item.id));
      [...state.scriptGenerationMetaByCase.keys()].forEach((caseId) => {
        if (!visibleIds.has(caseId)) {
          state.scriptGenerationMetaByCase.delete(caseId);
          state.generatingCaseIds.delete(caseId);
        }
      });

      updateTestCaseHeaderBadge(state.totalElements);
      if (!state.keyword && !state.status && !state.type && !state.priority) {
        updateCaseNavBadgeNodes(state.totalElements);
      }

      renderCards(list);
      renderPagination();
      refreshScriptGenerationStatuses(list).catch(() => {});
    }

    let scriptGenerationPanelNode = null;
    let scriptGenerationPanelTitle = null;
    let scriptGenerationPanelBody = null;
    const scriptGenerationContext = {
      caseId: null,
      caseLabel: '',
      activeTaskId: null,
      latestSnapshot: null,
      tracking: false,
      selectedScriptType: 'PLAYWRIGHT',
      selectedLanguage: 'JAVASCRIPT',
      targetUrl: '',
      historyPage: 0,
      historySize: 5,
      historyItems: [],
      historyTotalPages: 0,
      historyTotalElements: 0,
      selectedRecordId: null,
      selectedRecord: null
    };
    const scriptHistoryPageSizeOptions = [5, 10, 20, 50];
    const scriptTypeLanguageMap = {
      PLAYWRIGHT: ['JAVASCRIPT', 'TYPESCRIPT'],
      CYPRESS: ['JAVASCRIPT', 'TYPESCRIPT'],
      SELENIUM: ['JAVA', 'PYTHON'],
      APPIUM: ['JAVASCRIPT', 'PYTHON'],
      REST_ASSURED: ['JAVA']
    };

    function closeScriptGenerationPanel() {
      if (scriptGenerationPanelNode) scriptGenerationPanelNode.classList.add('hidden');
    }

    function ensureScriptGenerationPanel() {
      if (scriptGenerationPanelNode) return scriptGenerationPanelNode;

      scriptGenerationPanelNode = document.createElement('div');
      scriptGenerationPanelNode.className = 'hidden fixed inset-0 z-[99] bg-black/70 backdrop-blur-sm';
      scriptGenerationPanelNode.innerHTML = `
        <div class="absolute inset-y-0 right-0 w-full max-w-5xl bg-[#12121a] border-l border-white/10 shadow-2xl flex flex-col">
          <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
            <h3 id="tc-script-generation-title" class="text-base font-semibold text-white">脚本生成</h3>
            <button id="tc-script-generation-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
          </div>
          <div id="tc-script-generation-body" class="flex-1 overflow-y-auto p-5 space-y-5"></div>
        </div>
      `;
      document.body.appendChild(scriptGenerationPanelNode);
      scriptGenerationPanelTitle = $('#tc-script-generation-title', scriptGenerationPanelNode);
      scriptGenerationPanelBody = $('#tc-script-generation-body', scriptGenerationPanelNode);

      $('#tc-script-generation-close', scriptGenerationPanelNode)?.addEventListener('click', closeScriptGenerationPanel);
      scriptGenerationPanelNode.addEventListener('click', (event) => {
        if (event.target === scriptGenerationPanelNode) closeScriptGenerationPanel();
      });

      scriptGenerationPanelBody?.addEventListener('click', async (event) => {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const action = button.dataset.action;
        try {
          if (action === 'script-regenerate') {
            await regenerateCurrentScriptGeneration();
            return;
          }
          if (action === 'script-refine') {
            await submitScriptGenerationFeedback();
            return;
          }
          if (action === 'script-history-prev') {
            if (scriptGenerationContext.historyPage <= 0) return;
            scriptGenerationContext.historyPage -= 1;
            await refreshScriptGenerationHistory();
            renderScriptGenerationPanel();
            return;
          }
          if (action === 'script-history-next') {
            if (scriptGenerationContext.historyTotalPages && scriptGenerationContext.historyPage >= scriptGenerationContext.historyTotalPages - 1) return;
            scriptGenerationContext.historyPage += 1;
            await refreshScriptGenerationHistory();
            renderScriptGenerationPanel();
            return;
          }
          if (action === 'script-select-record') {
            const recordId = String(button.dataset.recordId || '').trim();
            if (!recordId) return;
            selectScriptHistoryRecord(recordId);
            renderScriptGenerationPanel();
            return;
          }
          if (action === 'script-view-record') {
            const recordId = String(button.dataset.recordId || '').trim();
            if (!recordId) return;
            await viewScriptGenerationRecordDetail(recordId);
            return;
          }
          if (action === 'script-delete-record') {
            const recordId = String(button.dataset.recordId || '').trim();
            if (!recordId) return;
            await deleteScriptGenerationRecord(recordId);
            return;
          }
          if (action === 'script-preview-record') {
            const recordId = String(button.dataset.recordId || '').trim();
            if (!recordId) return;
            await previewScriptGenerationRecord(recordId);
            return;
          }
          if (action === 'script-adopt-record') {
            const recordId = String(button.dataset.recordId || '').trim();
            if (!recordId) return;
            await adoptScriptGenerationRecord(recordId);
            return;
          }
          if (action === 'script-copy-code') {
            const code = scriptGenerationContext.selectedRecord?.generatedCode || scriptGenerationContext.latestSnapshot?.result?.latestRecord?.generatedCode || '';
            if (!String(code).trim()) {
              R.toast('暂无可复制脚本', 'warning');
              return;
            }
            await navigator.clipboard.writeText(code);
            R.toast('脚本代码已复制', 'success');
            return;
          }
          if (action === 'script-copy-command') {
            const command = scriptGenerationContext.selectedRecord?.runCommand || '';
            if (!String(command).trim()) {
              R.toast('暂无可复制运行命令', 'warning');
              return;
            }
            await navigator.clipboard.writeText(command);
            R.toast('运行命令已复制', 'success');
          }
        } catch (error) {
          R.toast(error.message || '操作失败', 'error');
        }
      });

      scriptGenerationPanelBody?.addEventListener('change', async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLSelectElement)) return;
        if (target.id === 'tc-script-type-select') {
          const nextType = String(target.value || 'PLAYWRIGHT').toUpperCase();
          scriptGenerationContext.selectedScriptType = nextType;
          const supported = resolveScriptLanguages(nextType);
          if (!supported.includes(scriptGenerationContext.selectedLanguage)) {
            scriptGenerationContext.selectedLanguage = supported[0] || 'JAVASCRIPT';
          }
          renderScriptGenerationPanel();
          return;
        }
        if (target.id === 'tc-script-language-select') {
          scriptGenerationContext.selectedLanguage = String(target.value || 'JAVASCRIPT').toUpperCase();
          return;
        }
        if (target.id === 'tc-script-history-size') {
          const nextSize = Number(target.value) || 5;
          scriptGenerationContext.historySize = scriptHistoryPageSizeOptions.includes(nextSize) ? nextSize : 5;
          scriptGenerationContext.historyPage = 0;
          await refreshScriptGenerationHistory();
          renderScriptGenerationPanel();
        }
      });

      return scriptGenerationPanelNode;
    }

    function resolveScriptLanguages(scriptType) {
      const normalized = String(scriptType || 'PLAYWRIGHT').toUpperCase();
      return scriptTypeLanguageMap[normalized] || ['JAVASCRIPT'];
    }

    function normalizeScriptGenerationSnapshot(raw) {
      const source = raw && typeof raw === 'object' ? raw : {};
      const result = source.result && typeof source.result === 'object' ? source.result : null;
      const latestRecord = result?.latestRecord && typeof result.latestRecord === 'object' ? result.latestRecord : null;
      return {
        status: String(source.status || 'NONE').toUpperCase(),
        taskId: source.taskId || null,
        pollIntervalMs: Number(source.pollIntervalMs) > 0 ? Number(source.pollIntervalMs) : 1500,
        pollPath: source.pollPath || null,
        generatedAt: source.generatedAt || result?.updatedAt || null,
        events: Array.isArray(source.events) ? source.events.filter(Boolean) : [],
        result,
        latestRecord,
        errorMessage: source.errorMessage || null,
        hasRecord: Boolean(source.hasRecord || latestRecord)
      };
    }

    async function fetchLatestScriptGenerationSnapshot(caseId) {
      const response = await R.api(`/test-scripts/test-cases/${caseId}/generation/latest`);
      return normalizeScriptGenerationSnapshot(response);
    }

    async function fetchScriptGenerationHistory(caseId, page, size) {
      const data = await R.api(`/test-scripts/test-cases/${caseId}/generation/records?page=${page}&size=${size}`);
      const records = unwrapPage(data);
      return {
        items: Array.isArray(records) ? records : [],
        pageNumber: Number(data?.pageNumber ?? page) || 0,
        totalPages: Number(data?.totalPages ?? 0) || 0,
        totalElements: Number(data?.totalElements ?? 0) || 0
      };
    }

    async function fetchScriptGenerationRecordDetail(caseId, recordId) {
      return R.api(`/test-scripts/test-cases/${caseId}/generation/records/${encodeURIComponent(recordId)}`);
    }

    async function requestDeleteScriptGenerationRecord(caseId, recordId) {
      return R.api(`/test-scripts/test-cases/${caseId}/generation/records/${encodeURIComponent(recordId)}`, {
        method: 'DELETE'
      });
    }

    async function requestPreviewScriptGenerationRecord(caseId, recordId) {
      const settings = R.getSettings();
      return R.api(`/test-scripts/test-cases/${caseId}/generation/records/${encodeURIComponent(recordId)}/preview`, {
        method: 'POST',
        body: {
          browser: settings.defaultBrowser || 'chromium',
          environment: settings.defaultEnvironment || 'staging'
        }
      });
    }

    async function requestAdoptScriptGenerationRecord(caseId, recordId) {
      return R.api(`/test-scripts/test-cases/${caseId}/generation/records/${encodeURIComponent(recordId)}/adopt`, {
        method: 'POST'
      });
    }

    function openScriptRecordDetailModal(record) {
      const existing = document.getElementById('tc-script-record-detail-modal');
      if (existing) existing.remove();

      const item = record || {};
      const overlay = document.createElement('div');
      overlay.id = 'tc-script-record-detail-modal';
      overlay.className = 'fixed inset-0 z-[120] bg-black/75 backdrop-blur-sm';
      const code = String(item.generatedCode || '').trim() || '// 暂无脚本内容';
      const dependencies = Array.isArray(item.dependencies) ? item.dependencies.filter(Boolean) : [];
      const runCommand = String(item.runCommand || '').trim();
      const adopted = Boolean(item.adopted);
      overlay.innerHTML = `
        <div class="absolute inset-0 flex items-center justify-center p-5">
          <div class="w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-2xl border border-white/10 bg-[#11111a] shadow-2xl flex flex-col">
            <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
              <h3 class="text-base font-semibold text-white">脚本记录详情 · ${R.escapeHtml(item.recordId || '-')}</h3>
              <button data-close class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
            </div>
            <div class="p-5 overflow-y-auto space-y-4">
              <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                <div class="rounded-lg border border-white/10 bg-white/[0.03] p-3">
                  <p class="text-[#71717a]">版本</p>
                  <p class="text-[#e4e4e7] mt-1">V${R.escapeHtml(String(item.version || '-'))}</p>
                </div>
                <div class="rounded-lg border border-white/10 bg-white/[0.03] p-3">
                  <p class="text-[#71717a]">脚本类型</p>
                  <p class="text-[#e4e4e7] mt-1">${R.escapeHtml(item.scriptType || '-')}</p>
                </div>
                <div class="rounded-lg border border-white/10 bg-white/[0.03] p-3">
                  <p class="text-[#71717a]">语言</p>
                  <p class="text-[#e4e4e7] mt-1">${R.escapeHtml(item.language || '-')}</p>
                </div>
                <div class="rounded-lg border border-white/10 bg-white/[0.03] p-3">
                  <p class="text-[#71717a]">生成时间</p>
                  <p class="text-[#e4e4e7] mt-1">${R.escapeHtml(R.formatDateTime(item.generatedAt))}</p>
                </div>
              </div>
              ${item.summary ? `<p class="text-sm text-[#d4d4d8]">${R.escapeHtml(item.summary)}</p>` : ''}
              ${item.feedback ? `<p class="text-xs text-[#a1a1aa]">优化建议：${R.escapeHtml(item.feedback)}</p>` : ''}
              <p class="text-xs ${adopted ? 'text-[#6ee7b7]' : 'text-[#a1a1aa]'}">${adopted ? `已采纳 · ${R.escapeHtml(R.formatDateTime(item.adoptedAt))}` : '未采纳到脚本工作室'}</p>
              ${dependencies.length ? `<div class="flex flex-wrap gap-2">${dependencies.map((dep) => `<span class="px-2 py-0.5 rounded text-[11px] bg-[#0ea5e9]/15 text-[#7dd3fc]">${R.escapeHtml(dep)}</span>`).join('')}</div>` : ''}
              ${runCommand ? `
                <div class="rounded-lg border border-white/10 bg-[#0b0b12] px-3 py-2">
                  <p class="text-[11px] text-[#a1a1aa] mb-1">建议运行命令</p>
                  <code class="text-xs text-[#e4e4e7]">${R.escapeHtml(runCommand)}</code>
                </div>
              ` : ''}
              <pre class="text-xs bg-[#0b0b12] border border-white/10 rounded-lg p-3 max-h-[52vh] overflow-auto whitespace-pre-wrap break-all">${R.escapeHtml(code)}</pre>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const close = () => overlay.remove();
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) close();
      });
      overlay.querySelector('[data-close]')?.addEventListener('click', close);
    }

    async function viewScriptGenerationRecordDetail(recordId) {
      const caseId = Number(scriptGenerationContext.caseId);
      if (!caseId) return;
      const detail = await fetchScriptGenerationRecordDetail(caseId, recordId);
      if (!detail) {
        R.toast('未找到脚本记录详情', 'warning');
        return;
      }
      scriptGenerationContext.selectedRecordId = detail.recordId || recordId;
      scriptGenerationContext.selectedRecord = detail;
      renderScriptGenerationPanel();
      openScriptRecordDetailModal(detail);
    }

    async function deleteScriptGenerationRecord(recordId) {
      const caseId = Number(scriptGenerationContext.caseId);
      if (!caseId) return;
      const confirmed = await R.confirm({
        title: '删除脚本记录',
        message: '确认删除该条脚本生成记录？删除后不可恢复。',
        confirmText: '确认删除',
        tone: 'danger'
      });
      if (!confirmed) return;
      const latest = await requestDeleteScriptGenerationRecord(caseId, recordId);
      scriptGenerationContext.latestSnapshot = normalizeScriptGenerationSnapshot(latest || {});
      if (scriptGenerationContext.selectedRecordId === recordId) {
        scriptGenerationContext.selectedRecordId = null;
        scriptGenerationContext.selectedRecord = null;
      }
      if (scriptGenerationContext.historyPage > 0 && scriptGenerationContext.historyItems.length <= 1) {
        scriptGenerationContext.historyPage -= 1;
      }
      await refreshScriptGenerationHistory();
      const preferredRecordId = scriptGenerationContext.selectedRecordId
        || scriptGenerationContext.historyItems[0]?.recordId
        || scriptGenerationContext.latestSnapshot?.result?.latestRecord?.recordId
        || null;
      if (preferredRecordId) {
        selectScriptHistoryRecord(preferredRecordId);
      }
      renderScriptGenerationPanel();
      R.toast('脚本记录已删除', 'success');
    }

    async function previewScriptGenerationRecord(recordId) {
      const caseId = Number(scriptGenerationContext.caseId);
      if (!caseId) return;
      const execution = await requestPreviewScriptGenerationRecord(caseId, recordId);
      if (!execution?.id) {
        R.toast('预览执行已提交，请稍后在执行中心查看', 'info');
        window.location.href = './execution-hub.html';
        return;
      }
      R.toast(`预览执行已启动：${execution.executionId || execution.id}`, 'success');
      window.location.href = `./execution-hub.html?execution=${encodeURIComponent(execution.id)}`;
    }

    async function adoptScriptGenerationRecord(recordId) {
      const caseId = Number(scriptGenerationContext.caseId);
      if (!caseId) return;
      const detail = scriptGenerationContext.historyItems.find((item) => item.recordId === recordId)
        || scriptGenerationContext.selectedRecord
        || null;
      if (detail?.adopted) {
        R.toast('该记录已采纳', 'info');
        return;
      }
      const confirmed = await R.confirm({
        title: '采纳脚本',
        message: '确认将该脚本采纳到脚本工作室并绑定当前用例？',
        confirmText: '确认采纳',
        tone: 'primary'
      });
      if (!confirmed) return;
      const adopted = await requestAdoptScriptGenerationRecord(caseId, recordId);
      scriptGenerationContext.selectedRecordId = adopted?.recordId || recordId;
      scriptGenerationContext.selectedRecord = adopted || scriptGenerationContext.selectedRecord;
      await refreshScriptGenerationHistory();
      selectScriptHistoryRecord(scriptGenerationContext.selectedRecordId);
      renderScriptGenerationPanel();
      R.toast('脚本已采纳到脚本工作室（待审核）', 'success');
      const scriptId = Number(adopted?.scriptId) || null;
      const jump = await R.confirm({
        title: '已采纳成功',
        message: '是否立即跳转脚本工作室进行二次加工与审核？',
        confirmText: '立即前往',
        cancelText: '稍后再说',
        tone: 'primary'
      });
      if (jump) {
        const params = new URLSearchParams();
        if (scriptId) params.set('script', String(scriptId));
        params.set('testCase', String(caseId));
        window.location.href = `./script-studio.html?${params.toString()}`;
      }
    }

    function renderScriptGenerationEvents(events) {
      const list = Array.isArray(events) ? events.filter(Boolean) : [];
      if (!list.length) {
        return '<p class="text-xs text-[#71717a]">任务已提交，等待执行日志...</p>';
      }
      return `<div class="space-y-2">${list.map((event) => `
        <div class="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2">
          <div class="flex items-center justify-between gap-3">
            <span class="text-[11px] px-2 py-0.5 rounded bg-[#0ea5e9]/20 text-[#7dd3fc]">${R.escapeHtml(String(event.stage || 'EVENT').toUpperCase())}</span>
            <span class="text-[11px] text-[#71717a]">${R.escapeHtml(R.formatDateTime(event.occurredAt))}</span>
          </div>
          <p class="text-xs text-[#d4d4d8] mt-2">${R.escapeHtml(event.message || '-')}</p>
        </div>
      `).join('')}</div>`;
    }

    function ensureScriptGenerationSelection(snapshot) {
      const latestRecord = snapshot?.result?.latestRecord || null;
      if (!latestRecord) return;
      if (!scriptGenerationContext.selectedRecordId) {
        scriptGenerationContext.selectedRecordId = latestRecord.recordId || null;
      }
      if (!scriptGenerationContext.selectedRecord && scriptGenerationContext.selectedRecordId && latestRecord.recordId === scriptGenerationContext.selectedRecordId) {
        scriptGenerationContext.selectedRecord = latestRecord;
      }
      const scriptType = String(latestRecord.scriptType || '').toUpperCase();
      const language = String(latestRecord.language || '').toUpperCase();
      if (scriptType) scriptGenerationContext.selectedScriptType = scriptType;
      if (language) scriptGenerationContext.selectedLanguage = language;
      if (latestRecord.targetUrl && !scriptGenerationContext.targetUrl) {
        scriptGenerationContext.targetUrl = latestRecord.targetUrl;
      }
    }

    function renderScriptGenerationPendingPanel(snapshot) {
      const normalized = normalizeScriptGenerationSnapshot(snapshot);
      ensureScriptGenerationSelection(normalized);
      if (!scriptGenerationPanelBody) return;
      scriptGenerationPanelBody.innerHTML = `
        <section class="rounded-xl border border-[#3b82f6]/30 bg-[#3b82f6]/10 p-4">
          <p class="text-sm text-[#93c5fd]">kun dark 正在生成脚本，请稍候...</p>
          <p class="text-xs text-[#bfdbfe] mt-2">你可以关闭当前面板，生成完成后消息中心会提示，重新打开可继续查看。</p>
          ${normalized.taskId ? `<p class="text-[11px] text-[#93c5fd] mt-3 font-mono">任务ID: ${R.escapeHtml(normalized.taskId)}</p>` : ''}
        </section>
        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <h4 class="text-sm font-semibold text-[#e4e4e7] mb-3">生成过程</h4>
          ${renderScriptGenerationEvents(normalized.events)}
        </section>
      `;
    }

    function renderScriptGenerationFailurePanel(snapshot, message) {
      const normalized = normalizeScriptGenerationSnapshot(snapshot);
      if (!scriptGenerationPanelBody) return;
      scriptGenerationPanelBody.innerHTML = `
        <section class="rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-4">
          <p class="text-sm text-[#fecaca]">脚本生成失败</p>
          <p class="text-xs text-[#fecaca] mt-2">${R.escapeHtml(message || normalized.errorMessage || '请稍后重试')}</p>
          <button data-action="script-regenerate" class="mt-3 px-3 py-1.5 text-sm rounded bg-[#ef4444]/20 text-[#fecaca] hover:bg-[#ef4444]/30">重新生成</button>
        </section>
        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <h4 class="text-sm font-semibold text-[#e4e4e7] mb-3">任务日志</h4>
          ${renderScriptGenerationEvents(normalized.events)}
        </section>
      `;
    }

    function renderScriptHistoryList() {
      const items = scriptGenerationContext.historyItems || [];
      if (!items.length) {
        return '<p class="text-xs text-[#71717a]">暂无历史记录</p>';
      }
      return `<div class="space-y-2">${items.map((item) => {
        const selected = scriptGenerationContext.selectedRecordId && scriptGenerationContext.selectedRecordId === item.recordId;
        const adopted = Boolean(item.adopted);
        return `
          <div class="rounded-lg border px-3 py-2 transition-colors ${selected ? 'border-[#0ea5e9]/40 bg-[#0ea5e9]/10' : 'border-white/10 bg-white/[0.03] hover:bg-white/[0.06]'}">
            <button data-action="script-select-record" data-record-id="${R.escapeHtml(item.recordId || '')}" class="w-full text-left">
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm text-[#f5f5f5]">${R.escapeHtml(item.summary || `版本 V${item.version || '-'}`)}</p>
                <div class="flex items-center gap-2">
                  ${adopted ? '<span class="text-[11px] px-2 py-0.5 rounded bg-[#10b981]/20 text-[#6ee7b7]">已采纳</span>' : ''}
                  <span class="text-[11px] text-[#71717a]">V${R.escapeHtml(String(item.version || '-'))}</span>
                </div>
              </div>
              <p class="text-[11px] text-[#71717a] mt-1">${R.escapeHtml(R.formatDateTime(item.generatedAt))}</p>
              ${item.feedback ? `<p class="text-xs text-[#a1a1aa] mt-1">反馈：${R.escapeHtml(item.feedback)}</p>` : ''}
            </button>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <button data-action="script-view-record" data-record-id="${R.escapeHtml(item.recordId || '')}" class="px-2 py-1 text-[11px] rounded bg-white/10 hover:bg-white/20">查看详情</button>
              <button data-action="script-preview-record" data-record-id="${R.escapeHtml(item.recordId || '')}" class="px-2 py-1 text-[11px] rounded bg-[#0ea5e9]/20 text-[#7dd3fc] hover:bg-[#0ea5e9]/30">运行预览</button>
              <button data-action="script-adopt-record" data-record-id="${R.escapeHtml(item.recordId || '')}" class="px-2 py-1 text-[11px] rounded ${adopted ? 'bg-[#10b981]/10 text-[#6ee7b7] cursor-not-allowed' : 'bg-[#10b981]/20 text-[#6ee7b7] hover:bg-[#10b981]/30'}" ${adopted ? 'disabled' : ''}>${adopted ? '已采纳' : '采纳到工作室'}</button>
              <button data-action="script-delete-record" data-record-id="${R.escapeHtml(item.recordId || '')}" class="px-2 py-1 text-[11px] rounded bg-[#ef4444]/20 text-[#fda4af] hover:bg-[#ef4444]/30">删除</button>
            </div>
          </div>
        `;
      }).join('')}</div>`;
    }

    function renderScriptGenerationPanel(snapshot = scriptGenerationContext.latestSnapshot) {
      const normalized = normalizeScriptGenerationSnapshot(snapshot || {});
      scriptGenerationContext.latestSnapshot = normalized;
      ensureScriptGenerationSelection(normalized);
      if (!scriptGenerationContext.targetUrl) {
        const settings = R.getSettings();
        scriptGenerationContext.targetUrl = settings.defaultTargetUrl || 'https://example.com';
      }
      const supportedLanguages = resolveScriptLanguages(scriptGenerationContext.selectedScriptType);
      if (!supportedLanguages.includes(scriptGenerationContext.selectedLanguage)) {
        scriptGenerationContext.selectedLanguage = supportedLanguages[0] || 'JAVASCRIPT';
      }

      const selectedRecord = scriptGenerationContext.selectedRecord
        || normalized.result?.latestRecord
        || null;
      if (selectedRecord && (!scriptGenerationContext.selectedRecordId || scriptGenerationContext.selectedRecordId === selectedRecord.recordId)) {
        scriptGenerationContext.selectedRecordId = selectedRecord.recordId || scriptGenerationContext.selectedRecordId;
        scriptGenerationContext.selectedRecord = selectedRecord;
      }
      const code = String(scriptGenerationContext.selectedRecord?.generatedCode || '').trim();
      const dependencies = Array.isArray(scriptGenerationContext.selectedRecord?.dependencies)
        ? scriptGenerationContext.selectedRecord.dependencies.filter(Boolean)
        : [];
      const runCommand = String(scriptGenerationContext.selectedRecord?.runCommand || '').trim();
      const hasHistory = scriptGenerationContext.historyTotalElements > 0;

      if (!scriptGenerationPanelBody) return;
      scriptGenerationPanelBody.innerHTML = `
        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label class="block">
              <span class="text-xs text-[#a1a1aa]">脚本框架</span>
              <select id="tc-script-type-select" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]">
                ${Object.entries(SCRIPT_TYPE_LABEL).map(([value, label]) => `<option value="${value}" ${scriptGenerationContext.selectedScriptType === value ? 'selected' : ''}>${R.escapeHtml(label)}</option>`).join('')}
              </select>
            </label>
            <label class="block">
              <span class="text-xs text-[#a1a1aa]">语言</span>
              <select id="tc-script-language-select" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]">
                ${supportedLanguages.map((lang) => `<option value="${lang}" ${scriptGenerationContext.selectedLanguage === lang ? 'selected' : ''}>${R.escapeHtml(lang)}</option>`).join('')}
              </select>
            </label>
            <label class="block">
              <span class="text-xs text-[#a1a1aa]">目标地址</span>
              <input id="tc-script-target-url" value="${R.escapeHtml(scriptGenerationContext.targetUrl || '')}" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]" />
            </label>
          </div>
          <div class="mt-3 flex items-center gap-2">
            <button data-action="script-regenerate" class="px-3 py-1.5 text-sm rounded bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90">${normalized.hasRecord ? '重新生成脚本' : '开始生成脚本'}</button>
            <p class="text-xs text-[#71717a]">${normalized.generatedAt ? `最近生成：${R.escapeHtml(R.formatDateTime(normalized.generatedAt))}` : '尚未生成脚本'}</p>
          </div>
        </section>

        ${normalized.status === 'RUNNING' || normalized.status === 'QUEUED' ? `
          <section class="rounded-xl border border-[#3b82f6]/30 bg-[#3b82f6]/10 p-4">
            <p class="text-sm text-[#93c5fd]">kun dark 正在生成脚本，请稍候...</p>
            <p class="text-xs text-[#bfdbfe] mt-2">生成过程会自动刷新，你可以先关闭面板处理其他工作。</p>
            ${renderScriptGenerationEvents(normalized.events)}
          </section>
        ` : ''}

        ${normalized.status === 'FAILED' ? `
          <section class="rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-4">
            <p class="text-sm text-[#fecaca]">上次生成失败</p>
            <p class="text-xs text-[#fecaca] mt-2">${R.escapeHtml(normalized.errorMessage || '请重新发起生成')}</p>
          </section>
        ` : ''}

        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div class="flex items-center justify-between gap-3">
            <h4 class="text-sm font-semibold text-[#e4e4e7]">脚本结果</h4>
            <div class="flex items-center gap-2">
              ${scriptGenerationContext.selectedRecord ? `<button data-action="script-view-record" data-record-id="${R.escapeHtml(scriptGenerationContext.selectedRecord.recordId || '')}" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20">查看详情</button>` : ''}
              ${scriptGenerationContext.selectedRecord ? `<button data-action="script-preview-record" data-record-id="${R.escapeHtml(scriptGenerationContext.selectedRecord.recordId || '')}" class="px-2 py-1 text-xs rounded bg-[#0ea5e9]/20 text-[#7dd3fc] hover:bg-[#0ea5e9]/30">运行预览</button>` : ''}
              ${scriptGenerationContext.selectedRecord ? `<button data-action="script-adopt-record" data-record-id="${R.escapeHtml(scriptGenerationContext.selectedRecord.recordId || '')}" class="px-2 py-1 text-xs rounded ${scriptGenerationContext.selectedRecord.adopted ? 'bg-[#10b981]/10 text-[#6ee7b7] cursor-not-allowed' : 'bg-[#10b981]/20 text-[#6ee7b7] hover:bg-[#10b981]/30'}" ${scriptGenerationContext.selectedRecord.adopted ? 'disabled' : ''}>${scriptGenerationContext.selectedRecord.adopted ? '已采纳' : '采纳到工作室'}</button>` : ''}
              <button data-action="script-copy-code" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20">复制代码</button>
              <button data-action="script-copy-command" class="px-2 py-1 text-xs rounded bg-[#0ea5e9]/20 text-[#7dd3fc] hover:bg-[#0ea5e9]/30">复制运行命令</button>
            </div>
          </div>
          ${scriptGenerationContext.selectedRecord ? `
            <p class="text-xs text-[#71717a] mt-2">记录 ${R.escapeHtml(scriptGenerationContext.selectedRecord.recordId || '-')} · V${R.escapeHtml(String(scriptGenerationContext.selectedRecord.version || '-'))} · ${R.escapeHtml(R.formatDateTime(scriptGenerationContext.selectedRecord.generatedAt))}</p>
            <p class="text-xs ${scriptGenerationContext.selectedRecord.adopted ? 'text-[#6ee7b7]' : 'text-[#a1a1aa]'} mt-1">${scriptGenerationContext.selectedRecord.adopted ? `已采纳到脚本工作室 · ${R.escapeHtml(R.formatDateTime(scriptGenerationContext.selectedRecord.adoptedAt))}` : '未采纳到脚本工作室'}</p>
            ${dependencies.length ? `<div class="flex flex-wrap gap-2 mt-2">${dependencies.map((dep) => `<span class="px-2 py-0.5 rounded text-[11px] bg-[#0ea5e9]/15 text-[#7dd3fc]">${R.escapeHtml(dep)}</span>`).join('')}</div>` : ''}
            ${runCommand ? `
              <div class="mt-2 rounded-lg border border-white/10 bg-[#0b0b12] px-3 py-2">
                <p class="text-[11px] text-[#a1a1aa] mb-1">建议运行命令</p>
                <code class="text-xs text-[#e4e4e7]">${R.escapeHtml(runCommand)}</code>
              </div>
            ` : ''}
            <pre class="mt-3 text-xs bg-[#0b0b12] border border-white/10 rounded-lg p-3 max-h-[360px] overflow-auto whitespace-pre-wrap break-all">${R.escapeHtml(code || '// 暂无脚本内容')}</pre>
          ` : '<p class="text-xs text-[#71717a] mt-2">暂无脚本结果</p>'}
        </section>

        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <h4 class="text-sm font-semibold text-[#e4e4e7]">优化建议</h4>
          <textarea id="tc-script-feedback-input" rows="3" class="mt-2 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]" placeholder="例如：增加异常路径断言、等待策略、更稳健的选择器"></textarea>
          <div class="mt-3 flex items-center gap-2">
            <button data-action="script-refine" class="px-3 py-1.5 text-sm rounded bg-[#0ea5e9]/20 text-[#7dd3fc] hover:bg-[#0ea5e9]/30">二次优化生成</button>
            <p class="text-xs text-[#71717a]">会基于当前结果和你的建议重新生成新版本。</p>
          </div>
        </section>

        <section class="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div class="flex items-center justify-between gap-3 mb-3">
            <h4 class="text-sm font-semibold text-[#e4e4e7]">历史记录</h4>
            <div class="flex items-center gap-2 text-xs text-[#a1a1aa]">
              <span>每页</span>
              <select id="tc-script-history-size" class="px-2 py-1 bg-white/5 border border-white/10 rounded text-xs focus:outline-none focus:border-[#00d4ff]">
                ${scriptHistoryPageSizeOptions.map((size) => `<option value="${size}" ${scriptGenerationContext.historySize === size ? 'selected' : ''}>${size}</option>`).join('')}
              </select>
            </div>
          </div>
          ${renderScriptHistoryList()}
          <div class="mt-3 flex items-center justify-between gap-3">
            <p class="text-xs text-[#71717a]">共 ${scriptGenerationContext.historyTotalElements} 条，页码 ${scriptGenerationContext.historyTotalPages ? scriptGenerationContext.historyPage + 1 : 0}/${scriptGenerationContext.historyTotalPages}</p>
            <div class="flex items-center gap-2">
              <button data-action="script-history-prev" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed" ${scriptGenerationContext.historyPage <= 0 ? 'disabled' : ''}>上一页</button>
              <button data-action="script-history-next" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed" ${(scriptGenerationContext.historyTotalPages === 0 || scriptGenerationContext.historyPage >= scriptGenerationContext.historyTotalPages - 1) ? 'disabled' : ''}>下一页</button>
            </div>
          </div>
        </section>
        ${hasHistory ? '' : '<p class="text-xs text-[#71717a]">提示：生成成功后会自动保留历史记录，可用于回溯与对比。</p>'}
      `;
    }

    async function refreshScriptGenerationHistory() {
      const caseId = Number(scriptGenerationContext.caseId);
      if (!caseId) return;
      const history = await fetchScriptGenerationHistory(caseId, scriptGenerationContext.historyPage, scriptGenerationContext.historySize);
      scriptGenerationContext.historyItems = history.items;
      scriptGenerationContext.historyPage = history.pageNumber;
      scriptGenerationContext.historyTotalPages = history.totalPages;
      scriptGenerationContext.historyTotalElements = history.totalElements;
      if (scriptGenerationContext.selectedRecordId) {
        const matched = history.items.find((item) => item.recordId === scriptGenerationContext.selectedRecordId);
        if (matched) {
          scriptGenerationContext.selectedRecord = matched;
        } else {
          scriptGenerationContext.selectedRecord = null;
        }
      }
    }

    function selectScriptHistoryRecord(recordId) {
      const normalized = String(recordId || '').trim();
      if (!normalized) return;
      scriptGenerationContext.selectedRecordId = normalized;
      const matched = (scriptGenerationContext.historyItems || []).find((item) => item.recordId === normalized)
        || scriptGenerationContext.latestSnapshot?.result?.latestRecord
        || null;
      scriptGenerationContext.selectedRecord = matched;
    }

    function buildScriptGenerationPayload(options = {}) {
      const targetInput = $('#tc-script-target-url', scriptGenerationPanelBody);
      const targetUrl = String(targetInput?.value || scriptGenerationContext.targetUrl || '').trim();
      scriptGenerationContext.targetUrl = targetUrl || scriptGenerationContext.targetUrl || '';
      return {
        scriptType: scriptGenerationContext.selectedScriptType,
        language: scriptGenerationContext.selectedLanguage,
        targetUrl: scriptGenerationContext.targetUrl || undefined,
        additionalInstructions: options.additionalInstructions || '由测试用例页面触发自动生成'
      };
    }

    async function submitScriptGenerationTask(caseId, payload = {}) {
      return R.api(`/test-scripts/test-cases/${caseId}/generation`, {
        method: 'POST',
        body: payload
      });
    }

    async function submitScriptGenerationRefine(caseId, payload = {}) {
      return R.api(`/test-scripts/test-cases/${caseId}/generation/refine`, {
        method: 'POST',
        body: payload
      });
    }

    async function trackScriptGenerationTask(caseId, pendingSnapshot) {
      const pending = normalizeScriptGenerationSnapshot(pendingSnapshot);
      scriptGenerationContext.activeTaskId = pending.taskId || null;
      scriptGenerationContext.latestSnapshot = pending;
      scriptGenerationContext.tracking = true;
      setCaseScriptGenerationSnapshot(caseId, pending);
      syncScriptGenerateButtonState(caseId);
      renderScriptGenerationPendingPanel(pending);

      const taskId = pending.taskId;
      if (!taskId) {
        scriptGenerationContext.tracking = false;
        return pending;
      }

      let latestTask = pending;
      const startedAt = Date.now();
      const maxDuration = 180000;
      const interval = pending.pollIntervalMs > 0 ? pending.pollIntervalMs : 1500;

      while (Date.now() - startedAt < maxDuration) {
        await new Promise((resolve) => window.setTimeout(resolve, interval));
        const task = normalizeScriptGenerationSnapshot(
          await R.api(`/test-scripts/generation-tasks/${encodeURIComponent(taskId)}`)
        );
        latestTask = task;
        scriptGenerationContext.latestSnapshot = task;
        setCaseScriptGenerationSnapshot(caseId, task);
        syncScriptGenerateButtonState(caseId);
        if (task.status === 'RUNNING' || task.status === 'QUEUED') {
          renderScriptGenerationPendingPanel(task);
          continue;
        }
        if (task.status === 'SUCCEEDED') {
          const latest = await fetchLatestScriptGenerationSnapshot(caseId).catch(() => task);
          scriptGenerationContext.latestSnapshot = latest;
          setCaseScriptGenerationSnapshot(caseId, latest);
          syncScriptGenerateButtonState(caseId);
          await refreshScriptGenerationHistory();
          selectScriptHistoryRecord(latest.result?.latestRecord?.recordId || scriptGenerationContext.selectedRecordId);
          renderScriptGenerationPanel(latest);
          scriptGenerationContext.tracking = false;
          return latest;
        }
        if (task.status === 'FAILED') {
          const latest = await fetchLatestScriptGenerationSnapshot(caseId).catch(() => task);
          setCaseScriptGenerationSnapshot(caseId, latest);
          syncScriptGenerateButtonState(caseId);
          renderScriptGenerationFailurePanel(task, task.errorMessage || '脚本生成失败，请稍后重试');
          scriptGenerationContext.tracking = false;
          return task;
        }
      }

      scriptGenerationContext.tracking = false;
      const latest = await fetchLatestScriptGenerationSnapshot(caseId).catch(() => latestTask);
      setCaseScriptGenerationSnapshot(caseId, latest);
      syncScriptGenerateButtonState(caseId);
      renderScriptGenerationFailurePanel(latestTask, '脚本生成超时，请稍后刷新重试');
      return latestTask;
    }

    async function openScriptGenerationPanel(caseId, options = {}) {
      const id = Number(caseId);
      if (!id) {
        R.toast('无效的测试用例', 'warning');
        return null;
      }
      const panel = ensureScriptGenerationPanel();
      panel.classList.remove('hidden');

      const previousCaseId = Number(scriptGenerationContext.caseId);
      if (!previousCaseId || previousCaseId !== id) {
        const settings = R.getSettings();
        scriptGenerationContext.activeTaskId = null;
        scriptGenerationContext.latestSnapshot = null;
        scriptGenerationContext.historyPage = 0;
        scriptGenerationContext.historySize = 5;
        scriptGenerationContext.historyItems = [];
        scriptGenerationContext.historyTotalPages = 0;
        scriptGenerationContext.historyTotalElements = 0;
        scriptGenerationContext.selectedRecordId = null;
        scriptGenerationContext.selectedRecord = null;
        scriptGenerationContext.targetUrl = settings.defaultTargetUrl || 'https://example.com';
      }

      const item = state.items.find((tc) => tc.id === id) || { id };
      scriptGenerationContext.caseId = id;
      scriptGenerationContext.caseLabel = item.caseNumber || `TC-${id}`;
      if (scriptGenerationPanelTitle) {
        scriptGenerationPanelTitle.textContent = `${scriptGenerationContext.caseLabel} 脚本生成`;
      }

      const forceNew = Boolean(options.forceNew);
      if (!forceNew) {
        const latest = await fetchLatestScriptGenerationSnapshot(id);
        scriptGenerationContext.latestSnapshot = latest;
        setCaseScriptGenerationSnapshot(id, latest);
        syncScriptGenerateButtonState(id);
        await refreshScriptGenerationHistory();
        selectScriptHistoryRecord(latest.result?.latestRecord?.recordId || scriptGenerationContext.selectedRecordId);
        if (latest.status === 'RUNNING' || latest.status === 'QUEUED') {
          return trackScriptGenerationTask(id, latest);
        }
        if (latest.status === 'FAILED') {
          renderScriptGenerationFailurePanel(latest, latest.errorMessage || '上次生成失败，请重新生成');
          return latest;
        }
        if (latest.status === 'SUCCEEDED' && latest.result?.latestRecord) {
          renderScriptGenerationPanel(latest);
          return latest;
        }
      }

      const payload = buildScriptGenerationPayload(options);
      const submitted = await submitScriptGenerationTask(id, payload);
      return trackScriptGenerationTask(id, submitted);
    }

    async function regenerateCurrentScriptGeneration() {
      const caseId = Number(scriptGenerationContext.caseId);
      if (!caseId) {
        R.toast('未找到可操作的测试用例', 'warning');
        return;
      }
      const payload = buildScriptGenerationPayload();
      const submitted = await submitScriptGenerationTask(caseId, payload);
      await trackScriptGenerationTask(caseId, submitted);
    }

    async function submitScriptGenerationFeedback() {
      const caseId = Number(scriptGenerationContext.caseId);
      if (!caseId) {
        R.toast('未找到可操作的测试用例', 'warning');
        return;
      }
      const feedbackInput = $('#tc-script-feedback-input', scriptGenerationPanelBody);
      const feedback = String(feedbackInput?.value || '').trim();
      if (!feedback) {
        R.toast('请输入优化建议', 'warning');
        return;
      }
      const payload = {
        ...buildScriptGenerationPayload(),
        feedback
      };
      const submitted = await submitScriptGenerationRefine(caseId, payload);
      if (feedbackInput) feedbackInput.value = '';
      await trackScriptGenerationTask(caseId, submitted);
    }

    let testCaseEditorModalNode = null;
    let testCaseEditorTitleNode = null;
    let testCaseEditorFormNode = null;
    let testCaseEditorSaveButton = null;
    let testCaseEditorEscHandler = null;
    const testCaseEditorContext = {
      existing: null,
      submitting: false,
      originalStepsInput: ''
    };

    function closeTestCaseEditor() {
      if (!testCaseEditorModalNode) return;
      testCaseEditorModalNode.classList.add('hidden');
      testCaseEditorContext.existing = null;
      testCaseEditorContext.submitting = false;
      testCaseEditorContext.originalStepsInput = '';
      if (testCaseEditorSaveButton) {
        testCaseEditorSaveButton.disabled = false;
        testCaseEditorSaveButton.classList.remove('opacity-50', 'cursor-not-allowed');
      }
    }

    function getEditorField(name) {
      if (!testCaseEditorFormNode) return null;
      return $(`[data-field="${name}"]`, testCaseEditorFormNode);
    }

    function toStepInputText(steps) {
      const source = Array.isArray(steps) ? steps.slice() : [];
      const sorted = source.sort((a, b) => (Number(a?.stepOrder) || 0) - (Number(b?.stepOrder) || 0));
      return sorted.map((step) => {
        const action = String(step?.action || '').trim();
        const expected = String(step?.expectedResult || '').trim();
        const data = String(step?.testData || '').trim();
        return `${action} | ${expected} | ${data}`;
      }).join('\n');
    }

    function parseEditorSteps(rawValue) {
      return String(rawValue || '')
        .split(/\n+/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line, index) => {
          const [action, expectedResult, testData] = line.split('|').map((part) => (part || '').trim());
          return {
            stepOrder: index + 1,
            action: action || `步骤 ${index + 1}`,
            expectedResult: expectedResult || '执行成功',
            testData: testData || ''
          };
        });
    }

    function normalizeStepText(value) {
      return String(value || '')
        .replace(/\r\n/g, '\n')
        .trim();
    }

    function ensureTestCaseEditorModal() {
      if (testCaseEditorModalNode) return testCaseEditorModalNode;

      const typeOptions = Object.entries(CASE_TYPE_LABEL)
        .map(([value, label]) => `<option value="${value}">${R.escapeHtml(label)}</option>`)
        .join('');
      const priorityOrder = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
      const priorityOptions = priorityOrder
        .map((value) => `<option value="${value}">${R.escapeHtml(CASE_PRIORITY_LABEL[value] || value)}</option>`)
        .join('');
      const statusOptions = Object.keys(CASE_STATUS_LABEL)
        .map((value) => `<option value="${value}">${R.escapeHtml(CASE_STATUS_LABEL[value] || value)}</option>`)
        .join('');

      testCaseEditorModalNode = document.createElement('div');
      testCaseEditorModalNode.className = 'hidden fixed inset-0 z-[10880] bg-black/75 backdrop-blur-sm';
      testCaseEditorModalNode.innerHTML = `
        <div class="absolute inset-0 flex items-center justify-center p-4">
          <div class="w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-2xl border border-white/10 bg-[#12121a] shadow-2xl flex flex-col">
            <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
              <h3 id="tc-editor-title" class="text-base font-semibold text-white">编辑测试用例</h3>
              <button id="tc-editor-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
            </div>
            <form id="tc-editor-form" class="flex-1 overflow-y-auto p-5 space-y-4">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label class="block md:col-span-2">
                  <span class="text-xs text-[#a1a1aa]">标题</span>
                  <input data-field="title" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]" placeholder="请输入测试用例标题" />
                </label>
                <label class="block">
                  <span class="text-xs text-[#a1a1aa]">类型</span>
                  <select data-field="testType" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]">${typeOptions}</select>
                </label>
                <label class="block">
                  <span class="text-xs text-[#a1a1aa]">优先级</span>
                  <select data-field="priority" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]">${priorityOptions}</select>
                </label>
                <label class="block">
                  <span class="text-xs text-[#a1a1aa]">状态</span>
                  <select data-field="status" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]">${statusOptions}</select>
                </label>
                <label class="block">
                  <span class="text-xs text-[#a1a1aa]">关联 US ID</span>
                  <input data-field="userStoryId" inputmode="numeric" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]" placeholder="可选，例如 101" />
                  <p data-field="userStoryHint" class="mt-1 text-[11px] text-[#71717a]"></p>
                </label>
              </div>
              <label class="block">
                <span class="text-xs text-[#a1a1aa]">描述</span>
                <textarea data-field="description" rows="3" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]" placeholder="请输入测试目的、范围或场景描述"></textarea>
              </label>
              <label class="block">
                <span class="text-xs text-[#a1a1aa]">前置条件</span>
                <textarea data-field="preconditions" rows="3" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]" placeholder="请输入测试前置条件"></textarea>
              </label>
              <label class="block">
                <span class="text-xs text-[#a1a1aa]">标签</span>
                <input data-field="tags" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-[#00d4ff]" placeholder="例如 smoke,regression" />
              </label>
              <label class="block">
                <span class="text-xs text-[#a1a1aa]">步骤（每行：动作 | 预期 | 数据）</span>
                <textarea data-field="steps" rows="8" class="mt-1 w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-sm font-mono focus:outline-none focus:border-[#00d4ff]" placeholder="打开页面 | 页面正常打开 |"></textarea>
              </label>
            </form>
            <div class="px-5 py-4 border-t border-white/10 flex items-center justify-between gap-2">
              <p class="text-xs text-[#71717a]">保存后将立即刷新列表。</p>
              <div class="flex items-center gap-2">
                <button id="tc-editor-cancel" class="px-3 py-1.5 text-sm rounded bg-white/10 hover:bg-white/20">取消</button>
                <button id="tc-editor-save" class="px-3 py-1.5 text-sm rounded bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90">保存</button>
              </div>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(testCaseEditorModalNode);

      testCaseEditorTitleNode = $('#tc-editor-title', testCaseEditorModalNode);
      testCaseEditorFormNode = $('#tc-editor-form', testCaseEditorModalNode);
      testCaseEditorSaveButton = $('#tc-editor-save', testCaseEditorModalNode);

      $('#tc-editor-close', testCaseEditorModalNode)?.addEventListener('click', closeTestCaseEditor);
      $('#tc-editor-cancel', testCaseEditorModalNode)?.addEventListener('click', closeTestCaseEditor);
      testCaseEditorModalNode.addEventListener('click', (event) => {
        if (event.target === testCaseEditorModalNode) closeTestCaseEditor();
      });
      testCaseEditorSaveButton?.addEventListener('click', (event) => {
        event.preventDefault();
        submitTestCaseEditor().catch((error) => R.toast(error.message || '保存失败', 'error'));
      });
      testCaseEditorFormNode?.addEventListener('submit', (event) => {
        event.preventDefault();
        submitTestCaseEditor().catch((error) => R.toast(error.message || '保存失败', 'error'));
      });

      if (!testCaseEditorEscHandler) {
        testCaseEditorEscHandler = (event) => {
          if (event.key !== 'Escape' || !testCaseEditorModalNode) return;
          if (!testCaseEditorModalNode.classList.contains('hidden')) closeTestCaseEditor();
        };
        document.addEventListener('keydown', testCaseEditorEscHandler);
      }

      return testCaseEditorModalNode;
    }

    function openTestCaseEditor(existing) {
      const modal = ensureTestCaseEditorModal();
      const isEdit = Boolean(existing && existing.id);
      const defaultStepsInput = '打开页面 | 页面正常打开 |\n执行核心操作 | 操作成功 |';
      const currentStepsInput = toStepInputText(existing?.steps) || defaultStepsInput;
      testCaseEditorContext.existing = isEdit ? existing : null;
      testCaseEditorContext.submitting = false;
      testCaseEditorContext.originalStepsInput = currentStepsInput;

      const titleInput = getEditorField('title');
      const descriptionInput = getEditorField('description');
      const preconditionsInput = getEditorField('preconditions');
      const tagsInput = getEditorField('tags');
      const stepsInput = getEditorField('steps');
      const typeSelect = getEditorField('testType');
      const prioritySelect = getEditorField('priority');
      const statusSelect = getEditorField('status');
      const userStoryIdInput = getEditorField('userStoryId');
      const userStoryHint = getEditorField('userStoryHint');

      if (testCaseEditorTitleNode) {
        const caseNumber = existing?.caseNumber || (existing?.id ? `TC-${existing.id}` : '');
        testCaseEditorTitleNode.textContent = isEdit
          ? `${caseNumber || '测试用例'} 详情编辑`
          : '新建测试用例';
      }
      if (testCaseEditorSaveButton) {
        testCaseEditorSaveButton.textContent = isEdit ? '保存修改' : '创建用例';
        testCaseEditorSaveButton.disabled = false;
        testCaseEditorSaveButton.classList.remove('opacity-50', 'cursor-not-allowed');
      }
      if (titleInput) titleInput.value = existing?.title || '';
      if (descriptionInput) descriptionInput.value = existing?.description || '';
      if (preconditionsInput) preconditionsInput.value = existing?.preconditions || '';
      if (tagsInput) tagsInput.value = existing?.tags || (isEdit ? '' : 'smoke');
      if (stepsInput) {
        stepsInput.value = currentStepsInput;
      }
      if (typeSelect) typeSelect.value = existing?.testType || state.type || 'FUNCTIONAL';
      if (prioritySelect) prioritySelect.value = existing?.priority || state.priority || 'MEDIUM';
      if (statusSelect) {
        statusSelect.value = existing?.status || 'DRAFT';
        statusSelect.disabled = !isEdit;
        statusSelect.classList.toggle('opacity-60', !isEdit);
      }
      if (userStoryIdInput) {
        userStoryIdInput.value = existing?.userStory?.id ? String(existing.userStory.id) : '';
        userStoryIdInput.disabled = isEdit;
        userStoryIdInput.classList.toggle('opacity-60', isEdit);
      }
      if (userStoryHint) {
        userStoryHint.textContent = isEdit
          ? '编辑模式下暂不支持修改关联 US，可在 US 页面重新关联。'
          : '可选，不填则创建为未关联 US 的用例。';
      }

      modal.classList.remove('hidden');
      window.setTimeout(() => {
        titleInput?.focus();
        titleInput?.select?.();
      }, 10);
    }

    async function submitTestCaseEditor() {
      if (testCaseEditorContext.submitting) return;
      const existing = testCaseEditorContext.existing;
      const isEdit = Boolean(existing && existing.id);

      const title = String(getEditorField('title')?.value || '').trim();
      const description = String(getEditorField('description')?.value || '').trim();
      const preconditions = String(getEditorField('preconditions')?.value || '').trim();
      const tags = String(getEditorField('tags')?.value || '').trim();
      const rawSteps = String(getEditorField('steps')?.value || '');
      const normalizedRawSteps = normalizeStepText(rawSteps);
      const normalizedOriginalSteps = normalizeStepText(testCaseEditorContext.originalStepsInput);
      const testType = String(getEditorField('testType')?.value || (existing?.testType || state.type || 'FUNCTIONAL')).toUpperCase();
      const priority = String(getEditorField('priority')?.value || (existing?.priority || state.priority || 'MEDIUM')).toUpperCase();
      const status = String(getEditorField('status')?.value || (existing?.status || 'DRAFT')).toUpperCase();
      const userStoryIdRaw = String(getEditorField('userStoryId')?.value || '').trim();

      if (!title) {
        R.toast('标题不能为空', 'warning');
        getEditorField('title')?.focus();
        return;
      }

      const stepsChanged = !isEdit || normalizedRawSteps !== normalizedOriginalSteps;
      const shouldUpdateSteps = !isEdit || stepsChanged;
      const steps = (isEdit && !stepsChanged && Array.isArray(existing?.steps) && existing.steps.length)
        ? existing.steps.map((step, index) => ({
            stepOrder: Number(step?.stepOrder) || (index + 1),
            action: String(step?.action || '').trim() || `步骤 ${index + 1}`,
            expectedResult: String(step?.expectedResult || '').trim() || '执行成功',
            testData: String(step?.testData || '').trim()
          }))
        : parseEditorSteps(rawSteps);
      if (shouldUpdateSteps && !steps.length) {
        R.toast('请至少填写一个测试步骤', 'warning');
        getEditorField('steps')?.focus();
        return;
      }

      let userStoryId;
      if (!isEdit && userStoryIdRaw) {
        const parsedId = Number(userStoryIdRaw);
        if (!Number.isInteger(parsedId) || parsedId <= 0) {
          R.toast('关联 US ID 必须为正整数', 'warning');
          getEditorField('userStoryId')?.focus();
          return;
        }
        userStoryId = parsedId;
      }

      const payload = isEdit
        ? {
            title,
            description,
            preconditions,
            testType,
            priority,
            status,
            ...(shouldUpdateSteps ? { steps } : {}),
            tags
          }
        : {
            title,
            description,
            preconditions,
            testType,
            priority,
            userStoryId: Number.isInteger(userStoryId) ? userStoryId : undefined,
            steps,
            tags
          };

      testCaseEditorContext.submitting = true;
      if (testCaseEditorSaveButton) {
        testCaseEditorSaveButton.disabled = true;
        testCaseEditorSaveButton.classList.add('opacity-50', 'cursor-not-allowed');
      }

      try {
        if (isEdit) {
          await R.api(`/test-cases/${existing.id}`, {
            method: 'PUT',
            body: payload
          });
          closeTestCaseEditor();
          R.toast('测试用例已更新', 'success');
        } else {
          await R.api('/test-cases', {
            method: 'POST',
            body: payload
          });
          closeTestCaseEditor();
          R.toast('测试用例已创建', 'success');
        }
        await loadTestCases();
      } catch (error) {
        if (testCaseEditorSaveButton) {
          testCaseEditorSaveButton.disabled = false;
          testCaseEditorSaveButton.classList.remove('opacity-50', 'cursor-not-allowed');
        }
        testCaseEditorContext.submitting = false;
        throw error;
      }
    }

    async function upsertTestCase(existing) {
      openTestCaseEditor(existing || null);
    }

    async function removeTestCase(id) {
      const confirmed = await R.confirm({
        title: '删除测试用例',
        message: `确认删除测试用例 #${id}？删除后不可恢复。`,
        confirmText: '确认删除',
        tone: 'danger'
      });
      if (!confirmed) return;
      await R.api(`/test-cases/${id}`, { method: 'DELETE' });
      R.toast('测试用例已删除', 'success');
      await loadTestCases();
    }

    async function removeTestCasesBatch() {
      const ids = getSelectedCaseIds();
      if (!ids.length) {
        R.toast('请先勾选要删除的测试用例', 'warning');
        return;
      }

      const confirmed = await R.confirm({
        title: '批量删除测试用例',
        message: `确认删除选中的 ${ids.length} 条测试用例？删除后不可恢复。`,
        confirmText: '确认删除',
        tone: 'danger'
      });
      if (!confirmed) return;

      let successCount = 0;
      const failedIds = [];
      for (const id of ids) {
        try {
          await R.api(`/test-cases/${id}`, { method: 'DELETE' });
          successCount += 1;
        } catch (_error) {
          failedIds.push(id);
        }
      }

      if (successCount > 0) {
        R.toast(`批量删除完成：成功 ${successCount} 条`, 'success');
      }
      if (failedIds.length > 0) {
        R.toast(`删除失败 ${failedIds.length} 条，请稍后重试`, 'warning');
      }

      if (state.page > 0 && successCount >= state.items.length) {
        state.page -= 1;
      }
      await loadTestCases();
    }

    async function updateTestCasesStatusBatch(nextStatus, actionLabel) {
      const ids = getSelectedCaseIds();
      if (!ids.length) {
        R.toast('请先勾选要批量处理的测试用例', 'warning');
        return;
      }

      const statusLabel = CASE_STATUS_LABEL[nextStatus] || nextStatus;
      const confirmed = await R.confirm({
        title: actionLabel,
        message: `确认将选中的 ${ids.length} 条测试用例状态更新为“${statusLabel}”？`,
        confirmText: '确认执行',
        tone: nextStatus === 'ARCHIVED' || nextStatus === 'DEPRECATED' ? 'danger' : 'primary'
      });
      if (!confirmed) return;

      let successCount = 0;
      const failedIds = [];
      for (const id of ids) {
        try {
          await R.api(`/test-cases/${id}`, {
            method: 'PUT',
            body: {
              status: nextStatus
            }
          });
          successCount += 1;
        } catch (_error) {
          failedIds.push(id);
        }
      }

      if (successCount > 0) {
        R.toast(`${actionLabel}完成：成功 ${successCount} 条`, 'success');
      }
      if (failedIds.length > 0) {
        R.toast(`处理失败 ${failedIds.length} 条，请稍后重试`, 'warning');
      }
      await loadTestCases();
    }

    async function batchGenerateScripts() {
      const ids = getSelectedCaseIds();
      if (!ids.length) {
        R.toast('请先勾选要批量生成脚本的用例', 'warning');
        return;
      }

      const runningIds = ids.filter((id) => {
        const snapshot = state.scriptGenerationMetaByCase.get(id);
        const status = String(snapshot?.status || '').toUpperCase();
        return status === 'RUNNING' || status === 'QUEUED' || state.generatingCaseIds.has(id);
      });
      const executableIds = ids.filter((id) => !runningIds.includes(id));
      if (!executableIds.length) {
        R.toast('选中的用例都在脚本生成中，请稍后再试', 'warning');
        return;
      }

      const skipHint = runningIds.length ? `（${runningIds.length} 条已在生成中，将自动跳过）` : '';
      const confirmed = await R.confirm({
        title: '批量生成脚本',
        message: `确认为选中的 ${executableIds.length} 条测试用例生成脚本？${skipHint}`,
        confirmText: '确认生成',
        tone: 'primary'
      });
      if (!confirmed) return;

      const settings = R.getSettings();
      const targetUrl = settings.defaultTargetUrl || 'https://example.com';
      const selectedScriptType = state.selectedScriptType || 'PLAYWRIGHT';
      const selectedLanguage = resolveScriptLanguages(selectedScriptType)[0] || 'JAVASCRIPT';
      let successCount = 0;
      const failedIds = [];
      for (const id of executableIds) {
        try {
          const submitted = await submitScriptGenerationTask(id, {
            scriptType: selectedScriptType,
            language: selectedLanguage,
            targetUrl,
            additionalInstructions: '由测试用例页面触发批量脚本生成'
          });
          setCaseScriptGenerationSnapshot(id, submitted);
          syncScriptGenerateButtonState(id);
          successCount += 1;
        } catch (_error) {
          failedIds.push(id);
        }
      }

      if (successCount > 0) {
        R.toast(`批量脚本生成任务已提交：${successCount}/${executableIds.length}，可在消息中心查看完成通知`, 'success');
      }
      if (failedIds.length > 0) {
        R.toast(`脚本生成提交失败 ${failedIds.length} 条，请稍后重试`, 'warning');
      }
    }

    async function generateScript(caseId) {
      const id = Number(caseId || state.selectedCaseId);
      if (!id) {
        R.toast('请先选择测试用例', 'warning');
        return;
      }
      await openScriptGenerationPanel(id);
    }

    cardsContainer.addEventListener('click', async (event) => {
      const button = event.target.closest('button[data-action]');
      if (!button) return;

      const id = Number(button.dataset.id);
      const action = button.dataset.action;
      const item = state.items.find((tc) => tc.id === id);

      try {
        if (action === 'expand') {
          const target = document.getElementById(button.dataset.target);
          if (target) target.classList.toggle('expanded');
          return;
        }
        if (action === 'generate') {
          state.selectedCaseId = id;
          await openScriptGenerationPanel(id);
          return;
        }
        if (action === 'edit' && item) {
          await upsertTestCase(item);
          return;
        }
        if (action === 'delete') {
          await removeTestCase(id);
        }
      } catch (error) {
        R.toast(error.message || '操作失败', 'error');
      }
    });

    cardsContainer.addEventListener('change', (event) => {
      if (event.target.matches('input[data-case-id]')) {
        syncBatchActionControls();
      }
    });

    prioritySelect.addEventListener('change', async () => {
      state.priority = prioritySelect.value;
      state.page = 0;
      try {
        await loadTestCases();
      } catch (error) {
        R.toast(error.message || '筛选失败', 'error');
      }
    });

    searchInput.addEventListener('input', debounce(async (event) => {
      state.keyword = event.target.value.trim();
      state.page = 0;
      try {
        await loadTestCases();
      } catch (error) {
        R.toast(error.message || '搜索失败', 'error');
      }
    }));

    statusSelect.addEventListener('change', async () => {
      state.status = statusSelect.value;
      state.page = 0;
      try {
        await loadTestCases();
      } catch (error) {
        R.toast(error.message || '筛选失败', 'error');
      }
    });

    typeSelect.addEventListener('change', async () => {
      state.type = typeSelect.value;
      state.page = 0;
      try {
        await loadTestCases();
      } catch (error) {
        R.toast(error.message || '筛选失败', 'error');
      }
    });

    pageSizeSelect?.addEventListener('change', async () => {
      const nextSize = Number(pageSizeSelect.value) || 20;
      state.size = pageSizeOptions.includes(nextSize) ? nextSize : 20;
      state.page = 0;
      try {
        await loadTestCases();
      } catch (error) {
        R.toast(error.message || '分页查询失败', 'error');
      }
    });

    prevPageButton?.addEventListener('click', async () => {
      if (state.page <= 0) return;
      state.page -= 1;
      try {
        await loadTestCases();
      } catch (error) {
        R.toast(error.message || '分页查询失败', 'error');
      }
    });

    nextPageButton?.addEventListener('click', async () => {
      if (state.totalPages && state.page >= state.totalPages - 1) return;
      state.page += 1;
      try {
        await loadTestCases();
      } catch (error) {
        R.toast(error.message || '分页查询失败', 'error');
      }
    });

    function closeBatchActionsMenu() {
      if (batchActionsMenu) batchActionsMenu.classList.add('hidden');
    }

    batchActionsMenu?.addEventListener('click', async (event) => {
      const item = event.target.closest('a[data-action]');
      if (!item) return;
      event.preventDefault();
      closeBatchActionsMenu();
      const action = String(item.dataset.action || '').trim();
      try {
        if (action === 'delete') {
          await removeTestCasesBatch();
          return;
        }
        if (action === 'approve') {
          await updateTestCasesStatusBatch('READY', '批量审批');
          return;
        }
        if (action === 'archive') {
          await updateTestCasesStatusBatch('ARCHIVED', '批量归档');
          return;
        }
        if (action === 'deprecate') {
          await updateTestCasesStatusBatch('DEPRECATED', '批量废弃');
          return;
        }
        if (action === 'generate-script') {
          await batchGenerateScripts();
        }
      } catch (error) {
        R.toast(error.message || '批量操作失败', 'error');
      }
    });
    syncBatchActionControls();

    const usGenerateState = {
      modal: null,
      listNode: null,
      searchNode: null,
      countNode: null,
      selectedNode: null,
      submitNode: null,
      stories: [],
      filteredStories: [],
      selectedIds: new Set(),
      loading: false,
      submitting: false
    };

    function isUsGeneratable(story) {
      const status = String(story?.status || '').toUpperCase();
      return status !== 'ARCHIVED';
    }

    function getUsGenerateSelectedIds() {
      return [...usGenerateState.selectedIds].filter((id) => Number.isInteger(id) && id > 0);
    }

    function syncUsGenerateSummary() {
      const selectedCount = getUsGenerateSelectedIds().length;
      const totalGeneratable = usGenerateState.stories.filter((story) => isUsGeneratable(story)).length;
      if (usGenerateState.selectedNode) {
        usGenerateState.selectedNode.textContent = usGenerateState.loading
          ? '正在加载 US...'
          : `已选 ${selectedCount} / ${totalGeneratable}`;
      }
      if (usGenerateState.submitNode) {
        usGenerateState.submitNode.disabled = usGenerateState.loading || usGenerateState.submitting || selectedCount <= 0;
        usGenerateState.submitNode.classList.toggle('opacity-50', usGenerateState.submitNode.disabled);
        usGenerateState.submitNode.classList.toggle('cursor-not-allowed', usGenerateState.submitNode.disabled);
        usGenerateState.submitNode.textContent = usGenerateState.submitting ? '生成中...' : '开始生成';
      }
    }

    function renderUsGenerateList() {
      if (!usGenerateState.listNode) return;
      if (usGenerateState.loading) {
        usGenerateState.listNode.innerHTML = '<div class="py-10 text-center text-sm text-[#71717a]">正在加载 US 列表...</div>';
        syncUsGenerateSummary();
        return;
      }
      if (!usGenerateState.filteredStories.length) {
        usGenerateState.listNode.innerHTML = '<div class="py-10 text-center text-sm text-[#71717a]">未找到可选 US</div>';
        syncUsGenerateSummary();
        return;
      }

      usGenerateState.listNode.innerHTML = usGenerateState.filteredStories.map((story) => {
        const usId = Number(story?.id) || 0;
        const usNumber = story?.usNumber || `US-${usId}`;
        const title = story?.title || '未命名 US';
        const status = String(story?.status || '').toUpperCase();
        const statusLabel = US_STATUS_LABEL[status] || status || '-';
        const disabled = !isUsGeneratable(story);
        const checked = usGenerateState.selectedIds.has(usId);
        const statusColor = disabled
          ? 'bg-white/10 text-[#a1a1aa]'
          : 'bg-[#00d4ff]/20 text-[#67e8f9]';
        return `
          <label class="flex items-start gap-3 p-3 rounded-lg border border-white/10 bg-white/5 ${disabled ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer hover:bg-white/10'}">
            <input type="checkbox" data-us-checkbox data-us-id="${usId}" class="mt-1 rounded border-white/20 bg-white/5" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-xs text-[#67e8f9] font-medium">${R.escapeHtml(usNumber)}</span>
                <span class="px-2 py-0.5 text-[11px] rounded ${statusColor}">${R.escapeHtml(statusLabel)}</span>
              </div>
              <p class="mt-1 text-sm text-[#e4e4e7] break-words">${R.escapeHtml(title)}</p>
            </div>
          </label>
        `;
      }).join('');
      syncUsGenerateSummary();
    }

    function filterUsGenerateStories() {
      const keyword = String(usGenerateState.searchNode?.value || '').trim().toLowerCase();
      usGenerateState.filteredStories = usGenerateState.stories.filter((story) => {
        if (!keyword) return true;
        const usNumber = String(story?.usNumber || '').toLowerCase();
        const title = String(story?.title || '').toLowerCase();
        return usNumber.includes(keyword) || title.includes(keyword);
      });
      renderUsGenerateList();
    }

    async function fetchAllUserStoriesForGenerate() {
      const size = 100;
      const maxPages = 30;
      const allStories = [];
      for (let page = 0; page < maxPages; page += 1) {
        const response = await R.api(`/user-stories?page=${page}&size=${size}`);
        const list = unwrapPage(response);
        if (Array.isArray(list) && list.length) allStories.push(...list);
        const totalPages = Number(response?.totalPages) || 0;
        const isLastPage = Boolean(response?.last ?? (totalPages > 0 ? page >= totalPages - 1 : list.length < size));
        if (isLastPage) break;
      }
      return allStories;
    }

    async function loadUsGenerateStories() {
      usGenerateState.loading = true;
      renderUsGenerateList();
      try {
        const stories = await fetchAllUserStoriesForGenerate();
        usGenerateState.stories = stories
          .filter((story) => Number.isInteger(Number(story?.id)) && Number(story?.id) > 0)
          .sort((a, b) => Number(b?.id || 0) - Number(a?.id || 0));
        const validIdSet = new Set(usGenerateState.stories.map((story) => Number(story.id)));
        [...usGenerateState.selectedIds].forEach((id) => {
          if (!validIdSet.has(id)) usGenerateState.selectedIds.delete(id);
        });
        filterUsGenerateStories();
      } finally {
        usGenerateState.loading = false;
        renderUsGenerateList();
      }
    }

    function closeUsGenerateModal() {
      if (usGenerateState.modal) usGenerateState.modal.classList.add('hidden');
    }

    async function submitUsCaseGeneration() {
      if (usGenerateState.submitting || usGenerateState.loading) return;
      const selectedIds = getUsGenerateSelectedIds().filter((id) => {
        const story = usGenerateState.stories.find((item) => Number(item?.id) === id);
        return story && isUsGeneratable(story);
      });
      if (!selectedIds.length) {
        R.toast('请至少选择一个可生成的 US', 'warning');
        return;
      }

      const count = Math.max(1, Math.min(20, Number(usGenerateState.countNode?.value) || 3));
      if (usGenerateState.countNode) usGenerateState.countNode.value = String(count);
      usGenerateState.submitting = true;
      syncUsGenerateSummary();

      let success = 0;
      let failed = 0;
      let createdTotal = 0;

      try {
        for (const usId of selectedIds) {
          try {
            const created = await R.api(`/user-stories/${usId}/generate-test-cases`, {
              method: 'POST',
              body: { count }
            });
            success += 1;
            if (Array.isArray(created)) createdTotal += created.length;
          } catch (_error) {
            failed += 1;
          }
        }

        if (success > 0) {
          await loadTestCases();
        }

        const summary = failed > 0
          ? `已完成：成功 ${success} 个 US，失败 ${failed} 个 US`
          : `已完成：${success} 个 US，共生成 ${createdTotal} 条用例`;
        R.toast(summary, failed > 0 ? 'warning' : 'success');
        if (failed === 0) closeUsGenerateModal();
      } finally {
        usGenerateState.submitting = false;
        syncUsGenerateSummary();
      }
    }

    function ensureUsGenerateModal() {
      if (usGenerateState.modal) return usGenerateState.modal;

      const modal = document.createElement('div');
      modal.className = 'hidden fixed inset-0 z-[11120] bg-black/70 backdrop-blur-sm';
      modal.innerHTML = `
        <div class="absolute inset-0 flex items-center justify-center p-4">
          <div class="w-full max-w-3xl rounded-2xl border border-white/10 bg-[#18181f] shadow-2xl overflow-hidden">
            <div class="px-5 py-4 border-b border-white/10 flex items-center justify-between gap-3">
              <div>
                <h3 class="text-base font-semibold text-white">从 US 生成测试用例</h3>
                <p class="text-xs text-[#71717a] mt-1">支持多选 US，数据来源于 US 需求管理</p>
              </div>
              <button data-action="us-generate-close" class="px-2 py-1 text-sm rounded bg-white/10 hover:bg-white/20">关闭</button>
            </div>
            <div class="px-5 py-4 space-y-4">
              <div class="grid grid-cols-1 md:grid-cols-[1fr_auto_auto] gap-3 items-center">
                <div class="relative">
                  <i data-lucide="search" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#71717a]"></i>
                  <input id="tc-us-generate-search" type="text" placeholder="搜索 US 编号或标题..." class="w-full pl-9 pr-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm focus:outline-none focus:border-[#00d4ff]">
                </div>
                <label class="flex items-center gap-2 text-xs text-[#a1a1aa]">
                  <span>每个US生成</span>
                  <input id="tc-us-generate-count" type="number" min="1" max="20" value="3" class="w-16 px-2 py-1 rounded bg-white/5 border border-white/10 text-sm focus:outline-none focus:border-[#00d4ff]">
                  <span>条</span>
                </label>
                <div class="flex items-center justify-end gap-2">
                  <button data-action="us-generate-select-all" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20">全选可生成</button>
                  <button data-action="us-generate-clear" class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20">清空</button>
                </div>
              </div>
              <div id="tc-us-generate-list" class="max-h-[420px] overflow-y-auto space-y-2 pr-1"></div>
            </div>
            <div class="px-5 py-4 border-t border-white/10 flex items-center justify-between gap-3">
              <span id="tc-us-generate-selected" class="text-xs text-[#a1a1aa]">已选 0 / 0</span>
              <div class="flex items-center gap-2">
                <button data-action="us-generate-cancel" class="px-3 py-1.5 text-sm rounded bg-white/10 text-[#d4d4d8] hover:bg-white/20">取消</button>
                <button data-action="us-generate-submit" class="px-3 py-1.5 text-sm rounded bg-[#0ea5e9]/25 text-[#7dd3fc] hover:bg-[#0ea5e9]/35">开始生成</button>
              </div>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
      if (window.lucide) window.lucide.createIcons();

      usGenerateState.modal = modal;
      usGenerateState.listNode = $('#tc-us-generate-list', modal);
      usGenerateState.searchNode = $('#tc-us-generate-search', modal);
      usGenerateState.countNode = $('#tc-us-generate-count', modal);
      usGenerateState.selectedNode = $('#tc-us-generate-selected', modal);
      usGenerateState.submitNode = $('[data-action="us-generate-submit"]', modal);

      const searchHandler = debounce(() => filterUsGenerateStories(), 180);
      usGenerateState.searchNode?.addEventListener('input', searchHandler);

      usGenerateState.listNode?.addEventListener('change', (event) => {
        const checkbox = event.target.closest('input[data-us-checkbox]');
        if (!checkbox) return;
        const usId = Number(checkbox.dataset.usId);
        if (!usId) return;
        if (checkbox.checked) {
          usGenerateState.selectedIds.add(usId);
        } else {
          usGenerateState.selectedIds.delete(usId);
        }
        syncUsGenerateSummary();
      });

      modal.addEventListener('click', (event) => {
        if (event.target === modal) closeUsGenerateModal();
      });

      modal.addEventListener('click', async (event) => {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const action = button.dataset.action;
        if (action === 'us-generate-close' || action === 'us-generate-cancel') {
          closeUsGenerateModal();
          return;
        }
        if (action === 'us-generate-clear') {
          usGenerateState.selectedIds.clear();
          renderUsGenerateList();
          return;
        }
        if (action === 'us-generate-select-all') {
          usGenerateState.filteredStories.forEach((story) => {
            const usId = Number(story?.id);
            if (usId && isUsGeneratable(story)) usGenerateState.selectedIds.add(usId);
          });
          renderUsGenerateList();
          return;
        }
        if (action === 'us-generate-submit') {
          await submitUsCaseGeneration();
        }
      });

      document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape' || !usGenerateState.modal) return;
        if (!usGenerateState.modal.classList.contains('hidden')) {
          closeUsGenerateModal();
        }
      });

      return modal;
    }

    async function openUsGenerateModal() {
      ensureUsGenerateModal();
      usGenerateState.selectedIds.clear();
      if (usGenerateState.searchNode) usGenerateState.searchNode.value = '';
      if (usGenerateState.countNode) usGenerateState.countNode.value = '3';
      usGenerateState.filteredStories = usGenerateState.stories.slice();
      usGenerateState.modal?.classList.remove('hidden');
      await loadUsGenerateStories();
      usGenerateState.searchNode?.focus();
    }

    const menuItems = $$('a', generateMenu);
    menuItems.forEach((item) => {
      item.addEventListener('click', async (event) => {
        event.preventDefault();
        generateMenu.classList.add('hidden');
        const action = String(item.dataset.action || '').trim();
        try {
          if (action === 'from-us') {
            await openUsGenerateModal();
            return;
          }
          if (action === 'manual-create') {
            await upsertTestCase(null);
          }
        } catch (error) {
          R.toast(error.message || '操作失败', 'error');
        }
      });
    });

    window.toggleGenerateMenu = () => generateMenu.classList.toggle('hidden');
    window.toggleBatchActionsMenu = () => {
      if (!batchActionsMenu || !batchActionsButton || batchActionsButton.disabled) return;
      batchActionsMenu.classList.toggle('hidden');
    };
    window.openGenerateModal = () => generateModal.classList.remove('hidden');
    window.closeGenerateModal = () => generateModal.classList.add('hidden');
    window.generateScript = () => generateScript().catch((error) => R.toast(error.message || '生成失败', 'error'));
    window.toggleExpand = (id) => {
      const node = document.getElementById(id);
      if (node) node.classList.toggle('expanded');
    };

    document.addEventListener('click', (event) => {
      if (!event.target.closest('#generate-menu') && !event.target.closest('#tc-generate-menu-button')) {
        generateMenu.classList.add('hidden');
      }
      if (!event.target.closest('#tc-batch-actions-menu') && !event.target.closest('#tc-batch-actions-button')) {
        batchActionsMenu?.classList.add('hidden');
      }
    });

    const frameworkButtons = $$('button', generateModal).filter((btn) => ['Playwright', 'Cypress', 'Selenium'].includes((btn.textContent || '').trim()));
    frameworkButtons.forEach((btn) => {
      btn.addEventListener('click', (event) => {
        event.preventDefault();
        frameworkButtons.forEach((node) => {
          node.classList.remove('bg-[#00d4ff]/20', 'text-[#00d4ff]');
          node.classList.add('bg-white/5');
        });
        btn.classList.remove('bg-white/5');
        btn.classList.add('bg-[#00d4ff]/20', 'text-[#00d4ff]');

        const text = (btn.textContent || '').trim().toUpperCase();
        state.selectedScriptType = text === 'SELENIUM' ? 'SELENIUM' : text === 'CYPRESS' ? 'CYPRESS' : 'PLAYWRIGHT';
      });
    });

    await loadTestCases();
  }

  async function initializeScriptStudioPage() {
    const user = await R.ensureAuth();
    updateUserHeader(user);

    const header = $('main header');
    const columns = $('main .flex-1.flex.overflow-hidden');
    const headerTitleInput = $('header input[type="text"]');
    const saveButton = $$('header .flex.items-center.gap-4 button')[0];
    const runButton = $$('header .flex.items-center.gap-4 button')[1];
    if (!columns || !headerTitleInput || !saveButton || !runButton) return;

    const visualColumn = columns.children[0];
    const codeColumn = columns.children[1];
    const propsColumn = columns.children[2];
    if (!visualColumn || !codeColumn || !propsColumn) return;

    const visualStack = $('div[class*="min-h-[600px]"]', visualColumn);
    const codeHeaderName = $('.h-10 span', codeColumn);
    const codeView = $('pre code', codeColumn);
    const codeButtons = $$('button', codeColumn).slice(0, 2);
    const propsStack = $('.space-y-4', propsColumn);
    const actionTypeSelect = $$('select', propsColumn)[0];
    const actionTargetInput = $$('input', propsColumn)[0];
    const actionTimeoutInput = $$('input', propsColumn)[1];
    const actionDescriptionInput = $$('textarea', propsColumn)[0];
    const actionDeleteButton = $$('button', propsColumn).find((button) => (button.textContent || '').includes('删除动作'));
    const undoButton = header ? $('button[title="撤销"]', header) : null;
    const redoButton = header ? $('button[title="重做"]', header) : null;
    const zoomOutButton = header ? $('button[title="缩小"]', header) : null;
    const zoomInButton = header ? $('button[title="放大"]', header) : null;
    const zoomLabel = header ? $$('span', header).find((node) => /^\d+%$/.test((node.textContent || '').trim())) : null;
    const splitModeButton = header ? $('button[title="分屏"]', header) : null;
    const visualModeButton = header ? $('button[title="仅可视化"]', header) : null;
    const codeModeButton = header ? $('button[title="仅代码"]', header) : null;

    if (!visualStack || !codeHeaderName || !codeView || !propsStack || !actionTypeSelect || !actionTargetInput || !actionTimeoutInput || !actionDescriptionInput || !actionDeleteButton) return;

    codeHeaderName.id = 'studio-file-name';
    codeView.id = 'studio-code-view';
    $$('option', actionTypeSelect).forEach((option) => {
      if (!option.value) option.value = (option.textContent || '').trim();
    });
    if (!$$('option', actionTypeSelect).some((option) => option.value === 'Screenshot')) {
      const screenshotOption = document.createElement('option');
      screenshotOption.value = 'Screenshot';
      screenshotOption.textContent = 'Screenshot';
      actionTypeSelect.appendChild(screenshotOption);
    }

    let configPanel = $('#studio-config-panel', propsColumn);
    if (!configPanel) {
      configPanel = document.createElement('div');
      configPanel.id = 'studio-config-panel';
      configPanel.className = 'pt-4 border-t border-white/5 space-y-3';
      configPanel.innerHTML = `
        <div class="flex items-center justify-between">
          <p class="text-xs text-[#a1a1aa] uppercase tracking-wide">脚本配置</p>
          <button id="studio-new-script" class="px-2 py-1 rounded-lg bg-[#00d4ff]/20 text-[#00d4ff] hover:bg-[#00d4ff]/30 transition-colors text-xs">新建</button>
        </div>
        <div>
          <label class="block text-xs text-[#a1a1aa] mb-1">脚本</label>
          <select id="studio-script-select" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]"></select>
        </div>
        <div>
          <label class="block text-xs text-[#a1a1aa] mb-1">关联测试用例</label>
          <select id="studio-test-case" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]"></select>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <div>
            <label class="block text-xs text-[#a1a1aa] mb-1">脚本类型</label>
            <select id="studio-script-type" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]"></select>
          </div>
          <div>
            <label class="block text-xs text-[#a1a1aa] mb-1">脚本语言</label>
            <select id="studio-language" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]"></select>
          </div>
        </div>
        <div>
          <label class="block text-xs text-[#a1a1aa] mb-1">目标 URL</label>
          <input id="studio-target-url" type="text" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
        </div>
        <div>
          <label class="block text-xs text-[#a1a1aa] mb-1">附加说明</label>
          <textarea id="studio-instructions" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm h-20 resize-none focus:outline-none focus:border-[#00d4ff]"></textarea>
        </div>
        <div class="grid gap-2 pt-1">
          <button id="studio-ai-generate" class="w-full py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 transition-opacity text-sm font-medium">AI 生成脚本</button>
          <button id="studio-submit-review" class="w-full py-2 rounded-lg bg-[#0ea5e9]/20 text-[#7dd3fc] hover:bg-[#0ea5e9]/30 transition-colors text-sm">提交审核</button>
          <button id="studio-approve-script" class="w-full py-2 rounded-lg bg-[#10b981]/20 text-[#6ee7b7] hover:bg-[#10b981]/30 transition-colors text-sm">审核通过</button>
          <button id="studio-delete-script" class="w-full py-2 rounded-lg bg-[#ef4444]/20 text-[#ef4444] hover:bg-[#ef4444]/30 transition-colors text-sm">删除当前脚本</button>
        </div>
        <div id="studio-meta" class="p-3 rounded-lg bg-white/5 text-xs text-[#a1a1aa]">未选择脚本</div>
      `;
      propsStack.appendChild(configPanel);
    }

    const scriptSelect = $('#studio-script-select', configPanel);
    const testCaseSelect = $('#studio-test-case', configPanel);
    const scriptTypeSelect = $('#studio-script-type', configPanel);
    const languageSelect = $('#studio-language', configPanel);
    const targetUrlInput = $('#studio-target-url', configPanel);
    const instructionsInput = $('#studio-instructions', configPanel);
    const aiButton = $('#studio-ai-generate', configPanel);
    const submitReviewButton = $('#studio-submit-review', configPanel);
    const approveButton = $('#studio-approve-script', configPanel);
    const deleteButton = $('#studio-delete-script', configPanel);
    const newButton = $('#studio-new-script', configPanel);
    const metaNode = $('#studio-meta', configPanel);

    if (!scriptSelect || !testCaseSelect || !scriptTypeSelect || !languageSelect || !targetUrlInput || !instructionsInput || !aiButton || !submitReviewButton || !approveButton || !deleteButton || !newButton || !metaNode) return;

    const settings = R.getSettings();
    const studioQuery = new URLSearchParams(window.location.search);
    const preferredScriptIdFromQuery = Number(studioQuery.get('script')) || null;
    const preferredCaseIdFromQuery = Number(studioQuery.get('testCase')) || null;
    let consumedInitialQuerySelection = false;
    const initialFlowMarkup = visualStack.innerHTML;
    const initialCode = (codeView.textContent || '').trim();

    const state = {
      scripts: [],
      testCases: [],
      selectedScriptId: null,
      code: initialCode,
      steps: [],
      currentScriptConfig: {},
      selectedStepIndex: 0,
      syncingStepFields: false,
      undoStack: [],
      redoStack: [],
      canvasZoom: 1,
      layoutMode: 'split',
      activeGenerationTaskId: null,
      generationPollingToken: 0
    };

    function cloneSteps(steps) {
      return Array.isArray(steps) ? steps.map((step) => ({ ...step })) : [];
    }

    function createSnapshot() {
      return {
        code: state.code || '',
        steps: cloneSteps(state.steps),
        selectedStepIndex: state.selectedStepIndex
      };
    }

    function applySnapshot(snapshot) {
      if (!snapshot) return;
      state.code = snapshot.code || '';
      state.steps = cloneSteps(snapshot.steps);
      state.selectedStepIndex = Math.max(0, Math.min(
        state.steps.length ? state.steps.length - 1 : 0,
        Number(snapshot.selectedStepIndex || 0)
      ));
      renderCodePreview();
      renderFlowchart();
      syncActionPanelFromStep();
    }

    function updateHistoryButtons() {
      if (undoButton) {
        undoButton.disabled = state.undoStack.length === 0;
        undoButton.classList.toggle('opacity-50', undoButton.disabled);
      }
      if (redoButton) {
        redoButton.disabled = state.redoStack.length === 0;
        redoButton.classList.toggle('opacity-50', redoButton.disabled);
      }
    }

    function pushUndoSnapshot() {
      state.undoStack.push(createSnapshot());
      if (state.undoStack.length > 120) state.undoStack.shift();
      state.redoStack = [];
      updateHistoryButtons();
    }

    function applyCanvasZoom(nextZoom) {
      state.canvasZoom = Math.max(0.5, Math.min(1.8, Math.round(nextZoom * 100) / 100));
      visualStack.style.transformOrigin = 'top center';
      visualStack.style.transform = `scale(${state.canvasZoom})`;
      visualStack.style.transition = 'transform 0.12s ease';
      if (zoomLabel) {
        zoomLabel.textContent = `${Math.round(state.canvasZoom * 100)}%`;
      }
    }

    function markModeButton(button, active) {
      if (!button) return;
      button.classList.toggle('bg-white/10', active);
      if (!active) button.classList.remove('text-[#00d4ff]');
      if (active) button.classList.add('text-[#00d4ff]');
    }

    function applyLayoutMode(mode) {
      state.layoutMode = mode;
      if (mode === 'visual') {
        visualColumn.style.display = '';
        codeColumn.style.display = 'none';
        propsColumn.style.display = '';
        visualColumn.style.flex = '1';
        codeColumn.style.width = '';
        codeColumn.style.flex = '';
      } else if (mode === 'code') {
        visualColumn.style.display = 'none';
        propsColumn.style.display = 'none';
        codeColumn.style.display = 'flex';
        codeColumn.style.width = '100%';
        codeColumn.style.flex = '1';
      } else {
        visualColumn.style.display = '';
        codeColumn.style.display = 'flex';
        propsColumn.style.display = '';
        visualColumn.style.flex = '1';
        codeColumn.style.width = '';
        codeColumn.style.flex = '';
      }

      markModeButton(splitModeButton, mode === 'split');
      markModeButton(visualModeButton, mode === 'visual');
      markModeButton(codeModeButton, mode === 'code');
    }

    const stepTheme = {
      Navigate: {
        icon: 'globe',
        card: 'border-[#3b82f6]/30',
        iconWrap: 'bg-[#3b82f6]/20',
        iconColor: 'text-[#3b82f6]',
        color: '#3b82f6'
      },
      Wait: {
        icon: 'clock',
        card: 'border-[#00d4ff]/30',
        iconWrap: 'bg-[#00d4ff]/20',
        iconColor: 'text-[#00d4ff]',
        color: '#00d4ff'
      },
      Type: {
        icon: 'type',
        card: 'border-[#7c3aed]/30',
        iconWrap: 'bg-[#7c3aed]/20',
        iconColor: 'text-[#7c3aed]',
        color: '#7c3aed'
      },
      Click: {
        icon: 'mouse-pointer-click',
        card: 'border-[#10b981]/30',
        iconWrap: 'bg-[#10b981]/20',
        iconColor: 'text-[#10b981]',
        color: '#10b981'
      },
      Assert: {
        icon: 'check-square',
        card: 'border-[#f59e0b]/30',
        iconWrap: 'bg-[#f59e0b]/20',
        iconColor: 'text-[#f59e0b]',
        color: '#f59e0b'
      },
      Screenshot: {
        icon: 'camera',
        card: 'border-[#f59e0b]/30',
        iconWrap: 'bg-[#f59e0b]/20',
        iconColor: 'text-[#f59e0b]',
        color: '#f59e0b'
      }
    };

    const keywordSet = new Set([
      'const', 'let', 'var', 'await', 'async', 'if', 'else', 'for', 'while',
      'return', 'function', 'new', 'try', 'catch', 'throw', 'require', 'test', 'expect'
    ]);
    const methodSet = new Set([
      'goto', 'waitForSelector', 'waitForNavigation', 'waitForTimeout', 'fill', 'click',
      'locator', 'toContainText', 'screenshot'
    ]);
    const scriptTypes = ['PLAYWRIGHT', 'SELENIUM', 'CYPRESS', 'APPIUM', 'REST_ASSURED'];
    const languages = ['JAVASCRIPT', 'TYPESCRIPT', 'PYTHON', 'JAVA', 'CSHARP'];
    scriptTypeSelect.innerHTML = scriptTypes.map((type) => `<option value="${type}">${SCRIPT_TYPE_LABEL[type] || type}</option>`).join('');
    languageSelect.innerHTML = languages.map((lang) => `<option value="${lang}">${lang}</option>`).join('');
    targetUrlInput.value = settings.defaultTargetUrl;

    function parseConfig(rawConfig) {
      if (!rawConfig) return {};
      if (typeof rawConfig === 'object') return rawConfig;
      try {
        return JSON.parse(rawConfig);
      } catch (_error) {
        return {};
      }
    }

    function cloneConfigObject(raw) {
      if (!raw || typeof raw !== 'object') return {};
      try {
        return JSON.parse(JSON.stringify(raw));
      } catch (_error) {
        return { ...raw };
      }
    }

    function normalizeInlineText(value) {
      return String(value || '')
        .replace(/\s+/g, ' ')
        .trim();
    }

    function trimStepComment(value) {
      const normalized = normalizeInlineText(String(value || '').replace(/^\/{2,}\s*/, ''));
      return normalized
        .replace(/^step\s*\d+\s*[:：-]?\s*/i, '')
        .replace(/^步骤\s*\d+\s*[:：-]?\s*/i, '')
        .trim();
    }

    function extractQuotedSegment(raw) {
      const text = String(raw || '');
      const match = text.match(/['"`]([^'"`]+)['"`]/);
      return match ? match[1].trim() : '';
    }

    function summarizeExpression(raw, fallback = '') {
      const quoted = extractQuotedSegment(raw);
      if (quoted) return quoted;
      const normalized = normalizeInlineText(String(raw || '').replace(/[;)]$/, ''));
      if (!normalized) return fallback;
      return normalized.length > 80 ? `${normalized.slice(0, 80)}...` : normalized;
    }

    function splitTopLevelArgs(raw) {
      const text = String(raw || '').trim();
      if (!text) return [];
      const args = [];
      let current = '';
      let depth = 0;
      let quote = '';
      let prev = '';

      for (const ch of text) {
        if (quote) {
          current += ch;
          if (ch === quote && prev !== '\\') quote = '';
          prev = ch;
          continue;
        }
        if (ch === '\'' || ch === '"' || ch === '`') {
          quote = ch;
          current += ch;
          prev = ch;
          continue;
        }
        if (ch === '(' || ch === '[' || ch === '{') {
          depth += 1;
          current += ch;
          prev = ch;
          continue;
        }
        if (ch === ')' || ch === ']' || ch === '}') {
          depth = Math.max(0, depth - 1);
          current += ch;
          prev = ch;
          continue;
        }
        if (ch === ',' && depth === 0) {
          if (current.trim()) args.push(current.trim());
          current = '';
          prev = ch;
          continue;
        }
        current += ch;
        prev = ch;
      }
      if (current.trim()) args.push(current.trim());
      return args;
    }

    function extractRootVariable(expression) {
      const match = String(expression || '').trim().match(/^([A-Za-z_$][\w$]*)/);
      return match ? match[1] : '';
    }

    function extractLocatorHint(expression) {
      const text = String(expression || '');
      if (!text) return '';

      let match = text.match(/locator\(\s*(['"`])(.+?)\1/);
      if (match) return match[2].trim();

      match = text.match(/getByRole\(\s*(['"`])(.+?)\1/);
      if (match) {
        const role = match[2].trim();
        const nameRegex = text.match(/name\s*:\s*\/(.+?)\//);
        if (nameRegex) return `role=${role}(${nameRegex[1]})`;
        const nameLiteral = text.match(/name\s*:\s*(['"`])(.+?)\1/);
        if (nameLiteral) return `role=${role}(${nameLiteral[2]})`;
        return `role=${role}`;
      }

      match = text.match(/getByText\(\s*(['"`])(.+?)\1/);
      if (match) return `text=${match[2].trim()}`;

      match = text.match(/getByLabel\(\s*(['"`])(.+?)\1/);
      if (match) return `label=${match[2].trim()}`;

      match = text.match(/querySelector\(\s*(['"`])(.+?)\1/);
      if (match) return match[2].trim();

      return '';
    }

    function resolveSelectorHint(callerExpr, locatorByVar) {
      const root = extractRootVariable(callerExpr);
      if (root && locatorByVar.has(root)) {
        return locatorByVar.get(root);
      }
      return extractLocatorHint(callerExpr);
    }

    function inferStepTypeFromHelper(fnName) {
      const name = String(fnName || '').toLowerCase();
      if (!name) return '';
      if (/navigate|goto|open|visit|login|logout/.test(name)) return 'Navigate';
      if (/click|tap|submit|confirm|save/.test(name)) return 'Click';
      if (/fill|type|input|enter|set/.test(name)) return 'Type';
      if (/assert|verify|check|expect|validate/.test(name)) return 'Assert';
      if (/screenshot|capture|snapshot/.test(name)) return 'Screenshot';
      if (/wait|sleep|poll|load/.test(name)) return 'Wait';
      return '';
    }

    function normalizeStepType(type) {
      const normalized = String(type || '').trim().toUpperCase();
      if (normalized === 'NAVIGATE' || normalized === 'GOTO') return 'Navigate';
      if (normalized === 'CLICK') return 'Click';
      if (normalized === 'TYPE' || normalized === 'FILL' || normalized === 'INPUT') return 'Type';
      if (normalized === 'WAIT') return 'Wait';
      if (normalized === 'ASSERT' || normalized === 'EXPECT') return 'Assert';
      if (normalized === 'SCREENSHOT') return 'Screenshot';
      return 'Wait';
    }

    function describeStep(step) {
      if (!step) return '';
      const type = normalizeStepType(step.type);
      if (type === 'Navigate') return step.target || settings.defaultTargetUrl;
      if (type === 'Click') return step.selector || '#submit';
      if (type === 'Type') return `${step.selector || '#input'} -> ${step.value || ''}`;
      if (type === 'Assert') {
        if (step.selector && step.text) return `${step.selector} -> ${step.text}`;
        if (step.text) return `text visible: ${step.text}`;
        return step.selector || 'assertion';
      }
      if (type === 'Screenshot') return step.path || 'capture.png';
      if (step.selector) return `for ${step.selector}`;
      if (step.description) return step.description;
      return 'for condition';
    }

    function withStepDefaults(rawStep = {}) {
      const step = {
        type: normalizeStepType(rawStep.type || 'Wait'),
        selector: rawStep.selector || '',
        value: rawStep.value || '',
        text: rawStep.text || '',
        target: rawStep.target || '',
        path: rawStep.path || '',
        timeout: Number(rawStep.timeout) > 0 ? Number(rawStep.timeout) : 30000,
        description: rawStep.description || ''
      };
      step.detail = describeStep(step);
      return step;
    }

    function sanitizeStepForStorage(rawStep = {}) {
      const step = withStepDefaults(rawStep);
      return {
        type: step.type,
        selector: step.selector,
        value: step.value,
        text: step.text,
        target: step.target,
        path: step.path,
        timeout: step.timeout,
        description: step.description
      };
    }

    function parseStepsFromStoredConfig(configObject) {
      const source = configObject?.studioFlow?.steps || configObject?.studioSteps || configObject?.steps;
      if (!Array.isArray(source)) return [];
      return source
        .map((item) => withStepDefaults(item))
        .filter(Boolean);
    }

    function looksWeakStepSet(steps) {
      const list = Array.isArray(steps) ? steps : [];
      if (!list.length) return true;
      const types = new Set(list.map((step) => normalizeStepType(step.type)));
      const nonWaitCount = list.filter((step) => normalizeStepType(step.type) !== 'Wait').length;
      if (nonWaitCount === 0) return true;
      if (list.length <= 2 && types.size <= 1) return true;
      return false;
    }

    function compactSteps(steps) {
      const source = Array.isArray(steps) ? steps : [];
      const compacted = [];
      source.forEach((item) => {
        const step = withStepDefaults(item);
        const previous = compacted[compacted.length - 1];
        if (
          previous
          && previous.type === step.type
          && previous.selector === step.selector
          && previous.value === step.value
          && previous.text === step.text
          && previous.target === step.target
          && previous.path === step.path
          && previous.timeout === step.timeout
          && previous.description === step.description
        ) {
          return;
        }
        compacted.push(step);
      });
      return compacted;
    }

    function parseStepFromCodeLine(line, context = {}) {
      const text = String(line || '').trim();
      if (!text) return null;
      const locatorByVar = context.locatorByVar instanceof Map ? context.locatorByVar : new Map();
      const commentHint = String(context.pendingComment || '').trim();

      let match = text.match(/^await\s+(.+?)\.goto\(\s*([\s\S]+)\)\s*;?$/);
      if (match) {
        const args = splitTopLevelArgs(match[2]);
        const target = summarizeExpression(args[0] || '', settings.defaultTargetUrl);
        return withStepDefaults({
          type: 'Navigate',
          target,
          description: commentHint || `导航到 ${target}`
        });
      }

      match = text.match(/^await\s+(.+?)\.waitForSelector\(\s*([\s\S]+)\)\s*;?$/);
      if (match) {
        const args = splitTopLevelArgs(match[2]);
        const selector = summarizeExpression(args[0] || '', resolveSelectorHint(match[1], locatorByVar) || '');
        const timeoutMatch = String(match[2] || '').match(/timeout\s*:\s*(\d+)/i);
        return withStepDefaults({
          type: 'Wait',
          selector,
          timeout: timeoutMatch ? Number(timeoutMatch[1]) : 30000,
          description: commentHint || `等待元素 ${selector || '可见'}`
        });
      }

      match = text.match(/^await\s+(.+?)\.waitForLoadState\(\s*([\s\S]+)\)\s*;?$/);
      if (match) {
        const args = splitTopLevelArgs(match[2]);
        const stateValue = summarizeExpression(args[0] || '', 'load');
        const timeoutMatch = String(match[2] || '').match(/timeout\s*:\s*(\d+)/i);
        return withStepDefaults({
          type: 'Wait',
          selector: `loadState:${stateValue}`,
          timeout: timeoutMatch ? Number(timeoutMatch[1]) : 30000,
          description: commentHint || `等待加载状态 ${stateValue}`
        });
      }

      match = text.match(/^await\s+(.+?)\.waitForTimeout\(\s*(\d+)\s*\)\s*;?$/);
      if (match) {
        return withStepDefaults({
          type: 'Wait',
          timeout: Number(match[2]),
          description: commentHint || `等待 ${match[2]}ms`
        });
      }

      if (/^await\s+.+?\.waitForNavigation\(/.test(text)) {
        return withStepDefaults({
          type: 'Wait',
          selector: 'navigation',
          description: commentHint || '等待页面跳转'
        });
      }

      match = text.match(/^await\s+(.+?)\.waitFor\(\s*([\s\S]+)\)\s*;?$/);
      if (match) {
        const selector = resolveSelectorHint(match[1], locatorByVar);
        const timeoutMatch = String(match[2] || '').match(/timeout\s*:\s*(\d+)/i);
        const stateMatch = String(match[2] || '').match(/state\s*:\s*(['"`])(.+?)\1/i);
        const stateText = stateMatch ? stateMatch[2] : 'ready';
        return withStepDefaults({
          type: 'Wait',
          selector: selector || '',
          timeout: timeoutMatch ? Number(timeoutMatch[1]) : 30000,
          description: commentHint || `${selector ? `等待 ${selector}` : '等待元素'} ${stateText}`
        });
      }

      match = text.match(/^await\s+(.+?)\.(fill|type)\(\s*([\s\S]+)\)\s*;?$/);
      if (match) {
        const caller = match[1];
        const args = splitTopLevelArgs(match[3]);
        const root = extractRootVariable(caller);
        let selector = '';
        let value = '';

        if (root === 'page' && args.length >= 2) {
          selector = summarizeExpression(args[0], resolveSelectorHint(caller, locatorByVar) || '#input');
          value = summarizeExpression(args[1], '');
        } else {
          selector = resolveSelectorHint(caller, locatorByVar) || summarizeExpression(args[0], '#input');
          value = summarizeExpression(args.length >= 2 ? args[1] : args[0], '');
        }

        return withStepDefaults({
          type: 'Type',
          selector,
          value,
          description: commentHint || `输入 ${selector}`
        });
      }

      match = text.match(/^await\s+(.+?)\.(click|check|uncheck|tap|press)\(\s*([\s\S]*)\)\s*;?$/);
      if (match) {
        const caller = match[1];
        const args = splitTopLevelArgs(match[3] || '');
        const root = extractRootVariable(caller);
        const selectorFromCaller = resolveSelectorHint(caller, locatorByVar);
        const selector = (root === 'page' && args.length)
          ? summarizeExpression(args[0], selectorFromCaller || '#submit')
          : (selectorFromCaller || summarizeExpression(args[0], 'element'));
        const actionType = match[2] === 'press' ? 'Type' : 'Click';
        return withStepDefaults({
          type: actionType,
          selector,
          value: match[2] === 'press' ? summarizeExpression(args[0], '') : '',
          description: commentHint || `${actionType === 'Click' ? '点击' : '触发按键'} ${selector}`
        });
      }

      match = text.match(/^await\s+(.+?)\.screenshot\(\s*([\s\S]*)\)\s*;?$/);
      if (match) {
        const pathMatch = String(match[2] || '').match(/path\s*:\s*(['"`])(.+?)\1/);
        const path = pathMatch ? pathMatch[2] : 'capture.png';
        return withStepDefaults({
          type: 'Screenshot',
          path,
          description: commentHint || '截图'
        });
      }

      match = text.match(/^await\s+expect\(([\s\S]+)\)\.([\s\S]+)\s*;?$/);
      if (!match) {
        match = text.match(/^expect\(([\s\S]+)\)\.([\s\S]+)\s*;?$/);
      }
      if (match) {
        const subject = String(match[1] || '');
        const assertion = String(match[2] || '');
        const selector = extractLocatorHint(subject) || '';
        const shouldKeep = /(page|locator|url|text|visible|hidden|content|tohaveurl|tocontaintext|tohavetext|tobevisible|tobehidden|tohavevalue)/i
          .test(`${subject} ${assertion}`);
        if (shouldKeep) {
          return withStepDefaults({
            type: 'Assert',
            selector,
            text: summarizeExpression(assertion, ''),
            description: commentHint || `断言 ${selector || '页面状态'}`
          });
        }
      }

      match = text.match(/^await\s+([A-Za-z_$][\w$]*)\(\s*([\s\S]*)\)\s*;?$/);
      if (match) {
        const helperName = match[1];
        const inferredType = inferStepTypeFromHelper(helperName);
        if (inferredType) {
          const helperArgs = splitTopLevelArgs(match[2] || '')
            .map((item) => summarizeExpression(item, ''))
            .filter((item) => item && item !== 'page');
          return withStepDefaults({
            type: inferredType,
            selector: helperArgs[0] || '',
            value: inferredType === 'Type' ? (helperArgs[1] || '') : '',
            description: commentHint || `调用 ${helperName}`
          });
        }
      }

      return null;
    }

    function parseStepsFromCode(code) {
      const source = String(code || '');
      const lines = source.split('\n');
      const locatorByVar = new Map();
      const parsed = [];
      let pendingComment = '';

      lines.forEach((rawLine) => {
        const line = String(rawLine || '').trim();
        if (!line) return;

        if (line.startsWith('//')) {
          pendingComment = trimStepComment(line);
          return;
        }

        const assignMatch = line.match(/^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([\s\S]+)$/);
        if (assignMatch) {
          const varName = assignMatch[1];
          const locatorHint = extractLocatorHint(assignMatch[2]);
          if (locatorHint) {
            locatorByVar.set(varName, locatorHint);
          }
        }

        const step = parseStepFromCodeLine(line, {
          locatorByVar,
          pendingComment
        });
        if (step) {
          parsed.push(step);
          pendingComment = '';
        }
      });

      const steps = compactSteps(parsed);
      if (steps.length) {
        return steps;
      }

      const fallbackSteps = $$('.action-block', visualStack).map((block) => {
        const lines = $$('p', block);
        return withStepDefaults({
          type: lines[0]?.textContent || 'Wait',
          description: lines[1]?.textContent || ''
        });
      });

      if (fallbackSteps.length) return fallbackSteps;

      return [
        withStepDefaults({ type: 'Navigate', target: settings.defaultTargetUrl, description: '导航到目标页面' }),
        withStepDefaults({ type: 'Wait', description: '等待页面稳定' })
      ];
    }

    function toJsLiteral(value) {
      return String(value ?? '')
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'");
    }

    function buildCodeFromSteps() {
      const testName = toJsLiteral((headerTitleInput.value || '自动化流程').trim() || '自动化流程');
      const lines = [
        "const { test, expect } = require('@playwright/test');",
        '',
        `test('${testName}', async ({ page }) => {`
      ];

      const steps = state.steps.length ? state.steps : parseStepsFromCode(initialCode);
      steps.forEach((rawStep, index) => {
        const step = withStepDefaults(rawStep);
        const label = toJsLiteral(step.description || step.type);
        lines.push(`  // 步骤 ${index + 1}: ${label}`);

        if (step.type === 'Navigate') {
          lines.push(`  await page.goto('${toJsLiteral(step.target || targetUrlInput.value.trim() || settings.defaultTargetUrl)}');`);
        } else if (step.type === 'Click') {
          lines.push(`  await page.click('${toJsLiteral(step.selector || '#submit')}');`);
        } else if (step.type === 'Type') {
          lines.push(`  await page.fill('${toJsLiteral(step.selector || '#input')}', '${toJsLiteral(step.value || '')}');`);
        } else if (step.type === 'Assert') {
          lines.push(`  await expect(page.locator('${toJsLiteral(step.selector || 'body')}')).toContainText('${toJsLiteral(step.text || 'expected')}');`);
        } else if (step.type === 'Screenshot') {
          lines.push(`  await page.screenshot({ path: '${toJsLiteral(step.path || 'capture.png')}' });`);
        } else if (step.selector === 'navigation' || /跳转|navigation/i.test(step.description || '')) {
          lines.push('  await page.waitForNavigation();');
        } else if (step.selector) {
          lines.push(`  await page.waitForSelector('${toJsLiteral(step.selector)}', { timeout: ${step.timeout || 30000} });`);
        } else {
          lines.push(`  await page.waitForTimeout(${step.timeout || 30000});`);
        }

        lines.push('');
      });

      if (lines[lines.length - 1] === '') lines.pop();
      lines.push('});');
      return lines.join('\n');
    }

    function highlightCode(source) {
      const text = String(source || '');
      const tokenRegExp = /\/\/[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\.[A-Za-z_][\w]*|\b[A-Za-z_][\w]*\b/g;
      let output = '';
      let cursor = 0;
      let match = tokenRegExp.exec(text);

      while (match) {
        const token = match[0];
        const offset = match.index;
        if (offset > cursor) {
          output += R.escapeHtml(text.slice(cursor, offset));
        }

        if (token.startsWith('//')) {
          output += `<span class="text-[#71717a]">${R.escapeHtml(token)}</span>`;
        } else if (token.startsWith('"') || token.startsWith('\'') || token.startsWith('`')) {
          output += `<span class="text-[#10b981]">${R.escapeHtml(token)}</span>`;
        } else if (token.startsWith('.')) {
          const method = token.slice(1);
          if (methodSet.has(method)) {
            output += `.<span class="text-[#00d4ff]">${R.escapeHtml(method)}</span>`;
          } else {
            output += R.escapeHtml(token);
          }
        } else if (keywordSet.has(token)) {
          output += `<span class="text-[#7c3aed]">${R.escapeHtml(token)}</span>`;
        } else {
          output += R.escapeHtml(token);
        }

        cursor = tokenRegExp.lastIndex;
        match = tokenRegExp.exec(text);
      }

      if (cursor < text.length) {
        output += R.escapeHtml(text.slice(cursor));
      }
      return output || '<span class="text-[#71717a]">// 暂无脚本代码</span>';
    }

    function getFileExtension(language) {
      if (language === 'TYPESCRIPT') return 'spec.ts';
      if (language === 'PYTHON') return 'py';
      if (language === 'JAVA') return 'java';
      if (language === 'CSHARP') return 'cs';
      return 'spec.js';
    }

    function updateFileName() {
      const slug = (headerTitleInput.value || 'script')
        .trim()
        .toLowerCase()
        .replace(/[^\w\u4e00-\u9fa5-]+/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '') || 'script';
      codeHeaderName.textContent = `${slug}.${getFileExtension(languageSelect.value)}`;
    }

    function renderCodePreview() {
      codeView.innerHTML = highlightCode(state.code);
    }

    function renderFlowchart() {
      if (!state.steps.length) {
        visualStack.innerHTML = initialFlowMarkup;
        if (window.lucide) window.lucide.createIcons();
        return;
      }

      const html = [];
      state.steps.forEach((rawStep, index) => {
        const step = withStepDefaults(rawStep);
        const theme = stepTheme[step.type] || stepTheme.Wait;
        const active = index === state.selectedStepIndex ? 'ring-2 ring-[#00d4ff]/40' : '';
        html.push(`
          <div class="action-block w-64 p-4 rounded-xl bg-[#12121a] border ${theme.card} cursor-pointer ${active}" data-step-index="${index}">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-lg ${theme.iconWrap} flex items-center justify-center">
                <i data-lucide="${theme.icon}" class="w-5 h-5 ${theme.iconColor}"></i>
              </div>
              <div class="flex-1">
                <p class="text-sm font-medium">${R.escapeHtml(step.type)}</p>
                <p class="text-xs text-[#71717a] truncate">${R.escapeHtml(step.detail || '')}</p>
              </div>
            </div>
          </div>
        `);

        if (index < state.steps.length - 1) {
          const nextStep = withStepDefaults(state.steps[index + 1]);
          const nextTheme = stepTheme[nextStep.type] || stepTheme.Wait;
          html.push(`<div class="w-0.5 h-8" style="background: linear-gradient(to bottom, ${theme.color}, ${nextTheme.color});"></div>`);
        }
      });

      visualStack.innerHTML = html.join('');
      if (window.lucide) window.lucide.createIcons();
    }

    function targetTextFromStep(step) {
      if (!step) return '';
      if (step.type === 'Navigate') return step.target || '';
      if (step.type === 'Type') return `${step.selector || ''}${step.value ? ` -> ${step.value}` : ''}`;
      if (step.type === 'Assert') return `${step.selector || ''}${step.text ? ` -> ${step.text}` : ''}`;
      if (step.type === 'Screenshot') return step.path || '';
      return step.selector || '';
    }

    function applyTargetTextToStep(step, rawTarget) {
      const value = rawTarget.trim();
      if (step.type === 'Navigate') {
        step.target = value || settings.defaultTargetUrl;
        return;
      }
      if (step.type === 'Type') {
        const [selector, inputValue] = value.split('->').map((part) => part.trim());
        step.selector = selector || '#input';
        step.value = inputValue || '';
        return;
      }
      if (step.type === 'Assert') {
        const [selector, expectText] = value.split('->').map((part) => part.trim());
        step.selector = selector || 'body';
        step.text = expectText || '';
        return;
      }
      if (step.type === 'Screenshot') {
        step.path = value || 'capture.png';
        return;
      }
      step.selector = value;
    }

    function syncActionPanelFromStep() {
      state.syncingStepFields = true;
      const step = state.steps[state.selectedStepIndex];

      if (!step) {
        actionDeleteButton.disabled = true;
        actionDeleteButton.classList.add('opacity-50', 'cursor-not-allowed');
        actionTargetInput.value = '';
        actionTimeoutInput.value = '30000';
        actionDescriptionInput.value = '';
        state.syncingStepFields = false;
        return;
      }

      actionDeleteButton.disabled = false;
      actionDeleteButton.classList.remove('opacity-50', 'cursor-not-allowed');
      actionTypeSelect.value = step.type;
      actionTargetInput.value = targetTextFromStep(step);
      actionTimeoutInput.value = String(step.timeout || 30000);
      actionDescriptionInput.value = step.description || step.detail || '';
      state.syncingStepFields = false;
    }

    function setSelectedStep(index) {
      if (!state.steps.length) return;
      const nextIndex = Math.max(0, Math.min(state.steps.length - 1, index));
      state.selectedStepIndex = nextIndex;
      renderFlowchart();
      syncActionPanelFromStep();
    }

    function syncCodeFromSteps() {
      state.code = buildCodeFromSteps();
      renderCodePreview();
      renderFlowchart();
      syncActionPanelFromStep();
    }

    function renderScriptOptions() {
      const options = [
        '<option value="">新建脚本</option>',
        ...state.scripts.map((script) => `<option value="${script.id}">${R.escapeHtml(script.name || `Script-${script.id}`)}</option>`)
      ];
      scriptSelect.innerHTML = options.join('');
      scriptSelect.value = state.selectedScriptId ? String(state.selectedScriptId) : '';
    }

    function renderTestCaseOptions() {
      if (!state.testCases.length) {
        testCaseSelect.innerHTML = '<option value="">暂无测试用例</option>';
        return;
      }
      testCaseSelect.innerHTML = state.testCases.map((tc) =>
        `<option value="${tc.id}">${R.escapeHtml(tc.caseNumber || tc.id)} - ${R.escapeHtml(tc.title || '')}</option>`
      ).join('');
    }

    function updateReviewActionState(script) {
      const status = String(script?.status || '').toUpperCase();
      const hasScript = Boolean(script?.id);
      submitReviewButton.disabled = !hasScript || ['TESTING', 'PRODUCTION'].includes(status);
      approveButton.disabled = !hasScript || status === 'PRODUCTION';

      submitReviewButton.classList.toggle('opacity-50', submitReviewButton.disabled);
      submitReviewButton.classList.toggle('cursor-not-allowed', submitReviewButton.disabled);
      approveButton.classList.toggle('opacity-50', approveButton.disabled);
      approveButton.classList.toggle('cursor-not-allowed', approveButton.disabled);

      if (!hasScript) {
        submitReviewButton.textContent = '提交审核';
        approveButton.textContent = '审核通过';
        return;
      }
      submitReviewButton.textContent = status === 'TESTING' ? '审核中' : (status === 'PRODUCTION' ? '已审核通过' : '提交审核');
      approveButton.textContent = status === 'PRODUCTION' ? '已审核通过' : '审核通过';
    }

    async function updateCurrentScriptStatus(nextStatus, successMessage) {
      if (!state.selectedScriptId) {
        R.toast('请先选择脚本', 'warning');
        return;
      }
      await R.api(`/test-scripts/${state.selectedScriptId}`, {
        method: 'PUT',
        body: { status: nextStatus }
      });
      R.toast(successMessage, 'success');
      await loadData();
    }

    function fillEditor(script) {
      state.selectedScriptId = script?.id ?? null;
      renderScriptOptions();
      scriptSelect.value = state.selectedScriptId ? String(state.selectedScriptId) : '';

      headerTitleInput.value = script?.name || '新脚本';
      scriptTypeSelect.value = script?.scriptType || 'PLAYWRIGHT';
      languageSelect.value = script?.language || 'JAVASCRIPT';
      testCaseSelect.value = String(script?.testCase?.id || state.testCases[0]?.id || '');

      const config = parseConfig(script?.config);
      state.currentScriptConfig = cloneConfigObject(config);
      targetUrlInput.value = config.targetUrl || settings.defaultTargetUrl;
      instructionsInput.value = '';

      const configuredSteps = parseStepsFromStoredConfig(config);
      const cachedCode = localStorage.getItem('autotest_last_generated_script') || '';
      state.code = (script?.code || cachedCode || initialCode || '').trim();
      if (!state.code) {
        state.steps = configuredSteps.length ? configuredSteps : parseStepsFromCode(initialCode);
        state.code = buildCodeFromSteps();
      } else {
        const parsedSteps = parseStepsFromCode(state.code);
        state.steps = (looksWeakStepSet(parsedSteps) && configuredSteps.length)
          ? configuredSteps
          : parsedSteps;
      }
      state.selectedStepIndex = 0;

      updateFileName();
      renderCodePreview();
      renderFlowchart();
      syncActionPanelFromStep();

      metaNode.textContent = script
        ? `ID: ${script.id} · 状态: ${script.status || '-'} · 更新时间: ${R.formatDateTime(script.updatedAt)}`
        : '未选择脚本，保存时将创建新脚本';
      updateReviewActionState(script);

      state.undoStack = [];
      state.redoStack = [];
      updateHistoryButtons();
    }

    async function loadData() {
      const [casesData, scriptsData] = await Promise.all([
        R.api('/test-cases?page=0&size=200'),
        R.api('/test-scripts?page=0&size=200')
      ]);

      state.testCases = unwrapPage(casesData);
      state.scripts = unwrapPage(scriptsData);
      renderTestCaseOptions();
      renderScriptOptions();

      if (!consumedInitialQuerySelection) {
        consumedInitialQuerySelection = true;
        if (preferredScriptIdFromQuery) {
          const preferredByScript = state.scripts.find((item) => item.id === preferredScriptIdFromQuery);
          if (preferredByScript) {
            fillEditor(preferredByScript);
            return;
          }
        }
        if (preferredCaseIdFromQuery) {
          const preferredByCase = state.scripts.find((item) => Number(item?.testCase?.id) === preferredCaseIdFromQuery);
          if (preferredByCase) {
            fillEditor(preferredByCase);
            return;
          }
        }
      }

      if (state.selectedScriptId) {
        const current = state.scripts.find((item) => item.id === state.selectedScriptId);
        if (current) {
          fillEditor(current);
          return;
        }
      }

      fillEditor(state.scripts[0] || null);
    }

    function applyGeneratedCodeToEditor(generatedCode) {
      if (!String(generatedCode || '').trim()) return;
      pushUndoSnapshot();
      state.code = generatedCode;
      state.steps = parseStepsFromCode(state.code);
      state.selectedStepIndex = 0;
      localStorage.setItem('autotest_last_generated_script', state.code);
      renderCodePreview();
      renderFlowchart();
      syncActionPanelFromStep();
    }

    async function pollStudioScriptGeneration(taskId, testCaseId) {
      if (!taskId) return;
      const pollingToken = ++state.generationPollingToken;
      state.activeGenerationTaskId = taskId;

      const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
      while (state.activeGenerationTaskId === taskId && pollingToken === state.generationPollingToken) {
        await sleep(1500);
        let task;
        try {
          task = await R.api(`/test-scripts/generation-tasks/${encodeURIComponent(taskId)}`);
        } catch (error) {
          metaNode.textContent = `脚本生成任务查询失败：${error.message || '请稍后重试'}`;
          return;
        }

        const status = String(task?.status || '').toUpperCase();
        const events = Array.isArray(task?.events) ? task.events : [];
        const latestEvent = events.length ? events[events.length - 1] : null;
        if (status === 'RUNNING' || status === 'QUEUED') {
          metaNode.textContent = `脚本生成中（任务 ${taskId}）${latestEvent?.message ? `：${latestEvent.message}` : ''}`;
          continue;
        }

        state.activeGenerationTaskId = null;
        if (status === 'FAILED') {
          const message = task?.errorMessage || latestEvent?.message || '脚本生成失败，请重试';
          metaNode.textContent = `脚本生成失败：${message}`;
          R.toast(message, 'error');
          return;
        }

        if (status === 'SUCCEEDED') {
          let latestSnapshot = null;
          try {
            latestSnapshot = await R.api(`/test-scripts/test-cases/${testCaseId}/generation/latest`);
          } catch (_error) {
            // ignore latest query failure and fallback to task payload
          }
          const latestRecord = latestSnapshot?.result?.latestRecord
            || task?.result?.latestRecord
            || null;
          applyGeneratedCodeToEditor(latestRecord?.generatedCode || '');
          const deps = Array.isArray(latestRecord?.dependencies) ? latestRecord.dependencies.filter(Boolean) : [];
          metaNode.textContent = latestRecord?.runCommand
            ? `AI 已生成脚本，依赖: ${deps.join(', ') || '-'}，运行命令: ${latestRecord.runCommand}`
            : `AI 已生成脚本，依赖: ${deps.join(', ') || '-'}`;
          R.toast('AI 脚本生成完成，可在消息中心查看通知', 'success');
          await loadData();
          return;
        }

        metaNode.textContent = `脚本生成状态：${status || 'UNKNOWN'}`;
        return;
      }
    }

    async function saveScript() {
      const name = (headerTitleInput.value || '').trim();
      const testCaseId = Number(testCaseSelect.value);
      if (!name) {
        R.toast('脚本名称不能为空', 'warning');
        return;
      }
      if (!testCaseId) {
        R.toast('请选择关联测试用例', 'warning');
        return;
      }
      if (!state.code.trim()) {
        state.code = buildCodeFromSteps();
      }

      const nextConfig = cloneConfigObject(state.currentScriptConfig);
      nextConfig.targetUrl = targetUrlInput.value.trim() || settings.defaultTargetUrl;
      nextConfig.studioFlow = {
        version: 1,
        updatedAt: new Date().toISOString(),
        steps: (state.steps || []).map((step) => sanitizeStepForStorage(step))
      };

      const payload = {
        name,
        scriptType: scriptTypeSelect.value,
        language: languageSelect.value,
        code: state.code,
        config: JSON.stringify(nextConfig)
      };

      if (state.selectedScriptId) {
        await R.api(`/test-scripts/${state.selectedScriptId}`, {
          method: 'PUT',
          body: {
            name: payload.name,
            code: payload.code,
            config: payload.config,
            status: 'READY'
          }
        });
        R.toast('脚本已更新', 'success');
      } else {
        const created = await R.api('/test-scripts', {
          method: 'POST',
          body: {
            ...payload,
            testCaseId
          }
        });
        state.selectedScriptId = created?.id || null;
        R.toast('脚本已创建', 'success');
      }

      await loadData();
    }

    async function deleteCurrentScript() {
      if (!state.selectedScriptId) {
        R.toast('当前没有可删除脚本', 'warning');
        return;
      }
      const confirmed = await R.confirm({
        title: '删除脚本',
        message: '确认删除当前脚本？删除后不可恢复。',
        confirmText: '确认删除',
        tone: 'danger'
      });
      if (!confirmed) return;
      await R.api(`/test-scripts/${state.selectedScriptId}`, { method: 'DELETE' });
      state.selectedScriptId = null;
      R.toast('脚本已删除', 'success');
      await loadData();
    }

    async function generateWithAI() {
      const testCaseId = Number(testCaseSelect.value);
      if (!testCaseId) {
        R.toast('请选择测试用例', 'warning');
        return;
      }

      const submitted = await R.api(`/test-scripts/test-cases/${testCaseId}/generation`, {
        method: 'POST',
        body: {
          scriptType: scriptTypeSelect.value,
          language: languageSelect.value,
          targetUrl: targetUrlInput.value.trim() || settings.defaultTargetUrl,
          additionalInstructions: instructionsInput.value.trim()
        }
      });

      const taskId = String(submitted?.taskId || '').trim();
      metaNode.textContent = taskId
        ? `脚本生成任务已提交（${taskId}），正在后台生成...`
        : '脚本生成任务已提交，正在后台生成...';
      R.toast('AI 脚本任务已提交，可继续处理其他工作', 'info');
      if (!taskId) return;
      pollStudioScriptGeneration(taskId, testCaseId).catch((error) => {
        metaNode.textContent = `脚本生成异常：${error.message || '请稍后重试'}`;
      });
    }

    async function runCurrentScript() {
      const testCaseId = Number(testCaseSelect.value);
      if (!testCaseId) {
        R.toast('请选择测试用例后再运行', 'warning');
        return;
      }

      const settingsNow = R.getSettings();
      const execution = await R.api('/executions', {
        method: 'POST',
        body: {
          testCaseId,
          scriptId: state.selectedScriptId || undefined,
          browser: settingsNow.defaultBrowser || 'chromium',
          environment: settingsNow.defaultEnvironment || 'staging'
        }
      });

      await R.api(`/executions/${execution.id}/start`, { method: 'POST' });
      R.toast(`执行已启动: ${execution.executionId}`, 'success');
      window.location.href = `./execution-hub.html?execution=${encodeURIComponent(execution.id)}`;
    }

    function handleStepFieldChange() {
      if (state.syncingStepFields) return;
      if (!state.steps.length) {
        state.steps = [withStepDefaults({ type: actionTypeSelect.value })];
        state.selectedStepIndex = 0;
      }

      pushUndoSnapshot();
      const current = withStepDefaults(state.steps[state.selectedStepIndex]);
      current.type = normalizeStepType(actionTypeSelect.value);
      current.timeout = Number(actionTimeoutInput.value) > 0 ? Number(actionTimeoutInput.value) : 30000;
      current.description = (actionDescriptionInput.value || '').trim();
      applyTargetTextToStep(current, actionTargetInput.value || '');
      current.detail = describeStep(current);
      state.steps[state.selectedStepIndex] = current;
      syncCodeFromSteps();
    }

    visualStack.addEventListener('click', (event) => {
      const block = event.target.closest('.action-block[data-step-index]');
      if (!block) return;
      const stepIndex = Number(block.dataset.stepIndex);
      if (Number.isNaN(stepIndex)) return;
      setSelectedStep(stepIndex);
    });

    const paletteButtons = $$('div.fixed button[title]').filter((button) =>
      ['Navigate', 'Click', 'Type', 'Wait', 'Assert', 'Screenshot'].includes(button.getAttribute('title'))
    );
    paletteButtons.forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        pushUndoSnapshot();
        const type = normalizeStepType(button.getAttribute('title'));
        state.steps.push(withStepDefaults({ type }));
        state.selectedStepIndex = state.steps.length - 1;
        syncCodeFromSteps();
      });
    });

    actionTypeSelect.addEventListener('change', handleStepFieldChange);
    actionTargetInput.addEventListener('input', debounce(handleStepFieldChange, 120));
    actionTimeoutInput.addEventListener('input', debounce(handleStepFieldChange, 120));
    actionDescriptionInput.addEventListener('input', debounce(handleStepFieldChange, 120));

    actionDeleteButton.addEventListener('click', (event) => {
      event.preventDefault();
      if (!state.steps.length) {
        R.toast('当前没有可删除动作', 'warning');
        return;
      }
      pushUndoSnapshot();
      state.steps.splice(state.selectedStepIndex, 1);
      if (!state.steps.length) {
        state.steps = [withStepDefaults({ type: 'Wait', description: '等待页面稳定' })];
      }
      state.selectedStepIndex = Math.min(state.selectedStepIndex, state.steps.length - 1);
      syncCodeFromSteps();
    });

    scriptSelect.addEventListener('change', () => {
      const id = Number(scriptSelect.value);
      if (!id) {
        state.selectedScriptId = null;
        fillEditor(null);
        return;
      }
      const script = state.scripts.find((item) => item.id === id);
      if (script) fillEditor(script);
    });

    newButton.addEventListener('click', () => {
      state.selectedScriptId = null;
      fillEditor(null);
    });

    aiButton.addEventListener('click', () => generateWithAI().catch((error) => R.toast(error.message || '生成失败', 'error')));
    submitReviewButton.addEventListener('click', () => {
      updateCurrentScriptStatus('TESTING', '脚本已提交审核').catch((error) => R.toast(error.message || '提交审核失败', 'error'));
    });
    approveButton.addEventListener('click', () => {
      updateCurrentScriptStatus('PRODUCTION', '脚本已审核通过，可在执行中心执行').catch((error) => R.toast(error.message || '审核操作失败', 'error'));
    });
    deleteButton.addEventListener('click', () => deleteCurrentScript().catch((error) => R.toast(error.message || '删除失败', 'error')));

    saveButton.addEventListener('click', (event) => {
      event.preventDefault();
      saveScript().catch((error) => R.toast(error.message || '保存失败', 'error'));
    });

    runButton.addEventListener('click', (event) => {
      event.preventDefault();
      runCurrentScript().catch((error) => R.toast(error.message || '执行失败', 'error'));
    });

    headerTitleInput.addEventListener('input', () => updateFileName());
    languageSelect.addEventListener('change', () => updateFileName());

    if (codeButtons[0]) {
      codeButtons[0].addEventListener('click', async () => {
        await navigator.clipboard.writeText(state.code || '');
        R.toast('代码已复制', 'success');
      });
    }

    if (codeButtons[1]) {
      codeButtons[1].addEventListener('click', () => {
        const payload = state.code || '';
        const blob = new Blob([payload], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${(headerTitleInput.value || 'script').replace(/\s+/g, '-').toLowerCase()}.${getFileExtension(languageSelect.value)}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      });
    }

    codeView.addEventListener('dblclick', () => {
      const nextCode = window.prompt('编辑脚本代码（确认后会同步流程图）', state.code || '');
      if (nextCode === null) return;
      pushUndoSnapshot();
      state.code = nextCode;
      state.steps = parseStepsFromCode(state.code);
      state.selectedStepIndex = 0;
      renderCodePreview();
      renderFlowchart();
      syncActionPanelFromStep();
    });

    if (undoButton) {
      undoButton.addEventListener('click', () => {
        if (!state.undoStack.length) {
          R.toast('没有可撤销的操作', 'warning');
          return;
        }
        const snapshot = state.undoStack.pop();
        state.redoStack.push(createSnapshot());
        applySnapshot(snapshot);
        updateHistoryButtons();
      });
    }

    if (redoButton) {
      redoButton.addEventListener('click', () => {
        if (!state.redoStack.length) {
          R.toast('没有可重做的操作', 'warning');
          return;
        }
        const snapshot = state.redoStack.pop();
        state.undoStack.push(createSnapshot());
        applySnapshot(snapshot);
        updateHistoryButtons();
      });
    }

    if (zoomOutButton) {
      zoomOutButton.addEventListener('click', () => applyCanvasZoom(state.canvasZoom - 0.1));
    }
    if (zoomInButton) {
      zoomInButton.addEventListener('click', () => applyCanvasZoom(state.canvasZoom + 0.1));
    }

    if (splitModeButton) splitModeButton.addEventListener('click', () => applyLayoutMode('split'));
    if (visualModeButton) visualModeButton.addEventListener('click', () => applyLayoutMode('visual'));
    if (codeModeButton) codeModeButton.addEventListener('click', () => applyLayoutMode('code'));

    const paletteMoreButton = $$('div.fixed button[title]').find((button) => button.getAttribute('title') === '更多');
    if (paletteMoreButton) {
      paletteMoreButton.addEventListener('click', (event) => {
        event.preventDefault();
        R.toast('动作库扩展入口已预留', 'info');
      });
    }

    applyCanvasZoom(1);
    applyLayoutMode('split');
    updateHistoryButtons();

    await loadData();
  }

  async function initializeExecutionHubPage() {
    const user = await R.ensureAuth();
    updateUserHeader(user);

    const header = $('main header');
    const selects = $$('select', header);
    const [caseSelect, envSelect, browserSelect] = selects;
    const startButton = $('#start-btn');
    const stopButton = $('#stop-btn');
    const progressBar = $('#progress-bar');
    const statusIndicator = $('#status-indicator');
    const statusText = $('#status-text');
    const etaNode = $('#eta');
    const logContainer = $('#log-container');
    const waterfallContainer = $('#waterfall-container');
    const autoScrollIcon = $('#autoscroll-icon');
    const screenshotLink = $('#execution-screenshots-view-all');
    const screenshotGrid = $('#execution-screenshot-grid');
    const timelineList = $('#execution-timeline-list');
    const videoPanel = $('#execution-video-panel');
    const videoEmpty = $('#execution-video-empty');
    const videoPlayer = $('#execution-video-player');
    const videoMeta = $('#execution-video-meta');
    const videoOpenBtn = $('#execution-video-open');
    const videoDownloadBtn = $('#execution-video-download');

    if (!caseSelect || !envSelect || !browserSelect || !startButton || !stopButton) return;

    let scriptSelect = $('#execution-script-select', header);
    if (!scriptSelect) {
      scriptSelect = document.createElement('select');
      scriptSelect.id = 'execution-script-select';
      scriptSelect.className = 'px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]';
      scriptSelect.style.minWidth = '180px';
      scriptSelect.style.maxWidth = '240px';
      scriptSelect.style.flex = '0 1 220px';
      caseSelect.insertAdjacentElement('afterend', scriptSelect);
    }

    const settings = R.getSettings();
    envSelect.innerHTML = [
      '<option value="staging">Staging 环境</option>',
      '<option value="dev">Dev 环境</option>',
      '<option value="prod">Prod 环境</option>'
    ].join('');
    browserSelect.innerHTML = [
      '<option value="chromium">Chrome</option>',
      '<option value="firefox">Firefox</option>',
      '<option value="webkit">Safari</option>'
    ].join('');
    envSelect.value = settings.defaultEnvironment || 'staging';
    browserSelect.value = settings.defaultBrowser || 'chromium';

    const state = {
      testCases: [],
      scripts: [],
      recentExecutions: [],
      currentExecution: null,
      pollTimer: null,
      autoScroll: true,
      logLines: [],
      logCursor: new Map(),
      currentExecutionKey: null,
      assetObjectUrlByPath: new Map()
    };

    function revokeExecutionAssetUrls() {
      state.assetObjectUrlByPath.forEach((url) => {
        if (typeof url === 'string' && url.startsWith('blob:')) {
          URL.revokeObjectURL(url);
        }
      });
      state.assetObjectUrlByPath.clear();
    }

    async function resolveExecutionAssetUrl(path) {
      const normalized = String(path || '').trim();
      if (!normalized) return '';
      if (!normalized.startsWith('/api/')) return normalized;
      if (state.assetObjectUrlByPath.has(normalized)) {
        return state.assetObjectUrlByPath.get(normalized) || '';
      }
      const token = R.getAccessToken();
      const response = await fetch(normalized, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!response.ok) {
        throw new Error(`资源加载失败(${response.status})`);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      state.assetObjectUrlByPath.set(normalized, objectUrl);
      return objectUrl;
    }

    async function hydrateExecutionAssetImages(root) {
      if (!root) return;
      const imageNodes = $$('img[data-auth-path]', root);
      if (!imageNodes.length) return;
      await Promise.all(imageNodes.map(async (node) => {
        const path = String(node.dataset.authPath || '').trim();
        if (!path) return;
        try {
          const url = await resolveExecutionAssetUrl(path);
          if (url) {
            node.src = url;
          }
        } catch (_error) {
          node.classList.add('opacity-20');
        }
      }));
    }

    function syncCaseSelectTooltip() {
      const selected = caseSelect.selectedOptions && caseSelect.selectedOptions.length
        ? caseSelect.selectedOptions[0]
        : null;
      caseSelect.title = selected ? String(selected.textContent || '').trim() : '';
    }

    function scriptStatusLabel(status) {
      const normalized = String(status || '').toUpperCase();
      if (normalized === 'PRODUCTION') return '审核通过';
      if (normalized === 'TESTING') return '待审核';
      if (normalized === 'READY') return '可执行';
      if (normalized === 'DRAFT') return '草稿';
      if (normalized === 'DEPRECATED') return '废弃';
      return normalized || '-';
    }

    function syncScriptOptionsByCase() {
      if (!scriptSelect) return;
      const caseId = Number(caseSelect.value);
      const scripts = state.scripts.filter((item) => Number(item?.testCase?.id) === caseId);
      if (!scripts.length) {
        scriptSelect.innerHTML = '<option value="">无关联脚本</option>';
        scriptSelect.title = '无关联脚本';
        return;
      }
      scriptSelect.innerHTML = scripts.map((script) => `
        <option value="${script.id}" ${String(script.status || '').toUpperCase() === 'PRODUCTION' ? 'selected' : ''}>
          ${R.escapeHtml(script.name || `Script-${script.id}`)} · ${R.escapeHtml(scriptStatusLabel(script.status))}
        </option>
      `).join('');
      const selected = scriptSelect.selectedOptions && scriptSelect.selectedOptions.length
        ? scriptSelect.selectedOptions[0]
        : null;
      scriptSelect.title = selected ? String(selected.textContent || '').trim() : '';
    }

    function pushLog(line, type = 'info') {
      const prefix = type === 'error'
        ? 'log-error'
        : type === 'success'
          ? 'log-success'
          : type === 'warn'
            ? 'log-warn'
            : 'log-info';
      state.logLines.push({ line, type: prefix });
      if (state.logLines.length > 200) state.logLines.splice(0, state.logLines.length - 200);
      renderLogs();
    }

    function renderLogs() {
      logContainer.innerHTML = state.logLines.map((item) =>
        `<div class="${item.type}">${R.escapeHtml(item.line)}</div>`
      ).join('');
      if (state.autoScroll) {
        logContainer.scrollTop = logContainer.scrollHeight;
      }
    }

    function renderScreenshots(execution) {
      if (!screenshotGrid) return;
      const screenshots = Array.isArray(execution?.screenshots) ? execution.screenshots : [];
      if (!screenshots.length) {
        screenshotGrid.innerHTML = `
          <div class="col-span-3 aspect-video bg-white/5 rounded-lg overflow-hidden flex items-center justify-center text-[#71717a]">
            <div class="flex items-center gap-2 text-sm">
              <i data-lucide="image" class="w-4 h-4"></i>
              <span>暂无执行截图</span>
            </div>
          </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return;
      }

      screenshotGrid.innerHTML = screenshots.slice(0, 9).map((shot, index) => {
        const type = String(shot.type || '').toUpperCase();
        const failed = type.includes('FAIL') || type.includes('ERROR');
        const badge = failed ? '失败' : '成功';
        const path = String(shot.filePath || '').trim();
        const isImage = path.startsWith('data:image/') || path.startsWith('http://') || path.startsWith('https://') || path.startsWith('/');
        const authImage = isImage && path.startsWith('/api/');
        const fileName = path.startsWith('data:image/')
          ? `inline-${index + 1}.png`
          : (path.split('/').filter(Boolean).pop() || `step-${index + 1}.png`);
        return `
          <button type="button" data-shot-index="${index}" class="aspect-video bg-white/5 rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-[#00d4ff] transition-all text-left relative">
            ${isImage ? `<img ${authImage ? `data-auth-path="${R.escapeHtml(path)}"` : `src="${R.escapeHtml(path)}"`} alt="screenshot-${index + 1}" class="absolute inset-0 w-full h-full object-cover opacity-90" />` : ''}
            <div class="absolute inset-0 flex flex-col justify-between p-2">
              <div class="self-start px-2 py-0.5 rounded text-[10px] ${failed ? 'bg-[#ef4444]/20 text-[#ef4444]' : 'bg-[#10b981]/20 text-[#10b981]'}">${badge}</div>
              <div class="text-[10px] text-[#d1d5db] truncate">${R.escapeHtml(fileName)}</div>
            </div>
          </button>
        `;
      }).join('');
      void hydrateExecutionAssetImages(screenshotGrid);
    }

    function renderTimeline(execution) {
      if (!timelineList) return;
      const timeline = Array.isArray(execution?.timeline) ? execution.timeline : [];
      if (!timeline.length) {
        timelineList.innerHTML = '<div class="p-2 rounded-lg bg-white/5">暂无时间线数据</div>';
        return;
      }

      timelineList.innerHTML = timeline.map((step) => {
        const status = String(step.status || '').toUpperCase();
        const color = status === 'FAILED'
          ? '#ef4444'
          : status === 'RUNNING'
            ? '#3b82f6'
            : status === 'PENDING'
              ? '#f59e0b'
              : '#10b981';
        return `
          <div class="p-2 rounded-lg bg-white/5 border border-white/10">
            <div class="flex items-center justify-between gap-2">
              <p class="text-xs font-medium">${R.escapeHtml(String(step.stepOrder || '-'))}. ${R.escapeHtml(step.stepName || '未命名步骤')}</p>
              <span class="text-[10px] px-1.5 py-0.5 rounded" style="background:${color}33;color:${color};">${R.escapeHtml(step.status || 'UNKNOWN')}</span>
            </div>
            <p class="text-[10px] text-[#71717a] mt-1">${R.escapeHtml(step.details || '-')} · ${R.escapeHtml(R.formatDurationMs(step.duration || 0))}</p>
          </div>
        `;
      }).join('');
    }

    function resetExecutionVideo() {
      if (!videoPanel || !videoPlayer || !videoEmpty || !videoMeta) return;
      videoPlayer.pause();
      videoPlayer.removeAttribute('src');
      videoPlayer.classList.add('hidden');
      videoEmpty.classList.remove('hidden');
      videoMeta.textContent = '暂无录屏文件';
      videoPanel.dataset.videoPath = '';
      videoPanel.dataset.videoUrl = '';
    }

    async function renderExecutionVideo(execution) {
      if (!videoPanel || !videoPlayer || !videoEmpty || !videoMeta) return;
      const videoPath = String(execution?.videoPath || '').trim();
      if (!videoPath) {
        resetExecutionVideo();
        return;
      }
      try {
        const resolvedUrl = await resolveExecutionAssetUrl(videoPath);
        if (!resolvedUrl) {
          resetExecutionVideo();
          return;
        }
        videoPlayer.src = resolvedUrl;
        videoPlayer.classList.remove('hidden');
        videoEmpty.classList.add('hidden');
        videoPanel.dataset.videoPath = videoPath;
        videoPanel.dataset.videoUrl = resolvedUrl;
        const fileName = videoPath.split('/').filter(Boolean).pop() || 'execution-video.webm';
        videoMeta.textContent = `录屏文件: ${fileName}`;
      } catch (_error) {
        resetExecutionVideo();
        videoMeta.textContent = '录屏加载失败';
      }
    }

    function renderWaterfall(executions) {
      if (!executions.length) {
        waterfallContainer.innerHTML = '<div class="text-sm text-[#71717a]">暂无执行记录</div>';
        return;
      }

      const maxDuration = Math.max(...executions.map((item) => Number(item.duration || 1000)), 1000);
      waterfallContainer.innerHTML = executions.slice(0, 8).map((execution, index) => {
        const width = Math.max(8, Math.round((Number(execution.duration || 1000) / maxDuration) * 80));
        const color = execution.result === 'PASS'
          ? '#10b981'
          : execution.result === 'FAIL' || execution.status === 'FAILED'
            ? '#ef4444'
            : execution.status === 'RUNNING'
              ? '#3b82f6'
              : '#f59e0b';
        return `
          <div class="flex items-center gap-4">
            <div class="w-36 text-sm truncate">${R.escapeHtml(execution.testCase?.caseNumber || execution.executionId || `EX-${index + 1}`)}</div>
            <div class="flex-1 h-8 bg-white/5 rounded-full overflow-hidden relative">
              <div class="waterfall-bar absolute h-full rounded-full" style="left: ${index * 2}%; width: ${width}%; background:${color};"></div>
            </div>
            <div class="w-20 text-xs text-[#71717a] text-right">${R.escapeHtml(R.formatDurationMs(execution.duration))}</div>
          </div>
        `;
      }).join('');
    }

    function updateStatsByExecutions(executions) {
      const total = executions.length;
      const pass = executions.filter((item) => item.result === 'PASS').length;
      const fail = executions.filter((item) => item.result === 'FAIL' || item.status === 'FAILED').length;
      const skip = executions.filter((item) => item.result === 'SKIP').length;

      $('#stat-total').textContent = `${total}/${total}`;
      $('#stat-pass').textContent = String(pass);
      $('#stat-fail').textContent = String(fail);
      $('#stat-skip').textContent = String(skip);
    }

    function updateCurrentExecutionUI(execution) {
      const executionKey = execution?.id
        ? `id-${execution.id}`
        : execution?.executionId
          ? `execution-${execution.executionId}`
          : 'unknown';
      const switchedExecution = state.currentExecutionKey !== executionKey;
      if (switchedExecution) {
        state.currentExecutionKey = executionKey;
        state.logLines = [];
        renderLogs();
      }
      state.currentExecution = execution;
      if (switchedExecution) {
        revokeExecutionAssetUrls();
      }

      const status = execution?.status || 'PENDING';
      const statusMap = {
        PENDING: '#a1a1aa',
        QUEUED: '#f59e0b',
        RUNNING: '#3b82f6',
        COMPLETED: '#10b981',
        FAILED: '#ef4444',
        CANCELLED: '#ef4444',
        TIMEOUT: '#ef4444'
      };

      statusIndicator.className = 'w-3 h-3 rounded-full';
      statusIndicator.style.background = statusMap[status] || '#a1a1aa';
      const statusLabel = EXEC_STATUS_LABEL[status] || status;
      const modeLabel = execution?.previewMode ? '预览执行' : '正式执行';
      statusText.textContent = `${statusLabel} · ${modeLabel}`;

      let progress = 10;
      if (status === 'QUEUED') progress = 25;
      if (status === 'RUNNING') progress = 65;
      if (status === 'COMPLETED' || status === 'FAILED' || status === 'CANCELLED' || status === 'TIMEOUT') progress = 100;
      progressBar.style.width = `${progress}%`;

      etaNode.textContent = execution?.duration ? R.formatDurationMs(execution.duration) : '--:--';

      if (status === 'RUNNING' || status === 'QUEUED' || status === 'PENDING') {
        startButton.classList.add('hidden');
        stopButton.classList.remove('hidden');
      } else {
        startButton.classList.remove('hidden');
        stopButton.classList.add('hidden');
      }

      if (execution?.logs) {
        const lines = String(execution.logs).split(/\n+/).filter(Boolean);
        const processed = switchedExecution ? 0 : (state.logCursor.get(executionKey) || 0);
        lines.slice(processed).forEach((line) =>
          pushLog(`[${R.formatDateTime(new Date())}] ${line}`, /FAIL|ERROR|Exception/i.test(line) ? 'error' : 'info')
        );
        state.logCursor.set(executionKey, lines.length);
      }

      if (switchedExecution && execution?.scriptName) {
        pushLog(`[${R.formatDateTime(new Date())}] 关联脚本: ${execution.scriptName} (${execution.scriptStatus || '-'})`, 'info');
      }

      renderScreenshots(execution);
      renderTimeline(execution);
      void renderExecutionVideo(execution);
    }

    async function loadCasesAndExecutions() {
      const [casesPage, recent, scriptsPage] = await Promise.all([
        R.api('/test-cases?page=0&size=200'),
        R.api('/executions/recent?limit=20'),
        R.api('/test-scripts?page=0&size=300')
      ]);

      state.testCases = unwrapPage(casesPage);
      state.recentExecutions = Array.isArray(recent) ? recent : [];
      state.scripts = unwrapPage(scriptsPage);

      caseSelect.innerHTML = state.testCases.map((tc) =>
        `<option value="${tc.id}">${R.escapeHtml(tc.caseNumber || tc.id)} - ${R.escapeHtml(tc.title || '')}</option>`
      ).join('');
      syncCaseSelectTooltip();
      syncScriptOptionsByCase();

      renderWaterfall(state.recentExecutions);
      updateStatsByExecutions(state.recentExecutions);

      if (state.recentExecutions.length) {
        updateCurrentExecutionUI(state.recentExecutions[0]);
      } else {
        state.currentExecution = null;
        state.currentExecutionKey = null;
        state.logLines = [];
        state.logCursor.clear();
        renderLogs();
        renderScreenshots(null);
        renderTimeline(null);
        void renderExecutionVideo(null);
      }
    }

    async function pollCurrentExecution() {
      if (!state.currentExecution?.id) return;
      try {
        const latest = await R.api(`/executions/${state.currentExecution.id}`);
        updateCurrentExecutionUI(latest);

        if (!['RUNNING', 'QUEUED', 'PENDING'].includes(latest.status)) {
          window.clearInterval(state.pollTimer);
          state.pollTimer = null;
          await loadCasesAndExecutions();
        }
      } catch (error) {
        R.toast(error.message || '轮询执行状态失败', 'error');
      }
    }

    async function startExecution() {
      const testCaseId = Number(caseSelect.value);
      if (!testCaseId) {
        R.toast('请选择测试用例', 'warning');
        return;
      }
      const scriptId = Number(scriptSelect?.value);
      const selectedScript = state.scripts.find((item) => Number(item.id) === scriptId) || null;
      if (!selectedScript || !scriptId) {
        R.toast('该用例暂无可执行脚本，请先在脚本工作室采纳并审核通过', 'warning');
        return;
      }
      const normalizedStatus = String(selectedScript.status || '').toUpperCase();
      if (!['PRODUCTION', 'READY'].includes(normalizedStatus)) {
        R.toast('当前脚本未审核通过，请先在脚本工作室完成审核', 'warning');
        return;
      }

      const created = await R.api('/executions', {
        method: 'POST',
        body: {
          testCaseId,
          scriptId,
          browser: browserSelect.value,
          environment: envSelect.value
        }
      });

      pushLog(`[${R.formatDateTime(new Date())}] 创建执行任务: ${created.executionId}`, 'info');

      const started = await R.api(`/executions/${created.id}/start`, { method: 'POST' });
      pushLog(`[${R.formatDateTime(new Date())}] 开始执行: ${started.executionId}`, 'success');
      updateCurrentExecutionUI(started);

      if (state.pollTimer) window.clearInterval(state.pollTimer);
      state.pollTimer = window.setInterval(() => {
        pollCurrentExecution().catch(() => null);
      }, 2500);
    }

    async function stopExecution() {
      if (!state.currentExecution?.id) {
        R.toast('当前没有可停止执行', 'warning');
        return;
      }
      await R.api(`/executions/${state.currentExecution.id}/cancel`, { method: 'POST' });
      pushLog(`[${R.formatDateTime(new Date())}] 已取消执行: ${state.currentExecution.executionId}`, 'warn');
      if (state.pollTimer) {
        window.clearInterval(state.pollTimer);
        state.pollTimer = null;
      }
      const latest = await R.api(`/executions/${state.currentExecution.id}`);
      updateCurrentExecutionUI(latest);
      await loadCasesAndExecutions();
    }

    function toggleAutoScroll() {
      state.autoScroll = !state.autoScroll;
      if (state.autoScroll) {
        autoScrollIcon.classList.add('text-[#00d4ff]');
        autoScrollIcon.classList.remove('text-[#71717a]');
      } else {
        autoScrollIcon.classList.remove('text-[#00d4ff]');
        autoScrollIcon.classList.add('text-[#71717a]');
      }
    }

    const clearButton = $$('button', logContainer.parentElement).find((btn) => (btn.title || '').includes('清空'));
    if (clearButton) {
      clearButton.addEventListener('click', () => {
        state.logLines = [];
        if (state.currentExecutionKey) state.logCursor.set(state.currentExecutionKey, 0);
        renderLogs();
      });
    }

    function openExecutionScreenshotModal(shot, index, total) {
      if (!shot) return;
      const existing = document.getElementById('execution-shot-modal');
      if (existing) existing.remove();
      const path = String(shot.filePath || '').trim();
      const isImage = path.startsWith('data:image/') || path.startsWith('http://') || path.startsWith('https://') || path.startsWith('/');
      const overlay = document.createElement('div');
      overlay.id = 'execution-shot-modal';
      overlay.className = 'fixed inset-0 z-[115] bg-black/80 backdrop-blur-sm';
      overlay.innerHTML = `
        <div class="absolute inset-0 flex items-center justify-center p-4">
          <div class="w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-2xl border border-white/10 bg-[#12121a] flex flex-col">
            <div class="px-4 py-3 border-b border-white/10 flex items-center justify-between gap-2">
              <p class="text-sm text-white">截图 ${index + 1}/${total} · Step ${R.escapeHtml(String(shot.stepNumber || index + 1))} ${R.escapeHtml(shot.stepName || '')}</p>
              <button data-close class="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20">关闭</button>
            </div>
            <div class="p-4 overflow-auto">
              ${isImage ? `<img ${path.startsWith('/api/') ? `data-auth-path="${R.escapeHtml(path)}"` : `src="${R.escapeHtml(path)}"`} alt="execution-screenshot" class="w-full rounded-lg border border-white/10 bg-black/30" />` : `<pre class="text-xs text-[#d1d5db] bg-[#0b0b12] border border-white/10 rounded-lg p-3 overflow-auto">${R.escapeHtml(JSON.stringify(shot, null, 2))}</pre>`}
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      void hydrateExecutionAssetImages(overlay);
      const close = () => overlay.remove();
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) close();
      });
      overlay.querySelector('[data-close]')?.addEventListener('click', close);
    }

    if (screenshotLink) {
      screenshotLink.addEventListener('click', (event) => {
        event.preventDefault();
        const screenshots = Array.isArray(state.currentExecution?.screenshots) ? state.currentExecution.screenshots : [];
        if (!screenshots.length) {
          R.toast('当前执行暂无截图', 'warning');
          return;
        }
        openExecutionScreenshotModal(screenshots[0], 0, screenshots.length);
      });
    }

    if (screenshotGrid) {
      screenshotGrid.addEventListener('click', (event) => {
        const card = event.target.closest('button[data-shot-index]');
        if (!card) return;
        const index = Number(card.dataset.shotIndex);
        if (Number.isNaN(index)) return;
        const screenshots = Array.isArray(state.currentExecution?.screenshots) ? state.currentExecution.screenshots : [];
        const shot = screenshots[index];
        if (!shot) return;
        openExecutionScreenshotModal(shot, index, screenshots.length);
      });
    }

    if (videoOpenBtn) {
      videoOpenBtn.addEventListener('click', async () => {
        const path = String(videoPanel?.dataset.videoPath || '').trim();
        if (!path) {
          R.toast('当前执行暂无录屏', 'warning');
          return;
        }
        try {
          const resolvedUrl = await resolveExecutionAssetUrl(path);
          if (!resolvedUrl) {
            R.toast('录屏地址不可用', 'warning');
            return;
          }
          window.open(resolvedUrl, '_blank', 'noopener');
        } catch (_error) {
          R.toast('录屏加载失败', 'error');
        }
      });
    }

    if (videoDownloadBtn) {
      videoDownloadBtn.addEventListener('click', async () => {
        const path = String(videoPanel?.dataset.videoPath || '').trim();
        if (!path) {
          R.toast('当前执行暂无录屏', 'warning');
          return;
        }
        try {
          const resolvedUrl = await resolveExecutionAssetUrl(path);
          if (!resolvedUrl) {
            R.toast('录屏地址不可用', 'warning');
            return;
          }
          const fileName = path.split('/').filter(Boolean).pop() || 'execution-video.webm';
          const anchor = document.createElement('a');
          anchor.href = resolvedUrl;
          anchor.download = fileName;
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
        } catch (_error) {
          R.toast('录屏下载失败', 'error');
        }
      });
    }

    window.startExecution = () => startExecution().catch((error) => R.toast(error.message || '启动失败', 'error'));
    window.stopExecution = () => stopExecution().catch((error) => R.toast(error.message || '停止失败', 'error'));
    window.toggleAutoScroll = () => toggleAutoScroll();
    caseSelect.addEventListener('change', () => {
      syncCaseSelectTooltip();
      syncScriptOptionsByCase();
    });
    if (scriptSelect) {
      scriptSelect.addEventListener('change', () => {
        const selected = scriptSelect.selectedOptions && scriptSelect.selectedOptions.length
          ? scriptSelect.selectedOptions[0]
          : null;
        scriptSelect.title = selected ? String(selected.textContent || '').trim() : '';
      });
    }

    const params = new URLSearchParams(window.location.search);
    const executionIdParam = params.get('execution');

    await loadCasesAndExecutions();

    if (executionIdParam) {
      try {
        const execution = await R.api(`/executions/${encodeURIComponent(executionIdParam)}`);
        updateCurrentExecutionUI(execution);
        if (['RUNNING', 'QUEUED', 'PENDING'].includes(execution.status)) {
          state.pollTimer = window.setInterval(() => {
            pollCurrentExecution().catch(() => null);
          }, 2500);
        }
      } catch (_error) {
        // ignore invalid query id
      }
    }

    window.addEventListener('beforeunload', () => {
      revokeExecutionAssetUrls();
    }, { once: true });
  }

  async function initializeReportsPage() {
    const user = await R.ensureAuth();
    updateUserHeader(user);

    const header = $('main header');
    const selects = $$('select', header);
    const [rangeSelect, envSelect] = selects;
    const searchInput = $('input[placeholder*="搜索报告"]', header);
    const summaryCards = $$('main .p-6 > .grid.grid-cols-4 .glass-card');
    const tableBody = $('tbody');
    const modal = $('#report-modal');

    if (!rangeSelect || !envSelect || !searchInput || !tableBody || !modal) return;

    rangeSelect.innerHTML = [
      '<option value="7">最近7天</option>',
      '<option value="30">最近30天</option>',
      '<option value="90">最近90天</option>',
      '<option value="365">最近一年</option>'
    ].join('');

    envSelect.innerHTML = [
      '<option value="">全部环境</option>',
      '<option value="staging">Staging</option>',
      '<option value="dev">Dev</option>',
      '<option value="prod">Prod</option>'
    ].join('');

    const state = {
      executions: [],
      filtered: [],
      selected: null
    };
    const assetObjectUrlByPath = new Map();

    function revokeReportAssetUrls() {
      assetObjectUrlByPath.forEach((url) => {
        if (typeof url === 'string' && url.startsWith('blob:')) {
          URL.revokeObjectURL(url);
        }
      });
      assetObjectUrlByPath.clear();
    }

    async function resolveReportAssetUrl(path) {
      const normalized = String(path || '').trim();
      if (!normalized) return '';
      if (!normalized.startsWith('/api/')) return normalized;
      if (assetObjectUrlByPath.has(normalized)) {
        return assetObjectUrlByPath.get(normalized) || '';
      }
      const token = R.getAccessToken();
      const response = await fetch(normalized, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!response.ok) {
        throw new Error(`资源加载失败(${response.status})`);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      assetObjectUrlByPath.set(normalized, objectUrl);
      return objectUrl;
    }

    function inRange(dateString, days) {
      if (!dateString) return false;
      const date = new Date(dateString);
      if (Number.isNaN(date.getTime())) return false;
      const diff = Date.now() - date.getTime();
      return diff <= Number(days) * 24 * 60 * 60 * 1000;
    }

    function applyFilters() {
      const keyword = searchInput.value.trim().toLowerCase();
      const env = envSelect.value;
      const days = Number(rangeSelect.value || 7);

      state.filtered = state.executions.filter((item) => {
        const title = `${item.executionId || ''} ${item.testCase?.title || ''} ${item.testCase?.caseNumber || ''}`.toLowerCase();
        const passKeyword = !keyword || title.includes(keyword);
        const passEnv = !env || String(item.environment || '').toLowerCase() === env;
        const passRange = inRange(item.createdAt || item.startedAt || item.updatedAt, days);
        return passKeyword && passEnv && passRange;
      });

      renderSummary();
      renderTable();
    }

    function renderSummary() {
      const total = state.filtered.length;
      const passCount = state.filtered.filter((item) => item.result === 'PASS').length;
      const failCount = state.filtered.filter((item) => item.result === 'FAIL' || item.status === 'FAILED').length;
      const avgMs = total
        ? Math.round(state.filtered.reduce((sum, item) => sum + Number(item.duration || 0), 0) / total)
        : 0;
      const passRate = total ? (passCount / total) * 100 : 0;

      if (summaryCards[0]) {
        $('p.text-2xl', summaryCards[0]).textContent = String(total);
      }
      if (summaryCards[1]) {
        const node = $('p.text-2xl', summaryCards[1]);
        if (node) node.textContent = `${passRate.toFixed(1)}%`;
      }
      if (summaryCards[2]) {
        const node = $('p.text-2xl', summaryCards[2]);
        if (node) node.textContent = R.formatDurationMs(avgMs);
      }
      if (summaryCards[3]) {
        const node = $('p.text-2xl', summaryCards[3]);
        if (node) node.textContent = String(failCount);
      }
    }

    function renderTable() {
      if (!state.filtered.length) {
        tableBody.innerHTML = '<tr><td colspan="8" class="px-4 py-10 text-center text-sm text-[#71717a]">暂无报告数据</td></tr>';
        return;
      }

      tableBody.innerHTML = state.filtered.map((item) => {
        const duration = R.formatDurationMs(item.duration);
        const passRate = item.result === 'PASS' ? 100 : item.result === 'SKIP' ? 60 : item.result === 'WARNING' ? 80 : 0;
        return `
          <tr class="border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer" data-report-id="${item.id}">
            <td class="px-4 py-3 text-[#00d4ff] font-mono text-sm">${R.escapeHtml(item.executionId || `EX-${item.id}`)}</td>
            <td class="px-4 py-3 text-sm">${R.escapeHtml(R.formatDateTime(item.createdAt || item.startedAt))}</td>
            <td class="px-4 py-3 text-sm">${R.escapeHtml(item.testCase?.title || '-')}</td>
            <td class="px-4 py-3"><span class="px-2 py-1 text-xs bg-white/10 text-[#d1d5db] rounded">${R.escapeHtml(item.environment || '-')}</span></td>
            <td class="px-4 py-3 text-sm">1/${item.result === 'PASS' ? '1' : '0'}/${item.result === 'PASS' ? '0' : '1'}</td>
            <td class="px-4 py-3">
              <div class="flex items-center gap-2">
                <div class="w-16 h-2 bg-white/10 rounded-full overflow-hidden">
                  <div class="h-full ${item.result === 'PASS' ? 'bg-[#10b981]' : 'bg-[#ef4444]'}" style="width:${passRate}%"></div>
                </div>
                <span class="text-xs">${passRate}%</span>
              </div>
            </td>
            <td class="px-4 py-3 text-sm">${R.escapeHtml(duration)}</td>
            <td class="px-4 py-3"><button data-open-report="${item.id}" class="p-1 hover:bg-white/10 rounded transition-colors text-[#a1a1aa]">查看</button></td>
          </tr>
        `;
      }).join('');
    }

    function closeReport() {
      modal.classList.add('hidden');
      revokeReportAssetUrls();
    }

    async function openReport(executionId) {
      const listItem = state.executions.find((execution) => execution.id === executionId);
      if (!listItem) return;
      let item = listItem;
      try {
        item = await R.api(`/executions/${executionId}`);
      } catch (_error) {
        item = listItem;
      }
      state.selected = item;

      const pass = item.result === 'PASS' ? 1 : 0;
      const fail = pass ? 0 : 1;
      const timeline = Array.isArray(item.timeline) ? item.timeline : [];
      const screenshots = Array.isArray(item.screenshots) ? item.screenshots : [];
      const timelineHtml = timeline.length
        ? timeline.map((step) => {
          const status = String(step.status || '').toUpperCase();
          const color = status === 'FAILED'
            ? '#ef4444'
            : status === 'RUNNING'
              ? '#3b82f6'
              : status === 'PENDING'
                ? '#f59e0b'
                : '#10b981';
          return `
            <div class="p-3 rounded-lg bg-white/5 border border-white/10">
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-medium">${R.escapeHtml(String(step.stepOrder || '-'))}. ${R.escapeHtml(step.stepName || '未命名步骤')}</p>
                <span class="text-[10px] px-2 py-0.5 rounded" style="background:${color}33;color:${color};">${R.escapeHtml(step.status || 'UNKNOWN')}</span>
              </div>
              <p class="text-xs text-[#a1a1aa] mt-1">${R.escapeHtml(step.details || '-')}</p>
              <p class="text-[11px] text-[#71717a] mt-1">${R.escapeHtml(R.formatDurationMs(step.duration || 0))}</p>
            </div>
          `;
        }).join('')
        : '<p class="text-sm text-[#71717a]">暂无时间线数据</p>';
      const screenshotHtml = screenshots.length
        ? screenshots.slice(0, 12).map((shot, index) => {
          const type = String(shot.type || '').toUpperCase();
          const failed = type.includes('FAIL') || type.includes('ERROR');
          const label = failed ? '失败' : '成功';
          const fileName = String(shot.filePath || '').split('/').filter(Boolean).pop() || `step-${index + 1}.png`;
          return `
            <div class="aspect-video bg-white/5 rounded-lg border border-white/10 p-2 flex flex-col justify-between">
              <div class="self-start px-2 py-0.5 rounded text-[10px] ${failed ? 'bg-[#ef4444]/20 text-[#ef4444]' : 'bg-[#10b981]/20 text-[#10b981]'}">${label}</div>
              <div class="text-[10px] text-[#a1a1aa] truncate">${R.escapeHtml(fileName)}</div>
              <div class="text-[10px] text-[#71717a] truncate">${R.escapeHtml(shot.stepName || `Step ${shot.stepNumber || index + 1}`)}</div>
            </div>
          `;
        }).join('')
        : '<p class="text-sm text-[#71717a]">暂无截图数据</p>';
      const hasVideo = String(item.videoPath || '').trim().length > 0;
      const detailHtml = `
        <div class="sticky top-0 bg-[#12121a] p-6 border-b border-white/5 flex items-center justify-between">
          <div>
            <h2 class="text-xl font-semibold">报告详情</h2>
            <p class="text-sm text-[#71717a]">${R.escapeHtml(item.executionId || '-')} · ${R.escapeHtml(R.formatDateTime(item.createdAt || item.startedAt))}</p>
          </div>
          <button id="report-close-btn" class="p-2 hover:bg-white/10 rounded-lg transition-colors">
            <i data-lucide="x" class="w-5 h-5"></i>
          </button>
        </div>
        <div class="p-6 space-y-6">
          <div class="grid grid-cols-4 gap-4">
            <div class="p-4 bg-white/5 rounded-lg text-center"><p class="text-2xl font-bold">1</p><p class="text-xs text-[#a1a1aa]">总用例</p></div>
            <div class="p-4 bg-[#10b981]/10 rounded-lg text-center"><p class="text-2xl font-bold text-[#10b981]">${pass}</p><p class="text-xs text-[#a1a1aa]">通过</p></div>
            <div class="p-4 bg-[#ef4444]/10 rounded-lg text-center"><p class="text-2xl font-bold text-[#ef4444]">${fail}</p><p class="text-xs text-[#a1a1aa]">失败</p></div>
            <div class="p-4 bg-white/5 rounded-lg text-center"><p class="text-2xl font-bold">${R.escapeHtml(R.formatDurationMs(item.duration))}</p><p class="text-xs text-[#a1a1aa]">执行时长</p></div>
          </div>
          <div>
            <h3 class="text-lg font-semibold mb-3">执行详情</h3>
            <div class="p-4 bg-white/5 border border-white/10 rounded-lg">
              <p class="text-sm"><span class="text-[#a1a1aa]">用例:</span> ${R.escapeHtml(item.testCase?.caseNumber || '-')} - ${R.escapeHtml(item.testCase?.title || '-')}</p>
              <p class="text-sm mt-2"><span class="text-[#a1a1aa]">状态:</span> ${statusBadge(item.status)} ${R.escapeHtml(EXEC_STATUS_LABEL[item.status] || item.status || '-')}</p>
              <p class="text-sm mt-2"><span class="text-[#a1a1aa]">结果:</span> ${statusBadge(item.result)} ${R.escapeHtml(EXEC_RESULT_LABEL[item.result] || item.result || '-')}</p>
              <p class="text-sm mt-2"><span class="text-[#a1a1aa]">日志:</span></p>
              <pre class="text-xs text-[#d1d5db] mt-1 whitespace-pre-wrap">${R.escapeHtml(item.logs || item.errorMessage || '暂无日志')}</pre>
            </div>
          </div>
          <div>
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-lg font-semibold">执行录屏</h3>
              <div class="flex items-center gap-2">
                <button id="report-video-open" type="button" class="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors text-sm ${hasVideo ? '' : 'opacity-50 cursor-not-allowed'}" ${hasVideo ? '' : 'disabled'}>打开录屏</button>
                <button id="report-video-download" type="button" class="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors text-sm ${hasVideo ? '' : 'opacity-50 cursor-not-allowed'}" ${hasVideo ? '' : 'disabled'}>下载录屏</button>
              </div>
            </div>
            <div class="rounded-lg border border-white/10 bg-white/5 p-3">
              <div id="report-video-empty" class="aspect-video rounded bg-black/30 border border-white/10 flex items-center justify-center text-sm text-[#71717a]">${hasVideo ? '录屏加载中...' : '暂无录屏文件'}</div>
              <video id="report-video-player" class="hidden w-full aspect-video rounded border border-white/10 bg-black/40" controls preload="metadata"></video>
              <p id="report-video-meta" class="mt-2 text-[11px] text-[#71717a] truncate">${hasVideo ? R.escapeHtml(String(item.videoPath || '').split('/').filter(Boolean).pop() || 'execution-video.webm') : ''}</p>
            </div>
          </div>
          <div>
            <h3 class="text-lg font-semibold mb-3">执行时间线</h3>
            <div class="space-y-2">
              ${timelineHtml}
            </div>
          </div>
          <div>
            <h3 class="text-lg font-semibold mb-3">执行截图</h3>
            <div class="grid grid-cols-4 gap-3">
              ${screenshotHtml}
            </div>
          </div>
          <div class="flex justify-end gap-3 pt-4 border-t border-white/5">
            <button id="report-download-btn" class="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors text-sm">下载报告</button>
            <button id="report-share-btn" class="px-4 py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 transition-opacity text-sm font-medium">复制分享信息</button>
          </div>
        </div>
      `;

      const card = $('.glass-card', modal);
      card.innerHTML = detailHtml;
      if (window.lucide) window.lucide.createIcons();

      $('#report-close-btn', card).addEventListener('click', closeReport);
      $('#report-download-btn', card).addEventListener('click', () => {
        R.downloadJson(`${item.executionId || `execution-${item.id}`}.json`, item);
      });
      $('#report-share-btn', card).addEventListener('click', async () => {
        const text = `报告 ${item.executionId || item.id} - ${item.result || item.status} - ${R.formatDateTime(item.createdAt || item.startedAt)}`;
        try {
          await navigator.clipboard.writeText(text);
          R.toast('分享信息已复制', 'success');
        } catch (_error) {
          R.toast('复制失败，请手动复制报告内容', 'warning');
        }
      });

      const videoPath = String(item.videoPath || '').trim();
      const reportVideoPlayer = $('#report-video-player', card);
      const reportVideoEmpty = $('#report-video-empty', card);
      const reportVideoMeta = $('#report-video-meta', card);
      const reportVideoOpen = $('#report-video-open', card);
      const reportVideoDownload = $('#report-video-download', card);

      if (videoPath && reportVideoPlayer && reportVideoEmpty) {
        try {
          const videoUrl = await resolveReportAssetUrl(videoPath);
          if (videoUrl) {
            reportVideoPlayer.src = videoUrl;
            reportVideoPlayer.classList.remove('hidden');
            reportVideoEmpty.classList.add('hidden');
            if (reportVideoMeta) {
              const fileName = videoPath.split('/').filter(Boolean).pop() || 'execution-video.webm';
              reportVideoMeta.textContent = `录屏文件: ${fileName}`;
            }
          } else {
            reportVideoEmpty.textContent = '录屏地址不可用';
          }
        } catch (_error) {
          reportVideoEmpty.textContent = '录屏加载失败';
        }
      }

      if (reportVideoOpen) {
        reportVideoOpen.addEventListener('click', async () => {
          if (!videoPath) {
            R.toast('该执行暂无录屏', 'warning');
            return;
          }
          try {
            const videoUrl = await resolveReportAssetUrl(videoPath);
            if (!videoUrl) {
              R.toast('录屏地址不可用', 'warning');
              return;
            }
            window.open(videoUrl, '_blank', 'noopener');
          } catch (_error) {
            R.toast('录屏加载失败', 'error');
          }
        });
      }

      if (reportVideoDownload) {
        reportVideoDownload.addEventListener('click', async () => {
          if (!videoPath) {
            R.toast('该执行暂无录屏', 'warning');
            return;
          }
          try {
            const videoUrl = await resolveReportAssetUrl(videoPath);
            if (!videoUrl) {
              R.toast('录屏地址不可用', 'warning');
              return;
            }
            const fileName = videoPath.split('/').filter(Boolean).pop() || 'execution-video.webm';
            const anchor = document.createElement('a');
            anchor.href = videoUrl;
            anchor.download = fileName;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
          } catch (_error) {
            R.toast('录屏下载失败', 'error');
          }
        });
      }

      modal.classList.remove('hidden');
    }

    async function loadExecutions() {
      const page = await R.api('/executions?page=0&size=200');
      state.executions = unwrapPage(page);
      applyFilters();
    }

    tableBody.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-open-report]');
      const row = event.target.closest('tr[data-report-id]');
      const id = Number((button && button.dataset.openReport) || (row && row.dataset.reportId));
      if (!id) return;
      openReport(id).catch((error) => {
        R.toast(error?.message || '报告加载失败', 'error');
      });
    });

    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeReport();
    });

    window.openReportDetail = () => {
      if (state.filtered[0]) {
        openReport(state.filtered[0].id).catch((error) => {
          R.toast(error?.message || '报告加载失败', 'error');
        });
      }
    };
    window.closeReportDetail = closeReport;

    rangeSelect.addEventListener('change', applyFilters);
    envSelect.addEventListener('change', applyFilters);
    searchInput.addEventListener('input', debounce(applyFilters, 240));

    await loadExecutions();
  }

  async function initializeSettingsPage() {
    const user = await R.ensureAuth();
    updateUserHeader(user);

    const pageRoot = $('main .p-6');
    const tabsContainer = $('main .p-6 > .flex.gap-6') || $('main .p-6 > div:first-child');
    const tabButtons = $$('button', tabsContainer);
    const legacyPanel = $$(':scope > div', pageRoot)[1];
    if (!pageRoot || !tabsContainer || !tabButtons.length) return;

    if (legacyPanel) legacyPanel.style.display = 'none';

    let dynamicHost = $('#settings-dynamic-host');
    if (!dynamicHost) {
      dynamicHost = document.createElement('div');
      dynamicHost.id = 'settings-dynamic-host';
      pageRoot.appendChild(dynamicHost);
    }

    const systemRoleAliases = {
      ADMIN: 'SYSTEM_ADMIN',
      MANAGER: 'OPERATIONS_ADMIN',
      USER: 'OPS_ADMIN',
      TEST_MANAGER: 'OPERATIONS_ADMIN',
      TEST_DEVELOPER: 'OPS_ADMIN',
      QA: 'OPS_ADMIN'
    };
    const fallbackSystemRoleLabels = {
      SYSTEM_ADMIN: '系统管理员',
      OPS_ADMIN: '运维管理员',
      OPERATIONS_ADMIN: '运营管理员'
    };
    const tenantRoleAliases = {
      SYSTEM_ADMIN: 'TEST_MANAGER',
      ADMIN: 'TEST_MANAGER',
      MANAGER: 'TEST_MANAGER',
      TEST_DEVELOPER: 'TEST_ENGINEER',
      USER: 'QA'
    };
    const fallbackTenantRoleLabels = {
      TEST_MANAGER: '测试经理',
      TEST_ENGINEER: '测试工程师',
      QA: 'QA'
    };
    const isSystemAdmin = ['SYSTEM_ADMIN', 'ADMIN'].includes(String(user?.role || '').toUpperCase());
    const modelProviderDefaults = {
      OPENAI: 'https://api.openai.com/v1',
      ZHIPU: 'https://open.bigmodel.cn/api/paas/v4',
      DEEPSEEK: 'https://api.deepseek.com/v1'
    };

    function normalizeModelProvider(rawProvider) {
      const provider = String(rawProvider || '').trim().toUpperCase();
      return modelProviderDefaults[provider] ? provider : 'OPENAI';
    }

    function defaultModelBaseUrl(provider) {
      return modelProviderDefaults[normalizeModelProvider(provider)];
    }

    function createModelId() {
      if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return `MODEL-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
      }
      return `MODEL-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    }

    function clampModelTemperature(rawTemperature) {
      const parsed = Number(rawTemperature);
      if (!Number.isFinite(parsed)) return 0.7;
      return Math.max(0, Math.min(2, parsed));
    }

    function normalizeIntegrationSettings(rawIntegration) {
      const integration = { ...(rawIntegration || {}) };
      const legacyProvider = normalizeModelProvider(integration.modelProvider || 'OPENAI');
      const legacyModel = String(integration.modelName || integration.openaiModel || 'gpt-4o-mini').trim() || 'gpt-4o-mini';
      const legacyBaseUrl = String(integration.modelBaseUrl || defaultModelBaseUrl(legacyProvider)).trim() || defaultModelBaseUrl(legacyProvider);
      const legacyApiKey = String(integration.modelApiKey || '').trim();
      const legacyTemperature = clampModelTemperature(integration.modelTemperature);

      const incomingModels = Array.isArray(integration.models) ? integration.models : [];
      const normalizedModels = incomingModels
        .map((item, index) => {
          const source = (item && typeof item === 'object') ? item : {};
          const provider = normalizeModelProvider(source.provider || source.modelProvider || legacyProvider);
          const model = String(source.model || source.modelName || source.openaiModel || legacyModel).trim() || legacyModel;
          const baseUrl = String(source.baseUrl || source.modelBaseUrl || defaultModelBaseUrl(provider)).trim() || defaultModelBaseUrl(provider);
          const apiKey = String(source.apiKey || source.modelApiKey || '').trim();
          const temperature = clampModelTemperature(source.temperature ?? source.modelTemperature ?? legacyTemperature);
          const id = String(source.id || '').trim() || `MODEL-${index + 1}`;
          const name = String(source.name || `${provider} / ${model}`).trim() || `${provider} / ${model}`;
          return { id, name, provider, baseUrl, apiKey, model, temperature };
        })
        .filter((item) => item && item.id);

      const models = normalizedModels.length
        ? normalizedModels
        : [{
            id: 'MODEL-1',
            name: '默认模型',
            provider: legacyProvider,
            baseUrl: legacyBaseUrl,
            apiKey: legacyApiKey,
            model: legacyModel,
            temperature: legacyTemperature
          }];

      let activeModelId = String(integration.activeModelId || '').trim();
      let activeModel = models.find((item) => item.id === activeModelId);
      if (!activeModel) {
        activeModel = models[0];
        activeModelId = activeModel.id;
      }

      return {
        apiBase: String(integration.apiBase || '/api').trim() || '/api',
        models,
        activeModelId,
        modelProvider: activeModel.provider,
        modelBaseUrl: activeModel.baseUrl,
        modelApiKey: activeModel.apiKey,
        modelName: activeModel.model,
        modelTemperature: activeModel.temperature,
        openaiModel: String(integration.openaiModel || activeModel.model).trim() || activeModel.model,
        jiraServerUrl: String(integration.jiraServerUrl || '').trim(),
        jiraProjectKey: String(integration.jiraProjectKey || '').trim(),
        githubRepo: String(integration.githubRepo || '').trim(),
        githubBranch: String(integration.githubBranch || 'main').trim() || 'main'
      };
    }

    const legacySettings = R.getSettings();
    const state = {
      settings: {
        general: {
          appName: 'Nasus',
          theme: legacySettings.theme || 'dark',
          language: legacySettings.language || 'zh-CN',
          timezone: legacySettings.timezone || 'Asia/Shanghai',
          autoSave: legacySettings.autoSave !== false,
          notifications: legacySettings.notifications !== false,
          telemetry: !!legacySettings.telemetry
        },
        integration: {
          apiBase: legacySettings.apiBase || '/api',
          models: Array.isArray(legacySettings.models) ? legacySettings.models : [],
          activeModelId: legacySettings.activeModelId || '',
          modelProvider: legacySettings.modelProvider || 'OPENAI',
          modelBaseUrl: legacySettings.modelBaseUrl || 'https://api.openai.com/v1',
          modelApiKey: legacySettings.modelApiKey || '',
          modelName: legacySettings.modelName || legacySettings.openaiModel || 'gpt-4o-mini',
          modelTemperature: Number.isFinite(Number(legacySettings.modelTemperature)) ? Number(legacySettings.modelTemperature) : 0.7,
          openaiModel: legacySettings.openaiModel || legacySettings.modelName || 'gpt-4o-mini',
          jiraServerUrl: legacySettings.jiraServerUrl || '',
          jiraProjectKey: legacySettings.jiraProjectKey || '',
          githubRepo: legacySettings.githubRepo || '',
          githubBranch: legacySettings.githubBranch || 'main'
        },
        notification: {
          executionComplete: legacySettings.notifications !== false,
          executionFailed: legacySettings.notifications !== false,
          dailyReport: !!legacySettings.dailyReport
        },
        execution: {
          defaultBrowser: legacySettings.defaultBrowser || 'chromium',
          defaultEnvironment: legacySettings.defaultEnvironment || 'staging',
          defaultTargetUrl: legacySettings.defaultTargetUrl || 'https://example.com'
        }
      },
      users: [],
      roleProfiles: [],
      tenantRoleProfiles: [],
      tenants: [],
      tenantMembers: {},
      assignableUsers: [],
      selectedTenantId: null,
      activeTab: 'general',
      currentUser: user,
      profileDraft: {
        fullName: (user?.fullName || '').trim(),
        avatar: String(user?.avatar || '').trim()
      }
    };
    state.settings.integration = normalizeIntegrationSettings(state.settings.integration);

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

    const defaultGalleryAvatars = [
      { key: 'a1', label: 'AI', value: createGalleryAvatar('AI', '#00d4ff', '#7c3aed') },
      { key: 'q1', label: 'QA', value: createGalleryAvatar('QA', '#22d3ee', '#2563eb') },
      { key: 'tm', label: 'TM', value: createGalleryAvatar('TM', '#34d399', '#0ea5e9') },
      { key: 'td', label: 'TD', value: createGalleryAvatar('TD', '#f59e0b', '#ef4444') },
      { key: 'sa', label: 'SA', value: createGalleryAvatar('SA', '#a78bfa', '#ec4899') },
      { key: 'ux', label: 'UX', value: createGalleryAvatar('UX', '#14b8a6', '#6366f1') }
    ];

    const animalEmojiAvatars = ['🐼', '🦊', '🐯', '🦁', '🐨', '🐶', '🐱', '🐸', '🐧', '🦉', '🐰', '🐻'];

    function cloneObject(input) {
      return JSON.parse(JSON.stringify(input || {}));
    }

    function deepMergeObject(current, patch) {
      if (!patch || typeof patch !== 'object') return current;
      Object.entries(patch).forEach(([key, value]) => {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          const base = current[key] && typeof current[key] === 'object' ? current[key] : {};
          current[key] = deepMergeObject({ ...base }, value);
          return;
        }
        current[key] = value;
      });
      return current;
    }

    function toLegacyRuntimeSettings(structured) {
      const integration = normalizeIntegrationSettings(structured.integration || {});
      return {
        apiBase: integration.apiBase || '/api',
        defaultBrowser: structured.execution?.defaultBrowser || 'chromium',
        defaultEnvironment: structured.execution?.defaultEnvironment || 'staging',
        defaultTargetUrl: structured.execution?.defaultTargetUrl || 'https://example.com',
        theme: structured.general?.theme || 'dark',
        language: structured.general?.language || 'zh-CN',
        timezone: structured.general?.timezone || 'Asia/Shanghai',
        autoSave: structured.general?.autoSave !== false,
        notifications: structured.general?.notifications !== false,
        telemetry: !!structured.general?.telemetry,
        models: integration.models || [],
        activeModelId: integration.activeModelId || '',
        modelProvider: integration.modelProvider || 'OPENAI',
        modelBaseUrl: integration.modelBaseUrl || 'https://api.openai.com/v1',
        modelApiKey: integration.modelApiKey || '',
        modelName: integration.modelName || integration.openaiModel || 'gpt-4o-mini',
        modelTemperature: Number.isFinite(Number(integration.modelTemperature))
          ? Number(integration.modelTemperature)
          : 0.7,
        openaiModel: integration.modelName || integration.openaiModel || 'gpt-4o-mini',
        jiraServerUrl: integration.jiraServerUrl || '',
        jiraProjectKey: integration.jiraProjectKey || '',
        githubRepo: integration.githubRepo || '',
        githubBranch: integration.githubBranch || 'main',
        dailyReport: !!structured.notification?.dailyReport
      };
    }

    async function persistSettingsPatch(patch, successMessage = '设置已保存') {
      const localNext = deepMergeObject(cloneObject(state.settings), patch || {});
      localNext.integration = normalizeIntegrationSettings(localNext.integration || {});
      state.settings = localNext;
      R.saveSettings(toLegacyRuntimeSettings(state.settings));

      try {
        const response = await R.api('/settings', {
          method: 'PUT',
          body: patch || {}
        });
        if (response?.settings && typeof response.settings === 'object') {
          state.settings = deepMergeObject(cloneObject(state.settings), response.settings);
          state.settings.integration = normalizeIntegrationSettings(state.settings.integration || {});
          R.saveSettings(toLegacyRuntimeSettings(state.settings));
        }
        R.toast(successMessage, 'success');
      } catch (error) {
        R.toast(error.message || '设置保存失败', 'error');
      }
    }

    function syncProfileDraft(nextUser) {
      if (!nextUser) return;
      state.profileDraft = {
        fullName: String(nextUser.fullName || '').trim(),
        avatar: String(nextUser.avatar || '').trim()
      };
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

    async function persistCurrentProfile(fullName, avatar) {
      const normalizedName = String(fullName || '').trim();
      if (!normalizedName) {
        R.toast('姓名不能为空', 'warning');
        return false;
      }

      const normalizedAvatar = String(avatar || '').trim();
      if (normalizedAvatar.length > 58000) {
        R.toast('头像内容过大，请选择更小图片', 'warning');
        return false;
      }

      try {
        const updatedUser = await R.api('/users/me/profile', {
          method: 'PUT',
          body: {
            fullName: normalizedName,
            avatar: normalizedAvatar
          }
        });
        state.currentUser = updatedUser;
        syncProfileDraft(updatedUser);
        R.setUserCache(updatedUser);
        updateUserHeader(updatedUser);
        R.toast('个人资料已保存', 'success');
        return true;
      } catch (error) {
        R.toast(error.message || '个人资料保存失败', 'error');
        return false;
      }
    }

    const tabDefs = [
      { key: 'general', adminOnly: false, render: renderGeneralSection },
      { key: 'integration', adminOnly: false, render: renderIntegrationSection },
      { key: 'tenant', adminOnly: true, render: renderTenantSection },
      { key: 'accounts', adminOnly: true, render: renderAccountsSection },
      { key: 'api-key', adminOnly: false, render: renderApiKeySection },
      { key: 'notification', adminOnly: false, render: renderNotificationSection },
      { key: 'execution', adminOnly: false, render: renderExecutionSection }
    ];

    function normalizeSystemRole(role) {
      const raw = String(role || '').toUpperCase();
      return systemRoleAliases[raw] || raw || 'OPERATIONS_ADMIN';
    }

    function normalizeTenantRole(role) {
      const raw = String(role || '').toUpperCase();
      return tenantRoleAliases[raw] || raw || 'QA';
    }

    function defaultPermissionsByRole(role) {
      const normalized = normalizeSystemRole(role);
      const profile = state.roleProfiles.find((item) => item.role === normalized);
      return Array.isArray(profile?.defaultPermissions) ? profile.defaultPermissions : [];
    }

    function roleDisplayName(role) {
      const normalized = normalizeSystemRole(role);
      const profile = state.roleProfiles.find((item) => item.role === normalized);
      return profile?.roleDisplayName || fallbackSystemRoleLabels[normalized] || normalized;
    }

    function tenantRoleDisplayName(role) {
      const normalized = normalizeTenantRole(role);
      const profile = state.tenantRoleProfiles.find((item) => item.role === normalized);
      return profile?.roleDisplayName || fallbackTenantRoleLabels[normalized] || normalized;
    }

    function parsePermissions(raw) {
      if (!raw) return [];
      return String(raw)
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
        .filter((item, index, all) => all.indexOf(item) === index);
    }

    function stringifyPermissions(permissions) {
      return Array.isArray(permissions) && permissions.length ? permissions.join(', ') : '';
    }

    function getVisibleTabs() {
      return tabDefs.filter((tab) => !tab.adminOnly || isSystemAdmin);
    }

    function syncTabButtons() {
      tabButtons.forEach((button, index) => {
        const def = tabDefs[index];
        if (!def) {
          button.style.display = 'none';
          return;
        }
        if (def.key === 'accounts') {
          button.textContent = '账户管理';
        }
        if (def.key === 'tenant') {
          button.textContent = '项目管理';
        }
        if (def.adminOnly && !isSystemAdmin) {
          button.style.display = 'none';
          delete button.dataset.tabKey;
          return;
        }
        button.style.display = '';
        button.dataset.tabKey = def.key;
      });
    }

    function markTabActive() {
      tabButtons.forEach((button) => {
        const active = button.dataset.tabKey === state.activeTab;
        if (active) {
          button.classList.add('tab-active');
          button.classList.remove('text-[#a1a1aa]');
        } else {
          button.classList.remove('tab-active');
          button.classList.add('text-[#a1a1aa]');
        }
      });
    }

    async function loadUsersAndRoles() {
      const [usersPage, roleProfiles] = await Promise.all([
        R.api('/users?page=0&size=100'),
        R.api('/users/roles')
      ]);
      state.users = unwrapPage(usersPage);
      state.roleProfiles = Array.isArray(roleProfiles) ? roleProfiles : [];
    }

    async function loadTenantBaseData() {
      const [roleProfiles, tenantRoleProfiles, tenants, assignableUsers] = await Promise.all([
        state.roleProfiles.length ? Promise.resolve(state.roleProfiles) : R.api('/users/roles'),
        state.tenantRoleProfiles.length ? Promise.resolve(state.tenantRoleProfiles) : R.api('/tenants/roles'),
        R.api('/tenants'),
        R.api('/tenants/users')
      ]);
      state.roleProfiles = Array.isArray(roleProfiles) ? roleProfiles : [];
      state.tenantRoleProfiles = Array.isArray(tenantRoleProfiles) ? tenantRoleProfiles : [];
      state.tenants = Array.isArray(tenants) ? tenants : [];
      state.assignableUsers = Array.isArray(assignableUsers) ? assignableUsers : [];

      if (!state.selectedTenantId || !state.tenants.some((item) => Number(item.id) === Number(state.selectedTenantId))) {
        state.selectedTenantId = state.tenants[0] ? Number(state.tenants[0].id) : null;
      }
    }

    async function loadTenantMembers(tenantId, force = false) {
      const key = Number(tenantId);
      if (!key) return [];
      if (!force && Array.isArray(state.tenantMembers[key])) {
        return state.tenantMembers[key];
      }
      const members = await R.api(`/tenants/${key}/members`);
      state.tenantMembers[key] = Array.isArray(members) ? members : [];
      return state.tenantMembers[key];
    }

    async function renderTenantSection() {
      if (!isSystemAdmin) {
        dynamicHost.innerHTML = '<div class="glass-card p-6 text-sm text-[#a1a1aa]">当前账号没有项目管理权限。</div>';
        return;
      }

      try {
        await loadTenantBaseData();
      } catch (error) {
        dynamicHost.innerHTML = `<div class="glass-card p-6 text-sm text-[#ef4444]">项目管理加载失败: ${R.escapeHtml(error.message || '未知错误')}</div>`;
        return;
      }

      const selectedTenantId = Number(state.selectedTenantId || 0);
      const selectedTenant = state.tenants.find((item) => Number(item.id) === selectedTenantId) || null;
      let selectedMembers = [];
      if (selectedTenant) {
        try {
          selectedMembers = await loadTenantMembers(selectedTenant.id);
        } catch (error) {
          dynamicHost.innerHTML = `<div class="glass-card p-6 text-sm text-[#ef4444]">租户成员加载失败: ${R.escapeHtml(error.message || '未知错误')}</div>`;
          return;
        }
      }

      const tenantRoleOptions = state.tenantRoleProfiles.length
        ? state.tenantRoleProfiles
        : [
          { role: 'TEST_MANAGER', roleDisplayName: '测试经理' },
          { role: 'TEST_ENGINEER', roleDisplayName: '测试工程师' },
          { role: 'QA', roleDisplayName: 'QA' }
        ];
      const roleOptionsHtml = tenantRoleOptions.map((profile) =>
        `<option value="${profile.role}">${R.escapeHtml(profile.roleDisplayName || profile.role || tenantRoleDisplayName(profile.role))}</option>`
      ).join('');

      const tenantRowsHtml = state.tenants.length
        ? state.tenants.map((tenant) => {
          const active = Number(tenant.id) === selectedTenantId;
          return `
            <button data-tenant-select="${tenant.id}" class="w-full text-left rounded-lg border px-3 py-2 transition-colors ${active ? 'border-[#00d4ff] bg-[#00d4ff]/10' : 'border-white/10 bg-white/5 hover:bg-white/10'}">
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-medium text-white">${R.escapeHtml(tenant.tenantName || '-')}</p>
                <span class="text-[11px] text-[#a1a1aa]">${R.escapeHtml(tenant.tenantCode || '-')}</span>
              </div>
              <p class="mt-1 text-xs text-[#71717a]">成员 ${Number(tenant.memberCount || 0)} 人 · ${R.escapeHtml(R.formatDateTime(tenant.createdAt))}</p>
            </button>
          `;
        }).join('')
        : '<p class="text-sm text-[#71717a]">暂无项目空间，请先创建租户。</p>';

      const assignableOptionsHtml = [
        '<option value="">选择用户</option>',
        ...state.assignableUsers.map((userItem) => `<option value="${userItem.id}">${R.escapeHtml(`${userItem.username} (${userItem.fullName || '-'})`)}</option>`)
      ].join('');

      dynamicHost.innerHTML = `
        <div class="grid grid-cols-1 lg:grid-cols-[340px,1fr] gap-4">
          <div class="space-y-4">
            <div class="glass-card p-6">
              <h3 class="text-lg font-semibold mb-4">创建项目空间（租户）</h3>
              <div class="space-y-3">
                <input id="settings-tenant-name" type="text" placeholder="租户名称（如：kun）" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
                <input id="settings-tenant-code" type="text" placeholder="租户编码（如：KUN）" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm uppercase focus:outline-none focus:border-[#00d4ff]" />
              </div>
              <div class="mt-4 flex justify-end">
                <button id="settings-tenant-create" class="px-4 py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 text-sm font-medium">创建租户</button>
              </div>
            </div>
            <div class="glass-card p-6">
              <h3 class="text-lg font-semibold mb-3">我的租户</h3>
              <div class="space-y-2">${tenantRowsHtml}</div>
            </div>
          </div>

          <div class="glass-card p-6">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-semibold">${selectedTenant ? `成员管理 · ${R.escapeHtml(selectedTenant.tenantName || '-')}` : '成员管理'}</h3>
              <span class="text-xs text-[#a1a1aa]">${selectedTenant ? `租户编码 ${R.escapeHtml(selectedTenant.tenantCode || '-')}` : '请先选择租户'}</span>
            </div>

            ${selectedTenant ? `
              <div class="grid grid-cols-1 lg:grid-cols-[1fr,180px,140px] gap-3 mb-4">
                <select id="settings-tenant-member-user" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
                  ${assignableOptionsHtml}
                </select>
                <select id="settings-tenant-member-role" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">${roleOptionsHtml}</select>
                <button id="settings-tenant-member-add" class="px-4 py-2 rounded-lg bg-[#10b981]/20 text-[#10b981] hover:bg-[#10b981]/30 text-sm">添加成员</button>
              </div>

              <div class="overflow-auto">
                <table class="w-full text-sm">
                  <thead>
                    <tr class="border-b border-white/10 text-[#a1a1aa]">
                      <th class="text-left py-2">用户</th>
                      <th class="text-left py-2">姓名</th>
                      <th class="text-left py-2">角色</th>
                      <th class="text-left py-2">状态</th>
                      <th class="text-left py-2">操作</th>
                    </tr>
                  </thead>
                  <tbody id="settings-tenant-members-table">
                    ${selectedMembers.length ? selectedMembers.map((member) => `
                      <tr class="border-b border-white/5">
                        <td class="py-2">${R.escapeHtml(member.username || '-')}</td>
                        <td class="py-2">${R.escapeHtml(member.fullName || '-')}</td>
                        <td class="py-2">
                          <select data-member-role="${member.userId}" class="px-2 py-1 bg-white/5 border border-white/10 rounded">
                            ${tenantRoleOptions.map((profile) => `<option value="${profile.role}" ${normalizeTenantRole(member.role) === profile.role ? 'selected' : ''}>${R.escapeHtml(profile.roleDisplayName || tenantRoleDisplayName(profile.role))}</option>`).join('')}
                          </select>
                        </td>
                        <td class="py-2">${R.escapeHtml(member.status || '-')}</td>
                        <td class="py-2">
                          <div class="flex gap-2">
                            <button data-member-save="${member.userId}" class="px-2 py-1 text-xs rounded bg-[#3b82f6]/20 text-[#3b82f6]">保存</button>
                            <button data-member-remove="${member.userId}" class="px-2 py-1 text-xs rounded bg-[#ef4444]/20 text-[#ef4444]">移除</button>
                          </div>
                        </td>
                      </tr>
                    `).join('') : '<tr><td colspan="5" class="py-6 text-center text-[#71717a]">暂无成员</td></tr>'}
                  </tbody>
                </table>
              </div>
            ` : '<p class="text-sm text-[#71717a]">选择左侧租户后可管理成员角色。</p>'}
          </div>
        </div>
      `;

      $('#settings-tenant-create')?.addEventListener('click', async () => {
        const tenantName = $('#settings-tenant-name').value.trim();
        const tenantCode = $('#settings-tenant-code').value.trim();
        if (!tenantName) {
          R.toast('请填写租户名称', 'warning');
          return;
        }
        await R.api('/tenants', {
          method: 'POST',
          body: { tenantName, tenantCode }
        });
        R.toast('租户创建成功', 'success');
        await renderTenantSection();
      });

      $$('button[data-tenant-select]', dynamicHost).forEach((button) => {
        button.addEventListener('click', async () => {
          state.selectedTenantId = Number(button.dataset.tenantSelect || 0) || null;
          await renderTenantSection();
        });
      });

      if (!selectedTenant) return;

      $('#settings-tenant-member-add')?.addEventListener('click', async () => {
        const userId = Number($('#settings-tenant-member-user').value || 0);
        const role = String($('#settings-tenant-member-role').value || '').trim();
        if (!userId) {
          R.toast('请选择用户', 'warning');
          return;
        }
        await R.api(`/tenants/${selectedTenant.id}/members/${userId}`, {
          method: 'PUT',
          body: { role }
        });
        state.tenantMembers[selectedTenant.id] = null;
        R.toast('成员已添加', 'success');
        await renderTenantSection();
      });

      $('#settings-tenant-members-table')?.addEventListener('click', async (event) => {
        const saveBtn = event.target.closest('button[data-member-save]');
        const removeBtn = event.target.closest('button[data-member-remove]');

        if (saveBtn) {
          const userId = Number(saveBtn.dataset.memberSave || 0);
          const role = $(`select[data-member-role="${userId}"]`)?.value;
          if (!userId || !role) return;
          await R.api(`/tenants/${selectedTenant.id}/members/${userId}`, {
            method: 'PUT',
            body: { role }
          });
          state.tenantMembers[selectedTenant.id] = null;
          R.toast('成员角色已更新', 'success');
          await renderTenantSection();
          return;
        }

        if (removeBtn) {
          const userId = Number(removeBtn.dataset.memberRemove || 0);
          if (!userId) return;
          const confirmed = await R.confirm({
            title: '移除成员',
            message: '确认从当前租户移除该成员？',
            confirmText: '确认移除',
            tone: 'danger'
          });
          if (!confirmed) return;
          await R.api(`/tenants/${selectedTenant.id}/members/${userId}`, {
            method: 'DELETE'
          });
          state.tenantMembers[selectedTenant.id] = null;
          R.toast('成员已移除', 'success');
          await renderTenantSection();
        }
      });
    }

    async function renderAccountsSection() {
      if (!isSystemAdmin) {
        dynamicHost.innerHTML = '<div class="glass-card p-6 text-sm text-[#a1a1aa]">当前账号没有账户管理权限。</div>';
        return;
      }

      try {
        await loadUsersAndRoles();
      } catch (error) {
        dynamicHost.innerHTML = `<div class="glass-card p-6 text-sm text-[#ef4444]">账户管理加载失败: ${R.escapeHtml(error.message || '未知错误')}</div>`;
        return;
      }

      const roleOptions = state.roleProfiles.map((profile) =>
        `<option value="${profile.role}">${R.escapeHtml(profile.roleDisplayName || profile.role)}</option>`
      ).join('');

      dynamicHost.innerHTML = `
        <div class="glass-card p-6 mb-4">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold">账户管理</h3>
            <span class="text-xs text-[#a1a1aa]">当前管理员: ${R.escapeHtml(state.currentUser?.username || '-')}</span>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <input id="settings-user-username" type="text" placeholder="用户名" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            <input id="settings-user-email" type="email" placeholder="邮箱" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            <input id="settings-user-fullname" type="text" placeholder="姓名" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            <input id="settings-user-password" type="password" placeholder="初始密码" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            <select id="settings-user-role-create" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">${roleOptions}</select>
            <input id="settings-user-permissions-create" type="text" placeholder="权限（逗号分隔）" class="px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
          </div>
          <p class="mt-2 text-xs text-[#71717a]">示例权限: ACCOUNT_VIEW, ROLE_ASSIGN, EXECUTION_MANAGE。留空将自动使用角色默认权限。</p>
          <div class="mt-4 flex justify-end">
            <button id="settings-user-create" class="px-4 py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 text-sm font-medium">创建账户</button>
          </div>
        </div>
        <div class="glass-card p-6">
          <h3 class="text-lg font-semibold mb-4">账户列表</h3>
          <div class="overflow-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-white/10 text-[#a1a1aa]">
                  <th class="text-left py-2">ID</th>
                  <th class="text-left py-2">用户名</th>
                  <th class="text-left py-2">姓名</th>
                  <th class="text-left py-2">角色</th>
                  <th class="text-left py-2">权限</th>
                  <th class="text-left py-2">状态</th>
                  <th class="text-left py-2">最近登录</th>
                  <th class="text-left py-2">操作</th>
                </tr>
              </thead>
              <tbody id="settings-user-table">
                ${state.users.map((row) => `
                  <tr class="border-b border-white/5">
                    <td class="py-2">${row.id}</td>
                    <td class="py-2">${R.escapeHtml(row.username || '')}</td>
                    <td class="py-2">${R.escapeHtml(row.fullName || '-')}</td>
                    <td class="py-2">
                      <select data-user-role="${row.id}" class="px-2 py-1 bg-white/5 border border-white/10 rounded">
                        ${state.roleProfiles.map((profile) => `<option value="${profile.role}" ${normalizeSystemRole(row.role) === profile.role ? 'selected' : ''}>${R.escapeHtml(profile.roleDisplayName || profile.role)}</option>`).join('')}
                      </select>
                    </td>
                    <td class="py-2">
                      <input data-user-permissions="${row.id}" type="text" value="${R.escapeHtml(stringifyPermissions(row.permissions))}" class="w-64 px-2 py-1 bg-white/5 border border-white/10 rounded text-xs focus:outline-none focus:border-[#00d4ff]" />
                    </td>
                    <td class="py-2">
                      <select data-user-status="${row.id}" class="px-2 py-1 bg-white/5 border border-white/10 rounded">
                        ${['ACTIVE', 'INACTIVE', 'SUSPENDED'].map((status) => `<option value="${status}" ${row.status === status ? 'selected' : ''}>${status}</option>`).join('')}
                      </select>
                    </td>
                    <td class="py-2">${R.escapeHtml(R.formatDateTime(row.lastLoginAt))}</td>
                    <td class="py-2">
                      <div class="flex gap-2">
                        <button data-user-save="${row.id}" class="px-2 py-1 text-xs rounded bg-[#3b82f6]/20 text-[#3b82f6]">保存</button>
                        <button data-user-delete="${row.id}" class="px-2 py-1 text-xs rounded bg-[#ef4444]/20 text-[#ef4444]">停用</button>
                      </div>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;

      const createRoleSelect = $('#settings-user-role-create');
      const createPermissionsInput = $('#settings-user-permissions-create');
      if (createRoleSelect && createPermissionsInput) {
        const preferredCreateRole = state.roleProfiles.some((item) => item.role === 'OPERATIONS_ADMIN')
          ? 'OPERATIONS_ADMIN'
          : (state.roleProfiles[0]?.role || 'OPERATIONS_ADMIN');
        const initialRole = normalizeSystemRole(preferredCreateRole);
        createRoleSelect.value = initialRole;
        createPermissionsInput.value = stringifyPermissions(defaultPermissionsByRole(initialRole));
        createRoleSelect.addEventListener('change', () => {
          createPermissionsInput.value = stringifyPermissions(defaultPermissionsByRole(createRoleSelect.value));
        });
      }

      $('#settings-user-create').addEventListener('click', async () => {
        const username = $('#settings-user-username').value.trim();
        const email = $('#settings-user-email').value.trim();
        const fullName = $('#settings-user-fullname').value.trim();
        const password = $('#settings-user-password').value;
        const role = normalizeSystemRole($('#settings-user-role-create').value);
        const permissions = parsePermissions($('#settings-user-permissions-create').value);

        if (!username || !email || !fullName || !password) {
          R.toast('请填写完整用户信息', 'warning');
          return;
        }

        await R.api('/users', {
          method: 'POST',
          body: {
            username,
            email,
            fullName,
            password,
            role,
            permissions
          }
        });

        R.toast('账户创建成功', 'success');
        await renderAccountsSection();
      });

      $('#settings-user-table').addEventListener('change', (event) => {
        const roleSelect = event.target.closest('select[data-user-role]');
        if (!roleSelect) return;
        const id = Number(roleSelect.dataset.userRole);
        const permissionInput = $(`input[data-user-permissions="${id}"]`);
        if (!permissionInput) return;
        permissionInput.value = stringifyPermissions(defaultPermissionsByRole(roleSelect.value));
      });

      $('#settings-user-table').addEventListener('click', async (event) => {
        const saveButton = event.target.closest('button[data-user-save]');
        const deleteButton = event.target.closest('button[data-user-delete]');

        if (saveButton) {
          const id = Number(saveButton.dataset.userSave);
          const row = state.users.find((item) => item.id === id);
          if (!row) return;

          const role = normalizeSystemRole($(`select[data-user-role="${id}"]`).value);
          const status = $(`select[data-user-status="${id}"]`).value;
          const permissions = parsePermissions($(`input[data-user-permissions="${id}"]`).value);

          await R.api(`/users/${id}`, {
            method: 'PUT',
            body: {
              fullName: row.fullName,
              avatar: row.avatar,
              role,
              status,
              permissions
            }
          });

          R.toast('账户已更新', 'success');
          await renderAccountsSection();
          return;
        }

        if (deleteButton) {
          const id = Number(deleteButton.dataset.userDelete);
          const confirmed = await R.confirm({
            title: '停用用户',
            message: `确认停用用户 #${id}？`,
            confirmText: '确认停用',
            tone: 'danger'
          });
          if (!confirmed) return;
          await R.api(`/users/${id}`, { method: 'DELETE' });
          R.toast('用户已停用', 'success');
          await renderAccountsSection();
        }
      });
    }

    const timezoneOptions = [
      { value: 'Asia/Shanghai', label: 'Asia/Shanghai (UTC+08:00)' },
      { value: 'Asia/Tokyo', label: 'Asia/Tokyo (UTC+09:00)' },
      { value: 'Asia/Singapore', label: 'Asia/Singapore (UTC+08:00)' },
      { value: 'UTC', label: 'UTC (UTC+00:00)' },
      { value: 'Europe/London', label: 'Europe/London' },
      { value: 'Europe/Berlin', label: 'Europe/Berlin' },
      { value: 'America/New_York', label: 'America/New_York' },
      { value: 'America/Los_Angeles', label: 'America/Los_Angeles' }
    ];

    function renderTimezoneOptions(selectedTimezone) {
      const normalizedSelected = String(selectedTimezone || '').trim() || 'Asia/Shanghai';
      const known = timezoneOptions.some((item) => item.value === normalizedSelected);
      const list = known
        ? timezoneOptions
        : [{ value: normalizedSelected, label: normalizedSelected }, ...timezoneOptions];
      return list
        .map((item) => `<option value="${R.escapeHtml(item.value)}">${R.escapeHtml(item.label)}</option>`)
        .join('');
    }

    function refreshTimezonePreview() {
      const preview = $('#settings-timezone-preview');
      const timezoneSelect = $('#settings-timezone');
      if (!preview || !timezoneSelect) return;
      try {
        const formatter = new Intl.DateTimeFormat('zh-CN', {
          timeZone: timezoneSelect.value,
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false
        });
        const parts = formatter.formatToParts(new Date());
        const map = {};
        parts.forEach((part) => {
          if (part.type !== 'literal') map[part.type] = part.value;
        });
        preview.textContent = `当前时区时间：${map.year}-${map.month}-${map.day} ${map.hour}:${map.minute}:${map.second} (${timezoneSelect.value})`;
      } catch (_error) {
        preview.textContent = `当前时区时间：${R.formatDateTime(new Date())} (${timezoneSelect.value})`;
      }
    }

    function renderGeneralSection() {
      const selectedTimezone = state.settings.general?.timezone || 'Asia/Shanghai';
      dynamicHost.innerHTML = `
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div class="glass-card p-6">
            <h3 class="text-lg font-semibold mb-4">通用设置</h3>
            <div class="space-y-3">
              <label class="block text-sm text-[#a1a1aa]">系统名称</label>
              <input id="settings-app-name" type="text" value="${R.escapeHtml(state.settings.general?.appName || 'Nasus')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />

              <label class="block text-sm text-[#a1a1aa]">主题</label>
              <select id="settings-theme" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
                <option value="dark">深色</option>
                <option value="light">浅色</option>
                <option value="auto">自动</option>
              </select>

              <label class="block text-sm text-[#a1a1aa]">语言</label>
              <select id="settings-language" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
                <option value="zh-CN">简体中文</option>
                <option value="en-US">English</option>
              </select>

              <label class="block text-sm text-[#a1a1aa]">时区</label>
              <select id="settings-timezone" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
                ${renderTimezoneOptions(selectedTimezone)}
              </select>
              <p id="settings-timezone-preview" class="text-xs text-[#71717a] mt-1"></p>
            </div>
          </div>
          <div class="glass-card p-6">
            <h3 class="text-lg font-semibold mb-4">系统选项</h3>
            <div class="space-y-3">
              <label class="flex items-center justify-between"><span class="text-sm">自动保存</span><input id="settings-auto-save" type="checkbox" class="w-5 h-5" /></label>
              <label class="flex items-center justify-between"><span class="text-sm">启用通知</span><input id="settings-notifications" type="checkbox" class="w-5 h-5" /></label>
              <label class="flex items-center justify-between"><span class="text-sm">匿名数据收集</span><input id="settings-telemetry" type="checkbox" class="w-5 h-5" /></label>
            </div>
            <div class="mt-6 flex justify-end gap-2">
              <button id="settings-reset" class="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-sm">重置</button>
              <button id="settings-save" class="px-4 py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 text-sm font-medium">保存设置</button>
            </div>
          </div>
        </div>
      `;

      $('#settings-theme').value = state.settings.general?.theme || 'dark';
      $('#settings-language').value = state.settings.general?.language || 'zh-CN';
      $('#settings-timezone').value = selectedTimezone;
      $('#settings-auto-save').checked = state.settings.general?.autoSave !== false;
      $('#settings-notifications').checked = state.settings.general?.notifications !== false;
      $('#settings-telemetry').checked = !!state.settings.general?.telemetry;
      refreshTimezonePreview();
      $('#settings-timezone').addEventListener('change', refreshTimezonePreview);

      $('#settings-save').addEventListener('click', async () => {
        await persistSettingsPatch({
          general: {
            appName: $('#settings-app-name').value.trim() || 'Nasus',
            theme: $('#settings-theme').value,
            language: $('#settings-language').value,
            timezone: $('#settings-timezone').value,
            autoSave: $('#settings-auto-save').checked,
            notifications: $('#settings-notifications').checked,
            telemetry: $('#settings-telemetry').checked
          }
        }, '通用设置已保存');
      });

      $('#settings-reset').addEventListener('click', async () => {
        await persistSettingsPatch({
          general: {
            appName: 'Nasus',
            theme: 'dark',
            language: 'zh-CN',
            timezone: 'Asia/Shanghai',
            autoSave: true,
            notifications: true,
            telemetry: false
          }
        }, '已重置通用设置');
        renderGeneralSection();
      });
    }

    function renderIntegrationSection() {
      state.settings.integration = normalizeIntegrationSettings(state.settings.integration || {});
      let activeModelId = state.settings.integration.activeModelId;
      let modelDrafts = state.settings.integration.models.map((item) => ({ ...item }));

      dynamicHost.innerHTML = `
        <div class="glass-card p-6">
          <h3 class="text-lg font-semibold mb-4">集成配置</h3>
          <div class="mb-4 p-4 rounded-xl border border-white/10 bg-white/5">
            <div class="flex items-center justify-between gap-3 mb-3">
              <h4 class="text-sm font-semibold">模型配置（OpenAI 兼容协议）</h4>
              <button id="settings-model-add" class="px-3 py-2 rounded-lg bg-white/10 hover:bg-white/20 text-sm">新增模型</button>
            </div>
            <div id="settings-model-list" class="space-y-3"></div>
            <p class="mt-2 text-xs text-[#71717a]">可配置多个模型，并选择一个作为系统启用模型。启用模型将用于 US 分析、用例生成和脚本生成。</p>
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">API Base URL</label>
              <input id="settings-api-base" type="text" value="${R.escapeHtml(state.settings.integration.apiBase || '/api')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            </div>
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">兼容模型别名</label>
              <input id="settings-openai-model" type="text" value="${R.escapeHtml(state.settings.integration.openaiModel || state.settings.integration.modelName || 'gpt-4o-mini')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            </div>
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">JIRA Server URL</label>
              <input id="settings-jira-url" type="text" value="${R.escapeHtml(state.settings.integration.jiraServerUrl || '')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            </div>
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">JIRA 项目 Key</label>
              <input id="settings-jira-project" type="text" value="${R.escapeHtml(state.settings.integration.jiraProjectKey || '')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            </div>
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">Git 仓库</label>
              <input id="settings-github-repo" type="text" value="${R.escapeHtml(state.settings.integration.githubRepo || '')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            </div>
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">Git 分支</label>
              <input id="settings-github-branch" type="text" value="${R.escapeHtml(state.settings.integration.githubBranch || 'main')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
            </div>
          </div>
          <div class="mt-4 flex justify-end gap-2">
            <button id="settings-test-model" class="px-4 py-2 rounded-lg bg-[#22c55e]/20 text-[#22c55e] hover:bg-[#22c55e]/30 text-sm">测试当前启用模型</button>
            <button id="settings-test-conn" class="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-sm">测试连接</button>
            <button id="settings-save-api" class="px-4 py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 text-sm font-medium">保存</button>
          </div>
        </div>
      `;

      const modelListNode = $('#settings-model-list');
      const providerDefaultValues = Object.values(modelProviderDefaults);

      function renderModelCards() {
        modelListNode.innerHTML = modelDrafts.map((model) => {
          const isActive = model.id === activeModelId;
          const provider = normalizeModelProvider(model.provider);
          const defaultBaseUrl = defaultModelBaseUrl(provider);
          return `
            <div class="settings-model-row p-4 rounded-xl border ${isActive ? 'border-[#00d4ff]/50 bg-[#00d4ff]/10' : 'border-white/10 bg-white/5'}" data-model-id="${R.escapeHtml(model.id)}">
              <div class="flex items-center justify-between gap-3 mb-3">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="px-2 py-1 rounded-full text-xs ${isActive ? 'bg-[#00d4ff]/20 text-[#00d4ff]' : 'bg-white/10 text-[#a1a1aa]'}">${isActive ? '已启用' : '未启用'}</span>
                  <span class="text-sm font-medium">${R.escapeHtml(model.name || '未命名模型')}</span>
                </div>
                <div class="flex items-center gap-2">
                  <button data-action="activate-model" data-model-id="${R.escapeHtml(model.id)}" class="px-3 py-1.5 rounded-lg text-xs ${isActive ? 'bg-[#00d4ff]/20 text-[#00d4ff]' : 'bg-white/10 hover:bg-white/20 text-white'}">${isActive ? '当前使用' : '设为启用'}</button>
                  <button data-action="remove-model" data-model-id="${R.escapeHtml(model.id)}" class="px-3 py-1.5 rounded-lg text-xs bg-[#ef4444]/20 text-[#ef4444] ${modelDrafts.length <= 1 ? 'opacity-40 cursor-not-allowed' : 'hover:bg-[#ef4444]/30'}" ${modelDrafts.length <= 1 ? 'disabled' : ''}>删除</button>
                </div>
              </div>
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs text-[#a1a1aa] mb-1">展示名称</label>
                  <input data-field="name" type="text" value="${R.escapeHtml(model.name || '')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
                </div>
                <div>
                  <label class="block text-xs text-[#a1a1aa] mb-1">模型厂商</label>
                  <select data-field="provider" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
                    <option value="OPENAI" ${provider === 'OPENAI' ? 'selected' : ''}>OpenAI</option>
                    <option value="ZHIPU" ${provider === 'ZHIPU' ? 'selected' : ''}>智谱 AI</option>
                    <option value="DEEPSEEK" ${provider === 'DEEPSEEK' ? 'selected' : ''}>DeepSeek</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs text-[#a1a1aa] mb-1">模型名称</label>
                  <input data-field="model" type="text" value="${R.escapeHtml(model.model || 'gpt-4o-mini')}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
                </div>
                <div>
                  <label class="block text-xs text-[#a1a1aa] mb-1">Base URL</label>
                  <input data-field="baseUrl" type="text" value="${R.escapeHtml(model.baseUrl || defaultBaseUrl)}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
                </div>
                <div>
                  <label class="block text-xs text-[#a1a1aa] mb-1">API Key</label>
                  <div class="flex gap-2">
                    <input data-field="apiKey" type="password" value="${R.escapeHtml(model.apiKey || '')}" autocomplete="off" class="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
                    <button data-action="toggle-api-key" data-model-id="${R.escapeHtml(model.id)}" class="px-3 py-2 rounded-lg bg-white/10 hover:bg-white/20 text-xs">显示</button>
                  </div>
                </div>
                <div>
                  <label class="block text-xs text-[#a1a1aa] mb-1">温度（0-2）</label>
                  <input data-field="temperature" type="number" min="0" max="2" step="0.1" value="${R.escapeHtml(String(model.temperature ?? 0.7))}" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" />
                </div>
              </div>
              <div class="mt-3 flex justify-end">
                <button data-action="test-model" data-model-id="${R.escapeHtml(model.id)}" class="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-xs">测试此模型</button>
              </div>
            </div>
          `;
        }).join('');
      }

      function readModelRow(row, index) {
        const id = String(row?.dataset?.modelId || `MODEL-${index + 1}`).trim() || `MODEL-${index + 1}`;
        const provider = normalizeModelProvider(row.querySelector('[data-field="provider"]')?.value || 'OPENAI');
        const model = (row.querySelector('[data-field="model"]')?.value || '').trim() || 'gpt-4o-mini';
        const baseUrlRaw = (row.querySelector('[data-field="baseUrl"]')?.value || '').trim();
        const baseUrl = baseUrlRaw || defaultModelBaseUrl(provider);
        const apiKey = (row.querySelector('[data-field="apiKey"]')?.value || '').trim();
        const temperature = clampModelTemperature(row.querySelector('[data-field="temperature"]')?.value);
        const name = (row.querySelector('[data-field="name"]')?.value || '').trim() || `${provider} / ${model}`;
        return { id, name, provider, baseUrl, apiKey, model, temperature };
      }

      function collectModelsFromDom() {
        const rows = $$('#settings-model-list .settings-model-row');
        const models = rows.map((row, index) => readModelRow(row, index));
        return models.length ? models : modelDrafts.map((item) => ({ ...item }));
      }

      async function testSingleModel(modelConfig) {
        try {
          const result = await R.api('/settings/integration/model/test', {
            method: 'POST',
            body: {
              provider: modelConfig.provider,
              baseUrl: modelConfig.baseUrl,
              apiKey: modelConfig.apiKey,
              model: modelConfig.model,
              temperature: modelConfig.temperature
            }
          });
          if (result?.reachable) {
            R.toast(`模型连接成功（${result.model}，${result.latencyMs || '-'}ms）`, 'success');
          } else {
            R.toast(result?.message || '模型连接失败', 'warning');
          }
          R.showJsonModal('模型连接测试结果', result || {});
        } catch (error) {
          R.toast(error.message || '模型连接失败', 'error');
        }
      }

      function collectIntegrationPatch() {
        modelDrafts = collectModelsFromDom().map((item) => ({
          ...item,
          provider: normalizeModelProvider(item.provider),
          baseUrl: item.baseUrl || defaultModelBaseUrl(item.provider),
          model: item.model || 'gpt-4o-mini',
          temperature: clampModelTemperature(item.temperature)
        }));
        if (!modelDrafts.length) {
          throw new Error('请至少保留一个模型配置');
        }
        if (!modelDrafts.some((item) => item.id === activeModelId)) {
          activeModelId = modelDrafts[0].id;
        }
        const activeModel = modelDrafts.find((item) => item.id === activeModelId) || modelDrafts[0];
        const openaiAlias = ($('#settings-openai-model').value || '').trim() || activeModel.model || 'gpt-4o-mini';
        return {
          apiBase: ($('#settings-api-base').value || '').trim() || '/api',
          models: modelDrafts,
          activeModelId,
          modelProvider: activeModel.provider,
          modelBaseUrl: activeModel.baseUrl,
          modelApiKey: activeModel.apiKey,
          modelName: activeModel.model,
          modelTemperature: activeModel.temperature,
          openaiModel: openaiAlias,
          jiraServerUrl: ($('#settings-jira-url').value || '').trim(),
          jiraProjectKey: ($('#settings-jira-project').value || '').trim(),
          githubRepo: ($('#settings-github-repo').value || '').trim(),
          githubBranch: ($('#settings-github-branch').value || '').trim() || 'main'
        };
      }

      renderModelCards();

      modelListNode.addEventListener('click', async (event) => {
        const trigger = event.target.closest('button[data-action]');
        if (!trigger) return;
        const action = trigger.dataset.action;
        const modelId = String(trigger.dataset.modelId || '').trim();
        const row = trigger.closest('.settings-model-row');

        if (action === 'toggle-api-key' && row) {
          const apiKeyInput = row.querySelector('input[data-field="apiKey"]');
          if (!apiKeyInput) return;
          const nextType = apiKeyInput.type === 'password' ? 'text' : 'password';
          apiKeyInput.type = nextType;
          trigger.textContent = nextType === 'password' ? '显示' : '隐藏';
          return;
        }

        modelDrafts = collectModelsFromDom();

        if (action === 'activate-model' && modelId) {
          activeModelId = modelId;
          renderModelCards();
          return;
        }

        if (action === 'remove-model' && modelId) {
          if (modelDrafts.length <= 1) {
            R.toast('至少保留一个模型配置', 'warning');
            return;
          }
          modelDrafts = modelDrafts.filter((item) => item.id !== modelId);
          if (!modelDrafts.some((item) => item.id === activeModelId)) {
            activeModelId = modelDrafts[0]?.id || '';
          }
          renderModelCards();
          return;
        }

        if (action === 'test-model' && modelId) {
          const modelConfig = modelDrafts.find((item) => item.id === modelId);
          if (!modelConfig) {
            R.toast('模型配置不存在', 'warning');
            return;
          }
          await testSingleModel(modelConfig);
        }
      });

      modelListNode.addEventListener('change', (event) => {
        const select = event.target.closest('select[data-field="provider"]');
        if (!select) return;
        const row = select.closest('.settings-model-row');
        if (!row) return;
        const baseUrlInput = row.querySelector('input[data-field="baseUrl"]');
        if (!baseUrlInput) return;
        const normalizedProvider = normalizeModelProvider(select.value || 'OPENAI');
        const currentBaseUrl = (baseUrlInput.value || '').trim();
        if (!currentBaseUrl || providerDefaultValues.includes(currentBaseUrl)) {
          baseUrlInput.value = defaultModelBaseUrl(normalizedProvider);
        }
      });

      $('#settings-model-add').addEventListener('click', () => {
        modelDrafts = collectModelsFromDom();
        const provider = 'OPENAI';
        const model = 'gpt-4o-mini';
        modelDrafts.push({
          id: createModelId(),
          name: `${provider} / ${model}`,
          provider,
          baseUrl: defaultModelBaseUrl(provider),
          apiKey: '',
          model,
          temperature: 0.7
        });
        renderModelCards();
      });

      $('#settings-save-api').addEventListener('click', async () => {
        try {
          const integrationPatch = collectIntegrationPatch();
          await persistSettingsPatch({ integration: integrationPatch }, '集成配置已保存');
          state.settings.integration = normalizeIntegrationSettings(state.settings.integration || {});
          activeModelId = state.settings.integration.activeModelId;
          modelDrafts = state.settings.integration.models.map((item) => ({ ...item }));
          renderModelCards();
        } catch (error) {
          R.toast(error.message || '集成配置保存失败', 'error');
        }
      });

      $('#settings-test-model').addEventListener('click', async () => {
        try {
          const integrationPatch = collectIntegrationPatch();
          const activeModel = integrationPatch.models.find((item) => item.id === integrationPatch.activeModelId) || integrationPatch.models[0];
          if (!activeModel) {
            R.toast('缺少可测试的模型配置', 'warning');
            return;
          }
          await testSingleModel(activeModel);
        } catch (error) {
          R.toast(error.message || '模型连接失败', 'error');
        }
      });

      $('#settings-test-conn').addEventListener('click', async () => {
        try {
          const jiraUrl = $('#settings-jira-url').value.trim();
          const apiStatus = await R.api('/dashboard');
          let jiraStatus = { reachable: true, message: '未配置 JIRA，已跳过' };
          if (jiraUrl) {
            jiraStatus = await R.api('/user-stories/import/test-connection', {
              method: 'POST',
              body: {
                sourceType: 'JIRA',
                serverUrl: jiraUrl,
                projectKey: $('#settings-jira-project').value.trim()
              }
            });
          }
          const message = jiraStatus.reachable
            ? '连接正常'
            : `API 可用，但 JIRA 不可达: ${jiraStatus.message || '未知错误'}`;
          R.toast(message, jiraStatus.reachable ? 'success' : 'warning');
          void apiStatus;
        } catch (error) {
          R.toast(error.message || '连接失败', 'error');
        }
      });
    }

    function renderApiKeySection() {
      const token = R.getAccessToken() || '';
      const refresh = R.getRefreshToken() || '';
      dynamicHost.innerHTML = `
        <div class="glass-card p-6">
          <h3 class="text-lg font-semibold mb-4">API 密钥与安全</h3>
          <div class="space-y-3 text-sm">
            <p><span class="text-[#a1a1aa]">Access Token:</span> <code>${R.escapeHtml(token ? `${token.slice(0, 24)}...` : '未登录')}</code></p>
            <p><span class="text-[#a1a1aa]">Refresh Token:</span> <code>${R.escapeHtml(refresh ? `${refresh.slice(0, 24)}...` : '未登录')}</code></p>
            <p><span class="text-[#a1a1aa]">当前角色:</span> <code>${R.escapeHtml(roleDisplayName(state.currentUser?.role || 'OPERATIONS_ADMIN'))}</code></p>
          </div>
          <div class="mt-4 flex gap-2">
            <button id="settings-copy-access" class="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-sm">复制 Access Token</button>
            <button id="settings-change-password" class="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-sm">修改密码</button>
            <button id="settings-logout" data-action="logout" class="px-4 py-2 rounded-lg bg-[#ef4444]/20 text-[#ef4444] text-sm">退出登录</button>
          </div>
        </div>
      `;

      $('#settings-copy-access').addEventListener('click', async () => {
        if (!token) {
          R.toast('当前无可复制 token', 'warning');
          return;
        }
        await navigator.clipboard.writeText(token);
        R.toast('Access Token 已复制', 'success');
      });

      $('#settings-change-password').addEventListener('click', async () => {
        const currentUser = R.getUserCache();
        if (!currentUser?.id) {
          R.toast('请先登录', 'warning');
          return;
        }
        const oldPassword = window.prompt('旧密码');
        if (!oldPassword) return;
        const newPassword = window.prompt('新密码（至少 6 位）');
        if (!newPassword || newPassword.length < 6) {
          R.toast('新密码长度不足', 'warning');
          return;
        }

        await R.api(`/users/${currentUser.id}/change-password`, {
          method: 'POST',
          body: { oldPassword, newPassword }
        });
        R.toast('密码修改成功', 'success');
      });
    }

    function renderNotificationSection() {
      dynamicHost.innerHTML = `
        <div class="glass-card p-6">
          <h3 class="text-lg font-semibold mb-4">通知设置</h3>
          <div class="space-y-3">
            <label class="flex items-center justify-between text-sm"><span>执行完成通知</span><input id="notify-exec" type="checkbox" class="w-5 h-5" ${state.settings.notification?.executionComplete ? 'checked' : ''}></label>
            <label class="flex items-center justify-between text-sm"><span>失败告警通知</span><input id="notify-fail" type="checkbox" class="w-5 h-5" ${state.settings.notification?.executionFailed ? 'checked' : ''}></label>
            <label class="flex items-center justify-between text-sm"><span>日报通知</span><input id="notify-daily" type="checkbox" class="w-5 h-5" ${state.settings.notification?.dailyReport ? 'checked' : ''}></label>
          </div>
          <div class="mt-4 flex justify-end">
            <button id="notify-save" class="px-4 py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 text-sm font-medium">保存通知配置</button>
          </div>
        </div>
      `;

      $('#notify-save').addEventListener('click', async () => {
        await persistSettingsPatch({
          notification: {
            executionComplete: $('#notify-exec').checked,
            executionFailed: $('#notify-fail').checked,
            dailyReport: $('#notify-daily').checked
          },
          general: {
            notifications: $('#notify-exec').checked || $('#notify-fail').checked || $('#notify-daily').checked
          }
        }, '通知配置已保存');
      });
    }

    function renderExecutionSection() {
      dynamicHost.innerHTML = `
        <div class="glass-card p-6">
          <h3 class="text-lg font-semibold mb-4">执行默认配置</h3>
          <div class="grid grid-cols-3 gap-4">
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">默认浏览器</label>
              <select id="exec-browser" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
                <option value="chromium">Chrome</option>
                <option value="firefox">Firefox</option>
                <option value="webkit">Safari</option>
              </select>
            </div>
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">默认环境</label>
              <select id="exec-env" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]">
                <option value="staging">Staging</option>
                <option value="dev">Dev</option>
                <option value="prod">Prod</option>
              </select>
            </div>
            <div>
              <label class="block text-sm text-[#a1a1aa] mb-2">目标 URL</label>
              <input id="exec-target" type="text" class="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-[#00d4ff]" value="${R.escapeHtml(state.settings.execution?.defaultTargetUrl || 'https://example.com')}" />
            </div>
          </div>
          <div class="mt-4 flex justify-end gap-2">
            <button id="exec-reset" class="px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-sm">重置</button>
            <button id="exec-save" class="px-4 py-2 rounded-lg bg-gradient-to-r from-[#00d4ff] to-[#7c3aed] hover:opacity-90 text-sm font-medium">保存</button>
          </div>
        </div>
      `;

      $('#exec-browser').value = state.settings.execution?.defaultBrowser || 'chromium';
      $('#exec-env').value = state.settings.execution?.defaultEnvironment || 'staging';

      $('#exec-save').addEventListener('click', async () => {
        await persistSettingsPatch({
          execution: {
            defaultBrowser: $('#exec-browser').value,
            defaultEnvironment: $('#exec-env').value,
            defaultTargetUrl: $('#exec-target').value.trim() || 'https://example.com'
          }
        }, '执行配置已保存');
      });

      $('#exec-reset').addEventListener('click', async () => {
        await persistSettingsPatch({
          execution: {
            defaultBrowser: 'chromium',
            defaultEnvironment: 'staging',
            defaultTargetUrl: 'https://example.com'
          }
        }, '执行配置已重置');
        renderExecutionSection();
      });
    }

    async function renderActiveTab() {
      const visibleTabs = getVisibleTabs();
      if (!visibleTabs.length) {
        dynamicHost.innerHTML = '<div class="glass-card p-6 text-sm text-[#a1a1aa]">暂无可用设置项。</div>';
        return;
      }
      if (!visibleTabs.some((tab) => tab.key === state.activeTab)) {
        state.activeTab = visibleTabs[0].key;
      }
      markTabActive();
      const tab = visibleTabs.find((item) => item.key === state.activeTab);
      if (!tab) return;
      await tab.render();
    }

    try {
      const remoteSettings = await R.api('/settings');
      if (remoteSettings?.settings && typeof remoteSettings.settings === 'object') {
        state.settings = deepMergeObject(cloneObject(state.settings), remoteSettings.settings);
        state.settings.integration = normalizeIntegrationSettings(state.settings.integration || {});
        R.saveSettings(toLegacyRuntimeSettings(state.settings));
      }
    } catch (_error) {
      // Fallback to local settings silently.
    }

    syncTabButtons();
    if (!getVisibleTabs().some((tab) => tab.key === state.activeTab)) {
      state.activeTab = getVisibleTabs()[0]?.key || 'general';
    }

    tabButtons.forEach((button) => {
      button.addEventListener('click', async () => {
        const nextKey = button.dataset.tabKey;
        if (!nextKey) return;
        state.activeTab = nextKey;
        await renderActiveTab();
      });
    });

    window.saveSettings = () => {
      renderActiveTab().catch((error) => R.toast(error.message || '保存失败', 'error'));
    };

    await renderActiveTab();

    const hash = String(window.location.hash || '').toLowerCase();
    if (hash === '#profile' || hash === '#avatar' || hash.includes('profile')) {
      state.activeTab = 'general';
      await renderActiveTab();
      const preview = $('#profile-avatar-preview');
      if (preview) {
        preview.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const panel = preview.closest('.glass-card') || preview;
        const originalShadow = panel.style.boxShadow || '';
        panel.style.boxShadow = '0 0 0 2px rgba(0,212,255,0.45)';
        window.setTimeout(() => {
          panel.style.boxShadow = originalShadow;
        }, 1800);
      }
    }
  }

  async function initializeByRoute() {
    const path = window.location.pathname;
    await refreshGlobalUsCounters();

    if (path.endsWith('/index.html') || path === '/' || /\/(?:test-auto-pro|Nasus|nasus)\/?$/.test(path)) {
      await initializeDashboardPage();
      return;
    }

    if (path.endsWith('/pages/us-management.html')) {
      await initializeUserStoriesPage();
      return;
    }

    if (path.endsWith('/pages/test-cases.html')) {
      await initializeTestCasesPage();
      return;
    }

    if (path.endsWith('/pages/script-studio.html')) {
      await initializeScriptStudioPage();
      return;
    }

    if (path.endsWith('/pages/execution-hub.html')) {
      await initializeExecutionHubPage();
      return;
    }

    if (path.endsWith('/pages/reports.html')) {
      await initializeReportsPage();
      return;
    }

    if (path.endsWith('/pages/settings.html')) {
      await initializeSettingsPage();
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    initializeByRoute().catch((error) => {
      R.toast(error.message || '页面初始化失败', 'error');
      console.error(error);
    });
  });
})();
