function renderNutritionistNoteAlert() {
  const alert = document.getElementById('nutritionist-note-alert');
  if (!alert) return;
  const total = Number(state.nutritionistNotes.total || 0);
  alert.hidden = total === 0;
  document.getElementById('nutritionist-note-alert-count').textContent = total > 99 ? '99+' : String(total);
  const latest = state.nutritionistNotes.items[0];
  document.getElementById('nutritionist-note-alert-text').textContent = latest
    ? `${latest.user_message || '原问题'}：${latest.content || ''}`
    : '点击查看补充内容';
}

function syncNutritionistNoteInCurrentChat(note) {
  const botIndex = state.messages.findIndex((message) => message.role === 'bot' && Number(message.historyId) === Number(note.history_id));
  if (botIndex < 0) return false;
  const noteId = `nutritionist-note-${note.id}`;
  state.messages = state.messages.filter((message) => message.id !== noteId);
  const updatedBotIndex = state.messages.findIndex((message) => message.role === 'bot' && Number(message.historyId) === Number(note.history_id));
  state.messages.splice(updatedBotIndex + 1, 0, {
    id: noteId,
    role: 'nutritionist',
    content: note.content || '',
    time: formatTime(note.updated_at, true),
    historyId: note.history_id,
    nutritionistNoteId: note.id,
    revision: note.revision,
  });
  renderMessages();
  return true;
}

async function pollNutritionistNotes(announce = true) {
  if (!state.sessionToken && !state.token) return;
  try {
    const response = await fetch(`${API_BASE}/api/nutritionist-notes/unread?limit=20`, { headers: authHeaders() });
    if (!response.ok) return;
    const data = await response.json();
    const items = data.items || [];
    const fresh = items.filter((item) => !state.nutritionistNotes.revisionKeys.has(`${item.id}:${item.revision}`));
    items.forEach((item) => {
      state.nutritionistNotes.revisionKeys.add(`${item.id}:${item.revision}`);
      syncNutritionistNoteInCurrentChat(item);
    });
    state.nutritionistNotes.items = items;
    state.nutritionistNotes.total = Number(data.total || 0);
    renderNutritionistNoteAlert();
    if (announce && state.nutritionistNotes.initialized && fresh.length) {
      showToast('在线营养师发来了新的补充留言', 'success');
    }
    state.nutritionistNotes.initialized = true;
  } catch {}
}

async function startNutritionistNotePolling() {
  clearInterval(state.nutritionistNotes.pollTimer);
  await pollNutritionistNotes(false);
  state.nutritionistNotes.pollTimer = setInterval(() => pollNutritionistNotes(true), 30000);
}

async function openLatestNutritionistNote() {
  const note = state.nutritionistNotes.items[0];
  if (!note) return;
  try {
    const response = await fetch(`${API_BASE}/api/history/sessions`, { headers: authHeaders() });
    if (!response.ok) throw new Error('无法加载原问答');
    const data = await response.json();
    const session = (data.sessions || []).find((candidate) => (candidate.items || []).some((item) => Number(item.id) === Number(note.history_id)));
    if (!session) throw new Error('原问答已不存在');
    applyHistoryItems(session.items || []);
    switchView('chat');
    await fetch(`${API_BASE}/api/nutritionist-notes/${encodeURIComponent(note.id)}/read`, { method: 'POST', headers: authHeaders() });
    await pollNutritionistNotes(false);
    requestAnimationFrame(() => {
      const target = document.querySelector(`[data-msg-id="nutritionist-note-${note.id}"]`);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  } catch (error) {
    showToast(error.message || '留言加载失败', 'error');
  }
}
