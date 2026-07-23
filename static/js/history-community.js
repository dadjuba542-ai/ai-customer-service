/* ===== History ===== */
async function restoreLatestChat() {
  // Keep the current in-memory conversation intact when this is called after
  // a view transition or a session handoff.
  if (state.messages.length > 0) return;

  try {
    const res = await fetch(`${API_BASE}/api/history/sessions`, { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    const latestSession = data.sessions?.[0];
    const items = latestSession?.items || [];
    if (!items.length) return;

    applyHistoryItems(items);
  } catch {}
}

function applyHistoryItems(items) {
    const firstItem = items[0];
    const firstAgent = AGENTS.find(a => a.id === firstItem?.agent_id)
      || AGENTS.find(a => a.type === firstItem?.query_type)
      || AGENTS[0];
    if (firstAgent) state.activeAgentId = firstAgent.id;
    state.messages = [];
    (items || []).forEach(item => {
      const time = typeof formatTime === 'function'
        ? formatTime(item.created_at, true)
        : item.created_at || '';
      const agent = AGENTS.find(a => a.id === item.agent_id)
        || AGENTS.find(a => a.type === item.query_type)
        || firstAgent;
      state.messages.push({
        id: `history-user-${item.id}`,
        role: 'user',
        content: item.user_message || '',
        time,
        agentId: agent?.id || state.activeAgentId,
      });
      if (item.bot_response) {
        state.messages.push({
          id: `history-bot-${item.id}`,
          role: 'bot',
          content: item.bot_response,
          time,
          agentId: item.agent_id || agent?.id || state.activeAgentId,
          historyId: item.id,
          feedback: item.feedback,
          replyToText: item.user_message || '',
        });
      }
      if (item.nutritionist_note) {
        state.messages.push({
          id: `nutritionist-note-${item.nutritionist_note.id}`,
          role: 'nutritionist',
          content: item.nutritionist_note.content || '',
          time: typeof formatTime === 'function' ? formatTime(item.nutritionist_note.updated_at, true) : '',
          historyId: item.id,
          nutritionistNoteId: item.nutritionist_note.id,
          revision: item.nutritionist_note.revision,
        });
      }
    });
    renderAgentTabs();
    renderMessages();
}

async function loadHistory(queryType = '') {
  try {
    const base = `${API_BASE}/api/history/sessions`;
    const url = queryType ? `${base}&query_type=${encodeURIComponent(queryType)}` : base;
    const res = await fetch(url, { headers: authHeaders() });
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
      headers: authHeaders({ 'Content-Type': 'application/json' }),
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
    const res = await fetch(`${API_BASE}/api/community/questions/${id}`, { headers: authHeaders() });
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
    const res = await fetch(`${API_BASE}/api/community/replies/${replyId}/like`, { method: 'POST', headers: authHeaders() });
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
