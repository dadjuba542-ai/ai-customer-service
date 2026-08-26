const VOICE_PRESS_THRESHOLD_MS = 150;

async function toggleVoiceInput() {
  if (!state.speech.enabled) return showToast('语音识别未开启', 'info');
  if (['connecting', 'transcribing', 'finalizing'].includes(state.speech.phase)) return;
  if (state.isStreaming || state.isTyping) return showToast('正在回答中，稍后再录音', 'info');
  if (state.speech.phase === 'recording') return stopVoiceRecording();
  await startVoiceRecording();
}

function initVoicePress() {
  const btn = document.getElementById('voice-btn');
  if (!btn) return;
  btn.addEventListener('pointerdown', handleVoicePointerDown);
  btn.addEventListener('pointerup', handleVoicePointerUp);
  btn.addEventListener('pointercancel', handleVoicePointerCancel);
  btn.addEventListener('contextmenu', (e) => e.preventDefault());
  btn.addEventListener('click', handleVoiceClick);
}

function clearVoicePressTimer() {
  if (state.speech.pressTimer) clearTimeout(state.speech.pressTimer);
  state.speech.pressTimer = null;
}

function handleVoicePointerDown(e) {
  if (!state.speech.enabled) return;
  if (['connecting', 'transcribing', 'finalizing'].includes(state.speech.phase)) return;
  if (state.isStreaming || state.isTyping) return;
  if (state.speech.phase === 'recording' || state.speech.pressActive) return;
  e.preventDefault();
  state.speech.pressActive = true;
  state.speech.pressStarted = false;
  state.speech.pressTriggered = false;
  state.speech.pressPointerId = e.pointerId;
  try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch (_) {}
  clearVoicePressTimer();
  state.speech.pressTimer = setTimeout(() => {
    state.speech.pressTimer = null;
    if (!state.speech.pressActive) return;
    state.speech.pressStarted = true;
    state.speech.pressTriggered = true;
    startVoiceRecording();
  }, VOICE_PRESS_THRESHOLD_MS);
}

function handleVoicePointerUp(e) {
  if (state.speech.pressPointerId !== null && e.pointerId !== state.speech.pressPointerId) return;
  clearVoicePressTimer();
  const wasActive = state.speech.pressActive;
  state.speech.pressActive = false;
  state.speech.pressPointerId = null;
  state.speech.suppressClick = true;
  updateVoiceButton();
  setTimeout(() => { state.speech.suppressClick = false; }, 0);
  if (!wasActive) return;
  if (state.speech.phase === 'recording') {
    stopVoiceRecording();
  }
}

function handleVoicePointerCancel(e) {
  if (state.speech.pressPointerId !== null && e.pointerId !== state.speech.pressPointerId) return;
  clearVoicePressTimer();
  const shouldCancel = state.speech.pressActive && state.speech.phase !== 'idle';
  state.speech.pressActive = false;
  state.speech.pressStarted = false;
  state.speech.pressTriggered = false;
  state.speech.pressPointerId = null;
  if (shouldCancel) cancelVoiceInput();
}

function handleVoiceClick(e) {
  if (state.speech.suppressClick) {
    e.preventDefault();
    return;
  }
  toggleVoiceInput();
}

async function startVoiceRecording() {
  if (speechBusy()) return;
  createVoiceDraft();
  state.speech.cancelled = false;
  state.speech.fallbackInProgress = false;
  state.speech.pressStarted = true;
  const canRealtime = state.speech.realtimeEnabled && state.speech.mode !== 'batch' &&
    window.TencentRealtimeSpeechController?.isSupported();
  if (canRealtime) {
    await startRealtimeVoiceRecording();
  } else if (state.speech.mode === 'realtime') {
    resetVoiceState();
    return showToast('当前浏览器不支持腾讯云实时语音，请换用新版浏览器', 'error');
  } else {
    await startBatchVoiceRecording();
  }
  if (state.speech.pressTriggered && !state.speech.pressActive && state.speech.phase !== 'idle') {
    await stopVoiceRecording();
  }
}

