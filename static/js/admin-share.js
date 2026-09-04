/* ===== 分享功能开关 =====
   见 index.html 中的 window.SHARE_ENABLED。关闭时隐藏入口并移除相关 DOM，
   保留 copyText / openAdmin（聊天区「复制」按钮仍依赖 copyText）。       */
function shareEnabled() {
  return window.SHARE_ENABLED === true;
}

function removeShareDom() {
  ['share-overlay', 'share-card'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.remove();
  });
}

if (!shareEnabled()) {
  removeShareDom();
  document.addEventListener('DOMContentLoaded', removeShareDom);
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
function truncateShareText(text, max = 280) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function latestUserQuestionBefore(index) {
  for (let i = index - 1; i >= 0; i--) {
    const msg = state.messages[i];
    if (msg && msg.role === 'user' && msg.content) return msg.content;
  }
  return '';
}

function renderShareCaseSnippet(caseItem) {
  if (!caseItem) return '';
  const tags = [
    ...splitTags(caseItem.symptom_tags).slice(0, 2),
    ...splitTags(caseItem.product_tags).slice(0, 2),
  ].slice(0, 4);
  return `
    <div style="margin-top:18px;padding:16px;border-radius:20px;background:#F8FAFC;border:1px solid #E2E8F0">
      <div style="font-size:22px;font-weight:900;color:#475569;margin-bottom:8px">相关客户案例</div>
      <div style="font-size:26px;font-weight:900;color:#0F172A;line-height:1.25;margin-bottom:8px">${escapeHtml(caseItem.title || '')}</div>
      ${caseItem.summary ? `<div style="font-size:22px;color:#64748B;line-height:1.5">${escapeHtml(truncateShareText(caseItem.summary, 80))}</div>` : ''}
      ${tags.length ? `<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px">${tags.map(t => `<span style="font-size:18px;font-weight:800;color:#0F766E;background:#CCFBF1;border-radius:999px;padding:5px 10px">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
    </div>`;
}

function currentShareUrl() {
  return window.location.origin + window.location.pathname;
}

async function renderShareImage(card, alt, width = 750, scale = 2) {
  const wrap = document.getElementById('share-image-wrap');
  wrap.innerHTML = '<div class="share-loading"><i class="ph ph-spinner-gap"></i> 生成中...</div>';
  document.getElementById('share-overlay').classList.add('active');
  card.style.width = `${width}px`;
  try {
    await ensureHtml2Canvas();
  } catch {
    document.getElementById('share-overlay').classList.remove('active');
    showToast('分享组件加载失败，请稍后重试', 'error');
    return;
  }

  try {
    const canvas = await html2canvas(card, {
      scale,
      useCORS: true,
      backgroundColor: '#ffffff',
      width,
    });
    const dataUrl = canvas.toDataURL('image/png');
    wrap.innerHTML = `<img src="${dataUrl}" alt="${escapeHtml(alt || '分享图')}" style="width:100%;display:block;border-radius:8px">`;
  } catch {
    showToast('生成失败，请重试', 'error');
  }
}

async function recordShareEvent(msg, shareType = 'answer_card') {
  const agent = AGENTS.find(a => a.id === msg.agentId) || AGENTS.find(a => a.id === state.activeAgentId) || {};
  try {
    await fetch(`${API_BASE}/api/share-events`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        user_id: getUserId(),
        team_name: state.profile?.team || '',
        member_name: state.profile?.name || '',
        query_type: agent.type || '',
        history_id: msg.historyId || null,
        share_type: shareType,
      }),
    });
  } catch {}
}

async function shareAnswerCard(index) {
  if (!shareEnabled()) return;
  const msg = state.messages[index];
  if (!msg || msg.role !== 'bot' || !msg.content) {
    showToast('没有可分享的回答', 'info');
    return;
  }
  const agent = AGENTS.find(a => a.id === msg.agentId) || AGENTS[0] || {};
  const card = document.getElementById('share-card');
  const content = document.getElementById('share-card-content');
  const now = new Date().toLocaleString('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const question = msg.replyToText || latestUserQuestionBefore(index) || '我的健康咨询';
  const caseItem = (msg.relatedCases || [])[0];

  content.innerHTML = `
    <div style="width:750px;box-sizing:border-box;padding:40px;background:linear-gradient(160deg,#F8F7FF 0%,#FFFFFF 42%,#ECFEFF 100%);font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:#0F172A">
      <div style="display:flex;align-items:center;gap:18px;margin-bottom:28px">
        <div style="width:72px;height:72px;border-radius:24px;background:${agent.color || '#7C3AED'};display:flex;align-items:center;justify-content:center;color:#fff;font-size:30px;font-weight:900;box-shadow:0 12px 30px rgba(124,58,237,.25)">AI</div>
        <div>
          <div style="font-size:30px;font-weight:900;letter-spacing:-.5px">AI宝儿智能体</div>
          <div style="font-size:22px;color:#64748B;margin-top:4px">${escapeHtml(agent.name || '智能问答')}</div>
        </div>
      </div>

      <div style="font-size:22px;font-weight:900;color:#7C3AED;margin-bottom:10px">用户提问</div>
      <div style="padding:22px 24px;border-radius:24px;background:#FFFFFF;border:1px solid #EDE9FE;box-shadow:0 16px 42px rgba(15,23,42,.08);font-size:30px;font-weight:900;line-height:1.35;margin-bottom:24px">${escapeHtml(truncateShareText(question, 90))}</div>

      <div style="font-size:22px;font-weight:900;color:#2563EB;margin-bottom:10px">AI回答摘要</div>
      <div style="padding:24px;border-radius:28px;background:#EEF6FF;border:1px solid #DBEAFE;font-size:25px;line-height:1.62;color:#1E293B;white-space:pre-wrap">${escapeHtml(truncateShareText(msg.content, 360))}</div>

      ${msg.content.length > 360 ? `<div style="margin-top:12px;font-size:20px;color:#64748B">内容已简化展示，打开网页可继续查看完整回答。</div>` : ''}
      ${renderShareCaseSnippet(caseItem)}

      <div style="margin-top:28px;padding:22px 24px;border-radius:24px;background:#111827;color:#fff">
        <div style="font-size:25px;font-weight:900;margin-bottom:8px">长按保存，转发给朋友一起看看</div>
        <div style="font-size:19px;color:#CBD5E1;line-height:1.5">微信内打开：${escapeHtml(currentShareUrl())}</div>
      </div>

      <div style="margin-top:18px;text-align:center;font-size:18px;color:#94A3B8">${now} · 仅供交流参考</div>
    </div>`;

  showToast('正在生成分享图片...', 'info');
  await renderShareImage(card, '回答分享图', 750, 2);
  recordShareEvent(msg, 'answer_card');
}

async function shareChat() {
  if (!shareEnabled()) return;
  if (state.handoff.session && ['queued', 'assigned', 'active'].includes(state.handoff.session.status)) {
    showToast('人工咨询进行中暂不支持分享，请结束后再操作', 'info');
    return;
  }
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

  await renderShareImage(card, '分享对话', 390, 3);
}

function closeSharePreview(e) {
  if (e && e.target !== e.currentTarget) return;
  document.getElementById('share-overlay').classList.remove('active');
}
