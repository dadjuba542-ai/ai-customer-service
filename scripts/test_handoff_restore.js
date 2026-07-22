#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const removedKeys = [];
const context = {
  state: {
    activeAgentId: 'aura',
    handoff: {
      session: { status: 'closed', service_mode: 'message' },
      pollTimer: 123,
      lastMessageId: 42,
      isNutritionMode: false,
    },
  },
  localStorage: { removeItem: (key) => removedKeys.push(key) },
  clearInterval: () => {},
  ensureConfiguredHandoffAgent: () => ({ agent_id: 'aura', name: '营养咨询' }),
  renderAgentTabs: () => {},
  updateHandoffUi: () => {},
  document: {
    getElementById: () => ({
      classList: { toggle: () => {} },
      placeholder: '',
      hidden: false,
    }),
  },
  addMessage: () => {},
  escapeHtml: (value) => value,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/js/handoff.js', 'utf8'), context);
context.resumeAiAfterHandoff();

assert.deepStrictEqual(removedKeys, ['handoff_session_id']);
assert.strictEqual(context.state.handoff.session, null);
assert.strictEqual(context.state.handoff.lastMessageId, 0);
console.log('PASS: closed handoff cleanup removes stale session storage');
