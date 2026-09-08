const API = '';
const assetPromises = new Map();

function loadScriptOnce(src) {
  if (assetPromises.has(src)) return assetPromises.get(src);
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
  assetPromises.set(src, promise);
  return promise;
}

function loadStylesheetOnce(href) {
  if (assetPromises.has(href)) return assetPromises.get(href);
  const promise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`link[href="${href}"]`);
    if (existing) {
      resolve();
      return;
    }
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.onload = () => resolve();
    link.onerror = () => reject(new Error(`Failed to load stylesheet: ${href}`));
    document.head.appendChild(link);
  });
  assetPromises.set(href, promise);
  return promise;
}

async function ensureChartJs() {
  if (typeof Chart !== 'undefined') return;
  await loadScriptOnce('https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js');
}

async function ensureQuill() {
  if (typeof Quill !== 'undefined') return;
  await Promise.all([
    loadStylesheetOnce('https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css'),
    loadScriptOnce('https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.min.js'),
  ]);
}

// ===== Auth =====
function getToken() { return localStorage.getItem('token'); }
function getUser() {
  try { return JSON.parse(localStorage.getItem('user') || 'null'); }
  catch { return null; }
}

async function checkAuth() {
  const token = getToken();
  if (!token) { showLogin(); return; }
  try {
    const res = await fetch(`${API}/api/user/profile`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (!res.ok) throw new Error('not authorized');
    const user = await res.json();
    if (!user.is_admin) { showLogin(); return; }
    localStorage.setItem('user', JSON.stringify(user));
    showDashboard(user);
  } catch { showLogin(); }
}

function showLogin() {
  document.getElementById('login-page').style.display = 'flex';
  document.getElementById('dashboard-page').style.display = 'none';
  document.getElementById('login-username').focus();
}

function showDashboard(user) {
  document.getElementById('login-page').style.display = 'none';
  document.getElementById('dashboard-page').style.display = 'block';
  document.getElementById('admin-username').textContent = user.username;
  switchPage('dashboard');
}

async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value.trim();
  const errEl = document.getElementById('login-error');
  const btn = document.getElementById('login-btn');
  if (!username || !password) { errEl.textContent = '请输入账号和密码'; errEl.style.display = 'block'; return; }
  errEl.style.display = 'none';
  btn.disabled = true; btn.textContent = '登录中...';
  try {
    const res = await fetch(`${API}/api/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (!res.ok) { throw new Error(data.error || '登录失败'); }
    if (!data.is_admin) { throw new Error('该账号不是管理员'); }
    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data));
    showDashboard(data);
  } catch (e) {
    errEl.textContent = e.message; errEl.style.display = 'block';
  } finally {
    btn.disabled = false; btn.textContent = '登录';
  }
}

function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  showLogin();
  document.getElementById('login-password').value = '';
}

// ===== Page Switching =====
async function switchPage(page) {
  document.querySelectorAll('.page-content').forEach(p => p.classList.remove('active'));
  document.getElementById(`page-${page}`).classList.add('active');
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(n => n.classList.remove('active'));
  document.querySelector(`.sidebar-nav .nav-item[data-page="${page}"]`).classList.add('active');

  const titles = {
    dashboard: '数据看板',
    news: '资讯管理',
    products: '产品管理',
    cases: '案例档案',
    agents: '智能体配置',
    share: '分享设置',
    feedback: '评价看板',
    community: '问答管理',
    'team-stats': '团队提问统计',
    leads: '客户需求',
    handoff: '人工客服',
    features: '功能开关'
  };
  document.getElementById('page-title-text').textContent = titles[page] || '数据看板';

  if (page === 'dashboard') loadAll();
  if (page === 'news') {
    try {
      await ensureQuill();
      loadAdminNews();
      initQuill();
    } catch (e) {
      console.error('quill load error:', e);
    }
  }
  if (page === 'products') loadAdminProducts();
  if (page === 'cases') {
    loadCaseLibraryUrl();
    loadCaseTags();
    loadAdminCases();
  }
  if (page === 'agents') loadAdminAgents();
  if (page === 'share') loadShareSettings();
  if (page === 'feedback') loadFeedbackDashboard();
  if (page === 'community') loadAdminQA();
  if (page === 'team-stats') loadTeamStatsPage();
  if (page === 'leads') loadAdminLeads();
  if (page === 'handoff') loadHandoffPage();
  if (page === 'features') loadFeatureFlagsPage();
}

// ===== Dashboard Data =====
let trendChartInstance = null;
let typeChartInstance = null;
let filterDays = 30;
let filterStart = '';
let filterEnd = '';

function dateParams() {
  const start = document.getElementById('filter-start')?.value || filterStart;
  const end = document.getElementById('filter-end')?.value || filterEnd;
  const p = new URLSearchParams();
  if (start) p.set('start_date', start);
  if (end) p.set('end_date', end);
  const s = p.toString();
  return s ? '&' + s : '';
}

function setDateRange(days) {
  filterDays = days;
  document.querySelectorAll('.date-filter .quick-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.days) === days);
  });
  const now = new Date();
  if (days === 0) {
    document.getElementById('filter-start').value = '';
    document.getElementById('filter-end').value = '';
  } else {
    const start = new Date(now);
    start.setDate(start.getDate() - days);
    document.getElementById('filter-start').value = start.toISOString().slice(0, 10);
    document.getElementById('filter-end').value = now.toISOString().slice(0, 10);
  }
  applyDateFilter();
}

function applyDateFilter() {
  filterStart = document.getElementById('filter-start').value;
  filterEnd = document.getElementById('filter-end').value;
  loadAll();
}

/* ===== Feedback Date Filter ===== */
let fbFilterDays = 30;

function setFbDateRange(days) {
  fbFilterDays = days;
  document.querySelectorAll('#page-feedback .quick-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.days) === days);
  });
  const now = new Date();
  if (days === 0) {
    document.getElementById('fb-filter-start').value = '';
    document.getElementById('fb-filter-end').value = '';
  } else {
    const start = new Date(now);
    start.setDate(start.getDate() - days);
    document.getElementById('fb-filter-start').value = start.toISOString().slice(0, 10);
    document.getElementById('fb-filter-end').value = now.toISOString().slice(0, 10);
  }
  applyFbDateFilter();
}

function applyFbDateFilter() {
  loadFeedbackDashboard();
}

function fbDateParams() {
  const s = document.getElementById('fb-filter-start').value;
  const e = document.getElementById('fb-filter-end').value;
  let q = '';
  if (s) q += `&start_date=${s}`;
  if (e) q += `&end_date=${e}`;
  return q;
}

function fbApiUrl(path) {
  const dp = fbDateParams();
  return `${API}${path}${dp ? '?' + dp.slice(1) : ''}`;
}

/* ===== Team Question Stats ===== */
function teamDateParams() {
  const start = document.getElementById('team-filter-start')?.value || '';
  const end = document.getElementById('team-filter-end')?.value || '';
  const team = document.getElementById('team-filter-team')?.value || '';
  const member = (document.getElementById('team-filter-member')?.value || '').trim();
  const p = new URLSearchParams();
  if (start) p.set('start_date', start);
  if (end) p.set('end_date', end);
  if (team) p.set('team_name', team);
  if (member) p.set('member_name', member);
  return p.toString();
}

function setTeamDateRange(days) {
  document.querySelectorAll('#page-team-stats .quick-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.days) === days);
  });
  const now = new Date();
  if (days === 0) {
    document.getElementById('team-filter-start').value = '';
    document.getElementById('team-filter-end').value = '';
  } else {
    const start = new Date(now);
    start.setDate(start.getDate() - days);
    document.getElementById('team-filter-start').value = start.toISOString().slice(0, 10);
    document.getElementById('team-filter-end').value = now.toISOString().slice(0, 10);
  }
  loadTeamQuestionStats();
}

async function loadTeamStatsPage() {
  if (!document.getElementById('team-filter-start').value) {
    setTeamDateRange(30);
  } else {
    await loadTeamQuestionStats();
  }
  await loadDefaultTeamSetting();
}

async function loadDefaultTeamSetting() {
  try {
    const res = await fetch(`${API}/api/admin/settings/default-team`, {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const data = await res.json();
    if (res.ok) {
      const teams = data.team_names || [];
      document.getElementById('default-team-input').value = teams.join(',');
      fillTeamFilterOptions(teams);
    }
  } catch {}
}

async function saveDefaultTeam() {
  const team_names = (document.getElementById('default-team-input').value || '')
    .split(',')
    .map(t => t.trim())
    .filter(Boolean);
  if (!team_names.length) return showToast('请至少填写一个团队', 'error');
  try {
    const res = await fetch(`${API}/api/admin/settings/default-team`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ team_names }),
    });
    if (res.ok) {
      fillTeamFilterOptions(team_names);
      showToast('团队名单已保存', 'success');
    }
    else showToast('保存失败', 'error');
  } catch { showToast('保存失败', 'error'); }
}

function fillTeamFilterOptions(teams) {
  const select = document.getElementById('team-filter-team');
  if (!select) return;
  const current = select.value || '';
  const unique = [...new Set((teams || []).map(t => (t || '').trim()).filter(Boolean))];
  select.innerHTML = '<option value="">全部团队</option>' + unique.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
  if (current && unique.includes(current)) select.value = current;
}

async function loadTeamQuestionStats() {
  const loading = document.getElementById('team-stats-loading');
  const wrap = document.getElementById('team-stats-wrap');
  const body = document.getElementById('team-stats-body');
  const count = document.getElementById('team-stats-count');
  loading.style.display = '';
  wrap.style.display = 'none';
  try {
    const qs = teamDateParams();
    const url = `${API}/api/admin/dashboard/team-question-stats?limit=200${qs ? '&' + qs : ''}`;
    const res = await fetch(url, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    const data = await res.json();
    const items = data.items || [];
    fillTeamFilterOptions([
      ...(document.getElementById('default-team-input').value || '').split(',').map(t => t.trim()),
      ...items.map(it => it.team_name || '')
    ]);
    count.textContent = items.length;
    if (!items.length) {
      body.innerHTML = '<tr><td colspan="4" class="team-empty">暂无数据</td></tr>';
    } else {
      body.innerHTML = items.map(it => `
        <tr>
          <td><span class="tag tag-sky">${esc(it.team_name)}</span></td>
          <td>${esc(it.member_name)}</td>
          <td class="q" title="${esc(it.user_message)}">${esc(it.user_message).slice(0, 120)}${it.user_message.length > 120 ? '...' : ''}</td>
          <td class="times">${it.total}</td>
        </tr>
      `).join('');
    }
    wrap.style.display = '';
  } catch {
    body.innerHTML = '<tr><td colspan="4" class="team-empty" style="color:var(--rose)">加载失败</td></tr>';
    wrap.style.display = '';
  } finally {
    loading.style.display = 'none';
  }
}

async function loadFeedbackDashboard() {
  // 首次加载默认 30 天（手动设日期，避免循环调用）
  if (!document.getElementById('fb-filter-start').value) {
    const now = new Date();
    const start = new Date(now);
    start.setDate(start.getDate() - 30);
    document.getElementById('fb-filter-start').value = start.toISOString().slice(0, 10);
    document.getElementById('fb-filter-end').value = now.toISOString().slice(0, 10);
    document.querySelectorAll('#page-feedback .quick-btn').forEach(b => {
      b.classList.toggle('active', parseInt(b.dataset.days) === 30);
    });
  }
  await Promise.all([loadFeedbackOverview(), loadFeedbackByAgent(), loadNegativeFeedback(), loadFeedbackReasons()]);
}

async function loadFeedbackOverview() {
  try {
    const res = await fetch(fbApiUrl('/api/admin/dashboard/feedback-overview'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const d = await res.json();
    document.getElementById('fb-ratio').textContent = d.total > 0 ? d.ratio + '%' : '-';
    document.getElementById('fb-likes').textContent = d.likes.toLocaleString();
    document.getElementById('fb-dislikes').textContent = d.dislikes.toLocaleString();
    document.getElementById('fb-total').textContent = d.total.toLocaleString();
  } catch {}
}

async function loadFeedbackByAgent() {
  try {
    const res = await fetch(fbApiUrl('/api/admin/dashboard/feedback-by-agent'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const d = await res.json();
    const list = document.getElementById('fb-agent-list');
    const wrap = document.getElementById('fb-agent-wrap');
    const loading = document.getElementById('fb-agent-loading');
    if (!d.agents || d.agents.length === 0) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--slate-400)">暂无评价数据</div>';
    } else {
      list.innerHTML = d.agents.map(a => {
        const pct = a.ratio;
        const barColor = pct >= 80 ? '#059669' : pct >= 60 ? '#D97706' : '#E11D48';
        return `<div class="fb-agent-row">
          <div class="fb-agent-info">
            <span class="fb-agent-name">${a.agent_name}</span>
            <span class="fb-agent-stats">👍 ${a.likes} &nbsp; 👎 ${a.dislikes}</span>
          </div>
          <div class="fb-bar-wrap">
            <div class="fb-bar-bg">
              <div class="fb-bar-fill" style="width:${pct}%;background:${barColor}"></div>
            </div>
            <span class="fb-bar-label" style="color:${barColor}">${pct}%</span>
          </div>
        </div>`;
      }).join('');
    }
    wrap.style.display = 'block';
    loading.style.display = 'none';
  } catch {}
}

async function loadNegativeFeedback() {
  try {
    const res = await fetch(fbApiUrl('/api/admin/dashboard/negative-feedback'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const d = await res.json();
    const body = document.getElementById('fb-negative-body');
    const wrap = document.getElementById('fb-negative-wrap');
    const loading = document.getElementById('fb-negative-loading');
    const count = document.getElementById('fb-negative-count');
    count.textContent = (d.items || []).length;
    if (!d.items || d.items.length === 0) {
      body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--slate-400);padding:20px">暂无差评</td></tr>';
    } else {
      body.innerHTML = d.items.map(item => {
        const agentName = item.agent_name || item.query_type || '未知';
        const time = new Date(item.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        const question = item.user_message ? item.user_message.substring(0, 60) + (item.user_message.length > 60 ? '...' : '') : '(空)';
        const answer = item.bot_response ? item.bot_response.substring(0, 80) + (item.bot_response.length > 80 ? '...' : '') : '(空)';
        return `<tr><td><span class="tag tag-${getTypeTag(item.query_type)}">${agentName}</span></td><td title="${escapeHtml(item.user_message || '')}">${escapeHtml(question)}</td><td title="${escapeHtml(item.bot_response || '')}">${escapeHtml(answer)}</td><td class="time">${time}</td></tr>`;
      }).join('');
    }
    wrap.style.display = 'block';
    loading.style.display = 'none';
  } catch {}
}

async function loadFeedbackReasons() {
  try {
    const res = await fetch(fbApiUrl('/api/admin/dashboard/feedback-reasons'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const d = await res.json();
    const body = document.getElementById('fb-reasons-body');
    const wrap = document.getElementById('fb-reasons-wrap');
    const loading = document.getElementById('fb-reasons-loading');
    if (!d.reasons || !d.reasons.length) {
      body.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--slate-400);padding:20px">暂无差评原因数据</td></tr>';
    } else {
      body.innerHTML = d.reasons.map(r => {
        const agent = r.agent_name || r.query_type || '未知';
        return `<tr><td><span class="tag tag-${getTypeTag(r.query_type)}">${escapeHtml(agent)}</span></td><td>${escapeHtml(r.feedback_reason)}</td><td><strong>${r.cnt}</strong></td></tr>`;
      }).join('');
    }
    wrap.style.display = 'block';
    loading.style.display = 'none';
  } catch {}
}

function getTypeTag(type) {
  const map = { '产品咨询': 'primary', '使用答疑': 'sky', '朋友圈帮写': 'emerald', '口播文案帮写': 'rose' };
  return map[type] || 'slate';
}

function escapeHtml(t) {
  if (!t) return '';
  const d = document.createElement('div');
  d.textContent = t;
  return d.innerHTML;
}

function exportCSV() {
  const start = document.getElementById('filter-start').value || '全部';
  const end = document.getElementById('filter-end').value || '全部';
  const lines = [];

  const push = (...cells) => lines.push(cells.join(','));

  push(`周报,${start},~,${end}`);
  push('');

  // Stats
  push('统计概览');
  const stats = [
    ['总对话数', g('stat-conversations')],
    ['独立用户', g('stat-users')],
    ['智能体数', g('stat-agents')],
    ['资讯数', g('stat-news')],
    ['今日对话', g('stat-today')],
    ['今日用户', g('stat-today-users')],
  ];
  stats.forEach(s => push(s[0], s[1]));
  push('');

  // Trends
  const trendLabels = document.querySelectorAll('#trendChart + *') ? [] : [];
  const trendCanvas = document.getElementById('trendChart');
  let trendData = [];
  if (trendChartInstance) {
    trendData = trendChartInstance.data.labels.map((l, i) => [l, trendChartInstance.data.datasets[0].data[i]]);
  }
  if (trendData.length > 0) {
    push('日期,对话数');
    trendData.forEach(t => push(t[0], t[1]));
    push('');
  }

  // Agent usage
  if (typeChartInstance) {
    const labels = typeChartInstance.data.labels;
    const vals = typeChartInstance.data.datasets[0].data;
    push('咨询类型,对话数');
    labels.forEach((l, i) => push(l, vals[i]));
    push('');
  }

  // Hot questions
  const wcItems = document.querySelectorAll('.wc-item');
  if (wcItems.length > 0) {
    push('热门问题');
    wcItems.forEach(el => {
      const text = el.textContent.trim();
      const title = el.getAttribute('title') || '';
      push(`"${text}",${title}`);
    });
  }

  const csv = '\uFEFF' + lines.join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `周报_${start}_${end}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function g(id) { return document.getElementById(id)?.textContent || '-'; }

/* ===== Feedback Export ===== */
function exportFbCSV() {
  const start = document.getElementById('fb-filter-start').value || '全部';
  const end = document.getElementById('fb-filter-end').value || '全部';
  const lines = [];

  const push = (...cells) => lines.push(cells.join(','));

  push(`评价看板,${start},~,${end}`);
  push('');

  // Overview
  push('统计概览');
  push('好评率,' + g('fb-ratio'));
  push('好评数,' + g('fb-likes'));
  push('差评数,' + g('fb-dislikes'));
  push('评价总数,' + g('fb-total'));
  push('');

  // Per-agent
  const agentRows = document.querySelectorAll('.fb-agent-row');
  if (agentRows.length > 0) {
    push('各智能体评价详情');
    push('智能体,好评,差评,好评率');
    agentRows.forEach(row => {
      const name = row.querySelector('.fb-agent-name')?.textContent || '';
      const stats = row.querySelector('.fb-agent-stats')?.textContent || '';
      const pct = row.querySelector('.fb-bar-label')?.textContent || '';
      push(name, stats, pct);
    });
    push('');
  }

  // Negative feedback
  const negRows = document.querySelectorAll('#fb-negative-body tr');
  if (negRows.length > 0 && !negRows[0].textContent.includes('暂无差评')) {
    push('差评问题');
    push('智能体,用户问题,AI回答,时间');
    negRows.forEach(row => {
      const cells = row.querySelectorAll('td');
      if (cells.length >= 4) {
        const agent = cells[0].textContent.trim();
        const question = cells[1].textContent.trim();
        const answer = cells[2].textContent.trim();
        const time = cells[3].textContent.trim();
        push(`"${agent}","${question}","${answer}",${time}`);
      }
    });
  }

  const csv = '\uFEFF' + lines.join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `评价看板_${start}_${end}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function loadAll() {
  document.getElementById('last-update').textContent = '加载中...';
  await ensureChartJs();
  await Promise.all([
    loadStats(), loadTrends(), loadAgentUsage(), loadRecent(), loadHotQuestions(), loadExampleQuestions(),
  ]);
  document.getElementById('last-update').textContent = `更新于 ${new Date().toLocaleTimeString()}`;
}

function apiUrl(path) {
  const dp = dateParams();
  return `${API}${path}${dp ? '?' + dp.slice(1) : ''}`;
}

async function loadStats() {
  try {
    const res = await fetch(apiUrl('/api/admin/dashboard/stats'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const data = await res.json();
    document.getElementById('stat-conversations').textContent = data.total_conversations.toLocaleString();
    document.getElementById('stat-users').textContent = data.unique_users.toLocaleString();
    document.getElementById('stat-agents').textContent = data.total_agents;
    document.getElementById('stat-news').textContent = data.total_news;
    document.getElementById('stat-today').textContent = data.today_conversations.toLocaleString();
    document.getElementById('stat-today-users').textContent = data.today_users.toLocaleString();
  } catch (e) { console.error('stats error:', e); }

  try {
    const fbRes = await fetch(apiUrl('/api/admin/dashboard/feedback-stats'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const fb = await fbRes.json();
    document.getElementById('stat-feedback').textContent = fb.total > 0 ? fb.ratio + '%' : '-';
    document.getElementById('stat-feedback-detail').innerHTML = fb.total > 0
      ? `<span style="color:var(--emerald)">👍 ${fb.likes}</span> · <span style="color:var(--rose)">👎 ${fb.dislikes}</span> · ${fb.total}条评价`
      : '暂无人评价';
  } catch (e) { console.error('feedback stats error:', e); }
}

async function loadTrends() {
  try {
    const days = filterDays > 0 ? filterDays : 30;
    const url = apiUrl('/api/admin/dashboard/trends') + (dateParams() ? `&days=${days}` : `?days=${days}`);
    const res = await fetch(url, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    renderTrendChart((await res.json()).trends);
  } catch (e) { console.error('trends error:', e); }
}

async function loadAgentUsage() {
  try {
    const res = await fetch(apiUrl('/api/admin/dashboard/agent-usage'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    renderTypeChart((await res.json()).usage);
  } catch (e) { console.error('usage error:', e); }
}

async function loadRecent() {
  try {
    const url = apiUrl('/api/admin/dashboard/recent') + (dateParams() ? '&limit=12' : '?limit=12');
    const res = await fetch(url, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    renderRecent((await res.json()).recent);
  } catch (e) { console.error('recent error:', e); }
}

async function loadHotQuestions() {
  await loadAgentOptions();
  try {
    const res = await fetch(apiUrl('/api/admin/dashboard/hot-questions'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    const data = await res.json();
    if (Array.isArray(data.agents) && data.agents.length) adminAgentOptions = data.agents;
    renderWordCloud(data.questions);
  } catch (e) { console.error('hot error:', e); }
}

/* ===== 首页示例问题（可绑定固定智能体） ===== */
let exampleQuestionRows = [];
let adminAgentOptions = [];

async function loadAgentOptions() {
  if (adminAgentOptions.length) return adminAgentOptions;
  try {
    const res = await fetch(`${API}/api/admin/settings/example-questions`, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    const data = await res.json().catch(() => ({}));
    adminAgentOptions = Array.isArray(data.agents) ? data.agents : [];
  } catch (e) {
    adminAgentOptions = [];
  }
  return adminAgentOptions;
}

function agentOptionsHtml(selectedId) {
  const options = ['<option value="">未绑定（默认智能体）</option>'].concat(
    adminAgentOptions.map(a => `<option value="${esc(a.agent_id)}" ${a.agent_id === selectedId ? 'selected' : ''}>${esc(a.name)}</option>`)
  );
  return options.join('');
}

function agentSelectHtml(index, selectedId, extraClass) {
  return `<select class="${extraClass}" data-example-agent="${index}" style="padding:8px 10px;font-size:13px;font-family:inherit;border:1.5px solid var(--slate-200);border-radius:8px;outline:none;background:#fff;max-width:180px">${agentOptionsHtml(selectedId)}</select>`;
}

function renderExampleQuestionRows() {
  const wrap = document.getElementById('example-question-rows');
  if (!wrap) return;
  wrap.innerHTML = exampleQuestionRows.map((item, index) => `
    <div style="display:flex;gap:8px;align-items:center">
      <input type="text" class="example-q-input" data-example-text="${index}" value="${esc(item.text)}" maxlength="80"
        placeholder="输入示例问题" style="flex:1;padding:8px 10px;font-size:13px;font-family:inherit;border:1.5px solid var(--slate-200);border-radius:8px;outline:none">
      ${agentSelectHtml(index, item.agent_id, 'example-q-agent')}
      <button class="btn btn-secondary btn-sm" onclick="removeExampleQuestionRow(${index})" title="删除" style="color:var(--rose)">✕</button>
    </div>`).join('') || '<div style="font-size:12px;color:var(--slate-400)">暂无示例问题，点「添加一条」开始配置</div>';
  const counter = document.getElementById('example-count');
  if (counter) counter.textContent = exampleQuestionRows.length;
}

function addExampleQuestionRow() {
  if (exampleQuestionRows.length >= 8) { showToast('最多 8 条示例问题', 'info'); return; }
  exampleQuestionRows.push({ text: '', agent_id: '' });
  renderExampleQuestionRows();
  const inputs = document.querySelectorAll('.example-q-input');
  if (inputs.length) inputs[inputs.length - 1].focus();
}

function removeExampleQuestionRow(index) {
  exampleQuestionRows.splice(index, 1);
  renderExampleQuestionRows();
}

function collectExampleQuestionRows() {
  const list = document.getElementById('example-question-rows');
  if (!list) return [];
  return exampleQuestionRows.map((_, index) => {
    const textEl = list.querySelector(`[data-example-text="${index}"]`);
    const agentEl = list.querySelector(`[data-example-agent="${index}"]`);
    return { text: (textEl?.value || '').trim(), agent_id: agentEl?.value || '' };
  }).filter(item => item.text);
}

async function loadExampleQuestions() {
  const wrap = document.getElementById('example-question-rows');
  if (!wrap) return;
  try {
    const res = await fetch(`${API}/api/admin/settings/example-questions`, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    const data = await res.json();
    adminAgentOptions = Array.isArray(data.agents) ? data.agents : adminAgentOptions;
    exampleQuestionRows = (data.questions || []).map(q => ({
      text: typeof q === 'string' ? q : (q.text || ''),
      agent_id: typeof q === 'string' ? '' : (q.agent_id || ''),
    }));
    renderExampleQuestionRows();
  } catch (e) { console.error('example questions error:', e); }
}

async function saveExampleQuestions() {
  const questions = collectExampleQuestionRows();
  if (!questions.length) { showToast('至少保留一条示例问题', 'error'); return; }
  if (questions.some(q => q.text.length > 80)) { showToast('单条问题不能超过 80 字', 'error'); return; }
  try {
    const res = await fetch(`${API}/api/admin/settings/example-questions`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ questions }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '保存失败');
    exampleQuestionRows = (data.questions || questions).map(q => ({ text: q.text, agent_id: q.agent_id || '' }));
    renderExampleQuestionRows();
    showToast('示例问题已更新', 'success');
  } catch (e) { showToast(e.message || '保存失败', 'error'); }
}

function renderTrendChart(trends) {
  const labels = trends.map(t => t.day.slice(5));
  const values = trends.map(t => t.cnt);
  const ctx = document.getElementById('trendChart').getContext('2d');
  if (trendChartInstance) trendChartInstance.destroy();
  trendChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: '对话数', data: values,
        borderColor: '#4F46E5', backgroundColor: 'rgba(79,70,229,0.08)',
        fill: true, tension: 0.4, pointRadius: 3,
        pointBackgroundColor: '#4F46E5', borderWidth: 2,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 11 }, color: '#94A3B8' } },
        y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.04)' }, ticks: { font: { size: 11 }, color: '#94A3B8', stepSize: 1 } }
      }
    }
  });
}

function renderTypeChart(usage) {
  const colors = ['#4F46E5', '#059669', '#D97706', '#E11D48', '#0284C7', '#7C3AED'];
  const labels = usage.map(u => u.query_type || '未分类');
  const values = usage.map(u => u.cnt);
  const ctx = document.getElementById('typeChart').getContext('2d');
  if (typeChartInstance) typeChartInstance.destroy();
  typeChartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors.slice(0, labels.length), borderWidth: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { position: 'bottom', labels: { padding: 12, font: { size: 11 }, color: '#475569' } } },
      cutout: '65%',
    }
  });
}

function renderRecent(items) {
  document.getElementById('recent-loading').style.display = 'none';
  document.getElementById('recent-table-wrap').style.display = '';
  document.getElementById('recent-count').textContent = items.length;
  document.getElementById('recent-body').innerHTML = items.map(item => {
    const time = item.created_at ? item.created_at.slice(5, 16) : '-';
    return `<tr><td><div class="text-truncate q-text">${esc(item.user_message)}</div></td><td><span class="tag ${tagForType(item.query_type)}">${item.query_type || '未知'}</span></td><td class="text-mono">${time}</td></tr>`;
  }).join('');
}

let manualHotItems = [];

function hotAgentSelectHtml(selectedId, extraClass) {
  return `<select class="${extraClass}" style="padding:4px 6px;font-size:12px;font-family:inherit;border:1.5px solid var(--slate-200);border-radius:6px;outline:none;background:#fff;max-width:170px">${agentOptionsHtml(selectedId)}</select>`;
}

function renderWordCloud(items) {
  document.getElementById('hot-loading').style.display = 'none';
  const wrap = document.getElementById('hot-check-wrap');
  const list = document.getElementById('hot-check-list');
  fetch(`${API}/api/history/hot-questions`)
    .then(r => r.json())
    .then(d => {
      // 已选问题 → {text: agent_id}，兼容旧的字符串数组
      const approvedMap = new Map();
      (d.questions || []).forEach(q => {
        approvedMap.set(typeof q === 'string' ? q : q.text, typeof q === 'string' ? '' : (q.agent_id || ''));
      });
      // Deduplicate: manual items should not appear as checkboxes too
      const manualTexts = new Set(manualHotItems.map(i => i.text));
      const autoItems = (items || []).filter(item => !manualTexts.has(item.text));
      let html = autoItems.map(item => {
        const checked = approvedMap.has(item.text);
        return `<label class="hot-check-item" style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:6px 0">
          <input type="checkbox" class="hot-checkbox" value="${esc(item.text)}" ${checked ? 'checked' : ''} onchange="updateHotCheck()">
          <span style="font-size:13px">${esc(item.text)}</span>
          <span style="font-size:11px;color:var(--slate-400)">${item.users}人以此提问</span>
          ${hotAgentSelectHtml(approvedMap.get(item.text) || item.agent_id || '', 'hot-agent-select')}
        </label>`;
      }).join('');
      // Manual items section
      if (manualHotItems.length) {
        html += `<div style="border-top:1px solid var(--slate-100);margin:8px 0 4px;padding-top:8px;font-size:11px;color:var(--slate-400)">手动添加</div>`;
        html += manualHotItems.map(item => `<div class="hot-check-item" style="display:flex;align-items:center;gap:8px;padding:6px 0">
          <input type="checkbox" class="hot-checkbox" value="${esc(item.text)}" checked onchange="updateHotCheck()">
          <span style="font-size:13px">${esc(item.text)}</span>
          ${hotAgentSelectHtml(item.agent_id || '', 'hot-agent-select')}
          <button class="btn btn-secondary btn-sm" onclick="removeManualHot('${esc(item.text)}')" style="margin-left:auto;color:var(--rose)">✕</button>
        </div>`).join('');
      }
      list.innerHTML = html || '<div class="empty-state" style="padding:10px"><p>暂无候选，自行输入即可</p></div>';
      wrap.style.display = 'block';
      updateHotCheck();
    });
}

function addManualHot() {
  const input = document.getElementById('hot-manual-input');
  const text = input.value.trim();
  if (!text) return;
  if (manualHotItems.some(i => i.text === text)) { showToast('已存在', 'info'); return; }
  manualHotItems.push({ text, agent_id: '' });
  input.value = '';
  // Reload word cloud (will use stored items)
  loadHotQuestions();
}

function removeManualHot(text) {
  manualHotItems = manualHotItems.filter(i => i.text !== text);
  loadHotQuestions();
}

function updateHotCheck() {
  const checked = document.querySelectorAll('.hot-checkbox:checked');
  const max = 5;
  checked.forEach((cb, i) => { if (i >= max) cb.checked = false; });
  document.getElementById('hot-selected-count').textContent = Math.min(checked.length, max);
  const allCb = document.querySelectorAll('.hot-checkbox');
  allCb.forEach(cb => { cb.disabled = document.querySelectorAll('.hot-checkbox:checked').length >= max && !cb.checked; });
}

async function saveHotQuestions() {
  // 逐行读取：同一行内的 checkbox 与 select 一一对应，避免依赖文本做 DOM 匹配
  const questions = [];
  document.querySelectorAll('#hot-check-list .hot-check-item').forEach(row => {
    const cb = row.querySelector('.hot-checkbox');
    if (!cb || !cb.checked) return;
    questions.push({ text: cb.value, agent_id: row.querySelector('.hot-agent-select')?.value || '' });
  });
  const payload = questions.slice(0, 5);
  try {
    const res = await fetch(`${API}/api/admin/dashboard/hot-questions/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ questions: payload }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '保存失败');
    showToast('热门问题已更新', 'success');
  } catch (e) { showToast(e.message || '保存失败', 'error'); }
}

