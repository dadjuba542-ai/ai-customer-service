/* Product lessons and due review never write to the weekly score ledger. */
const learningState = { home:null, product:null, course:null, session:null, factSeen:false, busy:false, attempt:null, identity:null };
const learningEscape = practiceEscape;
function learningNotice(text='') { const el=document.getElementById('learning-notice'); if(el)el.textContent=text; }
function learningApi(path,options={}) { return practiceApi(`/learning${path}`,options); }
function learningIdentity() {
  const identity=state.sessionToken || state.token;
  if(learningState.identity!==identity)Object.assign(learningState,{home:null,product:null,course:null,session:null,factSeen:false,attempt:null,identity});
}
async function loadLearningPage() {
  if(!featureEnabled('practice_learning'))return;
  learningIdentity();
  learningNotice('正在加载课程…');
  try {
    if(learningState.session)learningState.session=await learningApi(`/sessions/${learningState.session.id}`);
    if(learningState.product)learningState.course=await learningApi(`/products/${learningState.product}`);
    learningState.home=await learningApi('/home');
    learningNotice();renderLearningPage();
  }catch(e){learningNotice(e.message);document.getElementById('learning-body').innerHTML='<button class="practice-button" onclick="loadLearningPage()">重试</button>';}
}
function renderLearningPage() {
  const host=document.getElementById('learning-body'),h=learningState.home;
  if(!host||!h)return;
  if(learningState.session)return renderLearningSession();
  if(learningState.course){
    const c=learningState.course;
    host.innerHTML=`<button class="learning-back" onclick="leaveLearningCourse()">← 问答课堂</button><div class="learning-hero"><span>产品知识 · ${learningEscape(c.product.category)}</span><h2>${learningEscape(c.product.name)}</h2><p>每单元约1分钟资料卡＋3道题。完成一个单元，点亮下一个节点。</p><strong>${c.completed_units}/4 已完成</strong></div>
      <div class="learning-units">${c.units.map(u=>`<button class="learning-unit ${u.completed?'done':''}" ${u.locked?'disabled':''} onclick="startLearningUnit(${u.unit_no})"><span class="learning-unit-node">${u.completed?'✓':u.locked?'·':u.unit_no}</span><span><strong>${learningEscape(u.title)}</strong><small>${learningEscape(u.fact_title || '内容准备中')}</small></span><em>${u.completed?'已点亮':u.locked?'待解锁':'开始 →'}</em></button>`).join('')}</div>`;
    return;
  }
  if(state.currentView==='learning')switchView('training');
}
async function openLearningProduct(productId) {
  if(!featureEnabled('practice_learning'))return;
  if(!productId){switchView('training');return;}
  learningIdentity();learningState.product=productId;learningState.course=null;learningState.session=null;learningState.factSeen=false;
  if(state.currentView!=='learning'){switchView('learning');return;}
  await loadLearningPage();
}
function leaveLearningCourse(){learningState.course=null;learningState.product=null;switchView('training');}
async function resumeLearning(id){
  try{learningState.session=await learningApi(`/sessions/${id}`);learningState.product=learningState.session.product_id;learningState.course=null;learningState.factSeen=learningState.session.answered_count>0;switchView('learning');renderLearningPage();}
  catch(e){trainingHubNotice(e.message);}
}
async function createLearningSession(kind,productId=null,unitNo=null){
  if(learningState.busy)return;
  const key=JSON.stringify([kind,productId,unitNo]);
  if(learningState.attempt?.key!==key)learningState.attempt={key,request_id:practiceRequestId()};
  learningState.busy=true;learningNotice('正在准备短课…');
  try{learningState.session=await learningApi('/sessions',{method:'POST',body:JSON.stringify({request_id:learningState.attempt.request_id,kind,product_id:productId,unit_no:unitNo})});learningState.attempt=null;learningState.factSeen=false;learningNotice();renderLearningPage();return learningState.session;}
  catch(e){learningNotice(e.message);return null;}
  finally{learningState.busy=false;}
}
function startLearningUnit(unitNo){return createLearningSession('unit',learningState.product,unitNo);}
async function openLearningReview(){
  if(learningState.busy || !featureEnabled('practice_learning'))return;
  learningIdentity();trainingHubNotice('正在读取待复习题…');
  try{
    const home=await learningApi('/home');
    learningState.home=home;trainingHubNotice();
    if(home.resume?.kind==='review')return resumeLearning(home.resume.id);
    if(!home.due_count){trainingHubNotice('今天没有到期的错题，明天再来看看。');return;}
    learningState.product=null;learningState.course=null;learningState.session=null;
    const session=await createLearningSession('review');
    if(session)switchView('learning');
    else trainingHubNotice(document.getElementById('learning-notice')?.textContent || '复习暂时无法开始，请重试。');
  }catch(e){trainingHubNotice(e.message);}
}
function renderLearningSession(){
  const s=learningState.session,host=document.getElementById('learning-body');
  if(s.completed){
    host.innerHTML=`<div class="learning-complete"><div class="learning-complete-badge">✦</div><span>完成学习 · 点亮一个节点</span><h2>${s.kind==='unit'?'单元完成！':'复习完成！'}</h2><p>答对 ${s.correct_count}/${s.total_questions} 题。知识点会按复习节奏再次出现。</p><button class="practice-button" onclick="finishLearningSession()">${s.kind==='unit'?'返回课程':'返回学习路径'} →</button></div>`;
    return;
  }
  if(s.kind==='unit' && s.fact && !learningState.factSeen){
    host.innerHTML=`<div class="learning-fact"><span class="learning-eyebrow">先学一张事实卡 · 约1分钟</span><h2>${learningEscape(s.fact.title)}</h2><p>${learningEscape(s.fact.body).replace(/\n/g,'<br>')}</p>${s.fact.source_url?`<a href="${learningEscape(s.fact.source_url)}" target="_blank" rel="noopener noreferrer">查看素材库来源 ↗</a>`:''}<small>资料版本 v${s.fact.version}</small><button class="practice-button" onclick="learningState.factSeen=true;renderLearningPage()">我了解了，开始3题 →</button></div>`;return;
  }
  const q=s.questions[s.cursor],answered=q.selected_index!==undefined;
  host.innerHTML=`<button class="learning-back" onclick="leaveLearningSession()">← 保存退出</button><div class="learning-progress"><span>${s.kind==='unit'?'产品小单元':'错题复习'} · ${s.cursor+1}/${s.total_questions}</span><div class="reception-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${s.total_questions}" aria-valuenow="${s.answered_count}"><span style="width:${s.answered_count/s.total_questions*100}%"></span></div></div>
    <div class="learning-question ${q.kind==='application'?'application':''}"><span class="learning-eyebrow">${q.kind==='knowledge'?'记住这个知识点':q.kind==='review'?'再想一想':'应用练习'}</span><h2>${learningEscape(q.title)}</h2><div class="practice-options">${q.options.map((option,i)=>`<button class="practice-option ${answered&&i===q.answer_index?'correct':answered&&i===q.selected_index?'incorrect':''}" ${answered||learningState.busy?'disabled':''} onclick="answerLearning(${i})">${learningEscape(option)}</button>`).join('')}</div>
    ${answered?`<div class="practice-feedback"><h4>${q.correct?'✓ 回答准确':'再记住这个处理方法'}</h4><p>${learningEscape(q.explanation)}</p><blockquote>${learningEscape(q.method)}</blockquote><button class="practice-coach-link" onclick="askLearningCoach()">追问AI教练 →</button></div><button class="practice-button" onclick="nextLearning()">下一题 →</button>`:''}</div>`;
}
async function learningAction(action,optionIndex){
  if(learningState.busy||!learningState.session)return;
  const s=learningState.session,q=s.questions[s.cursor];learningState.busy=true;
  try{learningState.session=await learningApi(`/sessions/${s.id}/${action}`,{method:'POST',body:JSON.stringify({request_id:practiceRequestId(),question_id:q.id,option_index:optionIndex})});learningNotice();}
  catch(e){learningNotice(e.message);try{learningState.session=await learningApi(`/sessions/${s.id}`);}catch{}}
  finally{learningState.busy=false;renderLearningPage();}
}
function answerLearning(index){return learningAction('answer',index);}
function nextLearning(){return learningAction('next');}
function askLearningCoach(){
  const s=learningState.session,q=s?.questions[s.cursor];if(!q?.explanation)return;
  quickSend('aura',`请作为产品学习教练，依据已发布的事实卡和题目解析简短回答，不改变推荐答案。\n事实卡：${s.fact?.body||'本题没有产品事实卡'}\n题目：${q.title}\n推荐选择：${q.options[q.answer_index]}\n解析：${q.explanation}\n参考回复：${q.method}\n我想继续理解这道题。`);
}
async function leaveLearningSession(){
  const kind=learningState.session?.kind;
  learningState.session=null;learningState.factSeen=false;
  if(kind==='unit' && learningState.product)await loadLearningPage();
  else switchView('training');
}
async function finishLearningSession(){return leaveLearningSession();}
