const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const renders = [];
let created = 0;
global.API_BASE = '';
global.state = { messages: [], handoff: { interrupting: false }, isStreaming: true };
global.authHeaders = headers => headers;
global.hideWaitingPanel = () => {};
global.updateChatAgentInfo = () => {};
global.createStreamingBotMessage = agentId => {
  created += 1;
  state.messages.push({ id: created, content: '', agentId, isStreaming: true });
  return created;
};
global.updateStreamingMessageDom = (id, text) => renders.push({ id, text });
global.appendStreamingBotMessage = (id, text) => {
  state.messages.find(m => m.id === id).content += text;
};
global.finalizeStreamingBotMessage = (id, extras) => {
  Object.assign(state.messages.find(m => m.id === id), extras, { isStreaming: false });
};
global.parseSSEChunk = chunk => {
  const lines = chunk.split('\n');
  return { event: lines[0].slice(7), data: JSON.parse(lines[1].slice(6)) };
};
const source = fs.readFileSync(path.join(__dirname, '..', 'static/js/chat-stream.js'), 'utf8');
vm.runInThisContext(`${source}\nglobalThis.runStream = streamChatRequest;`);

async function run(events) {
  state.messages = [];
  renders.length = 0;
  created = 0;
  const encoded = new TextEncoder().encode(events.map(([event, data]) =>
    `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''));
  let offset = 0;
  global.fetch = async () => ({ ok: true, status: 200, body: { getReader: () => ({
    read: async () => {
      if (offset >= encoded.length) return { done: true };
      const value = encoded.slice(offset, offset + 17);
      offset += 17;
      return { done: false, value };
    },
  }) } });
  return runStream({ message: '原问题' }, 'aura');
}

(async () => {
  const result = await run([
    ['delta', { text: '原兜底' }],
    ['replace', { text: '正在换个问法查找资料…' }],
    ['replace', { text: '恢复后的完整回答' }],
    ['done', { full_text: '恢复后的完整回答', history_id: 88 }],
  ]);
  assert.equal(created, 1);
  assert.equal(state.messages[0].content, '恢复后的完整回答');
  assert.equal(state.messages[0].historyId, 88);
  assert.equal(state.messages[0].isStreaming, false);
  assert.equal(result.history_id, 88);
  assert.deepEqual(renders.map(r => r.text), ['正在换个问法查找资料…', '恢复后的完整回答']);
  await run([
    ['delta', { text: '兜底' }],
    ['replace', { text: '正在换个问法查找资料…' }],
    ['replace', { text: '兜底' }],
    ['done', { full_text: '兜底', history_id: 89 }],
  ]);
  assert.equal(created, 1);
  assert.equal(state.messages[0].content, '兜底');
  await run([['delta', { text: '正常回答' }], ['done', { full_text: '正常回答', history_id: 90 }]]);
  assert.equal(state.messages[0].content, '正常回答');
  assert.equal(renders.length, 0);
  console.log('PASS: recovery replaces one streaming bubble, restores fallback and preserves normal answers');
})().catch(error => { console.error(error); process.exitCode = 1; });
