/* A reviewed, standalone learning outline. Product knowledge is entered here, not read from Products. */
let adminPracticePathData=null;

async function retryAdminPracticePath(){
  const host=document.getElementById('practice-path-manager');
  host.textContent='正在加载学习主线…';
  try{adminPracticePathData=await adminPracticeApi('/learning/path');renderAdminPracticePath();}
  catch(error){host.innerHTML=`<div class="admin-card">${practiceAdminEscape(error.message)} <button class="btn btn-secondary btn-sm" onclick="retryAdminPracticePath()">重试主线</button></div>`;}
}

function renderAdminPracticePath(){
  const host=document.getElementById('practice-path-manager'),data=adminPracticePathData;
  if(!host||!data)return;
  const open=host.querySelector('details')?.open??true,e=practiceAdminEscape;
  if(!data.settings){
    host.innerHTML=`<section class="admin-card path-admin"><h3>建立学习主线</h3><p class="hint">单独输入培训产品名称，再为产品知识与沟通方法单元填写知识卡和题目。不会从产品板块读取资料。</p><div class="field"><label for="path-product-name">培训产品名称</label><input id="path-product-name" maxlength="100" placeholder="例如：益生菌"></div><button class="btn btn-primary" onclick="initializeAdminPracticePath(this)">建立7单元主线</button></section>`;
    return;
  }
  const pending=data.suggestions||[];
  host.innerHTML=`<details class="admin-card path-admin" ${open?'open':''}><summary>进阶学习主线 <small>${e(data.settings.product_name)} · ${data.settings.published&&data.ready?'已发布':'待发布'}</small></summary>
    <p class="hint">产品知识卡和产品问题在这里单独输入。主线按识别事实 → 理解判断 → 场景应用 → 组织回答 → 综合应对推进，每单元1张卡＋3道已审核题；完成即可继续下一单元。</p>
    <div class="path-admin-stats"><span>7个单元</span>${Object.keys(data.levels).map(level=>`<span>${e(data.levels[level])}：待补${data.level_gaps[level].remaining_slots}题 · 可选${data.level_gaps[level].available_questions}题</span>`).join('')}<button type="button" onclick="showUnclassifiedQuestions()">${data.unclassified_count}道母题待编排 →</button><span>${pending.length}条AI建议待审核</span></div>
    ${pending.length?`<section class="path-suggestions"><h4>AI分级建议 · 待审核</h4>${pending.map(item=>`<div class="path-suggestion"><strong>#${item.question_id} ${e(item.question_title)}</strong><small>建议放入「${e(item.unit_title)}」· ${e(data.levels[item.difficulty_level])}</small><p>学习目标：${e(item.learning_objective)}</p>${item.rationale?`<p>理由：${e(item.rationale)}</p>`:''}<div><button class="btn btn-primary btn-sm" onclick="reviewAdminPathSuggestion(${item.id},true,this)">确认分级</button><button class="btn btn-secondary btn-sm" onclick="reviewAdminPathSuggestion(${item.id},false,this)">不采用</button></div></div>`).join('')}</section>`:''}
    <div class="path-admin-units">${data.units.map(unit=>renderAdminPathUnit(unit,data)).join('')}</div>
    <div class="path-admin-actions"><button class="btn btn-primary" onclick="publishAdminPracticePath(this)">检查并发布学习主线</button><small>修改已发布单元或题目后，请重新检查并发布。</small></div>
  </details>`;
}

