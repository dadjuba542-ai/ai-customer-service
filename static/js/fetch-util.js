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
  const payload = {
    message: text,
    query_type: agent.type,
    agent_id: agent.id,
    user_id: getUserId(),
    team_name: state.profile?.team || '',
    member_name: state.profile?.name || '',
  };
  if (state.handoff.isNutritionMode) payload.channel = 'nutrition_consultation';
  return payload;
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const token = state.sessionToken || state.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

function startChatRequest() {
  const sendBtn = document.getElementById('send-btn');
  sendBtn.disabled = true;
  state.isTyping = true;
  state.isStreaming = false;
  showWaitingPanel();
  updateChatAgentInfo();
  updateVoiceButton();
  return sendBtn;
}

function finishChatRequest(sendBtn) {
  hideWaitingPanel();
  hideTyping();
  state.isTyping = false;
  state.isStreaming = false;
  if (sendBtn) sendBtn.disabled = false;
  updateChatAgentInfo();
  updateVoiceButton();
}

// 内联 SVG 图标：不依赖图标字体，避免字体缺失/字形叠加导致的重叠
const VOICE_ICONS = {
  mic: '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9.2" y="2.6" width="5.6" height="10.8" rx="2.8"/><path d="M5.6 11.2v.9a6.4 6.4 0 0 0 12.8 0v-.9"/><path d="M12 18.6v2.1"/><path d="M8.7 20.7h6.6"/></svg>',
  stop: '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2.4" fill="currentColor"/></svg>',
  spinner: '<svg class="voice-spinner" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" aria-hidden="true"><path d="M12 3.2a8.8 8.8 0 1 0 8.8 8.8"/></svg>',
};

function updateVoiceButton(message = '') {
  const btn = document.getElementById('voice-btn');
  const status = document.getElementById('voice-status');
  if (!btn || !status) return;
  const phase = state.speech.phase || 'idle';
  const busy = phase !== 'idle';
  const waiting = ['connecting', 'transcribing', 'finalizing'].includes(phase);
  btn.style.display = state.speech.enabled ? 'flex' : 'none';
  btn.classList.toggle('recording', phase === 'recording');
  btn.classList.toggle('transcribing', phase === 'transcribing' || phase === 'finalizing');
  btn.classList.toggle('connecting', phase === 'connecting');
  btn.disabled = waiting || state.isStreaming || state.isTyping;
  btn.setAttribute('aria-pressed', phase === 'recording' ? 'true' : 'false');
  const labels = {
    recording: '点击结束录音并转文字',
    connecting: '正在连接语音服务',
    transcribing: '正在转写录音',
    finalizing: '正在整理最后一句',
  };
  const label = labels[phase] || '点击开始录音';
  btn.setAttribute('aria-label', label);
  btn.title = label;
  const icon = waiting ? VOICE_ICONS.spinner : phase === 'recording' ? VOICE_ICONS.stop : VOICE_ICONS.mic;
  if (btn.dataset.voiceIcon !== (waiting ? 'spinner' : phase === 'recording' ? 'stop' : 'mic')) {
    btn.innerHTML = icon;
    btn.dataset.voiceIcon = waiting ? 'spinner' : phase === 'recording' ? 'stop' : 'mic';
  }
  const defaults = {
    connecting: '正在连接腾讯云...',
    recording: '正在录音，点击按钮结束',
    finalizing: '正在整理最后一句...',
    transcribing: '正在转写录音...',
  };
  const text = message || defaults[phase] || '';
  const statusText = document.getElementById('voice-status-text');
  if (statusText) statusText.textContent = text;
  status.classList.toggle('finalizing', phase === 'finalizing');
  status.classList.toggle('transcribing', phase === 'transcribing');
  status.style.display = text ? 'flex' : 'none';
  const timer = document.getElementById('voice-timer');
  if (timer) timer.style.display = phase === 'recording' ? '' : 'none';
  const cancel = document.getElementById('voice-cancel-btn');
  if (cancel) cancel.style.display = busy ? '' : 'none';
  const sendBtn = document.getElementById('send-btn');
  if (sendBtn) sendBtn.disabled = busy || state.isStreaming || state.isTyping;
}

function speechBusy() {
  return state.speech.phase !== 'idle';
}

function batchSpeechSupported() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
}

function pickSpeechMimeType() {
  const candidates = ['audio/mp4', 'audio/ogg;codecs=opus', 'audio/webm;codecs=opus', 'audio/webm'];
  if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
  return candidates.find(type => MediaRecorder.isTypeSupported(type)) || '';
}

