async function streamChatRequest(payload, agentId) {
  const controller = new AbortController();
  state.chatAbortController = controller;
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    signal: controller.signal,
  });

  if (!res.ok || !res.body) {
    const errorPayload = await res.json().catch(() => ({}));
    const error = new Error(errorPayload.error || '流式连接失败');
    error.canFallback = true;
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
    const result = await streamChatRequest(payload, agentId);
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
