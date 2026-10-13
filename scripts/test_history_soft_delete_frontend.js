#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

async function main() {
  const requests = [];
  const toasts = [];
  let succeed = true;
  let confirmedText;
  let renders = 0;
  let polls = 0;
  const context = {
    state: { messages: [], nutritionistNotes: { items: [], total: 0 } },
    lastUserText: '', lastUserAgentId: '', API_BASE: '',
    document: { getElementById: () => ({ value: '产品咨询' }) },
    confirm: text => { confirmedText = text; return true; },
    authHeaders: extras => extras || {},
    showToast: (...args) => toasts.push(args),
    renderMessages: () => { renders++; },
    renderNutritionistNoteAlert: () => {},
    pollNutritionistNotes: async () => { polls++; },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: succeed, json: async () => ({ sessions: [] }) };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('static/js/history-community.js', 'utf8'), context);
  context.renderMemorySessions = () => {};
  context.state.messages = [
    { id: 'history-user-1', role: 'user', historyId: 1, content: 'restored deleted' },
    { id: 'history-bot-1', role: 'bot', historyId: 1 },
    { id: 'note-1', role: 'nutritionist', historyId: 1 },
    { id: 'live-user', role: 'user', content: 'live deleted', agentId: 'aura' },
    { id: 'live-bot', role: 'bot', historyId: 2 },
    { id: 'keep-user', role: 'user', historyId: 3, content: 'keep', agentId: 'coder' },
    { id: 'keep-bot', role: 'bot', historyId: 3 },
    { id: 'human-note', role: 'nutritionist', content: 'keep unrelated' },
  ];
  context.state.nutritionistNotes = { items: [{ history_id: 1 }, { history_id: 3 }], total: 2 };
  await context.deleteSession({ stopPropagation() {} }, [1, 2]);
  assert(confirmedText.includes('后台服务记录仍会保留'));
  assert.deepStrictEqual(Array.from(context.state.messages, m => m.id), ['keep-user', 'keep-bot', 'human-note']);
  assert.strictEqual(context.lastUserText, 'keep');
  assert.strictEqual(context.lastUserAgentId, 'coder');
  assert.strictEqual(context.state.nutritionistNotes.items.length, 1);
  assert.strictEqual(context.state.nutritionistNotes.total, 1);
  assert.strictEqual(renders, 1);
  assert.strictEqual(polls, 1);
  assert.strictEqual(requests[1].url, '/api/history/sessions?query_type=%E4%BA%A7%E5%93%81%E5%92%A8%E8%AF%A2');
  succeed = false;
  await context.deleteSession({ stopPropagation() {} }, [3]);
  assert.strictEqual(context.state.messages.length, 3);
  assert.strictEqual(toasts.at(-1)[0], '删除失败');
  console.log('PASS: frontend deletion removes restored/live turns and notes, refreshes filtered history, preserves data on failure');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
