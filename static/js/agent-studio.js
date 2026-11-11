const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let agents = [];
let documents = [];
let editingId = null;
let searchTimer;
let toastTimer;
let editingAgentId = null;
let documentLoadId = 0;
let documentFindPositions = [];
let documentFindIndex = -1;
const detailAgentId = document.body.dataset.agentId || '';

function highlightMatch(value, query) {
  const source = String(value || '');
  const needle = String(query || '').trim();
  if (!needle) return escapeHtml(source);
  const index = source.toLocaleLowerCase().indexOf(needle.toLocaleLowerCase());
  if (index < 0) return escapeHtml(source);
  return `${escapeHtml(source.slice(0, index))}<mark>${escapeHtml(source.slice(index, index + needle.length))}</mark>${escapeHtml(source.slice(index + needle.length))}`;
}

function toast(message, error = false) {
  const el = $('toast');
  el.textContent = message;
  el.classList.toggle('error', error);
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3500);
}

async function api(path, options = {}) {
  const headers = {Authorization: `Bearer ${localStorage.getItem('token') || ''}`, ...(options.headers || {})};
  const response = await fetch(path, {...options, headers});
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    $('studio-view').hidden = true;
    $('login-view').hidden = false;
  }
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

async function checkAuth() {
  if (!localStorage.getItem('token')) { $('login-view').hidden = false; return; }
  try {
    const user = await api('/api/user/profile');
    if (!user.is_admin) throw new Error('需要管理员账号');
    $('account-name').textContent = user.username || '管理员';
    $('login-view').hidden = true;
    $('studio-view').hidden = false;
    await loadAgents();
    if (detailAgentId) {
      showAgentDetail();
    } else {
      const initialPanel = ['knowledge', 'agents', 'api'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'prompts';
      showPanel(initialPanel);
      if (initialPanel === 'knowledge') await loadDocuments();
      if (initialPanel === 'api') await loadApiSettings();
    }
  } catch (error) { $('login-view').hidden = false; $('studio-view').hidden = true; $('login-error').textContent = error.message; }
}

async function loadAgents() {
  const data = await api('/api/admin/agents');
  agents = data.agents || [];
  $('agent-list').innerHTML = agents.length ? agents.map((agent) => `
    <a class="agent-card agent-link" href="/agent-studio/agents/${encodeURIComponent(agent.agent_id)}">
      <span class="agent-badge">✦</span><h3>${escapeHtml(agent.name)}</h3>
      <small>${escapeHtml(agent.type || agent.agent_id)}</small>
      <span class="agent-link-footer">${agent.system_prompt ? '已配置提示词' : '尚未配置提示词'} · 思考：${({none:'关闭',low:'低',high:'高',max:'最高'})[agent.reasoning_effort] || '关闭'}<b>进入编辑 →</b></span>
    </a>`).join('') : '<p class="empty">暂无子智能体。请先在管理后台添加。</p>';
  $('document-agents').innerHTML = agents.map((a) => `<label><input type="checkbox" value="${escapeHtml(a.agent_id)}">${escapeHtml(a.name)}</label>`).join('');
  $('manage-agent-list').innerHTML = agents.length ? agents.map((a) => `<button class="manage-agent-row" type="button" data-id="${escapeHtml(a.agent_id)}"><strong>${escapeHtml(a.name)}</strong><span>${escapeHtml(a.agent_id)} · 编辑 →</span></button>`).join('') : '<p class="empty">暂无智能体</p>';
}

function showAgentDetail() {
  const agent = agents.find((item) => item.agent_id === detailAgentId);
  $('prompts-panel').hidden = true;
  $('knowledge-panel').hidden = true;
  $('agents-panel').hidden = true;
  $('api-panel').hidden = true;
  $('agent-detail-panel').hidden = false;
  $('page-title').textContent = agent ? agent.name : '子智能体不存在';
  $('detail-agent-name').textContent = agent ? `${agent.name} · 提示词` : '找不到这个子智能体';
  $('prompt-form').hidden = !agent;
  if (agent) {
    $('detail-prompt').value = agent.system_prompt || '';
    $('detail-effort').value = agent.reasoning_effort || 'none';
    updatePromptCount();
  }
}

function showPanel(panel) {
  if ($('document-dialog').open) $('document-dialog').close();
  document.querySelectorAll('.nav-button').forEach((item) => item.classList.toggle('active', item.dataset.panel === panel));
  for (const name of ['prompts', 'knowledge', 'agents', 'api']) $(`${name}-panel`).hidden = name !== panel;
  $('agent-detail-panel').hidden = true;
  $('page-title').textContent = ({prompts:'子智能体设置', knowledge:'文字知识库', agents:'智能体管理', api:'API 设置'})[panel];
  history.replaceState(null, '', panel === 'prompts' ? '/agent-studio' : `/agent-studio#${panel}`);
}

function updatePromptCount() {
  $('prompt-count').textContent = `${$('detail-prompt').value.length} / 6000 字`;
}

async function savePrompt(event) {
  event.preventDefault();
  const button = $('save-prompt');
  const prompt = $('detail-prompt').value;
  button.disabled = true;
  try {
    await api(`/api/admin/agents/${encodeURIComponent(detailAgentId)}/ai-config`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({system_prompt: prompt, reasoning_effort: $('detail-effort').value})
    });
    toast('智能体设置已保存');
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function loadDocuments() {
  const loadId = ++documentLoadId;
  const params = new URLSearchParams();
  const query = $('search-input').value.trim();
  if (query) params.set('q', query);
  const data = await api(`/api/admin/knowledge?${params}`);
  if (loadId !== documentLoadId) return;
  documents = data.documents || [];
  $('document-count').textContent = query ? `找到 ${documents.length} 份资料` : `共 ${documents.length} 份资料`;
  $('document-list').innerHTML = documents.length ? documents.map((d) => `
    <article class="knowledge-item" data-id="${d.id}">
      <button class="knowledge-item-main" type="button" data-action="edit" aria-label="编辑资料：${escapeHtml(d.title)}">
        <span class="knowledge-file-icon" aria-hidden="true">▤</span>
        <span class="knowledge-item-copy">
          <strong>${highlightMatch(d.title, query)}</strong>
          <span class="knowledge-excerpt">${highlightMatch(`${d.excerpt_prefix ? '…' : ''}${(d.excerpt || '').replace(/\s+/g, ' ').trim()}`, query) || '暂无摘要'}</span>
          <span class="knowledge-meta">${escapeHtml((d.agent_ids || []).map((id) => agents.find((a) => a.agent_id === id)?.name || id).join('、') || '未分配智能体')}<span aria-hidden="true"> · </span>更新于 ${escapeHtml(formatDocumentDate(d.updated_at || d.created_at))}</span>
        </span>
      </button>
      <div class="knowledge-item-side">
        <span class="knowledge-status ${d.enabled ? 'is-enabled' : 'is-disabled'}">${d.enabled ? '已启用' : '已停用'}</span>
        <div class="knowledge-item-actions"><button type="button" data-action="toggle" aria-label="${d.enabled ? '停用' : '启用'}资料：${escapeHtml(d.title)}">${d.enabled ? '停用' : '启用'}</button><button type="button" class="danger" data-action="delete" aria-label="删除资料：${escapeHtml(d.title)}">删除</button></div>
      </div>
    </article>`).join('') : `<div class="knowledge-empty"><span class="knowledge-empty-icon" aria-hidden="true">▤</span><h3>${query ? '没有找到匹配的资料' : '还没有资料'}</h3><p>${query ? '试试更短的关键词，或清空搜索框。' : '新增文字资料或上传文件，智能体就能开始检索。'}</p>${query ? '' : '<button class="primary" type="button" data-action="new">＋ 新增第一份资料</button>'}</div>`;
}

function formatDocumentDate(value) {
  const raw = String(value || '');
  if (!raw) return '未知时间';
  const iso = raw.replace(' ', 'T');
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? raw.slice(0, 16) : date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  });
}

