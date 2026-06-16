const API_BASE = '';

const FALLBACK_AGENTS = [
  { id: 'aura', name: '产品资料查询', type: '产品咨询', icon: 'database', color: '#8B5CF6', bg: '#F5F3FF' },
  { id: 'coder', name: '产品使用答疑', type: '使用答疑', icon: 'question', color: '#3B82F6', bg: '#EFF6FF' },
  { id: 'translator', name: '个人IP打造', type: '朋友圈帮写', icon: 'lightning', color: '#10B981', bg: '#ECFDF5' },
  { id: 'creative', name: '疑难问题解答', type: '口播文案帮写', icon: 'lifebuoy', color: '#F97316', bg: '#FFF7ED' },
];

let AGENTS = [];
let lastUserText = '';
let lastUserAgentId = '';
const assetLoaders = new Map();
let state = {
  currentView: 'home',
  activeAgentId: 'aura',
  messages: [],
  isTyping: false,
  isStreaming: false,
  token: localStorage.getItem('token'),
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  profile: JSON.parse(localStorage.getItem('chat_profile') || 'null'),
  teamOptions: [],
};

function loadScriptOnce(src) {
  if (assetLoaders.has(src)) return assetLoaders.get(src);
  const promise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (existing.dataset.loaded === 'true') {
        resolve();
        return;
      }
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error(`Failed to load script: ${src}`)), { once: true });
      return;
    }
    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.onload = () => {
      script.dataset.loaded = 'true';
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed to load script: ${src}`));
    document.head.appendChild(script);
  });
  assetLoaders.set(src, promise);
  return promise;
}

async function ensureHtml2Canvas() {
  if (typeof html2canvas !== 'undefined') return;
  await loadScriptOnce('https://html2canvas.hertzen.com/dist/html2canvas.min.js');
}

function getUserId() {
  let id = localStorage.getItem('user_uuid');
  if (!id) {
    id = 'u' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    localStorage.setItem('user_uuid', id);
  }
  return id;
}

function getViewerId() {
  let id = localStorage.getItem('qa_viewer_id');
  if (!id) {
    id = 'qa' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
    localStorage.setItem('qa_viewer_id', id);
  }
  return id;
}

document.addEventListener('DOMContentLoaded', () => {
  loadAgents();
  loadWaitingContent();
  // Chat scroll listener for "scroll to bottom" button
  const chatContainer = document.getElementById('chat-messages');
  if (chatContainer) {
    chatContainer.addEventListener('scroll', updateScrollBtn);
  }
  // Agent tab long-press drag
  initAgentTabDrag();
  bindIdentityEvents();
});

async function loadAgents() {
  try {
    const res = await fetch(`${API_BASE}/api/agents`);
    if (res.ok) {
      const data = await res.json();
      AGENTS = (data.agents || []).map(a => ({
        id: a.agent_id,
        name: a.name,
        type: a.type,
        description: a.description || '',
        chatDesc: a.chat_desc || '',
        icon: a.icon || 'robot',
        color: a.color || '#4F46E5',
        bg: (a.color || '#4F46E5') + '20',
      }));
    } else {
      AGENTS = [...FALLBACK_AGENTS];
    }
  } catch {
    AGENTS = [...FALLBACK_AGENTS];
  }
  await loadDefaultTeamSetting();
  renderAgentTabs();
  renderQuickFunctions();
  ensureIdentity();
}

async function loadDefaultTeamSetting() {
  try {
    const res = await fetch(`${API_BASE}/api/default-team`);
    if (!res.ok) return;
    const data = await res.json();
    state.teamOptions = (data.team_names || []).map(t => String(t).trim()).filter(Boolean);
    localStorage.setItem('team_options_cache', JSON.stringify(state.teamOptions));
  } catch {
    try {
      state.teamOptions = JSON.parse(localStorage.getItem('team_options_cache') || '[]');
    } catch {
      state.teamOptions = [];
    }
  }
}



function enterApp() {
  document.getElementById('app').classList.add('active');
  loadNews();
  loadHotQuestions();
}

function bindIdentityEvents() {
  const nameInput = document.getElementById('member-name-input');
  const teamSelect = document.getElementById('team-select');
  if (nameInput) {
    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submitIdentity();
    });
  }
  if (teamSelect) {
    teamSelect.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submitIdentity();
    });
  }
}

function ensureIdentity() {
  const gate = document.getElementById('identity-gate');
  const teamSelect = document.getElementById('team-select');
  if (teamSelect) {
    const options = ['<option value="">请选择团队</option>'].concat(
      state.teamOptions.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`)
    );
    teamSelect.innerHTML = options.join('');
  }
  if (state.profile && state.profile.team && state.profile.name) {
    const isAllowed = !state.teamOptions.length || state.teamOptions.includes(state.profile.team);
    if (!isAllowed) {
      state.profile = null;
      localStorage.removeItem('chat_profile');
    } else {
      if (gate) gate.classList.remove('active');
      if (!state.teamOptions.length) showToast('团队配置加载失败，已使用上次身份进入', 'info');
      enterApp();
      return;
    }
  }
  if (!state.teamOptions.length) {
    if (gate) gate.classList.add('active');
    const input = document.getElementById('member-name-input');
    const btn = document.querySelector('#identity-gate .btn-primary');
    if (input) input.disabled = true;
    if (teamSelect) teamSelect.disabled = true;
    if (btn) btn.disabled = true;
    showToast('未配置可选团队，请联系管理员', 'error');
    return;
  }
  if (teamSelect) teamSelect.disabled = false;
  const input = document.getElementById('member-name-input');
  const btn = document.querySelector('#identity-gate .btn-primary');
  if (input) input.disabled = false;
  if (btn) btn.disabled = false;
  if (gate) gate.classList.add('active');
}

function submitIdentity() {
  const team = (document.getElementById('team-select')?.value || '').trim();
  const name = (document.getElementById('member-name-input')?.value || '').trim();
  if (!team) { showToast('请选择团队', 'error'); return; }
  if (!state.teamOptions.includes(team)) { showToast('请选择管理员配置的团队', 'error'); return; }
  if (!name) { showToast('请输入姓名', 'error'); return; }
  state.profile = { team, name };
  localStorage.setItem('chat_profile', JSON.stringify(state.profile));
  document.getElementById('identity-gate')?.classList.remove('active');
  enterApp();
}

