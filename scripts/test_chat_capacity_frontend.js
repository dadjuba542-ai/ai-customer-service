const fs = require('fs');
const path = require('path');
const vm = require('vm');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const calls = [];
const renderedMessages = [];
const toasts = [];
let finished = false;

global.API_BASE = '';
global.state = { handoff: { interrupting: false }, chatAbortController: null };
global.AGENTS = [{ id: 'aura' }];
global.authHeaders = (headers = {}) => headers;
global.buildChatPayload = text => ({ message: text });
global.startChatRequest = () => ({ disabled: true });
global.finishChatRequest = () => { finished = true; };
global.checkSurvey = () => {};
global.addBotMessage = message => { renderedMessages.push(message); };
global.showToast = message => { toasts.push(message); };
global.fetch = async url => {
  calls.push(url);
  return {
    ok: false,
    status: 503,
    body: {},
    headers: { get: name => (name === 'Retry-After' ? '3' : null) },
    json: async () => ({
      error: '当前咨询人数较多，请稍后重试',
      error_code: 'chat_capacity',
      retryable: true,
      retry_after: 3,
    }),
  };
};

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'chat-stream.js'), 'utf8');
vm.runInThisContext(`${source}\nglobalThis.__executeChatRequest = executeChatRequest;`);

(async () => {
  let error;
  try {
    await global.__executeChatRequest({ text: '并发测试', agentId: 'aura' });
  } catch (exc) {
    error = exc;
  }

  assert(error, 'capacity rejection should reject the chat request');
  assert(error.errorCode === 'chat_capacity', `unexpected error code: ${error.errorCode}`);
  assert(error.canFallback === false, 'capacity rejection must not fall back to sync chat');
  assert(calls.length === 1 && calls[0].endsWith('/api/chat/stream'), `unexpected fetch calls: ${calls}`);
  assert(renderedMessages.includes('当前咨询人数较多，请稍后重试'), `unexpected messages: ${renderedMessages}`);
  assert(toasts.includes('当前咨询人数较多，请稍后重试'), `unexpected toasts: ${toasts}`);
  assert(finished, 'chat request UI state should be finalized');
  console.log('PASS: chat capacity frontend does not fall back to sync');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
