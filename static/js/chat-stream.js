async function streamChatRequest(payload, agentId) {
  const controller = new AbortController();
  state.chatAbortController = controller;
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    signal: controller.signal,
  });

  if (res.status === 202) {
    const queued = await res.json().catch(() => ({}));
    if (queued.job_id) {
      return {
        queued: true,
        jobId: queued.job_id,
        position: Number(queued.position || 1),
        retryAfter: Number(queued.retry_after || 2),
        agentId,
      };
    }
  }

  if (!res.ok || !res.body) {
    const errorPayload = await res.json().catch(() => ({}));
    const error = new Error(errorPayload.error || '流式连接失败');
    error.errorCode = errorPayload.error_code || '';
    error.retryAfter = Number(errorPayload.retry_after || res.headers?.get?.('Retry-After') || 0);
    error.canFallback = !['chat_capacity', 'chat_queue_full', 'chat_queue_unavailable', 'chat_pending'].includes(error.errorCode);
    throw error;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let botMsgId = null;
  let sawOutput = false;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    while (buffer.includes('\n\n')) {
      const boundary = buffer.indexOf('\n\n');
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSSEChunk(chunk);
      if (!parsed) continue;

      if (parsed.event === 'status') {
        continue;
      }

      if (parsed.event === 'delta') {
        if (!botMsgId) {
          hideWaitingPanel();
          botMsgId = createStreamingBotMessage(agentId);
        }
        sawOutput = true;
        appendStreamingBotMessage(botMsgId, parsed.data?.text || '');
        continue;
      }

      if (parsed.event === 'done') {
        hideWaitingPanel();
        // The answer is complete at this point. Clear the transient waiting
        // state before rendering/follow-up work so a chat re-render (or a
        // quick view switch) cannot recreate the waiting panel.
        state.isTyping = false;
        const finalText = parsed.data?.full_text || '';
        if (!botMsgId) {
          botMsgId = createStreamingBotMessage(agentId);
        }
        if (!sawOutput && finalText) {
          appendStreamingBotMessage(botMsgId, finalText);
        }
        finalizeStreamingBotMessage(botMsgId, {
          historyId: parsed.data?.history_id,
          content: finalText || (state.messages.find(m => m.id === botMsgId)?.content || ''),
          relatedCases: parsed.data?.related_cases || [],
          relatedCasesTotal: parsed.data?.related_cases_total,
        });
        state.isStreaming = false;
        updateChatAgentInfo();
        return parsed.data;
      }

      if (parsed.event === 'error') {
        const error = new Error(parsed.data?.message || '流式回复失败');
        if (botMsgId) {
          const msg = state.messages.find(m => m.id === botMsgId);
          const partial = msg?.content || '';
          const nextContent = partial
            ? `${partial}\n\n[本次回答未完成：${error.message}]`
            : error.message;
          finalizeStreamingBotMessage(botMsgId, { content: nextContent });
          error.renderedInMessage = true;
        } else {
          error.canFallback = true;
        }
        throw error;
      }
    }
  }

  if (!sawOutput) {
    const error = new Error('流式回复中断，请稍后重试');
    error.canFallback = true;
    throw error;
  }

  return null;
}