function resetEditor() {
  editingId = null;
  documentFindPositions = [];
  documentFindIndex = -1;
  $('document-form').reset();
  $('document-enabled').checked = true;
  $('editor-title').textContent = '新增资料';
  $('document-find').hidden = true;
  $('document-find-count').textContent = '';
  $('editor-note').textContent = '选择文件后将使用文件内容；原文件不留在服务器。DOCX 最多 5 MB，TXT/MD 最多 600 KB。';
  $('document-error').hidden = true;
  $('document-error').textContent = '';
}

function openDocumentEditor() {
  $('document-dialog').showModal();
  document.body.classList.add('document-editor-open');
  $('document-title').focus();
}

function showDocumentError(message) {
  $('document-error').textContent = message;
  $('document-error').hidden = false;
}

function updateDocumentFind() {
  const content = $('document-content').value.toLocaleLowerCase();
  const term = $('document-find-input').value.trim().toLocaleLowerCase();
  documentFindPositions = [];
  documentFindIndex = -1;
  if (term) {
    let offset = 0;
    while (documentFindPositions.length < 2000) {
      const position = content.indexOf(term, offset);
      if (position < 0) break;
      documentFindPositions.push(position);
      offset = position + term.length;
    }
  }
  $('document-find-count').textContent = !term ? '输入关键词' : documentFindPositions.length === 2000 ? '至少 2000 处' : `${documentFindPositions.length} 处`;
  $('document-find-prev').disabled = !documentFindPositions.length;
  $('document-find-next').disabled = !documentFindPositions.length;
}

