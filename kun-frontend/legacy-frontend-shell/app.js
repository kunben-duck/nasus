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
  defaultTargetUrl: 'https://example.com'
};

const SECTION_META = {
  dashboard: { title: '仪表盘', subtitle: '系统总览与运行状态' },
  'user-stories': { title: 'US 管理', subtitle: '维护需求并调用 Spring AI 分析与生成测试用例' },
  'test-cases': { title: '测试用例', subtitle: '管理测试用例和步骤' },
  'test-scripts': { title: '测试脚本', subtitle: '维护脚本并通过 Spring AI 自动生成' },
  executions: { title: '执行中心', subtitle: '创建与流转测试执行任务' },
  reports: { title: '报告中心', subtitle: '执行结果统计与导出' },
  settings: { title: '系统设置', subtitle: '前端 API 与默认执行配置' }
};

const state = {
  currentSection: 'dashboard',
  user: null,
  settings: loadSettings(),
  dashboard: null,
  userStories: [],
  testCases: [],
  testScripts: [],
  executions: []
};

document.addEventListener('DOMContentLoaded', () => {
  bindGlobalEvents();
  bindModuleEvents();
  fillSettingsForm();
  hydrateFromAuth();
});

function bindGlobalEvents() {
  document.getElementById('login-form').addEventListener('submit', handleLogin);
  document.getElementById('logout-btn').addEventListener('click', logout);
  document.getElementById('global-refresh').addEventListener('click', () => {
    refreshCurrentSection(true).catch((err) => notifyError(err, '刷新失败'));
  });

  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const target = btn.dataset.section;
      if (!target || target === state.currentSection) return;
      setSection(target);
      await refreshCurrentSection(true).catch((err) => notifyError(err, '加载页面失败'));
    });
  });
}

function bindModuleEvents() {
  document.getElementById('us-form').addEventListener('submit', submitUserStoryForm);
  document.getElementById('us-form-reset').addEventListener('click', resetUserStoryForm);
  document.getElementById('us-reload').addEventListener('click', () => loadUserStories(true));
  document.getElementById('us-table-body').addEventListener('click', onUserStoryTableClick);

  document.getElementById('case-form').addEventListener('submit', submitTestCaseForm);
  document.getElementById('case-form-reset').addEventListener('click', resetTestCaseForm);
  document.getElementById('case-reload').addEventListener('click', () => {
    loadTestCases(true).catch((err) => notifyError(err, '刷新测试用例失败'));
  });
  document.getElementById('case-table-body').addEventListener('click', onTestCaseTableClick);

  document.getElementById('script-form').addEventListener('submit', submitScriptForm);
  document.getElementById('script-form-reset').addEventListener('click', resetScriptForm);
  document.getElementById('script-reload').addEventListener('click', () => {
    loadTestScripts(true).catch((err) => notifyError(err, '刷新脚本失败'));
  });
  document.getElementById('script-table-body').addEventListener('click', onScriptTableClick);
  document.getElementById('ai-script-form').addEventListener('submit', submitAIScriptForm);

  document.getElementById('execution-form').addEventListener('submit', submitExecutionForm);
  document.getElementById('execution-reload').addEventListener('click', () => {
    loadExecutions(true).catch((err) => notifyError(err, '刷新执行失败'));
  });
  document.getElementById('execution-table-body').addEventListener('click', onExecutionTableClick);

  document.getElementById('download-report-btn').addEventListener('click', downloadReport);

  document.getElementById('settings-form').addEventListener('submit', saveSettingsFromForm);
  document.getElementById('settings-test-connection').addEventListener('click', testConnection);
}

async function hydrateFromAuth() {
  const accessToken = localStorage.getItem(STORAGE_KEYS.accessToken);
  if (!accessToken) {
    showLogin();
    return;
  }

  try {
    const me = await apiRequest('/auth/me');
    state.user = me;
    showApp();
    await refreshAllData();
  } catch (err) {
    clearAuth();
    showLogin();
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errorNode = document.getElementById('login-error');
  errorNode.classList.add('hidden');

  try {
    const response = await apiRequest('/auth/login', {
      method: 'POST',
      auth: false,
      body: { username, password }
    });

    localStorage.setItem(STORAGE_KEYS.accessToken, response.accessToken);
    localStorage.setItem(STORAGE_KEYS.refreshToken, response.refreshToken);
    localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(response.user));

    state.user = response.user;
    showApp();
    await refreshAllData();
    toast('登录成功', 'success');
  } catch (err) {
    errorNode.textContent = err.message || '登录失败';
    errorNode.classList.remove('hidden');
  }
}