function sleepWithSignal(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('The operation was aborted.', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('The operation was aborted.', 'AbortError'));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

async function waitForChatJob(jobId, agentId, initialPosition = 1) {
  const controller = new AbortController();
  state.chatAbortController = controller;
  state.chatJobId = jobId;
  localStorage.setItem('chat_pending_job', JSON.stringify({ jobId, agentId }));
  setWaitingQueueStatus(`当前排队中，前面还有 ${Math.max(0, initialPosition - 1)} 人`);

  try {
    while (true) {
      const res = await fetch(`${API_BASE}/api/chat/jobs/${encodeURIComponent(jobId)}`, {
        headers: authHeaders(),
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const error = new Error(data.error || '排队状态查询失败');
        error.errorCode = data.error_code || '';
        error.canFallback = false;
        throw error;
      }

      if (data.status === 'queued') {
        const position = Number(data.position || 1);
        setWaitingQueueStatus(`当前排队中，前面还有 ${Math.max(0, position - 1)} 人`);
      } else if (data.status === 'running') {
        setWaitingQueueStatus('已轮到您，正在生成完整回答', false);
      } else if (data.status === 'completed') {
        localStorage.removeItem('chat_pending_job');
        state.chatJobId = null;
        hideWaitingPanel();
        if (data.history_id && state.messages.some(message => message.historyId === data.history_id)) {
          return data;
        }
        addBotMessage(data.bot_response || '抱歉，我现在无法回答您的问题。', {
          agentId,
          historyId: data.history_id,
          relatedCases: data.related_cases || [],
          relatedCasesTotal: data.related_cases_total,
        });
        return data;
      } else if (['failed', 'expired', 'cancelled'].includes(data.status)) {
        localStorage.removeItem('chat_pending_job');
        state.chatJobId = null;
        const error = new Error(data.error || '排队任务未能完成');
        error.errorCode = data.error_code || `chat_${data.status}`;
        error.canFallback = false;
        throw error;
      }

      await sleepWithSignal(Math.max(1000, Number(data.retry_after || 2) * 1000), controller.signal);
    }
  } catch (error) {
    if (error?.name === 'AbortError' && state.chatQueueCanceling) return null;
    throw error;
  } finally {
    if (state.chatJobId === jobId && !state.chatQueueCanceling) {
      state.chatJobId = null;
    }
  }
}

async function resumeQueuedChat() {
  let pending = null;
  try {
    pending = JSON.parse(localStorage.getItem('chat_pending_job') || 'null');
  } catch {}
  if (!pending?.jobId) return null;
  if (state.chatJobId === pending.jobId) return null;

  const sendBtn = document.getElementById('send-btn');
  state.isTyping = true;
  if (sendBtn) sendBtn.disabled = true;
  showWaitingPanel();
  try {
    const result = await waitForChatJob(pending.jobId, pending.agentId || state.activeAgentId, 1);
    if (result) checkSurvey();
    return result;
  } catch (error) {
    localStorage.removeItem('chat_pending_job');
    state.chatJobId = null;
    addBotMessage(error.message || '排队任务未能完成', { agentId: pending.agentId || state.activeAgentId });
    showToast(error.message || '排队任务未能完成', 'error');
    return null;
  } finally {
    state.chatAbortController = null;
    state.chatQueueCanceling = false;
    finishChatRequest(sendBtn);
  }
}

async function fallbackToSyncChat(payload, agentId) {
  const res = await fetchWithTimeout(`${API_BASE}/api/chat/send`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  }, 120000);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || '发送失败');
  }
  addBotMessage(data.bot_response, {
    agentId,
    historyId: data.history_id,
    relatedCases: data.related_cases || [],
    relatedCasesTotal: data.related_cases_total,
  });
  return data;
}

async function executeChatRequest({ text, agentId }) {
  const agent = AGENTS.find(a => a.id === agentId) || AGENTS[0];
  const payload = buildChatPayload(text, agent);
  const sendBtn = startChatRequest();

  try {
    let result = await streamChatRequest(payload, agentId);
    if (result?.queued) {
      result = await waitForChatJob(result.jobId, agentId, result.position);
    }
    checkSurvey();
    return result;
  } catch (error) {
    if (error?.name === 'AbortError' && state.handoff.interrupting) return null;
    if (error.canFallback) {
      try {
        const result = await fallbackToSyncChat(payload, agentId);
        showToast('已切换为普通回复模式', 'info');
        checkSurvey();
        return result;
      } catch (fallbackError) {
        addBotMessage(fallbackError.message || '网络错误，请检查您的连接。', { agentId });
        showToast(fallbackError.message || '发送失败', 'error');
        throw fallbackError;
      }
    }

    if (error.renderedInMessage) {
      showToast(error.message || '回复中断', 'error');
      throw error;
    }

    addBotMessage(error.message || '网络错误，请检查您的连接。', { agentId });
    showToast(error.message || '发送失败', 'error');
    throw error;
  } finally {
    state.chatAbortController = null;
    finishChatRequest(sendBtn);
  }
}