/* ===== View Switching ===== */
function switchView(view) {
  if (state.currentView === view) return;
  state.currentView = view;
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(`${view}-view`).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelector(`.nav-item[data-view="${view}"]`)?.classList.add('active');
  if (view === 'chat') {
    if (state.messages.length > 0) renderMessages();
    if (state.isTyping) showWaitingPanel();
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
  document.getElementById('chat-agent-name').innerHTML = `${agent.name} <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${state.isStreaming ? '#10B981' : '#CBD5E1'};animation:pulse-dot 2s infinite"></span>`;
}

/* ===== Quick Functions ===== */
function renderQuickFunctions() {
  const grid = document.getElementById('quick-grid');
  grid.innerHTML = AGENTS.map(a => `
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

/* ===== Fetch with Timeout ===== */
async function fetchWithTimeout(url, options = {}, timeout = 35000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    });
    clearTimeout(id);
    return response;
  } catch (error) {
    clearTimeout(id);
    if (error.name === 'AbortError') {
      throw new Error('请求超时，请稍后重试');
    }
    throw error;
  }
}

function buildChatPayload(text, agent) {
  return {
    message: text,
    query_type: agent.type,
    agent_id: agent.id,
    user_id: getUserId(),
    team_name: state.profile?.team || '',
    member_name: state.profile?.name || '',
  };
}

function startChatRequest() {
  const sendBtn = document.getElementById('send-btn');
  sendBtn.disabled = true;
  state.isTyping = true;
  state.isStreaming = false;
  showWaitingPanel();
  updateChatAgentInfo();
  return sendBtn;
}

function finishChatRequest(sendBtn) {
  hideWaitingPanel();
  hideTyping();
  state.isTyping = false;
  state.isStreaming = false;
  if (sendBtn) sendBtn.disabled = false;
  updateChatAgentInfo();
}

function createStreamingBotMessage(agentId) {
  state.isStreaming = true;
  const msgId = Date.now();
  state.messages.push({
    id: msgId,
    role: 'bot',
    content: '',
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    agentId,
    isStreaming: true,
    replyToText: lastUserText,
  });
  renderMessages();
  updateChatAgentInfo();
  return msgId;
}

function getMessageBubbleElement(msgId) {
  return document.querySelector(`.msg[data-msg-id="${msgId}"] .msg-bubble`);
}

function updateStreamingMessageDom(msgId, content, isStreaming = true) {
  const bubble = getMessageBubbleElement(msgId);
  if (!bubble) {
    renderMessages();
    return;
  }
  bubble.innerHTML = `${escapeHtml(content)}${isStreaming ? '<span class="cursor-blink"></span>' : ''}`;
  scrollToBottom();
  updateScrollBtn();
}

function appendStreamingBotMessage(msgId, text) {
  if (!text) return;
  const msg = state.messages.find(m => m.id === msgId);
  if (!msg) return;
  msg.content += text;
  updateStreamingMessageDom(msgId, msg.content, true);
}

function finalizeStreamingBotMessage(msgId, extras = {}) {
  const msg = state.messages.find(m => m.id === msgId);
  if (!msg) return;
  msg.isStreaming = false;
  if (extras.historyId) msg.historyId = extras.historyId;
  if (extras.feedback !== undefined) msg.feedback = extras.feedback;
  if (extras.content !== undefined) msg.content = extras.content;
  renderMessages();
}

function addBotMessage(content, options = {}) {
  addMessage({
    id: Date.now(),
    role: 'bot',
    content,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    agentId: options.agentId || state.activeAgentId,
    historyId: options.historyId,
    feedback: options.feedback,
    replyToText: options.replyToText || lastUserText,
  });
}

function parseSSEChunk(chunk) {
  const lines = chunk.split('\n');
  let event = 'message';
  const dataLines = [];
  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!dataLines.length) return null;
  try {
    return {
      event,
      data: JSON.parse(dataLines.join('\n')),
    };
  } catch {
    return null;
  }
}

async function streamChatRequest(payload, agentId) {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok || !res.body) {
    const errorPayload = await res.json().catch(() => ({}));
    const error = new Error(errorPayload.error || '流式连接失败');
    error.canFallback = true;
    throw error;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let botMsgId = null;
  let sawOutput = false;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    while (buffer.includes('\n\n')) {
      const boundary = buffer.indexOf('\n\n');
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSSEChunk(chunk);
      if (!parsed) continue;

      if (parsed.event === 'status') {
        continue;
      }

      if (parsed.event === 'delta') {
        if (!botMsgId) {
          hideWaitingPanel();
          botMsgId = createStreamingBotMessage(agentId);
        }
        sawOutput = true;
        appendStreamingBotMessage(botMsgId, parsed.data?.text || '');
        continue;
      }

      if (parsed.event === 'done') {
        hideWaitingPanel();
        const finalText = parsed.data?.full_text || '';
        if (!botMsgId) {
          botMsgId = createStreamingBotMessage(agentId);
        }
        if (!sawOutput && finalText) {
          appendStreamingBotMessage(botMsgId, finalText);
        }
        finalizeStreamingBotMessage(botMsgId, {
          historyId: parsed.data?.history_id,
          content: finalText || (state.messages.find(m => m.id === botMsgId)?.content || ''),
        });
        state.isStreaming = false;
        updateChatAgentInfo();
        return parsed.data;
      }

      if (parsed.event === 'error') {
        const error = new Error(parsed.data?.message || '流式回复失败');
        if (botMsgId) {
          const msg = state.messages.find(m => m.id === botMsgId);
          const partial = msg?.content || '';
          const nextContent = partial
            ? `${partial}\n\n[本次回答未完成：${error.message}]`
            : error.message;
          finalizeStreamingBotMessage(botMsgId, { content: nextContent });
          error.renderedInMessage = true;
        } else {
          error.canFallback = true;
        }
        throw error;
      }
    }
  }

  if (!sawOutput) {
    const error = new Error('流式回复中断，请稍后重试');
    error.canFallback = true;
    throw error;
  }

  return null;
}

async function fallbackToSyncChat(payload, agentId) {
  const res = await fetchWithTimeout(`${API_BASE}/api/chat/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }, 120000);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || '发送失败');
  }
  addBotMessage(data.bot_response, { agentId, historyId: data.history_id });
  return data;
}

async function executeChatRequest({ text, agentId }) {
  const agent = AGENTS.find(a => a.id === agentId) || AGENTS[0];
  const payload = buildChatPayload(text, agent);
  const sendBtn = startChatRequest();

  try {
    const result = await streamChatRequest(payload, agentId);
    checkSurvey();
    return result;
  } catch (error) {
    if (error.canFallback) {
      try {
        const result = await fallbackToSyncChat(payload, agentId);
        showToast('已切换为普通回复模式', 'info');
        checkSurvey();
        return result;
      } catch (fallbackError) {
        addBotMessage(fallbackError.message || '网络错误，请检查您的连接。', { agentId });
        showToast(fallbackError.message || '发送失败', 'error');
        throw fallbackError;
      }
    }

    if (error.renderedInMessage) {
      showToast(error.message || '回复中断', 'error');
      throw error;
    }

    addBotMessage(error.message || '网络错误，请检查您的连接。', { agentId });
    showToast(error.message || '发送失败', 'error');
    throw error;
  } finally {
    finishChatRequest(sendBtn);
  }
}

