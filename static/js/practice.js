/* The game owns its state; no messages enter the ordinary AI conversation. */
const practiceState = { catalog: null, session: null, tab: 'training', busy: false,
  identity: null, createAttempt: null, page: 1, generation: 0, entryData: null, entryAttempt: null, promotionGeneration: 0 };
function practiceEscape(value) {
  const el = document.createElement('span'); el.textContent = String(value ?? ''); return el.innerHTML;
}
function practiceRequestId() {
  return window.crypto?.randomUUID ? crypto.randomUUID() : `p${Date.now()}_${Math.random().toString(36).slice(2)}`;
}
function practiceNotice(message = '') { document.getElementById('practice-notice').textContent = message; }
async function practiceApi(path, options = {}) {
  const response = await fetchWithTimeout(`${API_BASE}/api/practice${path}`, {
    ...options, headers: authHeaders({ ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers }),
  }, 20000);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || '暂时未能连接，请重试');
  return data;
}
async function loadPracticePage() {
  if (!featureEnabled('practice')) { practiceNotice('每日闯关暂未开启'); return; }
  if (practiceState.busy) return;
  const identity = state.sessionToken || state.token;
  if (practiceState.identity !== identity) {
    Object.assign(practiceState, { identity, session: null, createAttempt: null, catalog: null, tab: 'training', page: 1 });
  }
  practiceNotice('正在加载关卡…');
  const generation = ++practiceState.generation;
  try {
    const data = await practiceApi('/catalog');
    if (generation !== practiceState.generation) return;
    practiceState.catalog = data;
    practiceState.entryData = data.entry || practiceState.entryData;
    if (practiceState.session) practiceState.session = await practiceApi(`/sessions/${practiceState.session.id}`);
    practiceNotice();
    await practiceTab(practiceState.tab);
    if(practiceState.linkStage && practiceState.linkStage!==data.stage?.id) practiceNotice('该活动已结束，已为你展示当前可练内容。');
    practiceState.linkStage=null;
  } catch (error) {
    practiceNotice(error.message);
    document.getElementById('practice-body').innerHTML = '<button class="practice-button" onclick="loadPracticePage()">重新加载</button>';
  }
}
async function practiceTab(tab) {
  if (practiceState.busy) return;
  practiceState.tab = tab;
  const generation = ++practiceState.generation;
  document.querySelectorAll('[data-practice-tab]').forEach(btn => btn.classList.toggle('active', btn.dataset.practiceTab === tab));
  practiceNotice();
  if (tab === 'training') return renderPracticeTraining();
  const host = document.getElementById('practice-body');
  host.innerHTML = '<p class="practice-hint">正在加载…</p>';
  try {
    if (tab === 'records') {
      const data = await practiceApi(`/sessions?page=${practiceState.page}`);
      if (generation !== practiceState.generation) return;
      host.innerHTML = `<h2 class="practice-subpage-title">闯关记录</h2><p class="practice-hint">共 ${data.total} 局 · 第 ${data.page} 页</p>` +
        data.items.map(item => `<button class="practice-record" onclick="openPracticeRecord('${item.id}')">
          <strong>${practiceEscape(practiceSessionLabel(item))} · ${practiceBatchLabel(item)}</strong>
          <small>${practiceEscape(new Date(item.created_at).toLocaleString('zh-CN'))}</small>
          <small>${item.completed ? `答对 ${item.correct_count}/10 · +${item.points} 积分` : `继续答题 · 第 ${item.cursor + 1}/10 题`}</small></button>`).join('') +
        (!data.items.length ? '<div class="practice-card"><p>从今天的10道题开始吧。</p></div>' : '') +
        `<div class="practice-actions"><button class="practice-button secondary" ${data.page === 1 ? 'disabled' : ''} onclick="practiceRecordsPage(-1)">上一页</button>
        <button class="practice-button secondary" ${data.page * 20 >= data.total ? 'disabled' : ''} onclick="practiceRecordsPage(1)">下一页</button></div>`;
    } else {
      const data = await practiceApi('/scores');
      if (generation !== practiceState.generation) return;
      host.innerHTML = `<h2 class="practice-subpage-title">团队周榜</h2><div class="practice-card"><span class="practice-eyebrow">本周一起进步</span><h3>${practiceEscape(data.team_name || '本团队')}周榜</h3>
        <p>${data.week_start} 至 ${data.week_end} · 北京时间</p>
        <div class="practice-score-grid"><div><b>${data.today_points}<small>/100</small></b><span>今日积分</span></div><div><b>${data.week_points}</b><span>本周积分</span></div><div><b>${data.my_rank ?? '—'}</b><span>我的名次</span></div></div>
        ${data.my_honor ? `<p class="practice-honor">✦ 本周荣誉 · ${practiceEscape(data.my_honor)}</p>` : ''}
        <table class="practice-ranking"><thead><tr><th>名次</th><th>伙伴</th><th>积分</th></tr></thead><tbody>
        ${data.items.map(item => `<tr class="${item.is_me ? 'mine' : ''}"><td>${item.rank}</td><td>${practiceEscape(item.name)}${item.is_me ? '（我）' : ''}${item.honor ? `<span class="practice-rank-honor">${practiceEscape(item.honor)}</span>` : ''}</td><td>${item.points}</td></tr>`).join('')}
        </tbody></table>${data.items.length ? '' : '<p>本周榜单等你点亮。</p>'}</div>
        <div class="practice-card"><h3>每周荣誉</h3><p>按上周团队积分授予，本周展示。同分并列、同名次同头衔。</p>
        <div class="practice-honor-list"><span>🥇 第1名 · 周冠军</span><span>✦ 第2–3名 · 沟通达人</span><span>☆ 第4–10名 · 学习之星</span></div>
        <p class="practice-hint">完成每日局，每答对1题获10分，每日最高100分。自由练习保留成绩。周榜展示前100名（含并列），本人名次单独显示。</p></div>`;
    }
  } catch (error) { if (generation === practiceState.generation) practiceNotice(error.message); }
}
function practiceRecordsPage(delta) { practiceState.page = Math.max(1, practiceState.page + delta); practiceTab('records'); }
function renderPracticeTraining() {
  if (practiceState.tab !== 'training') return;
  const host = document.getElementById('practice-body');
  const s = practiceState.session;
  if (!s) {
    const data = practiceState.catalog;
    if (!data) return;
    const today = data.daily, existing = data.daily_session, stage = data.stage;
    const ordinaryOther = existing && (existing.stage_id || 0)!==0;
    host.innerHTML = (practiceState.linkLanding && data.entry ? practiceEntryCard(data.entry) : '') + renderPracticeStage(stage, existing) + (today ? `<div class="practice-card ${stage?'practice-daily-compact':'practice-hero'}"><span class="practice-eyebrow">今日挑战 · ${today.day}</span>
      <h3>${stage?'每日闯关 · 常规练习':'每天10题，边答边学'}</h3><p>每题选完立即看解析，再学一个可以用在实际场景中的方法。</p>
      <div class="practice-category-tags">${data.categories.map(c => `<span>${practiceEscape(c)}</span>`).join('')}</div>
      <div class="practice-hero-score"><b>10</b> 道题 <i>·</i> 最高 <b>100</b> 积分</div>
      <button class="practice-button" onclick="startPractice('${ordinaryOther?'free':'daily'}',${ordinaryOther?today.batch_no:'undefined'},0)">${ordinaryOther?'自由练习常规题':existing ? existing.completed ? '查看今日成绩' : '继续今日闯关' : '开始今日闯关'} <span aria-hidden="true">→</span></button>
      <p class="practice-hint">每日首次作答计分，完成一局后入账。答题后即可学习解析。</p></div>` : '<div class="practice-card"><p>每日关卡正在准备中。</p></div>');
    if(practiceState.linkLanding && data.entry)recordPracticeEntryImpression(data.entry,host.querySelector('[data-practice-entry-button]'));
    return;
  }
  const stats = practiceReceptionStats(s);
  const celebrate = practiceState.receptionFlash === `${s.id}:${s.answered_count}`;
  practiceState.receptionFlash = null;
  if (s.completed) {
    const review = s.questions.map((q, index) => ({q,index})).sort((a,b) => Number(a.q.correct)-Number(b.q.correct));
    const wrong = review.filter(item => !item.q.correct).length;
    const badge = s.correct_count===10 ? '满分通关' : s.correct_count>=7 ? '闯关达人' : '练习完成';
    host.innerHTML = `<div class="practice-card practice-result reception-report ${celebrate?'reception-celebrate':''}"><span class="practice-eyebrow">${practiceEscape(practiceSessionLabel(s))} · ${practiceBatchLabel(s)}</span>
      <div class="reception-trophy" aria-hidden="true">✦</div><h3>今日闯关完成</h3><span class="reception-badge">本局徽章 · ${badge}</span>
      <div class="reception-report-stats"><div><b>${s.correct_count}<small>/10</small></b><span>答对题数</span></div><div><b>${stats.longest}<small>题</small></b><span>最长连对</span></div><div><b>${s.points}<small>分</small></b><span>本局获得</span></div></div>
      <p class="practice-hint">${practiceEscape(s.point_reason)}</p>
      ${renderReceptionRoute(s)}
      <div class="practice-actions"><button class="practice-button" onclick="startNextPracticeRound()">继续练习 · 随机10题</button>
      <button class="practice-button secondary" onclick="leavePracticeSession(true)">返回问答课堂</button></div></div>
      <div class="practice-card"><h3>答题回顾 · ${wrong ? `${wrong}道题值得再看` : '10道题全部答对'}</h3>
      ${review.map(({q,index},position) => `<details class="practice-review" ${position===0?'open':''}><summary>${q.correct ? '✓' : '↗'} 第 ${index+1} 题 · ${practiceEscape(q.title)}</summary>
      <p>我的选择：${practiceEscape(q.options[q.selected_index])}</p><p><strong>推荐选择：</strong>${practiceEscape(q.options[q.answer_index])}</p>${renderPracticeExplanation(q,index)}</details>`).join('')}</div>`;
    return;
  }
  const q = s.questions[s.cursor], answered = q.selected_index !== undefined;
  const milestone = s.answered_count===3 ? '热身完成！接下来用刚学的方法做判断。' : s.answered_count===7 ? '应用完成！最后3题，巩固今天的知识。' : '';
  const segment = s.cursor < 3 ? '热身 · 1/3' : s.cursor < 7 ? '应用 · 2/3' : '巩固 · 3/3';
  host.innerHTML = `<div class="practice-card reception-route-card"><div class="practice-question-meta"><span class="practice-category">问答闯关</span><span>已完成 ${s.answered_count} / 10 题</span></div>
    <p class="practice-hint">${practiceEscape(practiceSessionLabel(s))} · ${practiceBatchLabel(s)} · ${segment}</p>${renderReceptionRoute(s)}</div>
    <div class="practice-card reception-conversation"><div class="reception-customer"><span class="reception-avatar" aria-hidden="true">${s.cursor+1}</span><div><strong>第 ${s.cursor+1} 题</strong><span>${practiceEscape(q.category)} · ${segment}</span></div></div>
    <h3 class="practice-question-title reception-message">${practiceEscape(q.title)}</h3><h4 class="reception-prompt">你会选哪一个？</h4>
    <div class="practice-options">${q.options.map((o,i) => `<button class="practice-option reception-reply ${answered && i===q.answer_index?'correct':answered && i===q.selected_index?'incorrect':''}"
      ${answered || practiceState.busy?'disabled':''} onclick="answerPractice(${i})"><span>${practiceEscape(o)}${answered && i===q.answer_index?'<em>推荐选择 ✓</em>':answered && i===q.selected_index?'<em>你的选择</em>':''}</span></button>`).join('')}</div>
    ${answered ? `<div class="practice-feedback ${celebrate?'reception-celebrate':''}" role="status"><h4>${q.correct?'✓ 答对了！':'再看看这题的思路'}</h4>
      ${q.correct && stats.current>=3?`<p class="reception-streak">🔥 连续答对 ${stats.current} 题</p>`:''}${milestone?`<p class="reception-milestone">✦ ${milestone}</p>`:''}${renderPracticeExplanation(q,s.cursor)}</div>
      <button class="practice-button practice-next" onclick="nextPractice()">下一题 →</button>${s.entry && s.cursor===0?`<p class="practice-hint">${s.mode==='daily'?'继续剩余9题，完成后结算积分':'继续剩余9题，完成本次练习'}</p>`:''}`:'<p class="practice-hint">先做选择，答完马上看解析。</p>'}
    <div class="practice-actions"><button class="practice-button secondary" onclick="leavePracticeSession()" ${practiceState.busy?'disabled':''}>稍后继续</button></div></div>`;
}
function practiceReceptionStats(session) {
  let current=0,longest=0;
  for (const q of session.questions) {
    if(q.selected_index===undefined)break;
    current=q.correct?current+1:0; longest=Math.max(longest,current);
  }
  return {current,longest};
}
function renderReceptionRoute(session) {
  const count=Math.max(0,Math.min(10,Number(session.answered_count)||0));
  return `<div class="reception-progress" role="progressbar" aria-label="问答闯关进度" aria-valuemin="0" aria-valuemax="10" aria-valuenow="${count}" aria-valuetext="已完成${count}题，共10题"><span style="width:${count*10}%"></span></div>`;
}
function renderPracticeExplanation(q,index=practiceState.session?.cursor) {
  return `<p>${practiceEscape(q.explanation)}</p><div class="reception-method-title"><h4>参考回答</h4><button class="reception-copy" onclick="copyPracticeReply(${Number(index)},this)">复制回答</button></div><blockquote>${practiceEscape(q.method)}</blockquote><button class="practice-coach-link" onclick="askPracticeCoach(${Number(index)})">追问AI教练 →</button>`;
}
function askPracticeCoach(index) {
  const q=practiceState.session?.questions[index];
  if(!q?.explanation)return;
  quickSend('aura',`请作为培训教练，基于这道题的既有解析回答我的追问。题目：${q.title}\n推荐选择：${q.options[q.answer_index]}\n解析：${q.explanation}\n参考回答：${q.method}\n请先简短解释这道题的判断方法，再问我还有哪里不明白。不要改变题目的推荐答案。`);
}
async function copyPracticeReply(index,button) {
  const q=practiceState.session?.questions[index];
  if(!q?.method)return;
  button.disabled=true;
  try {
    if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(q.method);
    else {
      const text=document.createElement('textarea'); text.value=q.method;
      text.style.position='fixed';text.style.opacity='0';document.body.appendChild(text);
      try {text.select();if(!document.execCommand('copy'))throw new Error('copy failed');}finally{text.remove();}
    }
    button.textContent='已复制 ✓';
  } catch { button.textContent='复制失败，请长按参考回答复制'; }
  finally {button.disabled=false;}
}
async function startPractice(mode, batchNo, stageId=0) {
  if (practiceState.busy) return;
  const previous = practiceState.createAttempt;
  const attempt = previous && previous.mode === mode && previous.batch_no === batchNo && previous.stage_id === stageId ? previous :
    { mode, stage_id: stageId, batch_no: batchNo, request_id: practiceRequestId() };
  practiceState.createAttempt = attempt;
  practiceState.busy = true; practiceNotice('正在准备关卡…');
  document.querySelectorAll('#practice-body button').forEach(btn => { btn.disabled = true; });
  try {
    practiceState.session = await practiceApi('/sessions', { method: 'POST', body: JSON.stringify(attempt) });
    practiceState.createAttempt = null; practiceNotice();
  } catch (error) { practiceNotice(error.message); }
  finally { practiceState.busy = false; renderPracticeTraining(); }
}
async function practiceAction(action, optionIndex) {
  if (practiceState.busy || !practiceState.session || practiceState.session.completed) return;
  const s = practiceState.session, q = s.questions[s.cursor];
  practiceState.busy = true; practiceNotice();
  document.querySelectorAll('#practice-body button').forEach(btn => { btn.disabled = true; });
  try {
    practiceState.session = await practiceApi(`/sessions/${s.id}/${action}`, { method: 'POST', body: JSON.stringify({
      request_id: practiceRequestId(), question_id: q.id, option_index: optionIndex,
    }) });
  } catch (error) {
    practiceNotice(error.message);
    // The server may have committed a response that never reached this device.
    try { practiceState.session = await practiceApi(`/sessions/${s.id}`); } catch { /* retry reads durable state */ }
  } finally {
    if(action==='answer' && q.selected_index===undefined && practiceState.session?.answered_count>s.answered_count) practiceState.receptionFlash=`${s.id}:${practiceState.session.answered_count}`;
    practiceState.busy = false; renderPracticeTraining();
    if(action==='answer' && practiceState.session?.answered_count>s.answered_count && !practiceState.session.completed) document.querySelector('.practice-feedback')?.scrollIntoView?.({block:'start',behavior:'smooth'});
    if (action === 'next' || practiceState.session?.completed) document.querySelector('.practice-scroll')?.scrollTo?.({ top: 0, behavior: 'smooth' });
  }
}
function answerPractice(index) { return practiceAction('answer', index); }
function nextPractice() { return practiceAction('next'); }
async function openPracticeRecord(id) {
  if (practiceState.busy) return;
  practiceState.busy = true;
  try { practiceState.session = await practiceApi(`/sessions/${id}`); }
  catch (error) { practiceNotice(error.message); return; }
  finally { practiceState.busy = false; }
  return practiceTab('training');
}
async function leavePracticeSession(home=false) {
  if (practiceState.busy) return;
  practiceState.session = null;
  practiceState.tab = 'training';
  if (state.currentView !== 'training') switchView('training');
  else await loadTrainingHub();
}