function scrollDocumentToMatch(content, start) {
  const style = getComputedStyle(content);
  const mirror = document.createElement('div');
  Object.assign(mirror.style, {
    position: 'fixed', top: '0', left: '-10000px', visibility: 'hidden', pointerEvents: 'none',
    boxSizing: 'border-box', width: `${content.clientWidth}px`, padding: style.padding,
    fontFamily: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight,
    lineHeight: style.lineHeight, letterSpacing: style.letterSpacing,
    whiteSpace: 'pre-wrap', overflowWrap: 'break-word', wordBreak: style.wordBreak,
  });
  mirror.textContent = content.value.slice(0, start);
  const marker = document.createElement('span');
  marker.textContent = '\u200b';
  mirror.appendChild(marker);
  document.body.appendChild(mirror);
  const top = marker.getBoundingClientRect().top - mirror.getBoundingClientRect().top;
  mirror.remove();
  content.scrollTop = Math.max(0, top - content.clientHeight / 3);
}

function jumpToDocumentMatch(direction) {
  if (!documentFindPositions.length) return;
  documentFindIndex = (documentFindIndex + direction + documentFindPositions.length) % documentFindPositions.length;
  const content = $('document-content');
  const start = documentFindPositions[documentFindIndex];
  content.focus();
  content.setSelectionRange(start, start + $('document-find-input').value.trim().length);
  scrollDocumentToMatch(content, start);
  $('document-find-count').textContent = `${documentFindIndex + 1} / ${documentFindPositions.length}${documentFindPositions.length === 2000 ? '+' : ''} 处`;
}

async function editDocument(id) {
  try {
    const {document: d} = await api(`/api/admin/knowledge/${id}`);
    resetEditor();
    editingId = id;
    $('editor-title').textContent = '编辑资料';
    $('document-title').value = d.title;
    $('document-content').value = d.content;
    $('document-enabled').checked = !!d.enabled;
    $('document-agents').querySelectorAll('input').forEach((input) => { input.checked = d.agent_ids.includes(input.value); });
    $('editor-note').textContent = '可直接修改正文，也可选择新文件替换。原文件不留在服务器。';
    $('document-find').hidden = false;
    $('document-find-input').value = $('search-input').value.trim();
    updateDocumentFind();
    openDocumentEditor();
    if (documentFindPositions.length) jumpToDocumentMatch(1);
  } catch (error) { toast(error.message, true); }
}

async function saveDocument(event) {
  event.preventDefault();
  const title = $('document-title').value.trim();
  const content = $('document-content').value.trim();
  const file = $('document-file').files[0];
  const agentIds = [...$('document-agents').querySelectorAll('input:checked')].map((input) => input.value);
  $('document-error').hidden = true;
  if (!title || !agentIds.length || (!content && !file)) { showDocumentError('请填写标题、正文或选择文件，并至少勾选一个智能体。'); return; }
  const button = $('save-document'); button.disabled = true;
  try {
    const body = file ? new FormData() : JSON.stringify({title, content, agent_ids: agentIds, enabled: $('document-enabled').checked});
    if (file) {
      body.append('file', file); body.append('title', title); body.append('agent_ids', JSON.stringify(agentIds));
      body.append('enabled', String($('document-enabled').checked));
    }
    await api(`/api/admin/knowledge${editingId ? `/${editingId}` : ''}`, {
      method: editingId ? 'PUT' : 'POST', headers: file ? {} : {'Content-Type': 'application/json'}, body
    });
    $('document-dialog').close();
    await loadDocuments(); toast('资料已保存');
  } catch (error) { showDocumentError(error.message); toast(error.message, true); }
  finally { button.disabled = false; }
}

