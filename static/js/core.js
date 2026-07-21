const API_BASE = '';
const HANDOFF_TRIGGER_AGENT_ID = 'creative';
const HOME_AGENT_IDS = ['aura', 'coder', 'translator', HANDOFF_TRIGGER_AGENT_ID];

const FALLBACK_AGENTS = [
  { id: 'aura', name: '产品资料查询', type: '产品咨询', icon: 'database', color: '#8B5CF6', bg: '#F5F3FF' },
  { id: 'coder', name: '产品使用答疑', type: '使用答疑', icon: 'question', color: '#3B82F6', bg: '#EFF6FF' },
  { id: 'translator', name: '个人IP打造', type: '朋友圈帮写', icon: 'lightning', color: '#10B981', bg: '#ECFDF5' },
  { id: 'creative', name: '疑难问题解答', type: '口播文案帮写', icon: 'lifebuoy', color: '#F97316', bg: '#FFF7ED' },
];

let AGENTS = [];
let lastUserText = '';
let lastUserAgentId = '';
let caseLibraryUrl = '';
let bulletinTimer = null;
const assetLoaders = new Map();
let state = {
  currentView: 'home',
  activeAgentId: 'aura',
  messages: [],
  isTyping: false,
  isStreaming: false,
  token: localStorage.getItem('token'),
  sessionToken: localStorage.getItem('session_token'),
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  profile: JSON.parse(localStorage.getItem('chat_profile') || 'null'),
  teamOptions: [],
  chatAbortController: null,
  handoff: {
    config: null,
    isNutritionMode: false,
    session: null,
    lastMessageId: 0,
    pollTimer: null,
    interrupting: false,
    pendingInitialQuestion: '',
    draftInitialQuestion: '',
  },
  speech: {
    enabled: false,
    mode: 'auto',
    realtimeEnabled: false,
    batchFallbackEnabled: true,
    maxDurationSeconds: 60,
    phase: 'idle',
    isRecording: false,
    isTranscribing: false,
    isStarting: false,
    controller: null,
    mediaRecorder: null,
    stream: null,
    chunks: [],
    stopTimer: null,
    elapsedTimer: null,
    startedAt: 0,
    draft: null,
    committedText: '',
    partialText: '',
    cancelled: false,
    fallbackInProgress: false,
    sessionAbortController: null,
    transcribeAbortController: null,
  },
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
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(id || '')) {
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
  loadHandoffConfig();
  loadAgents();
  loadWaitingContent();
  loadExampleQuestions();
  loadNews();
  loadCaseLibraryConfig();
  loadSpeechConfig();
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
  await ensureIdentity();
  if (state.sessionToken || state.token) await restoreHandoffSession();
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

async function loadCaseLibraryConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/case-library-config`);
    if (!res.ok) return;
    const data = await res.json();
    caseLibraryUrl = (data.case_library_url || '').trim();
  } catch {
    caseLibraryUrl = '';
  }
}

async function loadSpeechConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/speech/config`);
    if (!res.ok) return;
    const data = await res.json();
    state.speech.enabled = !!data.enabled;
    state.speech.mode = data.mode || 'auto';
    state.speech.realtimeEnabled = !!data.realtime_enabled;
    state.speech.batchFallbackEnabled = data.batch_fallback_enabled !== false;
    state.speech.maxDurationSeconds = Number(data.max_duration_seconds) || 60;
  } catch {
    state.speech.enabled = false;
  }
  updateVoiceButton();
}



function enterApp() {
  document.getElementById('app').classList.add('active');
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

async function ensureGuestSession() {
  if (!state.profile?.team || !state.profile?.name) return false;
  const res = await fetch(`${API_BASE}/api/auth/session`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      team_name: state.profile.team,
      member_name: state.profile.name,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.token) throw new Error(data.error || '身份会话创建失败');
  state.sessionToken = data.token;
  localStorage.setItem('session_token', data.token);
  return true;
}

async function ensureIdentity() {
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
      try {
        await ensureGuestSession();
      } catch (error) {
        if (gate) gate.classList.add('active');
        showToast(error.message || '身份会话创建失败，请重试', 'error');
        return;
      }
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

async function submitIdentity() {
  const team = (document.getElementById('team-select')?.value || '').trim();
  const name = (document.getElementById('member-name-input')?.value || '').trim();
  if (!team) { showToast('请选择团队', 'error'); return; }
  if (!state.teamOptions.includes(team)) { showToast('请选择管理员配置的团队', 'error'); return; }
  if (!name) { showToast('请输入姓名', 'error'); return; }
  const button = document.querySelector('#identity-gate .btn-primary');
  if (button) button.disabled = true;
  try {
    state.profile = { team, name };
    state.sessionToken = null;
    localStorage.removeItem('session_token');
    await ensureGuestSession();
    localStorage.setItem('chat_profile', JSON.stringify(state.profile));
    document.getElementById('identity-gate')?.classList.remove('active');
    enterApp();
  } catch (error) {
    state.profile = null;
    showToast(error.message || '身份会话创建失败，请重试', 'error');
  } finally {
    if (button) button.disabled = false;
  }
}
