/**
 * Settings Page - Nasus
 * System settings with tabs for general, integrations, users, API keys, notifications, and execution config
 */

const { useState, useEffect, useRef, useCallback } = React;

// ============================================
// 3D Particle Background Component
// ============================================
const ParticleBackground = () => {
  const canvasRef = useRef(null);
  const animationRef = useRef(null);
  const particlesRef = useRef([]);
  const mouseRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let width = canvas.width = window.innerWidth;
    let height = canvas.height = window.innerHeight;

    // Particle configuration
    const config = {
      count: 80,
      color: '#00d4ff',
      secondaryColor: '#7c3aed',
      size: { min: 1, max: 3 },
      speed: { min: 0.2, max: 0.8 },
      opacity: { min: 0.3, max: 0.8 },
      connectionDistance: 150,
      connectionOpacity: 0.15,
      mouseRadius: 200,
      mouseForce: 0.02
    };

    // Initialize particles
    const initParticles = () => {
      particlesRef.current = [];
      for (let i = 0; i < config.count; i++) {
        particlesRef.current.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * config.speed.max,
          vy: (Math.random() - 0.5) * config.speed.max,
          size: Math.random() * (config.size.max - config.size.min) + config.size.min,
          opacity: Math.random() * (config.opacity.max - config.opacity.min) + config.opacity.min,
          color: Math.random() > 0.5 ? config.color : config.secondaryColor
        });
      }
    };

    // Draw particles and connections
    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      const particles = particlesRef.current;

      // Draw connections
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const distance = Math.sqrt(dx * dx + dy * dy);

          if (distance < config.connectionDistance) {
            const opacity = (1 - distance / config.connectionDistance) * config.connectionOpacity;
            ctx.beginPath();
            ctx.strokeStyle = `rgba(0, 212, 255, ${opacity})`;
            ctx.lineWidth = 1;
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.stroke();
          }
        }
      }

      // Draw particles
      particles.forEach(particle => {
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
        ctx.fillStyle = particle.color;
        ctx.globalAlpha = particle.opacity;
        ctx.fill();
        ctx.globalAlpha = 1;

        // Update position
        particle.x += particle.vx;
        particle.y += particle.vy;

        // Mouse interaction
        const mouseDx = mouseRef.current.x - particle.x;
        const mouseDy = mouseRef.current.y - particle.y;
        const mouseDistance = Math.sqrt(mouseDx * mouseDx + mouseDy * mouseDy);

        if (mouseDistance < config.mouseRadius) {
          const force = (config.mouseRadius - mouseDistance) / config.mouseRadius;
          particle.vx -= (mouseDx / mouseDistance) * force * config.mouseForce;
          particle.vy -= (mouseDy / mouseDistance) * force * config.mouseForce;
        }

        // Boundary check
        if (particle.x < 0 || particle.x > width) particle.vx *= -1;
        if (particle.y < 0 || particle.y > height) particle.vy *= -1;

        // Keep in bounds
        particle.x = Math.max(0, Math.min(width, particle.x));
        particle.y = Math.max(0, Math.min(height, particle.y));

        // Speed limit
        const speed = Math.sqrt(particle.vx * particle.vx + particle.vy * particle.vy);
        if (speed > config.speed.max) {
          particle.vx = (particle.vx / speed) * config.speed.max;
          particle.vy = (particle.vy / speed) * config.speed.max;
        }
      });

      animationRef.current = requestAnimationFrame(draw);
    };

    // Handle mouse move
    const handleMouseMove = (e) => {
      mouseRef.current = { x: e.clientX, y: e.clientY };
    };

    // Handle resize
    const handleResize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };

    initParticles();
    draw();

    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    window.addEventListener('resize', handleResize, { passive: true });

    return () => {
      cancelAnimationFrame(animationRef.current);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="particle-canvas"
      style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 0 }}
    />
  );
};