function tagForType(type) {
  const map = { '产品咨询': 'tag-sky', '使用答疑': 'tag-emerald', '朋友圈帮写': 'tag-amber', '口播文案帮写': 'tag-rose' };
  return map[type] || 'tag-sky';
}

// ===== Rich Text Extensions =====
// 排版格式一律走 class，不走 inline style：后端 sanitize_rich_html 只放行 class，style 属性会被
// 整段丢弃 —— 这正是原先「字体颜色按钮点了能看到、保存后就没了」的根因。
// 新增格式必须三处同步，缺一处就会出现「编辑时能看到、保存后前台没有」：
//   1. 这里注册的 attributor（决定输出的 class 名）
//   2. services/content_security.py 的 CLASS_PATTERN（决定能不能入库）
//   3. static/css/rich-text.css（决定编辑器和前台显不显示）

const TEXT_COLOR_PALETTE = [
  ['', '默认'], ['dark', '深墨'], ['gray', '中灰'], ['muted', '浅灰'],
  ['red', '朱红'], ['orange', '橙'], ['amber', '金'], ['green', '绿'],
  ['teal', '青'], ['blue', '蓝'], ['purple', '紫'], ['pink', '粉'], ['brown', '棕'],
];
const TEXT_BG_PALETTE = [
  ['', '无'], ['yellow', '黄'], ['mint', '薄荷'], ['peach', '蜜桃'],
  ['sky', '天蓝'], ['rose', '粉'], ['silver', '银灰'],
];
const LINE_HEIGHT_OPTIONS = [
  ['', '默认'], ['1', '1.0 倍'], ['125', '1.25 倍'], ['15', '1.5 倍'],
  ['175', '1.75 倍'], ['2', '2.0 倍'], ['25', '2.5 倍'], ['3', '3.0 倍'],
];
const PARAGRAPH_GAP_OPTIONS = [
  ['', '默认'], ['0', '无'], ['8', '8px'], ['12', '12px'],
  ['20', '20px'], ['32', '32px'], ['48', '48px'],
];
const SIZE_OPTIONS = [['', '标准'], ['small', '小'], ['large', '大'], ['huge', '特大']];
const ALIGN_OPTIONS = [['', '左对齐'], ['center', '居中'], ['right', '右对齐'], ['justify', '两端对齐']];