async function startRealtimeVoiceRecording() {
  state.speech.phase = 'connecting';
  state.speech.isStarting = true;
  updateVoiceButton();
  let controller;
  try {
    const sessionAbortController = new AbortController();
    state.speech.sessionAbortController = sessionAbortController;
    const res = await fetch(`${API_BASE}/api/speech/realtime/session`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ user_id: getUserId() }),
      signal: sessionAbortController.signal,
    });
    state.speech.sessionAbortController = null;
    const session = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(session.error || '无法创建实时语音会话');
    state.speech.maxDurationSeconds = Number(session.max_duration_seconds) || state.speech.maxDurationSeconds;
    controller = new window.TencentRealtimeSpeechController({
      onState: (phase) => {
        if (state.speech.controller !== controller || state.speech.cancelled) return;
        state.speech.phase = phase;
        state.speech.isRecording = phase === 'recording';
        if (phase === 'recording' && !state.speech.startedAt) startSpeechClock();
        updateVoiceButton();
      },
      onVolume: updateVoiceMeter,
      onPartial: updateRealtimePartial,
      onSentenceEnd: commitRealtimeSentence,
      onComplete: finishRealtimeVoiceInput,
      onError: (error) => handleRealtimeVoiceError(error, controller),
    });
    state.speech.controller = controller;
    await controller.start(session);
    state.speech.isStarting = false;
    if (!state.speech.startedAt) startSpeechClock();
    state.speech.stopTimer = setTimeout(() => {
      if (state.speech.phase === 'recording' || state.speech.phase === 'connecting') {
        showToast(`已到 ${state.speech.maxDurationSeconds} 秒，正在整理文字`, 'info');
        stopVoiceRecording();
      }
    }, state.speech.maxDurationSeconds * 1000);
  } catch (error) {
    state.speech.sessionAbortController = null;
    state.speech.isStarting = false;
    if (state.speech.controller === controller) state.speech.controller = null;
    if (error?.name === 'AbortError') return;
    const denied = error && (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError');
    if (denied) {
      resetVoiceState();
      showToast('录音权限被拒绝，请在浏览器设置中允许麦克风', 'error');
      return;
    }
    if (state.speech.mode === 'auto' && state.speech.batchFallbackEnabled) {
      showToast('实时连接失败，已切换为录音转写', 'info');
      await startBatchVoiceRecording(true);
    } else {
      resetVoiceState();
      showToast(error.message || '无法开始实时语音输入', 'error');
    }
  }
}

async function startBatchVoiceRecording(fromRealtime = false) {
  if (!batchSpeechSupported()) {
    resetVoiceState();
    return showToast('当前浏览器不支持语音输入，请使用文字输入', 'error');
  }
  state.speech.phase = 'connecting';
  updateVoiceButton(fromRealtime ? '正在切换录音模式...' : '正在打开麦克风...');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: false,
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const mimeType = pickSpeechMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    state.speech.stream = stream;
    state.speech.mediaRecorder = recorder;
    state.speech.chunks = [];
    state.speech.cancelled = false;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) state.speech.chunks.push(event.data);
    };
    recorder.onstop = () => {
      const chunks = state.speech.chunks.slice();
      const finalType = recorder.mimeType || mimeType || 'audio/webm';
      const cancelled = !!recorder._voiceCancelled;
      cleanupBatchVoiceRecording();
      if (cancelled) return;
      if (chunks.length) transcribeVoiceBlob(new Blob(chunks, { type: finalType }));
      else {
        showToast('没有录到声音，请重试', 'error');
        resetVoiceState();
      }
    };
    recorder.start(250);
    state.speech.phase = 'recording';
    state.speech.isRecording = true;
    startSpeechClock();
    updateVoiceButton('正在录音，松手结束');
    state.speech.stopTimer = setTimeout(() => {
      if (state.speech.phase === 'recording') {
        showToast(`已到 ${state.speech.maxDurationSeconds} 秒，正在转写`, 'info');
        stopVoiceRecording();
      }
    }, state.speech.maxDurationSeconds * 1000);
  } catch (error) {
    cleanupBatchVoiceRecording();
    resetVoiceState();
    const denied = error && (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError');
    showToast(denied ? '录音权限被拒绝，请在浏览器设置中允许麦克风' : '无法开始录音，请重试', 'error');
  }
}

async function stopVoiceRecording() {
  if (state.speech.controller) {
    state.speech.phase = 'finalizing';
    state.speech.isRecording = false;
    stopSpeechClock();
    updateVoiceButton();
    try { await state.speech.controller.stop(); } catch {}
    return;
  }
  const recorder = state.speech.mediaRecorder;
  if (recorder && recorder.state !== 'inactive') {
    state.speech.phase = 'transcribing';
    state.speech.isRecording = false;
    stopSpeechClock();
    updateVoiceButton();
    recorder.stop();
  } else resetVoiceState();
}

function cleanupBatchVoiceRecording() {
  if (state.speech.stopTimer) clearTimeout(state.speech.stopTimer);
  state.speech.stopTimer = null;
  if (state.speech.stream) state.speech.stream.getTracks().forEach((track) => track.stop());
  state.speech.stream = null;
  state.speech.mediaRecorder = null;
  state.speech.isRecording = false;
}