function logout() {
  clearAuth();
  state.user = null;
  state.dashboard = null;
  state.userStories = [];
  state.testCases = [];
  state.testScripts = [];
  state.executions = [];
  showLogin();
}

function clearAuth() {
  localStorage.removeItem(STORAGE_KEYS.accessToken);
  localStorage.removeItem(STORAGE_KEYS.refreshToken);
  localStorage.removeItem(STORAGE_KEYS.user);
}

function showLogin() {
  document.getElementById('login-view').classList.remove('hidden');
  document.getElementById('app-shell').classList.add('hidden');
}

function showApp() {
  document.getElementById('login-view').classList.add('hidden');
  document.getElementById('app-shell').classList.remove('hidden');
  const name = state.user?.fullName || state.user?.username || 'Unknown';
  document.getElementById('current-user').textContent = name;
}

function setSection(section) {
  state.currentSection = section;
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.section === section);
  });

  document.querySelectorAll('.section').forEach((node) => {
    node.classList.toggle('active', node.id === `section-${section}`);
  });

  const meta = SECTION_META[section] || SECTION_META.dashboard;
  document.getElementById('section-title').textContent = meta.title;
  document.getElementById('section-subtitle').textContent = meta.subtitle;
}

async function refreshAllData() {
  const results = await Promise.allSettled([
    loadDashboard(true),
    loadUserStories(true),
    loadTestCases(true),
    loadTestScripts(true),
    loadExecutions(true)
  ]);
  const failed = results.filter((item) => item.status === 'rejected');
  if (failed.length > 0) {
    toast(`${failed.length} 个模块加载失败，请点击“刷新当前页”重试`, 'error');
  }
  renderReports();
}

async function refreshCurrentSection(force) {
  switch (state.currentSection) {
    case 'dashboard':
      await loadDashboard(force);
      return;
    case 'user-stories':
      await loadUserStories(force);
      return;
    case 'test-cases':
      await loadTestCases(force);
      return;
    case 'test-scripts':
      await loadTestScripts(force);
      return;
    case 'executions':
      await loadExecutions(force);
      return;
    case 'reports':
      await loadExecutions(force);
      renderReports();
      return;
    case 'settings':
      fillSettingsForm();
      return;
    default:
      return;
  }
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.settings);
    if (!raw) return { ...DEFAULT_SETTINGS };
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch (_err) {
    return { ...DEFAULT_SETTINGS };
  }
}

function fillSettingsForm() {
  document.getElementById('settings-api-base').value = state.settings.apiBase;
  document.getElementById('settings-browser').value = state.settings.defaultBrowser;
  document.getElementById('settings-environment').value = state.settings.defaultEnvironment;
  document.getElementById('settings-target-url').value = state.settings.defaultTargetUrl;

  if (!document.getElementById('execution-browser').value) {
    document.getElementById('execution-browser').value = state.settings.defaultBrowser;
  }
  if (!document.getElementById('execution-env').value) {
    document.getElementById('execution-env').value = state.settings.defaultEnvironment;
  }
  if (!document.getElementById('ai-target-url').value) {
    document.getElementById('ai-target-url').value = state.settings.defaultTargetUrl;
  }
}

function saveSettingsFromForm(event) {
  event.preventDefault();
  state.settings = {
    apiBase: document.getElementById('settings-api-base').value.trim() || '/api',
    defaultBrowser: document.getElementById('settings-browser').value.trim() || 'chromium',
    defaultEnvironment: document.getElementById('settings-environment').value.trim() || 'staging',
    defaultTargetUrl: document.getElementById('settings-target-url').value.trim() || 'https://example.com'
  };
  localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(state.settings));
  document.getElementById('execution-browser').value = state.settings.defaultBrowser;
  document.getElementById('execution-env').value = state.settings.defaultEnvironment;
  document.getElementById('ai-target-url').value = state.settings.defaultTargetUrl;
  toast('设置已保存', 'success');
}

async function testConnection() {
  const statusNode = document.getElementById('settings-connection-status');
  statusNode.textContent = '检测中';

  try {
    if (localStorage.getItem(STORAGE_KEYS.accessToken)) {
      await apiRequest('/auth/me');
    } else {
      await apiRequest('/dashboard', { auth: false });
    }
    statusNode.textContent = '连接正常';
    toast('后端连接正常', 'success');
  } catch (err) {
    statusNode.textContent = '连接失败';
    notifyError(err, '后端连接失败');
  }
}