const PICKER_LABELS = {
  size: Object.fromEntries(SIZE_OPTIONS),
  align: Object.fromEntries(ALIGN_OPTIONS),
  textcolor: Object.fromEntries(TEXT_COLOR_PALETTE),
  textbg: Object.fromEntries(TEXT_BG_PALETTE),
  line: Object.fromEntries(LINE_HEIGHT_OPTIONS),
  para: Object.fromEntries(PARAGRAPH_GAP_OPTIONS),
};

let richFormatsReady = false;

function registerRichTextFormats() {
  if (richFormatsReady || typeof Quill === 'undefined') return;
  const Parchment = Quill.import('parchment');
  if (!Parchment || !Parchment.ClassAttributor) return;
  const Scope = Parchment.Scope;
  // 空串表示「不设置该格式」，不能进 whitelist，否则会输出 ql-line- 这种残缺 class
  const whitelistOf = options => options.map(([value]) => value).filter(Boolean);

  // Quill 2 没有可直接用的 size / align 白名单，不显式注册下拉就是空的
  Quill.register(new Parchment.ClassAttributor('size', 'ql-size', {
    scope: Scope.INLINE, whitelist: whitelistOf(SIZE_OPTIONS),
  }), true);
  Quill.register(new Parchment.ClassAttributor('align', 'ql-align', {
    scope: Scope.BLOCK, whitelist: whitelistOf(ALIGN_OPTIONS),
  }), true);
  // 字体颜色用预设色板而非自由取色：class 化之后枚举空间封闭，
  // 后端不必为它开放 style 白名单，XSS 面完全不变
  Quill.register(new Parchment.ClassAttributor('textcolor', 'ql-color', {
    scope: Scope.INLINE, whitelist: whitelistOf(TEXT_COLOR_PALETTE),
  }), true);
  Quill.register(new Parchment.ClassAttributor('textbg', 'ql-bg', {
    scope: Scope.INLINE, whitelist: whitelistOf(TEXT_BG_PALETTE),
  }), true);
  Quill.register(new Parchment.ClassAttributor('line', 'ql-line', {
    scope: Scope.BLOCK, whitelist: whitelistOf(LINE_HEIGHT_OPTIONS),
  }), true);
  Quill.register(new Parchment.ClassAttributor('para', 'ql-para', {
    scope: Scope.BLOCK, whitelist: whitelistOf(PARAGRAPH_GAP_OPTIONS),
  }), true);
  richFormatsReady = true;
}

