document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const chatMessages = document.getElementById('chat-messages');
    const chatContainer = document.getElementById('chat-container');
    const inputContainer = document.getElementById('input-container');
    
    const contextTabs = document.querySelectorAll('.context-tab');
    const tabContents = {
        'assets': document.getElementById('tab-assets'),
        'system': document.getElementById('tab-system'),
        'runs': document.getElementById('tab-runs')
    };

    const actionButtons = document.querySelectorAll('.action-btn');

    // --- State ---
    let isWaitingForAgent = false;
    let step = 0;

    // --- Tab Logic (Right Panel) ---
    contextTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            contextTabs.forEach(t => {
                t.classList.remove('active');
            });
            tab.classList.add('active');
            
            Object.values(tabContents).forEach(content => {
                content.style.display = 'none';
            });
            
            const target = tab.dataset.tab;
            if(tabContents[target]) {
                tabContents[target].style.display = '';
            }
        });
    });

    // --- Input Focus Effect (Gradient Border) ---
    chatInput.addEventListener('focus', () => {
        inputContainer.classList.add('focused');
    });
    chatInput.addEventListener('blur', () => {
        inputContainer.classList.remove('focused');
    });

    // --- Auto Resize Textarea ---
    chatInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        
        if(this.value.trim().length > 0) {
            sendBtn.removeAttribute('disabled');
        } else {
            sendBtn.setAttribute('disabled', 'true');
        }
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

        removeActionButtons();
        appendUserMessage(text);
        
        chatInput.setAttribute('disabled', 'true');
        isWaitingForAgent = true;

        const typingId = appendTypingIndicator();

        setTimeout(() => {
            removeElement(typingId);
            generateAgentResponse(text);
        }, 1500);
    }

    // --- Action Button Handlers ---
    actionButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            if(this.dataset.action === 'generate_scenarios') {
                const text = "Please generate test scenarios for the checkout module changes.";
                chatInput.value = text;
                handleSend();
            }
        });
    });

    function removeActionButtons() {
        const container = document.getElementById('action-buttons');
        if(container) {
            container.style.opacity = '0.4';
            container.style.pointerEvents = 'none';
        }
    }

    // --- Message Appenders ---
    function appendUserMessage(text) {
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        const msgHtml = `
            <div class="message user message-in">
                <img src="https://ui-avatars.com/api/?name=US&background=8ab4f8&color=131314&size=28" alt="User" class="message-avatar">
                <div class="message-body">
                    <div class="message-meta">
                        <span class="time">${time}</span>
                        <span class="name">You</span>
                    </div>
                    <div class="message-bubble">
                        ${escapeHtml(text)}
                    </div>
                </div>
            </div>
        `;
        chatMessages.insertAdjacentHTML('beforeend', msgHtml);
        scrollToBottom();
    }

    function appendTypingIndicator() {
        const id = 'typing-' + Date.now();
        const html = `
            <div id="${id}" class="message agent message-in">
                <div class="agent-avatar">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg>
                </div>
                <div class="message-body">
                    <div style="padding:4px 0;display:flex;align-items:center;">
                        <div class="typing-dots">
                            <div class="typing-dot"></div>
                            <div class="typing-dot"></div>
                            <div class="typing-dot"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        chatMessages.insertAdjacentHTML('beforeend', html);
        scrollToBottom();
        return id;
    }

    function generateAgentResponse(userText) {
        let contentHtml = '';
        
        if(step === 0) {
            contentHtml = `
                <div class="markdown-content">
                    <p>I have generated 5 core test scenarios for the <strong>Checkout Module</strong> based on the system image rules and recent changes. These cover both positive flows and edge cases related to the payment gateway update.</p>
                </div>
                
                <div class="impact-card" style="margin:12px 0 16px;">
                    <div class="impact-card-header" style="border-bottom:1px solid var(--border-subtle);margin:-12px -12px 10px;padding:8px 12px;">
                        <span style="font-size:12px;font-weight:500;color:var(--text-primary);display:flex;align-items:center;gap:6px;">
                            <i class="fa-solid fa-list-ul" style="color:#818cf8;"></i> Generated Scenarios
                        </span>
                        <button style="font-size:10px;background:var(--bg-elevated);padding:4px 8px;border-radius:4px;border:1px solid var(--border-subtle);color:var(--text-secondary);cursor:pointer;">Review Full List</button>
                    </div>
                    <div style="font-size:12px;">
                        <div style="padding:6px 0;border-bottom:1px solid var(--border-subtle);display:flex;gap:8px;color:var(--text-secondary);">
                            <span style="color:var(--text-tertiary);font-family:monospace;">#1</span>
                            Verify successful payment flow with valid credit card credentials.
                        </div>
                        <div style="padding:6px 0;display:flex;gap:8px;color:var(--text-secondary);">
                            <span style="color:var(--text-tertiary);font-family:monospace;">#2</span>
                            Verify fallback logic when primary payment gateway times out.
                        </div>
                    </div>
                    <div style="margin:8px -12px -12px;padding:6px 12px;border-top:1px solid var(--border-subtle);text-align:center;font-size:10px;color:var(--text-tertiary);">
                        + 3 more scenarios
                    </div>
                </div>

                <div class="markdown-content">
                    <p>I have saved these to the <strong>Quality Asset Pack</strong>. Should I proceed to generate the automated Playwright scripts for these?</p>
                </div>

                <div class="pill-chips" style="margin-top:12px;">
                    <button class="pill-chip primary" onclick="document.getElementById('chat-input').value='Yes, generate the Playwright scripts'; document.getElementById('chat-input').dispatchEvent(new Event('input'))">
                        <i class="fa-solid fa-file-code"></i> Generate Automation Scripts
                    </button>
                </div>
            `;
            
            // Update sidebar progress
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
            }, 600);
            
            step++;
        } else {
            contentHtml = `
                <div class="markdown-content">
                    <p>I am generating the Playwright automation scripts...</p>
                    <p>The scripts use our <code>checkout-page</code> Page Object Model as defined in the official baseline.</p>
                </div>
            `;
        }

        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        const msgHtml = `
            <div class="message agent message-in">
                <div class="agent-avatar">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="currentColor"/></svg>
                </div>
                <div class="message-body" style="flex:1;max-width:85%;">
                    <div class="message-meta">
                        <span class="name">Nasus Agent</span>
                        <span class="time">${time}</span>
                    </div>
                    <div class="message-bubble">
                        ${contentHtml}
                    </div>
                </div>
            </div>
        `;
        
        chatMessages.insertAdjacentHTML('beforeend', msgHtml);
        scrollToBottom();
        
        chatInput.removeAttribute('disabled');
        chatInput.focus();
        isWaitingForAgent = false;
    }

    function removeElement(id) {
        const el = document.getElementById(id);
        if(el) el.remove();
    }

    function scrollToBottom() {
        chatContainer.scrollTo({
            top: chatContainer.scrollHeight,
            behavior: 'smooth'
        });
    }

    function escapeHtml(unsafe) {
        return unsafe
             .replace(/&/g, "&amp;")
             .replace(/</g, "&lt;")
             .replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;")
             .replace(/'/g, "&#039;");
    }

    // --- Sidebar nav active state ---
    document.querySelectorAll('.sidebar-nav-item').forEach(item => {
        item.addEventListener('click', function() {
            document.querySelectorAll('.sidebar-nav-item').forEach(i => i.classList.remove('active'));
            this.classList.add('active');
        });
    });
    
    // Initial scroll setup
    setTimeout(scrollToBottom, 100);
});