async function cancelVoiceInput() {
  if (!speechBusy()) return;
  state.speech.cancelled = true;
  const draft = state.speech.draft;
  if (state.speech.sessionAbortController) state.speech.sessionAbortController.abort();
  if (state.speech.transcribeAbortController) state.speech.transcribeAbortController.abort();
  if (state.speech.controller) await state.speech.controller.cancel();
  const recorder = state.speech.mediaRecorder;
  if (recorder && recorder.state !== 'inactive') {
    recorder._voiceCancelled = true;
    recorder.stop();
  }
  cleanupBatchVoiceRecording();
  if (draft) restoreVoiceDraft(draft);
  resetVoiceState();
  showToast('已取消语音输入', 'info');
}

async function handleRealtimeVoiceError(error, controller) {
  if (state.speech.cancelled || state.speech.fallbackInProgress || state.speech.controller !== controller) return;
  state.speech.fallbackInProgress = true;
  stopSpeechClock();
  if (state.speech.stopTimer) clearTimeout(state.speech.stopTimer);
  state.speech.stopTimer = null;
  const blob = controller.getWavBlob();
  state.speech.controller = null;
  if (state.speech.mode === 'auto' && state.speech.batchFallbackEnabled && blob.size > 44) {
    showToast('实时识别中断，正在用同一段录音完成转写', 'info');
    await transcribeVoiceBlob(blob, true);
  } else {
    resetVoiceState();
    showToast(error.message || '实时语音识别失败', 'error');
  }
}

function finishRealtimeVoiceInput() {
  if (state.speech.cancelled) return;
  if (state.speech.partialText) commitRealtimeSentence(state.speech.partialText);
  stopSpeechClock();
  resetVoiceState({ preserveInput: true });
  showToast('语音已转成文字，请确认后发送', 'success');
}