function richTextToolbar() {
  return [
    [{ header: [1, 2, 3, false] }],
    [{ size: SIZE_OPTIONS.map(([v]) => v) }],
    ['bold', 'italic', 'underline', 'strike'],
    [
      { textcolor: TEXT_COLOR_PALETTE.map(([v]) => v) },
      { textbg: TEXT_BG_PALETTE.map(([v]) => v) },
    ],
    [{ align: ALIGN_OPTIONS.map(([v]) => v) }],
    [{ list: 'ordered' }, { list: 'bullet' }],
    [
      { line: LINE_HEIGHT_OPTIONS.map(([v]) => v) },
      { para: PARAGRAPH_GAP_OPTIONS.map(([v]) => v) },
    ],
    ['blockquote', 'code-block'],
    ['link', 'image'],
    ['clean'],
  ];
}

// Quill 生成的下拉项文字直接取 whitelist 里的值（dark / textbg / 125 …），
// 对中文后台不可读，初始化后统一换成中文标签
function localizeToolbarPickers(quill) {
  const toolbar = quill.getModule('toolbar');
  if (!toolbar || !toolbar.container) return;
  Object.entries(PICKER_LABELS).forEach(([format, labels]) => {
    const select = toolbar.container.querySelector(`select.ql-${format}`);
    if (select) {
      Array.from(select.options || []).forEach(option => {
        const label = labels[option.value || ''];
        if (label) option.textContent = label;
      });
    }
    const picker = toolbar.container.querySelector(`.ql-picker.ql-${format}`);
    if (!picker) return;
    picker.querySelectorAll('.ql-picker-item').forEach(item => {
      const label = labels[item.getAttribute('data-value') || ''];
      if (label) {
        item.setAttribute('data-label', label);
        item.textContent = label;
      }
    });
  });
}

// ===== Format Painter =====
const FORMAT_PAINTER = { editor: null, locked: false, formats: null };
// 不复制 link：格式刷复制的是排版样式，把目标整段变成超链接几乎总是误操作
const PAINTER_INLINE_KEYS = ['bold', 'italic', 'underline', 'strike', 'code', 'size', 'textcolor', 'textbg'];
const PAINTER_BLOCK_KEYS = ['align', 'header', 'list', 'blockquote', 'code-block', 'indent', 'line', 'para'];
let painterEscBound = false;

function painterIsActive() { return !!FORMAT_PAINTER.formats; }

// 取选区起始处的格式（含块级），与 Word 格式刷一致地以首字符为准
function painterGrab(quill) {
  // 点按钮会让编辑器失焦，getSelection(true) 会先聚焦并恢复上一次选区
  const range = quill.getSelection(true);
  if (!range || range.length === 0) return null;
  const source = quill.getFormat(range.index, 1) || {};
  const picked = {};
  Object.keys(source).forEach(key => {
    if (key === 'link') return;
    const value = source[key];
    if (value === false || value === null || value === undefined || value === '') return;
    picked[key] = value;
  });
  return Object.keys(picked).length ? picked : null;
}

function painterApply(quill, range) {
  const formats = FORMAT_PAINTER.formats;
  if (!formats || !range || range.length === 0) return;
  // 先整类清空、再按源格式设置，这样「源没有的格式」也会从目标上移除，
  // 否则源没有加粗、目标有加粗时，刷完目标仍然加粗
  const clearInline = {};
  PAINTER_INLINE_KEYS.forEach(key => { clearInline[key] = false; });
  const clearBlock = {};
  PAINTER_BLOCK_KEYS.forEach(key => { clearBlock[key] = false; });
  const inline = {};
  PAINTER_INLINE_KEYS.forEach(key => {
    if (key in formats) inline[key] = formats[key];
  });
  const block = {};
  PAINTER_BLOCK_KEYS.forEach(key => {
    if (key in formats) block[key] = formats[key];
  });

  quill.formatText(range.index, range.length, clearInline, 'user');
  quill.formatLine(range.index, range.length, clearBlock, 'user');
  if (Object.keys(inline).length) quill.formatText(range.index, range.length, inline, 'user');
  if (Object.keys(block).length) quill.formatLine(range.index, range.length, block, 'user');
}

function painterDisarm() {
  if (FORMAT_PAINTER.editor) {
    FORMAT_PAINTER.editor.root.classList.remove('format-painter-armed');
  }
  FORMAT_PAINTER.editor = null;
  FORMAT_PAINTER.locked = false;
  FORMAT_PAINTER.formats = null;
  document.querySelectorAll('.ql-formatpainter.ql-active').forEach(el => el.classList.remove('ql-active'));
}

function painterArm(quill, locked) {
  const formats = painterGrab(quill);
  if (!formats) {
    showToast('先在源文字上选中一段，再点格式刷', 'error');
    return;
  }
  FORMAT_PAINTER.editor = quill;
  FORMAT_PAINTER.locked = locked;
  FORMAT_PAINTER.formats = formats;
  quill.root.classList.add('format-painter-armed');
  const toolbar = quill.getModule('toolbar');
  const btn = toolbar && toolbar.container && toolbar.container.querySelector('.ql-formatpainter');
  if (btn) btn.classList.add('ql-active');
}

function setupFormatPainter(quill) {
  const toolbar = quill.getModule('toolbar');
  if (!toolbar || !toolbar.container) return;
  if (toolbar.container.querySelector('.ql-formatpainter')) return;

  // 和 Quill 其他组一样包一层 .ql-formats：裸 button 直接挂在 .ql-toolbar 上会失去
  // 组间距，视觉上孤立错位；图标用内联 SVG（与 Quill 自带图标同风格），不再依赖
  // Phosphor 字体里是否有 paint-brush 字形——之前用 <i class="ph">，图标缺失时按钮
  // 就是一个看不见的空位，看起来像「菜单栏错乱」
  const group = document.createElement('span');
  group.className = 'ql-formats';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ql-formatpainter';
  btn.title = '格式刷：先选中源文字，单击刷一次，双击可连续刷，Esc 退出';
  btn.innerHTML =
    '<svg viewBox="0 0 18 18" aria-hidden="true">' +
    '<path d="M15 3l-5.2 5.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
    '<path d="M8.6 7.2l2.2 2.2-4.2 4.2a1.6 1.6 0 01-2.2-2.2z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>' +
    '</svg>';
  group.appendChild(btn);
  toolbar.container.appendChild(group);

  let clickTimer = null;
  btn.addEventListener('click', () => {
    if (painterIsActive() && FORMAT_PAINTER.editor === quill) { painterDisarm(); return; }
    if (clickTimer) {
      clearTimeout(clickTimer);
      clickTimer = null;
      painterArm(quill, true);
      return;
    }
    // 单击延迟一拍，给双击留判断窗口
    clickTimer = setTimeout(() => {
      clickTimer = null;
      painterArm(quill, false);
    }, 220);
  });
  btn.addEventListener('dblclick', event => event.preventDefault());

  // 松手后才刷，避免拖动选区过程中反复触发
  const tryPaint = () => {
    setTimeout(() => {
      if (!painterIsActive() || FORMAT_PAINTER.editor !== quill) return;
      const range = quill.getSelection();
      if (!range || range.length === 0) return;
      painterApply(quill, range);
      if (!FORMAT_PAINTER.locked) painterDisarm();
    }, 0);
  };
  quill.root.addEventListener('mouseup', tryPaint);
  quill.root.addEventListener('keyup', event => {
    if (event.shiftKey) tryPaint();
  });

  if (!painterEscBound) {
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && painterIsActive()) painterDisarm();
    });
    painterEscBound = true;
  }
}

// 填充/清空编辑器内容的唯一入口。
// 不能直接赋值 quill.root.innerHTML：那只改了 DOM，Quill 内部的 Delta 模型不知道，
// 之后的光标、格式识别、撤销都会错。必须走 clipboard.convert -> setContents 同步模型。
function setEditorContents(quill, html) {
  if (!quill) return;
  try {
    const delta = quill.clipboard.convert({ html: html || '<p><br></p>' });
    quill.setContents(delta, 'user');
  } catch (e) { console.error('set editor contents failed:', e); }
}

// ===== News Management =====
let newsEditingId = null;
let quill = null;
let quillInited = false;

function initQuill() {
  if (quillInited) return;
  const container = document.getElementById('news-editor');
  if (!container || container.style.display === 'none') return;
  if (typeof Quill === 'undefined') return;
  try {
    registerRichTextFormats();
    quill = new Quill('#news-editor', {
      theme: 'snow',
      modules: { toolbar: richTextToolbar() },
      placeholder: '输入正文内容...',
    });
    quill.getModule('toolbar').addHandler('image', handleNewsEditorImage);
    localizeToolbarPickers(quill);
    setupFormatPainter(quill);
    bindEditorImageEvents(quill);
    quillInited = true;
  } catch (e) { console.error('Quill init error:', e); }
}

function insertEditorImage(editor, url) {
  if (!editor || !url) return;
  const range = editor.getSelection(true);
  const index = range ? range.index : editor.getLength();
  editor.insertEmbed(index, 'image', url, 'user');
  editor.setSelection(index + 1);
}

async function uploadEditorImageFile(editor, file) {
  if (!file || !file.type || !file.type.startsWith('image/')) {
    showToast('请上传图片文件', 'error');
    return;
  }
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(`${API}/api/admin/upload`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || '图片上传失败', 'error');
      return;
    }
    insertEditorImage(editor, data.url);
  } catch {
    showToast('图片上传失败', 'error');
  }
}

function pickEditorImage(editor) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.onchange = () => uploadEditorImageFile(editor, input.files && input.files[0]);
  input.click();
}

function insertEditorImageFromEvent(editor, event) {
  const files = event.dataTransfer?.files || event.clipboardData?.files || [];
  const file = Array.from(files).find(f => f.type && f.type.startsWith('image/'));
  if (!file) return false;
  event.preventDefault();
  event.stopPropagation();
  uploadEditorImageFile(editor, file);
  return true;
}

// 图片拖拽 / 粘贴必须绑在 document 捕获阶段：Quill 自己也在 quill.root 上
// 监听了 paste（Clipboard）和 drop（Uploader，且不检查 defaultPrevented），
// 若绑在 root 冒泡阶段，会先由 Quill 插入一张 base64 内嵌图，再叠加我们上传的图。
const EDITOR_IMAGE_EVENTS = new WeakMap();

function bindEditorImageEvents(editor) {
  if (!editor || EDITOR_IMAGE_EVENTS.has(editor)) return;
  const root = editor.root;
  const handler = (event) => {
    if (!root.isConnected || !root.contains(event.target)) return;
    insertEditorImageFromEvent(editor, event);
  };
  document.addEventListener('paste', handler, true);
  document.addEventListener('drop', handler, true);
  EDITOR_IMAGE_EVENTS.set(editor, handler);
}

function unbindEditorImageEvents(editor) {
  const handler = EDITOR_IMAGE_EVENTS.get(editor);
  if (!handler) return;
  document.removeEventListener('paste', handler, true);
  document.removeEventListener('drop', handler, true);
  EDITOR_IMAGE_EVENTS.delete(editor);
}

function handleNewsEditorImage() {
  pickEditorImage(quill);
}

async function loadAdminNews() {
  try {
    const res = await fetch(`${API}/api/news?mode=content`);
    if (!res.ok) return;
    const data = await res.json();
    loadAdminHomeBulletins();
    const container = document.getElementById('admin-news-list');
    if (!data.news || data.news.length === 0) {
      container.innerHTML = '<div class="empty-state"><i class="ph ph-newspaper"></i>暂无资讯，在上方添加</div>';
      return;
    }
    container.innerHTML = data.news.map(item => `
      <div class="admin-list-item">
        <div>
          <div class="item-title">${esc(item.title)}</div>
          <div class="item-meta">
            ${item.category ? `🏷 ${esc(item.category)} · ` : ''}${fmt(item.created_at)}${item.image_url ? ' · 有配图' : ''}${item.views !== undefined ? ` · 阅读 ${item.views} 次` : ''}
            ${item.pinned ? ' · 📌置顶' : ''}${item.featured ? ' · 🏠首页' : ''}
          </div>
        </div>
        <div class="item-actions">
          <button class="btn btn-secondary btn-sm" onclick="toggleNewsPin(${item.id})" style="${item.pinned ? 'color:var(--primary);font-weight:700' : ''}">📌</button>
          <button class="btn btn-secondary btn-sm" onclick="toggleNewsFeature(${item.id})" style="${item.featured ? 'color:var(--emerald);font-weight:700' : ''}">🏠</button>
          <button class="btn btn-secondary btn-sm" onclick="editNews(${item.id})">编辑</button>
          <button class="btn btn-danger btn-sm" onclick="deleteNews(${item.id})">删除</button>
        </div>
      </div>
    `).join('');
  } catch {}
}