/* ===== Send Message ===== */
async function sendMessage() {
  const input = document.getElementById('message-input');
  const text = input.value.trim();
  if (!text || state.isStreaming) return;
  if (state.currentView !== 'chat') { switchView('chat'); setTimeout(() => sendMessage(), 200); return; }
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  lastUserText = text;
  lastUserAgentId = state.activeAgentId;
  addMessage({ id: Date.now(), role: 'user', content: text, time });
  input.value = '';

  try {
    await executeChatRequest({ text, agentId: state.activeAgentId });
  } catch {}
}

function handleInputKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function addMessage(msg) {
  state.messages.push(msg);
  renderMessages();
}

function replaceSystemMessage(text) {
  state.messages = state.messages.filter(m => m.role !== 'system');
  state.messages.push({ id: Date.now(), role: 'system', content: text });
  renderMessages();
}

function renderMessages() {
  const container = document.getElementById('chat-messages');
  document.getElementById('empty-chat').style.display = state.messages.length > 0 ? 'none' : 'flex';
  document.querySelectorAll('.msg, .typing-indicator').forEach(el => el.remove());

  state.messages.forEach((msg, idx) => {
    const agent = msg.agentId ? AGENTS.find(a => a.id === msg.agentId) : AGENTS[0];
    const div = document.createElement('div');
    div.className = `msg ${msg.role}`;
    div.dataset.msgId = msg.id;
    if (msg.role === 'system') {
      div.innerHTML = `<div class="system-bubble"><i class="ph ph-check-circle"></i><div class="sb-text">${msg.content}</div></div>`;
    } else if (msg.role === 'bot') {
      const icon = agent ? agent.icon : 'sparkle';
      const color = agent ? agent.color : '#4F46E5';
      const escapedContent = escapeHtml(msg.content);
      const likeActive = msg.feedback === 1 ? ' active' : '';
      const dislikeActive = msg.feedback === 0 ? ' active' : '';
      const feedbackDisabled = msg.feedback !== undefined ? ' disabled' : '';
      const actions = !msg.isStreaming ? `
        <div class="msg-actions">
          <button class="msg-action-btn" onclick="copyText('${escapedContent.replace(/'/g, "\\'")}')"><i class="ph ph-copy-simple"></i> 复制</button>
          <button class="msg-action-btn" onclick="regenerateMsg(${idx})"><i class="ph ph-arrows-clockwise"></i> 重新回答</button>
          ${msg.historyId ? `
          <button class="msg-feedback-btn${likeActive}${feedbackDisabled}" onclick="sendFeedback(${msg.historyId}, 1, ${idx})"><i class="ph ph-thumbs-up"></i></button>
          <button class="msg-feedback-btn${dislikeActive}${feedbackDisabled}" onclick="sendFeedback(${msg.historyId}, 0, ${idx})"><i class="ph ph-thumbs-down"></i></button>` : ''}
        </div>` : '';
      div.innerHTML = `<div class="msg-avatar" style="background:${color}"><i class="ph ph-${icon}"></i></div>
        <div class="msg-body"><div class="msg-bubble">${escapedContent}${msg.isStreaming ? '<span class="cursor-blink"></span>' : ''}</div><span class="msg-time">${msg.time}</span>${actions}</div>`;
    } else {
      div.innerHTML = `<div class="msg-avatar"><i class="ph ph-user"></i></div>
        <div class="msg-body"><div class="msg-bubble">${escapeHtml(msg.content)}</div><span class="msg-time">${msg.time}</span></div>`;
    }
    container.appendChild(div);
  });
  container.scrollTop = container.scrollHeight;
  updateScrollBtn();
}

