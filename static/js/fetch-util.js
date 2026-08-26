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

function updateVoiceButton(message = '') {
  const btn = document.getElementById('voice-btn');
  const status = document.getElementById('voice-status');
  if (!btn || !status) return;
  const phase = state.speech.phase || 'idle';
  const busy = phase !== 'idle';
  btn.style.display = state.speech.enabled ? 'flex' : 'none';
  btn.classList.toggle('recording', phase === 'recording');
  btn.classList.toggle('transcribing', phase === 'transcribing' || phase === 'finalizing');
  btn.classList.toggle('connecting', phase === 'connecting');
  const disabledPhase = ['connecting', 'transcribing', 'finalizing'].includes(phase);
  btn.disabled = (disabledPhase && !state.speech.pressActive) || state.isStreaming || state.isTyping;
  btn.setAttribute('aria-pressed', phase === 'recording' ? 'true' : 'false');
  btn.setAttribute('aria-label', phase === 'recording' ? '松手结束录音' : busy ? '语音处理中' : '按住说话，松手结束');
  btn.innerHTML = ['connecting', 'transcribing', 'finalizing'].includes(phase)
    ? '<i class="ph ph-spinner-gap"></i>'
    : phase === 'recording' ? '<i class="ph ph-stop"></i>' : '<i class="ph ph-microphone"></i>';
  btn.title = phase === 'recording' ? '松手结束录音' : busy ? '语音处理中' : '按住说话，松手结束';
  const defaults = {
    connecting: '正在连接腾讯云...',
    recording: state.speech.realtimeEnabled && state.speech.mode !== 'batch' ? '正在录音，松手结束' : '正在录音，松手结束',
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

