document.addEventListener('DOMContentLoaded', () => {
    const sidebarNav = document.getElementById('sidebar-nav');
    const homeLink = document.getElementById('home-link');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const chatMessages = document.getElementById('chat-messages');
    const chatContainer = document.getElementById('chat-container');
    const inputContainer = document.getElementById('input-container');
    const mainHeaderTitle = document.querySelector('.main-header-title');
    const panelTabsContainer = document.querySelector('.panel-tab-group');
    const panelHeaderTitle = document.querySelector('.panel-header h2');
    const panelContentContainer = document.getElementById('panel-content');

    const WORKSPACE_VIEWS = new Set([
        'projectOverview',
        'versionSpace',
        'versionCreate',
        'personalWorkspace',
        'knowledgeGallery',
        'knowledgeDetail',
        'runs',
        'runDetail',
        'governance',
        'approvalDetail',
        'releaseReadiness',
        'desktop'
    ]);

    const state = {
        currentViewId: 'welcome',
        currentUsId: 'US-123',
        currentRunId: 'RUN-9021',
        currentApprovalId: 'APR-442',
        currentObjectId: 'OBJ-CHECKOUT',
        currentVersionId: 'VER-2026Q2',
        currentProjectId: 'PRJ-PAYMENTS',
        isWaitingForAgent: false,
        panelTabs: {
            welcome: 'activity',
            build: 'projects',
            dashboard: 'alerts',
            documentation: 'topics',
            projectOverview: 'context',
            projectCreate: 'context',
            versionSpace: 'board',
            versionCreate: 'summary',
            personalWorkspace: 'assets',
            knowledgeGallery: 'graph',
            knowledgeDetail: 'context',
            runs: 'active',
            runDetail: 'evidence',
            governance: 'pending',
            approvalDetail: 'diff',
            releaseReadiness: 'blockers',
            desktop: 'queue'
        },
        projects: [
            {
                id: 'PRJ-PAYMENTS',
                name: 'Payment System',
                subtitle: 'Checkout, refunds, and promotion orchestration',
                baseline: 'Official System Image v1.4.2',
                versions: 2,
                modules: 45,
                tests: 1204,
                docs: 18,
                overallRisk: 'Elevated',
                progress: 74,
                activeVersion: '2026Q2 Release',
                nextAction: 'Resolve one failed run and one pending merge',
                sources: [
                    'Git · payment-system / checkout-ui',
                    'US Docs · PRD bundle and acceptance notes',
                    'UX Boards · checkout, refund, fallback states',
                    'Historical Assets · regression and flaky failure history'
                ]
            },
            {
                id: 'PRJ-IDENTITY',
                name: 'Identity Hub',
                subtitle: 'OAuth, session recovery, and profile sync',
                baseline: 'Official System Image v0.9.8',
                versions: 1,
                modules: 27,
                tests: 540,
                docs: 9,
                overallRisk: 'Stable',
                progress: 62,
                activeVersion: 'OAuth Hardening',
                nextAction: 'Complete performance lane for US-128',
                sources: [
                    'Git · auth-service / profile-api',
                    'US Docs · identity roadmap',
                    'UX Boards · sign-in fallback and recovery'
                ]
            }
        ],
        dashboard: {
            activeProjects: 2,
            activeVersions: 3,
            openUs: 12,
            blockedItems: 4,
            failedRuns: 2,
            pendingApprovals: 3,
            mergeConflicts: 2
        },
        buildDrafts: [
            {
                id: 'DR-SETUP-1',
                title: 'Payments Platform Migration',
                status: 'Awaiting Git repo binding',
                next: 'Connect checkout and payment-service repositories'
            },
            {
                id: 'DR-SETUP-2',
                title: 'Identity Recovery Upgrade',
                status: 'Waiting UX board import',
                next: 'Attach sign-in fallback flows and recovery states'
            }
        ],
        docs: [
            {
                id: 'DOC-START',
                title: 'Getting Started',
                copy: 'How to create a project, connect sources, and initialize the Official System Image.',
                category: 'Guide'
            },
            {
                id: 'DOC-BRANCHING',
                title: 'System Image & Branching',
                copy: 'Official baseline, version branch overlays, candidate promotion, and baseline write-back.',
                category: 'Concept'
            },
            {
                id: 'DOC-ASSET',
                title: 'Quality Asset Pack',
                copy: 'How scenarios, scope, plans, cases, automation, performance, and change docs work together.',
                category: 'Reference'
            }
        ],
        versionCreate: {
            usImported: 8,
            ownersAssigned: 5,
            baselineFork: 'Draft',
            targetDate: 'Apr 15',
            sourceBranch: 'main',
            targetBranch: 'release/2026Q2'
        },
        createProject: {
            repoCount: 2,
            usDocs: 6,
            uxBoards: 3,
            historicalPacks: 2,
            validation: 'Validated',
            import: 'Ready',
            systemImage: 'Ready to initialize'
        },
        versions: [
            {
                id: 'VER-2026Q2',
                name: '2026Q2 Release',
                status: 'Execution Phase',
                risk: 'High',
                progress: 74,
                pendingApprovals: 2,
                pendingMerge: 1,
                usCount: 8,
                branch: 'release/2026Q2',
                releaseWindow: 'Apr 15'
            },
            {
                id: 'VER-HOTFIX31',
                name: 'Hotfix 3.1',
                status: 'Reviewing',
                risk: 'Medium',
                progress: 82,
                pendingApprovals: 1,
                pendingMerge: 0,
                usCount: 2,
                branch: 'hotfix/3.1',
                releaseWindow: 'Mar 27'
            }
        ],
        usItems: {
            'US-123': {
                id: 'US-123',
                title: 'Payment flow update',
                owner: 'You',
                status: 'In Progress',
                risk: 'High',
                branch: 'feature/payment-flow-update',
                progress: 64,
                summary: 'Checkout flow update touching payment gateway fallback, promo recalculation, and receipt handoff.',
                impact: 'Checkout Module, Payment Gateway App, Order Summary',
                blockers: 1,
                revision: 3
            },
            'US-128': {
                id: 'US-128',
                title: 'OAuth Resiliency',
                owner: 'Mira',
                status: 'Pending Review',
                risk: 'Medium',
                branch: 'feature/oauth-resiliency',
                progress: 42,
                summary: 'Improve token refresh fallback and provider timeout handling in the login journey.',
                impact: 'Auth Service, Session Store, Profile API',
                blockers: 0,
                revision: 2
            },
            'US-115': {
                id: 'US-115',
                title: 'PDF Export',
                owner: 'Ari',
                status: 'Executing',
                risk: 'Low',
                branch: 'feature/pdf-export',
                progress: 87,
                summary: 'Invoice and report export packaging with print-friendly layout adjustments.',
                impact: 'Document Generator, Export Queue',
                blockers: 0,
                revision: 4
            }
        },
        assetPack: {
            status: 'Drafting',
            scenariosDone: 5,
            scenarioTotal: 5,
            casesDone: 14,
            casesTotal: 18,
            automationStatus: 'Draft Ready',
            performanceStatus: 'Waiting Approval',
            changeDocStatus: 'Ready',
            revision: 'r3',
            pendingExecution: 1
        },
        knowledge: {
            objects: [
                {
                    id: 'OBJ-CHECKOUT',
                    name: 'Checkout Flow',
                    type: 'Feature',
                    branch: 'Version Shared',
                    confidence: '0.91',
                    relations: ['Payment Gateway App', 'Order Summary', 'Promo Engine'],
                    evidence: ['PR #882', 'Scenario Pack r3', 'Run-9021'],
                    freshness: '12 mins ago'
                },
                {
                    id: 'OBJ-AUTH',
                    name: 'Auth Service',
                    type: 'System',
                    branch: 'Official',
                    confidence: '0.97',
                    relations: ['OAuth Callback', 'Session Store', 'Profile API'],
                    evidence: ['System Image', 'Legacy Regression Pack'],
                    freshness: '1 hr ago'
                },
                {
                    id: 'OBJ-ASSET',
                    name: 'Checkout Scenario Pack',
                    type: 'QualityAssetPack',
                    branch: 'Candidate',
                    confidence: '0.88',
                    relations: ['US-123', 'Run-9021', 'Release Gate'],
                    evidence: ['Scenario Set', 'Automation Draft'],
                    freshness: '5 mins ago'
                }
            ]
        },
        runs: {
            'RUN-9021': {
                id: 'RUN-9021',
                source: 'US-123 Automation Pack',
                status: 'Failed',
                channel: 'Web Runner',
                environment: 'staging-checkout',
                failure: 'Locator mismatch on #submit-payment',
                healing: 'Not Proposed',
                evidence: 7,
                trace: 'trace-checkout-9021.zip'
            },
            'RUN-9020': {
                id: 'RUN-9020',
                source: 'Regression Pack',
                status: 'Passed',
                channel: 'Desktop Local',
                environment: 'qa-macbook-03',
                failure: 'None',
                healing: 'N/A',
                evidence: 11,
                trace: 'trace-regression-9020.zip'
            }
        },
        approvals: {
            'APR-442': {
                id: 'APR-442',
                title: 'Baseline Promotion #442',
                status: 'Waiting Approval',
                type: 'Promotion',
                scope: 'Version Branch 2026Q2 -> Official System Image',
                policy: 'Quality Lead Sign-off',
                conflictFields: 2,
                autoMergeReady: true
            },
            'APR-447': {
                id: 'APR-447',
                title: 'Desktop Local Capability',
                status: 'Waiting Confirmation',
                type: 'Capability',
                scope: 'device.local.execute',
                policy: 'User confirmation required',
                conflictFields: 0,
                autoMergeReady: false
            }
        },
        release: {
            score: 71,
            status: 'Conditionally Ready',
            blockers: 3,
            approvalsOpen: 2,
            pendingMerge: 1,
            executionHealth: '1 failed run pending review'
        },
        desktop: {
            deviceName: 'qa-macbook-03',
            status: 'Online',
            syncHealth: 'Healthy',
            queue: [
                { id: 'D-1', title: 'Confirm local retry screenshots collection', status: 'Needs confirmation' },
                { id: 'D-2', title: 'Replay receipt admin flow locally', status: 'Running' },
                { id: 'D-3', title: 'Upload local trace bundle', status: 'Queued' }
            ],
            grants: [
                'Task-scoped file write',
                'Browser automation',
                'Native script sandbox (confirm per invocation)'
            ]
        },
        conversations: {}
    };

    const PANEL_TABS = {
        welcome: [
            { id: 'activity', label: 'Activity' },
            { id: 'tips', label: 'Tips' },
            { id: 'status', label: 'Status' }
        ],
        build: [
            { id: 'projects', label: 'Projects' },
            { id: 'imports', label: 'Imports' },
            { id: 'health', label: 'Health' }
        ],
        dashboard: [
            { id: 'alerts', label: 'Alerts' },
            { id: 'progress', label: 'Progress' },
            { id: 'activity', label: 'Activity' }
        ],
        documentation: [
            { id: 'topics', label: 'Topics' },
            { id: 'templates', label: 'Templates' },
            { id: 'updates', label: 'Updates' }
        ],
        projectOverview: [
            { id: 'context', label: 'Context' },
            { id: 'versions', label: 'Versions' },
            { id: 'activity', label: 'Activity' }
        ],
        projectCreate: [
            { id: 'context', label: 'Context' },
            { id: 'assets', label: 'Assets' },
            { id: 'activity', label: 'Activity' }
        ],
        versionSpace: [
            { id: 'board', label: 'Board' },
            { id: 'context', label: 'Context' },
            { id: 'activity', label: 'Activity' }
        ],
        versionCreate: [
            { id: 'summary', label: 'Summary' },
            { id: 'owners', label: 'Owners' },
            { id: 'activity', label: 'Activity' }
        ],
        personalWorkspace: [
            { id: 'assets', label: 'Assets' },
            { id: 'context', label: 'Context' },
            { id: 'activity', label: 'Activity' }
        ],
        knowledgeGallery: [
            { id: 'graph', label: 'Graph' },
            { id: 'branches', label: 'Branches' },
            { id: 'activity', label: 'Activity' }
        ],
        knowledgeDetail: [
            { id: 'context', label: 'Context' },
            { id: 'evidence', label: 'Evidence' },
            { id: 'history', label: 'History' }
        ],
        runs: [
            { id: 'active', label: 'Active' },
            { id: 'channels', label: 'Channels' },
            { id: 'activity', label: 'Activity' }
        ],
        runDetail: [
            { id: 'evidence', label: 'Evidence' },
            { id: 'trace', label: 'Trace' },
            { id: 'activity', label: 'Activity' }
        ],
        governance: [
            { id: 'pending', label: 'Pending' },
            { id: 'policy', label: 'Policy' },
            { id: 'activity', label: 'Activity' }
        ],
        approvalDetail: [
            { id: 'diff', label: 'Diff' },
            { id: 'policy', label: 'Policy' },
            { id: 'activity', label: 'Activity' }
        ],
        releaseReadiness: [
            { id: 'blockers', label: 'Blockers' },
            { id: 'signals', label: 'Signals' },
            { id: 'activity', label: 'Activity' }
        ],
        desktop: [
            { id: 'queue', label: 'Queue' },
            { id: 'grants', label: 'Grants' },
            { id: 'sync', label: 'Sync' }
        ]
    };

    function viewMeta(viewId = state.currentViewId) {
        return {
            welcome: {
                title: 'Welcome to Nasus',
                badge: badge('Studio Home', 'info'),
                panelTitle: 'Studio Overview',
                placeholder: 'Ask Nasus to create a project, resume work, or explain what changed.'
            },
            build: {
                title: 'Build',
                badge: badge('Project Entry', 'info'),
                panelTitle: 'Build Context',
                placeholder: 'Ask Nasus to create a project, import Git, or initialize a system image.'
            },
            dashboard: {
                title: 'Dashboard',
                badge: badge('Global Health', 'active'),
                panelTitle: 'Global Signals',
                placeholder: 'Ask for blocked releases, project risk, or current testing progress.'
            },
            documentation: {
                title: 'Documentation',
                badge: badge('Guides', 'review'),
                panelTitle: 'Docs Navigator',
                placeholder: 'Ask how Nasus works, how to use branching, or how a workflow closes.'
            },
            projectOverview: {
                title: `${currentProjectName()} · Project Overview`,
                badge: badge('Workspace', 'active'),
                panelTitle: 'Project Context',
                placeholder: 'Ask Nasus to refresh the system image, review imports, or launch a version.'
            },
            projectCreate: {
                title: 'Create Project',
                badge: badge('Setup Flow', 'progress'),
                panelTitle: 'Project Setup',
                placeholder: 'Describe the repositories, docs, boards, and quality assets to import.'
            },
            versionSpace: {
                title: `${currentVersion().name} · Version Space`,
                badge: badge(currentVersion().status, 'progress'),
                panelTitle: 'Version Pulse',
                placeholder: 'Ask for version progress, blockers, risk, or owner-level closure.'
            },
            versionCreate: {
                title: 'Create Version Branch',
                badge: badge('Branching', 'review'),
                panelTitle: 'Version Setup',
                placeholder: 'Describe the release branch, imported US input, and owner assignment plan.'
            },
            personalWorkspace: {
                title: `${currentUs().id} Quality Workspace`,
                badge: badge(currentUs().status, 'progress'),
                panelTitle: 'Asset Pack',
                placeholder: 'Generate assets, inspect context, or continue the US quality closure.'
            },
            knowledgeGallery: {
                title: 'Knowledge Gallery',
                badge: badge('System Image', 'info'),
                panelTitle: 'Knowledge Context',
                placeholder: 'Ask about system objects, evidence, branch lineage, or risk hotspots.'
            },
            knowledgeDetail: {
                title: `${currentObject().name} · Object Detail`,
                badge: badge(currentObject().branch, 'info'),
                panelTitle: 'Object Detail',
                placeholder: 'Ask for object lineage, related US, or evidence-backed impact.'
            },
            runs: {
                title: 'Execution Runs',
                badge: badge('Canonical Run Model', 'info'),
                panelTitle: 'Run Queue',
                placeholder: 'Ask about run health, channels, failures, or execution backlog.'
            },
            runDetail: {
                title: `${currentRun().id} · Run Detail`,
                badge: badge(currentRun().status, currentRun().status === 'Failed' ? 'danger' : 'active'),
                panelTitle: 'Run Evidence',
                placeholder: 'Explain the failure, inspect trace, or propose healing.'
            },
            governance: {
                title: 'Governance',
                badge: badge('Approval Queue', 'review'),
                panelTitle: 'Governance Queue',
                placeholder: 'Ask what is waiting approval, what is blocked, or what needs merge resolution.'
            },
            approvalDetail: {
                title: `${currentApproval().title}`,
                badge: badge(currentApproval().status, 'review'),
                panelTitle: 'Approval Detail',
                placeholder: 'Ask why this item is blocked or how the merge should be resolved.'
            },
            releaseReadiness: {
                title: `${currentVersion().name} · Release Readiness`,
                badge: badge(state.release.status, 'progress'),
                panelTitle: 'Release Gate',
                placeholder: 'Ask if the version is ready, what still blocks release, or what to close next.'
            },
            desktop: {
                title: 'Desktop Execution',
                badge: badge(state.desktop.status, 'active'),
                panelTitle: 'Desktop Runtime',
                placeholder: 'Ask about local queue, sync health, or why a task needs confirmation.'
            }
        }[viewId];
    }

    function currentProject() {
        return state.projects.find((project) => project.id === state.currentProjectId) || state.projects[0];
    }

    function currentProjectName() {
        return currentProject().name;
    }

    function currentVersion() {
        return state.versions.find((version) => version.id === state.currentVersionId) || state.versions[0];
    }

    function currentUs() {
        return state.usItems[state.currentUsId];
    }

    function currentRun() {
        return state.runs[state.currentRunId];
    }

    function currentApproval() {
        return state.approvals[state.currentApprovalId];
    }

    function currentObject() {
        return state.knowledge.objects.find((item) => item.id === state.currentObjectId) || state.knowledge.objects[0];
    }

    function isWorkspaceView(viewId = state.currentViewId) {
        return WORKSPACE_VIEWS.has(viewId);
    }

    function timeLabel() {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function badge(text, tone = 'default') {
        const styleMap = {
            progress: 'background:rgba(253,214,99,0.1);color:var(--accent-amber);border:1px solid rgba(253,214,99,0.2);',
            active: 'background:rgba(129,201,149,0.1);color:var(--accent-green);border:1px solid rgba(129,201,149,0.2);',
            info: 'background:rgba(138,180,248,0.1);color:var(--accent-blue);border:1px solid rgba(138,180,248,0.2);',
            review: 'background:rgba(197,138,249,0.1);color:var(--accent-purple);border:1px solid rgba(197,138,249,0.2);',
            danger: 'background:rgba(242,139,130,0.1);color:var(--accent-red);border:1px solid rgba(242,139,130,0.2);'
        };
        return `<span class="status-badge" style="${styleMap[tone] || styleMap.info}">${text}</span>`;
    }

    function miniChip(label, tone = 'info') {
        return `<span class="mini-chip ${tone}">${label}</span>`;
    }

    function statusTone(status) {
        const normalized = status.toLowerCase();
        if (normalized.includes('progress') || normalized.includes('execut') || normalized.includes('running')) return 'info';
        if (normalized.includes('review') || normalized.includes('pending') || normalized.includes('waiting')) return 'warn';
        if (normalized.includes('fail') || normalized.includes('block') || normalized.includes('elevated')) return 'bad';
        if (normalized.includes('pass') || normalized.includes('approved') || normalized.includes('ready') || normalized.includes('stable')) return 'good';
        return 'info';
    }

    function agentIcon() {
        return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg>';
    }

    function createMessage(role, options) {
        return { role, time: options.time || timeLabel(), name: options.name, text: options.text, html: options.html };
    }

    function conversationKey(viewId = state.currentViewId) {
        if (viewId === 'personalWorkspace') return `personalWorkspace:${state.currentUsId}`;
        if (viewId === 'runDetail') return `runDetail:${state.currentRunId}`;
        if (viewId === 'approvalDetail') return `approvalDetail:${state.currentApprovalId}`;
        if (viewId === 'knowledgeDetail') return `knowledgeDetail:${state.currentObjectId}`;
        return viewId;
    }

    function summaryStat(label, value, note = '') {
        return `
            <div class="surface-stat">
                <div class="surface-stat-label">${label}</div>
                <div class="surface-stat-value">${value}</div>
                ${note ? `<div class="surface-stat-note">${note}</div>` : ''}
            </div>
        `;
    }

    function surfaceRow(title, subtitle, meta = [], actionHtml = '') {
        return `
            <div class="surface-row">
                <div class="surface-row-main">
                    <div class="surface-row-title">${title}</div>
                    <div class="surface-row-subtitle">${subtitle}</div>
                    ${meta.length ? `<div class="surface-row-meta">${meta.join('')}</div>` : ''}
                </div>
                ${actionHtml}
            </div>
        `;
    }

    function ghostButton(label, action, icon, dataAttrs = {}) {
        const attrs = Object.entries(dataAttrs).map(([key, value]) => `data-${key}="${value}"`).join(' ');
        return `<button class="ghost-chip" data-action="${action}" ${attrs}>${icon ? `<i class="${icon}"></i>` : ''}${label}</button>`;
    }

    function heroCard(icon, title, copy, action, actionLabel) {
        return `
            <div class="hero-card" data-action="${action}">
                <div class="hero-card-icon"><i class="${icon}"></i></div>
                <div class="hero-card-title">${title}</div>
                <div class="hero-card-copy">${copy}</div>
                ${actionLabel ? `<div class="collection-card-footer"><span class="collection-card-subtitle">${actionLabel}</span><i class="fa-solid fa-arrow-right" style="color:var(--text-tertiary);font-size:11px;"></i></div>` : ''}
            </div>
        `;
    }

    function projectCard(project) {
        return `
            <div class="collection-card">
                <div class="collection-card-title">${project.name}</div>
                <div class="collection-card-copy">${project.subtitle}</div>
                <div class="collection-card-meta">
                    ${miniChip(project.activeVersion, 'info')}
                    ${miniChip(project.overallRisk, statusTone(project.overallRisk))}
                    ${miniChip(`${project.progress}%`, 'good')}
                </div>
                <div class="collection-card-footer">
                    <span class="collection-card-subtitle">${project.nextAction}</span>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;width:100%;justify-content:flex-end;">
                        <button class="pill-chip" data-action="open_version_create" data-project="${project.id}"><i class="fa-solid fa-code-branch"></i>Create Version</button>
                        <button class="pill-chip primary" data-action="open_project" data-project="${project.id}"><i class="fa-solid fa-arrow-right"></i>Open</button>
                    </div>
                </div>
            </div>
        `;
    }

    function draftCard(draft) {
        return `
            <div class="collection-card">
                <div class="collection-card-title">${draft.title}</div>
                <div class="collection-card-copy">${draft.status}</div>
                <div class="collection-card-meta">
                    ${miniChip('draft', 'warn')}
                    ${miniChip('setup', 'info')}
                </div>
                <div class="collection-card-footer">
                    <span class="collection-card-subtitle">${draft.next}</span>
                    <div style="display:flex;width:100%;justify-content:flex-end;">
                        <button class="pill-chip" data-action="open_project_create"><i class="fa-solid fa-arrow-right"></i>Continue</button>
                    </div>
                </div>
            </div>
        `;
    }

    function docCard(doc) {
        return `
            <div class="collection-card">
                <div class="collection-card-title">${doc.title}</div>
                <div class="collection-card-copy">${doc.copy}</div>
                <div class="collection-card-meta">${miniChip(doc.category, 'info')}</div>
                <div class="collection-card-footer">
                    <span class="collection-card-subtitle">Agent-readable guide</span>
                    <div style="display:flex;width:100%;justify-content:flex-end;">
                        <button class="pill-chip" data-action="search_docs" data-doc="${doc.id}"><i class="fa-solid fa-book-open"></i>Open</button>
                    </div>
                </div>
            </div>
        `;
    }

    function createTypingMessage() {
        return `
            <div class="message agent message-in">
                <div class="agent-avatar">${agentIcon()}</div>
                <div class="message-body" style="flex:1;max-width:85%;">
                    <div class="message-meta"><span class="name">Nasus Agent</span><span class="time">${timeLabel()}</span></div>
                    <div class="message-bubble">
                        <div class="typing-dots">
                            <span class="typing-dot"></span>
                            <span class="typing-dot"></span>
                            <span class="typing-dot"></span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function renderMessage(message) {
        if (message.role === 'user') {
            return `
                <div class="message user message-in">
                    <img src="https://ui-avatars.com/api/?name=US&background=8ab4f8&color=131314&size=28" alt="User" class="message-avatar">
                    <div class="message-body">
                        <div class="message-meta"><span class="time">${message.time}</span><span class="name">You</span></div>
                        <div class="message-bubble">${escapeHtml(message.text)}</div>
                    </div>
                </div>
            `;
        }

        return `
            <div class="message agent message-in">
                <div class="agent-avatar">${agentIcon()}</div>
                <div class="message-body" style="flex:1;max-width:85%;">
                    <div class="message-meta"><span class="name">${message.name || 'Nasus Agent'}</span><span class="time">${message.time}</span></div>
                    <div class="message-bubble">${message.html}</div>
                </div>
            </div>
        `;
    }

    function seedConversation(viewId) {
        switch (viewId) {
            case 'welcome':
                return [
                    createMessage('agent', {
                        time: '09:02 AM',
                        html: `
                            <div class="hero-stack">
                                <div class="hero-panel">
                                    <div class="hero-kicker">Nasus Studio</div>
                                    <h2 class="hero-title">Build release quality with an agent-first workflow.</h2>
                                    <p class="hero-copy">Start from conversation, enter Build to create or open projects, use Dashboard to monitor quality closure, and use Documentation to understand the platform before entering a live workspace.</p>
                                </div>
                                <div>
                                    <div class="section-heading">
                                        <h3 class="section-heading-title">Choose how you want to begin</h3>
                                        <p class="section-heading-copy">This is the L0 welcome layer. It should feel like a product home, not a deep task screen.</p>
                                    </div>
                                    <div class="hero-grid">
                                        ${heroCard('fa-solid fa-hammer', 'Build', 'Create a project, connect Git and docs, and enter a project workspace.', 'open_build', 'Enter Build')}
                                        ${heroCard('fa-solid fa-chart-line', 'Dashboard', 'See blocked releases, open approvals, execution failures, and cross-project quality progress.', 'open_dashboard', 'Open Dashboard')}
                                        ${heroCard('fa-solid fa-book-open', 'Documentation', 'Learn branching, system images, asset packs, governance, and desktop execution.', 'open_documentation', 'Read docs')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Resume recent work</h3>
                                            <p class="surface-section-subtitle">Recent projects and versions should be available without dropping the user into a deep workspace by default.</p>
                                        </div>
                                    </div>
                                    <div class="collection-grid">
                                        ${state.projects.map(projectCard).join('')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'build':
                return [
                    createMessage('agent', {
                        time: '09:12 AM',
                        html: `
                            <div class="surface-stack">
                                <div class="hero-panel">
                                    <div class="hero-kicker">Build</div>
                                    <h2 class="hero-title" style="font-size:28px;">Create a new project and initialize its system image.</h2>
                                    <p class="hero-copy">Build is the project creation surface. It should foreground one obvious path: define the project, import Git and requirement sources, attach UX boards and historical quality assets, then let the agent guide the initialization of the Official System Image.</p>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Create Project</h3>
                                            <p class="surface-section-subtitle">This should be the dominant visual block on the page, with both direct actions and conversational onboarding.</p>
                                        </div>
                                    </div>
                                    <div class="overview-grid">
                                        <div class="collection-card full-span" style="padding:20px;">
                                            <div class="collection-card-title" style="font-size:18px;">Start a new project space</div>
                                            <div class="collection-card-copy" style="font-size:13px;">Create a project from a guided setup flow or simply ask Nasus in conversation. The agent should collect the required inputs step by step and show the setup progress as structured state.</div>
                                            <div class="collection-card-meta">
                                                ${miniChip('Git repository', 'info')}
                                                ${miniChip('US documents', 'info')}
                                                ${miniChip('UX boards', 'info')}
                                                ${miniChip('Historical assets', 'info')}
                                            </div>
                                            <div class="surface-actions" style="margin-top:16px;">
                                                ${ghostButton('Create Project', 'open_project_create', 'fa-solid fa-plus')}
                                                ${ghostButton('Ask Agent to Guide Setup', 'agent_create_project', 'fa-solid fa-comments')}
                                            </div>
                                        </div>
                                        <div class="collection-card">
                                            <div class="collection-card-title">Import checklist</div>
                                            <div class="collection-card-copy">What the agent should collect before initialization.</div>
                                            <div class="surface-list" style="margin-top:14px;">
                                                ${surfaceRow('Git repositories', 'Primary service repos and optional linked UI repos', [miniChip('required', 'warn')])}
                                                ${surfaceRow('US / PRD input', 'Requirement docs, acceptance notes, release notes', [miniChip('required', 'warn')])}
                                                ${surfaceRow('UX references', 'Boards, flows, or screenshots tied to the change surface', [miniChip('recommended', 'info')])}
                                                ${surfaceRow('Historical quality assets', 'Existing tests, logs, flaky history, smoke packs', [miniChip('recommended', 'info')])}
                                            </div>
                                        </div>
                                        <div class="collection-card">
                                            <div class="collection-card-title">Conversation-first setup</div>
                                            <div class="collection-card-copy">Natural language should be enough to start project creation.</div>
                                            <div class="surface-list" style="margin-top:14px;">
                                                ${surfaceRow('User says', '“Help me create a new project for Payment System.”', [miniChip('chat', 'good')])}
                                                ${surfaceRow('Agent asks', '“Please provide Git repos, US docs, and UX boards.”', [miniChip('guided', 'info')])}
                                                ${surfaceRow('Agent materializes', 'Project draft, import tasks, and system image init plan', [miniChip('structured', 'good')])}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Draft setups</h3>
                                            <p class="surface-section-subtitle">Build can keep unfinished project setup drafts, but it should not be the primary project browsing surface.</p>
                                        </div>
                                    </div>
                                    <div class="collection-grid">
                                        ${state.buildDrafts.map(draftCard).join('')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'dashboard':
                return [
                    createMessage('agent', {
                        time: '09:20 AM',
                        html: `
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Global quality pulse</h3>
                                            <p class="surface-section-subtitle">Dashboard is the project portfolio view. It should summarize cross-project progress, blockages, and governance pressure, then let users enter a project space by clicking a card.</p>
                                        </div>
                                    </div>
                                    <div class="surface-grid">
                                        ${summaryStat('Projects', `${state.dashboard.activeProjects}`, 'Tracked in Build')}
                                        ${summaryStat('Versions', `${state.dashboard.activeVersions}`, 'Live release branches')}
                                        ${summaryStat('Open US', `${state.dashboard.openUs}`, 'Across all versions')}
                                        ${summaryStat('Blocked', `${state.dashboard.blockedItems}`, 'Needs owner action')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Projects</h3>
                                            <p class="surface-section-subtitle">Each project is a card. Clicking a card should open a dedicated project page rather than expanding a nested menu inside the same top-level screen.</p>
                                        </div>
                                    </div>
                                    <div class="collection-grid">
                                        ${state.projects.map(projectCard).join('')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Ask about progress</h3>
                                            <p class="surface-section-subtitle">Dashboard conversation should answer portfolio-level questions like project risk, testing progress, and pending gates.</p>
                                        </div>
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Which project is riskiest?', 'dashboard_risk_query', 'fa-solid fa-triangle-exclamation')}
                                        ${ghostButton('Show blocked releases', 'dashboard_blockers_query', 'fa-solid fa-road-barrier')}
                                        ${ghostButton('Open governance backlog', 'open_governance', 'fa-solid fa-gavel')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'documentation':
                return [
                    createMessage('agent', {
                        time: '09:26 AM',
                        html: `
                            <div class="surface-stack">
                                <div class="hero-panel">
                                    <div class="hero-kicker">Documentation</div>
                                    <h2 class="hero-title" style="font-size:28px;">Explain the system before users enter deep workflow mode.</h2>
                                    <p class="hero-copy">Documentation should feel like a first-class product area, not a footer link. It helps new users understand how Build, versions, asset packs, governance, and desktop execution fit together.</p>
                                </div>
                                <div class="collection-grid">
                                    ${state.docs.map(docCard).join('')}
                                </div>
                            </div>
                        `
                    })
                ];
            case 'projectOverview':
                return [
                    createMessage('agent', {
                        time: '09:40 AM',
                        name: 'Nasus Central Agent',
                        html: `
                            <p style="margin:0 0 12px;">You are now inside the <strong>${currentProject().name}</strong> workspace. This is the L2 entry point for a selected project, not the general Build page.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Project command center</h3>
                                            <p class="surface-section-subtitle">Use this page to inspect connected sources, the official system image, and the versions that branch from it.</p>
                                        </div>
                                    </div>
                                    <div class="surface-grid">
                                        ${summaryStat('Baseline', currentProject().baseline, 'Official branch')}
                                        ${summaryStat('Modules', `${currentProject().modules}`, 'Indexed in system image')}
                                        ${summaryStat('Tests', `${currentProject().tests}`, 'Known historical assets')}
                                        ${summaryStat('Versions', `${currentProject().versions}`, currentProject().activeVersion)}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Create Version Branch', 'open_version_create', 'fa-solid fa-code-branch')}
                                        ${ghostButton('Refresh System Image', 'refresh_system_image', 'fa-solid fa-rotate-right')}
                                        ${ghostButton('Open Knowledge', 'open_knowledge_gallery', 'fa-solid fa-diagram-project')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Connected sources</h3>
                                            <p class="surface-section-subtitle">The project overview should summarize ingestion and source readiness before you dive into version work.</p>
                                        </div>
                                    </div>
                                    <div class="surface-list">
                                        ${currentProject().sources.map((source) => surfaceRow(source, 'Connected and queryable', [miniChip('ready', 'good')])).join('')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'projectCreate':
                return [
                    createMessage('agent', {
                        time: '09:45 AM',
                        name: 'Nasus Setup Agent',
                        html: `
                            <p style="margin:0 0 12px;">I can create a new project space from conversation or form input. Provide Git repositories, US docs, UX boards, and historical assets, and I will validate connections before initializing the <strong>Official System Image Branch</strong>.</p>
                            <div class="surface-section">
                                <div class="surface-section-header">
                                    <div>
                                        <h3 class="surface-section-title">Create Project flow</h3>
                                        <p class="surface-section-subtitle">This page should live under Build, before any version work starts.</p>
                                    </div>
                                </div>
                                <div class="form-grid">
                                    <div class="form-field">
                                        <div class="form-label">Project profile</div>
                                        <div class="form-value">Payment System / Commerce Platform</div>
                                        <div class="form-note">Single enterprise deployment, multi-project model.</div>
                                    </div>
                                    <div class="form-field">
                                        <div class="form-label">Git repositories</div>
                                        <div class="form-value">${state.createProject.repoCount} connected repos</div>
                                        <div class="form-note">payment-system, checkout-ui</div>
                                    </div>
                                    <div class="form-field">
                                        <div class="form-label">US documents</div>
                                        <div class="form-value">${state.createProject.usDocs} files uploaded</div>
                                        <div class="form-note">PRD, acceptance notes, release notes</div>
                                    </div>
                                    <div class="form-field">
                                        <div class="form-label">UX boards</div>
                                        <div class="form-value">${state.createProject.uxBoards} boards linked</div>
                                        <div class="form-note">Checkout, refund, fallback states</div>
                                    </div>
                                    <div class="form-field full">
                                        <div class="form-label">Historical quality assets</div>
                                        <div class="form-value">${state.createProject.historicalPacks} imported packs · ${state.createProject.validation}</div>
                                        <div class="form-note">Legacy smoke, regression artifacts, flaky failure history</div>
                                    </div>
                                </div>
                                <div class="surface-actions">
                                    ${ghostButton('Validate Sources', 'validate_project_inputs', 'fa-solid fa-bolt')}
                                    ${ghostButton('Import Assets', 'import_project_assets', 'fa-solid fa-file-import')}
                                    ${ghostButton('Initialize System Image', 'initialize_system_image', 'fa-solid fa-layer-group')}
                                    ${ghostButton('Back to Build', 'open_build', 'fa-solid fa-arrow-left')}
                                </div>
                            </div>
                        `
                    })
                ];
            case 'versionSpace':
                return [
                    createMessage('agent', {
                        time: '10:12 AM',
                        html: `
                            <p style="margin:0 0 12px;">The <strong>${currentVersion().name}</strong> branch is active. This is the version-level operational center where US board, owner assignment, risk pulse, and release progress come together.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Version board</h3>
                                            <p class="surface-section-subtitle">This page should exist before users jump into a single US workspace.</p>
                                        </div>
                                    </div>
                                    <div class="surface-grid">
                                        ${summaryStat('Progress', `${currentVersion().progress}%`, currentVersion().releaseWindow)}
                                        ${summaryStat('Open US', `${currentVersion().usCount}`, 'Across all owners')}
                                        ${summaryStat('Pending approvals', `${currentVersion().pendingApprovals}`, 'Governance queue')}
                                        ${summaryStat('Pending merge', `${currentVersion().pendingMerge}`, 'Needs manual resolution')}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Create Version Branch', 'open_version_create', 'fa-solid fa-plus')}
                                        ${ghostButton('Generate Version Risk', 'generate_version_risk', 'fa-solid fa-shield-halved')}
                                        ${ghostButton('Release Readiness', 'open_release_readiness', 'fa-solid fa-clipboard-check')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">US board</h3>
                                            <p class="surface-section-subtitle">Every US card should be a stable entry into the personal quality workspace.</p>
                                        </div>
                                    </div>
                                    <div class="surface-list">
                                        ${Object.values(state.usItems).map((item) => surfaceRow(
                                            `${item.id} · ${item.title}`,
                                            item.summary,
                                            [
                                                miniChip(item.owner, 'info'),
                                                miniChip(item.status, statusTone(item.status)),
                                                miniChip(`${item.progress}%`, 'good'),
                                                miniChip(item.risk, item.risk === 'High' ? 'bad' : 'warn')
                                            ],
                                            `<button class="pill-chip primary" data-action="open_us_workspace" data-us="${item.id}"><i class="fa-solid fa-arrow-right"></i>Open</button>`
                                        )).join('')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'versionCreate':
                return [
                    createMessage('agent', {
                        time: '10:18 AM',
                        name: 'Nasus Branch Agent',
                        html: `
                            <p style="margin:0 0 12px;">Version creation belongs inside the project workspace, but it still precedes detailed US execution. This page launches a branch, imports US input, assigns owners, and forks the baseline.</p>
                            <div class="surface-section">
                                <div class="surface-section-header">
                                    <div>
                                        <h3 class="surface-section-title">Create Version Branch</h3>
                                        <p class="surface-section-subtitle">Branch from ${state.versionCreate.sourceBranch} into ${state.versionCreate.targetBranch} and seed the quality loop.</p>
                                    </div>
                                </div>
                                <div class="form-grid">
                                    <div class="form-field">
                                        <div class="form-label">Version basics</div>
                                        <div class="form-value">${currentVersion().name}</div>
                                        <div class="form-note">Target release: ${state.versionCreate.targetDate}</div>
                                    </div>
                                    <div class="form-field">
                                        <div class="form-label">Source branch</div>
                                        <div class="form-value">${state.versionCreate.sourceBranch}</div>
                                        <div class="form-note">Current baseline parent</div>
                                    </div>
                                    <div class="form-field">
                                        <div class="form-label">Imported US</div>
                                        <div class="form-value">${state.versionCreate.usImported} items</div>
                                        <div class="form-note">Imported from product docs</div>
                                    </div>
                                    <div class="form-field">
                                        <div class="form-label">Owner assignment</div>
                                        <div class="form-value">${state.versionCreate.ownersAssigned} assigned</div>
                                        <div class="form-note">By component expertise and workload</div>
                                    </div>
                                    <div class="form-field full">
                                        <div class="form-label">Baseline fork preview</div>
                                        <div class="form-value">${state.versionCreate.baselineFork}</div>
                                        <div class="form-note">Copy-on-write delta overlay, not full duplication.</div>
                                    </div>
                                </div>
                                <div class="surface-actions">
                                    ${ghostButton('Import US', 'import_version_us', 'fa-solid fa-file-circle-plus')}
                                    ${ghostButton('Assign Owners', 'assign_owners', 'fa-solid fa-user-plus')}
                                    ${ghostButton('Fork Baseline', 'fork_baseline', 'fa-solid fa-code-branch')}
                                    ${ghostButton('Create Version', 'create_version_branch', 'fa-solid fa-check')}
                                </div>
                            </div>
                        `
                    })
                ];
            case 'personalWorkspace':
                return [
                    createMessage('user', { time: '10:41 AM', text: `Continue quality closure for ${currentUs().id}.` }),
                    createMessage('agent', {
                        time: '10:42 AM',
                        html: `
                            <p style="margin:0 0 12px;">You are now in the project-level personal workspace for <strong>${currentUs().id}: ${currentUs().title}</strong>. This is the deepest L2 work surface.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">US quality closure snapshot</h3>
                                            <p class="surface-section-subtitle">Current task context, latest asset pack revision, and the next actions the agent can take.</p>
                                        </div>
                                    </div>
                                    <div class="surface-grid">
                                        ${summaryStat('Progress', `${currentUs().progress}%`, currentUs().branch)}
                                        ${summaryStat('Risk', currentUs().risk, currentUs().impact)}
                                        ${summaryStat('Revision', state.assetPack.revision, `${state.assetPack.scenariosDone}/${state.assetPack.scenarioTotal} scenarios`)}
                                        ${summaryStat('Pending Execution', `${state.assetPack.pendingExecution}`, state.assetPack.automationStatus)}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Generate Scenarios', 'generate_scenarios', 'fa-solid fa-wand-magic-sparkles')}
                                        ${ghostButton('Open Run Detail', 'open_run_detail', 'fa-solid fa-play')}
                                        ${ghostButton('Open Release Readiness', 'open_release_readiness', 'fa-solid fa-clipboard-check')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Quality Asset Pack lanes</h3>
                                            <p class="surface-section-subtitle">Every lane is structured, revisable, and eventually feeds execution, governance, or release readiness.</p>
                                        </div>
                                    </div>
                                    <div class="surface-list">
                                        ${surfaceRow('Scenario Set', `Drafted from ${currentUs().impact}`, [miniChip(`${state.assetPack.scenariosDone}/${state.assetPack.scenarioTotal} done`, 'info')], `<button class="pill-chip primary" data-action="generate_scenarios"><i class="fa-solid fa-list-check"></i>Generate</button>`)}
                                        ${surfaceRow('Case Set', `${state.assetPack.casesDone}/${state.assetPack.casesTotal} cases drafted`, [miniChip('Needs review', 'warn')], `<button class="pill-chip" data-action="open_us_workspace"><i class="fa-solid fa-table-list"></i>Inspect</button>`)}
                                        ${surfaceRow('Automation', state.assetPack.automationStatus, [miniChip('Playwright target', 'good')], `<button class="pill-chip" data-action="open_run_detail"><i class="fa-solid fa-terminal"></i>Inspect Run</button>`)}
                                        ${surfaceRow('Performance', state.assetPack.performanceStatus, [miniChip('Approval gate', 'warn')], `<button class="pill-chip" data-action="open_approval_detail"><i class="fa-solid fa-gavel"></i>Open Gate</button>`)}
                                        ${surfaceRow('Change Doc', state.assetPack.changeDocStatus, [miniChip('Ready for release summary', 'good')], `<button class="pill-chip" data-action="open_release_readiness"><i class="fa-solid fa-file-lines"></i>Use in Release</button>`)}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'knowledgeGallery':
                return [
                    createMessage('agent', {
                        time: '11:05 AM',
                        html: `
                            <p style="margin:0 0 12px;">Knowledge is a project workspace page, not a platform homepage. This gallery should help users navigate trusted and candidate context objects tied to the selected project and version.</p>
                            <div class="surface-section">
                                <div class="surface-section-header">
                                    <div>
                                        <h3 class="surface-section-title">Knowledge objects</h3>
                                        <p class="surface-section-subtitle">System, feature, and quality asset objects with branch-aware provenance.</p>
                                    </div>
                                </div>
                                <div class="surface-list">
                                    ${state.knowledge.objects.map((obj) => surfaceRow(
                                        `${obj.name} · ${obj.type}`,
                                        `Branch: ${obj.branch} · Confidence: ${obj.confidence} · Freshness: ${obj.freshness}`,
                                        obj.relations.slice(0, 2).map((name) => miniChip(name, 'info')),
                                        `<button class="pill-chip primary" data-action="open_knowledge_detail" data-object="${obj.id}"><i class="fa-solid fa-arrow-right"></i>Inspect</button>`
                                    )).join('')}
                                </div>
                            </div>
                        `
                    })
                ];
            case 'knowledgeDetail':
                return [
                    createMessage('agent', {
                        time: '11:18 AM',
                        html: `
                            <p style="margin:0 0 12px;"><strong>${currentObject().name}</strong> is open as a branch-aware object detail page so the team can inspect evidence, relationships, and promotion readiness.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-grid">
                                        ${summaryStat('Freshness', currentObject().freshness, 'Last refresh')}
                                        ${summaryStat('Evidence', `${currentObject().evidence.length}`, 'Attached references')}
                                        ${summaryStat('Relations', `${currentObject().relations.length}`, 'Direct graph edges')}
                                        ${summaryStat('Branch', currentObject().branch, 'Current storage tier')}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Analyze Impact', 'analyze_object_impact', 'fa-solid fa-wave-square')}
                                        ${ghostButton('Promote Candidate', 'promote_candidate', 'fa-solid fa-arrow-up-right-dots')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Relationship and evidence trail</h3>
                                            <p class="surface-section-subtitle">Every object needs explainable lineage and downstream navigation.</p>
                                        </div>
                                    </div>
                                    <div class="surface-list">
                                        ${currentObject().relations.map((relation) => surfaceRow(relation, 'Direct relationship in the current context graph', [miniChip('related', 'info')])).join('')}
                                        ${currentObject().evidence.map((ref) => surfaceRow(ref, 'Referenced source or generated evidence', [miniChip('evidence', 'good')])).join('')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'runs':
                return [
                    createMessage('agent', {
                        time: '11:30 AM',
                        html: `
                            <p style="margin:0 0 12px;">Runs should stay inside the project workspace. This page shows the canonical run list across web and desktop execution channels.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-grid">
                                        ${summaryStat('Failed', '1', 'Needs triage')}
                                        ${summaryStat('Running', '1', 'Desktop local replay')}
                                        ${summaryStat('Passed', '1', 'Latest stable run')}
                                        ${summaryStat('Evidence', '18', 'Artifacts attached')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Run list</h3>
                                            <p class="surface-section-subtitle">Every row should open into a detailed timeline and evidence workspace.</p>
                                        </div>
                                    </div>
                                    <div class="surface-list">
                                        ${Object.values(state.runs).map((run) => surfaceRow(
                                            `${run.id} · ${run.source}`,
                                            `${run.channel} · ${run.environment} · ${run.failure}`,
                                            [
                                                miniChip(run.status, run.status === 'Failed' ? 'bad' : 'good'),
                                                miniChip(`${run.evidence} evidence`, 'info')
                                            ],
                                            `<button class="pill-chip primary" data-action="open_run_detail" data-run="${run.id}"><i class="fa-solid fa-arrow-right"></i>Open</button>`
                                        )).join('')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'runDetail':
                return [
                    createMessage('agent', {
                        time: '11:42 AM',
                        html: `
                            <p style="margin:0 0 12px;">Run detail should carry the full failure analysis loop: timeline, logs, evidence, healing proposal, and fallback-to-human threshold.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-grid">
                                        ${summaryStat('Failure', currentRun().failure, 'Current primary fingerprint')}
                                        ${summaryStat('Healing', currentRun().healing, 'Proposal status')}
                                        ${summaryStat('Evidence', `${currentRun().evidence}`, 'Artifacts available')}
                                        ${summaryStat('Trace', 'Ready', currentRun().trace)}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Propose Healing Patch', 'propose_healing', 'fa-solid fa-syringe')}
                                        ${ghostButton('Retry Run', 'retry_run', 'fa-solid fa-rotate')}
                                        ${ghostButton('Fallback to Human', 'fallback_human', 'fa-solid fa-user-check')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Timeline</h3>
                                            <p class="surface-section-subtitle">This is where the team learns what actually happened in execution.</p>
                                        </div>
                                    </div>
                                    <div class="timeline-list">
                                        <div class="timeline-item"><div class="timeline-dot"></div><div class="timeline-content"><div class="timeline-title">Run queued</div><div class="timeline-text">Asset pack execution was accepted by the web runner.</div></div></div>
                                        <div class="timeline-item"><div class="timeline-dot"></div><div class="timeline-content"><div class="timeline-title">Scenario and script bundle loaded</div><div class="timeline-text">Playwright draft aligned with checkout selectors from baseline.</div></div></div>
                                        <div class="timeline-item"><div class="timeline-dot bad"></div><div class="timeline-content"><div class="timeline-title">Locator mismatch detected</div><div class="timeline-text">The selector <code>#submit-payment</code> no longer matches the current DOM after PR #882.</div></div></div>
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'governance':
                return [
                    createMessage('agent', {
                        time: '12:00 PM',
                        name: 'Nasus Policy Agent',
                        html: `
                            <p style="margin:0 0 12px;">Governance belongs inside the project workspace, but it should separate queue view from item detail. The list page shows approvals, pending merges, and policy-blocked items at a glance.</p>
                            <div class="surface-section">
                                <div class="surface-section-header">
                                    <div>
                                        <h3 class="surface-section-title">Pending governance items</h3>
                                        <p class="surface-section-subtitle">Approvals, promotions, local capability requests, and merge conflicts all belong here.</p>
                                    </div>
                                </div>
                                <div class="surface-list">
                                    ${Object.values(state.approvals).map((approval) => surfaceRow(
                                        approval.title,
                                        `${approval.scope} · ${approval.policy}`,
                                        [
                                            miniChip(approval.status, approval.status.includes('Waiting') ? 'warn' : 'good'),
                                            miniChip(approval.type, 'info')
                                        ],
                                        `<button class="pill-chip primary" data-action="open_approval_detail" data-approval="${approval.id}"><i class="fa-solid fa-arrow-right"></i>Review</button>`
                                    )).join('')}
                                </div>
                                <div class="surface-actions">
                                    ${ghostButton('Open Release Readiness', 'open_release_readiness', 'fa-solid fa-clipboard-check')}
                                </div>
                            </div>
                        `
                    })
                ];
            case 'approvalDetail':
                return [
                    createMessage('agent', {
                        time: '12:08 PM',
                        name: 'Nasus Policy Agent',
                        html: `
                            <p style="margin:0 0 12px;">This page must resolve more than a yes/no decision. It needs explicit merge detail, policy reason, and evidence links so the user understands what they are approving.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-grid">
                                        ${summaryStat('Status', currentApproval().status, currentApproval().policy)}
                                        ${summaryStat('Conflict fields', `${currentApproval().conflictFields}`, currentApproval().autoMergeReady ? 'Auto merge available' : 'Manual only')}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Approve Promotion', 'approve_promotion', 'fa-solid fa-thumbs-up')}
                                        ${ghostButton('Accept Auto Merge', 'accept_auto_merge', 'fa-solid fa-code-merge')}
                                        ${ghostButton('Reject', 'reject_promotion', 'fa-solid fa-ban')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">3-way merge detail</h3>
                                            <p class="surface-section-subtitle">This page avoids reducing conflict resolution to a generic text explanation.</p>
                                        </div>
                                    </div>
                                    <div class="split-columns">
                                        <div class="compare-card">
                                            <h4>Base</h4>
                                            <ul>
                                                <li>Selector path: <code>Checkout.SubmitButton</code></li>
                                                <li>Quality profile risk: medium</li>
                                                <li>Scenario branch: official</li>
                                            </ul>
                                        </div>
                                        <div class="compare-card">
                                            <h4>Version branch</h4>
                                            <ul>
                                                <li>Selector path updated to <code>Checkout.ConfirmAction</code></li>
                                                <li>Quality profile risk elevated to high</li>
                                                <li>Candidate automation draft attached</li>
                                            </ul>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'releaseReadiness':
                return [
                    createMessage('agent', {
                        time: '12:18 PM',
                        html: `
                            <p style="margin:0 0 12px;">Release readiness deserves a dedicated page so quality leads can see score, blockers, open approvals, and unresolved execution problems in one place.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-grid">
                                        ${summaryStat('Score', `${state.release.score}`, 'Composite release score')}
                                        ${summaryStat('Blockers', `${state.release.blockers}`, state.release.executionHealth)}
                                        ${summaryStat('Open approvals', `${state.release.approvalsOpen}`, 'Promotion + capability')}
                                        ${summaryStat('Pending merge', `${state.release.pendingMerge}`, 'Conflict resolution required')}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Generate Release Advice', 'generate_release_advice', 'fa-solid fa-wand-magic-sparkles')}
                                        ${ghostButton('Submit Release Gate', 'submit_release_gate', 'fa-solid fa-paper-plane')}
                                        ${ghostButton('Open Approval Detail', 'open_approval_detail', 'fa-solid fa-arrow-right')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Blocking issues</h3>
                                            <p class="surface-section-subtitle">These should be visible without drilling into multiple pages.</p>
                                        </div>
                                    </div>
                                    <div class="surface-list">
                                        ${surfaceRow('RUN-9021 failed on web runner', 'Healing proposal not yet accepted', [miniChip('run blocker', 'bad')])}
                                        ${surfaceRow('Baseline Promotion #442 still waiting approval', 'Official system image cannot be updated yet', [miniChip('approval', 'warn')])}
                                        ${surfaceRow('One performance lane still waiting confirmation', 'Perf script generation has not been approved', [miniChip('governance', 'warn')])}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            case 'desktop':
                return [
                    createMessage('agent', {
                        time: '12:26 PM',
                        html: `
                            <p style="margin:0 0 12px;">Desktop is not a separate role. It is a project execution surface for the same users when work needs local permissions, file access, or device-scoped capabilities.</p>
                            <div class="surface-stack">
                                <div class="surface-section">
                                    <div class="surface-grid">
                                        ${summaryStat('Queue', `${state.desktop.queue.length}`, 'Pending + running local work')}
                                        ${summaryStat('Grants', `${state.desktop.grants.length}`, 'Scoped capabilities')}
                                        ${summaryStat('Sync', state.desktop.syncHealth, 'Device bridge status')}
                                        ${summaryStat('Linked Version', currentVersion().name, currentVersion().branch)}
                                    </div>
                                    <div class="surface-actions">
                                        ${ghostButton('Confirm Local Task', 'confirm_local_task', 'fa-solid fa-check')}
                                        ${ghostButton('Check Sync', 'check_sync', 'fa-solid fa-rotate')}
                                        ${ghostButton('Open Run Detail', 'open_run_detail', 'fa-solid fa-play')}
                                    </div>
                                </div>
                                <div class="surface-section">
                                    <div class="surface-section-header">
                                        <div>
                                            <h3 class="surface-section-title">Local queue</h3>
                                            <p class="surface-section-subtitle">Requests waiting on confirmation, active execution, and sync replay.</p>
                                        </div>
                                    </div>
                                    <div class="surface-list">
                                        ${state.desktop.queue.map((item) => surfaceRow(item.title, 'Desktop local task', [miniChip(item.status, item.status.includes('Needs') ? 'warn' : item.status === 'Running' ? 'info' : 'good')], item.status === 'Needs confirmation' ? `<button class="pill-chip primary" data-action="confirm_local_task"><i class="fa-solid fa-check"></i>Confirm</button>` : '')).join('')}
                                    </div>
                                </div>
                            </div>
                        `
                    })
                ];
            default:
                return [];
        }
    }

    function ensureConversation(viewId) {
        const key = conversationKey(viewId);
        if (!state.conversations[key]) {
            state.conversations[key] = seedConversation(viewId);
        }
    }

    function pushUserMessage(text) {
        ensureConversation(state.currentViewId);
        state.conversations[conversationKey()].push(createMessage('user', { text }));
    }

    function pushAgentMessage(html, name = 'Nasus Agent') {
        ensureConversation(state.currentViewId);
        state.conversations[conversationKey()].push(createMessage('agent', { name, html }));
    }

    function addGenericAgentResponse(text) {
        pushUserMessage(text);
        pushAgentMessage(`<div class="markdown-content"><p>I routed that request from the current conversation surface. The next step is to map it to a concrete tool invocation or navigation action in the real product.</p></div>`);
    }

    function renderSidebar() {
        const inWorkspace = isWorkspaceView();
        const project = currentProject();
        const version = currentVersion();
        const us = currentUs();

        const topNav = [
            ['build', 'fa-solid fa-hammer', 'Build'],
            ['dashboard', 'fa-solid fa-chart-line', 'Dashboard'],
            ['documentation', 'fa-solid fa-book-open', 'Documentation']
        ].map(([view, icon, label]) => `
            <button class="sidebar-nav-item ${state.currentViewId === view ? 'active' : ''}" data-view="${view}">
                <i class="${icon}"></i>
                ${label}
            </button>
        `).join('');

        if (inWorkspace) {
            sidebarNav.innerHTML = `
                <button class="sidebar-parent-link" data-action="open_dashboard">
                    <i class="fa-solid fa-chevron-left"></i>
                    Dashboard
                </button>
                <div class="workspace-context">
                    <div class="workspace-context-title">${project.name}</div>
                    <div class="workspace-context-meta">${version.name} · ${us.id} · ${project.baseline}</div>
                    <div class="workspace-context-badges">
                        <span class="workspace-badge"><i class="fa-solid fa-wave-square"></i>${project.overallRisk}</span>
                        <span class="workspace-badge"><i class="fa-solid fa-circle-nodes"></i>${project.modules} modules</span>
                        <span class="workspace-badge"><i class="fa-solid fa-flask-vial"></i>${project.tests} tests</span>
                    </div>
                </div>
                <div class="sidebar-section-label">Workspace</div>
                <button class="sidebar-nav-item ${state.currentViewId === 'projectOverview' ? 'active' : ''}" data-view="projectOverview">
                    <i class="fa-solid fa-layer-group"></i>
                    Project Overview
                </button>
                <button class="sidebar-nav-item ${state.currentViewId === 'versionSpace' || state.currentViewId === 'versionCreate' ? 'active' : ''}" data-view="versionSpace">
                    <i class="fa-solid fa-code-branch"></i>
                    Version Space
                </button>
                <button class="sidebar-nav-item ${state.currentViewId === 'personalWorkspace' ? 'active' : ''}" data-view="personalWorkspace">
                    <i class="fa-regular fa-user"></i>
                    Personal Workspace
                </button>
                <button class="sidebar-nav-item ${state.currentViewId === 'knowledgeGallery' || state.currentViewId === 'knowledgeDetail' ? 'active' : ''}" data-view="knowledgeGallery">
                    <i class="fa-solid fa-diagram-project"></i>
                    Knowledge
                </button>
                <button class="sidebar-nav-item ${state.currentViewId === 'runs' || state.currentViewId === 'runDetail' ? 'active' : ''}" data-view="runs">
                    <i class="fa-solid fa-play"></i>
                    Runs
                </button>
                <button class="sidebar-nav-item ${state.currentViewId === 'governance' || state.currentViewId === 'approvalDetail' || state.currentViewId === 'releaseReadiness' ? 'active' : ''}" data-view="governance">
                    <i class="fa-solid fa-stamp"></i>
                    Governance
                </button>
                <button class="sidebar-nav-item ${state.currentViewId === 'desktop' ? 'active' : ''}" data-view="desktop">
                    <i class="fa-solid fa-desktop"></i>
                    Desktop
                </button>
                <div class="sidebar-section-label">
                    Active US
                    <button style="background:none;border:none;color:var(--text-tertiary);cursor:pointer;font-size:11px;" class="tooltip" data-tip="Add US">
                        <i class="fa-solid fa-plus"></i>
                    </button>
                </div>
                ${Object.values(state.usItems).map((item) => `
                    <button class="us-item ${state.currentUsId === item.id ? 'active' : ''}" data-us="${item.id}">
                        <span class="us-dot ${item.risk === 'High' ? 'amber' : item.risk === 'Medium' ? 'gray' : 'green'}"></span>
                        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${item.id}: ${item.title}</span>
                    </button>
                `).join('')}
            `;
            return;
        }

        sidebarNav.innerHTML = `
            <div class="sidebar-section-label" style="padding-top:8px;">Studio</div>
            <button class="sidebar-nav-item ${state.currentViewId === 'welcome' ? 'active' : ''}" data-view="welcome">
                <i class="fa-solid fa-house"></i>
                Welcome
            </button>
            <div class="sidebar-section-label">Explore</div>
            ${topNav}
        `;
    }

    function renderHeader() {
        const meta = viewMeta(state.currentViewId);
        mainHeaderTitle.innerHTML = `
            <h1 style="margin:0;font-size:15px;font-weight:500;">${meta.title}</h1>
            ${meta.badge}
        `;
        panelHeaderTitle.textContent = meta.panelTitle;
        chatInput.placeholder = meta.placeholder;
    }

    function renderMessages() {
        ensureConversation(state.currentViewId);
        const messages = state.conversations[conversationKey()];
        chatMessages.innerHTML = `
            <div class="time-separator"><span>Today</span></div>
            ${messages.map(renderMessage).join('')}
            ${state.isWaitingForAgent ? createTypingMessage() : ''}
        `;
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function tabActive(viewId, tabId) {
        return state.panelTabs[viewId] === tabId ? 'active' : '';
    }

    function renderPanelTabs() {
        const tabs = PANEL_TABS[state.currentViewId] || [{ id: 'activity', label: 'Activity' }];
        panelTabsContainer.innerHTML = tabs.map((tab) => `
            <button class="panel-tab context-tab ${tabActive(state.currentViewId, tab.id)}" data-tab="${tab.id}">${tab.label}</button>
        `).join('');
    }

    function moduleItem(text, badgeText = '') {
        return `
            <div class="module-item">
                <div class="module-item-name"><i class="fa-solid fa-circle-nodes" style="color:var(--text-tertiary)"></i>${text}</div>
                ${badgeText ? `<span class="risk-badge medium">${badgeText}</span>` : ''}
            </div>
        `;
    }

    function panelActivity(items) {
        return `
            <div class="panel-section-label">Recent Activity</div>
            ${items.map((item) => `
                <div class="module-item">
                    <div class="module-item-name"><i class="fa-solid fa-clock-rotate-left" style="color:var(--text-tertiary)"></i>${item}</div>
                </div>
            `).join('')}
        `;
    }

    function renderPanelContent() {
        const tab = state.panelTabs[state.currentViewId];
        const project = currentProject();
        const version = currentVersion();
        const us = currentUs();
        const run = currentRun();
        const approval = currentApproval();
        const object = currentObject();

        const views = {
            welcome: {
                activity: panelActivity(['Platform opened', 'Payment System remains active', '2 versions need review']),
                tips: `
                    <div class="panel-section-label">Suggested Starts</div>
                    ${moduleItem('Create a project from conversation', 'agent')}
                    ${moduleItem('Use Build to start a new project', 'build')}
                    ${moduleItem('Use Dashboard to inspect active projects', 'ops')}
                `,
                status: `
                    <div class="panel-section-label">Platform Status</div>
                    ${moduleItem('Core services healthy', 'ok')}
                    ${moduleItem('SSE streaming connected', 'live')}
                    ${moduleItem('Desktop bridge available', 'edge')}
                `
            },
            build: {
                projects: `
                    <div class="panel-section-label">Build Readiness</div>
                    ${moduleItem('Create Project is the primary action', 'primary')}
                    ${moduleItem('Conversation-guided import supported', 'agent')}
                    ${moduleItem('System image init follows validation', 'flow')}
                `,
                imports: `
                    <div class="panel-section-label">Import Lanes</div>
                    ${moduleItem('Git repositories', 'git')}
                    ${moduleItem('US and PRD docs', 'docs')}
                    ${moduleItem('UX boards and screenshots', 'ux')}
                    ${moduleItem('Historical quality assets', 'qa')}
                `,
                health: `
                    <div class="panel-section-label">Setup Drafts</div>
                    ${state.buildDrafts.map((draft) => moduleItem(draft.title, 'draft')).join('')}
                `
            },
            dashboard: {
                alerts: `
                    <div class="panel-section-label">Alerts</div>
                    ${moduleItem('RUN-9021 still failed', 'high')}
                    ${moduleItem('APR-442 waiting approval', 'warn')}
                    ${moduleItem('1 local task needs confirmation', 'edge')}
                `,
                progress: `
                    <div class="panel-section-label">Progress</div>
                    ${moduleItem('2026Q2 Release · 74%', '74%')}
                    ${moduleItem('Hotfix 3.1 · 82%', '82%')}
                    ${moduleItem('Identity Hub OAuth Hardening · 62%', '62%')}
                `,
                activity: panelActivity(['Dashboard risk pulse refreshed', 'Governance backlog queried', 'Project health rollup updated'])
            },
            documentation: {
                topics: `
                    <div class="panel-section-label">Topics</div>
                    ${state.docs.map((doc) => moduleItem(doc.title, doc.category.toUpperCase())).join('')}
                `,
                templates: `
                    <div class="panel-section-label">Templates</div>
                    ${moduleItem('Project setup checklist', 'template')}
                    ${moduleItem('Version launch checklist', 'template')}
                    ${moduleItem('Release readiness summary', 'template')}
                `,
                updates: panelActivity(['Branching guide revised', 'Quality Asset Pack reference updated', 'Desktop execution page added'])
            },
            projectOverview: {
                context: `
                    <div class="panel-section-label">Project Context</div>
                    ${moduleItem(project.baseline, 'official')}
                    ${moduleItem(`${project.modules} modules indexed`, 'graph')}
                    ${moduleItem(`${project.tests} historical tests known`, 'qa')}
                `,
                versions: `
                    <div class="panel-section-label">Versions</div>
                    ${state.versions.map((item) => moduleItem(`${item.name} · ${item.branch}`, item.status.toUpperCase())).join('')}
                `,
                activity: panelActivity(['System image refreshed 1h ago', 'Version overlay active', 'No provider degradation detected'])
            },
            projectCreate: {
                context: `
                    <div class="panel-section-label">Setup Status</div>
                    ${moduleItem(`${state.createProject.repoCount} repos connected`, 'git')}
                    ${moduleItem(`${state.createProject.usDocs} docs loaded`, 'docs')}
                    ${moduleItem(`${state.createProject.uxBoards} boards linked`, 'ux')}
                `,
                assets: `
                    <div class="panel-section-label">Imported Assets</div>
                    ${moduleItem('Legacy smoke pack', 'qa')}
                    ${moduleItem('Regression suite snapshot', 'qa')}
                    ${moduleItem('Checkout board', 'ux')}
                `,
                activity: panelActivity(['Source validation completed', 'Import bundle staged', 'System image init waiting'])
            },
            versionSpace: {
                board: `
                    <div class="panel-section-label">US Board Pulse</div>
                    ${Object.values(state.usItems).map((item) => moduleItem(`${item.id} · ${item.owner}`, item.status.toUpperCase())).join('')}
                `,
                context: `
                    <div class="panel-section-label">Version Context</div>
                    ${moduleItem(version.branch, 'branch')}
                    ${moduleItem(`${version.pendingApprovals} open approvals`, 'warn')}
                    ${moduleItem(`${version.pendingMerge} pending merge`, 'warn')}
                `,
                activity: panelActivity(['US board refreshed', 'Version risk recomputed', 'Release readiness still blocked'])
            },
            versionCreate: {
                summary: `
                    <div class="panel-section-label">Branch Summary</div>
                    ${moduleItem(state.versionCreate.targetBranch, 'target')}
                    ${moduleItem(`${state.versionCreate.usImported} imported US`, 'us')}
                    ${moduleItem(state.versionCreate.baselineFork, 'fork')}
                `,
                owners: `
                    <div class="panel-section-label">Owner Assignment</div>
                    ${moduleItem('US-123 · You', 'assigned')}
                    ${moduleItem('US-128 · Mira', 'assigned')}
                    ${moduleItem('US-115 · Ari', 'assigned')}
                `,
                activity: panelActivity(['US import staged', 'Owner suggestion ready', 'Fork preview generated'])
            },
            personalWorkspace: {
                assets: `
                    <div class="panel-section-label">Asset Pack</div>
                    ${moduleItem(`Scenario Set · ${state.assetPack.scenariosDone}/${state.assetPack.scenarioTotal}`, 'draft')}
                    ${moduleItem(`Case Set · ${state.assetPack.casesDone}/${state.assetPack.casesTotal}`, 'draft')}
                    ${moduleItem(`Automation · ${state.assetPack.automationStatus}`, 'playwright')}
                    ${moduleItem(`Performance · ${state.assetPack.performanceStatus}`, 'gate')}
                `,
                context: `
                    <div class="panel-section-label">US Context</div>
                    ${moduleItem(`${us.id} · ${us.title}`, us.risk.toUpperCase())}
                    ${moduleItem(us.impact, 'impact')}
                    ${moduleItem(us.branch, 'branch')}
                `,
                activity: panelActivity(['US context refreshed', 'Scenarios ready for review', 'Run queued from current pack'])
            },
            knowledgeGallery: {
                graph: `
                    <div class="panel-section-label">Graph Nodes</div>
                    ${state.knowledge.objects.map((item) => moduleItem(`${item.name} · ${item.type}`, item.branch.toUpperCase())).join('')}
                `,
                branches: `
                    <div class="panel-section-label">Branch Tiers</div>
                    ${moduleItem('Official', 'trusted')}
                    ${moduleItem('Version Shared', 'working')}
                    ${moduleItem('Candidate', 'pending')}
                `,
                activity: panelActivity(['Object freshness updated', 'Candidate pack detected', 'One promotion recommendation queued'])
            },
            knowledgeDetail: {
                context: `
                    <div class="panel-section-label">Object Context</div>
                    ${moduleItem(object.name, object.type.toUpperCase())}
                    ${moduleItem(`Confidence ${object.confidence}`, 'score')}
                    ${moduleItem(`Branch ${object.branch}`, 'branch')}
                `,
                evidence: `
                    <div class="panel-section-label">Evidence</div>
                    ${object.evidence.map((item) => moduleItem(item, 'evidence')).join('')}
                `,
                history: panelActivity(['Object opened from gallery', 'Promotion advice prepared', 'Evidence lineage loaded'])
            },
            runs: {
                active: `
                    <div class="panel-section-label">Run Queue</div>
                    ${Object.values(state.runs).map((item) => moduleItem(`${item.id} · ${item.status}`, item.channel === 'Web Runner' ? 'web' : 'edge')).join('')}
                `,
                channels: `
                    <div class="panel-section-label">Channels</div>
                    ${moduleItem('Web Runner', 'shared')}
                    ${moduleItem('Desktop Local', 'device')}
                `,
                activity: panelActivity(['Run backlog refreshed', 'Healing threshold healthy', 'Evidence manifests available'])
            },
            runDetail: {
                evidence: `
                    <div class="panel-section-label">Artifacts</div>
                    ${moduleItem(`Trace · ${run.trace}`, 'trace')}
                    ${moduleItem(`${run.evidence} evidence items`, 'bundle')}
                    ${moduleItem(run.failure, 'failure')}
                `,
                trace: `
                    <div class="panel-section-label">Trace Context</div>
                    ${moduleItem(run.environment, 'env')}
                    ${moduleItem(run.channel, 'channel')}
                    ${moduleItem(run.healing, 'healing')}
                `,
                activity: panelActivity(['Failure fingerprint loaded', 'Trace bundle attached', 'Healing still pending'])
            },
            governance: {
                pending: `
                    <div class="panel-section-label">Pending Items</div>
                    ${Object.values(state.approvals).map((item) => moduleItem(item.title, item.status.toUpperCase())).join('')}
                `,
                policy: `
                    <div class="panel-section-label">Policy Gates</div>
                    ${moduleItem('Baseline promotion requires quality lead sign-off', 'policy')}
                    ${moduleItem('Desktop local execute requires user confirmation', 'policy')}
                `,
                activity: panelActivity(['Approval queue opened', 'Policy reason loaded', 'Release gate still blocked'])
            },
            approvalDetail: {
                diff: `
                    <div class="panel-section-label">Conflict Payload</div>
                    ${moduleItem('Selector path conflict', 'field')}
                    ${moduleItem('Risk level conflict', 'field')}
                    ${moduleItem('Auto merge available', 'safe')}
                `,
                policy: `
                    <div class="panel-section-label">Approval Policy</div>
                    ${moduleItem(approval.policy, 'required')}
                    ${moduleItem(approval.scope, 'scope')}
                `,
                activity: panelActivity(['Detail opened from governance queue', '3-way merge shown', 'No final resolution yet'])
            },
            releaseReadiness: {
                blockers: `
                    <div class="panel-section-label">Blockers</div>
                    ${moduleItem('RUN-9021 failed on web runner', 'run')}
                    ${moduleItem('APR-442 waiting approval', 'approval')}
                    ${moduleItem('Performance lane still pending', 'perf')}
                `,
                signals: `
                    <div class="panel-section-label">Signals</div>
                    ${moduleItem(`Score ${state.release.score}`, 'score')}
                    ${moduleItem(state.release.status, 'status')}
                    ${moduleItem(state.release.executionHealth, 'exec')}
                `,
                activity: panelActivity(['Release advice generated', 'Approval queue referenced', 'No gate submission accepted yet'])
            },
            desktop: {
                queue: `
                    <div class="panel-section-label">Local Queue</div>
                    ${state.desktop.queue.map((item) => moduleItem(item.title, item.status.toUpperCase())).join('')}
                `,
                grants: `
                    <div class="panel-section-label">Capability Grants</div>
                    ${state.desktop.grants.map((item) => moduleItem(item, 'grant')).join('')}
                `,
                sync: `
                    <div class="panel-section-label">Sync Health</div>
                    ${moduleItem(state.desktop.status, 'device')}
                    ${moduleItem(state.desktop.syncHealth, 'sync')}
                    ${moduleItem(currentVersion().name, 'version')}
                `
            }
        };

        panelContentContainer.innerHTML = views[state.currentViewId]?.[tab] || '';
    }

    function renderView(viewId) {
        state.currentViewId = viewId;
        ensureConversation(viewId);
        renderSidebar();
        renderHeader();
        renderMessages();
        renderPanelTabs();
        renderPanelContent();
    }

    function setProjectContext(projectId) {
        state.currentProjectId = projectId;
    }

    function invokeAction(action, payload = {}) {
        if (payload.project) setProjectContext(payload.project);
        if (payload.us) state.currentUsId = payload.us;
        if (payload.run) state.currentRunId = payload.run;
        if (payload.approval) state.currentApprovalId = payload.approval;
        if (payload.object) state.currentObjectId = payload.object;

        switch (action) {
            case 'open_welcome':
                renderView('welcome');
                return;
            case 'open_build':
                renderView('build');
                return;
            case 'open_dashboard':
                renderView('dashboard');
                return;
            case 'open_documentation':
                renderView('documentation');
                return;
            case 'open_project':
                renderView('projectOverview');
                return;
            case 'open_project_create':
                renderView('projectCreate');
                return;
            case 'open_version_space':
                renderView('versionSpace');
                return;
            case 'open_version_create':
                renderView('versionCreate');
                return;
            case 'open_us_workspace':
                renderView('personalWorkspace');
                return;
            case 'open_knowledge_gallery':
                renderView('knowledgeGallery');
                return;
            case 'open_knowledge_detail':
                renderView('knowledgeDetail');
                return;
            case 'open_runs':
                renderView('runs');
                return;
            case 'open_run_detail':
                renderView('runDetail');
                return;
            case 'open_governance':
                renderView('governance');
                return;
            case 'open_approval_detail':
                renderView('approvalDetail');
                return;
            case 'open_release_readiness':
                renderView('releaseReadiness');
                return;
            case 'open_desktop':
                renderView('desktop');
                return;
            case 'generate_scenarios':
                pushUserMessage(`Generate scenario coverage for ${currentUs().id}.`);
                pushAgentMessage('<div class="markdown-content"><p>I refreshed the scenario set and linked three risk-driven branches: promotion fallback, payment gateway retry, and receipt handoff consistency.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'agent_create_project':
                pushUserMessage('Help me create a new project.');
                pushAgentMessage(`
                    <div class="markdown-content">
                        <p>I can guide the setup. To create a project and initialize its system image, please provide:</p>
                        <ol style="margin:8px 0 0 18px;padding:0;">
                            <li>Git repository URLs</li>
                            <li>US / PRD documents</li>
                            <li>UX boards or screenshots</li>
                            <li>Historical tests or quality assets if available</li>
                        </ol>
                        <p style="margin-top:8px;">I will convert that into a structured project draft, validate the sources, and then prepare the initialization plan.</p>
                    </div>
                `, 'Nasus Setup Agent');
                renderView('build');
                return;
            case 'refresh_system_image':
                pushUserMessage('Refresh the current project system image and report the ingest delta.');
                currentProject().nextAction = 'System image refreshed just now';
                pushAgentMessage('<div class="markdown-content"><p>The system image refresh completed. I indexed 3 new modules, refreshed 2 outdated context objects, and detected 1 candidate relationship that should stay version-scoped until approval.</p></div>', 'Nasus Central Agent');
                renderView(state.currentViewId);
                return;
            case 'validate_project_inputs':
                pushUserMessage('Validate the current project inputs and provider connections.');
                state.createProject.validation = 'Validated';
                pushAgentMessage('<div class="markdown-content"><p>All project inputs validated successfully. Git access, document parsing, UX import, and historical asset ingestion are ready.</p></div>', 'Nasus Setup Agent');
                renderView(state.currentViewId);
                return;
            case 'import_project_assets':
                pushUserMessage('Import the connected project assets and prepare initialization.');
                state.createProject.import = 'Imported';
                pushAgentMessage('<div class="markdown-content"><p>The project assets were imported and normalized into raw asset references. You can initialize the Official System Image next.</p></div>', 'Nasus Setup Agent');
                renderView(state.currentViewId);
                return;
            case 'initialize_system_image':
                pushUserMessage('Initialize the Official System Image using the imported project assets.');
                state.createProject.systemImage = 'Initialized';
                pushAgentMessage('<div class="markdown-content"><p>The Official System Image branch is initialized. The project is now ready for version branching and US assignment.</p></div>', 'Nasus Setup Agent');
                renderView('build');
                return;
            case 'import_version_us':
                pushUserMessage('Import the latest US items into the draft version branch.');
                state.versionCreate.usImported = 10;
                pushAgentMessage('<div class="markdown-content"><p>I imported 2 additional US items and classified them by affected modules and historical risk patterns.</p></div>', 'Nasus Branch Agent');
                renderView(state.currentViewId);
                return;
            case 'assign_owners':
                pushUserMessage('Assign owners to the imported US items.');
                state.versionCreate.ownersAssigned = 8;
                pushAgentMessage('<div class="markdown-content"><p>Owner suggestions are ready. They balance component expertise, current workload, and blocker distribution.</p></div>', 'Nasus Branch Agent');
                renderView(state.currentViewId);
                return;
            case 'fork_baseline':
                pushUserMessage('Fork the baseline for the new version branch.');
                state.versionCreate.baselineFork = 'Forked';
                pushAgentMessage('<div class="markdown-content"><p>The version baseline was forked as a delta overlay. No full-copy duplication was required.</p></div>', 'Nasus Branch Agent');
                renderView(state.currentViewId);
                return;
            case 'create_version_branch':
                pushUserMessage('Create the version branch and activate the US board.');
                pushAgentMessage('<div class="markdown-content"><p>The version branch is active. US board, risk pulse, and asset pack generation are now available in Version Space.</p></div>', 'Nasus Branch Agent');
                renderView('versionSpace');
                return;
            case 'generate_version_risk':
                pushUserMessage('Summarize the current version risk and testing gaps.');
                pushAgentMessage('<div class="markdown-content"><p>The current version risk is elevated by one unresolved merge gate, one failed run, and one US item that still lacks performance coverage.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'dashboard_risk_query':
                pushUserMessage('Which project is currently the riskiest?');
                pushAgentMessage('<div class="markdown-content"><p><strong>Payment System</strong> is currently the riskiest project because it combines one failed run, one unresolved merge, and two open governance items in its active version.</p></div>');
                renderView('dashboard');
                return;
            case 'dashboard_blockers_query':
                pushUserMessage('Show me the currently blocked releases.');
                pushAgentMessage('<div class="markdown-content"><p>Two release trains need attention: <strong>2026Q2 Release</strong> is blocked by one failed run and one pending merge, and <strong>OAuth Hardening</strong> is blocked by a missing performance lane approval.</p></div>');
                renderView('dashboard');
                return;
            case 'analyze_object_impact':
                pushUserMessage(`Analyze the downstream impact of ${currentObject().name}.`);
                pushAgentMessage(`<div class="markdown-content"><p>${currentObject().name} affects ${currentObject().relations.slice(0, 2).join(', ')} and directly influences the current version risk because it is referenced by ${currentUs().id} and the active failed run.</p></div>`);
                renderView(state.currentViewId);
                return;
            case 'promote_candidate':
                pushUserMessage(`Prepare a promotion recommendation for ${currentObject().name}.`);
                pushAgentMessage('<div class="markdown-content"><p>I prepared a promotion recommendation. The object can move from Candidate to Version Shared, but it should not enter Official until the related baseline promotion approval is resolved.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'propose_healing':
                pushUserMessage(`Propose a healing patch for ${currentRun().id}.`);
                currentRun().healing = 'Proposed';
                pushAgentMessage('<div class="markdown-content"><p>I prepared a healing proposal that remaps the button selector from <code>#submit-payment</code> to the new checkout confirm action and adds a DOM fallback probe.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'retry_run':
                pushUserMessage(`Retry ${currentRun().id} with the updated healing proposal.`);
                currentRun().status = 'Reviewing';
                pushAgentMessage('<div class="markdown-content"><p>The retry was scheduled. The run is back in review with the healing proposal attached for verification.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'fallback_human':
                pushUserMessage(`Stop automated healing for ${currentRun().id} and escalate to human review.`);
                currentRun().status = 'Needs Human Review';
                pushAgentMessage('<div class="markdown-content"><p>The run was marked for manual review. This prevents repeated healing attempts from entering a token-burning loop.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'approve_promotion':
                pushUserMessage(`Approve ${currentApproval().title}.`);
                currentApproval().status = 'Approved';
                pushAgentMessage('<div class="markdown-content"><p>The promotion was approved and moved to the next governance step. Official baseline write-back is still gated by release closure.</p></div>', 'Nasus Policy Agent');
                renderView(state.currentViewId);
                return;
            case 'accept_auto_merge':
                pushUserMessage(`Accept the auto-merge suggestion for ${currentApproval().title}.`);
                currentApproval().status = 'Resolved';
                currentApproval().conflictFields = 0;
                pushAgentMessage('<div class="markdown-content"><p>The auto-merge suggestion was applied. Conflict fields are resolved, and the merged resolution is ready for final approval.</p></div>', 'Nasus Policy Agent');
                renderView(state.currentViewId);
                return;
            case 'reject_promotion':
                pushUserMessage(`Reject ${currentApproval().title}.`);
                currentApproval().status = 'Rejected';
                pushAgentMessage('<div class="markdown-content"><p>The promotion was rejected and sent back with an explanation so the version branch can revise its candidate knowledge or delta payload.</p></div>', 'Nasus Policy Agent');
                renderView(state.currentViewId);
                return;
            case 'generate_release_advice':
                pushUserMessage('Generate release advice for the current version.');
                state.release.score = 78;
                pushAgentMessage('<div class="markdown-content"><p>The release is conditionally ready. One failed run and one pending approval remain, but the quality signal is strong enough to prepare a release gate recommendation.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'submit_release_gate':
                pushUserMessage('Submit the release gate for review.');
                pushAgentMessage('<div class="markdown-content"><p>The release gate was submitted. Governance now has a complete readiness summary, blocker list, and linked evidence package.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'confirm_local_task':
                pushUserMessage('Confirm the top local desktop task.');
                if (state.desktop.queue[0]) state.desktop.queue[0].status = 'Running';
                pushAgentMessage('<div class="markdown-content"><p>The local task was confirmed. Desktop runtime is now collecting the requested artifacts and will sync the result back into the canonical run model.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'check_sync':
                pushUserMessage('Check the current desktop sync state.');
                pushAgentMessage('<div class="markdown-content"><p>Desktop sync is healthy. One local trace bundle is queued for upload and no replay conflicts were detected.</p></div>');
                renderView(state.currentViewId);
                return;
            case 'search_docs':
                renderView('documentation');
                return;
            default:
                addGenericAgentResponse(`Run action: ${action}`);
                renderView(state.currentViewId);
        }
    }

    function routeUserInput(text) {
        const lower = text.toLowerCase();
        if (lower.includes('build')) return renderView('build');
        if (lower.includes('dashboard')) return renderView('dashboard');
        if (lower.includes('documentation') || lower.includes('docs')) return renderView('documentation');
        if (lower.includes('create project') || lower.includes('new project')) return renderView('projectCreate');
        if (lower.includes('open project') || lower.includes('project workspace')) return renderView('projectOverview');
        if (lower.includes('create version') || lower.includes('version branch')) return renderView('versionCreate');
        if (lower.includes('version progress') || lower.includes('us board')) return renderView('versionSpace');
        if (lower.includes('scenario')) return invokeAction('generate_scenarios');
        if (lower.includes('run') && lower.includes('detail')) return renderView('runDetail');
        if (lower.includes('approval') || lower.includes('merge')) return renderView('approvalDetail');
        if (lower.includes('desktop') || lower.includes('sync')) return renderView('desktop');
        if (lower.includes('knowledge') || lower.includes('object')) return renderView('knowledgeGallery');
        if (lower.includes('release') && lower.includes('ready')) return renderView('releaseReadiness');
        addGenericAgentResponse(text);
        renderView(state.currentViewId);
    }

    function handleSend() {
        const text = chatInput.value.trim();
        if (!text || state.isWaitingForAgent) return;

        chatInput.value = '';
        chatInput.style.height = 'auto';
        sendBtn.setAttribute('disabled', 'true');
        state.isWaitingForAgent = true;
        renderView(state.currentViewId);

        setTimeout(() => {
            state.isWaitingForAgent = false;
            routeUserInput(text);
        }, 450);
    }

    document.body.addEventListener('click', (event) => {
        const navTarget = event.target.closest('.sidebar-nav-item[data-view]');
        if (navTarget) {
            renderView(navTarget.dataset.view);
            return;
        }

        const tabTarget = event.target.closest('.context-tab[data-tab]');
        if (tabTarget) {
            state.panelTabs[state.currentViewId] = tabTarget.dataset.tab;
            renderView(state.currentViewId);
            return;
        }

        const usTarget = event.target.closest('.us-item[data-us]');
        if (usTarget) {
            state.currentUsId = usTarget.dataset.us;
            renderView('personalWorkspace');
            return;
        }

        const actionTarget = event.target.closest('[data-action]');
        if (actionTarget) {
            invokeAction(actionTarget.dataset.action, {
                project: actionTarget.dataset.project,
                us: actionTarget.dataset.us,
                run: actionTarget.dataset.run,
                approval: actionTarget.dataset.approval,
                object: actionTarget.dataset.object,
                doc: actionTarget.dataset.doc
            });
        }
    });

    homeLink.addEventListener('click', () => renderView('welcome'));
    chatInput.addEventListener('focus', () => inputContainer.classList.add('focused'));
    chatInput.addEventListener('blur', () => inputContainer.classList.remove('focused'));
    chatInput.addEventListener('input', function onInput() {
        this.style.height = 'auto';
        this.style.height = `${this.scrollHeight}px`;
        if (this.value.trim().length > 0) sendBtn.removeAttribute('disabled');
        else sendBtn.setAttribute('disabled', 'true');
    });
    chatInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            handleSend();
        }
    });
    sendBtn.addEventListener('click', handleSend);

    renderView(state.currentViewId);
});