async function transcribeVoiceBlob(blob, fromRealtimeFallback = false) {
  if (!blob || blob.size <= 0) {
    showToast('没有录到声音，请重试', 'error');
    resetVoiceState();
    return;
  }
  if (blob.size > 10 * 1024 * 1024) {
    showToast('录音太大，请缩短录音时间', 'error');
    resetVoiceState();
    return;
  }
  state.speech.phase = 'transcribing';
  state.speech.isTranscribing = true;
  updateVoiceButton(fromRealtimeFallback ? '实时中断，正在完成转写...' : '正在转写录音...');
  try {
    const transcribeAbortController = new AbortController();
    state.speech.transcribeAbortController = transcribeAbortController;
    const form = new FormData();
    const ext = blob.type.includes('wav') ? 'wav' : blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : 'webm';
    form.append('audio', blob, `voice.${ext}`);
    form.append('user_id', getUserId());
    const res = await fetch(`${API_BASE}/api/speech/transcribe`, {
      method: 'POST', headers: authHeaders(), body: form, signal: transcribeAbortController.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '识别失败，请重试');
    const text = String(data.text || '').trim();
    if (!text) throw new Error('未识别到文字，请重试');
    applyVoiceResult(text);
    showToast('语音已转成文字，请确认后发送', 'success');
  } catch (error) {
    if (error?.name !== 'AbortError') showToast(error.message || '识别失败，请重试', 'error');
  } finally {
    state.speech.transcribeAbortController = null;
    resetVoiceState({ preserveInput: true });
  }
}

function createVoiceDraft() {
  const input = document.getElementById('message-input');
  if (!input) return null;
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
  const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;
  state.speech.draft = { original: input.value, start, end, before: input.value.slice(0, start), after: input.value.slice(end) };
  state.speech.committedText = '';
  state.speech.partialText = '';
  return state.speech.draft;
}

function renderVoiceDraft() {
  const input = document.getElementById('message-input');
  const draft = state.speech.draft;
  if (!input || !draft) return;
  const spoken = `${state.speech.committedText}${state.speech.partialText}`;
  input.value = `${draft.before}${spoken}${draft.after}`;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.focus();
  const caret = draft.before.length + spoken.length;
  input.setSelectionRange(caret, caret);
}

function updateRealtimePartial(text) {
  if (!state.speech.draft || state.speech.cancelled) return;
  state.speech.partialText = String(text || '');
  renderVoiceDraft();
}

function commitRealtimeSentence(text) {
  if (!state.speech.draft || state.speech.cancelled) return;
  const finalText = String(text || state.speech.partialText || '');
  if (finalText && !state.speech.committedText.endsWith(finalText)) state.speech.committedText += finalText;
  state.speech.partialText = '';
  renderVoiceDraft();
}

function applyVoiceResult(text) {
  if (!state.speech.draft) createVoiceDraft();
  state.speech.committedText = String(text || '');
  state.speech.partialText = '';
  renderVoiceDraft();
}

function restoreVoiceDraft(draft) {
  const input = document.getElementById('message-input');
  if (!input || !draft) return;
  input.value = draft.original;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.focus();
  input.setSelectionRange(draft.start, draft.end);
}

function startSpeechClock() {
  if (!state.speech.startedAt) state.speech.startedAt = Date.now();
  stopSpeechClock(false);
  updateSpeechTimer();
  state.speech.elapsedTimer = setInterval(updateSpeechTimer, 250);
}

function stopSpeechClock(resetStartedAt = false) {
  if (state.speech.elapsedTimer) clearInterval(state.speech.elapsedTimer);
  state.speech.elapsedTimer = null;
  if (resetStartedAt) state.speech.startedAt = 0;
}

function updateSpeechTimer() {
  const timer = document.getElementById('voice-timer');
  if (!timer || !state.speech.startedAt) return;
  const seconds = Math.max(0, Math.floor((Date.now() - state.speech.startedAt) / 1000));
  timer.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function updateVoiceMeter(level) {
  document.getElementById('voice-meter')?.style.setProperty('--voice-level', String(Math.max(0.16, Math.min(1, Number(level) || 0))));
}

function resetVoiceState() {
  if (state.speech.stopTimer) clearTimeout(state.speech.stopTimer);
  state.speech.stopTimer = null;
  stopSpeechClock(true);
  state.speech.phase = 'idle';
  state.speech.isRecording = false;
  state.speech.isTranscribing = false;
  state.speech.isStarting = false;
  state.speech.controller = null;
  state.speech.mediaRecorder = null;
  state.speech.stream = null;
  state.speech.chunks = [];
  state.speech.cancelled = false;
  state.speech.fallbackInProgress = false;
  state.speech.sessionAbortController = null;
  state.speech.transcribeAbortController = null;
  clearVoicePressTimer();
  state.speech.pressActive = false;
  state.speech.pressStarted = false;
  state.speech.pressTriggered = false;
  state.speech.pressPointerId = null;
  state.speech.suppressClick = false;
  state.speech.draft = null;
  state.speech.committedText = '';
  state.speech.partialText = '';
  updateVoiceMeter(0);
  updateVoiceButton('');
}

function createStreamingBotMessage(agentId) {
  state.isStreaming = true;
  const msgId = Date.now();
  state.messages.push({
    id: msgId,
    role: 'bot',
    content: '',
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    agentId,
    isStreaming: true,
    replyToText: lastUserText,
  });
  renderMessages();
  updateChatAgentInfo();
  return msgId;
}

function getMessageBubbleElement(msgId) {
  return document.querySelector(`.msg[data-msg-id="${msgId}"] .msg-bubble`);
}

function updateStreamingMessageDom(msgId, content, isStreaming = true) {
  const bubble = getMessageBubbleElement(msgId);
  if (!bubble) {
    renderMessages();
    return;
  }
  bubble.innerHTML = `${escapeHtml(content)}${isStreaming ? '<span class="cursor-blink"></span>' : ''}`;
  scrollToBottom();
  updateScrollBtn();
}

function appendStreamingBotMessage(msgId, text) {
  if (!text) return;
  const msg = state.messages.find(m => m.id === msgId);
  if (!msg) return;
  msg.content += text;
  updateStreamingMessageDom(msgId, msg.content, true);
}

function finalizeStreamingBotMessage(msgId, extras = {}) {
  const msg = state.messages.find(m => m.id === msgId);
  if (!msg) return;
  msg.isStreaming = false;
  if (extras.historyId) msg.historyId = extras.historyId;
  if (extras.feedback !== undefined) msg.feedback = extras.feedback;
  if (extras.content !== undefined) msg.content = extras.content;
  if (extras.relatedCases !== undefined) msg.relatedCases = extras.relatedCases;
  if (extras.relatedCasesTotal !== undefined) msg.relatedCasesTotal = extras.relatedCasesTotal;
  renderMessages();
}

function addBotMessage(content, options = {}) {
  addMessage({
    id: Date.now(),
    role: 'bot',
    content,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    agentId: options.agentId || state.activeAgentId,
    historyId: options.historyId,
    feedback: options.feedback,
    relatedCases: options.relatedCases || [],
    relatedCasesTotal: options.relatedCasesTotal,
    replyToText: options.replyToText || lastUserText,
  });
}

function parseSSEChunk(chunk) {
  const lines = chunk.split('\n');
  let event = 'message';
  const dataLines = [];
  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!dataLines.length) return null;
  try {
    return {
      event,
      data: JSON.parse(dataLines.join('\n')),
    };
  } catch {
    return null;
  }
}

