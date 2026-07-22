/* ===== Send Message ===== */
async function sendMessage() {
  const input = document.getElementById('message-input');
  const text = input.value.trim();
  const handoffClassification = window.HandoffIntent?.classifyHandoffInput?.(text)
    || { isHandoffIntent: window.HandoffIntent?.isExplicitHandoffIntent?.(text) === true, questionText: '' };
  const isHandoffIntent = handoffClassification.isHandoffIntent === true;
  if (!text || (state.isStreaming && !state.handoff.session && !isHandoffIntent)) return;
  if (speechBusy()) {
    showToast('请先结束语音输入，再确认发送', 'info');
    return;
  }
  if (state.currentView !== 'chat') { switchView('chat'); setTimeout(() => sendMessage(), 200); return; }
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (state.handoff.session?.status === 'closed') resumeAiAfterHandoff();
  const humanSession = hasOpenHandoffSession();
  input.value = '';
  if (humanSession) {
    try {
      await sendHandoffMessage(text);
    } catch (error) {
      input.value = text;
      showToast(error.message || '消息发送失败', 'error');
    }
    return;
  }
  if (isHandoffIntent) {
    await handleHandoffIntent(text, time, handoffClassification);
    return;
  }
  lastUserText = text;
  lastUserAgentId = state.activeAgentId;
  addMessage({
    id: Date.now(),
    role: 'user',
    content: text,
    time,
    agentId: state.activeAgentId,
    nutritionMessage: state.handoff.isNutritionMode,
  });

  try {
    await executeChatRequest({ text, agentId: state.activeAgentId });
  } catch {}
}

function handleInputKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

