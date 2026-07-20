/* ===== Chat Menu ===== */
function toggleChatMenu(e) {
  e.stopPropagation();
  const menu = document.getElementById('chat-menu');
  const isActive = menu.classList.toggle('active');
  if (isActive) {
    setTimeout(() => document.addEventListener('click', closeChatMenu), 10);
  }
}
function closeChatMenu() {
  document.getElementById('chat-menu').classList.remove('active');
  document.removeEventListener('click', closeChatMenu);
}

/* ===== Clear Chat ===== */
function clearChat() {
  closeChatMenu();
  if (state.handoff.session && ['queued', 'assigned', 'active'].includes(state.handoff.session.status)) {
    showToast('人工咨询进行中不能清空对话', 'info');
    return;
  }
  if (state.messages.length === 0) return;
  if (!confirm('确定清空当前对话？历史记录不会被删除。')) return;
  state.messages = [];
  renderMessages();
  showToast('对话已清空', 'success');
}

/* ===== Feedback ===== */
async function sendFeedback(historyId, feedback, msgIdx) {
  if (state.messages[msgIdx] && state.messages[msgIdx].feedback !== undefined) return;
  if (feedback === 1) {
    await submitFeedback(historyId, 1, '', msgIdx);
  } else {
    showReasonPopup(historyId, msgIdx);
  }
}

async function submitFeedback(historyId, feedback, reason, msgIdx) {
  try {
    const body = { history_id: historyId, feedback };
    if (reason) body.reason = reason;
    const res = await fetch(`${API_BASE}/api/chat/feedback`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    });
    if (res.ok) {
      if (state.messages[msgIdx]) {
        state.messages[msgIdx].feedback = feedback;
      }
      document.querySelectorAll('.msg-feedback-btn').forEach(btn => {
        if (btn.getAttribute('onclick')?.includes(`sendFeedback(${historyId},`)) {
          btn.disabled = true;
          if (btn.getAttribute('onclick')?.includes(`, ${feedback}, `)) {
            btn.classList.add('active');
          }
        }
      });
      showToast(feedback ? '感谢你的反馈 😊' : '已记录反馈', 'success');
    }
  } catch {
    showToast('提交失败，请重试', 'error');
  }
}

function showReasonPopup(historyId, msgIdx) {
  const reasons = ['回答不准确', '不是我想要的', '其他原因'];
  const container = document.getElementById('reason-popup');
  container.innerHTML = reasons.map(r =>
    `<button class="reason-tag" onclick="submitFeedback(${historyId}, 0, '${r}', ${msgIdx});closeReasonPopup()">${r}</button>`
  ).join('');
  container.classList.add('active');
  setTimeout(closeReasonPopup, 4000);
}

function closeReasonPopup() {
  document.getElementById('reason-popup').classList.remove('active');
}

/* ===== Survey ===== */
function checkSurvey() {
  const key = 'survey_count';
  let count = parseInt(localStorage.getItem(key) || '0', 10);
  count++;
  localStorage.setItem(key, count);
  if (count % 10 === 0) {
    document.getElementById('survey-overlay').classList.add('active');
  }
}

function submitSurvey(score) {
  document.getElementById('survey-overlay').classList.remove('active');
  fetch(`${API_BASE}/api/survey`, {
    method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ score }),
  }).catch(() => {});
}

/* ===== Regenerate ===== */
async function regenerateMsg(msgIdx) {
  if (state.handoff.session && ['queued', 'assigned', 'active'].includes(state.handoff.session.status)) {
    showToast('人工咨询进行中，不能让 AI 重新回答', 'info');
    return;
  }
  const botMsg = state.messages[msgIdx];
  if (!botMsg || botMsg.role !== 'bot' || state.isStreaming) return;
  
  // Find the user message this bot responded to
  let userText = botMsg.replyToText;
  let agentId = botMsg.agentId || state.activeAgentId;
  
  // If no stored replyToText, find preceding user message
  if (!userText) {
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (state.messages[i].role === 'user') {
        userText = state.messages[i].content;
        break;
      }
    }
  }
  if (!userText) return;
  
  // Remove this bot message and all messages after it
  state.messages.splice(msgIdx);
  renderMessages();
  
  // Switch to the correct agent
  state.activeAgentId = agentId;
  renderAgentTabs();
  
  // Re-send
  lastUserText = userText;
  lastUserAgentId = agentId;
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  addMessage({ id: Date.now(), role: 'user', content: userText, time });

  try {
    await executeChatRequest({ text: userText, agentId });
  } catch {}
}

