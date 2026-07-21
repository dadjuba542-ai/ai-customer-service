/* ===== View Switching ===== */
function switchView(view) {
  if (state.currentView === view) return;
  if (view !== 'chat' && speechBusy()) cancelVoiceInput();
  state.currentView = view;
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(`${view}-view`).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelector(`.nav-item[data-view="${view}"]`)?.classList.add('active');
  if (view === 'chat') {
    if (state.messages.length > 0) renderMessages();
    if (state.isTyping) showWaitingPanel();
    updateVoiceButton();
    scrollToBottom();
    focusInput();
  }
  if (view === 'community') loadQA();
  if (view === 'products') loadProducts();
  if (view === 'discover') loadDiscover();
  if (view !== 'discover') stopCarouselAuto();
}

function focusInput() {
  setTimeout(() => document.getElementById('message-input').focus(), 100);
}



/* ===== Agent Tab Drag Support ===== */
function initAgentTabDrag() {
  const container = document.getElementById('agent-tabs');
  if (!container) return;

  let isDragging = false;
  let startX = 0;
  let startScrollLeft = 0;
  let holdTimer = null;
  let dragActive = false;

  function canScroll() {
    return container.scrollWidth > container.clientWidth;
  }

  container.addEventListener('pointerdown', (e) => {
    if (!canScroll()) return;
    startX = e.clientX;
    startScrollLeft = container.scrollLeft;
    isDragging = false;
    dragActive = false;

    clearTimeout(holdTimer);
    holdTimer = setTimeout(() => {
      isDragging = true;
      dragActive = true;
      container.style.cursor = 'grabbing';
    }, 200);
  });

  container.addEventListener('pointermove', (e) => {
    if (!canScroll()) return;
    const dx = e.clientX - startX;
    
    if (Math.abs(dx) > 5) {
      clearTimeout(holdTimer);
      isDragging = true;
      dragActive = true;
      container.style.cursor = 'grabbing';
    }
    
    if (isDragging) {
      container.scrollLeft = startScrollLeft - dx;
    }
  });

  container.addEventListener('pointerup', (e) => {
    clearTimeout(holdTimer);
    container.style.cursor = 'grab';
    dragActive = false;
    isDragging = false;
  });

  container.addEventListener('pointercancel', () => {
    clearTimeout(holdTimer);
    container.style.cursor = 'grab';
    dragActive = false;
    isDragging = false;
  });

  container.addEventListener('click', (e) => {
    if (dragActive) {
      e.stopPropagation();
      e.preventDefault();
    }
  }, true);
}

/* ===== Agent Tabs ===== */
function renderAgentTabs() {
  const container = document.getElementById('agent-tabs');
  container.innerHTML = AGENTS.map(a => `
    <button class="agent-tab ${a.id === state.activeAgentId ? 'active' : ''}"
      onclick="switchAgent('${a.id}')"
      style="${a.id === state.activeAgentId ? `background:${a.color}` : ''}">
      <i class="ph ph-${a.icon}"></i> ${a.name}
    </button>
  `).join('');
  updateChatAgentInfo();
}

function switchAgent(id) {
  if (hasOpenHandoffSession()) {
    state.handoff.isNutritionMode = true;
    updateHandoffUi();
    showToast('人工咨询进行中，结束后才能切换 AI', 'info');
    return;
  }
  state.handoff.isNutritionMode = false;
  updateHandoffUi();
  state.activeAgentId = id;
  renderAgentTabs();
  const agent = AGENTS.find(a => a.id === id);
  if (agent) {
    const msg = agent.chatDesc
      ? `<div class="sb-title">已切换到「${agent.name}」</div><div class="sb-desc">${agent.chatDesc}</div>`
      : `<div class="sb-title">已切换到「${agent.name}」</div>`;
    replaceSystemMessage(msg);
  }
}

function updateChatAgentInfo() {
  const agent = AGENTS.find(a => a.id === state.activeAgentId);
  const humanActive = state.handoff.session?.service_mode !== 'message'
    && state.handoff.session?.status === 'active';
  const name = humanActive ? '在线营养师' : (agent?.name || '在线营养师');
  document.getElementById('chat-agent-name').innerHTML = `${name} <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${state.isStreaming ? '#10B981' : '#CBD5E1'};animation:pulse-dot 2s infinite"></span>`;
}

/* ===== Quick Functions ===== */
function renderQuickFunctions() {
  const grid = document.getElementById('quick-grid');
  const homeAgents = HOME_AGENT_IDS
    .map(id => AGENTS.find(agent => agent.id === id))
    .filter(Boolean);
  grid.innerHTML = homeAgents.map(a => `
    <button class="quick-card" onclick="quickSend('${a.id}')">
      <div class="quick-card-icon" style="background:${a.color}"><i class="ph ph-${a.icon}"></i></div>
      <div class="quick-card-text">
        <div class="quick-card-title">${a.name}</div>
        <div class="quick-card-desc">${getAgentDesc(a.id)}</div>
      </div>
    </button>
  `).join('');
}

function getAgentDesc(agentId) {
  const agent = AGENTS.find(a => a.id === agentId);
  return agent ? agent.description : '';
}

function quickSend(agentId, text) {
  if (hasOpenHandoffSession()) {
    state.handoff.isNutritionMode = true;
    switchView('chat');
    updateHandoffUi();
    showToast('人工咨询进行中，当前消息仍将发送给营养师', 'info');
    focusInput();
    return;
  }
  state.handoff.isNutritionMode = false;
  updateHandoffUi();
  state.activeAgentId = agentId;
  renderAgentTabs();
  if (text) {
    document.getElementById('message-input').value = text;
    switchView('chat');
    sendMessage();
  } else {
    switchView('chat');
    const agent = AGENTS.find(a => a.id === agentId);
    const msg = agent && agent.chatDesc
      ? `<div class="sb-text"><div class="sb-title">已切换到「${agent.name}」</div><div class="sb-desc">${agent.chatDesc}</div></div>`
      : `<div class="sb-title">已切换到「${agent ? agent.name : agentId}」</div>`;
    replaceSystemMessage(msg);
  }
}
