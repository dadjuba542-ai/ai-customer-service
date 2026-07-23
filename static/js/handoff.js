/* ===== Nutrition consultation / AI to human handoff ===== */
async function loadHandoffConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/handoff/config`);
    if (!res.ok) {
      state.handoff.config = null;
      return false;
    }
    state.handoff.config = await res.json();
    const ai = state.handoff.config.ai_agent;
    if (ai && !AGENTS.some(a => a.id === ai.agent_id)) {
      AGENTS.push({
        id: ai.agent_id, name: ai.name, type: ai.type || '营养咨询',
        description: ai.chat_desc || '营养健康咨询', chatDesc: ai.chat_desc || '',
        icon: 'heartbeat', color: '#0F766E', bg: '#F0FDFA',
      });
    }
    renderQuickFunctions();
    updateHandoffUi();
    return true;
  } catch {
    state.handoff.config = null;
    return false;
  }
}

function updateHandoffUi() {
  const config = state.handoff.config;
  const session = state.handoff.session;
  const banner = document.getElementById('handoff-status');
  const input = document.getElementById('message-input');
  document.getElementById('chat-view')?.classList.toggle('chat-view-nutrition', !!state.handoff.isNutritionMode);
  if (!session || !state.handoff.isNutritionMode) {
    if (banner) banner.hidden = true;
    if (input) input.placeholder = '说点什么...';
    return;
  }
  banner.hidden = false;
  const title = document.getElementById('handoff-status-title');
  const detail = document.getElementById('handoff-status-detail');
  const action = document.getElementById('handoff-status-action');
  const deferAction = document.getElementById('handoff-defer-action');
  if (session.service_mode === 'message') {
    title.textContent = '已转为留言，等待营养师回复';
    detail.textContent = '可继续使用 AI 或浏览其他内容，回复后会在前台提示';
    action.textContent = '返回首页'; action.dataset.action = 'home';
    deferAction.hidden = true;
    input.placeholder = '继续向 AI 提问...';
    return;
  }
  deferAction.hidden = false;
  if (session.status === 'queued') {
    title.textContent = session.queue_position ? `正在排队，第 ${session.queue_position} 位` : '正在等待营养师';
    detail.textContent = `最多在线等待约 ${Math.max(1, Math.ceil(Number(session.live_wait_sec || config?.live_wait_sec || 600) / 60))} 分钟，超时自动转留言`;
    deferAction.textContent = '立即转留言';
    action.textContent = '取消排队'; action.dataset.action = 'cancel';
    input.placeholder = '给营养师补充问题...';
  } else if (session.status === 'assigned') {
    title.textContent = '营养师已收到，正在接入'; detail.textContent = `超过 ${Math.max(1, Math.ceil(Number(session.live_wait_sec || config?.live_wait_sec || 600) / 60))} 分钟未回复将自动转留言`;
    deferAction.textContent = '立即转留言';
    action.textContent = '取消转接'; action.dataset.action = 'cancel'; input.placeholder = '给营养师补充问题...';
  } else if (session.status === 'active') {
    title.textContent = '在线营养师';
    detail.textContent = '当前消息将由真人营养师回复'; deferAction.textContent = '暂时挂起';
    action.textContent = '结束咨询'; action.dataset.action = 'close'; input.placeholder = '给营养师留言...';
  } else {
    banner.hidden = true;
    input.placeholder = '请继续向 AI 提问...';
  }
}

function hasOpenHandoffSession() {
  return !!(
    state.handoff.session
      && state.handoff.session.service_mode !== 'message'
      && ['queued', 'assigned', 'active'].includes(state.handoff.session.status)
  );
}

function activateAiWhileMessagePending() {
  state.handoff.isNutritionMode = true;
  const ai = ensureConfiguredHandoffAgent();
  if (ai) state.activeAgentId = ai.agent_id;
  renderAgentTabs();
  updateHandoffUi();
  focusInput();
}

function resetClosedHandoffSession() {
  if (state.handoff.session?.status !== 'closed') return;
  state.handoff.session = null;
  state.handoff.lastMessageId = 0;
  localStorage.removeItem('handoff_session_id');
}

function resumeAiAfterHandoff({ announce = true } = {}) {
  if (state.handoff.session && state.handoff.session.status !== 'closed') return false;
  if (state.handoff.session?.service_mode === 'message') announce = false;
  clearInterval(state.handoff.pollTimer);
  state.handoff.pollTimer = null;
  state.handoff.session = null;
  state.handoff.lastMessageId = 0;
  localStorage.removeItem('handoff_session_id');
  state.handoff.isNutritionMode = true;
  const ai = ensureConfiguredHandoffAgent();
  if (ai) state.activeAgentId = ai.agent_id;
  renderAgentTabs();
  updateHandoffUi();
  const input = document.getElementById('message-input');
  if (input) input.placeholder = '请继续向 AI 提问...';
  if (announce) {
    addMessage({
      id: `hs-ai-${Date.now()}`,
      role: 'handoff-system',
      content: `本次人工咨询已结束，已自动返回${ai?.name ? `「${escapeHtml(ai.name)}」` : ' AI'}。如仍需真人，请再次输入“转人工”。`,
    });
  }
  return true;
}

function canOfferHumanHandoff() {
  return state.activeAgentId === HANDOFF_TRIGGER_AGENT_ID || state.handoff.isNutritionMode;
}

function ensureConfiguredHandoffAgent() {
  const ai = state.handoff.config?.ai_agent;
  if (!ai || AGENTS.some(agent => agent.id === ai.agent_id)) return ai;
  AGENTS.push({
    id: ai.agent_id,
    name: ai.name,
    type: ai.type || '营养咨询',
    description: ai.chat_desc || '营养健康咨询',
    chatDesc: ai.chat_desc || '',
    icon: 'heartbeat',
    color: '#0F766E',
    bg: '#F0FDFA',
  });
  return ai;
}

function closeHandoffChoice(event) {
  const overlay = document.getElementById('handoff-choice-overlay');
  if (event && event.target !== overlay) return;
  overlay.classList.remove('active');
  overlay.setAttribute('aria-hidden', 'true');
  focusInput();
}

function latestMeaningfulHandoffQuestion() {
  return [...state.messages].reverse().find(message => (
    message.role === 'user'
      && !message.handoffIntent
      && !message.handoffMessageId
      && !message.restoredAiContext
      && String(message.content || '').trim()
  ))?.content?.trim() || '';
}

function handoffContextHistoryIds() {
  const ids = [];
  state.messages.forEach((message) => {
    if (message.role !== 'bot' || !message.historyId) return;
    const id = String(message.historyId);
    if (!ids.includes(id)) ids.push(id);
  });
  return ids.slice(-20);
}

function syncHandoffDraftState() {
  const note = document.getElementById('handoff-choice-note');
  const button = document.getElementById('handoff-choice-human');
  const error = document.getElementById('handoff-choice-note-error');
  if (!note || !button) return;
  const hasNote = !!note.value.trim();
  button.disabled = !state.handoff.config?.enabled || !hasNote;
  if (hasNote && error) error.textContent = '';
}

function openHandoffChoice() {
  const config = state.handoff.config;
  const ai = ensureConfiguredHandoffAgent();
  const overlay = document.getElementById('handoff-choice-overlay');
  const aiName = document.getElementById('handoff-choice-ai-name');
  const status = document.getElementById('handoff-choice-status');
  const humanButton = document.getElementById('handoff-choice-human');
  const note = document.getElementById('handoff-choice-note');
  const noteError = document.getElementById('handoff-choice-note-error');

  aiName.textContent = ai?.name ? `将由「${ai.name}」继续解答` : '专用营养 AI 暂未配置，将继续使用当前 AI';
  humanButton.textContent = config?.online ? '确认并联系营养师' : '确认并提交留言';
  note.value = state.handoff.draftInitialQuestion || '';
  noteError.textContent = '';
  if (!config) {
    status.textContent = '人工咨询配置暂不可用';
  } else if (!config.enabled) {
    status.textContent = '人工咨询暂未开启，可继续使用 AI';
  } else if (config.online) {
    status.textContent = '当前有营养师在线，将附上本次 AI 对话作为参考';
  } else {
    status.textContent = config.offline_msg || '营养师暂未在线，可先留言等待';
  }
  overlay.classList.add('active');
  overlay.setAttribute('aria-hidden', 'false');
  syncHandoffDraftState();
  document.getElementById('handoff-choice-ai').focus();
}

function chooseHandoffAi() {
  closeHandoffChoice();
  resetClosedHandoffSession();
  const ai = ensureConfiguredHandoffAgent();
  if (ai) {
    state.handoff.isNutritionMode = true;
    state.activeAgentId = ai.agent_id;
    renderAgentTabs();
    updateHandoffUi();
    addMessage({
      id: `hs-${Date.now()}`,
      role: 'handoff-system',
      content: `已切换到「${escapeHtml(ai.name)}」，请继续描述你的问题，AI 会优先为你解答。`,
    });
  } else {
    addMessage({ id: `hs-${Date.now()}`, role: 'handoff-system', content: '请继续描述你的问题，当前 AI 会优先为你解答。' });
  }
  document.getElementById('message-input').placeholder = '请描述需要解决的问题...';
  focusInput();
}

function switchToHandoffEligibleAgent() {
  if (!AGENTS.some(agent => agent.id === HANDOFF_TRIGGER_AGENT_ID)) {
    return showToast('深度调理答疑暂不可用', 'error');
  }
  switchAgent(HANDOFF_TRIGGER_AGENT_ID);
  switchView('chat');
  focusInput();
}

async function handleHandoffIntent(text, time, classification = {}) {
  const draft = String(classification.questionText || '').trim() || latestMeaningfulHandoffQuestion();
  state.handoff.draftInitialQuestion = draft;
  addMessage({
    id: `hs-${Date.now()}`,
    role: 'handoff-system',
    content: draft ? '已识别转人工请求，请确认给营养师的留言内容。' : '已识别转人工请求，请补充想让营养师了解的问题。',
  });
  if (state.handoff.session?.service_mode === 'message' && ['queued', 'assigned', 'active'].includes(state.handoff.session.status)) {
    addMessage({
      id: `hs-${Date.now()}`,
      role: 'handoff-system',
      content: '你已有一条营养师留言正在处理中，无需重复转接；可以继续向 AI 提问。',
    });
    return;
  }
  if (!canOfferHumanHandoff()) {
    addMessage({
      id: `hs-${Date.now()}`,
      role: 'handoff-system',
      content: '人工营养咨询仅支持「深度调理答疑」。<button type="button" class="handoff-inline-action" onclick="switchToHandoffEligibleAgent()">切换到深度调理答疑</button>',
    });
    return;
  }
  // 后台设置可能刚刚变更，不能只依赖页面首次加载时的旧配置。
  await loadHandoffConfig();
  openHandoffChoice();
}

async function chooseHumanHandoff() {
  const note = document.getElementById('handoff-choice-note')?.value.trim() || '';
  const error = document.getElementById('handoff-choice-note-error');
  if (!note) {
    if (error) error.textContent = '请先填写要咨询的问题，再联系营养师';
    document.getElementById('handoff-choice-note')?.focus();
    return;
  }
  closeHandoffChoice();
  await startHumanHandoff(note);
}

async function startHumanHandoff(note) {
  if (!state.handoff.config?.enabled) return showToast('人工咨询暂未开启，请继续使用 AI', 'error');
  note = String(note || '').trim();
  if (!note) return showToast('请先填写要咨询的问题', 'error');
  resetClosedHandoffSession();
  state.handoff.isNutritionMode = true;
  updateHandoffUi();
  state.handoff.interrupting = true;
  if (state.chatAbortController) state.chatAbortController.abort();
  const historyIds = handoffContextHistoryIds();
  try {
    const res = await fetch(`${API_BASE}/api/handoff/start`, {
      method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        history_ids: historyIds,
        query_type: state.handoff.config.ai_agent?.type || '营养咨询',
        note,
        service_mode: state.handoff.config?.online ? 'live' : 'message',
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '转接失败');
    state.handoff.session = data.session;
    state.handoff.lastMessageId = 0;
    state.handoff.pendingInitialQuestion = note;
    state.handoff.draftInitialQuestion = '';
    localStorage.setItem('handoff_session_id', data.session.session_id);
    await pollHandoffSession();
    startHandoffPolling();
    showToast(
      data.session.service_mode === 'message'
        ? '留言已提交，营养师稍后回复'
        : '已发起转接，可继续给营养师留言',
      'success',
    );
  } catch (error) {
    showToast(error.message || '转接失败', 'error');
  } finally {
    state.handoff.interrupting = false;
  }
}

async function restoreHandoffSession() {
  if (!state.handoff.config) await loadHandoffConfig();
  try {
    let res = await fetch(`${API_BASE}/api/handoff/current`, { headers: authHeaders() });
    if (!res.ok) return;
    let data = await res.json();
    let session = data.session;
    if (!session) {
      // A message-mode session is automatically closed after the nutritionist
      // replies, so it is no longer returned by /current. Recover the latest
      // unread closed handoff without relying only on localStorage.
      res = await fetch(`${API_BASE}/api/handoff/recent?limit=20`, { headers: authHeaders() });
      if (res.ok) {
        const recent = await res.json();
        const unread = (recent.sessions || []).find(item => (
          item.service_mode === 'message'
          && item.status === 'closed'
          && Number(item.unread_count || 0) > 0
        ));
        if (unread) {
          const detailRes = await fetch(`${API_BASE}/api/handoff/session/${encodeURIComponent(unread.session_id)}`, { headers: authHeaders() });
          if (detailRes.ok) session = (await detailRes.json()).session;
        }
      }
    }
    if (!session) {
      const stored = localStorage.getItem('handoff_session_id');
      if (stored) {
        res = await fetch(`${API_BASE}/api/handoff/session/${encodeURIComponent(stored)}`, { headers: authHeaders() });
        if (res.ok) session = (await res.json()).session;
      }
    }
    if (!session) return;
    state.handoff.isNutritionMode = true;
    state.handoff.session = session;
    const handoffAgentId = session.ai_agent_id || state.handoff.config?.ai_agent?.agent_id;
    if (handoffAgentId && AGENTS.some(agent => agent.id === handoffAgentId)) {
      state.activeAgentId = handoffAgentId;
    }
    renderAgentTabs();
    localStorage.setItem('handoff_session_id', session.session_id);
    // A closed message is a one-way nutritionist note. Do not expose the
    // original handoff question or the AI context in the user's chat.
    const messageOnly = session.service_mode === 'message';
    if (!messageOnly) restoreAiContext(session.ai_context || []);
    await loadHandoffMessages();
    if (session.status === 'closed') {
      resumeAiAfterHandoff();
      return;
    }
    updateHandoffUi();
    if (['queued', 'assigned', 'active'].includes(session.status)) startHandoffPolling();
  } catch {}
}

function restoreAiContext(context) {
  if (state.messages.some(m => m.restoredAiContext)) return;
  context.forEach((item, index) => {
    state.messages.push({
      id: `hc-${index}`, role: item.role === 'ai' ? 'bot' : 'user', content: item.text,
      time: item.at ? formatTime(item.at, true) : '', agentId: state.handoff.config?.ai_agent?.agent_id,
      restoredAiContext: true,
    });
  });
  if (context.length) state.messages.push({ id: 'handoff-divider', role: 'handoff-system', content: '以下为人工营养咨询' });
  renderMessages();
}

function startHandoffPolling() {
  clearInterval(state.handoff.pollTimer);
  const seconds = Math.max(2, Number(state.handoff.config?.poll_sec) || 4);
  state.handoff.pollTimer = setInterval(pollHandoffSession, seconds * 1000);
}

async function pollHandoffSession() {
  const sessionId = state.handoff.session?.session_id;
  if (!sessionId) return;
  try {
    const res = await fetch(`${API_BASE}/api/handoff/session/${encodeURIComponent(sessionId)}`, { headers: authHeaders() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '会话状态更新失败');
    const before = state.handoff.session?.status;
    const beforeMode = state.handoff.session?.service_mode || 'live';
    state.handoff.session = data.session;
    await loadHandoffMessages();
    if (before !== data.session.status && data.session.status === 'active') showToast('营养师已接入', 'success');
    if (beforeMode !== 'message' && data.session.service_mode === 'message') {
      activateAiWhileMessagePending();
      showToast('等待超时，已转为留言；你可以继续使用 AI', 'success');
    }
    if (data.session.status === 'closed') {
      resumeAiAfterHandoff();
      return;
    }
    updateHandoffUi();
  } catch {}
}

async function loadHandoffMessages() {
  const sessionId = state.handoff.session?.session_id;
  if (!sessionId) return false;
  const res = await fetch(`${API_BASE}/api/handoff/messages/${encodeURIComponent(sessionId)}?after_id=${state.handoff.lastMessageId}&limit=100`, { headers: authHeaders() });
  if (!res.ok) return false;
  const data = await res.json();
  let added = false;
  const messageOnly = state.handoff.session?.service_mode === 'message';
  (data.messages || []).forEach((item) => {
    state.handoff.lastMessageId = Math.max(state.handoff.lastMessageId, item.id);
    if (state.messages.some(m => m.handoffMessageId === item.id)) return;
    if (messageOnly && item.sender_role !== 'agent') return;
    if (item.sender_role === 'system' && item.content === '营养师已回复留言，本次留言已完成') return;
    if (item.sender_role === 'user' && state.handoff.pendingInitialQuestion === item.content) {
      const existing = [...state.messages].reverse().find(message => (
        message.role === 'user'
          && !message.handoffIntent
          && !message.handoffMessageId
          && message.content === item.content
      ));
      state.handoff.pendingInitialQuestion = '';
      if (existing) {
        existing.handoffMessageId = item.id;
        return;
      }
    }
    const asyncAgentReply = item.sender_role === 'agent' && messageOnly;
    const content = asyncAgentReply ? `营养师留言：${item.content}` : item.content;
    state.messages.push({
      id: `hm-${item.id}`, handoffMessageId: item.id,
      role: item.sender_role === 'agent' ? 'handoff-agent' : item.sender_role === 'system' ? 'handoff-system' : 'user',
      content, time: item.created_at ? formatTime(item.created_at, true) : '',
    });
    if (asyncAgentReply) showToast(content, 'success');
    added = true;
  });
  if (added) renderMessages();
  return added;
}

async function sendHandoffMessage(content) {
  const sessionId = state.handoff.session?.session_id;
  if (!sessionId) return;
  const res = await fetch(`${API_BASE}/api/handoff/message`, {
    method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ session_id: sessionId, content }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || '消息发送失败');
  const item = data.message;
  state.handoff.lastMessageId = Math.max(state.handoff.lastMessageId, item.id);
  addMessage({ id: `hm-${item.id}`, handoffMessageId: item.id, role: 'user', content: item.content, time: formatTime(item.created_at, true) });
}

async function handleHandoffStatusAction() {
  const action = document.getElementById('handoff-status-action')?.dataset.action;
  if (action === 'home') {
    switchView('home');
    return;
  }
  if (action === 'ai') {
    resumeAiAfterHandoff();
    return;
  }
  if (!confirm(action === 'close' ? '确认结束本次人工咨询？' : '确认取消人工转接？')) return;
  const sessionId = state.handoff.session?.session_id;
  if (!sessionId) return;
  try {
    const res = await fetch(`${API_BASE}/api/handoff/close`, {
      method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ session_id: sessionId, reason: action === 'close' ? 'done' : 'user_cancel' }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '操作失败');
    state.handoff.session = data.session;
    await loadHandoffMessages();
    if (data.session.status === 'closed') resumeAiAfterHandoff();
    else updateHandoffUi();
  } catch (error) { showToast(error.message, 'error'); }
}

async function deferHandoffSession() {
  const sessionId = state.handoff.session?.session_id;
  if (!sessionId || !hasOpenHandoffSession()) return;
  try {
    const res = await fetch(`${API_BASE}/api/handoff/defer`, {
      method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '转留言失败');
    state.handoff.session = data.session;
    await loadHandoffMessages();
    activateAiWhileMessagePending();
    showToast('已转为留言，营养师回复后会在前台提示', 'success');
  } catch (error) {
    showToast(error.message || '转留言失败', 'error');
  }
}
