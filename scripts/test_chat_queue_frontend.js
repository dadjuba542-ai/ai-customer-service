const fs = require('fs');
const path = require('path');
const vm = require('vm');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const calls = [];
const rendered = [];
const storage = new Map();
let finished = false;

global.API_BASE = '';
global.state = {
  handoff: { interrupting: false },
  chatAbortController: null,
  chatJobId: null,
  chatQueueCanceling: false,
  messages: [],
};
global.AGENTS = [{ id: 'aura' }];
global.authHeaders = headers => headers;
global.buildChatPayload = text => ({ message: text });
global.startChatRequest = () => ({ disabled: true });
global.finishChatRequest = () => { finished = true; };
global.checkSurvey = () => {};
global.showWaitingPanel = () => {};
global.setWaitingQueueStatus = () => {};
global.hideWaitingPanel = () => {};
global.addBotMessage = (message, options) => rendered.push({ message, options });
global.showToast = () => {};
global.localStorage = {
  getItem: key => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, value),
  removeItem: key => storage.delete(key),
};

let pollCount = 0;
global.fetch = async url => {
  calls.push(url);
  if (url.endsWith('/api/chat/stream')) {
    return {
      ok: true,
      status: 202,
      body: null,
      json: async () => ({ status: 'queued', job_id: 'job-1', position: 1, retry_after: 1 }),
    };
  }
  pollCount += 1;
  return {
    ok: true,
    status: 200,
    json: async () => ({
      status: 'completed',
      bot_response: '排队后的回答',
      history_id: 88,
      related_cases: [],
      related_cases_total: 0,
    }),
  };
};

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'chat-stream.js'), 'utf8');
vm.runInThisContext(`${source}\nglobalThis.__executeChatRequest = executeChatRequest;`);

(async () => {
  const result = await global.__executeChatRequest({ text: '排队测试', agentId: 'aura' });
  assert(result.history_id === 88, 'queued result should return the completed answer');
  assert(pollCount === 1, 'queued job should be polled once before completion');
  assert(calls.length === 2, `expected stream and status calls only: ${calls}`);
  assert(calls[0].endsWith('/api/chat/stream'), 'first request must use the stream endpoint');
  assert(calls[1].endsWith('/api/chat/jobs/job-1'), 'second request must poll the queued job');
  assert(rendered[0]?.message === '排队后的回答', 'completed queued answer should be rendered');
  assert(finished, 'chat request UI state should be finalized');
  console.log('PASS: chat queue frontend polling does not call sync endpoint');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
