const API = '';
const state = {
  token: localStorage.getItem('token') || '',
  user: null,
  agent: null,
  sessions: [],
  viewMode: 'live',
  activeSessionId: '',
  activeDetail: null,
  activeDetailMode: 'live',
  liveSessionId: '',
  returnSessionId: '',
  archiveItems: [],
  archivePagination: { page: 1, pages: 1, total: 0 },
  archiveLoading: false,
  selectedArchiveIds: new Set(),
  historyItems: [],
  historyKey: '',
  queueTimer: null,
  heartbeatTimer: null,
  initialQueueLoaded: false,
  previousStatuses: new Map(),
  notificationCursor: JSON.parse(localStorage.getItem('consultant_notification_cursor') || '{"session_id":0,"message_id":0}'),
  notificationReady: false,
  soundEnabled: localStorage.getItem('consultant_sound') !== '0',
  audioContext: null,
  primaryModule: 'consultations',
  reviewItems: [],
  reviewPagination: { page: 1, pages: 1, total: 0 },
  reviewActiveId: 0,
  reviewLoading: false,
  reviewEditingNote: false,
};

const $ = (id) => document.getElementById(id);

function authHeaders(extra = {}) {
  return { ...extra, Authorization: `Bearer ${state.token}` };
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function toast(message, type = '') {
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  $('toast-region').appendChild(node);
  setTimeout(() => node.remove(), 3800);
}

function resetToLogin(message = '') {
  clearInterval(state.queueTimer);
  clearInterval(state.heartbeatTimer);
  state.queueTimer = null;
  state.heartbeatTimer = null;
  state.token = '';
  state.user = null;
  state.agent = null;
  state.sessions = [];
  state.viewMode = 'live';
  state.activeSessionId = '';
  state.activeDetail = null;
  state.activeDetailMode = 'live';
  state.liveSessionId = '';
  state.returnSessionId = '';
  state.archiveItems = [];
  state.archivePagination = { page: 1, pages: 1, total: 0 };
  state.selectedArchiveIds.clear();
  state.historyItems = [];
  state.historyKey = '';
  state.initialQueueLoaded = false;
  state.previousStatuses.clear();
  state.notificationReady = false;
  state.primaryModule = 'consultations';
  state.reviewItems = [];
  state.reviewPagination = { page: 1, pages: 1, total: 0 };
  state.reviewActiveId = 0;
  state.reviewEditingNote = false;
  localStorage.removeItem('token');
  localStorage.removeItem('user');

  $('settings-modal').hidden = true;
  $('workspace').hidden = true;
  $('login-page').hidden = false;
  $('live-tab').classList.add('active');
  $('archive-tab').classList.remove('active');
  $('live-session-pane').hidden = false;
  $('archive-session-pane').hidden = true;
  $('archive-filter-form').reset();
  $('login-password').value = '';
  $('login-error').textContent = message;
  $('mine-list').innerHTML = '';
  $('queue-list').innerHTML = '';
  $('archive-list').innerHTML = '';
  $('history-list').innerHTML = '';
  $('message-list').innerHTML = '';
  $('ai-context-list').innerHTML = '';
  $('review-list').innerHTML = '';
  renderReviewDetail();
  $('active-chat').hidden = true;
  $('empty-chat').hidden = false;
  setTimeout(() => $('login-username').focus(), 0);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { ...options, headers: authHeaders(options.headers || {}) });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    resetToLogin('登录已过期，请重新登录');
    throw new Error('登录已过期，请重新登录');
  }
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

async function login(event) {
  event.preventDefault();
  const button = $('login-button');
  button.disabled = true;
  $('login-error').textContent = '';
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: $('login-username').value.trim(), password: $('login-password').value }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.is_admin) throw new Error(data.error || '该账号没有后台权限');
    state.token = data.token;
    localStorage.setItem('token', data.token);
    $('settings-modal').hidden = true;
    await bootWorkspace();
  } catch (error) {
    $('login-error').textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function bootWorkspace() {
  try {
    state.user = await api('/api/user/profile');
    if (!state.user.is_admin) throw new Error('该账号没有后台权限');
    $('login-page').hidden = true;
    $('workspace').hidden = false;
    $('agent-name').textContent = '在线营养师';
    const me = await api('/api/admin/handoff/agent/me');
    state.agent = me.agent;
    if (state.agent) {
      $('max-concurrent').value = String(state.agent.max_concurrent || 3);
      renderOnlineState();
    } else {
      toast('点击“上线接单”开通当前账号的客服坐席', 'success');
    }
    await pollAll();
    await applyPrimaryHash();
    clearInterval(state.queueTimer);
    clearInterval(state.heartbeatTimer);
    state.queueTimer = setInterval(pollAll, 4000);
    state.heartbeatTimer = setInterval(sendHeartbeat, 20000);
  } catch (error) {
    resetToLogin(error.message);
  }
}

async function setOnline(forceValue) {
  const online = typeof forceValue === 'boolean' ? forceValue : !(state.agent && state.agent.online);
  try {
    initAudio();
    const data = await api('/api/admin/handoff/agent/status', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ online, max_concurrent: Number($('max-concurrent').value) || 3 }),
    });
    state.agent = data.agent;
    renderOnlineState();
    toast(online ? '已上线，开始接收咨询' : '已下线，不再分配新咨询', online ? 'success' : '');
    await pollAll();
  } catch (error) { toast(error.message, 'error'); }
}