function showTyping() {
  const container = document.getElementById('chat-messages');
  document.querySelector('.typing-indicator')?.remove();
  const agent = AGENTS.find(a => a.id === state.activeAgentId);
  const div = document.createElement('div');
  div.className = 'typing-indicator';
  div.innerHTML = `<div class="msg-avatar" style="background:${agent.color}"><i class="ph ph-${agent.icon}"></i></div>
    <div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function hideTyping() { document.querySelector('.typing-indicator')?.remove(); }

// ===== Waiting Bubble =====
let waitingContent = null;
let wbStepTimer = null;
let wbTipTimer = null;
let wbStepIdx = 0;
let wbTipIdx = 0;
let wbMsgId = null;

const WB_ICONS = [
  'ph-question', 'ph-robot', 'ph-book-open', 'ph-magnifying-glass', 'ph-lightbulb',
  'ph-pencil-line', 'ph-check-circle', 'ph-sparkle', 'ph-file-text', 'ph-rocket-launch',
];

async function loadWaitingContent() {
  try {
    const res = await fetch(`${API_BASE}/api/waiting-content`);
    if (res.ok) waitingContent = await res.json();
  } catch {}
  const fallbackSteps = [
    "正在理解您的问题...",
    "正在匹配最佳智能体...",
    "正在检索产品知识库...",
    "正在分析问题关键点...",
    "正在构思回答框架...",
    "正在组织语言表达...",
    "正在校验回答准确性...",
    "正在润色语言风格...",
    "正在生成完整回复...",
    "即将完成...",
  ];
  const fallbackTips = [
    "试试问我：你的产品有什么功效？",
    "我可以帮你写朋友圈文案",
    "关注资讯栏目获取最新动态",
    "试试问我产品怎么使用",
    "我还能帮你写口播文案",
  ];
  if (!waitingContent) {
    waitingContent = { steps: fallbackSteps, tips: fallbackTips };
  } else {
    if (!waitingContent.steps || waitingContent.steps.length === 0) waitingContent.steps = fallbackSteps;
    if (!waitingContent.tips || waitingContent.tips.length === 0) waitingContent.tips = fallbackTips;
  }
}

function showWaitingPanel() {
  if (!waitingContent) return;
  const steps = waitingContent.steps || [];
  const tips = waitingContent.tips || [];
  if (steps.length === 0) return;

  const container = document.getElementById('chat-messages');
  wbMsgId = 'wb-' + Date.now();
  wbStepIdx = 0;
  wbTipIdx = 0;

  const agent = AGENTS.find(a => a.id === state.activeAgentId) || AGENTS[0];
  const icon = agent ? agent.icon : 'sparkle';
  const color = agent ? agent.color : '#4F46E5';

  const div = document.createElement('div');
  div.className = 'msg bot';
  div.id = wbMsgId;
  div.innerHTML =
    `<div class="msg-avatar" style="background:${color}"><i class="ph ph-${icon}"></i></div>` +
    `<div class="msg-body"><div class="msg-bubble waiting-bubble" id="${wbMsgId}-bubble">` +
      renderWbContent(0, tips.length > 0 ? tips[0] : '') +
    `</div></div>`;
  container.appendChild(div);
  scrollToBottom();

  clearInterval(wbStepTimer);
  clearInterval(wbTipTimer);

  if (steps.length > 1) {
    wbStepTimer = setInterval(() => {
      wbStepIdx = (wbStepIdx + 1) % steps.length;
      const bubble = document.getElementById(wbMsgId + '-bubble');
      if (bubble) {
        const currentTip = tips.length > 0 ? tips[wbTipIdx % tips.length] : '';
        bubble.innerHTML = renderWbContent(wbStepIdx, currentTip);
      }
      scrollToBottom();
    }, 3500);
  }

  if (tips.length > 1) {
    wbTipTimer = setInterval(() => {
      wbTipIdx = (wbTipIdx + 1) % tips.length;
      const bubble = document.getElementById(wbMsgId + '-bubble');
      if (bubble) {
        bubble.innerHTML = renderWbContent(wbStepIdx, tips[wbTipIdx]);
      }
    }, 10000);
  }
}

function renderWbContent(stepIdx, tipText) {
  const steps = waitingContent ? waitingContent.steps : [];
  const step = steps[stepIdx] || '处理中...';
  const icon = WB_ICONS[stepIdx % WB_ICONS.length];
  return `<div class="wb-step"><i class="ph ${icon}"></i><span>${escapeHtml(step)}</span></div>` +
    (tipText ? `<div class="wb-tip">${escapeHtml(tipText)}</div>` : '') +
    `<div class="wb-dots"><span class="wb-dot"></span><span class="wb-dot"></span><span class="wb-dot"></span></div>`;
}

function scrollToBottom() {
  const c = document.getElementById('chat-messages');
  if (c) c.scrollTop = c.scrollHeight;
}

function hideWaitingPanel() {
  clearInterval(wbStepTimer);
  clearInterval(wbTipTimer);
  wbStepTimer = null;
  wbTipTimer = null;
  if (wbMsgId) {
    const el = document.getElementById(wbMsgId);
    if (el) el.remove();
    wbMsgId = null;
  }
}

async function streamResponse(text, historyId) {
  addBotMessage(text, { historyId, agentId: state.activeAgentId });
}

/* ===== History ===== */
async function loadHistory(queryType = '') {
  try {
    const base = `${API_BASE}/api/history/sessions?user_id=${getUserId()}`;
    const url = queryType ? `${base}&query_type=${encodeURIComponent(queryType)}` : base;
    const res = await fetch(url);
    if (res.ok) {
      const data = await res.json();
      renderMemorySessions(data.sessions);
    }
  } catch {}
}

function renderMemorySessions(sessions) {
  const container = document.getElementById('memory-list');
  if (!sessions || sessions.length === 0) {
    container.innerHTML = '<div class="memory-empty"><i class="ph ph-inbox"></i><p>暂无咨询记录</p></div>';
    return;
  }
  const typeIcon = { '产品咨询': 'database', '使用答疑': 'question', '朋友圈帮写': 'lightning', '口播文案帮写': 'lifebuoy' };
  const typeColor = { '产品咨询': '#4F46E5', '使用答疑': '#3B82F6', '朋友圈帮写': '#059669', '口播文案帮写': '#EA580C' };
  container.innerHTML = sessions.map(s => {
    const icon = typeIcon[s.query_type] || 'file-text';
    const color = typeColor[s.query_type] || '#4F46E5';
    const firstMsg = (s.items[0] && s.items[0].user_message) || '';
    const date = new Date(s.date).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    const ids = JSON.stringify(s.items.map(i => i.id));
    return `<button class="session-card" onclick="loadSession(${ids})">
      <div class="session-icon" style="background:${color}"><i class="ph ph-${icon}"></i></div>
      <div class="session-body">
        <div class="session-meta">${date} · ${escapeHtml(s.query_type)} · ${s.count}轮</div>
        <div class="session-preview">${escapeHtml(firstMsg)}</div>
      </div>
      <button class="session-delete" onclick="deleteSession(event, ${ids})"><i class="ph ph-trash"></i></button>
    </button>`;
  }).join('');
}

async function deleteSession(e, itemIds) {
  e.stopPropagation();
  if (!confirm('确定删除该会话？')) return;
  try {
    const res = await fetch(`${API_BASE}/api/history/batch-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: itemIds }),
    });
    if (res.ok) {
      showToast('已删除', 'success');
      loadHistory(document.getElementById('memory-filter').value);
    }
  } catch { showToast('删除失败', 'error'); }
}

/* ===== Community ===== */
function switchCommunityTab(tab) {
  document.querySelectorAll('.community-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.community-panel').forEach(p => p.classList.remove('active'));
  if (tab === 'memory') {
    document.querySelector('.community-tab:nth-child(1)').classList.add('active');
    document.getElementById('community-tab-memory').classList.add('active');
    loadHistory(document.getElementById('memory-filter').value);
  } else {
    document.querySelector('.community-tab:nth-child(2)').classList.add('active');
    document.getElementById('community-tab-qa').classList.add('active');
    loadQA();
  }
}

// ===== Q&A Wall =====
let qaPage = 1;
let qaPages = 0;
let currentQId = null;
let nicknameResolve = null;

function getLikedReplyIds() {
  try {
    return new Set(JSON.parse(localStorage.getItem('liked_reply_ids') || '[]').map(String));
  } catch {
    return new Set();
  }
}

function markReplyLiked(replyId) {
  const ids = getLikedReplyIds();
  ids.add(String(replyId));
  localStorage.setItem('liked_reply_ids', JSON.stringify([...ids]));
}

function getNickname() {
  return new Promise(resolve => {
    const stored = localStorage.getItem('community_nickname');
    if (stored) { resolve(stored); return; }
    nicknameResolve = resolve;
    document.getElementById('nickname-input').value = '';
    document.getElementById('nickname-overlay').classList.add('active');
    setTimeout(() => document.getElementById('nickname-input').focus(), 100);
  });
}

function confirmNickname() {
  const n = (document.getElementById('nickname-input').value || '').trim() || '匿名用户';
  localStorage.setItem('community_nickname', n);
  document.getElementById('nickname-overlay').classList.remove('active');
  if (nicknameResolve) { nicknameResolve(n); nicknameResolve = null; }
}

function closeNicknameModal(e) {
  if (e && e.target !== e.currentTarget) return;
  document.getElementById('nickname-overlay').classList.remove('active');
  if (nicknameResolve) { nicknameResolve('匿名用户'); nicknameResolve = null; }
}