async function loadAdminHomeBulletins() {
  const container = document.getElementById('admin-home-bulletin-list');
  if (!container) return;
  try {
    const res = await fetch(`${API}/api/admin/home-bulletins`, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    const data = await res.json();
    if (!data.news || data.news.length === 0) {
      container.innerHTML = '<div class="empty-state"><i class="ph ph-megaphone"></i>暂无首页滚动内容</div>';
      return;
    }
    container.innerHTML = data.news.map(item => `
      <div class="admin-list-item">
        <div><div class="item-title">${esc(item.title)}</div><div class="item-meta">${fmt(item.created_at)} · 首页滚动</div></div>
        <div class="item-actions"><button class="btn btn-secondary btn-sm" onclick="editNews(${item.id})">编辑</button><button class="btn btn-danger btn-sm" onclick="deleteNews(${item.id})">移除</button></div>
      </div>
    `).join('');
  } catch { container.innerHTML = '<div class="empty-state">首页滚动加载失败</div>'; }
}

async function newHomeBulletin() {
  await switchPage('news');
  resetNewsForm();
  document.getElementById('news-category').value = '首页滚动';
  document.getElementById('news-category').readOnly = true;
  document.getElementById('news-title').placeholder = '首页滚动标题';
  document.getElementById('news-form-title').textContent = '新增首页滚动内容';
}

async function toggleNewsPin(id) {
  try {
    const res = await fetch(`${API}/api/news/${id}/pin`, {
      method: 'PUT', headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (res.ok) loadAdminNews();
  } catch {}
}

async function toggleNewsFeature(id) {
  try {
    const res = await fetch(`${API}/api/news/${id}/feature`, {
      method: 'PUT', headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (res.ok) loadAdminNews();
  } catch {}
}

function resetNewsForm() {
  document.getElementById('news-title').value = '';
  document.getElementById('news-title').placeholder = '资讯标题';
  document.getElementById('news-category').value = '';
  document.getElementById('news-category').readOnly = false;
  document.getElementById('news-summary').value = '';
  if (quill) setEditorContents(quill, '');
  document.getElementById('news-image-preview').classList.add('hidden');
  document.getElementById('news-upload-placeholder').classList.remove('hidden');
  document.getElementById('news-image-input').value = '';
  document.getElementById('news-form-title').textContent = '添加资讯';
  newsEditingId = null;
}

async function saveNews() {
  const title = document.getElementById('news-title').value.trim();
  const category = document.getElementById('news-category').value.trim();
  const summary = document.getElementById('news-summary').value.trim();
  const content = quill ? quill.root.innerHTML.trim() : '';
  const preview = document.getElementById('news-image-preview');
  const imageUrl = preview.classList.contains('hidden') ? '' : (preview.dataset.url || '');
  if (!title) return showToast('请输入标题', 'error');
  if (content.includes('data:image')) return showToast('正文图片请通过上传插入，不能保存内嵌图片', 'error');
  try {
    const method = newsEditingId ? 'PUT' : 'POST';
    const url = newsEditingId ? `${API}/api/news/${newsEditingId}` : `${API}/api/news`;
    const res = await fetch(url, {
      method, headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ title, summary, content, image_url: imageUrl, category }),
    });
    if (res.ok) {
      showToast(newsEditingId ? '资讯已更新' : '资讯已添加', 'success');
      resetNewsForm();
      loadAdminNews();
    } else { showToast('保存失败', 'error'); }
  } catch { showToast('保存失败', 'error'); }
}

async function editNews(id) {
  try {
    const res = await fetch(`${API}/api/news/${id}`);
    if (res.ok) {
      const item = await res.json();
      document.getElementById('news-title').value = item.title;
      document.getElementById('news-category').value = item.category || '';
      document.getElementById('news-category').readOnly = item.category === '首页滚动';
      document.getElementById('news-title').placeholder = item.category === '首页滚动' ? '首页滚动标题' : '资讯标题';
      document.getElementById('news-summary').value = item.summary || '';
      if (quill) setEditorContents(quill, item.content || '');
      document.getElementById('news-form-title').textContent = '编辑资讯';
      newsEditingId = id;
      if (item.image_url) {
        const preview = document.getElementById('news-image-preview');
        preview.src = item.image_url;
        preview.classList.remove('hidden');
        document.getElementById('news-upload-placeholder').classList.add('hidden');
        preview.dataset.url = item.image_url;
      }
    }
  } catch {}
}

async function deleteNews(id) {
  if (!confirm('确定删除这条资讯？')) return;
  try {
    const res = await fetch(`${API}/api/news/${id}`, {
      method: 'DELETE', headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (res.ok) { showToast('已删除', 'success'); loadAdminNews(); }
  } catch {}
}

async function uploadNewsImage(input) {
  if (!input.files[0]) return;
  const formData = new FormData();
  formData.append('file', input.files[0]);
  try {
    const res = await fetch(`${API}/api/admin/upload`, {
      method: 'POST', headers: { 'Authorization': `Bearer ${getToken()}` }, body: formData,
    });
    const data = await res.json();
    if (res.ok) {
      const preview = document.getElementById('news-image-preview');
      preview.src = data.url;
      preview.classList.remove('hidden');
      document.getElementById('news-upload-placeholder').classList.add('hidden');
      preview.dataset.url = data.url;
    } else { showToast('上传失败', 'error'); }
  } catch { showToast('上传失败', 'error'); }
}

// ===== Agent Management =====
async function loadAdminAgents() {
  try {
    const res = await fetch(`${API}/api/admin/agents`, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    if (!res.ok) return;
    const data = await res.json();
    const agents = data.agents || [];
    const container = document.getElementById('admin-agents-list');
    if (!container) return;

    container.innerHTML = agents.map(a => `
      <div class="agent-card">
        <div class="agent-header">
          <div class="agent-avatar" style="background:${a.color}"><i class="ph ph-${a.icon || 'robot'}"></i></div>
          <div class="agent-name">${esc(a.name)}</div>
        </div>
        <div class="field"><label>名称</label><input type="text" id="ag-name-${a.agent_id}" value="${esc(a.name)}"></div>
        <div class="field"><label>首页描述（简洁）</label><input type="text" id="ag-desc-${a.agent_id}" value="${esc(a.description || '')}"></div>
        <div class="field"><label>聊天描述（详细、切换时展示）</label><textarea id="ag-chat-desc-${a.agent_id}" rows="2">${esc(a.chat_desc || '')}</textarea></div>
        <div class="field"><label>快捷消息</label><input type="text" id="ag-prompt-${a.agent_id}" value="${esc(a.prompt || '')}"></div>
        <div style="display:flex;gap:12px">
          <div class="field" style="flex:1"><label>颜色</label><input type="color" id="ag-color-${a.agent_id}" value="${a.color}"></div>
          <div class="field" style="flex:1"><label>图标（Phosphor 名）</label><input type="text" id="ag-icon-${a.agent_id}" value="${esc(a.icon || 'robot')}"></div>
        </div>
        <div class="field"><label>机器人 ID</label><input type="text" id="ag-bot-${a.agent_id}" value="${esc(a.bot_id || '')}"></div>
        <div class="field">
          <label>头像图片</label>
          <div class="upload-area" onclick="document.getElementById('ag-avatar-input-${a.agent_id}').click()">
            ${a.avatar_url ? '<img src="' + esc(a.avatar_url) + '" id="ag-avatar-preview-' + a.agent_id + '">' : '<div id="ag-avatar-ph-' + a.agent_id + '"><i class="ph ph-upload"></i><span>点击上传头像</span></div>'}
          </div>
          <input type="file" id="ag-avatar-input-${a.agent_id}" accept="image/*" class="hidden" onchange="uploadAgentAvatar('${a.agent_id}', this)">
          <input type="hidden" id="ag-avatar-${a.agent_id}" value="${esc(a.avatar_url || '')}">
        </div>
        <div class="agent-actions">
          <button class="btn btn-primary" onclick="saveAgent('${a.agent_id}')">保存</button>
          <button class="btn btn-danger" onclick="deleteAgent('${a.agent_id}')">删除</button>
        </div>
      </div>
    `).join('');
  } catch (e) { console.error('loadAdminAgents error:', e); }

  // Load system config too
  loadAdminSystemConfig();
  loadWaitingSettings();
}

async function loadAdminSystemConfig() {
  try {
    const [keyRes, blockRes, speechRes] = await Promise.all([
      fetch(`${API}/api/admin/settings/coze-api-key`, { headers: { 'Authorization': `Bearer ${getToken()}` } }),
      fetch(`${API}/api/admin/settings/blocked-keywords`, { headers: { 'Authorization': `Bearer ${getToken()}` } }),
      fetch(`${API}/api/admin/settings/speech`, { headers: { 'Authorization': `Bearer ${getToken()}` } }),
    ]);
    let keyMasked = '未设置', blockedKW = '', defaultHint = '', speechEnabled = false;
    let speechMode = 'auto', tencentAppId = '', tencentSecretId = '', tencentSecretMasked = '';
    if (keyRes.ok) { const kd = await keyRes.json(); keyMasked = kd.masked || '未设置'; }
    if (blockRes.ok) { const bd = await blockRes.json(); blockedKW = bd.keywords || ''; defaultHint = bd.defaultHint || ''; }
    if (speechRes.ok) {
      const sd = await speechRes.json();
      speechEnabled = !!sd.enabled;
      speechMode = sd.mode || 'auto';
      tencentAppId = sd.tencent_app_id || '';
      tencentSecretId = sd.tencent_secret_id || '';
      tencentSecretMasked = sd.tencent_secret_key_masked || '';
    }
    document.getElementById('coze-key-label').textContent = `Coze API Key（当前: ${keyMasked}）`;
    document.getElementById('blocked-keywords-input').value = blockedKW;
    document.getElementById('blocked-hint').textContent = `参考: ${defaultHint}`;
    document.getElementById('speech-enabled-input').checked = speechEnabled;
    document.getElementById('speech-mode-input').value = speechMode;
    document.getElementById('tencent-app-id-input').value = tencentAppId;
    document.getElementById('tencent-secret-id-input').value = tencentSecretId;
    document.getElementById('tencent-secret-key-input').value = '';
    document.getElementById('tencent-secret-hint').textContent = tencentSecretMasked ? `已保存 SecretKey：${tencentSecretMasked}` : '尚未保存 SecretKey';
  } catch { console.error('loadAdminSystemConfig error'); }
}

async function loadShareSettings() {
  try {
    const res = await fetch(`${API}/api/admin/settings/share`, {
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!res.ok) throw new Error('load share settings failed');
    const data = await res.json();
    document.getElementById('share-title-input').value = data.title || '';
    document.getElementById('share-description-input').value = data.description || '';
    document.getElementById('share-image-url-input').value = data.image_url || '';
    updateShareImagePreview(data.image_url || '');
  } catch (e) {
    console.error('loadShareSettings error:', e);
  }
}

function updateShareImagePreview(url) {
  const wrap = document.getElementById('share-image-preview-wrap');
  const preview = document.getElementById('share-image-preview');
  if (!wrap || !preview) return;
  if (!url) {
    wrap.style.display = 'none';
    preview.removeAttribute('src');
    return;
  }
  preview.src = url;
  preview.onerror = () => { wrap.style.display = 'none'; };
  preview.onload = () => { wrap.style.display = 'block'; };
}

async function uploadShareImage(input) {
  if (!input.files[0]) return;
  const formData = new FormData();
  formData.append('file', input.files[0]);
  try {
    const res = await fetch(`${API}/api/admin/upload`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '上传失败');
    document.getElementById('share-image-url-input').value = data.url || '';
    updateShareImagePreview(data.url || '');
    showToast('缩略图已上传，请保存分享设置', 'success');
  } catch (e) {
    showToast(e.message || '上传失败', 'error');
  } finally {
    input.value = '';
  }
}

async function saveShareSettings() {
  const title = document.getElementById('share-title-input').value.trim();
  const description = document.getElementById('share-description-input').value.trim();
  const image_url = document.getElementById('share-image-url-input').value.trim();
  if (!title) return showToast('请填写分享标题', 'error');
  try {
    const res = await fetch(`${API}/api/admin/settings/share`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ title, description, image_url }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '保存失败');
    document.getElementById('share-image-url-input').value = data.image_url || image_url;
    updateShareImagePreview(data.image_url || image_url);
    showToast('分享设置已保存', 'success');
  } catch (e) {
    showToast(e.message || '保存失败', 'error');
  }
}

function showCreateAgentForm() {
  document.getElementById('create-agent-form').style.display = 'block';
}
function hideCreateAgentForm() {
  document.getElementById('create-agent-form').style.display = 'none';
}

async function createAgent() {
  const agent_id = document.getElementById('new-agent-id').value.trim();
  const name = document.getElementById('new-agent-name').value.trim();
  if (!agent_id || !name) return showToast('标识ID和名称不能为空', 'error');
  try {
    const res = await fetch(`${API}/api/admin/agents`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({
        agent_id, name,
        type: 'custom',
        description: document.getElementById('new-agent-desc').value,
        chat_desc: document.getElementById('new-agent-chat-desc').value,
        prompt: document.getElementById('new-agent-prompt').value,
        color: document.getElementById('new-agent-color').value,
        icon: document.getElementById('new-agent-icon').value || 'robot',
        bot_id: document.getElementById('new-agent-bot').value,
      }),
    });
    if (res.ok) {
      showToast('智能体已创建', 'success');
      hideCreateAgentForm();
      document.getElementById('new-agent-id').value = '';
      document.getElementById('new-agent-name').value = '';
      document.getElementById('new-agent-desc').value = '';
      document.getElementById('new-agent-chat-desc').value = '';
      document.getElementById('new-agent-prompt').value = '';
      document.getElementById('new-agent-icon').value = '';
      document.getElementById('new-agent-bot').value = '';
      loadAdminAgents();
    } else { const d = await res.json(); showToast(d.error || '创建失败', 'error'); }
  } catch { showToast('创建失败', 'error'); }
}

async function deleteAgent(agentId) {
  if (!confirm(`确定删除智能体？`)) return;
  try {
    const res = await fetch(`${API}/api/admin/agents/${agentId}`, {
      method: 'DELETE', headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (res.ok) { showToast('已删除', 'success'); loadAdminAgents(); }
    else { showToast('删除失败', 'error'); }
  } catch { showToast('删除失败', 'error'); }
}

async function uploadAgentAvatar(agentId, input) {
  if (!input.files[0]) return;
  const formData = new FormData();
  formData.append('file', input.files[0]);
  try {
    const res = await fetch(`${API}/api/admin/upload`, {
      method: 'POST', headers: { 'Authorization': `Bearer ${getToken()}` }, body: formData,
    });
    const data = await res.json();
    if (res.ok) {
      document.getElementById(`ag-avatar-${agentId}`).value = data.url;
      const preview = document.getElementById(`ag-avatar-preview-${agentId}`);
      if (preview) { preview.src = data.url; preview.classList.remove('hidden'); }
      document.getElementById(`ag-avatar-ph-${agentId}`)?.classList.add('hidden');
    } else { showToast('上传失败', 'error'); }
  } catch { showToast('上传失败', 'error'); }
}

async function saveAgent(agentId) {
  const name = document.getElementById(`ag-name-${agentId}`).value.trim();
  if (!name) return showToast('名称不能为空', 'error');
  try {
    const res = await fetch(`${API}/api/admin/agents/${agentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({
        name,
        description: document.getElementById(`ag-desc-${agentId}`).value,
        chat_desc: document.getElementById(`ag-chat-desc-${agentId}`).value,
        prompt: document.getElementById(`ag-prompt-${agentId}`).value,
        color: document.getElementById(`ag-color-${agentId}`).value,
        icon: document.getElementById(`ag-icon-${agentId}`).value || 'robot',
        bot_id: document.getElementById(`ag-bot-${agentId}`).value,
        avatar_url: document.getElementById(`ag-avatar-${agentId}`).value,
      }),
    });
    if (res.ok) { showToast('已保存', 'success'); }
    else { showToast('保存失败', 'error'); }
  } catch { showToast('保存失败', 'error'); }
}

// ===== System Config =====
async function updateCozeApiKey() {
  const input = document.getElementById('coze-api-key-input');
  const key = input.value.trim();
  if (!key) return showToast('请粘贴 API Key', 'error');
  try {
    const res = await fetch(`${API}/api/admin/settings/coze-api-key`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ api_key: key }),
    });
    if (res.ok) {
      showToast('API Key 已更新', 'success');
      input.value = '';
      loadAdminAgents();
    } else { const d = await res.json(); showToast(d.error || '更新失败', 'error'); }
  } catch { showToast('更新失败', 'error'); }
}

async function saveBlockedKeywords() {
  const val = document.getElementById('blocked-keywords-input').value.trim();
  try {
    const res = await fetch(`${API}/api/admin/settings/blocked-keywords`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ keywords: val }),
    });
    if (res.ok) { showToast('屏蔽词已保存', 'success'); }
    else { showToast('保存失败', 'error'); }
  } catch { showToast('保存失败', 'error'); }
}

async function saveSpeechSettings() {
  const enabled = document.getElementById('speech-enabled-input').checked;
  const mode = document.getElementById('speech-mode-input').value || 'auto';
  const tencentAppId = document.getElementById('tencent-app-id-input').value.trim();
  const tencentSecretId = document.getElementById('tencent-secret-id-input').value.trim();
  const tencentSecretKey = document.getElementById('tencent-secret-key-input').value.trim();
  try {
    const res = await fetch(`${API}/api/admin/settings/speech`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({
        enabled,
        mode,
        tencent_app_id: tencentAppId,
        tencent_secret_id: tencentSecretId,
        tencent_secret_key: tencentSecretKey,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToast('语音设置已保存', 'success');
      document.getElementById('tencent-secret-key-input').value = '';
      document.getElementById('tencent-secret-hint').textContent = data.tencent_secret_key_masked
        ? `已保存 SecretKey：${data.tencent_secret_key_masked}`
        : '尚未保存 SecretKey';
    } else {
      showToast(data.error || '保存失败', 'error');
    }
  } catch {
    showToast('保存失败', 'error');
  }
}



// ===== Waiting Tips =====
let tipItems = [];
let tipStepsCache = [];

async function loadWaitingSettings() {
  try {
    const res = await fetch(`${API}/api/admin/settings/waiting-content`, {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (res.ok) {
      const data = await res.json();
      tipStepsCache = (data.steps || []).length > 0 ? data.steps : [
        '正在理解您的问题...', '正在匹配最佳智能体...', '正在检索产品知识库...',
        '正在分析问题关键点...', '正在构思回答框架...', '正在组织语言表达...',
        '正在校验回答准确性...', '正在润色语言风格...', '正在生成完整回复...', '即将完成...',
      ];
      tipItems = data.tips || [];
      renderTipList();
    }
  } catch { console.error('loadWaitingSettings error'); }
}

function renderTipList() {
  const container = document.getElementById('tip-list');
  document.getElementById('tip-count').textContent = `当前共 ${tipItems.length} 条`;
  if (tipItems.length === 0) {
    container.innerHTML = '<div class="empty-state" style="padding:20px"><i class="ph ph-chats"></i><p>暂无小贴士，在上方添加</p></div>';
    return;
  }
  container.innerHTML = tipItems.map((t, i) =>
    `<div class="tip-card" draggable="true" data-idx="${i}">
      <span class="tip-drag"><i class="ph ph-grip-vertical"></i></span>
      <span class="tip-text">${esc(t)}</span>
      <button class="tip-del" onclick="removeTip(${i})"><i class="ph ph-x"></i></button>
    </div>`
  ).join('');

  container.querySelectorAll('.tip-card').forEach(el => {
    el.addEventListener('dragstart', onTipDragStart);
    el.addEventListener('dragover', onTipDragOver);
    el.addEventListener('drop', onTipDrop);
    el.addEventListener('dragend', onTipDragEnd);
  });
}

let dragSrcIdx = null;
function onTipDragStart(e) {
  dragSrcIdx = parseInt(e.target.closest('.tip-card').dataset.idx);
  e.target.closest('.tip-card').classList.add('dragging');
}
function onTipDragOver(e) { e.preventDefault(); }
function onTipDrop(e) {
  e.preventDefault();
  const target = e.target.closest('.tip-card');
  if (!target) return;
  const targetIdx = parseInt(target.dataset.idx);
  if (dragSrcIdx === targetIdx) return;
  const [moved] = tipItems.splice(dragSrcIdx, 1);
  tipItems.splice(targetIdx, 0, moved);
  renderTipList();
}
function onTipDragEnd(e) {
  document.querySelectorAll('.tip-card').forEach(el => el.classList.remove('dragging'));
}

function addTip() {
  const input = document.getElementById('tip-input');
  const val = input.value.trim();
  if (!val) return;
  tipItems.push(val);
  input.value = '';
  renderTipList();
  input.focus();
}

function removeTip(idx) {
  tipItems.splice(idx, 1);
  renderTipList();
}

async function saveWaitingTips() {
  if (tipItems.length === 0) return showToast('至少需要一条小贴士', 'error');
  try {
    const res = await fetch(`${API}/api/admin/settings/waiting-content`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({
        steps: JSON.stringify(tipStepsCache),
        tips: JSON.stringify(tipItems),
      }),
    });
    if (res.ok) { showToast('小贴士已保存', 'success'); }
    else { showToast('保存失败', 'error'); }
  } catch { showToast('保存失败', 'error'); }
}

// ===== Utilities =====
function fmt(d) {
  if (!d) return '';
  return new Date(d).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

async function loadAdminLeads() {
  const list = document.getElementById('lead-list');
  const params = new URLSearchParams({ limit: '100' });
  list.innerHTML = '<div class="loading"><i class="ph ph-spinner"></i> 加载中...</div>';
  try {
    const res = await fetch(apiUrl(`/api/admin/leads?${params}`), { headers: { Authorization: `Bearer ${getToken()}` } });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '加载失败');
    document.getElementById('lead-count').textContent = data.total || 0;
    if (!data.items.length) { list.innerHTML = '<div class="empty-state">暂无客户需求</div>'; return; }
    list.innerHTML = data.items.map(item => `<div class="admin-card" style="margin:10px 0;border:1px solid var(--slate-200)">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><strong>${esc(item.customer_type === 'partner' ? '经销商/合作伙伴' : '消费者')} · ${esc(item.product_name || '未指定产品')}</strong><span style="font-size:12px;color:var(--slate-400)">${esc(item.created_at)}</span></div>
      <p style="margin:8px 0;color:var(--slate-600);white-space:pre-wrap">${esc(item.description)}</p>
      <div style="font-size:12px;color:var(--slate-500)">联系方式：${esc([item.phone, item.wechat].filter(Boolean).join(' / '))} · 来源：${esc(item.query_type || item.agent_id || '-')}</div>
    </div>`).join('');
  } catch (err) { list.innerHTML = `<div class="empty-state">${esc(err.message || '加载失败')}</div>`; }
}

// ===== Handoff (人工客服) Page =====
async function loadHandoffPage() {
  await Promise.all([loadHandoffSettings(), loadCsAgents(), loadQuickReplies()]);
}

async function loadHandoffSettings() {
  try {
    const [settingsRes, agentsRes] = await Promise.all([
      fetch(apiUrl('/api/admin/settings/handoff'), { headers: { Authorization: `Bearer ${getToken()}` } }),
      fetch(apiUrl('/api/admin/agents'), { headers: { Authorization: `Bearer ${getToken()}` } }),
    ]);
    const settings = await settingsRes.json();
    if (!settingsRes.ok) throw new Error(settings.error || '加载转人工设置失败');
    const agentsData = await agentsRes.json().catch(() => ({ agents: [] }));

    const select = document.getElementById('handoff-ai-agent-select');
    const agents = agentsData.agents || [];
    select.innerHTML = '<option value="">（请选择营养咨询 AI）</option>' + agents.map(item => {
      const hasBot = !!(item.bot_id || '').trim();
      return `<option value="${esc(item.agent_id)}" ${hasBot ? '' : 'disabled'}>${esc(item.name || item.agent_id)}${hasBot ? '' : '（未配置Bot）'}</option>`;
    }).join('');

    document.getElementById('handoff-enabled-input').checked = !!settings.enabled;
    if (settings.ai_agent_id) select.value = settings.ai_agent_id;
    document.getElementById('handoff-button-label-input').value = settings.button_label || '';
    document.getElementById('handoff-queue-msg-input').value = settings.queue_msg || '';
    document.getElementById('handoff-offline-msg-input').value = settings.offline_msg || '';
    document.getElementById('handoff-welcome-msg-input').value = settings.welcome_msg || '';
    document.getElementById('handoff-avg-handle-input').value = settings.avg_handle_sec || 180;
    document.getElementById('handoff-live-wait-input').value = settings.live_wait_sec || 600;
  } catch (err) {
    showToast(err.message || '加载转人工设置失败', 'error');
  }
}

async function saveHandoffSettings() {
  const payload = {
    enabled: document.getElementById('handoff-enabled-input').checked,
    ai_agent_id: document.getElementById('handoff-ai-agent-select').value,
    button_label: document.getElementById('handoff-button-label-input').value.trim(),
    queue_msg: document.getElementById('handoff-queue-msg-input').value.trim(),
    offline_msg: document.getElementById('handoff-offline-msg-input').value.trim(),
    welcome_msg: document.getElementById('handoff-welcome-msg-input').value.trim(),
    avg_handle_sec: Number(document.getElementById('handoff-avg-handle-input').value) || 180,
    live_wait_sec: Number(document.getElementById('handoff-live-wait-input').value) || 600,
  };
  try {
    const res = await fetch(apiUrl('/api/admin/settings/handoff'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '保存失败');
    showToast('转人工设置已保存', 'success');
    loadHandoffSettings();
  } catch (err) {
    showToast(err.message || '保存失败', 'error');
  }
}

async function loadCsAgents() {
  const list = document.getElementById('cs-agent-list');
  if (!list) return;
  list.innerHTML = '<div class="loading"><i class="ph ph-spinner"></i> 加载中...</div>';
  try {
    const res = await fetch(apiUrl('/api/admin/handoff/agents'), { headers: { Authorization: `Bearer ${getToken()}` } });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '加载坐席名单失败');
    renderCsAgents(data.agents || []);
  } catch (err) {
    list.innerHTML = `<div class="empty-state">${esc(err.message || '加载失败')}</div>`;
  }
}

function renderCsAgents(agents) {
  const list = document.getElementById('cs-agent-list');
  if (!agents.length) { list.innerHTML = '<div class="empty-state">暂无坐席，请先添加</div>'; return; }
  list.innerHTML = agents.map(item => `
    <div class="admin-card" style="margin:10px 0;border:1px solid var(--slate-200)">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap">
        <div>
          <strong>${esc(item.display_name || item.user_id)}</strong>
          <span style="font-size:12px;color:var(--slate-400);margin-left:6px">${esc(item.username || item.user_id)}</span>
          <span style="font-size:12px;margin-left:8px;color:${item.online ? 'var(--emerald)' : 'var(--slate-400)'}">${item.online ? '● 在线' : '○ 离线'}</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <label style="font-size:12px;color:var(--slate-500)">并发上限</label>
          <input type="number" min="1" max="10" value="${item.max_concurrent || 3}" style="width:64px" onchange="updateCsAgentMax('${esc(item.user_id)}', this.value)">
          <button class="btn btn-secondary btn-sm" onclick="removeCsAgent('${esc(item.user_id)}', '${esc(item.display_name || item.user_id)}')"><i class="ph ph-trash"></i> 移除</button>
        </div>
      </div>
      <div style="font-size:12px;color:var(--slate-500);margin-top:6px">当前接待 ${item.current_load || 0} / ${item.max_concurrent || 3} · 最后心跳：${esc(item.last_seen_at || '从未上线')}</div>
    </div>`).join('');
}

async function updateCsAgentMax(userId, value) {
  const max = Math.max(1, Math.min(10, Number(value) || 3));
  try {
    const res = await fetch(apiUrl(`/api/admin/handoff/agents/${encodeURIComponent(userId)}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ max_concurrent: max }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '更新失败');
    showToast('坐席并发上限已更新', 'success');
  } catch (err) {
    showToast(err.message || '更新失败', 'error');
    loadCsAgents();
  }
}

async function addCsAgent() {
  const username = document.getElementById('cs-agent-username-input').value.trim();
  const display_name = document.getElementById('cs-agent-display-input').value.trim();
  const password = document.getElementById('cs-agent-password-input').value;
  const max_concurrent = Number(document.getElementById('cs-agent-max-input').value) || 3;
  if (!username) return showToast('请填写人工账号用户名', 'error');
  try {
    const res = await fetch(apiUrl('/api/admin/handoff/agents'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ username, display_name, max_concurrent, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '添加失败');
    showToast('坐席已添加，用该账号登录营养师工作台即可接单', 'success');
    document.getElementById('cs-agent-username-input').value = '';
    document.getElementById('cs-agent-display-input').value = '';
    document.getElementById('cs-agent-password-input').value = '';
    loadCsAgents();
  } catch (err) {
    showToast(err.message || '添加失败', 'error');
  }
}

async function removeCsAgent(userId, displayName) {
  if (!confirm(`确定移除坐席「${displayName}」？其排队中的会话会释放回队列。`)) return;
  try {
    const res = await fetch(apiUrl(`/api/admin/handoff/agents/${encodeURIComponent(userId)}`), {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '移除失败');
    showToast(data.released_sessions ? `坐席已移除，${data.released_sessions} 个排队会话已释放` : '坐席已移除', 'success');
    loadCsAgents();
  } catch (err) {
    showToast(err.message || '移除失败', 'error');
  }
}

let quickRepliesCache = [];
let editingQuickReplyId = null;

async function loadQuickReplies() {
  const list = document.getElementById('quick-reply-list');
  if (!list) return;
  list.innerHTML = '<div class="loading"><i class="ph ph-spinner"></i> 加载中...</div>';
  try {
    const res = await fetch(apiUrl('/api/admin/handoff/quick-replies'), { headers: { Authorization: `Bearer ${getToken()}` } });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '加载话术库失败');
    renderQuickReplies(data.quick_replies || []);
  } catch (err) {
    list.innerHTML = `<div class="empty-state">${esc(err.message || '加载失败')}</div>`;
  }
}

function renderQuickReplies(items) {
  quickRepliesCache = items || [];
  const list = document.getElementById('quick-reply-list');
  if (!items.length) { list.innerHTML = '<div class="empty-state">暂无话术，请先添加</div>'; return; }
  list.innerHTML = items.map(item => `
    <div class="admin-card" style="margin:10px 0;border:1px solid var(--slate-200)">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap">
        <div style="flex:1;min-width:220px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <strong>${esc(item.title)}</strong>
            <span style="font-size:12px;color:${item.enabled ? 'var(--emerald)' : 'var(--slate-400)'}">${item.enabled ? '启用中' : '已禁用'}</span>
            <span style="font-size:12px;color:var(--slate-400)">排序 ${item.sort_order}</span>
          </div>
          <div style="font-size:13px;color:var(--slate-600);margin-top:6px;white-space:pre-wrap;line-height:1.5">${esc(item.content)}</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-shrink:0">
          <button class="btn btn-secondary btn-sm" onclick="editQuickReply(${item.id})"><i class="ph ph-pencil"></i> 编辑</button>
          <button class="btn btn-secondary btn-sm" onclick="toggleQuickReply(${item.id}, ${item.enabled ? 0 : 1})">${item.enabled ? '禁用' : '启用'}</button>
          <button class="btn btn-secondary btn-sm" onclick="deleteQuickReply(${item.id}, '${esc(item.title)}')"><i class="ph ph-trash"></i> 删除</button>
        </div>
      </div>
    </div>`).join('');
}

async function addQuickReply() {
  const title = document.getElementById('quick-reply-title-input').value.trim();
  const content = document.getElementById('quick-reply-content-input').value.trim();
  const sort_order = Number(document.getElementById('quick-reply-sort-input').value) || 0;
  const enabled = document.getElementById('quick-reply-enabled-input').checked;
  if (!title) return showToast('请填写话术标题', 'error');
  if (!content) return showToast('请填写话术内容', 'error');
  const url = editingQuickReplyId
    ? apiUrl(`/api/admin/handoff/quick-replies/${editingQuickReplyId}`)
    : apiUrl('/api/admin/handoff/quick-replies');
  const method = editingQuickReplyId ? 'PUT' : 'POST';
  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ title, content, sort_order, enabled }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '保存失败');
    showToast(editingQuickReplyId ? '话术已更新' : '话术已添加', 'success');
    cancelQuickReplyEdit();
    loadQuickReplies();
  } catch (err) {
    showToast(err.message || '保存失败', 'error');
  }
}

function editQuickReply(id) {
  const item = quickRepliesCache.find((entry) => entry.id === id);
  if (!item) return;
  editingQuickReplyId = id;
  document.getElementById('quick-reply-title-input').value = item.title;
  document.getElementById('quick-reply-content-input').value = item.content;
  document.getElementById('quick-reply-sort-input').value = item.sort_order;
  document.getElementById('quick-reply-enabled-input').checked = !!item.enabled;
  document.getElementById('quick-reply-submit-text').textContent = '保存修改';
  document.getElementById('quick-reply-cancel-edit').hidden = false;
  document.getElementById('quick-reply-title-input').focus();
}

function cancelQuickReplyEdit() {
  editingQuickReplyId = null;
  document.getElementById('quick-reply-title-input').value = '';
  document.getElementById('quick-reply-content-input').value = '';
  document.getElementById('quick-reply-sort-input').value = '0';
  document.getElementById('quick-reply-enabled-input').checked = true;
  document.getElementById('quick-reply-submit-text').textContent = '添加话术';
  document.getElementById('quick-reply-cancel-edit').hidden = true;
}

async function toggleQuickReply(id, enabled) {
  try {
    const res = await fetch(apiUrl(`/api/admin/handoff/quick-replies/${id}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ enabled: !!enabled }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '操作失败');
    showToast(enabled ? '话术已启用' : '话术已禁用', 'success');
    loadQuickReplies();
  } catch (err) {
    showToast(err.message || '操作失败', 'error');
  }
}

async function deleteQuickReply(id, title) {
  if (!confirm(`确定删除话术「${title}」？`)) return;
  try {
    const res = await fetch(apiUrl(`/api/admin/handoff/quick-replies/${id}`), {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '删除失败');
    showToast('话术已删除', 'success');
    if (editingQuickReplyId === id) cancelQuickReplyEdit();
    loadQuickReplies();
  } catch (err) {
    showToast(err.message || '删除失败', 'error');
  }
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (type || 'info');
  requestAnimationFrame(() => requestAnimationFrame(() => t.classList.add('show')));
  clearTimeout(t._timeout);
  t._timeout = setTimeout(() => t.classList.remove('show'), 3000);
}

// ===== Product Admin =====
let prodQuill = null;

function initProdQuill() {
  const card = document.getElementById('prod-form-card');
  if (!card || card.style.display === 'none') return;
  if (typeof Quill === 'undefined') return;
  // Quill 2 没有 destroy()（实测 quill@2.0.3 里这个词一次都不出现），旧代码在这里调
  // prodQuill.destroy() 会直接抛 TypeError，后面的 new Quill 和内容填充统统执行不到——
  // 表现就是「编辑器永远停在上一次打开的内容」。所以这里做成惰性单例：只建一次，
  // 内容一律由 setEditorContents 覆盖，绝不销毁重建（重建还会叠加第二套工具栏）。
  if (prodQuill) return;
  registerRichTextFormats();
  prodQuill = new Quill('#prod-editor', {
    theme: 'snow',
    modules: { toolbar: richTextToolbar() },
    placeholder: '输入产品详细介绍...',
  });
  prodQuill.getModule('toolbar').addHandler('image', handleProdEditorImage);
  localizeToolbarPickers(prodQuill);
  setupFormatPainter(prodQuill);
  bindEditorImageEvents(prodQuill);
}

function handleProdEditorImage() {
  pickEditorImage(prodQuill);
}

function showProdForm() {
  document.getElementById('prod-form-card').style.display = 'block';
  document.getElementById('prod-form-title').innerHTML = '<i class="ph ph-pencil"></i> 新增产品';
  document.getElementById('prod-editing-id').value = '';
  document.getElementById('prod-name').value = '';
  document.getElementById('prod-category').value = '';
  document.getElementById('prod-summary').value = '';
  document.getElementById('prod-highlights').value = '';
  document.getElementById('prod-image-url').value = '';
  ensureQuill().then(() => setTimeout(() => {
    initProdQuill();
    // 新增必须是空白，否则残留上次编辑/查看的内容
    setEditorContents(prodQuill, '');
  }, 200)).catch(e => console.error('quill load error:', e));
}

function hideProdForm() {
  document.getElementById('prod-form-card').style.display = 'none';
}

function resetProdForm() {
  hideProdForm();
}

function editProduct(id) {
  const p = prodCache.find(x => x.id === id);
  if (!p) return;
  document.getElementById('prod-form-card').style.display = 'block';
  document.getElementById('prod-form-title').innerHTML = `<i class="ph ph-pencil"></i> 编辑「${escapeHtml(p.name)}」`;
  document.getElementById('prod-editing-id').value = p.id;
  document.getElementById('prod-name').value = p.name || '';
  document.getElementById('prod-category').value = p.category || '';
  document.getElementById('prod-summary').value = p.summary || '';
  document.getElementById('prod-highlights').value = p.highlights || '';
  document.getElementById('prod-image-url').value = p.image_url || '';
  ensureQuill().then(() => {
    setTimeout(() => {
      initProdQuill();
      setEditorContents(prodQuill, p.content);
    }, 200);
  }).catch(e => console.error('quill load error:', e));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

let prodCache = [];

async function loadAdminProducts() {
  try {
    const res = await fetch(API + '/api/products', {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    prodCache = data.products || [];
    const list = document.getElementById('admin-products-list');
    if (!prodCache.length) {
      list.innerHTML = '<div class="empty-state"><i class="ph ph-package"></i><p>暂无产品，点击右上角「新增」添加</p></div>';
    } else {
      list.innerHTML = prodCache.map(p => `
        <div class="admin-list-item">
          <div>
            <div class="item-title">${escapeHtml(p.name)}</div>
            <div class="item-meta">${escapeHtml(p.category || '未分类')} · ${escapeHtml(p.summary || '')}</div>
          </div>
          <div class="item-actions">
            <button class="btn btn-secondary btn-sm" onclick="editProduct(${p.id})"><i class="ph ph-pencil"></i></button>
            <button class="btn btn-secondary btn-sm" onclick="deleteProduct(${p.id})" style="color:var(--rose)"><i class="ph ph-trash"></i></button>
          </div>
        </div>
      `).join('');
    }
    // 分类排序列表
    const cats = data.categories || [];
    const sortList = document.getElementById('category-sort-list');
    if (sortList) {
      categorySortState = [...cats];
      sortList.innerHTML = cats.map((c, i) =>
        `<div class="category-sort-item" data-idx="${i}" style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--slate-100)">
          <span style="flex:1;font-size:13px;font-weight:500">${esc(c)}</span>
          <span style="font-size:11px;color:var(--slate-400);margin-right:8px">${i === 0 ? '顶部' : i === cats.length - 1 ? '底部' : ''}</span>
          <button class="btn btn-secondary btn-sm" onclick="moveCatUp(${i})" ${i === 0 ? 'disabled' : ''}>↑</button>
          <button class="btn btn-secondary btn-sm" onclick="moveCatDown(${i})" ${i === cats.length - 1 ? 'disabled' : ''}>↓</button>
        </div>`
      ).join('');
    }
  } catch {}
}

function moveCatUp(i) { moveCategory(i, i - 1); }
function moveCatDown(i) { moveCategory(i, i + 1); }

function moveCategory(from, to) {
  const arr = categorySortState;
  if (to < 0 || to >= arr.length) return;
  const el = arr.splice(from, 1);
  arr.splice(to, 0, el[0]);
  const list = document.getElementById('category-sort-list');
  list.innerHTML = arr.map((c, i) =>
    `<div class="category-sort-item" style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--slate-100)">
      <span style="flex:1;font-size:13px;font-weight:500">${esc(c)}</span>
      <button class="btn btn-secondary btn-sm" onclick="moveCatUp(${i})" ${i === 0 ? 'disabled' : ''}>↑</button>
      <button class="btn btn-secondary btn-sm" onclick="moveCatDown(${i})" ${i === arr.length - 1 ? 'disabled' : ''}>↓</button>
    </div>`
  ).join('');
}

async function saveCategoryOrder() {
  try {
    const res = await fetch(`${API}/api/products/category-order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ categories: categorySortState }),
    });
    if (res.ok) showToast('分类排序已保存', 'success');
  } catch { showToast('保存失败', 'error'); }
}