async function sendHeartbeat() {
  if (!state.agent || !state.agent.online) return;
  try {
    const data = await api('/api/admin/handoff/agent/status', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ online: true, max_concurrent: Number($('max-concurrent').value) || 3 }),
    });
    state.agent = data.agent;
    renderOnlineState();
  } catch {}
}

function renderOnlineState() {
  const online = !!(state.agent && state.agent.online);
  $('online-button').classList.toggle('online', online);
  $('online-button').innerHTML = `<span></span>${online ? '在线接单中' : '上线接单'}`;
  const load = state.agent?.current_load || 0;
  const max = state.agent?.max_concurrent || Number($('max-concurrent').value) || 3;
  $('load-label').textContent = `当前 ${load} / ${max}`;
}

async function pollAll() {
  if (!state.token) return;
  try {
    if (state.agent) {
      const data = await api('/api/admin/handoff/queue');
      state.agent = data.agent;
      processQueueEvents(data.sessions || []);
      state.sessions = data.sessions || [];
      renderSessions();
      renderOnlineState();
      if (state.activeSessionId && state.activeDetailMode === 'live') await loadDetail(state.activeSessionId, false);
      await pollNotifications();
    }
  } catch (error) {
    if (!String(error.message).includes('尚未开通')) console.error(error);
  }
}

function processQueueEvents(sessions) {
  const next = new Map(sessions.map((item) => [item.session_id, item.status]));
  if (state.initialQueueLoaded) {
    sessions.forEach((item) => {
      const before = state.previousStatuses.get(item.session_id);
      if (before && before !== item.status && item.status === 'assigned' && item.agent_id === state.user.user_id) {
        notify(`已为你分配新咨询：${item.member_name || '匿名用户'}`, item.session_id, true);
      }
    });
  }
  state.previousStatuses = next;
  state.initialQueueLoaded = true;
}

function renderSessions() {
  const mine = state.sessions.filter((item) => item.agent_id === state.user.user_id && ['assigned', 'active'].includes(item.status));
  const queued = state.sessions.filter((item) => item.status === 'queued');
  $('mine-count').textContent = mine.length;
  $('queue-count').textContent = queued.length;
  $('mine-list').innerHTML = mine.length ? mine.map(renderSessionCard).join('') : '<div class="empty-list">暂无分配给你的会话</div>';
  $('queue-list').innerHTML = queued.length ? queued.map(renderSessionCard).join('') : '<div class="empty-list">当前没有用户排队</div>';
  const unread = mine.reduce((sum, item) => sum + Number(item.unread_count || 0), 0);
  $('total-unread').hidden = unread === 0;
  $('total-unread').textContent = unread;
  const navCount = queued.length + unread;
  $('consultations-nav-badge').hidden = navCount === 0;
  $('consultations-nav-badge').textContent = navCount > 99 ? '99+' : navCount;
  document.title = unread ? `(${unread}) 营养师工作台` : '营养师工作台';
}

async function setPrimaryModule(module, updateHash = true) {
  state.primaryModule = module === 'ai-review' ? 'ai-review' : 'consultations';
  const review = state.primaryModule === 'ai-review';
  $('consultations-nav').classList.toggle('active', !review);
  $('ai-review-nav').classList.toggle('active', review);
  $('consultations-module').hidden = review;
  $('ai-review-module').hidden = !review;
  if (updateHash) {
    const next = review ? '#/ai-review' : '#/consultations';
    if (window.location.hash !== next) window.location.hash = next;
  }
  if (review && !state.reviewItems.length) await loadAiReviews(1);
}

function applyPrimaryHash() {
  return setPrimaryModule(window.location.hash === '#/ai-review' ? 'ai-review' : 'consultations', false);
}

function updateReviewPeriodFields() {
  const period = $('review-period').value;
  $('review-week-field').hidden = period !== 'week';
  $('review-day-field').hidden = period !== 'day';
  $('review-range-field').hidden = period !== 'range';
  if (period !== 'week') $('review-week').value = '';
  if (period !== 'day') $('review-date').value = '';
  if (period !== 'range') {
    $('review-from').value = '';
    $('review-to').value = '';
  }
}

function weekValueToMonday(value) {
  const match = /^(\d{4})-W(\d{2})$/.exec(value || '');
  if (!match) return '';
  const year = Number(match[1]);
  const week = Number(match[2]);
  const januaryFourth = new Date(Date.UTC(year, 0, 4));
  const monday = new Date(januaryFourth);
  monday.setUTCDate(januaryFourth.getUTCDate() - ((januaryFourth.getUTCDay() + 6) % 7) + (week - 1) * 7);
  return monday.toISOString().slice(0, 10);
}

function reviewFilterValues() {
  const values = {
    keyword: $('review-keyword').value.trim(),
    period: $('review-period').value,
    query_type: $('review-query-type').value,
    feedback: $('review-feedback').value,
    note_status: $('review-note-status').value,
  };
  if (values.period === 'week') values.week_start = weekValueToMonday($('review-week').value);
  if (values.period === 'day') values.date = $('review-date').value;
  if (values.period === 'range') {
    values.from_date = $('review-from').value;
    values.to_date = $('review-to').value;
  }
  return values;
}