async function loadQA() {
  qaPage = 1;
  try {
    const res = await fetch(`${API_BASE}/api/community/questions?page=1&limit=10`);
    if (!res.ok) return;
    const data = await res.json();
    qaPage = data.page;
    qaPages = data.pages;
    renderQA(data.items || []);
    const more = document.getElementById('qa-more-wrap');
    if (more) more.style.display = qaPage < qaPages ? 'flex' : 'none';
  } catch {}
}

function renderQA(items) {
  const container = document.getElementById('qa-list');
  if (!items || !items.length) {
    container.innerHTML = '<div class="memory-empty"><i class="ph ph-chats"></i><p>暂无精选问答</p></div>';
    return;
  }
  container.innerHTML = items.map(q => `
    <button class="qa-card" onclick="showQDetail(${q.id})">
      <div class="qa-card-body">
        <div class="qa-card-category">${q.category ? `🏷 ${escapeHtml(q.category)}` : ''}</div>
        <div class="qa-card-title">${escapeHtml(q.title)}</div>
        <div class="qa-card-meta">${q.reply_count}条评论 · 👍 ${q.view_count || 0}</div>
      </div>
    </button>
  `).join('');
}

async function loadMoreQA() {
  if (qaPage >= qaPages) return;
  const btn = document.querySelector('#qa-more-wrap .discover-more-btn');
  btn.textContent = '加载中...';
  btn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/community/questions?page=${qaPage + 1}&limit=10`);
    if (!res.ok) return;
    const data = await res.json();
    qaPage = data.page;
    const container = document.getElementById('qa-list');
    data.items.forEach(q => {
      const el = document.createElement('button');
      el.className = 'qa-card';
      el.onclick = () => showQDetail(q.id);
      el.innerHTML = `<div class="qa-card-body">
        <div class="qa-card-category">${q.category ? `🏷 ${escapeHtml(q.category)}` : ''}</div>
        <div class="qa-card-title">${escapeHtml(q.title)}</div>
        <div class="qa-card-meta">${q.reply_count}条评论 · 👍 ${q.view_count || 0}</div>
      </div>`;
      container.appendChild(el);
    });
    btn.textContent = '加载更多';
    btn.disabled = false;
    if (qaPage >= qaPages) document.getElementById('qa-more-wrap').style.display = 'none';
  } catch { btn.textContent = '加载失败'; btn.disabled = false; }
}

async function showQDetail(id) {
  currentQId = id;
  try {
    const res = await fetch(`${API_BASE}/api/community/questions/${id}?viewer_id=${encodeURIComponent(getViewerId())}`);
    if (!res.ok) return;
    const q = await res.json();
    let html = `
      <h2 class="qdetail-title">${escapeHtml(q.title)}</h2>
      ${q.content ? `<div class="qdetail-body">${escapeHtml(q.content)}</div>` : ''}
      <div class="qdetail-divider">💬 ${q.reply_count} 条评论</div>`;

    if (q.replies && q.replies.length) {
      const likedReplies = getLikedReplyIds();
      q.replies.forEach(r => {
        const liked = likedReplies.has(String(r.id));
        html += `<div class="qdetail-reply">
          <span class="qdetail-reply-avatar">${(r.nickname || '匿').charAt(0)}</span>
          <div class="qdetail-reply-body">
            <div class="qdetail-reply-author">
              ${escapeHtml(r.nickname || '匿名')}
            </div>
            <div class="qdetail-reply-text">${escapeHtml(r.content)}</div>
            <button class="qdetail-reply-like ${liked ? 'liked' : ''}" onclick="likeReply(${r.id}, this)" ${liked ? 'disabled' : ''}>
              <i class="ph ph-thumbs-up"></i><span>${r.like_count || 0}</span>
            </button>
          </div>
        </div>`;
      });
    } else {
      html += `<div class="qdetail-empty">暂无评论</div>`;
    }
    document.getElementById('qdetail-content').innerHTML = html;
    document.getElementById('qdetail-reply-input').value = '';
    document.getElementById('qdetail-overlay').classList.add('active');
  } catch {}
}

async function likeReply(replyId, btn) {
  if (!replyId || !btn || btn.disabled) return;
  btn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/community/replies/${replyId}/like`, { method: 'POST' });
    if (!res.ok) throw new Error('like failed');
    const data = await res.json();
    markReplyLiked(replyId);
    btn.classList.add('liked');
    const countEl = btn.querySelector('span');
    if (countEl) countEl.textContent = data.like_count || 0;
  } catch {
    btn.disabled = false;
    showToast('点赞失败', 'error');
  }
}

function closeQDetail(e) {
  if (e && e.target !== e.currentTarget) return;
  document.getElementById('qdetail-overlay').classList.remove('active');
  currentQId = null;
}

/* ===== Survey ===== */
function checkSurvey() {
  const key = 'survey_count';
  let count = parseInt(localStorage.getItem(key) || '0', 10);
  count++;
  localStorage.setItem(key, count);
  if (count % 10 === 0) {
    document.getElementById('survey-overlay').classList.add('active');
  }
}

function submitSurvey(score) {
  document.getElementById('survey-overlay').classList.remove('active');
  fetch(`${API_BASE}/api/survey`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ score }),
  }).catch(() => {});
}