async function documentAction(button) {
  if (button.dataset.action === 'new') { resetEditor(); openDocumentEditor(); return; }
  const id = Number(button.closest('[data-id]').dataset.id);
  const action = button.dataset.action;
  if (action === 'edit') return editDocument(id);
  if (action === 'delete' && !confirm('确定删除这份资料？')) return;
  button.disabled = true;
  try {
    if (action === 'delete') await api(`/api/admin/knowledge/${id}`, {method: 'DELETE'});
    else {
      const document = documents.find((d) => d.id === id);
      await api(`/api/admin/knowledge/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: !document.enabled})});
    }
    if (editingId === id && action === 'delete') resetEditor();
    await loadDocuments(); toast(action === 'delete' ? '资料已删除' : '状态已更新');
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

function resetAgentEditor() {
  editingAgentId = null;
  $('agent-form').reset();
  $('agent-id').disabled = false;
  $('agent-color').value = '#4F46E5';
  $('agent-avatar-url').value = '';
  $('agent-avatar-preview').hidden = true;
  $('agent-editor-title').textContent = '新建智能体';
  $('delete-agent').hidden = true;
}

function editAgent(id) {
  const agent = agents.find((item) => item.agent_id === id);
  if (!agent) return;
  editingAgentId = id;
  $('agent-editor-title').textContent = `编辑 · ${agent.name}`;
  $('agent-id').value = id;
  $('agent-id').disabled = true;
  for (const [field, value] of Object.entries({
    'agent-name': agent.name, 'agent-description': agent.description,
    'agent-chat-desc': agent.chat_desc, 'agent-quick-prompt': agent.prompt,
    'agent-color': agent.color || '#4F46E5', 'agent-icon': agent.icon,
    'agent-bot-id': agent.bot_id, 'agent-avatar-url': agent.avatar_url,
  })) $(field).value = value || '';
  $('agent-avatar-file').value = '';
  $('agent-avatar-preview').hidden = !agent.avatar_url;
  if (agent.avatar_url) $('agent-avatar-preview').src = agent.avatar_url;
  $('delete-agent').hidden = false;
  $('agent-form').scrollIntoView({behavior:'smooth', block:'start'});
}

async function saveAgent(event) {
  event.preventDefault();
  const button = $('save-agent'); button.disabled = true;
  try {
    let avatarUrl = $('agent-avatar-url').value;
    const file = $('agent-avatar-file').files[0];
    if (file) {
      const body = new FormData(); body.append('file', file);
      avatarUrl = (await api('/api/admin/upload', {method:'POST', body})).url;
    }
    const id = editingAgentId || $('agent-id').value.trim();
    const data = {
      name: $('agent-name').value.trim(), type: 'custom',
      description: $('agent-description').value, chat_desc: $('agent-chat-desc').value,
      prompt: $('agent-quick-prompt').value, color: $('agent-color').value,
      icon: $('agent-icon').value.trim() || 'robot', bot_id: $('agent-bot-id').value.trim(),
      avatar_url: avatarUrl,
    };
    if (!editingAgentId) data.agent_id = id;
    await api(editingAgentId ? `/api/admin/agents/${encodeURIComponent(id)}` : '/api/admin/agents', {
      method: editingAgentId ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data)
    });
    await loadAgents(); editAgent(id); toast('智能体已保存');
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function deleteAgent() {
  if (!editingAgentId || !confirm('确定删除这个智能体？')) return;
  try {
    await api(`/api/admin/agents/${encodeURIComponent(editingAgentId)}`, {method:'DELETE'});
    resetAgentEditor(); await loadAgents(); toast('智能体已删除');
  } catch (error) { toast(error.message, true); }
}

async function loadApiSettings() {
  const [provider, coze, rewrite] = await Promise.all([
    api('/api/admin/settings/ai-provider'),
    api('/api/admin/settings/coze-api-key'),
    api('/api/admin/settings/coze-rewrite'),
  ]);
  $('provider-select').value = provider.provider || 'coze';
  $('deepseek-key-status').textContent = provider.deepseek_key_configured ? `已配置：${provider.deepseek_key_masked}` : '尚未配置';
  $('coze-key-status').textContent = coze.configured ? `已配置：${coze.masked}` : '尚未配置';
  $('rewrite-bot-id').value = rewrite.bot_id || '';
  $('rewrite-hint').textContent = rewrite.supported ? 'Coze V3 空召回时可使用专用改写智能体。' : '当前不是 Coze V3，此设置暂不生效。';
}

async function submitJson(event, path, body, success) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    await api(path, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    toast(success); await loadApiSettings(); return true;
  } catch (error) { toast(error.message, true); return false; }
  finally { button.disabled = false; }
}

document.querySelectorAll('.nav-button').forEach((button) => button.addEventListener('click', () => {
  if (detailAgentId) { location.href = button.dataset.panel === 'prompts' ? '/agent-studio' : `/agent-studio#${button.dataset.panel}`; return; }
  showPanel(button.dataset.panel);
  if (button.dataset.panel === 'knowledge') loadDocuments().catch((error) => toast(error.message, true));
  if (button.dataset.panel === 'api') loadApiSettings().catch((error) => toast(error.message, true));
}));
$('prompt-form').addEventListener('submit', savePrompt);
$('detail-prompt').addEventListener('input', updatePromptCount);
$('manage-agent-list').addEventListener('click', (event) => { const row = event.target.closest('[data-id]'); if (row) editAgent(row.dataset.id); });
$('new-agent').addEventListener('click', () => { resetAgentEditor(); $('agent-form').scrollIntoView({behavior:'smooth'}); });
$('cancel-agent-edit').addEventListener('click', resetAgentEditor);
$('agent-form').addEventListener('submit', saveAgent);
$('delete-agent').addEventListener('click', deleteAgent);
$('provider-form').addEventListener('submit', (event) => submitJson(event, '/api/admin/settings/ai-provider', {provider:$('provider-select').value}, '服务设置已保存'));
$('deepseek-key-form').addEventListener('submit', async (event) => { if (await submitJson(event, '/api/admin/settings/deepseek-api-key', {api_key:$('deepseek-key').value.trim()}, 'DeepSeek 密钥已保存')) $('deepseek-key').value = ''; });
$('coze-key-form').addEventListener('submit', async (event) => { if (await submitJson(event, '/api/admin/settings/coze-api-key', {api_key:$('coze-key').value.trim()}, 'Coze 密钥已保存')) $('coze-key').value = ''; });
$('rewrite-form').addEventListener('submit', (event) => submitJson(event, '/api/admin/settings/coze-rewrite', {bot_id:$('rewrite-bot-id').value.trim()}, '重查设置已保存'));
$('document-list').addEventListener('click', (event) => { const button = event.target.closest('[data-action]'); if (button) documentAction(button); });
$('search-input').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadDocuments().catch((error) => toast(error.message, true)), 300); });
$('new-document').addEventListener('click', () => { resetEditor(); openDocumentEditor(); });
$('cancel-edit').addEventListener('click', () => $('document-dialog').close());
$('dismiss-document').addEventListener('click', () => $('document-dialog').close());
$('document-dialog').addEventListener('close', () => { document.body.classList.remove('document-editor-open'); resetEditor(); });
$('document-dialog').addEventListener('click', (event) => { if (event.target === $('document-dialog')) $('document-dialog').close(); });
$('document-file').addEventListener('change', () => { const file = $('document-file').files[0]; if (file && !$('document-title').value.trim()) $('document-title').value = file.name.replace(/\.[^.]+$/, ''); });
$('document-find-input').addEventListener('input', updateDocumentFind);
$('document-find-input').addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); jumpToDocumentMatch(event.shiftKey ? -1 : 1); } });
$('document-find-prev').addEventListener('click', () => jumpToDocumentMatch(-1));
$('document-find-next').addEventListener('click', () => jumpToDocumentMatch(1));
$('document-content').addEventListener('input', () => { if (!$('document-find').hidden) updateDocumentFind(); });
$('document-form').addEventListener('submit', saveDocument);
$('logout-button').addEventListener('click', () => { if ($('document-dialog').open) $('document-dialog').close(); localStorage.removeItem('token'); localStorage.removeItem('user'); $('studio-view').hidden = true; $('login-view').hidden = false; });
$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const response = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username: $('login-username').value.trim(), password: $('login-password').value})});
    const data = await response.json();
    if (!response.ok || !data.is_admin) throw new Error(data.error || '需要管理员账号');
    localStorage.setItem('token', data.token);
    $('login-error').textContent = '';
    await checkAuth();
  } catch (error) { $('login-error').textContent = error.message; }
});
checkAuth();