function reviewQuery(page) {
  const params = new URLSearchParams({ page: String(page), limit: '20' });
  Object.entries(reviewFilterValues()).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params.toString();
}

async function loadAiReviews(page = 1, preserveId = state.reviewActiveId) {
  if (state.reviewLoading) return;
  state.reviewLoading = true;
  $('review-list').innerHTML = '<div class="empty-list">正在加载 AI 问答…</div>';
  try {
    const data = await api(`/api/admin/ai-review?${reviewQuery(page)}`);
    state.reviewItems = data.items || [];
    state.reviewPagination = data.pagination || { page: 1, pages: 1, total: 0 };
    const typeSelect = $('review-query-type');
    const currentType = typeSelect.value;
    typeSelect.innerHTML = '<option value="">全部类型</option>' + (data.query_types || []).map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('');
    typeSelect.value = currentType;
    state.reviewActiveId = state.reviewItems.some((item) => item.id === preserveId) ? preserveId : 0;
    $('review-summary').textContent = `${data.period_label || '近30天全部'} · ${state.reviewPagination.total || 0} 条`;
    renderAiReviewList();
    renderReviewDetail();
  } catch (error) {
    $('review-list').innerHTML = `<div class="empty-list">${escapeHtml(error.message)}</div>`;
    toast(error.message, 'error');
  } finally {
    state.reviewLoading = false;
  }
}

function renderAiReviewList() {
  $('review-list').innerHTML = state.reviewItems.length ? state.reviewItems.map((item) => {
    const noted = !!item.nutritionist_note;
    return `<button class="review-card ${item.id === state.reviewActiveId ? 'active' : ''}" data-review-id="${item.id}">
      <span class="review-card-head"><strong>${escapeHtml(item.member_name || '匿名用户')}</strong><time>${formatShortDate(item.created_at)}</time></span>
      <span class="review-card-preview">${escapeHtml(item.user_message)}</span>
      <span class="review-card-meta">${escapeHtml(item.team_name || '未填写团队')} · ${escapeHtml(item.query_type || '未分类')}</span>
      <span class="review-card-status ${noted ? 'noted' : ''}">${noted ? '已留言' : '未留言'}</span>
    </button>`;
  }).join('') : '<div class="empty-list">没有符合条件的 AI 问答</div>';
  const paging = state.reviewPagination;
  $('review-page-label').textContent = `第 ${paging.page || 1} / ${paging.pages || 1} 页 · ${paging.total || 0} 条`;
  $('review-prev').disabled = (paging.page || 1) <= 1;
  $('review-next').disabled = (paging.page || 1) >= (paging.pages || 1);
}

function openAiReview(historyId) {
  state.reviewActiveId = Number(historyId);
  state.reviewEditingNote = false;
  renderAiReviewList();
  renderReviewDetail();
}

function activeReviewItem() {
  return state.reviewItems.find((item) => item.id === state.reviewActiveId) || null;
}

function renderReviewDetail() {
  const item = activeReviewItem();
  $('review-empty').hidden = !!item;
  $('review-detail').hidden = !item;
  $('review-meta-empty').hidden = !!item;
  $('review-meta').hidden = !item;
  if (!item) return;
  const note = item.nutritionist_note;
  $('review-detail-title').textContent = item.member_name ? `${item.member_name}的问答` : '匿名用户的问答';
  $('review-detail-time').textContent = formatTime(item.created_at);
  $('review-user-message').textContent = item.user_message || '';
  $('review-ai-response').textContent = item.bot_response || '';
  const feedbackText = item.feedback === 0 ? '用户差评' : item.feedback === 1 ? '用户好评' : '未评价';
  $('review-feedback-badge').textContent = feedbackText;
  $('review-feedback-badge').className = `review-badge ${item.feedback === 0 ? 'negative' : item.feedback === 1 ? 'positive' : ''}`;
  $('review-published-note').hidden = !note;
  $('review-published-content').textContent = note?.content || '';
  $('review-published-version').textContent = note ? `第 ${note.revision} 版` : '';
  $('review-published-time').textContent = note ? formatTime(note.updated_at) : '';
  $('review-note-form').hidden = !!note && !state.reviewEditingNote;
  $('review-note-label').textContent = note ? '编辑营养师留言' : '营养师留言输入框';
  $('review-note-content').value = note && state.reviewEditingNote ? note.content : '';
  $('review-note-count').textContent = `${$('review-note-content').value.length} / 4000`;
  $('review-note-revision').textContent = note ? `第 ${note.revision} 版` : item.note_revision ? '已撤回' : '尚未留言';
  $('review-note-save').textContent = note ? '更新留言' : '发布留言';
  $('review-edit-cancel').hidden = !note || !state.reviewEditingNote;
  $('review-member').textContent = item.member_name || '匿名用户';
  $('review-team').textContent = item.team_name || '未填写';
  $('review-type').textContent = item.query_type || '-';
  $('review-history-id').textContent = String(item.id);
  $('review-feedback-reason').textContent = item.feedback_reason || '-';
  $('review-note-state').textContent = note ? (note.unread ? '已发布 · 用户未读' : '已发布 · 用户已读') : item.note_revision ? '已撤回' : '未留言';
}