async function submitReply() {
  if (!currentQId) return;
  const content = document.getElementById('qdetail-reply-input').value.trim();
  if (!content) { showToast('请输入回复内容', 'error'); return; }
  try {
    const res = await fetch(`${API_BASE}/api/community/questions/${currentQId}/replies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nickname: '匿名用户', content, viewer_id: getViewerId() }),
    });
    if (res.ok) {
      showToast('评论已提交，精选后公开展示', 'success');
      showQDetail(currentQId);
    } else {
      const data = await res.json();
      showToast(data.error || '评论失败', 'error');
    }
  } catch { showToast('网络错误', 'error'); }
}

async function loadSession(itemIds) {
  if (!itemIds || itemIds.length === 0) return;
  const firstItemId = itemIds[0];
  try {
    const res = await fetch(`${API_BASE}/api/history/${firstItemId}?user_id=${getUserId()}`);
    if (!res.ok) return;
    const first = await res.json();
    const agent = AGENTS.find(a => a.type === first.query_type) || AGENTS[0];
    if (agent) state.activeAgentId = agent.id;
    renderAgentTabs();
    state.messages = [];
    for (const id of itemIds.reverse()) {
      try {
        const r = await fetch(`${API_BASE}/api/history/${id}?user_id=${getUserId()}`);
        if (r.ok) {
          const item = await r.json();
          addMessage({ id: Date.now(), role: 'user', content: item.user_message, time: formatTime(item.created_at, true) });
          if (item.bot_response) addMessage({ id: Date.now() + 1, role: 'bot', content: item.bot_response, time: formatTime(item.created_at, true), agentId: state.activeAgentId, historyId: item.id, feedback: item.feedback });
        }
      } catch {}
    }
    switchView('chat');
  } catch { showToast('加载会话失败', 'error'); }
}

/* ===== News ===== */
async function loadNews() {
  try {
    const res = await fetch(`${API_BASE}/api/news?mode=home&limit=3`);
    if (res.ok) {
      const data = await res.json();
      renderNews(data.news);
    }
  } catch {}
}

function renderNews(news) {
  const container = document.getElementById('home-news');
  if (!news || news.length === 0) {
    container.innerHTML = '<div class="news-empty">暂无资讯</div>';
    return;
  }
  container.innerHTML = news.map(item => `
    <button class="news-card" onclick="showNewsDetail(${item.id})">
      <div class="news-card-img">${item.image_url
        ? `<img src="${item.image_url}" alt="${escapeHtml(item.title)}">`
        : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <div class="news-card-body">
        <div class="news-card-title">${escapeHtml(item.title)}</div>
        <div class="news-card-summary">${escapeHtml(item.summary || item.content || '')}</div>
        <div class="news-card-time">${formatTime(item.created_at)}</div>
      </div>
    </button>
  `).join('');
}

/* ===== Discover ===== */
let discoverPage = 1;
let discoverTotal = 0;
let discoverPages = 0;
let carouselTimer = null;
let carouselIdx = 0;
let currentCategory = '';

async function loadDiscover(category) {
  if (category !== undefined) currentCategory = category || '';
  try {
    let url = `${API_BASE}/api/news?mode=discover&page=1&limit=10`;
    if (currentCategory) url += `&category=${encodeURIComponent(currentCategory)}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    discoverPage = data.page.page;
    discoverTotal = data.page.total;
    discoverPages = data.page.pages;
    renderCategories(data.categories || []);
    renderCarousel(data.pinned || []);
    renderDiscoverList(data.news || []);
    const more = document.getElementById('discover-more-wrap');
    more.style.display = discoverPage < discoverPages ? 'flex' : 'none';
  } catch {}
}

function renderCategories(categories) {
  const container = document.getElementById('category-tabs');
  container.innerHTML = `<button class="category-tab${currentCategory === '' ? ' active' : ''}" onclick="filterCategory('')">全部</button>` +
    categories.map(c => `<button class="category-tab${currentCategory === c ? ' active' : ''}" onclick="filterCategory('${escapeHtml(c)}')">${escapeHtml(c)}</button>`).join('');
}

function filterCategory(cat) {
  currentCategory = cat;
  document.querySelectorAll('.category-tab').forEach(b => b.classList.toggle('active', b.textContent === (cat || '全部')));
  loadDiscover();
}

function renderCarousel(pinned) {
  const wrap = document.getElementById('discover-carousel-wrap');
  const container = document.getElementById('discover-carousel');
  const dots = document.getElementById('carousel-dots');
  if (!pinned.length) { wrap.style.display = 'none'; stopCarouselAuto(); return; }
  wrap.style.display = 'block';
  carouselIdx = 0;

  container.innerHTML = pinned.map(p => `
    <button class="carousel-slide" onclick="showNewsDetail(${p.id})">
      <div class="carousel-img">${p.image_url
        ? `<img src="${p.image_url}" alt="${escapeHtml(p.title)}">`
        : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <div class="carousel-caption">
        <div class="carousel-pin">📌 置顶</div>
        <div class="carousel-title">${escapeHtml(p.title)}</div>
      </div>
    </button>
  `).join('');

  dots.innerHTML = pinned.map((_, i) => `<span class="carousel-dot${i === 0 ? ' active' : ''}"></span>`).join('');

  container.addEventListener('scroll', () => {
    const idx = Math.round(container.scrollLeft / container.clientWidth);
    if (idx !== carouselIdx) { carouselIdx = idx; updateCarouselDots(); }
  }, { once: false });

  stopCarouselAuto();
  if (pinned.length > 1) startCarouselAuto();
}

function updateCarouselDots() {
  document.querySelectorAll('.carousel-dot').forEach((d, i) => d.classList.toggle('active', i === carouselIdx));
}

function startCarouselAuto() {
  carouselTimer = setInterval(() => {
    const c = document.getElementById('discover-carousel');
    if (!c) return;
    carouselIdx = (carouselIdx + 1) % c.children.length;
    c.scrollTo({ left: carouselIdx * c.clientWidth, behavior: 'smooth' });
    updateCarouselDots();
  }, 4000);
}

function stopCarouselAuto() {
  clearInterval(carouselTimer);
  carouselTimer = null;
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopCarouselAuto();
  else if (state.currentView === 'discover') startCarouselAuto();
});

function renderDiscoverList(news) {
  const container = document.getElementById('discover-list');
  if (!news || news.length === 0) {
    container.innerHTML = '<div class="discover-empty">暂无更多资讯</div>';
    return;
  }
  container.innerHTML = news.map(item => `
    <button class="news-card" onclick="showNewsDetail(${item.id})">
      <div class="news-card-img">${item.image_url
        ? `<img src="${item.image_url}" alt="${escapeHtml(item.title)}">`
        : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <div class="news-card-body">
        <div class="news-card-title">${escapeHtml(item.title)}</div>
        <div class="news-card-summary">${escapeHtml(item.summary || item.content || '')}</div>
        <div class="news-card-time">${formatTime(item.created_at)}</div>
      </div>
    </button>
  `).join('');
}

async function loadMoreNews() {
  if (discoverPage >= discoverPages) return;
  const btn = document.querySelector('.discover-more-btn');
  btn.textContent = '加载中...';
  btn.disabled = true;
  try {
    let url = `${API_BASE}/api/news?mode=discover&page=${discoverPage + 1}&limit=10`;
    if (currentCategory) url += `&category=${encodeURIComponent(currentCategory)}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    discoverPage = data.page.page;
    const existing = document.getElementById('discover-list');
    data.news.forEach(item => {
      const el = document.createElement('button');
      el.className = 'news-card';
      el.onclick = () => showNewsDetail(item.id);
      el.innerHTML = `
        <div class="news-card-img">${item.image_url
          ? `<img src="${item.image_url}" alt="${escapeHtml(item.title)}">`
          : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
        </div>
        <div class="news-card-body">
          <div class="news-card-title">${escapeHtml(item.title)}</div>
          <div class="news-card-summary">${escapeHtml(item.summary || item.content || '')}</div>
          <div class="news-card-time">${formatTime(item.created_at)}</div>
        </div>`;
      existing.appendChild(el);
    });
    btn.textContent = '加载更多';
    btn.disabled = false;
    if (discoverPage >= discoverPages) {
      document.getElementById('discover-more-wrap').style.display = 'none';
    }
  } catch {
    btn.textContent = '加载失败，重试';
    btn.disabled = false;
  }
}

/* ===== Hot Questions ===== */
async function loadHotQuestions() {
  try {
    const res = await fetch(`${API_BASE}/api/history/hot-questions`);
    if (res.ok) {
      const data = await res.json();
      renderHotQuestions(data.questions);
    }
  } catch {}
}

function renderHotQuestions(questions) {
  const container = document.getElementById('hot-tags');
  if (!questions || questions.length === 0) {
    container.innerHTML = '<div class="news-empty">暂无热门问题</div>';
    return;
  }
  const maxCount = Math.max(...questions.map(q => q.count));
  container.innerHTML = questions.map(q => {
    const ratio = q.count / maxCount;
    const size = 12 + Math.round(ratio * 6);
    const opacity = 0.5 + ratio * 0.5;
    return `<span class="hot-tag" style="font-size:${size}px;opacity:${opacity}" onclick="quickSend('aura','${escapeHtml(q.text)}')">${escapeHtml(q.text)}</span>`;
  }).join('');
}

/* ===== News Detail ===== */
async function showNewsDetail(id) {
  try {
    const res = await fetch(`${API_BASE}/api/news/${id}`);
    if (!res.ok) return;
    const item = await res.json();
    const container = document.getElementById('news-detail-content');
    container.innerHTML = `
      <div class="news-detail-image">${item.image_url
        ? `<img src="${item.image_url}" alt="${escapeHtml(item.title)}">`
        : `<div class="placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <h1 class="news-detail-title">${escapeHtml(item.title)}</h1>
      <div class="news-detail-meta">${formatTime(item.created_at)}</div>
      <div class="news-detail-body">${item.content || item.summary || '暂无内容'}</div>
    `;
    document.getElementById('news-detail-overlay').classList.add('active');
  } catch {}
}

function closeNewsDetail() {
  document.getElementById('news-detail-overlay').classList.remove('active');
}

/* ===== Admin Panel ===== */
function openAdmin() {
  window.location.href = '/admin';
}

/* ===== Copy Text ===== */
function copyText(text) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    showToast('内容已复制', 'success');
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast('内容已复制', 'success');
  });
}