// 轻量 Markdown 渲染（不引第三方库，仅覆盖常用场景）
function renderBotContent(text) {
  if (!text) return '';
  const escaped = escapeHtml(text);

  // 代码块 ```lang ... ``` → <pre><code>
  const codeBlockPattern = /```(\w*)\n([\s\S]*?)```/g;
  let html = escaped.replace(codeBlockPattern, (match, lang, code) => {
    const codeHtml = code.trim().split('\n').map(line => `<div class="code-line">${escapeHtml(line)}</div>`).join('');
    return `<div class="code-block" data-lang="${lang || 'text'}"><div class="code-block-header"><span class="code-lang">${lang || 'text'}</span></div><pre class="code-content">${codeHtml}</pre></div>`;
  });

  // 表格 | a | b | → <table>
  const tablePattern = /\|(.+)\|\n\|[-\s|:]+\|\n((?:\|.+\|\n?)+)/g;
  html = html.replace(tablePattern, (match, header, body) => {
    const ths = header.split('|').map(h => `<th>${escapeHtml(h.trim())}</th>`).join('');
    const rows = body.trim().split('\n').map(row => {
      const tds = row.split('|').filter((_, i, arr) => i > 0 && i < arr.length - 1).map(td => `<td>${escapeHtml(td.trim())}</td>`).join('');
      return `<tr>${tds}</tr>`;
    }).join('');
    return `<div class="table-wrapper"><table class="md-table"><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table></div>`;
  });

  // 加粗 **text** → <strong>
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // 无序列表 - / * → <ul><li>
  html = html.replace(/^(\s*)[*-]\s+(.+)$/gm, (match, indent, text) => `<div class="md-list-item">${text}</div>`);

  // 换行保留（已有 white-space: pre-wrap，但代码块内的换行需要特殊处理）
  // 对代码块内容不做换行替换，已在上面处理

  return html;
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

function renderMessageItem(msg, idx, existing = null) {
  const agent = msg.agentId ? AGENTS.find(a => a.id === msg.agentId) : AGENTS[0];
  const div = existing || document.createElement('div');
  div.className = `msg ${msg.role}`;
  div.dataset.msgId = msg.id;
  if (msg.role === 'system' || msg.role === 'handoff-system') {
    if (msg.role === 'handoff-system') div.classList.add('handoff-system');
    div.innerHTML = `<div class="system-bubble"><i class="ph ph-check-circle"></i><div class="sb-text">${msg.content}</div></div>`;
  } else if (msg.role === 'handoff-agent') {
    div.classList.add('handoff-agent');
    div.innerHTML = `<div class="msg-avatar"><i class="ph ph-headset"></i></div><div class="msg-body"><span class="msg-sender-name">在线营养师</span><div class="msg-bubble">${escapeHtml(msg.content)}</div><span class="msg-time">${msg.time || ''}</span></div>`;
  } else if (msg.role === 'bot') {
    const icon = agent ? agent.icon : 'sparkle';
    const color = agent ? agent.color : '#4F46E5';
    const renderedContent = renderBotContent(msg.content);
    const likeActive = msg.feedback === 1 ? ' active' : '';
    const dislikeActive = msg.feedback === 0 ? ' active' : '';
    const feedbackDisabled = msg.feedback !== undefined ? ' disabled' : '';
    const actions = !msg.isStreaming ? `
      <div class="msg-actions" role="group" aria-label="回复操作">
        <button class="msg-action-btn" onclick="copyText('${escapeHtml(msg.content).replace(/'/g, "\\'")}')"><i class="ph ph-copy-simple"></i> 复制</button>
        ${agent && agent.type === '产品咨询' ? '<button class="msg-action-btn" onclick="switchView(\'products\')"><i class="ph ph-shopping-bag"></i> 查看产品</button>' : ''}
        <button class="msg-action-btn share-action" onclick="shareAnswerCard(${idx})"><i class="ph ph-share-network"></i> 生成分享图</button>
        <button class="msg-action-btn" onclick="regenerateMsg(${idx})"><i class="ph ph-arrows-clockwise"></i> 重新回答</button>
        ${msg.historyId ? `
        <span class="msg-feedback-group" role="group" aria-label="回答反馈">
          <button class="msg-feedback-btn${likeActive}${feedbackDisabled}" aria-label="回答有帮助" title="回答有帮助" onclick="sendFeedback(${msg.historyId}, 1, ${idx})"><i class="ph ph-thumbs-up" aria-hidden="true"></i></button>
          <button class="msg-feedback-btn${dislikeActive}${feedbackDisabled}" aria-label="回答没帮助" title="回答没帮助" onclick="sendFeedback(${msg.historyId}, 0, ${idx})"><i class="ph ph-thumbs-down" aria-hidden="true"></i></button>
        </span>` : ''}
      </div>` : '';
    const relatedCases = !msg.isStreaming
      ? renderRelatedCases(msg.relatedCases || [], msg.replyToText || '', msg.relatedCasesTotal)
      : '';
    div.innerHTML = `<div class="msg-avatar" style="background:${color}"><i class="ph ph-${icon}"></i></div>
      <div class="msg-body"><div class="msg-bubble">${renderedContent}${msg.isStreaming ? '<span class="cursor-blink"></span>' : ''}</div>${relatedCases}<span class="msg-time">${msg.time}</span>${actions}</div>`;
  } else {
    div.innerHTML = `<div class="msg-avatar"><i class="ph ph-user"></i></div>
      <div class="msg-body"><div class="msg-bubble">${escapeHtml(msg.content)}</div><span class="msg-time">${msg.time}</span></div>`;
  }
  return div;
}

function renderMessages() {
  const container = document.getElementById('chat-messages');
  const emptyChat = document.getElementById('empty-chat');
  emptyChat.style.display = state.messages.length > 0 ? 'none' : 'flex';

  // Reconcile keyed message nodes instead of append-only rendering. This keeps
  // streaming nodes up to date and removes messages deleted from state.
  const existingById = new Map();
  container.querySelectorAll('.msg[data-msg-id]').forEach(el => {
    const id = String(el.dataset.msgId);
    if (existingById.has(id)) {
      el.remove();
    } else {
      existingById.set(id, el);
    }
  });

  const desiredIds = new Set(state.messages.map(msg => String(msg.id)));
  existingById.forEach((el, id) => {
    if (!desiredIds.has(id)) el.remove();
  });

  // appendChild moves existing nodes, so this also restores state order.
  state.messages.forEach((msg, idx) => {
    const msgId = String(msg.id);
    const div = renderMessageItem(msg, idx, existingById.get(msgId) || null);
    container.appendChild(div);
  });

  // Waiting/typing indicators are transient DOM nodes and are not in state;
  // keep them after the reconciled message list.
  [...container.children]
    .filter(el => !el.matches('.msg[data-msg-id]'))
    .forEach(el => container.appendChild(el));

  container.scrollTop = container.scrollHeight;
  updateScrollBtn();
}

function openLeadModal(messageIndex = -1) {
  const msg = messageIndex >= 0 ? state.messages[messageIndex] : null;
  const lastUser = messageIndex >= 0 ? latestUserQuestionBefore(messageIndex) : (lastUserText || '');
  document.getElementById('lead-description').value = lastUser ? `我想进一步了解：${lastUser}` : '';
  document.getElementById('lead-product').value = '';
  document.getElementById('lead-phone').value = '';
  document.getElementById('lead-wechat').value = '';
  document.getElementById('lead-error').textContent = '';
  const overlay = document.getElementById('lead-overlay');
  overlay.dataset.historyId = msg && msg.historyId ? msg.historyId : '';
  overlay.dataset.messageIndex = messageIndex;
  overlay.classList.add('active');
}

function closeLeadModal(event) {
  if (event && event.target !== event.currentTarget) return;
  document.getElementById('lead-overlay').classList.remove('active');
}

async function submitLeadRequest() {
  const overlay = document.getElementById('lead-overlay');
  const button = document.getElementById('lead-submit-btn');
  const error = document.getElementById('lead-error');
  const payload = {
    customer_type: document.getElementById('lead-customer-type').value,
    product_name: document.getElementById('lead-product').value.trim(),
    description: document.getElementById('lead-description').value.trim(),
    phone: document.getElementById('lead-phone').value.trim(),
    wechat: document.getElementById('lead-wechat').value.trim(),
    query_type: AGENTS.find(a => a.id === state.activeAgentId)?.type || '',
    agent_id: state.activeAgentId,
    history_id: overlay.dataset.historyId ? Number(overlay.dataset.historyId) : null,
  };
  error.textContent = '';
  if (!payload.description) { error.textContent = '请先填写您的需求'; return; }
  if (!payload.phone && !payload.wechat) { error.textContent = '手机号或微信号至少填写一项'; return; }
  button.disabled = true;
  button.textContent = '提交中...';
  try {
    const res = await fetch(`${API_BASE}/api/leads`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify(payload) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '提交失败，请稍后重试');
    closeLeadModal();
    showToast(data.message || '需求已提交', 'success');
  } catch (err) {
    error.textContent = err.message || '提交失败，请稍后重试';
  } finally {
    button.disabled = false;
    button.textContent = '提交需求';
  }
}

function splitTags(value) {
  return String(value || '').split(',').map(t => t.trim()).filter(Boolean);
}

function renderCaseTagList(value, className, tagType = '') {
  return splitTags(value).map(tag => {
    const safeTag = escapeHtml(tag);
    if (!tagType) return `<span class="${className}">${safeTag}</span>`;
    return `<button class="${className} clickable" onclick="openCaseDrawerList(event, '${tagType}', '${safeTag.replace(/'/g, "\\'")}')">${safeTag}</button>`;
  }).join('');
}

function renderRelatedCases(cases, query = '', total) {
  if (!cases || cases.length === 0) return '';
  const relatedTotal = Number.isFinite(Number(total)) ? Number(total) : cases.length;
  const showMore = query && relatedTotal > cases.length;
  const safeQuery = escapeHtml(query).replace(/'/g, "\\'");
  return `<div class="related-cases">
    <div class="related-cases-title">
      <span><i class="ph ph-files"></i>相关案例</span>
      ${showMore ? `<button class="related-cases-more" onclick="openRelatedCaseDrawerList(event, '${safeQuery}')">查看更多</button>` : ''}
    </div>
    <div class="related-case-list">
      ${cases.map(item => `
        <div class="related-case-card" role="button" tabindex="0" onclick="openCaseDrawerDetail(${Number(item.id)}, { openedFromList: false })">
          ${item.image_url ? renderImage(item.image_url, '', 'related-case-img') : `<div class="related-case-img placeholder"><i class="ph ph-file-text"></i></div>`}
          <div class="related-case-body">
            <div class="related-case-name">${escapeHtml(item.title || '')}</div>
            <div class="related-case-profile">${escapeHtml(item.customer_profile || item.scenario || '')}</div>
            <div class="related-case-summary">${escapeHtml(item.summary || '')}</div>
            <div class="related-case-tags">
              ${renderCaseTagList(item.symptom_tags, 'case-tag symptom', 'symptom')}
              ${renderCaseTagList(item.product_tags, 'case-tag product', 'product')}
            </div>
          </div>
        </div>
      `).join('')}
    </div>
  </div>`;
}

async function openCaseDetail(caseId) {
  return openCaseDrawerDetail(caseId, { openedFromList: false });
}

let caseDrawerState = {
  mode: 'list',
  page: 1,
  pages: 1,
  tagType: '',
  tag: '',
  query: '',
  lastListFilter: null,
  openedFromList: false,
};

function ensureCaseDrawer() {
  let overlay = document.getElementById('case-drawer-overlay');
  if (overlay) return overlay;
  overlay = document.createElement('div');
  overlay.id = 'case-drawer-overlay';
  overlay.className = 'case-drawer-overlay';
  overlay.innerHTML = `
    <div class="case-drawer-panel" onclick="event.stopPropagation()">
      <div class="case-drawer-header" id="case-drawer-header"></div>
      <div id="case-drawer-body" class="case-drawer-body"></div>
      <div id="case-drawer-more-wrap" class="case-drawer-more-wrap" style="display:none">
        <button class="discover-more-btn" onclick="loadMoreCases()">加载更多</button>
      </div>
    </div>`;
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeCaseDrawer();
  });
  document.body.appendChild(overlay);
  return overlay;
}

