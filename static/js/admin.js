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
    leads: '客户需求'
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
  try {
    const res = await fetch(apiUrl('/api/admin/dashboard/hot-questions'), {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });
    renderWordCloud((await res.json()).questions);
  } catch (e) { console.error('hot error:', e); }
}

async function loadExampleQuestions() {
  const input = document.getElementById('example-questions-input');
  if (!input) return;
  try {
    const res = await fetch(`${API}/api/admin/settings/example-questions`, { headers: { 'Authorization': `Bearer ${getToken()}` } });
    const data = await res.json();
    input.value = (data.questions || []).join('\n');
  } catch (e) { console.error('example questions error:', e); }
}

async function saveExampleQuestions() {
  const input = document.getElementById('example-questions-input');
  const questions = input.value.split('\n').map(item => item.trim()).filter(Boolean);
  try {
    const res = await fetch(`${API}/api/admin/settings/example-questions`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ questions }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '保存失败');
    input.value = data.questions.join('\n');
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

function renderWordCloud(items) {
  document.getElementById('hot-loading').style.display = 'none';
  const wrap = document.getElementById('hot-check-wrap');
  const list = document.getElementById('hot-check-list');
  fetch(`${API}/api/history/hot-questions`)
    .then(r => r.json())
    .then(d => {
      const approved = (d.questions || []).map(q => q.text);
      // Deduplicate: manual items should not appear as checkboxes too
      const manualSet = new Set(manualHotItems);
      const autoItems = (items || []).filter(item => !manualSet.has(item.text));
      let html = autoItems.map(item => {
        const checked = approved.includes(item.text);
        return `<label class="hot-check-item" style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:6px 0">
          <input type="checkbox" class="hot-checkbox" value="${esc(item.text)}" ${checked ? 'checked' : ''} onchange="updateHotCheck()">
          <span style="font-size:13px">${esc(item.text)}</span>
          <span style="font-size:11px;color:var(--slate-400)">${item.users}人以此提问</span>
        </label>`;
      }).join('');
      // Manual items section
      if (manualHotItems.length) {
        html += `<div style="border-top:1px solid var(--slate-100);margin:8px 0 4px;padding-top:8px;font-size:11px;color:var(--slate-400)">手动添加</div>`;
        html += manualHotItems.map(t => `<div class="hot-check-item" style="display:flex;align-items:center;gap:8px;padding:6px 0">
          <input type="checkbox" class="hot-checkbox" value="${esc(t)}" checked onchange="updateHotCheck()">
          <span style="font-size:13px">${esc(t)}</span>
          <button class="btn btn-secondary btn-sm" onclick="removeManualHot('${esc(t)}')" style="margin-left:auto;color:var(--rose)">✕</button>
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
  if (manualHotItems.includes(text)) { showToast('已存在', 'info'); return; }
  manualHotItems.push(text);
  input.value = '';
  // Reload word cloud (will use stored items)
  loadHotQuestions();
}

function removeManualHot(text) {
  manualHotItems = manualHotItems.filter(t => t !== text);
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
  const checked = Array.from(document.querySelectorAll('.hot-checkbox:checked')).slice(0, 5).map(cb => cb.value);
  try {
    const res = await fetch(`${API}/api/admin/dashboard/hot-questions/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ questions: checked }),
    });
    if (res.ok) showToast('热门问题已更新', 'success');
  } catch { showToast('保存失败', 'error'); }
}

function tagForType(type) {
  const map = { '产品咨询': 'tag-sky', '使用答疑': 'tag-emerald', '朋友圈帮写': 'tag-amber', '口播文案帮写': 'tag-rose' };
  return map[type] || 'tag-sky';
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
    quill = new Quill('#news-editor', {
      theme: 'snow',
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ['bold', 'italic', 'underline', 'strike'],
          [{ color: [] }, { background: [] }],
          [{ list: 'ordered' }, { list: 'bullet' }],
          ['blockquote', 'code-block'],
          ['link', 'image'],
          ['clean'],
        ]
      },
      placeholder: '输入正文内容...',
    });
    quill.getModule('toolbar').addHandler('image', handleNewsEditorImage);
    quill.root.addEventListener('drop', handleNewsEditorDrop);
    quill.root.addEventListener('paste', handleNewsEditorPaste);
    quillInited = true;
  } catch (e) { console.error('Quill init error:', e); }
}

function insertNewsEditorImage(url) {
  if (!quill || !url) return;
  const range = quill.getSelection(true);
  const index = range ? range.index : quill.getLength();
  quill.insertEmbed(index, 'image', url, 'user');
  quill.setSelection(index + 1);
}

async function uploadNewsEditorImageFile(file) {
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
    insertNewsEditorImage(data.url);
  } catch {
    showToast('图片上传失败', 'error');
  }
}

function handleNewsEditorImage() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.onchange = () => uploadNewsEditorImageFile(input.files && input.files[0]);
  input.click();
}

function handleNewsEditorDrop(event) {
  const file = Array.from(event.dataTransfer?.files || []).find(f => f.type && f.type.startsWith('image/'));
  if (!file) return;
  event.preventDefault();
  uploadNewsEditorImageFile(file);
}

function handleNewsEditorPaste(event) {
  const file = Array.from(event.clipboardData?.files || []).find(f => f.type && f.type.startsWith('image/'));
  if (!file) return;
  event.preventDefault();
  uploadNewsEditorImageFile(file);
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
  if (quill) quill.root.innerHTML = '';
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
      if (quill) quill.root.innerHTML = item.content || '';
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
  if (prodQuill) {
    prodQuill.destroy();
    prodQuill = null;
  }
  prodQuill = new Quill('#prod-editor', {
    theme: 'snow',
    modules: {
      toolbar: [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic', 'underline'],
        [{ list: 'ordered' }, { list: 'bullet' }],
        ['link', 'clean'],
      ]
    },
    placeholder: '输入产品详细介绍...',
  });
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
  ensureQuill().then(() => setTimeout(initProdQuill, 200)).catch(e => console.error('quill load error:', e));
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
      if (prodQuill) prodQuill.root.innerHTML = p.content || '';
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
    content: prodQuill ? prodQuill.root.innerHTML : '',
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

// ===== Init =====
checkAuth();
