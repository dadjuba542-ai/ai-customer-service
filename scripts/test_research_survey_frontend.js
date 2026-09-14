const fs = require('fs');
const path = require('path');
const vm = require('vm');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const toasts = [];
const elements = {};
let lastFetch = null;

global.API_BASE = '';
global.authHeaders = (headers = {}) => headers;
global.showToast = (message, type) => { toasts.push({ message, type }); };
global.fetch = async (url, options = {}) => {
  lastFetch = { url, options, body: JSON.parse(options.body || '{}') };
  return { ok: true, status: 200, json: async () => ({ message: 'Survey saved' }) };
};

function makeElement(extra = {}) {
  return Object.assign({
    innerHTML: '',
    value: '',
    disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {},
  }, extra);
}

for (const id of ['research-body', 'research-overlay', 'research-submit', 'research-contact', 'research-q-comment']) {
  elements[id] = makeElement();
}

global.document = {
  getElementById(id) {
    return elements[id] || null;
  },
};

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'research-survey.js'), 'utf8');
vm.runInThisContext(`${source}
globalThis.__research = {
  openResearchSurvey,
  renderResearchQuestions,
  onResearchOptionClick,
  submitResearchSurvey,
  RESEARCH_QUESTIONS,
  getAnswers: () => researchAnswers,
};`);

(async () => {
  const api = global.__research;
  assert(api, 'research survey API should be exported');
  assert(api.RESEARCH_QUESTIONS.length === 5, 'expected 5 questions');
  assert(api.RESEARCH_QUESTIONS.filter(q => q.required).length === 3, 'expected 3 required questions');

  api.openResearchSurvey();
  const html = elements['research-body'].innerHTML;
  assert(html.includes('刚开始用'), 'render should include duration options');
  assert(html.includes('整体体验满意度'), 'render should include satisfaction question');
  assert(html.includes('research-q-required'), 'render should mark required questions');

  // 单选
  api.onResearchOptionClick({ target: { closest: () => ({
    dataset: { qid: 'duration', value: '1-3个月' },
    parentElement: { querySelectorAll: () => [] },
    classList: { toggle() {} },
  }) } });
  assert(api.getAnswers().duration === '1-3个月', 'single choice should be stored');

  // 多选
  const multiBtn = { dataset: { qid: 'usage', value: 'AI 问答' }, parentElement: { querySelectorAll: () => [] }, classList: { toggle() {} } };
  api.onResearchOptionClick({ target: { closest: () => multiBtn } });
  assert(JSON.stringify(api.getAnswers().usage) === JSON.stringify(['AI 问答']), 'multi choice should be stored');
  api.onResearchOptionClick({ target: { closest: () => multiBtn } });
  assert(JSON.stringify(api.getAnswers().usage) === JSON.stringify([]), 'multi choice should toggle off');

  // 缺少必填项时不得提交
  lastFetch = null;
  toasts.length = 0;
  await api.submitResearchSurvey();
  assert(lastFetch === null, 'should not submit with missing required answers');
  assert(toasts.some(t => t.type === 'error'), 'should warn about missing required answers');

  // 补齐后提交
  api.onResearchOptionClick({ target: { closest: () => ({
    dataset: { qid: 'usage', value: 'AI 问答' },
    parentElement: { querySelectorAll: () => [] },
    classList: { toggle() {} },
  }) } });
  api.onResearchOptionClick({ target: { closest: () => ({
    dataset: { qid: 'satisfaction', value: '5' },
    parentElement: { querySelectorAll: () => [] },
    classList: { toggle() {} },
  }) } });
  elements['research-q-comment'].value = '  很好用  ';
  elements['research-contact'].value = ' wx: test ';
  toasts.length = 0;
  await api.submitResearchSurvey();

  assert(lastFetch, 'should submit after required answers are filled');
  assert(lastFetch.url === '/api/survey/research', `unexpected url: ${lastFetch.url}`);
  assert(lastFetch.body.answers.duration === '1-3个月', lastFetch.body);
  assert(lastFetch.body.answers.satisfaction === '5', lastFetch.body);
  assert(lastFetch.body.answers.comment === '很好用', lastFetch.body);
  assert(lastFetch.body.contact === 'wx: test', lastFetch.body);
  assert(toasts.some(t => t.type === 'success'), 'should toast success');

  console.log('PASS: research survey frontend');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