/* ===== Share as Image ===== */
async function shareChat() {
  closeChatMenu();
  const msgs = state.messages.filter(m => m.content);
  if (msgs.length === 0) {
    showToast('没有内容可以分享', 'info');
    return;
  }

  const agent = AGENTS.find(a => a.id === state.activeAgentId) || AGENTS[0] || {};
  const card = document.getElementById('share-card');
  const content = document.getElementById('share-card-content');
  const now = new Date().toLocaleString('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });

  let html = `
    <div style="padding:0 0 16px;border-bottom:1px solid #f0f0f0;margin-bottom:16px;display:flex;align-items:center;gap:12px">
      <div style="width:40px;height:40px;border-radius:10px;background:${agent.color || '#8B5CF6'};display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#fff;font-family:sans-serif">AI</div>
      <div>
        <div style="font-weight:700;font-size:15px;color:#1F2937">AI宝儿智能体</div>
        <div style="font-size:12px;color:#9CA3AF">${agent.name || ''}</div>
      </div>
    </div>`;

  const limit = Math.min(msgs.length, 10);
  const msgsToShare = msgs.slice(-limit);

  for (const m of msgsToShare) {
    if (m.role === 'user') {
      html += `
        <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
          <div style="max-width:80%;padding:10px 14px;background:#F3F4F6;border-radius:16px 16px 4px 16px;font-size:14px;color:#1F2937;line-height:1.5;word-break:break-word">${escapeHtml(m.content)}</div>
        </div>`;
    } else {
      html += `
        <div style="display:flex;gap:8px;margin-bottom:12px">
          <div style="width:32px;height:32px;min-width:32px;border-radius:8px;background:${agent.color || '#8B5CF6'};display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;font-family:sans-serif">AI</div>
          <div style="max-width:calc(100% - 40px);padding:10px 14px;background:#F5F3FF;border-radius:16px 16px 16px 4px;font-size:14px;color:#1F2937;line-height:1.5;word-break:break-word">${escapeHtml(m.content)}</div>
        </div>`;
    }
  }

  html += `
    <div style="margin-top:16px;padding-top:16px;border-top:1px solid #f0f0f0;text-align:center;font-size:11px;color:#D1D5DB">
      ${now} · 来自 AI宝儿智能体
    </div>`;

  content.innerHTML = html;

  showToast('正在生成分享图片...', 'info');

  try {
    await ensureHtml2Canvas();
  } catch {
    showToast('分享组件加载失败，请稍后重试', 'error');
    return;
  }

  html2canvas(card, {
    scale: 3,
    useCORS: true,
    backgroundColor: '#ffffff',
    width: 390,
  }).then(canvas => {
    const dataUrl = canvas.toDataURL('image/png');
    const wrap = document.getElementById('share-image-wrap');
    wrap.innerHTML = `<img src="${dataUrl}" alt="分享对话" style="width:100%;display:block;border-radius:8px">`;
    document.getElementById('share-overlay').classList.add('active');
  }).catch(() => {
    showToast('生成失败，请重试', 'error');
  });
}

function closeSharePreview(e) {
  if (e && e.target !== e.currentTarget) return;
  document.getElementById('share-overlay').classList.remove('active');
}

/* ===== Chat Menu ===== */
function toggleChatMenu(e) {
  e.stopPropagation();
  const menu = document.getElementById('chat-menu');
  const isActive = menu.classList.toggle('active');
  if (isActive) {
    setTimeout(() => document.addEventListener('click', closeChatMenu), 10);
  }
}
function closeChatMenu() {
  document.getElementById('chat-menu').classList.remove('active');
  document.removeEventListener('click', closeChatMenu);
}

/* ===== Clear Chat ===== */
function clearChat() {
  closeChatMenu();
  if (state.messages.length === 0) return;
  if (!confirm('确定清空当前对话？历史记录不会被删除。')) return;
  state.messages = [];
  renderMessages();
  showToast('对话已清空', 'success');
}

/* ===== Feedback ===== */
async function sendFeedback(historyId, feedback, msgIdx) {
  if (state.messages[msgIdx] && state.messages[msgIdx].feedback !== undefined) return;
  if (feedback === 1) {
    await submitFeedback(historyId, 1, '', msgIdx);
  } else {
    showReasonPopup(historyId, msgIdx);
  }
}

async function submitFeedback(historyId, feedback, reason, msgIdx) {
  try {
    const body = { history_id: historyId, feedback };
    if (reason) body.reason = reason;
    const res = await fetch(`${API_BASE}/api/chat/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      if (state.messages[msgIdx]) {
        state.messages[msgIdx].feedback = feedback;
      }
      document.querySelectorAll('.msg-feedback-btn').forEach(btn => {
        if (btn.getAttribute('onclick')?.includes(`sendFeedback(${historyId},`)) {
          btn.disabled = true;
          if (btn.getAttribute('onclick')?.includes(`, ${feedback}, `)) {
            btn.classList.add('active');
          }
        }
      });
      showToast(feedback ? '感谢你的反馈 😊' : '已记录反馈', 'success');
    }
  } catch {
    showToast('提交失败，请重试', 'error');
  }
}

function showReasonPopup(historyId, msgIdx) {
  const reasons = ['回答不准确', '不是我想要的', '其他原因'];
  const container = document.getElementById('reason-popup');
  container.innerHTML = reasons.map(r =>
    `<button class="reason-tag" onclick="submitFeedback(${historyId}, 0, '${r}', ${msgIdx});closeReasonPopup()">${r}</button>`
  ).join('');
  container.classList.add('active');
  setTimeout(closeReasonPopup, 4000);
}

function closeReasonPopup() {
  document.getElementById('reason-popup').classList.remove('active');
}

/* ===== Survey ===== */
function checkSurvey() {
  const key = 'survey_count';
  let count = parseInt(localStorage.getItem(key) || '0', 10);
  count++;
  localStorage.setItem(key, count);
  if (count % 10 === 0) {
    document.getElementById('survey-overlay').classList.add('active');
  }
}

function submitSurvey(score) {
  document.getElementById('survey-overlay').classList.remove('active');
  fetch(`${API_BASE}/api/survey`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ score }),
  }).catch(() => {});
}

/* ===== Regenerate ===== */
async function regenerateMsg(msgIdx) {
  const botMsg = state.messages[msgIdx];
  if (!botMsg || botMsg.role !== 'bot' || state.isStreaming) return;
  
  // Find the user message this bot responded to
  let userText = botMsg.replyToText;
  let agentId = botMsg.agentId || state.activeAgentId;
  
  // If no stored replyToText, find preceding user message
  if (!userText) {
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (state.messages[i].role === 'user') {
        userText = state.messages[i].content;
        break;
      }
    }
  }
  if (!userText) return;
  
  // Remove this bot message and all messages after it
  state.messages.splice(msgIdx);
  renderMessages();
  
  // Switch to the correct agent
  state.activeAgentId = agentId;
  renderAgentTabs();
  
  // Re-send
  lastUserText = userText;
  lastUserAgentId = agentId;
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  addMessage({ id: Date.now(), role: 'user', content: userText, time });

  try {
    await executeChatRequest({ text: userText, agentId });
  } catch {}
}

/* ===== Scroll to Bottom ===== */
function updateScrollBtn() {
  const container = document.getElementById('chat-messages');
  const btn = document.getElementById('scroll-bottom-btn');
  if (!container || !btn) return;
  const isScrolledUp = container.scrollHeight - container.scrollTop - container.clientHeight > 100;
  btn.classList.toggle('active', isScrolledUp);
}

// Enhanced scrollToBottom with smooth behavior
const origScrollToBottom = scrollToBottom;
scrollToBottom = function() {
  const c = document.getElementById('chat-messages');
  if (c) {
    c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' });
    setTimeout(updateScrollBtn, 200);
  }
};

/* ===== Utilities ===== */
function formatTime(dateStr, short) {
  const d = new Date(dateStr);
  if (short) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
  if (!text) return '';
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

function showToast(msg, type = 'info') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = type;
  requestAnimationFrame(() => requestAnimationFrame(() => t.classList.add('show')));
  clearTimeout(t._timeout);
  t._timeout = setTimeout(() => t.classList.remove('show'), 3000);
}

/* ===== Products ===== */
let currentProductName = '';

async function loadProducts() {
  try {
    const res = await fetch(`${API_BASE}/api/products`);
    if (!res.ok) return;
    const data = await res.json();
    renderProducts(data.products || [], data.categories || []);
  } catch {}
}

function renderProducts(products, categories) {
  const container = document.getElementById('products-content');
  if (!products.length) {
    container.innerHTML = '<div class="products-empty"><i class="ph ph-package"></i><p>暂无产品</p></div>';
    return;
  }

  const grouped = {};
  for (const p of products) {
    const cat = p.category || '其他';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(p);
  }

  const cats = categories || Object.keys(grouped);

  const colors = ['#8B5CF6', '#3B82F6', '#059669', '#EA580C', '#D97706', '#0284C7'];
  let html = '';
  for (const cat of cats) {
    const c = cat.replace(/\s+/g, '');
    html += `<div class="product-category">
      <h3 class="product-category-title">${escapeHtml(cat)}</h3>
      <div class="product-cloud">`;
    for (const p of grouped[cat]) {
      const c = colors[p.id % colors.length];
      html += `<button class="product-name-tag" style="background:${c}15;color:${c};border-color:${c}30" onclick="showProductDetail(${p.id})">${escapeHtml(p.name)}</button>`;
    }
    html += `</div></div>`;
  }
  container.innerHTML = html;
}

async function showProductDetail(id) {
  try {
    const res = await fetch(`${API_BASE}/api/products/${id}`);
    if (!res.ok) return;
    const item = await res.json();
    currentProductName = item.name;
    document.getElementById('product-cta-btn').textContent = `咨询「${item.name}」`;

    const tags = (item.highlights || '').split(',').filter(t => t.trim());
    const container = document.getElementById('product-detail-content');
    container.innerHTML = `
      <div class="product-detail-image">${item.image_url
        ? `<img src="${item.image_url}" alt="${escapeHtml(item.name)}">`
        : `<div class="placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <h1 class="product-detail-name">${escapeHtml(item.name)}</h1>
      ${item.summary ? `<p class="product-detail-summary">${escapeHtml(item.summary)}</p>` : ''}
      ${tags.length ? `<div class="product-detail-tags">${tags.map(t => `<span class="product-tag">${escapeHtml(t.trim())}</span>`).join('')}</div>` : ''}
      ${item.content ? `<div class="product-detail-content">${item.content}</div>` : ''}
    `;
    document.getElementById('product-detail-overlay').classList.add('active');
  } catch {}
}

function closeProductDetail() {
  document.getElementById('product-detail-overlay').classList.remove('active');
}

function consultProduct() {
  const name = currentProductName || '';
  closeProductDetail();
  const agent = AGENTS.find(a => a.type === '产品咨询') || AGENTS[0];
  if (agent) {
    state.activeAgentId = agent.id;
    renderAgentTabs();
  }
  document.getElementById('message-input').value = `${name}的配方是什么？有什么功效？怎么用？`;
  switchView('chat');
  sendMessage();
}

document.addEventListener('input', (e) => {
  if (e.target.id === 'message-input') {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  }
});