function renderCaseDrawerHeader({ title, kicker = '案例档案', showBack = false }) {
  const header = document.getElementById('case-drawer-header');
  if (!header) return;
  header.innerHTML = `
    <div class="case-drawer-title-wrap">
      ${showBack ? `<button class="case-drawer-back" onclick="backToCaseList()"><i class="ph ph-caret-left"></i></button>` : ''}
      <div>
        <div class="case-list-kicker">${escapeHtml(kicker)}</div>
        <h3>${escapeHtml(title || '案例档案')}</h3>
      </div>
    </div>
    <button class="case-detail-close" onclick="closeCaseDrawer()"><i class="ph ph-x"></i></button>`;
}

async function openCaseDrawerDetail(caseId, options = {}) {
  ensureCaseDrawer();
  try {
    const res = await fetch(`${API_BASE}/api/cases/${caseId}`);
    const item = await res.json();
    if (!res.ok) {
      showToast(item.error || '案例不存在', 'error');
      return;
    }
    caseDrawerState.mode = 'detail';
    caseDrawerState.openedFromList = !!options.openedFromList;
    renderCaseDrawerDetail(item);
  } catch {
    showToast('案例加载失败', 'error');
  }
}

function renderCaseDrawerDetail(item) {
  renderCaseDrawerHeader({
    title: item.title || '案例详情',
    kicker: '客户案例档案',
    showBack: caseDrawerState.openedFromList && !!caseDrawerState.lastListFilter,
  });
  const body = document.getElementById('case-drawer-body');
  const more = document.getElementById('case-drawer-more-wrap');
  if (more) more.style.display = 'none';
  if (!body) return;
  body.className = 'case-drawer-body case-drawer-detail-body';
  body.innerHTML = `
      ${item.image_url ? renderImage(item.image_url, item.title || '', 'case-detail-hero', { thumb: false }) : ''}
      <div class="case-detail-content">
        <p class="case-detail-profile">${escapeHtml(item.customer_profile || '')}</p>
        <div class="case-detail-tags">
          ${renderCaseTagList(item.symptom_tags, 'case-tag symptom', 'symptom')}
          ${renderCaseTagList(item.product_tags, 'case-tag product', 'product')}
        </div>
        <div class="case-detail-section"><strong>使用场景</strong><p>${escapeHtml(item.scenario || '')}</p></div>
        <div class="case-detail-section"><strong>案例摘要</strong><p>${escapeHtml(item.summary || '')}</p></div>
        <div class="case-detail-section"><strong>详细记录</strong><p>${escapeHtml(item.content || '')}</p></div>
        <div class="case-detail-actions">
          <button class="case-secondary-btn" onclick="openSimilarFromCase(event, '${escapeHtml(item.symptom_tags || '')}', '${escapeHtml(item.product_tags || '')}')"><i class="ph ph-tag"></i> 查看相似案例</button>
          ${caseLibraryUrl ? `<button class="case-primary-btn" onclick="openExternalCase(event, '${escapeHtml(caseLibraryUrl).replace(/'/g, "\\'")}')"><i class="ph ph-books"></i> 查看更多客户案例</button>` : ''}
        </div>
      </div>`;
}

function closeCaseDetail() {
  closeCaseDrawer();
}

function closeCaseDrawer() {
  document.getElementById('case-drawer-overlay')?.remove();
}

function openExternalCase(event, url) {
  event?.stopPropagation();
  if (!url) return;
  window.open(url, '_blank', 'noopener,noreferrer');
}

function openSimilarFromCase(event, symptomTags, productTags) {
  event?.stopPropagation();
  const symptom = splitTags(symptomTags)[0];
  if (symptom) {
    openCaseDrawerList(event, 'symptom', symptom);
    return;
  }
  const product = splitTags(productTags)[0];
  if (product) {
    openCaseDrawerList(event, 'product', product);
    return;
  }
  showToast('暂无相似案例', 'info');
}

async function openCasesByTag(event, tagType, tag) {
  return openCaseDrawerList(event, tagType, tag);
}

async function openRelatedCaseDrawerList(event, query) {
  event?.stopPropagation();
  query = (query || '').trim();
  if (!query) return;
  ensureCaseDrawer();
  caseDrawerState.mode = 'related';
  caseDrawerState.page = 1;
  caseDrawerState.pages = 1;
  caseDrawerState.tagType = '';
  caseDrawerState.tag = '';
  caseDrawerState.query = query;
  caseDrawerState.openedFromList = false;
  caseDrawerState.lastListFilter = {
    mode: 'related',
    query,
  };
  renderCaseDrawerHeader({
    title: '更多相关案例',
    kicker: '本次问题匹配',
    showBack: false,
  });
  const body = document.getElementById('case-drawer-body');
  if (body) {
    body.className = 'case-drawer-body case-list-body';
    body.innerHTML = '<div id="case-list-items"><div class="case-list-empty">加载中...</div></div>';
  }
  await loadCases(true);
}

async function openCaseDrawerList(event, tagType, tag) {
  event?.stopPropagation();
  ensureCaseDrawer();
  caseDrawerState.mode = 'list';
  caseDrawerState.page = 1;
  caseDrawerState.pages = 1;
  caseDrawerState.tagType = tagType || '';
  caseDrawerState.tag = tag || '';
  caseDrawerState.query = '';
  caseDrawerState.openedFromList = false;
  caseDrawerState.lastListFilter = {
    mode: 'list',
    tagType: caseDrawerState.tagType,
    tag: caseDrawerState.tag,
  };
  renderCaseDrawerHeader({
    title: caseDrawerState.tag ? `${caseDrawerState.tag} 相关案例` : '全部案例',
    kicker: '案例档案',
    showBack: false,
  });
  const body = document.getElementById('case-drawer-body');
  if (body) {
    body.className = 'case-drawer-body case-list-body';
    body.innerHTML = '<div id="case-list-items"><div class="case-list-empty">加载中...</div></div>';
  }
  await loadCases(true);
}

function closeCaseList() {
  closeCaseDrawer();
}

function backToCaseList() {
  const filter = caseDrawerState.lastListFilter || { tagType: '', tag: '' };
  if (filter.mode === 'related') {
    openRelatedCaseDrawerList(null, filter.query || '');
    return;
  }
  openCaseDrawerList(null, filter.tagType, filter.tag);
}

async function loadCases(reset = false) {
  const body = document.getElementById('case-list-items');
  if (!body) return;
  if (reset) body.innerHTML = '<div class="case-list-empty">加载中...</div>';
  const params = new URLSearchParams({
    page: String(caseDrawerState.page),
    limit: '10',
  });
  let url = `${API_BASE}/api/cases`;
  if (caseDrawerState.mode === 'related') {
    params.set('q', caseDrawerState.query || '');
    url = `${API_BASE}/api/cases/search`;
  } else if (caseDrawerState.tagType && caseDrawerState.tag) {
    params.set('tag_type', caseDrawerState.tagType);
    params.set('tag', caseDrawerState.tag);
  }
  try {
    const res = await fetch(`${url}?${params.toString()}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '加载失败');
    caseDrawerState.page = data.page || 1;
    caseDrawerState.pages = data.pages || 1;
    const html = renderCaseListItems(data.items || []);
    if (reset) body.innerHTML = html || '<div class="case-list-empty">暂无相关案例</div>';
    else body.insertAdjacentHTML('beforeend', html);
    const more = document.getElementById('case-drawer-more-wrap');
    if (more) more.style.display = caseDrawerState.page < caseDrawerState.pages ? 'flex' : 'none';
  } catch {
    body.innerHTML = '<div class="case-list-empty">案例加载失败</div>';
  }
}

