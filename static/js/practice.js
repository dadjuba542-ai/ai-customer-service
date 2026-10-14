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
      host.innerHTML = `<p class="practice-hint">共 ${data.total} 局 · 第 ${data.page} 页</p>` +
        data.items.map(item => `<button class="practice-record" onclick="openPracticeRecord('${item.id}')">
          <strong>${practiceEscape(practiceSessionLabel(item))} · 第${item.batch_no}关</strong>
          <small>${practiceEscape(new Date(item.created_at).toLocaleString('zh-CN'))}</small>
          <small>${item.completed ? `答对 ${item.correct_count}/10 · +${item.points} 积分` : `继续答题 · 第 ${item.cursor + 1}/10 题`}</small></button>`).join('') +
        (!data.items.length ? '<div class="practice-card"><p>从今天的10道题开始吧。</p></div>' : '') +
        `<div class="practice-actions"><button class="practice-button secondary" ${data.page === 1 ? 'disabled' : ''} onclick="practiceRecordsPage(-1)">上一页</button>
        <button class="practice-button secondary" ${data.page * 20 >= data.total ? 'disabled' : ''} onclick="practiceRecordsPage(1)">下一页</button></div>`;
    } else {
      const data = await practiceApi('/scores');
      if (generation !== practiceState.generation) return;
      host.innerHTML = `<div class="practice-card"><span class="practice-eyebrow">本周一起进步</span><h3>${practiceEscape(data.team_name || '本团队')}周榜</h3>
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
      <h3>${stage?'每日闯关 · 常规练习':'每天10题，练会客户沟通'}</h3><p>把真实场景变成一次选择。选完看解析，再学一句可以直接用的回复。</p>
      <div class="practice-category-tags">${data.categories.map(c => `<span>${practiceEscape(c)}</span>`).join('')}</div>
      <div class="practice-hero-score"><b>10</b> 道题 <i>·</i> 最高 <b>100</b> 积分</div>
      <button class="practice-button" onclick="startPractice('${ordinaryOther?'free':'daily'}',${ordinaryOther?today.batch_no:'undefined'},0)">${ordinaryOther?'自由练习常规题':existing ? existing.completed ? '查看今日成绩' : '继续今日闯关' : '开始今日闯关'} <span aria-hidden="true">→</span></button>
      <p class="practice-hint">每日首次作答计分，完成一局后入账。答题后即可学习解析。</p></div>` : '<div class="practice-card"><p>每日关卡正在准备中。</p></div>') +
      `<${stage?'details':'div'} class="practice-card practice-base-levels">${stage?'<summary>常规题库 · 自由练习</summary>':'<h3>自由练习</h3>'}<p>四类场景穿插练习，每关10题。可反复巩固，保留成绩和解析。</p><div class="practice-levels">
      ${data.batches.map(b => `<button onclick="startPractice('free',${b.batch_no})"><strong>第 ${String(b.batch_no).padStart(2, '0')} 关</strong><span>10道情景题</span></button>`).join('')}</div>
      ${data.batches.length ? '' : '<p>题目正在整理中。</p>'}</${stage?'details':'div'}>`;
    if(practiceState.linkLanding && data.entry)recordPracticeEntryImpression(data.entry,host.querySelector('[data-practice-entry-button]'));
    return;
  }
  const stats = practiceReceptionStats(s);
  const celebrate = practiceState.receptionFlash === `${s.id}:${s.answered_count}`;
  practiceState.receptionFlash = null;
  if (s.completed) {
    const review = s.questions.map((q, index) => ({q,index})).sort((a,b) => Number(a.q.correct)-Number(b.q.correct));
    const wrong = review.filter(item => !item.q.correct).length;
    const badge = s.correct_count===10 ? '接待达人' : s.correct_count>=7 ? '沟通能手' : '练习完成';
    host.innerHTML = `<div class="practice-card practice-result reception-report ${celebrate?'reception-celebrate':''}"><span class="practice-eyebrow">${practiceEscape(practiceSessionLabel(s))} · 第${s.batch_no}关</span>
      <div class="reception-trophy" aria-hidden="true">✦</div><h3>今日接待完成</h3><span class="reception-badge">本局徽章 · ${badge}</span>
      <div class="reception-report-stats"><div><b>${s.correct_count}<small>/10</small></b><span>判断准确</span></div><div><b>${stats.longest}<small>位</small></b><span>最长连对</span></div><div><b>${s.points}<small>分</small></b><span>本局获得</span></div></div>
      <p class="practice-hint">${practiceEscape(s.point_reason)}</p>
      ${renderReceptionRoute(s)}
      <div class="practice-actions"><button class="practice-button" onclick="startPractice('free',${s.batch_no},${s.stage_id || 0})">再挑战一次</button>
      <button class="practice-button secondary" onclick="leavePracticeSession(true)">返回首页</button></div></div>
      <div class="practice-card"><h3>接待复盘 · ${wrong ? `${wrong}个场景值得再看` : '10个场景全部接住'}</h3>
      ${review.map(({q,index},position) => `<details class="practice-review" ${position===0?'open':''}><summary>${q.correct ? '✓' : '↗'} 客户 ${index+1} · ${practiceEscape(q.title)}</summary>
      <p>我的选择：${practiceEscape(q.options[q.selected_index])}</p><p><strong>推荐选择：</strong>${practiceEscape(q.options[q.answer_index])}</p>${renderPracticeExplanation(q,index)}</details>`).join('')}</div>`;
    return;
  }
  const q = s.questions[s.cursor], answered = q.selected_index !== undefined;
  const milestone = s.answered_count===3 ? '已接待3位客户，继续前进！' : s.answered_count===6 ? '过半了，再接待4位客户！' : '';
  host.innerHTML = `<div class="practice-card reception-route-card"><div class="practice-question-meta"><span class="practice-category">客户接待挑战</span><span>已接待 ${s.answered_count} / 10 位客户</span></div>
    <p class="practice-hint">${practiceEscape(practiceSessionLabel(s))} · 第${s.batch_no}关</p>${renderReceptionRoute(s)}</div>
    <div class="practice-card reception-conversation"><div class="reception-customer"><span class="reception-avatar" aria-hidden="true">☺</span><div><strong>客户 ${s.cursor+1} 发来消息</strong><span>${practiceEscape(q.category)} · 沟通场景</span></div></div>
    <h3 class="practice-question-title reception-message">${practiceEscape(q.title)}</h3><h4 class="reception-prompt">你准备怎么接？</h4>
    <div class="practice-options">${q.options.map((o,i) => `<button class="practice-option reception-reply ${answered && i===q.answer_index?'correct':answered && i===q.selected_index?'incorrect':''}"
      ${answered || practiceState.busy?'disabled':''} onclick="answerPractice(${i})"><span>${practiceEscape(o)}${answered && i===q.answer_index?'<em>推荐选择 ✓</em>':answered && i===q.selected_index?'<em>你的选择</em>':''}</span></button>`).join('')}</div>
    ${answered ? `<div class="practice-feedback ${celebrate?'reception-celebrate':''}" role="status"><h4>${q.correct?'✓ 判断准确！':'这个场景，可以换一种接法'}</h4>
      ${q.correct && stats.current>=3?`<p class="reception-streak">🔥 连续接住${stats.current}个客户问题</p>`:''}${milestone?`<p class="reception-milestone">✦ ${milestone}</p>`:''}${renderPracticeExplanation(q,s.cursor)}</div>
      <button class="practice-button practice-next" onclick="nextPractice()">接待下一位客户 →</button>${s.entry && s.cursor===0?`<p class="practice-hint">${s.mode==='daily'?'继续剩余9题，完成后结算积分':'继续剩余9题，完成本次接待'}</p>`:''}`:'<p class="practice-hint">选择你认为最合适的回复，看看推荐接法。</p>'}
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
  return `<div class="reception-progress" role="progressbar" aria-label="客户接待进度" aria-valuemin="0" aria-valuemax="10" aria-valuenow="${count}" aria-valuetext="已接待${count}位，共10位客户"><span style="width:${count*10}%"></span></div>`;
}
function renderPracticeExplanation(q,index=practiceState.session?.cursor) {
  return `<p>${practiceEscape(q.explanation)}</p><div class="reception-method-title"><h4>下一句可以这样说</h4><button class="reception-copy" onclick="copyPracticeReply(${Number(index)},this)">复制回复</button></div><blockquote>${practiceEscape(q.method)}</blockquote>`;
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
  } catch { button.textContent='复制失败，请长按回复复制'; }
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
  if(home) { switchView('home'); return; }
  await loadPracticePage();
}

function practiceSessionLabel(session) {
  return session.stage_title ? `${session.stage_title} · ${session.mode==='daily'?'每日专题':'自由练习'}` : session.mode==='daily'?'每日闯关':'自由练习';
}
function renderPracticeStage(stage, existing) {
  if(!stage)return '';
  const e=practiceEscape, other=existing && existing.stage_id!==stage.id;
  return `<div class="practice-card practice-stage-hero"><span class="practice-eyebrow">阶段主题 · ${stage.starts_on} 至 ${stage.ends_on}</span><h3>${e(stage.title)}</h3><p>${e(stage.description || '集中练习本阶段的客户沟通场景。')}</p><div class="practice-hero-score"><b>${stage.question_count}</b> 道题 <i>·</i> <b>${stage.batch_count}</b> 关</div>
    <button class="practice-button" onclick="startPractice('${other?'free':'daily'}',${other?stage.daily.batch_no:'undefined'},${stage.id})">${other?'练习今日专题':existing ? existing.completed?'查看今日专题成绩':'继续今日专题':'开始今日专题'} →</button>
    <p class="practice-hint">${other?'今天已选择一局计分，此处可自由练习。':'专题与普通每日闯关共用每天100分，每天只选一局计分。'}</p>
    <details class="practice-stage-levels"><summary>查看全部 ${stage.batch_count} 关 · 自由练习</summary><div class="practice-levels">${stage.batches.map(b=>`<button onclick="startPractice('free',${b.batch_no},${stage.id})"><strong>第${b.batch_no}关</strong><span>10道专题题</span></button>`).join('')}</div></details></div>`;
}
function practiceEntryCard(entry) {
  const e=practiceEscape;
  const title=entry.action==='resume' ? (entry.stage_title || '今日练习') : entry.kind==='weekly' ? `本周：${entry.stage_title}` : entry.stage_id ? entry.stage_title : '今日客户问题';
  return `<button class="practice-home-card practice-question-entry ${entry.stage_id?'practice-stage-home':''}" onclick="openPracticeEntry()" data-practice-entry-button><span class="practice-eyebrow">${e(title)} · ${e(entry.label)}</span><strong>${e(entry.question_title)}</strong><span>你会怎么回应？</span><span class="practice-entry-cta">${entry.action==='resume'?'继续今天的练习':entry.mode==='free'?'再练一下，看看解析':'选一下，看看你的判断'} →</span>${entry.mode==='free'?'<small>今日计分局已完成，本次为自由练习</small>':''}</button>`;
}
async function loadPracticePromotion() {
  const host=document.getElementById('practice-stage-home'),daily=document.getElementById('practice-daily-home');
  if(!host || !daily)return;
  const generation=++practiceState.promotionGeneration;
  const token=state.sessionToken || state.token;
  if(!featureEnabled('practice') || !token) {host.innerHTML='';daily.classList.remove('compact');return;}
  try {
    const r=await fetchWithTimeout(`${API_BASE}/api/practice/entry`,{headers:authHeaders({})},8000);
    if(!r.ok)throw new Error('暂未开放');
    const data=await r.json();
    if(generation!==practiceState.promotionGeneration || token!==(state.sessionToken || state.token))return;
    practiceState.entryData=data.entry;
    daily.classList.toggle('compact',Boolean(data.entry));
    host.innerHTML=data.entry ? practiceEntryCard(data.entry) : '';
    if(data.entry && state.currentView==='home')recordPracticeEntryImpression(data.entry,host);
  }catch {if(generation===practiceState.promotionGeneration){host.innerHTML='';daily.classList.remove('compact');practiceState.entryData=null;}}
}
async function openPracticeEntry() {
  if(practiceState.busy || !practiceState.entryData)return;
  const e=practiceState.entryData,signature=JSON.stringify([e.day,e.stage_id,e.question_id,e.session_id]);
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
let practiceThemeLinkHandled=false;
async function handlePracticeThemeLink() {
  if(practiceThemeLinkHandled)return;
  const value=new URLSearchParams(window.location.search).get('practice_theme');
  if(!value)return;
  practiceThemeLinkHandled=true;practiceState.linkStage=Number(value);practiceState.linkLanding=true;
  switchView('practice');
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden && state.currentView==='home')loadPracticePromotion();});
setInterval(()=>{if(!document.hidden && state.currentView==='home' && featureEnabled('practice'))loadPracticePromotion();},60000);

function recordPracticeEntryImpression(entry,element) {
  if(!element || document.hidden || document.getElementById('identity-gate')?.classList.contains('active'))return;
  const rect=element.getBoundingClientRect();
  if(rect.top<window.innerHeight && rect.bottom>0)practiceApi('/entry/impression',{method:'POST',body:JSON.stringify({day:entry.day,stage_id:entry.stage_id})}).catch(()=>{});
}