async function saveReviewNote(event) {
  event.preventDefault();
  const item = activeReviewItem();
  const content = $('review-note-content').value.trim();
  if (!item || !content) return toast('请输入营养师留言', 'error');
  $('review-note-save').disabled = true;
  try {
    await api(`/api/admin/ai-review/${item.id}/note`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, expected_revision: Number(item.note_revision || 0) }),
    });
    toast(item.nutritionist_note ? '营养师留言已更新' : '营养师留言已发布', 'success');
    state.reviewEditingNote = false;
    await loadAiReviews(state.reviewPagination.page, item.id);
    requestAnimationFrame(() => $('review-published-note')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  } catch (error) { toast(error.message, 'error'); }
  finally { $('review-note-save').disabled = false; }
}

function editReviewNote() {
  const item = activeReviewItem();
  if (!item?.nutritionist_note) return;
  state.reviewEditingNote = true;
  renderReviewDetail();
  requestAnimationFrame(() => $('review-note-content')?.focus());
}

function cancelReviewNoteEdit() {
  state.reviewEditingNote = false;
  renderReviewDetail();
}

async function withdrawReviewNote() {
  const item = activeReviewItem();
  if (!item?.nutritionist_note || !confirm('确认撤回这条营养师留言？用户将不再看到它。')) return;
  try {
    await api(`/api/admin/ai-review/${item.id}/note`, {
      method: 'DELETE', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_revision: Number(item.note_revision || 0) }),
    });
    toast('营养师留言已撤回', 'success');
    state.reviewEditingNote = false;
    await loadAiReviews(state.reviewPagination.page, item.id);
  } catch (error) { toast(error.message, 'error'); }
}

async function setWorkspaceMode(mode) {
  state.viewMode = mode === 'archive' ? 'archive' : 'live';
  $('live-tab').classList.toggle('active', state.viewMode === 'live');
  $('archive-tab').classList.toggle('active', state.viewMode === 'archive');
  $('live-session-pane').hidden = state.viewMode !== 'live';
  $('archive-session-pane').hidden = state.viewMode !== 'archive';
  if (state.viewMode === 'archive') {
    if (state.activeDetailMode === 'live' && state.activeSessionId) {
      state.liveSessionId = state.activeSessionId;
      state.returnSessionId = state.activeSessionId;
    }
    state.activeSessionId = '';
    state.activeDetail = null;
    state.activeDetailMode = 'archive';
    state.selectedArchiveIds.clear();
    renderDetail();
    await loadArchive(1);
  } else if (state.liveSessionId) {
    await openSession(state.liveSessionId);
  } else {
    state.activeSessionId = '';
    state.activeDetail = null;
    state.activeDetailMode = 'live';
    state.returnSessionId = '';
    renderDetail();
  }
}

function archiveFilters() {
  return {
    keyword: $('archive-keyword').value.trim(),
    from: $('archive-from').value,
    to: $('archive-to').value,
    service_mode: $('archive-service-mode').value,
    team: $('archive-team').value.trim(),
  };
}

function archiveQuery(page) {
  const params = new URLSearchParams({ page: String(page), limit: '20' });
  const values = archiveFilters();
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params.toString();
}

async function loadArchive(page = 1) {
  if (state.archiveLoading) return;
  state.archiveLoading = true;
  $('archive-list').innerHTML = '<div class="empty-list">正在加载咨询档案…</div>';
  try {
    const data = await api(`/api/admin/handoff/archive?${archiveQuery(page)}`);
    state.archiveItems = data.items || [];
    state.archivePagination = data.pagination || { page: 1, pages: 1, total: 0 };
    renderArchive();
  } catch (error) {
    $('archive-list').innerHTML = `<div class="empty-list">${escapeHtml(error.message)}</div>`;
  } finally {
    state.archiveLoading = false;
  }
}

function renderArchive() {
  $('archive-list').innerHTML = state.archiveItems.length
    ? state.archiveItems.map((item) => {
      const name = item.member_name || '匿名用户';
      const preview = item.last_question || item.last_reply || '无消息内容';
      const sessionId = escapeHtml(item.session_id);
      return `<div class="archive-card ${item.session_id === state.activeSessionId ? 'active' : ''}">
        <label class="archive-select" title="选择该档案"><input type="checkbox" data-archive-select="${sessionId}" ${state.selectedArchiveIds.has(item.session_id) ? 'checked' : ''}></label>
        <button class="archive-card-body" data-archive-session="${sessionId}">
          <span class="archive-card-head"><strong>${escapeHtml(name)}</strong><time>${formatShortDate(item.closed_at || item.updated_at)}</time></span>
          <span class="archive-card-preview">${escapeHtml(preview)}</span>
          <span class="archive-card-meta">${escapeHtml(item.agent_name || '未接入')} · ${item.service_mode === 'message' ? '留言' : '在线咨询'}</span>
        </button>
      </div>`;
    }).join('')
    : '<div class="empty-list">没有符合条件的咨询档案</div>';
  const paging = state.archivePagination;
  $('archive-page-label').textContent = `第 ${paging.page || 1} / ${paging.pages || 1} 页 · ${paging.total || 0} 条`;
  $('archive-prev').disabled = (paging.page || 1) <= 1;
  $('archive-next').disabled = (paging.page || 1) >= (paging.pages || 1);
  updateArchiveSelectionControls();
}