// ============================================
// Sidebar Navigation Component
// ============================================
const Sidebar = ({ activePage }) => {
  const navItems = [
    { id: 'index', label: '仪表盘', icon: 'LayoutDashboard', href: 'index.html' },
    { id: 'us-management', label: 'US 需求管理', icon: 'FileText', href: 'us-management.html', badge: '12' },
    { id: 'test-cases', label: '测试用例', icon: 'CheckSquare', href: 'test-cases.html', badge: '156' },
    { id: 'script-studio', label: '脚本工作室', icon: 'Code2', href: 'script-studio.html' },
    { id: 'execution-hub', label: '执行中心', icon: 'PlayCircle', href: 'execution-hub.html' },
    { id: 'reports', label: '报告中心', icon: 'BarChart3', href: 'reports.html' },
    { id: 'settings', label: '系统设置', icon: 'Settings', href: 'settings.html' }
  ];

  useEffect(() => {
    lucide.createIcons();
  }, []);

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <span className="sidebar-logo-text">Nasus</span>
      </div>
      <nav className="sidebar-nav">
        <ul className="sidebar-nav-list">
          {navItems.map(item => (
            <li key={item.id}>
              <a
                href={item.href}
                className={`sidebar-nav-item ${activePage === item.id ? 'active' : ''}`}
              >
                <i data-lucide={item.icon}></i>
                <span>{item.label}</span>
                {item.badge && (
                  <span className="ml-auto badge badge-cyan">{item.badge}</span>
                )}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="sidebar-user-avatar">AD</div>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name">Admin User</div>
            <div className="sidebar-user-role">系统管理员</div>
          </div>
        </div>
      </div>
    </aside>
  );
};

// ============================================
// Toggle Switch Component
// ============================================
const ToggleSwitch = ({ checked, onChange, disabled = false }) => (
  <div
    className={`toggle-switch ${checked ? 'active' : ''}`}
    onClick={() => !disabled && onChange(!checked)}
    style={{ opacity: disabled ? 0.5 : 1, cursor: disabled ? 'not-allowed' : 'pointer' }}
  />
);

// ============================================
// Form Input Component
// ============================================
const FormInput = ({ label, type = 'text', value, onChange, placeholder, disabled = false }) => (
  <div className="form-group">
    <label>{label}</label>
    <input
      type={type}
      className="form-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
    />
  </div>
);

// ============================================
// Form Select Component
// ============================================
const FormSelect = ({ label, value, onChange, options, disabled = false }) => (
  <div className="form-group">
    <label>{label}</label>
    <select
      className="form-select"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      {options.map(opt => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  </div>
);

// ============================================
// General Settings Tab
// ============================================
const GeneralSettingsTab = () => {
  const [settings, setSettings] = useState({
    platformName: 'Nasus',
    theme: 'dark',
    language: 'zh-CN',
    timezone: 'Asia/Shanghai',
    dateFormat: 'YYYY-MM-DD',
    autoSave: true
  });
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const themes = [
    { value: 'dark', label: '深色模式' },
    { value: 'light', label: '浅色模式' },
    { value: 'auto', label: '自动切换' }
  ];

  const languages = [
    { value: 'zh-CN', label: '简体中文' },
    { value: 'en-US', label: 'English' },
    { value: 'ja-JP', label: '日本語' }
  ];

  const timezones = [
    { value: 'Asia/Shanghai', label: 'Asia/Shanghai (UTC+8)' },
    { value: 'Asia/Tokyo', label: 'Asia/Tokyo (UTC+9)' },
    { value: 'America/New_York', label: 'America/New_York (UTC-5)' },
    { value: 'Europe/London', label: 'Europe/London (UTC+0)' }
  ];

  const dateFormats = [
    { value: 'YYYY-MM-DD', label: 'YYYY-MM-DD' },
    { value: 'DD/MM/YYYY', label: 'DD/MM/YYYY' },
    { value: 'MM/DD/YYYY', label: 'MM/DD/YYYY' },
    { value: 'YYYY年MM月DD日', label: 'YYYY年MM月DD日' }
  ];

  return (
    <div className="settings-section">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Platform Settings */}
        <div className="glass-card p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <i data-lucide="monitor" className="w-5 h-5 text-cyan-400"></i>
            平台设置
          </h3>
          
          <FormInput
            label="平台名称"
            value={settings.platformName}
            onChange={(v) => setSettings({...settings, platformName: v})}
          />
          
          <div className="form-group">
            <label>平台 Logo</label>
            <div className="logo-upload">
              <i data-lucide="upload" className="w-6 h-6 text-gray-400"></i>
              <span className="text-sm text-gray-400">点击上传</span>
            </div>
          </div>

          <div className="form-group">
            <label>主题模式</label>
            <div className="flex gap-3">
              {themes.map(t => (
                <div
                  key={t.value}
                  className={`theme-option ${settings.theme === t.value ? 'active' : ''}`}
                  onClick={() => setSettings({...settings, theme: t.value})}
                  style={{
                    background: t.value === 'dark' ? '#1a1a25' : t.value === 'light' ? '#f5f5f5' : 'linear-gradient(135deg, #1a1a25 50%, #f5f5f5 50%)'
                  }}
                  title={t.label}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Regional Settings */}
        <div className="glass-card p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <i data-lucide="globe" className="w-5 h-5 text-cyan-400"></i>
            区域设置
          </h3>
          
          <FormSelect
            label="界面语言"
            value={settings.language}
            onChange={(v) => setSettings({...settings, language: v})}
            options={languages}
          />
          
          <FormSelect
            label="时区"
            value={settings.timezone}
            onChange={(v) => setSettings({...settings, timezone: v})}
            options={timezones}
          />
          
          <FormSelect
            label="日期格式"
            value={settings.dateFormat}
            onChange={(v) => setSettings({...settings, dateFormat: v})}
            options={dateFormats}
          />

          <div className="form-group">
            <div className="flex items-center justify-between">
              <label>自动保存</label>
              <ToggleSwitch
                checked={settings.autoSave}
                onChange={(v) => setSettings({...settings, autoSave: v})}
              />
            </div>
            <p className="text-xs text-gray-500 mt-1">编辑内容时自动保存到草稿</p>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-end gap-4 mt-6">
        {saved && (
          <div className="save-indicator">
            <i data-lucide="check" className="w-4 h-4"></i>
            保存成功
          </div>
        )}
        <button className="btn btn-secondary" onClick={() => window.location.reload()}>
          <i data-lucide="rotate-ccw" className="w-4 h-4"></i>
          重置
        </button>
        <button className="btn btn-primary" onClick={handleSave}>
          <i data-lucide="save" className="w-4 h-4"></i>
          保存设置
        </button>
      </div>
    </div>
  );
};

// ============================================
// Integration Settings Tab
// ============================================
const IntegrationSettingsTab = () => {
  const [integrations, setIntegrations] = useState({
    jira: { enabled: true, url: 'https://jira.company.com', token: '••••••••••••', project: 'TEST' },
    github: { enabled: false, url: '', token: '', repo: '' },
    slack: { enabled: true, webhook: 'https://hooks.slack.com/services/...', channel: '#test-alerts' },
    smtp: { enabled: false, host: '', port: '587', user: '', pass: '' }
  });

  const [testingConnection, setTestingConnection] = useState(null);
  const [connectionStatus, setConnectionStatus] = useState({});

  const testConnection = (type) => {
    setTestingConnection(type);
    setTimeout(() => {
      setConnectionStatus({ ...connectionStatus, [type]: Math.random() > 0.3 ? 'success' : 'error' });
      setTestingConnection(null);
    }, 2000);
  };

  const IntegrationCard = ({ title, icon, color, type, children }) => (
    <div className="integration-card">
      <div className="integration-header">
        <div className="integration-title">
          <div className="integration-icon" style={{ background: `${color}20`, color }}>
            <i data-lucide={icon} className="w-5 h-5"></i>
          </div>
          <div>
            <h4 className="font-semibold">{title}</h4>
            <span className={`text-xs ${integrations[type].enabled ? 'text-green-400' : 'text-gray-500'}`}>
              {integrations[type].enabled ? '已启用' : '已禁用'}
            </span>
          </div>
        </div>
        <ToggleSwitch
          checked={integrations[type].enabled}
          onChange={(v) => setIntegrations({...integrations, [type]: {...integrations[type], enabled: v}})}
        />
      </div>
      <div style={{ opacity: integrations[type].enabled ? 1 : 0.5, pointerEvents: integrations[type].enabled ? 'auto' : 'none' }}>
        {children}
      </div>
    </div>
  );

  return (
    <div className="settings-section">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* JIRA Integration */}
        <IntegrationCard title="JIRA" icon="trello" color="#0052CC" type="jira">
          <div className="space-y-4">
            <FormInput
              label="JIRA Server URL"
              value={integrations.jira.url}
              onChange={(v) => setIntegrations({...integrations, jira: {...integrations.jira, url: v}})}
              placeholder="https://jira.company.com"
            />
            <FormInput
              label="API Token"
              type="password"
              value={integrations.jira.token}
              onChange={(v) => setIntegrations({...integrations, jira: {...integrations.jira, token: v}})}
              placeholder="输入 API Token"
            />
            <FormInput
              label="项目 Key"
              value={integrations.jira.project}
              onChange={(v) => setIntegrations({...integrations, jira: {...integrations.jira, project: v}})}
              placeholder="例如: TEST"
            />
            <div className="flex items-center gap-3">
              <button
                className={`test-connection-btn ${testingConnection === 'jira' ? 'testing' : ''}`}
                onClick={() => testConnection('jira')}
              >
                {testingConnection === 'jira' ? (
                  <><div className="spinner spinner-sm"></div>测试中...</>
                ) : (
                  <><i data-lucide="plug" className="w-4 h-4"></i>测试连接</>
                )}
              </button>
              {connectionStatus.jira && (
                <span className={`connection-status ${connectionStatus.jira}`}>
                  {connectionStatus.jira === 'success' ? (
                    <><i data-lucide="check-circle" className="w-4 h-4"></i>连接成功</>
                  ) : (
                    <><i data-lucide="x-circle" className="w-4 h-4"></i>连接失败</>
                  )}
                </span>
              )}
            </div>
          </div>
        </IntegrationCard>

        {/* GitHub Integration */}
        <IntegrationCard title="GitHub / GitLab" icon="github" color="#333" type="github">
          <div className="space-y-4">
            <FormInput
              label="仓库 URL"
              value={integrations.github.url}
              onChange={(v) => setIntegrations({...integrations, github: {...integrations.github, url: v}})}
              placeholder="https://github.com/company/repo"
            />
            <FormInput
              label="Access Token"
              type="password"
              value={integrations.github.token}
              onChange={(v) => setIntegrations({...integrations, github: {...integrations.github, token: v}})}
              placeholder="输入 Access Token"
            />
            <FormInput
              label="默认分支"
              value={integrations.github.repo}
              onChange={(v) => setIntegrations({...integrations, github: {...integrations.github, repo: v}})}
              placeholder="main"
            />
            <div className="flex items-center gap-3">
              <button
                className={`test-connection-btn ${testingConnection === 'github' ? 'testing' : ''}`}
                onClick={() => testConnection('github')}
              >
                {testingConnection === 'github' ? (
                  <><div className="spinner spinner-sm"></div>测试中...</>
                ) : (
                  <><i data-lucide="plug" className="w-4 h-4"></i>测试连接</>
                )}
              </button>
              {connectionStatus.github && (
                <span className={`connection-status ${connectionStatus.github}`}>
                  {connectionStatus.github === 'success' ? '连接成功' : '连接失败'}
                </span>
              )}
            </div>
          </div>
        </IntegrationCard>

        {/* Slack Integration */}
        <IntegrationCard title="Slack / 钉钉" icon="message-square" color="#4A154B" type="slack">
          <div className="space-y-4">
            <FormInput
              label="Webhook URL"
              value={integrations.slack.webhook}
              onChange={(v) => setIntegrations({...integrations, slack: {...integrations.slack, webhook: v}})}
              placeholder="https://hooks.slack.com/services/..."
            />
            <FormInput
              label="通知频道"
              value={integrations.slack.channel}
              onChange={(v) => setIntegrations({...integrations, slack: {...integrations.slack, channel: v}})}
              placeholder="#test-alerts"
            />
            <div className="flex items-center gap-3">
              <button
                className={`test-connection-btn ${testingConnection === 'slack' ? 'testing' : ''}`}
                onClick={() => testConnection('slack')}
              >
                {testingConnection === 'slack' ? (
                  <><div className="spinner spinner-sm"></div>测试中...</>
                ) : (
                  <><i data-lucide="send" className="w-4 h-4"></i>发送测试消息</>
                )}
              </button>
              {connectionStatus.slack && (
                <span className={`connection-status ${connectionStatus.slack}`}>
                  {connectionStatus.slack === 'success' ? '发送成功' : '发送失败'}
                </span>
              )}
            </div>
          </div>
        </IntegrationCard>

        {/* SMTP Configuration */}
        <IntegrationCard title="邮件 SMTP" icon="mail" color="#EA4335" type="smtp">
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <FormInput
                label="SMTP 服务器"
                value={integrations.smtp.host}
                onChange={(v) => setIntegrations({...integrations, smtp: {...integrations.smtp, host: v}})}
                placeholder="smtp.company.com"
              />
              <FormInput
                label="端口"
                value={integrations.smtp.port}
                onChange={(v) => setIntegrations({...integrations, smtp: {...integrations.smtp, port: v}})}
                placeholder="587"
              />
            </div>
            <FormInput
              label="用户名"
              value={integrations.smtp.user}
              onChange={(v) => setIntegrations({...integrations, smtp: {...integrations.smtp, user: v}})}
              placeholder="user@company.com"
            />
            <FormInput
              label="密码"
              type="password"
              value={integrations.smtp.pass}
              onChange={(v) => setIntegrations({...integrations, smtp: {...integrations.smtp, pass: v}})}
              placeholder="输入密码"
            />
            <div className="flex items-center gap-3">
              <button
                className={`test-connection-btn ${testingConnection === 'smtp' ? 'testing' : ''}`}
                onClick={() => testConnection('smtp')}
              >
                {testingConnection === 'smtp' ? (
                  <><div className="spinner spinner-sm"></div>测试中...</>
                ) : (
                  <><i data-lucide="mail-check" className="w-4 h-4"></i>发送测试邮件</>
                )}
              </button>
              {connectionStatus.smtp && (
                <span className={`connection-status ${connectionStatus.smtp}`}>
                  {connectionStatus.smtp === 'success' ? '发送成功' : '发送失败'}
                </span>
              )}
            </div>
          </div>
        </IntegrationCard>
      </div>
    </div>
  );
};

// ============================================
// User Management Tab
// ============================================
const UserManagementTab = () => {
  const [users, setUsers] = useState([
    { id: 1, name: 'Admin User', email: 'admin@autotest.ai', role: 'admin', status: 'active', lastLogin: '2024-01-15 09:30' },
    { id: 2, name: '张三', email: 'zhangsan@company.com', role: 'member', status: 'active', lastLogin: '2024-01-15 08:45' },
    { id: 3, name: '李四', email: 'lisi@company.com', role: 'member', status: 'inactive', lastLogin: '2024-01-10 16:20' },
    { id: 4, name: '王五', email: 'wangwu@company.com', role: 'viewer', status: 'active', lastLogin: '2024-01-14 14:15' },
    { id: 5, name: '赵六', email: 'zhaoliu@company.com', role: 'member', status: 'pending', lastLogin: '-' }
  ]);

  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');

  const roles = {
    admin: { label: '管理员', color: 'purple' },
    member: { label: '成员', color: 'cyan' },
    viewer: { label: '访客', color: 'gray' }
  };

  const statuses = {
    active: { label: '活跃', class: 'badge-green' },
    inactive: { label: '未激活', class: 'badge-gray' },
    pending: { label: '待邀请', class: 'badge-yellow' }
  };

  const handleInvite = () => {
    if (inviteEmail) {
      setUsers([...users, {
        id: users.length + 1,
        name: inviteEmail.split('@')[0],
        email: inviteEmail,
        role: inviteRole,
        status: 'pending',
        lastLogin: '-'
      }]);
      setShowInviteModal(false);
      setInviteEmail('');
    }
  };

  const handleDelete = (id) => {
    setUsers(users.filter(u => u.id !== id));
  };

  return (
    <div className="settings-section">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="text-gray-400">共 {users.length} 位用户</span>
        </div>
        <button className="btn btn-primary" onClick={() => setShowInviteModal(true)}>
          <i data-lucide="user-plus" className="w-4 h-4"></i>
          邀请用户
        </button>
      </div>

      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>用户</th>
              <th>邮箱</th>
              <th>角色</th>
              <th>状态</th>
              <th>最后登录</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map(user => (
              <tr key={user.id}>
                <td>
                  <div className="flex items-center gap-3">
                    <div className="user-avatar-small">{user.name.charAt(0).toUpperCase()}</div>
                    <span className="font-medium">{user.name}</span>
                  </div>
                </td>
                <td className="text-gray-400">{user.email}</td>
                <td>
                  <span className={`badge badge-${roles[user.role].color}`}>
                    {roles[user.role].label}
                  </span>
                </td>
                <td>
                  <span className={`badge ${statuses[user.status].class}`}>
                    {statuses[user.status].label}
                  </span>
                </td>
                <td className="text-gray-400">{user.lastLogin}</td>
                <td>
                  <div className="flex items-center gap-2">
                    <button className="btn btn-ghost btn-sm" title="编辑">
                      <i data-lucide="edit-2" className="w-4 h-4"></i>
                    </button>
                    <button className="btn btn-ghost btn-sm" title="重置密码">
                      <i data-lucide="key" className="w-4 h-4"></i>
                    </button>
                    {user.role !== 'admin' && (
                      <button className="btn btn-ghost btn-sm text-red-400" onClick={() => handleDelete(user.id)} title="删除">
                        <i data-lucide="trash-2" className="w-4 h-4"></i>
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="modal-overlay active" onClick={() => setShowInviteModal(false)}>
          <div className="modal" style={{ width: '400px' }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">邀请用户</h3>
              <button className="modal-close" onClick={() => setShowInviteModal(false)}>
                <i data-lucide="x" className="w-5 h-5"></i>
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>邮箱地址</label>
                <input
                  type="email"
                  className="form-input"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="user@company.com"
                />
              </div>
              <div className="form-group">
                <label>角色</label>
                <select
                  className="form-select"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                >
                  <option value="member">成员 - 可创建和编辑测试</option>
                  <option value="viewer">访客 - 仅可查看</option>
                  <option value="admin">管理员 - 完全访问权限</option>
                </select>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowInviteModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleInvite}>发送邀请</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ============================================
// API Keys Tab
// ============================================
const APIKeysTab = () => {
  const [keys, setKeys] = useState([
    { id: 1, name: 'CI/CD Pipeline', key: 'atk_live_xxxxxxxxxxxx', created: '2024-01-01', lastUsed: '2024-01-15', permissions: ['read', 'execute'] },
    { id: 2, name: 'Development', key: 'atk_test_yyyyyyyyyyyy', created: '2024-01-05', lastUsed: '2024-01-14', permissions: ['read', 'write', 'execute'] }
  ]);

  const [showNewKeyModal, setShowNewKeyModal] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyPermissions, setNewKeyPermissions] = useState(['read']);
  const [newlyCreatedKey, setNewlyCreatedKey] = useState(null);

  const handleCreateKey = () => {
    const newKey = {
      id: keys.length + 1,
      name: newKeyName,
      key: 'atk_live_' + Math.random().toString(36).substring(2, 14),
      created: new Date().toISOString().split('T')[0],
      lastUsed: '-',
      permissions: newKeyPermissions
    };
    setKeys([...keys, newKey]);
    setNewlyCreatedKey(newKey);
    setShowNewKeyModal(false);
    setNewKeyName('');
    setNewKeyPermissions(['read']);
  };

  const handleRevoke = (id) => {
    setKeys(keys.filter(k => k.id !== id));
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <div className="settings-section">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold">API 密钥</h3>
          <p className="text-sm text-gray-400">管理用于程序化访问的 API 密钥</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowNewKeyModal(true)}>
          <i data-lucide="plus" className="w-4 h-4"></i>
          生成新密钥
        </button>
      </div>

      <div className="space-y-4">
        {keys.map(apiKey => (
          <div key={apiKey.id} className="glass-card p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                  <i data-lucide="key" className="w-5 h-5 text-cyan-400"></i>
                </div>
                <div>
                  <h4 className="font-medium">{apiKey.name}</h4>
                  <div className="flex items-center gap-2 mt-1">
                    <code className="api-key-masked text-sm text-gray-400 bg-gray-800/50 px-2 py-0.5 rounded">
                      {apiKey.key.substring(0, 12)}••••••••••••
                    </code>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => copyToClipboard(apiKey.key)}
                      title="复制"
                    >
                      <i data-lucide="copy" className="w-4 h-4"></i>
                    </button>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right text-sm">
                  <div className="text-gray-400">创建于: {apiKey.created}</div>
                  <div className="text-gray-400">最后使用: {apiKey.lastUsed}</div>
                </div>
                <div className="flex gap-1">
                  {apiKey.permissions.map(p => (
                    <span key={p} className="badge badge-cyan text-xs uppercase">{p}</span>
                  ))}
                </div>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={() => handleRevoke(apiKey.id)}
                >
                  <i data-lucide="trash-2" className="w-4 h-4"></i>
                  撤销
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* New Key Modal */}
      {showNewKeyModal && (
        <div className="modal-overlay active" onClick={() => setShowNewKeyModal(false)}>
          <div className="modal" style={{ width: '450px' }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">生成新 API 密钥</h3>
              <button className="modal-close" onClick={() => setShowNewKeyModal(false)}>
                <i data-lucide="x" className="w-5 h-5"></i>
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>密钥名称</label>
                <input
                  type="text"
                  className="form-input"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="例如: Production CI"
                />
              </div>
              <div className="form-group">
                <label>权限</label>
                <div className="checkbox-group">
                  {['read', 'write', 'execute'].map(perm => (
                    <label key={perm} className="checkbox-item">
                      <input
                        type="checkbox"
                        checked={newKeyPermissions.includes(perm)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setNewKeyPermissions([...newKeyPermissions, perm]);
                          } else {
                            setNewKeyPermissions(newKeyPermissions.filter(p => p !== perm));
                          }
                        }}
                      />
                      <span className="capitalize">{perm === 'read' ? '读取' : perm === 'write' ? '写入' : '执行'}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowNewKeyModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleCreateKey}>生成密钥</button>
            </div>
          </div>
        </div>
      )}

      {/* Show Newly Created Key */}
      {newlyCreatedKey && (
        <div className="modal-overlay active" onClick={() => setNewlyCreatedKey(null)}>
          <div className="modal" style={{ width: '500px' }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title flex items-center gap-2">
                <i data-lucide="check-circle" className="w-5 h-5 text-green-400"></i>
                API 密钥已生成
              </h3>
            </div>
            <div className="modal-body">
              <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 mb-4">
                <div className="flex items-start gap-3">
                  <i data-lucide="alert-triangle" className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5"></i>
                  <p className="text-sm text-yellow-200">
                    请立即复制并安全保存此密钥。出于安全考虑，您将无法再次查看完整的密钥。
                  </p>
                </div>
              </div>
              <div className="form-group">
                <label>您的 API 密钥</label>
                <div className="flex gap-2">
                  <code className="form-input font-mono text-cyan-400">{newlyCreatedKey.key}</code>
                  <button
                    className="btn btn-secondary"
                    onClick={() => copyToClipboard(newlyCreatedKey.key)}
                  >
                    <i data-lucide="copy" className="w-4 h-4"></i>
                  </button>
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-primary" onClick={() => setNewlyCreatedKey(null)}>我已保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ============================================
// Notification Settings Tab
// ============================================
const NotificationSettingsTab = () => {
  const [settings, setSettings] = useState({
    emailEnabled: true,
    slackEnabled: true,
    slackWebhook: '',
    events: {
      executionComplete: true,
      executionFailed: true,
      dailySummary: false,
      weeklyReport: true
    }
  });

  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="settings-section">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Email Notifications */}
        <div className="glass-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <i data-lucide="mail" className="w-5 h-5 text-cyan-400"></i>
              邮件通知
            </h3>
            <ToggleSwitch
              checked={settings.emailEnabled}
              onChange={(v) => setSettings({...settings, emailEnabled: v})}
            />
          </div>
          <p className="text-sm text-gray-400 mb-4">启用后，系统将发送邮件通知到您的注册邮箱</p>
          
          <div style={{ opacity: settings.emailEnabled ? 1 : 0.5 }}>
            <div className="form-group">
              <label>默认收件人</label>
              <input type="text" className="form-input" value="admin@autotest.ai" disabled />
            </div>
            <div className="form-group">
              <label>附加收件人 (用逗号分隔)</label>
              <input type="text" className="form-input" placeholder="user1@company.com, user2@company.com" />
            </div>
          </div>
        </div>

        {/* Slack Notifications */}
        <div className="glass-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <i data-lucide="message-square" className="w-5 h-5 text-cyan-400"></i>
              Slack 通知
            </h3>
            <ToggleSwitch
              checked={settings.slackEnabled}
              onChange={(v) => setSettings({...settings, slackEnabled: v})}
            />
          </div>
          
          <div style={{ opacity: settings.slackEnabled ? 1 : 0.5 }}>
            <div className="form-group">
              <label>Webhook URL</label>
              <input
                type="text"
                className="form-input"
                value={settings.slackWebhook}
                onChange={(e) => setSettings({...settings, slackWebhook: e.target.value})}
              />
            </div>
            <div className="form-group">
              <label>通知频道</label>
              <input type="text" className="form-input" value="#test-alerts" />
            </div>
          </div>
        </div>

        {/* Event Triggers */}
        <div className="glass-card p-6 lg:col-span-2">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <i data-lucide="bell" className="w-5 h-5 text-cyan-400"></i>
            通知事件
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <label className="checkbox-item p-3 rounded-lg bg-gray-800/30 hover:bg-gray-800/50 transition-colors">
              <input
                type="checkbox"
                checked={settings.events.executionComplete}
                onChange={(e) => setSettings({
                  ...settings,
                  events: { ...settings.events, executionComplete: e.target.checked }
                })}
              />
              <div>
                <div className="font-medium">执行完成</div>
                <div className="text-sm text-gray-400">测试执行完成后发送通知</div>
              </div>
            </label>
            <label className="checkbox-item p-3 rounded-lg bg-gray-800/30 hover:bg-gray-800/50 transition-colors">
              <input
                type="checkbox"
                checked={settings.events.executionFailed}
                onChange={(e) => setSettings({
                  ...settings,
                  events: { ...settings.events, executionFailed: e.target.checked }
                })}
              />
              <div>
                <div className="font-medium">执行失败</div>
                <div className="text-sm text-gray-400">测试执行失败时发送通知</div>
              </div>
            </label>
            <label className="checkbox-item p-3 rounded-lg bg-gray-800/30 hover:bg-gray-800/50 transition-colors">
              <input
                type="checkbox"
                checked={settings.events.dailySummary}
                onChange={(e) => setSettings({
                  ...settings,
                  events: { ...settings.events, dailySummary: e.target.checked }
                })}
              />
              <div>
                <div className="font-medium">每日摘要</div>
                <div className="text-sm text-gray-400">每天发送执行摘要</div>
              </div>
            </label>
            <label className="checkbox-item p-3 rounded-lg bg-gray-800/30 hover:bg-gray-800/50 transition-colors">
              <input
                type="checkbox"
                checked={settings.events.weeklyReport}
                onChange={(e) => setSettings({
                  ...settings,
                  events: { ...settings.events, weeklyReport: e.target.checked }
                })}
              />
              <div>
                <div className="font-medium">周报</div>
                <div className="text-sm text-gray-400">每周一发送上周执行报告</div>
              </div>
            </label>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-end gap-4 mt-6">
        {saved && (
          <div className="save-indicator">
            <i data-lucide="check" className="w-4 h-4"></i>
            保存成功
          </div>
        )}
        <button className="btn btn-primary" onClick={handleSave}>
          <i data-lucide="save" className="w-4 h-4"></i>
          保存设置
        </button>
      </div>
    </div>
  );
};

// ============================================
// Execution Config Tab
// ============================================
const ExecutionConfigTab = () => {
  const [config, setConfig] = useState({
    browser: 'chrome',
    headless: true,
    parallelCount: 4,
    timeout: 30,
    screenshotPolicy: 'on-failure',
    videoRecording: true,
    retryCount: 2
  });

  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const browsers = [
    { value: 'chrome', label: 'Chrome', icon: 'chrome' },
    { value: 'firefox', label: 'Firefox', icon: 'firefox' },
    { value: 'safari', label: 'Safari', icon: 'compass' },
    { value: 'edge', label: 'Edge', icon: 'layout' }
  ];

  const screenshotPolicies = [
    { value: 'always', label: '始终截图' },
    { value: 'on-failure', label: '仅失败时' },
    { value: 'never', label: '从不截图' }
  ];

  return (
    <div className="settings-section">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Browser Settings */}
        <div className="glass-card p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <i data-lucide="monitor" className="w-5 h-5 text-cyan-400"></i>
            浏览器设置
          </h3>
          
          <div className="form-group">
            <label>默认浏览器</label>
            <div className="grid grid-cols-4 gap-3">
              {browsers.map(b => (
                <button
                  key={b.value}
                  className={`p-3 rounded-lg border transition-all ${
                    config.browser === b.value
                      ? 'border-cyan-500 bg-cyan-500/10'
                      : 'border-gray-700 hover:border-gray-600'
                  }`}
                  onClick={() => setConfig({...config, browser: b.value})}
                >
                  <i data-lucide={b.icon} className="w-6 h-6 mx-auto mb-1"></i>
                  <span className="text-xs">{b.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="form-group">
            <div className="flex items-center justify-between">
              <label>无头模式</label>
              <ToggleSwitch
                checked={config.headless}
                onChange={(v) => setConfig({...config, headless: v})}
              />
            </div>
            <p className="text-xs text-gray-500 mt-1">在后台运行浏览器，不显示界面</p>
          </div>
        </div>

        {/* Performance Settings */}
        <div className="glass-card p-6">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <i data-lucide="zap" className="w-5 h-5 text-cyan-400"></i>
            性能设置
          </h3>
          
          <div className="form-group">
            <label>并行执行数</label>
            <div className="slider-container">
              <input
                type="range"
                className="slider"
                min="1"
                max="10"
                value={config.parallelCount}
                onChange={(e) => setConfig({...config, parallelCount: parseInt(e.target.value)})}
              />
              <span className="slider-value">{config.parallelCount}</span>
            </div>
          </div>

          <div className="form-group">
            <label>默认超时时间 (秒)</label>
            <div className="slider-container">
              <input
                type="range"
                className="slider"
                min="5"
                max="120"
                step="5"
                value={config.timeout}
                onChange={(e) => setConfig({...config, timeout: parseInt(e.target.value)})}
              />
              <span className="slider-value">{config.timeout}s</span>
            </div>
          </div>

          <div className="form-group">
            <label>重试次数</label>
            <div className="slider-container">
              <input
                type="range"
                className="slider"
                min="0"
                max="5"
                value={config.retryCount}
                onChange={(e) => setConfig({...config, retryCount: parseInt(e.target.value)})}
              />
              <span className="slider-value">{config.retryCount}</span>
            </div>
            <p className="text-xs text-gray-500 mt-1">测试失败时的自动重试次数</p>
          </div>
        </div>

        {/* Screenshot & Video */}
        <div className="glass-card p-6 lg:col-span-2">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <i data-lucide="camera" className="w-5 h-5 text-cyan-400"></i>
            截图与录屏
          </h3>
          
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div>
              <FormSelect
                label="截图策略"
                value={config.screenshotPolicy}
                onChange={(v) => setConfig({...config, screenshotPolicy: v})}
                options={screenshotPolicies}
              />
            </div>
            <div>
              <div className="form-group">
                <div className="flex items-center justify-between">
                  <label>视频录制</label>
                  <ToggleSwitch
                    checked={config.videoRecording}
                    onChange={(v) => setConfig({...config, videoRecording: v})}
                  />
                </div>
                <p className="text-xs text-gray-500 mt-1">录制测试执行过程的视频</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-end gap-4 mt-6">
        {saved && (
          <div className="save-indicator">
            <i data-lucide="check" className="w-4 h-4"></i>
            保存成功
          </div>
        )}
        <button className="btn btn-secondary" onClick={() => window.location.reload()}>
          <i data-lucide="rotate-ccw" className="w-4 h-4"></i>
          重置
        </button>
        <button className="btn btn-primary" onClick={handleSave}>
          <i data-lucide="save" className="w-4 h-4"></i>
          保存设置
        </button>
      </div>
    </div>
  );
};

// ============================================
// Main Settings Page Component
// ============================================
const SettingsPage = () => {
  const [activeTab, setActiveTab] = useState('general');

  const tabs = [
    { id: 'general', label: '通用设置', icon: 'settings' },
    { id: 'integrations', label: '集成配置', icon: 'plug' },
    { id: 'users', label: '用户管理', icon: 'users' },
    { id: 'apikeys', label: 'API 密钥', icon: 'key' },
    { id: 'notifications', label: '通知设置', icon: 'bell' },
    { id: 'execution', label: '执行配置', icon: 'play-circle' }
  ];

  useEffect(() => {
    lucide.createIcons();
  }, [activeTab]);

  const renderTabContent = () => {
    switch (activeTab) {
      case 'general':
        return <GeneralSettingsTab />;
      case 'integrations':
        return <IntegrationSettingsTab />;
      case 'users':
        return <UserManagementTab />;
      case 'apikeys':
        return <APIKeysTab />;
      case 'notifications':
        return <NotificationSettingsTab />;
      case 'execution':
        return <ExecutionConfigTab />;
      default:
        return <GeneralSettingsTab />;
    }
  };

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <ParticleBackground />
      <div className="grid-background"></div>
      
      <Sidebar activePage="settings" />
      
      <main className="main-content" style={{ position: 'relative', zIndex: 1 }}>
        {/* Header */}
        <header className="main-header">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-semibold">系统设置</h1>
          </div>
          <div className="flex items-center gap-4">
            <button className="btn btn-ghost btn-icon">
              <i data-lucide="bell" className="w-5 h-5"></i>
            </button>
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-400 to-purple-500 flex items-center justify-center text-sm font-semibold">
              AD
            </div>
          </div>
        </header>

        {/* Main Body */}
        <div className="main-body">
          {/* Tabs */}
          <div className="tabs-scroll-container mb-6">
            <div className="flex border-b border-white/5">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  className={`settings-tab ${activeTab === tab.id ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <span className="flex items-center gap-2">
                    <i data-lucide={tab.icon} className="w-4 h-4"></i>
                    {tab.label}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Tab Content */}
          {renderTabContent()}
        </div>
      </main>
    </div>
  );
};

// Render the app
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<SettingsPage />);