async function saveProduct() {
  const id = document.getElementById('prod-editing-id').value;
  const body = {
    name: document.getElementById('prod-name').value.trim(),
    category: document.getElementById('prod-category').value.trim(),
    summary: document.getElementById('prod-summary').value.trim(),
    highlights: document.getElementById('prod-highlights').value.trim(),
    image_url: document.getElementById('prod-image-url').value.trim(),
    // 编辑器未就绪时不能用空串覆盖正文：编辑已有产品保留原 content，避免把数据库正文清空
    content: prodQuill ? prodQuill.root.innerHTML : (id ? (prodCache.find(x => x.id === parseInt(id)) || {}).content || '' : ''),
    sort_order: id ? (prodCache.find(x => x.id === parseInt(id)) || {}).sort_order || 0 : (prodCache.length + 1) * 10,
  };
  if (!body.name) { alert('请输入产品名称'); return; }

  const url = id ? `${API}/api/products/${id}` : `${API}/api/products`;
  const method = id ? 'PUT' : 'POST';

  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      hideProdForm();
      loadAdminProducts();
    }
  } catch {}
}

async function deleteProduct(id) {
  if (!confirm('确定删除该产品？')) return;
  try {
    const res = await fetch(`${API}/api/products/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (res.ok) loadAdminProducts();
  } catch {}
}

function uploadProductImage(input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  fetch(`${API}/api/admin/upload`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${getToken()}` },
    body: formData,
  }).then(r => r.json()).then(d => {
    if (d.url) document.getElementById('prod-image-url').value = d.url;
  }).catch(() => {});
}