async function loadDashboard(force) {
  if (state.dashboard && !force) {
    renderDashboard();
    return;
  }
  state.dashboard = await apiRequest('/dashboard');
  renderDashboard();
}

function renderDashboard() {
  const statistics = state.dashboard?.statistics || {};
  document.getElementById('dash-total-us').textContent = numberOrDash(statistics.totalUserStories);
  document.getElementById('dash-total-cases').textContent = numberOrDash(statistics.totalTestCases);
  document.getElementById('dash-total-scripts').textContent = numberOrDash(statistics.totalScripts);
  document.getElementById('dash-success-rate').textContent = statistics.successRate != null
    ? `${statistics.successRate}%`
    : '-';

  const recent = state.dashboard?.recentActivities || {};
  renderSimpleList(
    document.getElementById('dash-recent-executions'),
    (recent.recentExecutions || []).map((item) => `${item.id} | ${item.status} | ${item.title}`),
    '暂无执行数据'
  );
  renderSimpleList(
    document.getElementById('dash-recent-us'),
    (recent.recentUserStories || []).map((item) => `${item.id} | ${item.status} | ${item.title}`),
    '暂无 US 数据'
  );

  const systemStatus = state.dashboard?.systemStatus || {};
  const lines = [
    `Database: ${systemStatus.databaseStatus || '-'}`,
    `Redis: ${systemStatus.redisStatus || '-'}`,
    `RabbitMQ: ${systemStatus.rabbitmqStatus || '-'}`,
    `AI Service: ${systemStatus.aiServiceStatus || '-'}`,
    `Active Executors: ${systemStatus.activeExecutors ?? '-'}`,
    `Queued Tasks: ${systemStatus.queuedTasks ?? '-'}`
  ];
  renderSimpleList(document.getElementById('dash-system-status'), lines, '暂无系统状态');
}

async function loadUserStories(force) {
  if (state.userStories.length > 0 && !force) {
    renderUserStories();
    return;
  }

  const page = await apiRequest('/user-stories?page=0&size=200');
  state.userStories = page?.content || [];
  renderUserStories();
}