function renderAdminPathUnit(unit,data){
  const e=practiceAdminEscape,ids=unit.question_ids||[];
  const candidates=data.questions.filter(q=>q.learning_objective&&q.difficulty_level===unit.level&&(!q.assigned_unit_id||q.assigned_unit_id===unit.id));
  return `<section class="path-admin-unit" id="path-admin-unit-${unit.id}"><div class="bank-panel-heading"><div><span class="bank-eyebrow">第${unit.position}单元 · ${e(data.levels[unit.level])} · ${unit.kind==='product'?'产品知识':'沟通方法'}</span><h3>${e(unit.title)}</h3></div><span class="hint">${ids.length}/3题</span></div>
    <div class="field"><label for="path-title-${unit.id}">单元标题</label><input id="path-title-${unit.id}" maxlength="100" value="${e(unit.title)}"></div>
    <div class="field"><label for="path-body-${unit.id}">知识卡正文</label><textarea id="path-body-${unit.id}" maxlength="800" rows="4" placeholder="用约1分钟讲清这个知识点">${e(unit.body)}</textarea></div>
    <div class="path-admin-picks"><strong>本单元3道题</strong><p class="hint">先在题库中输入或由本地AI通过MCP创建题目，审核学习目标与难度后在这里选入。</p>
      <button class="btn btn-secondary btn-sm" onclick="newAdminPathQuestion(${unit.id},${unit.level})">＋ 单独输入${unit.kind==='product'?'产品':'沟通'}问题</button>
      ${[0,1,2].map(position=>`<div class="field"><label>第${position+1}题</label><select id="path-pick-${unit.id}-${position}"><option value="">选择已审核题目</option>${candidates.map(q=>`<option value="${q.id}" ${ids[position]===q.id?'selected':''}>#${q.id} · ${e(q.title.slice(0,55))} · ${e(data.levels[q.difficulty_level])}${q.suggested_unit_id===unit.id?' ★':''}</option>`).join('')}</select><button class="btn btn-secondary btn-sm" onclick="editAdminPathQuestion(Number(document.getElementById('path-pick-${unit.id}-${position}').value))">编辑题目</button></div>`).join('')}</div>
    <button class="btn btn-secondary btn-sm" onclick="saveAdminPathUnit(${unit.id},this)">保存单元</button></section>`;
}

async function initializeAdminPracticePath(button){
  button.disabled=true;
  try{adminPracticePathData=await adminPracticeApi('/learning/path/initialize',{method:'POST',body:JSON.stringify({product_name:document.getElementById('path-product-name').value})});renderAdminPracticePath();showToast('学习主线已建立，请填写知识卡与题目','success');}
  catch(e){showToast(e.message,'error');button.disabled=false;}
}
async function reviewAdminPathSuggestion(id,accepted,button){
  button.disabled=true;
  try{await adminPracticeApi(`/learning/path/suggestions/${id}`,{method:'POST',body:JSON.stringify({accepted})});await retryAdminPracticePath();await loadAdminPractice();showToast(accepted?'已确认分级，可选入单元':'建议已移出审核队列','success');}
  catch(e){showToast(e.message,'error');button.disabled=false;}
}
async function saveAdminPathUnit(id,button){
  button.disabled=true;
  try{const question_ids=[0,1,2].map(i=>Number(document.getElementById(`path-pick-${id}-${i}`).value));
    await adminPracticeApi(`/learning/path/units/${id}`,{method:'PUT',body:JSON.stringify({title:document.getElementById(`path-title-${id}`).value,body:document.getElementById(`path-body-${id}`).value,question_ids})});
    await retryAdminPracticePath();showToast('单元已保存','success');}
  catch(e){showToast(e.message,'error');button.disabled=false;}
}
async function publishAdminPracticePath(button){
  button.disabled=true;
  try{await adminPracticeApi('/learning/path/publish',{method:'POST',body:'{}'});await retryAdminPracticePath();showToast('学习主线已发布','success');}
  catch(e){showToast(e.message,'error');button.disabled=false;}
}
async function editAdminPathQuestion(id){
  if(!id){showToast('请先选择一道题','info');return;}
  practiceAdminState.stageId=0;
  await loadAdminPractice();editAdminPracticeQuestion(id);
  document.getElementById('practice-question-editor').scrollIntoView({block:'start',behavior:'smooth'});
}
async function newAdminPathQuestion(unitId,level){
  practiceAdminState.stageId=0;
  await loadAdminPractice();beginPracticeNewQuestion();
  document.getElementById('practice-q-difficulty').value=String(level);
  document.getElementById('practice-q-path-unit').value=String(unitId);
  practiceEditorChanged();
  document.getElementById('practice-question-editor').scrollIntoView({block:'start',behavior:'smooth'});
}
async function showUnclassifiedQuestions(){
  practiceAdminState.stageId=0;practiceAdminState.status='unclassified';
  await loadAdminPractice();
  document.querySelector('.bank-library')?.scrollIntoView({block:'start',behavior:'smooth'});
}