// ===== Admin Q&A =====
let qaEditingId = null;

function resetQAForm() {
  qaEditingId = null;
  document.getElementById('qa-editing-id').value = '';
  document.getElementById('qa-question').value = '';
  document.getElementById('qa-category').value = '';
  document.getElementById('qa-answer').value = '';
  document.getElementById('qa-form-title').innerHTML = '<i class="ph ph-pencil"></i> 新增问答';
}

async function loadAdminQA() {
  try {
    const res = await fetch(`${API}/api/community/admin/questions?page=1&limit=50`, {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    const list = document.getElementById('admin-qa-list');
    if (!data.items || !data.items.length) {
      list.innerHTML = '<div class="empty-state"><i class="ph ph-chats"></i><p>暂无问答，在上方新增</p></div>';
      return;
    }
    list.innerHTML = data.items.map(q => `
      <div class="admin-list-item">
        <div style="min-width:0;flex:1">
          <div class="item-title">${esc(q.title)} <span style="font-weight:400;font-size:12px;color:var(--slate-400)">${esc(q.category || '')}</span></div>
          <div class="item-meta">${q.reply_count}条已精选 · ${q.pending_reply_count || 0}条待精选 · ${fmt(q.created_at)} · ${q.status ? '✅ 显示' : '🚫 隐藏'}</div>
          ${renderQAReplies(q.replies || [])}
        </div>
        <div class="item-actions">
          <button class="btn btn-secondary btn-sm" onclick="editQA(${q.id})">编辑</button>
          <button class="btn btn-secondary btn-sm" onclick="toggleQAStatus(${q.id})" style="${q.status ? 'color:var(--emerald)' : 'color:var(--rose)'}">${q.status ? '隐藏' : '显示'}</button>
          <button class="btn btn-danger btn-sm" onclick="deleteQA(${q.id})">删除</button>
        </div>
      </div>
    `).join('');
  } catch {}
}

function renderQAReplies(replies) {
  if (!replies.length) return '';
  return `<div class="qa-replies">${replies.map(r => `
    <div class="qa-reply-item">
      <div class="qa-reply-main">
        <div class="qa-reply-meta">
          匿名用户 · ${fmt(r.created_at)} ·
          <span class="qa-reply-status" style="color:${r.status ? 'var(--emerald)' : 'var(--amber)'}">${r.status ? '已精选' : '待精选'}</span>
        </div>
        <div class="qa-reply-text">${esc(r.content || '')}</div>
      </div>
      <div class="qa-reply-actions">
        <button class="btn btn-secondary btn-sm" onclick="setReplyStatus(${r.id}, ${r.status ? 0 : 1})" style="${r.status ? 'color:var(--rose)' : 'color:var(--emerald)'}">${r.status ? '隐藏' : '精选'}</button>
        <button class="btn btn-danger btn-sm" onclick="deleteReply(${r.id})">删除</button>
      </div>
    </div>
  `).join('')}</div>`;
}

async function editQA(id) {
  try {
    const res = await fetch(`${API}/api/community/questions/${id}`);
    if (!res.ok) return;
    const q = await res.json();
    qaEditingId = id;
    document.getElementById('qa-editing-id').value = id;
    document.getElementById('qa-question').value = q.title || '';
    document.getElementById('qa-category').value = q.category || '';
    document.getElementById('qa-answer').value = q.content || '';
    document.getElementById('qa-form-title').innerHTML = `<i class="ph ph-pencil"></i> 编辑问答`;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch {}
}

async function saveQA() {
  const id = document.getElementById('qa-editing-id').value;
  const title = document.getElementById('qa-question').value.trim();
  const category = document.getElementById('qa-category').value.trim();
  const content = document.getElementById('qa-answer').value.trim();
  if (!title) { showToast('请输入问题', 'error'); return; }
  try {
    const method = id ? 'PUT' : 'POST';
    const url = id ? `${API}/api/community/admin/questions/${id}` : `${API}/api/community/admin/questions`;
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ title, content, category }),
    });
    if (res.ok) {
      showToast(id ? '已更新' : '已创建', 'success');
      resetQAForm();
      loadAdminQA();
    } else { showToast('保存失败', 'error'); }
  } catch { showToast('网络错误', 'error'); }
}