function renderUserStories() {
  const tbody = document.getElementById('us-table-body');
  if (state.userStories.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7">暂无 US 数据</td></tr>';
    return;
  }

  tbody.innerHTML = state.userStories.map((us) => {
    return `
      <tr>
        <td>${us.id}</td>
        <td>${escapeHtml(us.usNumber || '-')}</td>
        <td>${escapeHtml(us.title || '-')}</td>
        <td>${escapeHtml(us.priority || '-')}</td>
        <td>${escapeHtml(us.status || '-')}</td>
        <td>${numberOrDash(us.testCaseCount)}</td>
        <td>
          <div class="cell-actions">
            <button data-action="edit" data-id="${us.id}">编辑</button>
            <button data-action="analyze" data-id="${us.id}">AI分析</button>
            <button data-action="generate" data-id="${us.id}">生成用例</button>
            <button data-action="delete" data-id="${us.id}">删除</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function resetUserStoryForm() {
  document.getElementById('us-form').reset();
  document.getElementById('us-id').value = '';
  document.getElementById('us-number').disabled = false;
  document.getElementById('us-status').value = 'DRAFT';
  document.getElementById('us-priority').value = 'MEDIUM';
}

function fillUserStoryForm(us) {
  document.getElementById('us-id').value = us.id;
  document.getElementById('us-number').value = us.usNumber || '';
  document.getElementById('us-number').disabled = true;
  document.getElementById('us-title').value = us.title || '';
  document.getElementById('us-priority').value = us.priority || 'MEDIUM';
  document.getElementById('us-status').value = us.status || 'DRAFT';
  document.getElementById('us-sprint').value = us.sprint || '';
  document.getElementById('us-epic').value = us.epic || '';
  document.getElementById('us-story-points').value = us.storyPoints || '';
  document.getElementById('us-description').value = us.description || '';
  document.getElementById('us-acceptance').value = us.acceptanceCriteria || '';
}

async function submitUserStoryForm(event) {
  event.preventDefault();
  const id = toNumber(document.getElementById('us-id').value);

  const basePayload = {
    title: document.getElementById('us-title').value.trim(),
    description: document.getElementById('us-description').value.trim(),
    acceptanceCriteria: document.getElementById('us-acceptance').value.trim(),
    priority: document.getElementById('us-priority').value,
    sprint: document.getElementById('us-sprint').value.trim(),
    epic: document.getElementById('us-epic').value.trim(),
    storyPoints: document.getElementById('us-story-points').value.trim()
  };

  try {
    if (id) {
      await apiRequest(`/user-stories/${id}`, {
        method: 'PUT',
        body: {
          ...basePayload,
          status: document.getElementById('us-status').value
        }
      });
      toast('US 更新成功', 'success');
    } else {
      await apiRequest('/user-stories', {
        method: 'POST',
        body: {
          usNumber: document.getElementById('us-number').value.trim(),
          ...basePayload
        }
      });
      toast('US 创建成功', 'success');
    }

    resetUserStoryForm();
    await loadUserStories(true);
    await loadDashboard(true);
  } catch (err) {
    notifyError(err, '保存 US 失败');
  }
}

async function onUserStoryTableClick(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;

  const id = toNumber(button.dataset.id);
  if (!id) return;

  const action = button.dataset.action;
  const item = state.userStories.find((us) => us.id === id);
  if (!item) return;

  try {
    if (action === 'edit') {
      fillUserStoryForm(item);
      return;
    }

    if (action === 'delete') {
      if (!window.confirm(`确认删除 ${item.usNumber} ?`)) return;
      await apiRequest(`/user-stories/${id}`, { method: 'DELETE' });
      toast('US 已删除', 'success');
      await loadUserStories(true);
      await loadDashboard(true);
      return;
    }

    if (action === 'analyze') {
      const result = await apiRequest(`/user-stories/${id}/analyze`, {
        method: 'POST',
        body: {}
      });
      renderAnalysisResult(result);
      toast('AI 分析完成', 'success');
      return;
    }

    if (action === 'generate') {
      const countInput = window.prompt('请输入生成测试用例数量（1-20）', '3');
      const count = Math.max(1, Math.min(20, toNumber(countInput) || 3));
      const result = await apiRequest(`/user-stories/${id}/generate-test-cases`, {
        method: 'POST',
        body: { count }
      });
      toast(`AI 已生成 ${result?.length || 0} 条测试用例`, 'success');
      await loadTestCases(true);
      await loadUserStories(true);
      await loadDashboard(true);
      return;
    }
  } catch (err) {
    notifyError(err, 'US 操作失败');
  }
}

function renderAnalysisResult(result) {
  const summary = result?.analysisSummary || '无分析摘要';
  const validation = (result?.validationPoints || [])
    .map((item, idx) => `${idx + 1}. [${item.priority}] ${item.description}\n   期望: ${item.expectedResult}`)
    .join('\n') || '无验证点';

  const suggestions = (result?.suggestedTestCases || [])
    .map((item, idx) => `${idx + 1}. [${item.testType}/${item.priority}] ${item.title}\n   ${item.description}`)
    .join('\n') || '无推荐用例';

  const text = `分析摘要:\n${summary}\n\n验证点:\n${validation}\n\n建议测试用例:\n${suggestions}`;
  document.getElementById('us-analysis').textContent = text;
}

async function loadTestCases(force) {
  if (state.testCases.length > 0 && !force) {
    renderTestCases();
    return;
  }

  const [page, stats] = await Promise.all([
    apiRequest('/test-cases?page=0&size=300'),
    apiRequest('/test-cases/stats')
  ]);

  state.testCases = page?.content || [];
  renderTestCases();
  renderCaseStats(stats || {});
}

function renderCaseStats(stats) {
  const lines = [
    `总数: ${stats.total ?? '-'}`,
    `草稿: ${stats.draft ?? '-'}`,
    `评审中: ${stats.review ?? '-'}`,
    `就绪: ${stats.ready ?? '-'}`
  ];
  renderSimpleList(document.getElementById('case-stats'), lines, '暂无统计数据');
}

function renderTestCases() {
  const tbody = document.getElementById('case-table-body');
  if (state.testCases.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8">暂无测试用例</td></tr>';
    return;
  }

  tbody.innerHTML = state.testCases.map((tc) => `
    <tr>
      <td>${tc.id}</td>
      <td>${escapeHtml(tc.caseNumber || '-')}</td>
      <td>${escapeHtml(tc.title || '-')}</td>
      <td>${escapeHtml(tc.testType || '-')}</td>
      <td>${escapeHtml(tc.priority || '-')}</td>
      <td>${escapeHtml(tc.status || '-')}</td>
      <td>${tc.userStory?.id || '-'}</td>
      <td>
        <div class="cell-actions">
          <button data-action="edit" data-id="${tc.id}">编辑</button>
          <button data-action="delete" data-id="${tc.id}">删除</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function resetTestCaseForm() {
  document.getElementById('case-form').reset();
  document.getElementById('case-id').value = '';
  document.getElementById('case-type').value = 'FUNCTIONAL';
  document.getElementById('case-priority').value = 'MEDIUM';
  document.getElementById('case-status').value = 'DRAFT';
}

function fillTestCaseForm(tc) {
  document.getElementById('case-id').value = tc.id;
  document.getElementById('case-title').value = tc.title || '';
  document.getElementById('case-us-id').value = tc.userStory?.id || '';
  document.getElementById('case-type').value = tc.testType || 'FUNCTIONAL';
  document.getElementById('case-priority').value = tc.priority || 'MEDIUM';
  document.getElementById('case-status').value = tc.status || 'DRAFT';
  document.getElementById('case-tags').value = tc.tags || '';
  document.getElementById('case-preconditions').value = tc.preconditions || '';
  document.getElementById('case-description').value = tc.description || '';
  document.getElementById('case-steps').value = (tc.steps || [])
    .map((step) => `${step.action || ''} | ${step.expectedResult || ''} | ${step.testData || ''}`)
    .join('\n');
}

async function submitTestCaseForm(event) {
  event.preventDefault();
  const id = toNumber(document.getElementById('case-id').value);
  const payload = {
    title: document.getElementById('case-title').value.trim(),
    description: document.getElementById('case-description').value.trim(),
    preconditions: document.getElementById('case-preconditions').value.trim(),
    testType: document.getElementById('case-type').value,
    priority: document.getElementById('case-priority').value,
    tags: document.getElementById('case-tags').value.trim(),
    steps: parseSteps(document.getElementById('case-steps').value)
  };

  try {
    if (id) {
      await apiRequest(`/test-cases/${id}`, {
        method: 'PUT',
        body: {
          ...payload,
          status: document.getElementById('case-status').value
        }
      });
      toast('测试用例更新成功', 'success');
    } else {
      await apiRequest('/test-cases', {
        method: 'POST',
        body: {
          ...payload,
          userStoryId: toNumber(document.getElementById('case-us-id').value)
        }
      });
      toast('测试用例创建成功', 'success');
    }

    resetTestCaseForm();
    await loadTestCases(true);
    await loadDashboard(true);
  } catch (err) {
    notifyError(err, '保存测试用例失败');
  }
}

async function onTestCaseTableClick(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;

  const id = toNumber(button.dataset.id);
  if (!id) return;
  const action = button.dataset.action;
  const item = state.testCases.find((tc) => tc.id === id);
  if (!item) return;

  try {
    if (action === 'edit') {
      fillTestCaseForm(item);
      return;
    }

    if (action === 'delete') {
      if (!window.confirm(`确认删除用例 ${item.caseNumber} ?`)) return;
      await apiRequest(`/test-cases/${id}`, { method: 'DELETE' });
      toast('测试用例已删除', 'success');
      await loadTestCases(true);
      await loadDashboard(true);
      return;
    }
  } catch (err) {
    notifyError(err, '测试用例操作失败');
  }
}

async function loadTestScripts(force) {
  if (state.testScripts.length > 0 && !force) {
    renderScripts();
    return;
  }

  const page = await apiRequest('/test-scripts?page=0&size=300');
  state.testScripts = page?.content || [];
  renderScripts();
}

function renderScripts() {
  const tbody = document.getElementById('script-table-body');
  if (state.testScripts.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7">暂无脚本</td></tr>';
    return;
  }

  tbody.innerHTML = state.testScripts.map((script) => `
    <tr>
      <td>${script.id}</td>
      <td>${escapeHtml(script.name || '-')}</td>
      <td>${escapeHtml(script.scriptType || '-')}</td>
      <td>${escapeHtml(script.language || '-')}</td>
      <td>${escapeHtml(script.status || '-')}</td>
      <td>${script.testCase?.id || '-'}</td>
      <td>
        <div class="cell-actions">
          <button data-action="edit" data-id="${script.id}">编辑</button>
          <button data-action="view" data-id="${script.id}">查看代码</button>
          <button data-action="delete" data-id="${script.id}">删除</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function resetScriptForm() {
  document.getElementById('script-form').reset();
  document.getElementById('script-id').value = '';
  document.getElementById('script-type').value = 'PLAYWRIGHT';
  document.getElementById('script-language').value = 'JAVASCRIPT';
  document.getElementById('script-status').value = 'DRAFT';
}

function fillScriptForm(script) {
  document.getElementById('script-id').value = script.id;
  document.getElementById('script-name').value = script.name || '';
  document.getElementById('script-case-id').value = script.testCase?.id || '';
  document.getElementById('script-type').value = script.scriptType || 'PLAYWRIGHT';
  document.getElementById('script-language').value = script.language || 'JAVASCRIPT';
  document.getElementById('script-status').value = script.status || 'DRAFT';
  document.getElementById('script-config').value = script.config || '';
  document.getElementById('script-code').value = script.code || '';
}

async function submitScriptForm(event) {
  event.preventDefault();
  const id = toNumber(document.getElementById('script-id').value);

  try {
    if (id) {
      await apiRequest(`/test-scripts/${id}`, {
        method: 'PUT',
        body: {
          name: document.getElementById('script-name').value.trim(),
          code: document.getElementById('script-code').value,
          config: document.getElementById('script-config').value,
          status: document.getElementById('script-status').value
        }
      });
      toast('脚本更新成功', 'success');
    } else {
      await apiRequest('/test-scripts', {
        method: 'POST',
        body: {
          name: document.getElementById('script-name').value.trim(),
          scriptType: document.getElementById('script-type').value,
          language: document.getElementById('script-language').value,
          code: document.getElementById('script-code').value,
          config: document.getElementById('script-config').value,
          testCaseId: toNumber(document.getElementById('script-case-id').value)
        }
      });
      toast('脚本创建成功', 'success');
    }

    resetScriptForm();
    await loadTestScripts(true);
    await loadDashboard(true);
  } catch (err) {
    notifyError(err, '保存脚本失败');
  }
}

async function onScriptTableClick(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;

  const id = toNumber(button.dataset.id);
  if (!id) return;
  const action = button.dataset.action;
  const script = state.testScripts.find((item) => item.id === id);
  if (!script) return;

  try {
    if (action === 'edit') {
      fillScriptForm(script);
      return;
    }

    if (action === 'view') {
      document.getElementById('ai-script-output').textContent = script.code || '脚本无代码';
      return;
    }

    if (action === 'delete') {
      if (!window.confirm(`确认删除脚本 ${script.name} ?`)) return;
      await apiRequest(`/test-scripts/${id}`, { method: 'DELETE' });
      toast('脚本已删除', 'success');
      await loadTestScripts(true);
      await loadDashboard(true);
    }
  } catch (err) {
    notifyError(err, '脚本操作失败');
  }
}

async function submitAIScriptForm(event) {
  event.preventDefault();

  const payload = {
    testCaseId: toNumber(document.getElementById('ai-script-case-id').value),
    scriptType: document.getElementById('ai-script-type').value,
    language: document.getElementById('ai-script-language').value,
    targetUrl: document.getElementById('ai-target-url').value.trim(),
    additionalInstructions: document.getElementById('ai-instructions').value.trim()
  };

  try {
    const result = await apiRequest('/test-scripts/generate', {
      method: 'POST',
      body: payload
    });

    const dependencies = (result.dependencies || []).join(', ') || '无';
    const text = [
      `依赖: ${dependencies}`,
      '',
      result.explanation || '生成成功',
      '',
      result.generatedCode || ''
    ].join('\n');

    document.getElementById('ai-script-output').textContent = text;
    toast('AI 脚本生成成功并已保存', 'success');
    await loadTestScripts(true);
    await loadDashboard(true);
  } catch (err) {
    notifyError(err, 'AI 脚本生成失败');
  }
}

async function loadExecutions(force) {
  if (state.executions.length > 0 && !force) {
    renderExecutions();
    renderReports();
    return;
  }

  const [page, stats] = await Promise.all([
    apiRequest('/executions?page=0&size=300'),
    apiRequest('/executions/stats')
  ]);

  state.executions = page?.content || [];
  renderExecutions();
  renderExecutionStats(stats || {});
  renderReports();
}

function renderExecutionStats(stats) {
  const lines = [
    `总执行数: ${stats.total ?? '-'}`,
    `等待中: ${stats.pending ?? '-'}`,
    `运行中: ${stats.running ?? '-'}`,
    `已完成: ${stats.completed ?? '-'}`,
    `失败: ${stats.failed ?? '-'}`,
    `成功率: ${stats.successRate ?? '-'}%`,
    `平均时长(秒): ${stats.averageExecutionTime ?? '-'}`
  ];
  renderSimpleList(document.getElementById('execution-stats'), lines, '暂无执行统计');
}

function renderExecutions() {
  const tbody = document.getElementById('execution-table-body');
  if (state.executions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8">暂无执行任务</td></tr>';
    return;
  }

  tbody.innerHTML = state.executions.map((execution) => {
    const actions = [];
    if (execution.status === 'PENDING' || execution.status === 'QUEUED') {
      actions.push('<button data-action="start" data-id="' + execution.id + '">开始</button>');
      actions.push('<button data-action="cancel" data-id="' + execution.id + '">取消</button>');
    } else if (execution.status === 'RUNNING') {
      actions.push('<button data-action="complete" data-id="' + execution.id + '">完成</button>');
      actions.push('<button data-action="fail" data-id="' + execution.id + '">失败</button>');
      actions.push('<button data-action="cancel" data-id="' + execution.id + '">取消</button>');
    }

    return `
      <tr>
        <td>${execution.id}</td>
        <td>${escapeHtml(execution.executionId || '-')}</td>
        <td>${escapeHtml(execution.testCase?.caseNumber || '-')}</td>
        <td>${escapeHtml(execution.status || '-')}</td>
        <td>${escapeHtml(execution.result || '-')}</td>
        <td>${numberOrDash(execution.duration)}</td>
        <td>${escapeHtml(execution.executedBy || '-')}</td>
        <td><div class="cell-actions">${actions.join('')}</div></td>
      </tr>
    `;
  }).join('');
}

async function submitExecutionForm(event) {
  event.preventDefault();

  const payload = {
    testCaseId: toNumber(document.getElementById('execution-case-id').value),
    browser: document.getElementById('execution-browser').value.trim() || state.settings.defaultBrowser,
    environment: document.getElementById('execution-env').value.trim() || state.settings.defaultEnvironment
  };

  try {
    await apiRequest('/executions', {
      method: 'POST',
      body: payload
    });
    toast('执行任务已创建', 'success');
    event.target.reset();
    fillSettingsForm();
    await loadExecutions(true);
    await loadDashboard(true);
  } catch (err) {
    notifyError(err, '创建执行任务失败');
  }
}

async function onExecutionTableClick(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;

  const id = toNumber(button.dataset.id);
  if (!id) return;
  const action = button.dataset.action;

  try {
    if (action === 'start') {
      await apiRequest(`/executions/${id}/start`, { method: 'POST', body: {} });
      toast('执行已开始', 'success');
    } else if (action === 'cancel') {
      await apiRequest(`/executions/${id}/cancel`, { method: 'POST', body: {} });
      toast('执行已取消', 'info');
    } else if (action === 'fail') {
      const msg = window.prompt('请输入失败原因', '人工标记失败');
      if (msg == null) return;
      await apiRequest(`/executions/${id}/fail`, {
        method: 'POST',
        body: { errorMessage: msg }
      });
      toast('执行已标记失败', 'info');
    } else if (action === 'complete') {
      const resultInput = (window.prompt('请输入执行结果: PASS/FAIL/SKIP/ERROR/WARNING', 'PASS') || 'PASS').toUpperCase();
      const allowed = ['PASS', 'FAIL', 'SKIP', 'ERROR', 'WARNING'];
      const result = allowed.includes(resultInput) ? resultInput : 'PASS';
      const logs = window.prompt('请输入执行日志', '手工完成执行') || '';

      await apiRequest(`/executions/${id}/complete`, {
        method: 'POST',
        body: { result, logs }
      });
      toast('执行已完成', 'success');
    }

    await loadExecutions(true);
    await loadDashboard(true);
  } catch (err) {
    notifyError(err, '执行操作失败');
  }
}

function renderReports() {
  const executions = [...state.executions].sort((a, b) => {
    const left = new Date(b.createdAt || 0).getTime();
    const right = new Date(a.createdAt || 0).getTime();
    return left - right;
  });

  const total = executions.length;
  const pass = executions.filter((item) => item.result === 'PASS').length;
  const fail = executions.filter((item) => ['FAIL', 'ERROR'].includes(item.result) || item.status === 'FAILED').length;
  const rate = total > 0 ? ((pass / total) * 100).toFixed(2) : '0.00';

  document.getElementById('report-total').textContent = String(total);
  document.getElementById('report-pass').textContent = String(pass);
  document.getElementById('report-fail').textContent = String(fail);
  document.getElementById('report-rate').textContent = `${rate}%`;

  const tbody = document.getElementById('report-table-body');
  if (executions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7">暂无报告数据</td></tr>';
    return;
  }

  tbody.innerHTML = executions.map((item) => `
    <tr>
      <td>${escapeHtml(item.executionId || '-')}</td>
      <td>${escapeHtml(item.testCase?.caseNumber || '-')}</td>
      <td>${escapeHtml(item.status || '-')}</td>
      <td>${escapeHtml(item.result || '-')}</td>
      <td>${formatDate(item.startedAt)}</td>
      <td>${formatDate(item.completedAt)}</td>
      <td>${escapeHtml(item.errorMessage || '-')}</td>
    </tr>
  `).join('');
}

function downloadReport() {
  const payload = {
    generatedAt: new Date().toISOString(),
    statistics: {
      totalExecutions: state.executions.length,
      passed: state.executions.filter((item) => item.result === 'PASS').length,
      failed: state.executions.filter((item) => ['FAIL', 'ERROR'].includes(item.result) || item.status === 'FAILED').length
    },
    executions: state.executions
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `autotest-report-${Date.now()}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function apiRequest(endpoint, options = {}) {
  const method = options.method || 'GET';
  const body = options.body;
  const auth = options.auth !== false;
  const retry = options.retry !== false;
  const url = buildApiUrl(endpoint);

  const headers = {
    'Content-Type': 'application/json'
  };

  if (auth) {
    const token = localStorage.getItem(STORAGE_KEYS.accessToken);
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  const response = await fetch(url, {
    method,
    headers,
    body: body != null ? JSON.stringify(body) : undefined
  });

  if (response.status === 401 && auth && retry) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return apiRequest(endpoint, { ...options, retry: false });
    }
    clearAuth();
    showLogin();
    throw new Error('登录已过期，请重新登录');
  }

  const text = await response.text();
  const payload = parseJsonSafely(text);

  if (!response.ok) {
    const message = payload?.message || payload?.error || `HTTP ${response.status}`;
    throw new Error(message);
  }

  if (payload && typeof payload === 'object' && Object.prototype.hasOwnProperty.call(payload, 'success')) {
    if (!payload.success) {
      throw new Error(payload.message || '请求失败');
    }
    return payload.data;
  }

  return payload;
}

async function refreshAccessToken() {
  const refreshToken = localStorage.getItem(STORAGE_KEYS.refreshToken);
  if (!refreshToken) return false;

  const response = await fetch(buildApiUrl('/auth/refresh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refreshToken })
  });

  if (!response.ok) return false;
  const payload = parseJsonSafely(await response.text());
  if (!payload?.success) return false;

  const tokenData = payload.data || {};
  if (!tokenData.accessToken || !tokenData.refreshToken) return false;

  localStorage.setItem(STORAGE_KEYS.accessToken, tokenData.accessToken);
  localStorage.setItem(STORAGE_KEYS.refreshToken, tokenData.refreshToken);
  return true;
}

function buildApiUrl(endpoint) {
  const base = normalizeApiBase(state.settings.apiBase || '/api');
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${base}${path}`;
}

function normalizeApiBase(base) {
  if (!base) return '/api';
  return base.endsWith('/') ? base.slice(0, -1) : base;
}

function parseSteps(text) {
  const lines = (text || '').split('\n').map((line) => line.trim()).filter(Boolean);
  return lines.map((line, index) => {
    const [action, expectedResult, testData] = line.split('|').map((part) => (part || '').trim());
    return {
      stepOrder: index + 1,
      action: action || `Step ${index + 1}`,
      expectedResult: expectedResult || 'Expected result',
      testData: testData || ''
    };
  });
}

function renderSimpleList(node, items, emptyText) {
  if (!items || items.length === 0) {
    node.innerHTML = `<li>${escapeHtml(emptyText)}</li>`;
    return;
  }
  node.innerHTML = items.map((line) => `<li>${escapeHtml(line)}</li>`).join('');
}

function toast(message, type) {
  const container = document.getElementById('toast-container');
  const node = document.createElement('div');
  node.className = `toast ${type || 'info'}`;
  node.textContent = message;
  container.appendChild(node);
  setTimeout(() => node.remove(), 3500);
}

function notifyError(err, prefix) {
  const message = err?.message || String(err);
  toast(`${prefix}: ${message}`, 'error');
}

function numberOrDash(value) {
  return value == null ? '-' : String(value);
}

function formatDate(value) {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '-';
  return parsed.toLocaleString();
}

function parseJsonSafely(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (_err) {
    return null;
  }
}

function escapeHtml(value) {
  const str = String(value ?? '');
  return str
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}
