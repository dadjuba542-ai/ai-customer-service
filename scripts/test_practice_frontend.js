const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, { id, innerHTML: '', textContent: '', value: '', disabled: false });
  return elements.get(id);
}
const sandbox = {
  console, Date, setInterval: () => 0, window: { crypto: require('crypto').webcrypto }, crypto: require('crypto').webcrypto,
  API_BASE: '', state: { sessionToken: 'session' },
  document: {
    addEventListener() {}, getElementById: element, querySelectorAll: () => [], querySelector: () => null,
    createElement: () => {
      let text = '';
      return { set textContent(value) { text = value; }, get innerHTML() {
        return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      } };
    },
  },
  featureEnabled: () => true, authHeaders: extra => ({ Authorization: 'Bearer session', ...extra }),
  fetchWithTimeout: async () => { throw new Error('unexpected request'); },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static/js/practice.js'), 'utf8'), sandbox);
vm.runInContext('globalThis.ps = practiceState;', sandbox);
const q = { id: 1, category: '益生菌', title: '场景问题', options: ['选项一', '选项二', '选项三', '选项四'] };
const session = { id: 'test-session', mode: 'daily', batch_no: 1, cursor: 0, answered_count: 0, completed: 0, questions: [q] };
const answered = { ...session, answered_count: 1, questions: [{ ...q, selected_index: 0, answer_index: 0, correct: true, explanation: '先了解需求', method: '您想了解什么？' }] };
function response(data, status=200) { return { ok: status===200, json: async () => data }; }
(async () => {
  sandbox.ps.session = session;
  sandbox.renderPracticeTraining();
  assert.doesNotMatch(element('practice-body').innerHTML, /下一题 →/);
  let release;
  let calls = 0;
  sandbox.fetchWithTimeout = async () => { calls++; await new Promise(resolve => { release=resolve; }); return response(answered); };
  const first = sandbox.answerPractice(0);
  await sandbox.answerPractice(1);
  assert.equal(calls, 1); // Double click cannot send two answers.
  release(); await first;
  assert.match(element('practice-body').innerHTML, /推荐选择 ✓/);
  assert.match(element('practice-body').innerHTML, /下一句可以这样说/);
  assert.equal(sandbox.ps.busy, false);

  // Lost response: the durable server result restores feedback without another answer.
  sandbox.ps.session = session;
  const requests = [];
  sandbox.fetchWithTimeout = async (url, options) => {
    requests.push({url, options});
    if (url.endsWith('/answer')) throw new Error('连接中断');
    return response(answered);
  };
  await sandbox.answerPractice(0);
  assert.equal(requests.length, 2);
  assert.equal(sandbox.ps.session.answered_count, 1);
  assert.match(element('practice-body').innerHTML, /推荐选择 ✓/);

  // Create retries reuse the idempotency key, including after a network timeout.
  sandbox.ps.session = null;
  sandbox.ps.catalog = { daily: { day: '2026-10-14' }, categories: [], batches: [] };
  const keys = [];
  sandbox.fetchWithTimeout = async (url, options) => {
    keys.push(JSON.parse(options.body).request_id);
    if (keys.length === 1) throw new Error('连接中断');
    return response(session);
  };
  await sandbox.startPractice('free', 1);
  await sandbox.startPractice('free', 1);
  assert.equal(keys[0], keys[1]);

  // Untrusted bank content is displayed as text in questions and explanations.
  sandbox.ps.session = { ...answered, questions: [{ ...answered.questions[0], title: '<img src=x onerror=alert(1)>', method: '<script>bad()</script>' }] };
  sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML, /&lt;img/);
  assert.doesNotMatch(element('practice-body').innerHTML, /<script>bad/);
  sandbox.esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static/admin/practice.js'), 'utf8'), sandbox);
  assert.equal(sandbox.practiceAdminEscape('名字" onfocus="坏内容'), '名字&quot; onfocus=&quot;坏内容');

  // An older tab request must not replace a more recently selected tab.
  let releaseRecords;
  sandbox.fetchWithTimeout = async url => {
    if (url.includes('/sessions?')) { await new Promise(resolve => { releaseRecords=resolve; }); return response({items: [], total: 0, page: 1}); }
    return response({items: [], week_start:'2026-10-12', week_end:'2026-10-18', today_points:0, week_points:0, my_rank:null});
  };
  const records = sandbox.practiceTab('records');
  await sandbox.practiceTab('ranking');
  releaseRecords(); await records;
  assert.match(element('practice-body').innerHTML, /每周荣誉/);
  // Seasonal theme takes priority and ordinary practice stays available.
  sandbox.ps.session = null;
  sandbox.ps.catalog = {daily:{day:'2026-10-14',batch_no:1},daily_session:null,categories:[],batches:[{batch_no:1}],
    stage:{id:3,title:'三伏天专题',description:'阶段内容',starts_on:'2026-10-14',ends_on:'2026-10-20',question_count:50,batch_count:5,daily:{batch_no:2},batches:[{batch_no:1}]}};
  sandbox.ps.tab='training';sandbox.renderPracticeTraining();
  const themed=element('practice-body').innerHTML;
  assert.match(themed,/三伏天专题/);
  assert.match(themed,/practice-daily-compact/);
  assert.match(themed,/常规题库 · 自由练习/);
  assert.ok(themed.indexOf('三伏天专题')<themed.indexOf('每日闯关 · 常规练习'));
  sandbox.ps.catalog.daily_session={stage_id:0,completed:1};sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML,/今天已选择一局计分/);
  assert.match(element('practice-body').innerHTML,/startPractice\('free',2,3\)/);
  const submitted=[];
  sandbox.fetchWithTimeout=async (url,options)=>{submitted.push(JSON.parse(options.body));return response(session);};
  await sandbox.startPractice('free',1,3);
  assert.equal(submitted[0].stage_id,3);
  const entry={day:'2026-10-14',stage_id:3,stage_title:'价格沟通周',kind:'weekly',label:'初练',question_title:'客户说价格太贵，怎么接？',question_id:123,mode:'daily',action:'start',session_id:null};
  const entryHtml=sandbox.practiceEntryCard(entry);
  assert.match(entryHtml,/本周：价格沟通周/);
  assert.match(entryHtml,/客户说价格太贵/);
  assert.doesNotMatch(entryHtml,/选项一|answer_index/);
  assert.match(sandbox.practiceEntryCard({...entry,action:'resume'}),/继续今天的练习/);
  assert.match(sandbox.practiceEntryCard({...entry,mode:'free'}),/本次为自由练习/);
  sandbox.ps.session={...answered,entry:1};sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML,/继续剩余9题/);
  assert.match(element('practice-body').innerHTML,/稍后继续/);
  sandbox.ps.session={...answered,entry:1,mode:'free'};sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML,/完成本次接待/);
  assert.doesNotMatch(element('practice-body').innerHTML,/完成后结算积分/);
  // Reception route and streaks survive a restored session; unanswered questions do not reset a streak.
  const receptionQuestions=Array.from({length:10},(_,i)=>({...answered.questions[0],id:i+1,title:`客户场景${i+1}`,correct:![2,6].includes(i)}));
  const partial={...session,cursor:5,answered_count:6,questions:receptionQuestions.slice(0,6)};
  partial.questions.push({...q,id:7});
  assert.equal(sandbox.practiceReceptionStats(partial).current,3);
  assert.equal(sandbox.practiceReceptionStats(partial).longest,3);
  sandbox.ps.session=partial;sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML,/连续接住3个客户问题/);
  assert.match(element('practice-body').innerHTML,/过半了，再接待4位客户/);
  assert.match(element('practice-body').innerHTML,/aria-valuenow="6"/);
  assert.match(element('practice-body').innerHTML,/width:60%/);
  assert.doesNotMatch(element('practice-body').innerHTML,/reception-node/);
  assert.doesNotMatch(element('practice-body').innerHTML,/<b>A<\/b>|下一题 →/);
  sandbox.ps.receptionFlash=`${partial.id}:6`;sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML,/practice-feedback reception-celebrate/);
  sandbox.renderPracticeTraining();
  assert.doesNotMatch(element('practice-body').innerHTML,/practice-feedback reception-celebrate/);
  const complete={...session,completed:1,correct_count:8,points:80,point_reason:'每日局积分',answered_count:10,questions:receptionQuestions};
  sandbox.ps.session=complete;sandbox.renderPracticeTraining();
  const report=element('practice-body').innerHTML;
  assert.match(report,/本局徽章 · 沟通能手/);
  assert.match(report,/最长连对/);
  assert.ok(report.indexOf('客户 3 ·')<report.indexOf('客户 1 ·'));
  sandbox.ps.session={...complete,correct_count:10};sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML,/本局徽章 · 接待达人/);
  sandbox.ps.session={...complete,correct_count:0,points:0};sandbox.renderPracticeTraining();
  assert.match(element('practice-body').innerHTML,/本局徽章 · 练习完成/);
  let copied;
  sandbox.navigator={clipboard:{writeText:async text=>{copied=text;}}};
  const copyButton={disabled:false,textContent:'复制回复'};
  await sandbox.copyPracticeReply(2,copyButton);
  assert.equal(copied,receptionQuestions[2].method);assert.equal(copyButton.textContent,'已复制 ✓');
  sandbox.navigator.clipboard.writeText=async()=>{throw new Error('denied');};
  await sandbox.copyPracticeReply(2,copyButton);
  assert.match(copyButton.textContent,/复制失败/);assert.equal(copyButton.disabled,false);
  // Admin search, filters and pagination operate on the bank without resetting the editor.
  vm.runInContext(`adminPracticeData = {questions: [
    {id:1,batch_no:1,category:'益生菌',enabled:1,title:'客户问价格',explanation:'比较规格',method:'如何比较',options:[]},
    {id:2,batch_no:11,category:'蛋白质',enabled:0,title:'粉剂口感',explanation:'了解需求',method:'怎么使用',options:[]}
  ]};`, sandbox);
  sandbox.filterAdminPractice('search','价格');
  assert.match(element('practice-question-list').innerHTML, /客户问价格/);
  assert.doesNotMatch(element('practice-question-list').innerHTML, /粉剂口感/);
  sandbox.filterAdminPractice('search','');
  sandbox.filterAdminPractice('status','0');
  assert.match(element('practice-question-list').innerHTML, /粉剂口感/);
  assert.doesNotMatch(element('practice-question-list').innerHTML, /客户问价格/);
  assert.equal(sandbox.practiceAdminNextBatch(),11);
  console.log('PASS: double clicks, durable recovery, create retries, answer feedback, escaping, tab races, reception streaks/reports/copying, admin filters');
})().catch(error => { console.error(error); process.exitCode = 1; });