function updateArchiveSelectionControls() {
  const pageIds = state.archiveItems.map((item) => item.session_id);
  const selectedOnPage = pageIds.filter((id) => state.selectedArchiveIds.has(id)).length;
  $('archive-select-page').checked = pageIds.length > 0 && selectedOnPage === pageIds.length;
  $('archive-select-page').indeterminate = selectedOnPage > 0 && selectedOnPage < pageIds.length;
  $('export-selected').disabled = state.selectedArchiveIds.size === 0;
  $('export-selected').textContent = state.selectedArchiveIds.size ? `导出所选（${state.selectedArchiveIds.size}）` : '导出所选';
}

async function downloadArchive(payload, button) {
  if (button) button.disabled = true;
  try {
    const response = await fetch('/api/admin/handoff/export', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (response.status === 401) {
      resetToLogin('登录已过期，请重新登录');
      throw new Error('登录已过期，请重新登录');
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || '导出失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || 'consultant_archive.csv';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast(`已导出 ${response.headers.get('X-Export-Row-Count') || 0} 条咨询档案`, 'success');
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    if (button) button.disabled = false;
    updateArchiveSelectionControls();
  }
}

function exportSelectedArchive() {
  if (!state.selectedArchiveIds.size) return;
  return downloadArchive({ session_ids: [...state.selectedArchiveIds] }, $('export-selected'));
}

function exportFilteredArchive() {
  return downloadArchive({ filters: archiveFilters() }, $('export-filtered'));
}

function exportCurrentArchive() {
  if (state.activeDetailMode !== 'archive' || !state.activeSessionId) return;
  return downloadArchive({ session_ids: [state.activeSessionId] }, $('export-current-button'));
}

function renderSessionCard(item) {
  const name = item.member_name || '匿名用户';
  const unread = Number(item.unread_count || 0);
  const isMessage = item.service_mode === 'message';
  const status = isMessage
    ? ({ queued: '留言待分配', assigned: '留言待处理', active: '处理留言' }[item.status] || '留言')
    : ({ queued: '排队中', assigned: '待确认', active: '进行中' }[item.status] || item.status);
  return `<button class="session-card ${isMessage ? 'message-mode' : ''} ${item.session_id === state.activeSessionId ? 'active' : ''}" data-session="${escapeHtml(item.session_id)}">
    <span class="session-avatar">${escapeHtml(name.slice(0, 1))}</span>
    <span class="session-main"><span class="session-title"><span>${escapeHtml(name)}</span><span class="session-time">${status}</span></span><span class="session-preview">${escapeHtml(item.last_message || '等待处理')}</span></span>
    ${unread ? `<span class="unread">${unread}</span>` : ''}
  </button>`;
}

async function openSession(sessionId) {
  state.activeDetailMode = 'live';
  state.activeSessionId = sessionId;
  state.liveSessionId = sessionId;
  state.returnSessionId = '';
  renderSessions();
  await loadDetail(sessionId, true);
}

async function loadDetail(sessionId, showError) {
  try {
    const data = await api(`/api/admin/handoff/${encodeURIComponent(sessionId)}/detail`);
    if (state.activeSessionId !== sessionId) return;
    state.activeDetail = data.session;
    renderDetail();
    loadHistory(data.session).catch(() => {});
    const messages = data.session.messages || [];
    const lastId = messages.length ? messages[messages.length - 1].id : 0;
    if (data.session.agent_id === state.user.user_id && lastId) {
      api(`/api/admin/handoff/${encodeURIComponent(sessionId)}/read`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: lastId }),
      }).catch(() => {});
    }
  } catch (error) {
    if (showError) toast(error.message, 'error');
    if (error.message.includes('不存在') || error.message.includes('未分配')) {
      if (state.liveSessionId === sessionId) state.liveSessionId = '';
      state.activeSessionId = '';
      state.activeDetail = null;
      renderDetail();
    }
  }
}