function practiceSessionLabel(session) {
  return session.stage_title ? `${session.stage_title} · ${session.mode==='daily'?'每日专题':'自由练习'}` : session.mode==='daily'?'每日闯关':'自由练习';
}
function practiceBatchLabel(session) {
  return session.mode==='free' && session.entry ? `随机第${session.batch_no}组` : `第${session.batch_no}关`;
}
function renderPracticeStage(stage, existing) {
  if(!stage)return '';
  const e=practiceEscape, other=existing && existing.stage_id!==stage.id;
  return `<div class="practice-card practice-stage-hero"><span class="practice-eyebrow">阶段主题 · ${stage.starts_on} 至 ${stage.ends_on}</span><h3>${e(stage.title)}</h3><p>${e(stage.description || '集中学习本阶段的知识与应用题。')}</p><div class="practice-hero-score"><b>${stage.question_count}</b> 道题 <i>·</i> <b>${stage.batch_count}</b> 关</div>
    <button class="practice-button" onclick="startPractice('${other?'free':'daily'}',${other?stage.daily.batch_no:'undefined'},${stage.id})">${other?'练习今日专题':existing ? existing.completed?'查看今日专题成绩':'继续今日专题':'开始今日专题'} →</button>
    <p class="practice-hint">${other?'今天已选择一局计分，此处可自由练习。':'专题与普通每日闯关共用每天100分，每天只选一局计分。'}</p></div>`;
}
function practiceEntryCard(entry) {
  const e=practiceEscape;
  const count=Math.max(0,Math.min(10,Number(entry.answered_count)||0));
  const theme=entry.stage_id ? entry.stage_title : '今日问答闯关';
  const title=entry.mode==='free' ? entry.action==='resume' ? `随机练习 · 已完成 ${count}/10 题` : '今日闯关已完成 · 随机10题'
    : entry.action==='resume' && count ? `${theme} · 已完成 ${count}/10 题` : theme;
  const action=entry.mode==='free' ? entry.action==='resume' ? '继续这组题' : '继续练习 · 随机10题'
    : entry.action==='resume' ? '继续闯关' : '开始今日闯关';
  return `<button class="practice-home-card practice-question-entry ${entry.stage_id?'practice-stage-home':''}" onclick="openPracticeEntry()" data-practice-entry-button><span class="practice-eyebrow">${e(title)}</span><strong>${e(entry.question_title)}</strong><span>该怎么回答？来挑战一下</span><span class="practice-entry-cta">${action} →</span>${entry.mode==='free'?'<small>本组不计分 · 今日计分上限100分</small>':''}</button>`;
}
function practiceHomeLink(entry) {
  const resume = entry.action === 'resume';
  const count = Math.max(0, Math.min(10, Number(entry.answered_count) || 0));
  const theme = entry.stage_id ? `${entry.kind === 'weekly' ? '本周主题' : '阶段专题'} · ${entry.stage_title}` : '今日问答闯关';
  const status = resume ? count ? `已完成 ${count} / 10 题` : '从第1题开始，答完看解析' : entry.mode === 'free' ? '今日计分已完成 · 接着学不计分' : '10道题 · 边选边学';
  const action = resume && count ? '继续上课' : entry.mode === 'free' ? '继续练习' : '进入课堂';
  return `<button class="training-home-card" onclick="switchView('training')">
    <span class="training-home-top"><strong>AI宝儿问答课堂</strong><span>${entry.mode === 'free' ? '随机10题 · 不计分' : '10题 · 最高100分'}</span></span>
    <span class="training-home-scene">${practiceEscape(theme)} · ${resume ? `第 ${Math.min(count + 1, 10)} 题` : entry.mode === 'free' ? '继续练习' : '今日推荐题'}</span>
    <strong class="training-home-question">${practiceEscape(entry.question_title || '今天来学哪一道题？')}</strong>
    <span class="training-home-bottom"><small>${practiceEscape(status)}</small><span class="training-home-action">${action} <span aria-hidden="true">→</span></span></span>
    ${resume && count ? `<span class="training-home-progress" role="progressbar" aria-label="今日训练进度" aria-valuemin="0" aria-valuemax="10" aria-valuenow="${count}"><span style="width:${count * 10}%"></span></span>` : ''}
  </button>`;
}
async function loadPracticePromotion() {
  const host=document.getElementById('practice-stage-home');
  if(!host)return;
  const generation=++practiceState.promotionGeneration;
  const token=state.sessionToken || state.token;
  if(!featureEnabled('practice') || !token) {host.innerHTML='';return;}
  try {
    const r=await fetchWithTimeout(`${API_BASE}/api/practice/entry`,{headers:authHeaders({})},8000);
    if(!r.ok)throw new Error('暂未开放');
    const data=await r.json();
    if(generation!==practiceState.promotionGeneration || token!==(state.sessionToken || state.token))return;
    practiceState.entryData=data.entry;
    host.innerHTML=data.entry ? practiceHomeLink(data.entry) : '';
    if(data.entry && state.currentView==='home')recordPracticeEntryImpression(data.entry,host);
  }catch {if(generation===practiceState.promotionGeneration){host.innerHTML='';practiceState.entryData=null;}}
}
async function openPracticeEntry() {
  if(practiceState.busy || !practiceState.entryData)return;
  const e=practiceState.entryData,signature=JSON.stringify([e.day,e.stage_id,e.question_id,e.session_id,e.replay_round]);
  if(practiceState.entryAttempt?.signature!==signature)practiceState.entryAttempt={signature,request_id:practiceRequestId()};
  practiceState.busy=true;
  document.querySelectorAll('[data-practice-entry-button]').forEach(b=>b.disabled=true);
  try {
    const session=await practiceApi('/sessions',{method:'POST',body:JSON.stringify({entry:true,request_id:practiceState.entryAttempt.request_id,entry_day:e.day,entry_stage_id:e.stage_id,entry_question_id:e.question_id})});
    practiceState.identity=state.sessionToken || state.token;practiceState.session=session;practiceState.tab='training';practiceState.entryAttempt=null;
    switchView('practice');
    practiceState.busy=false;await practiceTab('training');
  }catch(error){showToast(error.message,'error');await loadPracticePromotion();}
  finally{practiceState.busy=false;document.querySelectorAll('[data-practice-entry-button]').forEach(b=>b.disabled=false);}
}
async function startNextPracticeRound() {
  if(practiceState.busy)return;
  try {
    const data=await practiceApi('/entry');
    practiceState.entryData=data.entry;
    if(!data.entry)throw new Error('题目正在准备中');
    await openPracticeEntry();
  } catch(error) {showToast(error.message,'error');}
}
let practiceThemeLinkHandled=false;
async function handlePracticeThemeLink() {
  if(practiceThemeLinkHandled)return;
  const value=new URLSearchParams(window.location.search).get('practice_theme');
  if(!value)return;
  practiceThemeLinkHandled=true;practiceState.linkStage=Number(value);practiceState.linkLanding=true;
  switchView('training');
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden && state.currentView==='home')loadPracticePromotion();});
setInterval(()=>{if(!document.hidden && state.currentView==='home' && featureEnabled('practice'))loadPracticePromotion();},60000);

function recordPracticeEntryImpression(entry,element) {
  if(!element || document.hidden || document.getElementById('identity-gate')?.classList.contains('active'))return;
  const rect=element.getBoundingClientRect();
  if(rect.top<window.innerHeight && rect.bottom>0)practiceApi('/entry/impression',{method:'POST',body:JSON.stringify({day:entry.day,stage_id:entry.stage_id})}).catch(()=>{});
}