function renderCaseListItems(items) {
  return items.map(item => `
    <div class="case-list-item" role="button" tabindex="0" onclick="openCaseDrawerDetail(${Number(item.id)}, { openedFromList: true })">
      ${item.image_url ? renderImage(item.image_url, '', 'case-list-img') : `<div class="case-list-img placeholder"><i class="ph ph-file-text"></i></div>`}
      <div class="case-list-info">
        <div class="case-list-name">${escapeHtml(item.title || '')}</div>
        <div class="case-list-profile">${escapeHtml(item.customer_profile || item.scenario || '')}</div>
        <div class="case-list-summary">${escapeHtml(item.summary || '')}</div>
        <div class="related-case-tags">
          ${renderCaseTagList(item.symptom_tags, 'case-tag symptom', 'symptom')}
          ${renderCaseTagList(item.product_tags, 'case-tag product', 'product')}
        </div>
      </div>
    </div>
  `).join('');
}

async function loadMoreCases() {
  if (caseDrawerState.page >= caseDrawerState.pages) return;
  caseDrawerState.page += 1;
  await loadCases(false);
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
let wbQueueMode = false;

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
  wbQueueMode = false;
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

function setWaitingQueueStatus(message, canCancel = true) {
  if (!wbMsgId) showWaitingPanel();
  if (!wbMsgId) return;
  wbQueueMode = true;
  clearInterval(wbStepTimer);
  clearInterval(wbTipTimer);
  wbStepTimer = null;
  wbTipTimer = null;
  const bubble = document.getElementById(wbMsgId + '-bubble');
  if (!bubble) return;
  bubble.innerHTML =
    `<div class="wb-step"><i class="ph ph-hourglass"></i><span>${escapeHtml(message || '正在排队...')}</span></div>` +
    '<div class="wb-dots"><span class="wb-dot"></span><span class="wb-dot"></span><span class="wb-dot"></span></div>' +
    (canCancel ? '<button type="button" class="wb-cancel-btn" onclick="cancelQueuedChat()">取消排队</button>' : '');
  scrollToBottom();
}

async function cancelQueuedChat() {
  const jobId = state.chatJobId || (() => {
    try { return JSON.parse(localStorage.getItem('chat_pending_job') || 'null')?.jobId || ''; } catch { return ''; }
  })();
  if (!jobId) return;
  state.chatQueueCanceling = true;
  try {
    const res = await fetch(`${API_BASE}/api/chat/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok && data.error_code !== 'chat_job_running') {
      throw new Error(data.error || '取消排队失败');
    }
    if (data.error_code === 'chat_job_running') {
      showToast(data.error || '任务已经开始生成，暂时不能取消', 'info');
      state.chatQueueCanceling = false;
      return;
    }
    localStorage.removeItem('chat_pending_job');
    state.chatJobId = null;
    state.chatAbortController?.abort();
    hideWaitingPanel();
    showToast('已取消排队', 'info');
  } catch (error) {
    state.chatQueueCanceling = false;
    showToast(error.message || '取消排队失败', 'error');
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
  wbQueueMode = false;
  if (wbMsgId) {
    const el = document.getElementById(wbMsgId);
    if (el) el.remove();
    wbMsgId = null;
  }
}

async function streamResponse(text, historyId) {
  addBotMessage(text, { historyId, agentId: state.activeAgentId });
}