async function openArchivedSession(sessionId, preserveCurrent = false) {
  if (preserveCurrent && state.activeDetailMode === 'live' && state.activeSessionId) {
    state.liveSessionId = state.activeSessionId;
    state.returnSessionId = state.activeSessionId;
  }
  state.activeSessionId = sessionId;
  state.activeDetailMode = 'archive';
  renderArchive();
  try {
    const data = await api(`/api/admin/handoff/archive/${encodeURIComponent(sessionId)}`);
    if (state.activeSessionId !== sessionId || state.activeDetailMode !== 'archive') return;
    state.activeDetail = data.session;
    renderDetail();
    loadHistory(data.session).catch(() => {});
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function returnToCurrentSession() {
  const sessionId = state.returnSessionId || state.liveSessionId;
  if (!sessionId) return;
  state.returnSessionId = '';
  await openSession(sessionId);
}

async function loadHistory(detail) {
  if (!detail?.user_id) return;
  const key = `${detail.user_id}:${detail.session_id}`;
  if (state.historyKey === key) return;
  state.historyKey = key;
  state.historyItems = [];
  $('history-count').textContent = '';
  $('history-list').innerHTML = '<div class="empty-list">正在加载历史咨询…</div>';
  try {
    const params = new URLSearchParams({ limit: '20', exclude_session_id: detail.session_id });
    const data = await api(`/api/admin/handoff/users/${encodeURIComponent(detail.user_id)}/history?${params}`);
    if (state.historyKey !== key) return;
    state.historyItems = data.items || [];
    renderHistory();
  } catch (error) {
    if (state.historyKey !== key) return;
    state.historyItems = [];
    $('history-list').innerHTML = `<div class="empty-list">${escapeHtml(error.message)}</div>`;
    $('history-count').textContent = '';
  }
}

function renderHistory() {
  $('history-count').textContent = state.historyItems.length ? `(${state.historyItems.length})` : '';
  $('history-list').innerHTML = state.historyItems.length
    ? state.historyItems.map((item) => `<button class="history-card" data-history-session="${escapeHtml(item.session_id)}">
        <span class="history-card-head"><strong>${formatShortDate(item.closed_at || item.updated_at)}</strong><span>${item.service_mode === 'message' ? '留言' : '在线咨询'}</span></span>
        <span><b>用户：</b>${escapeHtml(item.last_question || '无用户提问')}</span>
        <span><b>回复：</b>${escapeHtml(item.last_reply || '无真人回复')}</span>
        <small>${escapeHtml(item.agent_name || '未接入')}</small>
      </button>`).join('')
    : '<div class="empty-list">该用户暂无其他历史咨询</div>';
}

function setContextTab(tab) {
  const history = tab === 'history';
  $('profile-tab').classList.toggle('active', !history);
  $('history-tab').classList.toggle('active', history);
  $('profile-pane').hidden = history;
  $('history-pane').hidden = !history;
}

function renderDetail() {
  const detail = state.activeDetail;
  $('empty-chat').hidden = !!detail;
  $('active-chat').hidden = !detail;
  $('context-empty').hidden = !!detail;
  $('context-content').hidden = !detail;
  if (!detail) return;
  const isArchive = state.activeDetailMode === 'archive';
  $('chat-user').textContent = detail.member_name || '匿名用户';
  $('chat-meta').textContent = `${detail.team_name || '未填写团队'} · ${statusLabel(detail.status, detail.service_mode)}${isArchive && detail.closed_at ? ` · ${formatTime(detail.closed_at)}` : ''}`;
  $('archive-badge').hidden = !isArchive;
  $('export-current-button').hidden = !isArchive;
  $('back-current-button').hidden = !isArchive || !state.returnSessionId;
  $('claim-button').hidden = isArchive || !['queued', 'assigned'].includes(detail.status);
  $('claim-button').textContent = detail.service_mode === 'message' ? '处理留言' : '确认接入';
  $('close-button').hidden = isArchive || detail.status !== 'active';
  $('close-button').textContent = detail.service_mode === 'message' ? '关闭留言' : '结束咨询';
  const canReply = !isArchive && detail.status === 'active' && detail.agent_id === state.user.user_id;
  $('reply-form').hidden = isArchive;
  $('reply-input').disabled = !canReply;
  $('reply-button').disabled = !canReply;
  $('reply-input').placeholder = canReply
    ? (detail.service_mode === 'message' ? '回复后将自动归档，Enter 发送' : '回复用户，Enter 发送，Shift+Enter 换行')
    : '确认接入后才能回复';
  const messages = detail.messages || [];
  $('message-list').innerHTML = `<div class="message-list-label">用户初始留言及后续沟通</div>${messages.map((item) => `<div class="message ${item.sender_role}"><div class="bubble">${escapeHtml(item.content)}<time>${formatTime(item.created_at)}</time></div></div>`).join('') || '<div class="empty-list">暂无用户留言，请先查看右侧 AI 对话上下文</div>'}`;
  $('message-list').scrollTop = $('message-list').scrollHeight;
  $('profile-name').textContent = detail.member_name || '-';
  $('profile-team').textContent = detail.team_name || '-';
  $('profile-status').textContent = statusLabel(detail.status, detail.service_mode);
  $('profile-agent').textContent = detail.agent_name || detail.agent?.display_name || '未接入';
  $('ai-context-list').innerHTML = (detail.ai_context || []).map((item) => `<div class="context-message ${item.role}"><strong>${item.role === 'ai' ? 'AI 回复' : '用户问题'}</strong>${escapeHtml(item.text)}</div>`).join('') || '<div class="empty-list">本次转接没有附带 AI 对话</div>';
  setContextTab('profile');
}

function statusLabel(status, serviceMode = 'live') {
  if (serviceMode === 'message') {
    return ({ queued: '留言待分配', assigned: '留言待处理', active: '留言处理中', closed: '留言已回复' })[status] || status;
  }
  return ({ queued: '排队中', assigned: '等待确认', active: '人工咨询中', closed: '已结束' })[status] || status;
}

function formatTime(value) {
  if (!value) return '';
  const normalized = String(value).includes('T') ? value : `${String(value).replace(' ', 'T')}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
}

function formatShortDate(value) {
  if (!value) return '-';
  const normalized = String(value).includes('T') ? value : `${String(value).replace(' ', 'T')}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

async function claimActive() {
  if (!state.activeSessionId) return;
  try {
    const data = await api(`/api/admin/handoff/${encodeURIComponent(state.activeSessionId)}/claim`, { method: 'POST' });
    state.activeDetail = data.session;
    toast(data.session.service_mode === 'message' ? '已开始处理留言' : '已接入该咨询', 'success');
    await pollAll();
  } catch (error) { toast(error.message, 'error'); }
}

async function sendReply(event) {
  event.preventDefault();
  const content = $('reply-input').value.trim();
  if (!content || !state.activeSessionId) return;
  $('reply-button').disabled = true;
  try {
    const data = await api(`/api/admin/handoff/${encodeURIComponent(state.activeSessionId)}/reply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }),
    });
    $('reply-input').value = '';
    if (data.message?.auto_closed) {
      toast('留言已回复并自动归档', 'success');
      state.activeSessionId = '';
      state.liveSessionId = '';
      state.activeDetail = null;
      renderDetail();
      await pollAll();
    } else {
      await loadDetail(state.activeSessionId, true);
    }
  } catch (error) { toast(error.message, 'error'); }
  finally { $('reply-button').disabled = false; }
}

async function closeActive() {
  if (!state.activeSessionId || !confirm('确认结束本次人工咨询？用户仍可查看历史记录。')) return;
  try {
    await api(`/api/admin/handoff/${encodeURIComponent(state.activeSessionId)}/close`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: 'done' }),
    });
    toast('咨询已结束', 'success');
    state.activeSessionId = '';
    state.liveSessionId = '';
    state.activeDetail = null;
    renderDetail();
    await pollAll();
  } catch (error) { toast(error.message, 'error'); }
}

async function pollNotifications() {
  const cursor = state.notificationCursor;
  try {
    const data = await api(`/api/admin/handoff/notifications?after_session_id=${cursor.session_id || 0}&after_message_id=${cursor.message_id || 0}`);
    state.notificationCursor = data.cursor || cursor;
    localStorage.setItem('consultant_notification_cursor', JSON.stringify(state.notificationCursor));
    if (!state.notificationReady) { state.notificationReady = true; return; }
    (data.sessions || []).filter((item) => item.status === 'queued').forEach((item) => notify(`新的营养咨询：${item.member_name || '匿名用户'}`, item.session_id, false));
    (data.messages || []).forEach((item) => {
      if (item.session_id !== state.activeSessionId || document.hidden) notify(`${item.member_name || '用户'}：${item.content.slice(0, 40)}`, item.session_id, false);
    });
  } catch {}
}

function initAudio() {
  if (!state.audioContext) state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
  if (state.audioContext.state === 'suspended') state.audioContext.resume();
}

function beep(strong) {
  if (!state.soundEnabled) return;
  try {
    initAudio();
    const oscillator = state.audioContext.createOscillator();
    const gain = state.audioContext.createGain();
    oscillator.frequency.value = strong ? 880 : 660;
    gain.gain.setValueAtTime(.0001, state.audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.12, state.audioContext.currentTime + .02);
    gain.gain.exponentialRampToValueAtTime(.0001, state.audioContext.currentTime + .22);
    oscillator.connect(gain).connect(state.audioContext.destination);
    oscillator.start(); oscillator.stop(state.audioContext.currentTime + .23);
  } catch {}
}

function notify(message, sessionId, strong) {
  toast(message, 'success');
  beep(strong);
  if ('Notification' in window && Notification.permission === 'granted' && (document.hidden || strong)) {
    const notification = new Notification('营养师工作台', { body: message, tag: `${sessionId}-${message}` });
    notification.onclick = () => { window.focus(); openSession(sessionId); notification.close(); };
  }
}

async function requestNotifications() {
  if (!('Notification' in window)) return toast('当前浏览器不支持桌面通知', 'error');
  const permission = await Notification.requestPermission();
  toast(permission === 'granted' ? '桌面通知已开启' : '未获得桌面通知权限', permission === 'granted' ? 'success' : 'error');
  $('notification-button').textContent = permission === 'granted' ? '桌面通知已开启' : '开启桌面通知';
}

async function openSettings() {
  try {
    const [settings, agents] = await Promise.all([api('/api/admin/settings/handoff'), api('/api/admin/agents')]);
    $('setting-enabled').checked = !!settings.enabled;
    $('setting-agent').innerHTML = '<option value="">请选择已配置 Bot ID 的智能体</option>' + (agents.agents || []).map((item) => `<option value="${escapeHtml(item.agent_id)}">${escapeHtml(item.name)}${item.bot_id ? '' : '（未配置 Bot ID）'}</option>`).join('');
    $('setting-agent').value = settings.ai_agent_id || '';
    $('setting-button-label').value = settings.button_label || '';
    $('setting-avg-seconds').value = settings.avg_handle_sec || 180;
    $('setting-live-wait-seconds').value = settings.live_wait_sec || 600;
    $('setting-queue-msg').value = settings.queue_msg || '';
    $('setting-offline-msg').value = settings.offline_msg || '';
    $('setting-welcome-msg').value = settings.welcome_msg || '';
    $('settings-modal').hidden = false;
  } catch (error) { toast(error.message, 'error'); }
}

async function saveSettings(event) {
  event.preventDefault();
  try {
    await api('/api/admin/settings/handoff', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: $('setting-enabled').checked,
        ai_agent_id: $('setting-agent').value,
        button_label: $('setting-button-label').value.trim(),
        avg_handle_sec: Number($('setting-avg-seconds').value),
        live_wait_sec: Number($('setting-live-wait-seconds').value),
        queue_msg: $('setting-queue-msg').value.trim(),
        offline_msg: $('setting-offline-msg').value.trim(),
        welcome_msg: $('setting-welcome-msg').value.trim(),
      }),
    });
    $('settings-modal').hidden = true;
    toast('转接设置已保存', 'success');
  } catch (error) { toast(error.message, 'error'); }
}

async function logout(setOffline = true) {
  if (setOffline && state.agent?.online) await setOnline(false);
  resetToLogin();
}

document.addEventListener('DOMContentLoaded', () => {
  $('login-form').addEventListener('submit', login);
  $('online-button').addEventListener('click', () => setOnline());
  $('logout-button').addEventListener('click', () => logout());
  $('notification-button').addEventListener('click', requestNotifications);
  $('settings-button').addEventListener('click', openSettings);
  $('settings-close').addEventListener('click', () => { $('settings-modal').hidden = true; });
  $('settings-form').addEventListener('submit', saveSettings);
  $('claim-button').addEventListener('click', claimActive);
  $('close-button').addEventListener('click', closeActive);
  $('reply-form').addEventListener('submit', sendReply);
  $('reply-input').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('reply-form').requestSubmit(); } });
  $('live-tab').addEventListener('click', () => setWorkspaceMode('live'));
  $('archive-tab').addEventListener('click', () => setWorkspaceMode('archive'));
  $('archive-filter-form').addEventListener('submit', (event) => {
    event.preventDefault();
    state.selectedArchiveIds.clear();
    loadArchive(1);
  });
  $('archive-reset').addEventListener('click', () => {
    $('archive-filter-form').reset();
    state.selectedArchiveIds.clear();
    loadArchive(1);
  });
  $('archive-prev').addEventListener('click', () => loadArchive(Math.max(1, state.archivePagination.page - 1)));
  $('archive-next').addEventListener('click', () => loadArchive(Math.min(state.archivePagination.pages, state.archivePagination.page + 1)));
  $('archive-select-page').addEventListener('change', (event) => {
    state.archiveItems.forEach((item) => {
      if (event.target.checked) state.selectedArchiveIds.add(item.session_id);
      else state.selectedArchiveIds.delete(item.session_id);
    });
    renderArchive();
  });
  $('archive-list').addEventListener('change', (event) => {
    const checkbox = event.target.closest('[data-archive-select]');
    if (!checkbox) return;
    if (checkbox.checked) state.selectedArchiveIds.add(checkbox.dataset.archiveSelect);
    else state.selectedArchiveIds.delete(checkbox.dataset.archiveSelect);
    updateArchiveSelectionControls();
  });
  $('export-selected').addEventListener('click', exportSelectedArchive);
  $('export-filtered').addEventListener('click', exportFilteredArchive);
  $('export-current-button').addEventListener('click', exportCurrentArchive);
  $('profile-tab').addEventListener('click', () => setContextTab('profile'));
  $('history-tab').addEventListener('click', () => setContextTab('history'));
  $('consultations-nav').addEventListener('click', () => setPrimaryModule('consultations'));
  $('ai-review-nav').addEventListener('click', () => setPrimaryModule('ai-review'));
  window.addEventListener('hashchange', applyPrimaryHash);
  $('review-period').addEventListener('change', updateReviewPeriodFields);
  $('review-filter-form').addEventListener('submit', (event) => { event.preventDefault(); state.reviewActiveId = 0; loadAiReviews(1); });
  $('review-reset').addEventListener('click', () => { $('review-filter-form').reset(); updateReviewPeriodFields(); state.reviewActiveId = 0; loadAiReviews(1); });
  $('review-prev').addEventListener('click', () => loadAiReviews(Math.max(1, state.reviewPagination.page - 1), 0));
  $('review-next').addEventListener('click', () => loadAiReviews(Math.min(state.reviewPagination.pages, state.reviewPagination.page + 1), 0));
  $('review-note-form').addEventListener('submit', saveReviewNote);
  $('review-edit-note').addEventListener('click', editReviewNote);
  $('review-edit-cancel').addEventListener('click', cancelReviewNoteEdit);
  $('review-published-withdraw').addEventListener('click', withdrawReviewNote);
  $('review-note-content').addEventListener('input', () => { $('review-note-count').textContent = `${$('review-note-content').value.length} / 4000`; });
  $('back-current-button').addEventListener('click', returnToCurrentSession);
  document.body.addEventListener('click', (event) => {
    const liveCard = event.target.closest('[data-session]');
    if (liveCard) return openSession(liveCard.dataset.session);
    const archiveCard = event.target.closest('[data-archive-session]');
    if (archiveCard) return openArchivedSession(archiveCard.dataset.archiveSession);
    const historyCard = event.target.closest('[data-history-session]');
    if (historyCard) return openArchivedSession(historyCard.dataset.historySession, true);
    const reviewCard = event.target.closest('[data-review-id]');
    if (reviewCard) return openAiReview(reviewCard.dataset.reviewId);
  });
  $('max-concurrent').addEventListener('change', () => { if (state.agent) setOnline(!!state.agent.online); });
  if ('Notification' in window && Notification.permission === 'granted') $('notification-button').textContent = '桌面通知已开启';
  if (state.token) bootWorkspace();
});
