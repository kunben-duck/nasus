document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const chatMessages = document.getElementById('chat-messages');
    const chatContainer = document.getElementById('chat-container');
    const inputContainer = document.getElementById('input-container');
    const mainHeaderTitle = document.querySelector('.main-header-title');
    const panelTabsContainer = document.querySelector('.panel-tab-group');
    const panelContentContainer = document.getElementById('panel-content');
    
    // --- State ---
    let isWaitingForAgent = false;
    let currentViewId = 'personal';

    // --- Mock Data for Views ---
    const VIEWS = {
        personal: {
            title: 'US-123 Quality Analysis',
            badgeHtml: '<span class="status-badge in-progress">In Progress</span>',
            chatHtml: `
                <div class="time-separator"><span>Today, 10:41 AM</span></div>
                <div class="message user message-in">
                    <img src="https://ui-avatars.com/api/?name=US&background=8ab4f8&color=131314&size=28" alt="User" class="message-avatar">
                    <div class="message-body">
                        <div class="message-meta"><span class="time">10:41 AM</span><span class="name">You</span></div>
                        <div class="message-bubble">Start processing US-123. Let's analyze its quality impact.</div>
                    </div>
                </div>
                <div class="message agent message-in">
                    <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                    <div class="message-body" style="flex:1;max-width:85%;">
                        <div class="message-meta"><span class="name">Nasus Agent</span><span class="time">10:42 AM</span></div>
                        <div class="message-bubble">
                            <p style="margin:0 0 12px;">I've loaded the context for <strong style="color:var(--text-primary)">US-123: Payment flow update</strong> and linked it with our <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--accent-blue);border:1px solid var(--border-subtle);font-family:monospace;">Official System Image Branch</code>.</p>
                            <div class="impact-card">
                                <div class="impact-card-header">
                                    <div class="impact-card-title"><i class="fa-solid fa-network-wired"></i> Code Impact Analysis</div>
                                    <span class="impact-card-badge">Computed</span>
                                </div>
                                <ul class="impact-list">
                                    <li><i class="fa-solid fa-check check"></i> Identifies changes in <code style="background:var(--bg-elevated);padding:1px 5px;border-radius:3px;font-size:11px;color:var(--text-primary);font-family:monospace;border:1px solid var(--border-subtle);">Checkout Module</code> core logic.</li>
                                    <li><i class="fa-solid fa-check check"></i> Detected interface modifications in <code style="background:var(--bg-elevated);padding:1px 5px;border-radius:3px;font-size:11px;color:var(--text-primary);font-family:monospace;border:1px solid var(--border-subtle);">Payment Gateway App</code>.</li>
                                    <li><i class="fa-solid fa-triangle-exclamation warning"></i> Warning: Associated legacy tests need updating.</li>
                                </ul>
                            </div>
                            <p style="margin:12px 0 0;">What would you like to do next for this US? We should generate the initial test scenarios.</p>
                            <div class="pill-chips" id="action-buttons">
                                <button class="pill-chip primary action-btn" data-action="generate_scenarios"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate Scenarios</button>
                                <button class="pill-chip"><i class="fa-solid fa-code-pull-request"></i> Review Linked PRs</button>
                            </div>
                        </div>
                    </div>
                </div>
            `,
            tabs: [
                { id: 'assets', label: 'Assets', active: true },
                { id: 'system', label: 'System', active: false },
                { id: 'runs', label: 'Runs', active: false }
            ],
            panels: {
                'assets': `
                    <div class="panel-section-label">Quality Asset Pack <span class="panel-section-badge drafting">Drafting</span></div>
                    <div class="asset-card">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><div class="asset-icon indigo"><i class="fa-solid fa-list-check"></i></div>Test Scenarios</div>
                            <span class="asset-card-status" id="scenario-status">0/5 Done</span>
                        </div>
                        <div class="asset-card-desc">Checkout validation, promotion application, and edge cases.</div>
                        <div class="asset-progress-bar"><div class="asset-progress-fill" id="scenario-progress" style="width: 0%"></div></div>
                    </div>
                    <div class="asset-card muted">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><div class="asset-icon green"><i class="fa-solid fa-vial"></i></div>Automation Scripts</div>
                            <span class="asset-card-status">Pending</span>
                        </div>
                        <div class="asset-card-desc">Awaiting scenarios completion. Playwright target.</div>
                    </div>
                    <div class="panel-spacer"></div>
                    <div class="panel-section-label">Governance</div>
                    <div class="governance-card">
                        <div class="governance-icon"><i class="fa-solid fa-stamp"></i></div>
                        <div class="governance-text"><h4>Release Decision</h4><span>Requires Execution</span></div>
                    </div>
                `,
                'system': `
                    <div class="system-baseline"><i class="fa-solid fa-code-merge system-baseline-bg"></i><div class="system-baseline-label">Active Baseline</div><div class="system-baseline-name">Official System Image Branch</div><div class="system-baseline-sync"><span class="pulse-dot"></span>Synced 2 mins ago</div></div>
                    <div class="panel-section-label">Affected Modules</div>
                    <div class="module-item"><div class="module-item-name"><i class="fa-regular fa-folder" style="color:var(--accent-blue)"></i>Checkout Module</div><span class="risk-badge high">HIGH RISK</span></div>
                    <div class="module-item"><div class="module-item-name"><i class="fa-brands fa-react" style="color:var(--accent-blue)"></i>Payment Gateway UI</div><span class="risk-badge medium">MED RISK</span></div>
                `,
                'runs': `
                    <div class="empty-state"><div class="empty-state-icon"><i class="fa-solid fa-play"></i></div><h3>No Active Runs</h3><p>Generate automation scripts and trigger execution to see results here.</p></div>
                `
            }
        },
        project: {
            title: 'Project Space: Payment System',
            badgeHtml: '<span class="status-badge" style="background:rgba(129,201,149,0.1);color:var(--accent-green);border:1px solid rgba(129,201,149,0.2);">Active</span>',
            chatHtml: `
                <div class="time-separator"><span>Today, 09:15 AM</span></div>
                <div class="message agent message-in">
                    <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                    <div class="message-body" style="flex:1;max-width:85%;">
                        <div class="message-meta"><span class="name">Nasus Central Agent</span><span class="time">09:15 AM</span></div>
                        <div class="message-bubble">
                            <p style="margin:0 0 12px;">Welcome to the <strong>Payment System</strong> Project Space. I'm currently monitoring the <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--text-primary);border:1px solid var(--border-subtle);font-family:monospace;">Official System Image</code>, which has indexed <strong>45 modules</strong> and <strong>1,204 tests</strong>.</p>
                            <p style="margin:0 0 12px;">There are <strong>2 active Version Branches</strong> running concurrently. How would you like to manage the project today?</p>
                            <div class="pill-chips" id="action-buttons">
                                <button class="pill-chip primary action-btn" data-action="init_baseline"><i class="fa-solid fa-rotate-right"></i> Refresh System Image</button>
                                <button class="pill-chip"><i class="fa-solid fa-code-branch"></i> Create Version Branch</button>
                            </div>
                        </div>
                    </div>
                </div>
            `,
            tabs: [
                { id: 'overview', label: 'Overview', active: true },
                { id: 'versions', label: 'Active Versions', active: false }
            ],
            panels: {
                'overview': `
                    <div class="panel-section-label">System Image Status</div>
                    <div class="system-baseline"><i class="fa-solid fa-layer-group system-baseline-bg"></i><div class="system-baseline-label">Official Baseline</div><div class="system-baseline-name">v1.4.2-stable</div><div class="system-baseline-sync"><span class="pulse-dot"></span>Synced 1 hr ago</div></div>
                    <div class="panel-spacer"></div>
                    <div class="panel-section-label">Platform Metrics</div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
                        <div style="padding:12px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:8px;">
                            <div style="font-size:10px;color:var(--text-tertiary);margin-bottom:4px;text-transform:uppercase;">Coverage</div>
                            <div style="font-size:18px;font-weight:600;color:var(--text-primary);">84.2%</div>
                        </div>
                        <div style="padding:12px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:8px;">
                            <div style="font-size:10px;color:var(--text-tertiary);margin-bottom:4px;text-transform:uppercase;">Total US</div>
                            <div style="font-size:18px;font-weight:600;color:var(--text-primary);">148</div>
                        </div>
                    </div>
                `,
                'versions': `
                    <div class="asset-card">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><div class="asset-icon indigo"><i class="fa-solid fa-code-branch"></i></div>2026Q2 Release</div>
                            <span class="asset-card-status">In Progress</span>
                        </div>
                        <div class="asset-card-desc">12 active US items. Expected completion: April 15.</div>
                    </div>
                    <div class="asset-card">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><div class="asset-icon green"><i class="fa-solid fa-code-branch"></i></div>Hotfix-3.1</div>
                            <span class="asset-card-status">Reviewing</span>
                        </div>
                        <div class="asset-card-desc">2 active US items. Urgent deployment.</div>
                    </div>
                `
            }
        },
        version: {
            title: 'Version Space: 2026Q2 Release',
            badgeHtml: '<span class="status-badge" style="background:rgba(138,180,248,0.1);color:var(--accent-blue);border:1px solid rgba(138,180,248,0.2);">Execution Phase</span>',
            chatHtml: `
                <div class="time-separator"><span>Yesterday, 14:20 PM</span></div>
                <div class="message agent message-in">
                    <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                    <div class="message-body" style="flex:1;max-width:85%;">
                        <div class="message-meta"><span class="name">Nasus Agent</span><span class="time">14:20 PM</span></div>
                        <div class="message-bubble">
                            <p style="margin:0 0 12px;">I've generated the risk summary for the <strong>2026Q2 Release</strong> branch.</p>
                            <div class="impact-card">
                                <div class="impact-card-header">
                                    <div class="impact-card-title"><i class="fa-solid fa-shield-halved"></i> Version Risk Assessment</div>
                                </div>
                                <ul class="impact-list">
                                    <li><i class="fa-solid fa-triangle-exclamation warning"></i> 2 US items lack automation coverage.</li>
                                    <li><i class="fa-solid fa-triangle-exclamation warning"></i> Dependency overlap detected between US-123 and US-128 (Payment Module).</li>
                                    <li><i class="fa-solid fa-check check"></i> Baseline divergence is within accepted threshold (4.2%).</li>
                                </ul>
                            </div>
                            <div class="pill-chips" id="action-buttons">
                                <button class="pill-chip primary action-btn" data-action="run_all"><i class="fa-solid fa-play"></i> Run All Asset Packs</button>
                                <button class="pill-chip"><i class="fa-solid fa-file-invoice"></i> Generate Release Readiness</button>
                            </div>
                        </div>
                    </div>
                </div>
            `,
            tabs: [
                { id: 'us-list', label: 'US Items', active: true },
                { id: 'risks', label: 'Risks', active: false }
            ],
            panels: {
                'us-list': `
                    <div class="panel-section-label">Top Priority US</div>
                    <div class="asset-card">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><span class="us-dot amber"></span>US-123</div>
                            <span class="asset-card-status">Drafting</span>
                        </div>
                        <div class="asset-card-desc">Payment flow update. (Assignee: You)</div>
                    </div>
                    <div class="asset-card">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><span class="us-dot gray"></span>US-128</div>
                            <span class="asset-card-status">Pending</span>
                        </div>
                        <div class="asset-card-desc">OAuth Resiliency improvements.</div>
                    </div>
                `,
                'risks': `
                    <div class="panel-section-label">Risk Vectors</div>
                    <div class="module-item"><div class="module-item-name"><i class="fa-solid fa-code" style="color:var(--text-tertiary)"></i>Coverage Gap</div><span class="risk-badge high">HIGH</span></div>
                    <div class="module-item"><div class="module-item-name"><i class="fa-solid fa-link" style="color:var(--text-tertiary)"></i>Conflict Potential</div><span class="risk-badge medium">MED</span></div>
                `
            }
        },
        gallery: {
            title: 'Knowledge Gallery',
            badgeHtml: '',
            chatHtml: `
                <div class="time-separator"><span>Today, 11:05 AM</span></div>
                <div class="message agent message-in">
                    <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                    <div class="message-body" style="flex:1;max-width:85%;">
                        <div class="message-meta"><span class="name">Nasus Agent</span><span class="time">11:05 AM</span></div>
                        <div class="message-bubble">
                            <p style="margin:0 0 12px;">You are freely exploring the <strong>Context Graph</strong>. I can query across <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--accent-purple);border:1px solid var(--border-subtle);font-family:monospace;">System Features</code>, <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--accent-purple);border:1px solid var(--border-subtle);font-family:monospace;">Test Assets</code>, and <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--accent-purple);border:1px solid var(--border-subtle);font-family:monospace;">Execution Evidence</code>.</p>
                            <p style="margin:0 0 12px;">Try asking me "What modules depend on the Auth Service?" or "Show me historical test failures for the Checkout Page".</p>
                        </div>
                    </div>
                </div>
            `,
            tabs: [
                { id: 'graph', label: 'Graph Explorer', active: true },
                { id: 'objects', label: 'Object Detail', active: false }
            ],
            panels: {
                'graph': `
                    <div class="empty-state">
                        <div class="empty-state-icon"><i class="fa-solid fa-project-diagram"></i></div>
                        <h3>Graph View</h3>
                        <p>Ask a question to visualize system relationships.</p>
                    </div>
                `,
                'objects': `
                    <div class="empty-state">
                        <div class="empty-state-icon"><i class="fa-solid fa-cube"></i></div>
                        <h3>Select a Context Object</h3>
                    </div>
                `
            }
        },
        runs: {
            title: 'Execution Runs',
            badgeHtml: '',
            chatHtml: `
                <div class="time-separator"><span>Today, 11:30 AM</span></div>
                <div class="message agent message-in">
                    <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                    <div class="message-body" style="flex:1;max-width:85%;">
                        <div class="message-meta"><span class="name">Nasus Agent</span><span class="time">11:30 AM</span></div>
                        <div class="message-bubble">
                            <p style="margin:0 0 12px;">I'm monitoring the Automation Service. The most recent execution <code style="background:var(--bg-elevated);padding:2px 6px;border-radius:4px;font-size:12px;color:var(--accent-red);border:1px solid var(--border-subtle);font-family:monospace;">Run-9021</code> encountered a failure in the Web Runner.</p>
                            <div class="impact-card">
                                <div class="impact-card-header">
                                    <div class="impact-card-title"><i class="fa-solid fa-bug" style="color:var(--accent-red);"></i> Failure Analysis</div>
                                </div>
                                <ul class="impact-list">
                                    <li><i class="fa-solid fa-xmark" style="color:var(--accent-red);margin-top:2px;"></i> Locator mismatch on <code style="background:var(--bg-elevated);padding:1px 5px;border-radius:3px;font-size:11px;color:var(--text-primary);font-family:monospace;border:1px solid var(--border-subtle);">#submit-payment</code> button.</li>
                                    <li><i class="fa-solid fa-info-circle check"></i> The DOM structure likely changed in PR #882.</li>
                                </ul>
                            </div>
                            <div class="pill-chips" id="action-buttons">
                                <button class="pill-chip primary action-btn" data-action="propose_healing"><i class="fa-solid fa-notes-medical"></i> Propose Healing Patch</button>
                                <button class="pill-chip"><i class="fa-solid fa-desktop"></i> View Playwright Trace</button>
                            </div>
                        </div>
                    </div>
                </div>
            `,
            tabs: [
                { id: 'active', label: 'Active Runs', active: true },
                { id: 'history', label: 'History', active: false }
            ],
            panels: {
                'active': `
                    <div class="panel-section-label">Current Execution</div>
                    <div class="asset-card">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><div class="asset-icon indigo"><i class="fa-solid fa-robot"></i></div>Run-9021</div>
                            <span class="asset-card-status" style="color:var(--accent-red); border-color:rgba(242,139,130,0.3); background:rgba(242,139,130,0.1);">Failed</span>
                        </div>
                        <div class="asset-card-desc">Source: US-115 Automation Pack.<br/>Channel: Web Runner</div>
                    </div>
                `,
                'history': `
                    <div class="asset-card muted">
                        <div class="asset-card-header">
                            <div class="asset-card-title"><div class="asset-icon green"><i class="fa-solid fa-robot"></i></div>Run-9020</div>
                            <span class="asset-card-status">Passed</span>
                        </div>
                        <div class="asset-card-desc">Source: Regression Pack.</div>
                    </div>
                `
            }
        },
        approvals: {
            title: 'Governance & Approvals',
            badgeHtml: '<span class="status-badge" style="background:rgba(197,138,249,0.1);color:var(--accent-purple);border:1px solid rgba(197,138,249,0.2);">2 Pending</span>',
            chatHtml: `
                <div class="time-separator"><span>Today, 12:00 PM</span></div>
                <div class="message agent message-in">
                    <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                    <div class="message-body" style="flex:1;max-width:85%;">
                        <div class="message-meta"><span class="name">Nasus Policy Agent</span><span class="time">12:00 PM</span></div>
                        <div class="message-bubble">
                            <p style="margin:0 0 12px;">There is a high-risk PR merge request that requires human approval based on our Governance policies. The code modifies the authentication mechanism.</p>
                            <div class="impact-card">
                                <div class="impact-card-header">
                                    <div class="impact-card-title"><i class="fa-solid fa-scale-balanced" style="color:var(--accent-purple);"></i> Policy Review #442</div>
                                </div>
                                <ul class="impact-list">
                                    <li><i class="fa-solid fa-circle-info check"></i> <strong>Trigger:</strong> Baseline promotion request.</li>
                                    <li><i class="fa-solid fa-circle-info check"></i> <strong>Scope:</strong> Version Branch 2026Q2 -> Official System Image.</li>
                                </ul>
                            </div>
                            <div class="pill-chips" id="action-buttons">
                                <button class="pill-chip primary action-btn" data-action="approve_merge"><i class="fa-solid fa-thumbs-up"></i> Approve Promotion</button>
                                <button class="pill-chip"><i class="fa-solid fa-eye"></i> View Delta</button>
                            </div>
                        </div>
                    </div>
                </div>
            `,
            tabs: [
                { id: 'pending', label: 'Pending Reviews', active: true },
                { id: 'activity', label: 'Activity Log', active: false }
            ],
            panels: {
                'pending': `
                    <div class="governance-card" style="margin-bottom:10px;">
                        <div class="governance-icon" style="color:var(--accent-purple);background:rgba(197,138,249,0.1); border-color:rgba(197,138,249,0.2);"><i class="fa-solid fa-code-merge"></i></div>
                        <div class="governance-text"><h4>Baseline Promotion #442</h4><span>Requires Quality Lead Sign-off</span></div>
                    </div>
                    <div class="governance-card">
                        <div class="governance-icon"><i class="fa-solid fa-shield"></i></div>
                        <div class="governance-text"><h4>Desktop Local Capability</h4><span>Device Local Runtime Request</span></div>
                    </div>
                `,
                'activity': `
                    <div class="empty-state">
                        <div class="empty-state-icon"><i class="fa-solid fa-list"></i></div>
                        <h3>No Recent Activity</h3>
                    </div>
                `
            }
        }
    };

    // --- Render Engine ---
    function renderView(viewId) {
        const viewData = VIEWS[viewId];
        if (!viewData) return;

        currentViewId = viewId;

        // 1. Update Navigation Select State
        document.querySelectorAll('.sidebar-nav-item, .us-item').forEach(el => el.classList.remove('active'));
        if (viewId === 'personal') {
            document.getElementById('nav-personal').classList.add('active');
            document.getElementById('us-123-btn').classList.add('active');
        } else {
            const navBtn = document.getElementById('nav-' + viewId);
            if (navBtn) navBtn.classList.add('active');
        }

        // 2. Update Header
        mainHeaderTitle.innerHTML = `<h1 style="margin:0;font-size:15px;font-weight:500;">${viewData.title}</h1>${viewData.badgeHtml}`;

        // 3. Update Chat Content
        chatMessages.innerHTML = viewData.chatHtml;
        chatContainer.scrollTo({ top: chatContainer.scrollHeight });
        
        // 4. Update Right Panel Tabs
        panelTabsContainer.innerHTML = viewData.tabs.map(tab => 
            `<button class="panel-tab context-tab ${tab.active ? 'active' : ''}" data-tab="${tab.id}">${tab.label}</button>`
        ).join('');

        // 5. Update Right Panel Content
        panelContentContainer.innerHTML = Object.entries(viewData.panels).map(([id, html]) => 
            `<div id="tab-${id}" style="display:${viewData.tabs.find(t => t.id === id).active ? 'block' : 'none'};">${html}</div>`
        ).join('');

        // Reattach Listeners
        attachTabListeners();
        attachActionListeners();
    }

    // --- Interaction Listeners ---
    function attachTabListeners() {
        const tabs = document.querySelectorAll('.context-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                
                const targetId = 'tab-' + tab.dataset.tab;
                panelContentContainer.querySelectorAll(':scope > div').forEach(div => {
                    div.style.display = (div.id === targetId) ? 'block' : 'none';
                });
            });
        });
    }

    function attachActionListeners() {
        const actionButtons = document.querySelectorAll('.action-btn');
        actionButtons.forEach(btn => {
            btn.addEventListener('click', function() {
                const action = this.dataset.action;
                let text = '';
                if (action === 'generate_scenarios' && currentViewId === 'personal') {
                    text = "Please generate test scenarios for the checkout module changes.";
                } else if (action === 'init_baseline' && currentViewId === 'project') {
                    text = "Initiate a full sync of the System Image Baseline from the main repository.";
                } else if (action === 'run_all' && currentViewId === 'version') {
                    text = "Trigger execution runs for all approved Asset Packs in this version.";
                } else if (action === 'propose_healing' && currentViewId === 'runs') {
                    text = "Propose a healing patch for the locator mismatch on the checkout button.";
                } else if (action === 'approve_merge' && currentViewId === 'approvals') {
                    text = "I approve Baseline Promotion request #442.";
                }
                
                if (text) {
                    chatInput.value = text;
                    handleSend();
                }
            });
        });
    }

    // Sidebar Navigation Listnerers
    document.querySelectorAll('.sidebar-nav-item').forEach(item => {
        item.addEventListener('click', function() {
            const viewId = this.dataset.view;
            if (viewId && VIEWS[viewId]) {
                renderView(viewId);
            }
        });
    });

    // US Item listener
    const usBtn = document.getElementById('us-123-btn');
    if (usBtn) {
        usBtn.addEventListener('click', () => renderView('personal'));
    }

    // --- Input Chat logic ---
    chatInput.addEventListener('focus', () => inputContainer.classList.add('focused'));
    chatInput.addEventListener('blur', () => inputContainer.classList.remove('focused'));

    chatInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if(this.value.trim().length > 0) sendBtn.removeAttribute('disabled');
        else sendBtn.setAttribute('disabled', 'true');
    });

    chatInput.addEventListener('keydown', function(e) {
        if(e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    });

    sendBtn.addEventListener('click', handleSend);

    function handleSend() {
        const text = chatInput.value.trim();
        if(!text || isWaitingForAgent) return;

        chatInput.value = '';
        chatInput.style.height = 'auto';
        sendBtn.setAttribute('disabled', 'true');

        const container = document.getElementById('action-buttons');
        if(container) { container.style.opacity = '0.4'; container.style.pointerEvents = 'none'; }

        appendUserMessage(text);
        chatInput.setAttribute('disabled', 'true');
        isWaitingForAgent = true;

        const typingId = appendTypingIndicator();

        setTimeout(() => {
            const el = document.getElementById(typingId);
            if(el) el.remove();
            generateDynamicAgentResponse(text);
        }, 1200);
    }

    // --- Dynamic Agent Message ---
    function appendUserMessage(text) {
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        chatMessages.insertAdjacentHTML('beforeend', `
            <div class="message user message-in">
                <img src="https://ui-avatars.com/api/?name=US&background=8ab4f8&color=131314&size=28" alt="User" class="message-avatar">
                <div class="message-body">
                    <div class="message-meta"><span class="time">${time}</span><span class="name">You</span></div>
                    <div class="message-bubble">${escapeHtml(text)}</div>
                </div>
            </div>
        `);
        chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
    }

    function appendTypingIndicator() {
        const id = 'typing-' + Date.now();
        chatMessages.insertAdjacentHTML('beforeend', `
            <div id="${id}" class="message agent message-in">
                <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                <div class="message-body"><div style="padding:4px 0;display:flex;align-items:center;"><div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div></div>
            </div>
        `);
        chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
        return id;
    }

    function generateDynamicAgentResponse(userText) {
        let contentHtml = '';
        
        // Very basic mock responses depending on the view
        if (currentViewId === 'personal') {
            contentHtml = `
                <div class="markdown-content">
                    <p>I have generated 5 core test scenarios for the <strong>Checkout Module</strong> based on the system image rules and recent changes. These cover both positive flows and edge cases related to the payment gateway update.</p>
                </div>
                <div class="impact-card" style="margin:12px 0 16px;">
                    <div class="impact-card-header" style="border-bottom:1px solid var(--border-subtle);margin:-12px -12px 10px;padding:8px 12px;">
                        <span style="font-size:12px;font-weight:500;color:var(--text-primary);display:flex;align-items:center;gap:6px;"><i class="fa-solid fa-list-ul" style="color:#818cf8;"></i> Generated Scenarios</span>
                    </div>
                    <div style="font-size:12px;">
                        <div style="padding:6px 0;border-bottom:1px solid var(--border-subtle);display:flex;gap:8px;color:var(--text-secondary);"><span style="color:var(--text-tertiary);font-family:monospace;">#1</span> Verify successful payment flow with valid credit card credentials.</div>
                        <div style="padding:6px 0;display:flex;gap:8px;color:var(--text-secondary);"><span style="color:var(--text-tertiary);font-family:monospace;">#2</span> Verify fallback logic when primary payment gateway times out.</div>
                    </div>
                </div>
                <div class="pill-chips" style="margin-top:12px;">
                    <button class="pill-chip primary" onclick="document.getElementById('chat-input').value='Generate Playwright scripts'; document.getElementById('chat-input').dispatchEvent(new Event('input'))"><i class="fa-solid fa-file-code"></i> Generate Scripts</button>
                </div>
            `;
            // Trigger UI update in right panel if available
            setTimeout(() => {
                const progress = document.getElementById('scenario-progress');
                const status = document.getElementById('scenario-status');
                if(progress) progress.style.width = '100%';
                if(status) {
                    status.innerText = '5/5 Done';
                    status.style.background = 'rgba(99,102,241,0.15)';
                    status.style.color = '#818cf8';
                    status.style.borderColor = 'rgba(99,102,241,0.3)';
                }
            }, 500);
        } else {
             contentHtml = `
                <div class="markdown-content">
                    <p>Understood. Executing Tool Invocation Plan...</p>
                    <p>Update successful based on your instruction.</p>
                </div>
             `;
        }

        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        chatMessages.insertAdjacentHTML('beforeend', `
            <div class="message agent message-in">
                <div class="agent-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg></div>
                <div class="message-body" style="flex:1;max-width:85%;">
                    <div class="message-meta"><span class="name">Nasus Agent</span><span class="time">${time}</span></div>
                    <div class="message-bubble">${contentHtml}</div>
                </div>
            </div>
        `);
        
        chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: 'smooth' });
        chatInput.removeAttribute('disabled');
        chatInput.focus();
        isWaitingForAgent = false;
    }

    function escapeHtml(text) {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    // --- Initialize default view ---
    renderView('personal');

});