async function toggleQAStatus(id) {
  try {
    const res = await fetch(`${API}/api/community/admin/questions/${id}/status`, {
      method: 'PUT', headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (res.ok) loadAdminQA();
  } catch {}
}

async function deleteQA(id) {
  if (!confirm('确定删除？')) return;
  try {
    const res = await fetch(`${API}/api/community/admin/questions/${id}`, {
      method: 'DELETE', headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (res.ok) { showToast('已删除', 'success'); loadAdminQA(); }
  } catch {}
}

async function deleteQA(id) {
  if (!confirm('确定删除该帖子及其所有回复？')) return;
  try {
    const res = await fetch(`${API}/api/community/admin/questions/${id}`, {
      method: 'DELETE', headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (res.ok) { showToast('已删除', 'success'); loadAdminQA(); }
  } catch {}
}

async function setReplyStatus(id, status) {
  try {
    const res = await fetch(`${API}/api/community/admin/replies/${id}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ status }),
    });
    if (res.ok) {
      showToast(status ? '已精选' : '已隐藏', 'success');
      loadAdminQA();
    } else {
      showToast('操作失败', 'error');
    }
  } catch { showToast('网络错误', 'error'); }
}

async function deleteReply(id) {
  if (!confirm('确定删除这条评论？')) return;
  try {
    const res = await fetch(`${API}/api/community/admin/replies/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (res.ok) {
      showToast('已删除', 'success');
      loadAdminQA();
    } else {
      showToast('删除失败', 'error');
    }
  } catch { showToast('网络错误', 'error'); }
}

// ===== Feature flags =====
let FEATURE_FLAGS = [];

async function loadAdminFeatureFlags() {
  try {
    const res = await fetch(`${API}/api/admin/feature-flags`, {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    FEATURE_FLAGS = data.flags || [];
  } catch {
    FEATURE_FLAGS = [];
  }
  applyAdminFeatureFlags();
}

function applyAdminFeatureFlags() {
  const map = {};
  FEATURE_FLAGS.forEach(item => { map[item.name] = !!item.enabled; });
  document.querySelectorAll('.sidebar-nav [data-feature]').forEach((el) => {
    el.hidden = map[el.dataset.feature] === false;
  });
  // 当前停在已关闭系统的页面上时退回数据看板
  FEATURE_FLAGS.forEach((item) => {
    if (item.enabled) return;
    const page = document.getElementById(`page-${item.name}`);
    if (page && page.classList.contains('active')) switchPage('dashboard');
  });
}

function loadFeatureFlagsPage() {
  const host = document.getElementById('admin-feature-flags-list');
  if (!host) return;
  if (!FEATURE_FLAGS.length) {
    host.innerHTML = '<div style="font-size:13px;color:var(--slate-400)">开关加载失败，请刷新重试。</div>';
    return;
  }
  host.innerHTML = FEATURE_FLAGS.map(item => `
    <div style="padding:14px 0;border-bottom:1px solid var(--slate-100)">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
        <div>
          <div style="font-size:14px;font-weight:700;color:var(--slate-800)">${escapeHtmlAdmin(item.label)}</div>
          <div style="font-size:12px;color:var(--slate-500);margin-top:4px;line-height:1.6">${escapeHtmlAdmin(item.description || '')}</div>
          <div style="font-size:11px;color:var(--slate-400);margin-top:6px">
            当前状态：${item.enabled ? '已开启' : '已关闭'} · 来源：${escapeHtmlAdmin(item.source || '')} · 默认值：${item.default ? '开启' : '关闭'}
          </div>
        </div>
        <label style="display:flex;align-items:center;gap:8px;flex-shrink:0;cursor:pointer">
          <input type="checkbox" id="feature-flag-${escapeHtmlAdmin(item.name)}" ${item.enabled ? 'checked' : ''}
                 onchange="saveFeatureFlag('${escapeHtmlAdmin(item.name)}', this.checked)"
                 style="width:18px;height:18px;accent-color:#0F766E;cursor:pointer">
          <span style="font-size:13px;color:var(--slate-600)">${item.enabled ? '开启' : '关闭'}</span>
        </label>
      </div>
    </div>
  `).join('');
}

function escapeHtmlAdmin(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

async function saveFeatureFlag(name, enabled) {
  try {
    const res = await fetch(`${API}/api/admin/feature-flags`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ name, enabled }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showToast(data.error || '保存失败', 'error');
      await loadAdminFeatureFlags();
      loadFeatureFlagsPage();
      return;
    }
    FEATURE_FLAGS = data.flags || FEATURE_FLAGS;
    applyAdminFeatureFlags();
    loadFeatureFlagsPage();
    showToast(enabled ? '已开启' : '已关闭', 'success');
  } catch {
    showToast('网络错误', 'error');
  }
}

// ===== Init =====
(async function initAdmin() {
  await checkAuth();
  await loadAdminFeatureFlags();
})();
