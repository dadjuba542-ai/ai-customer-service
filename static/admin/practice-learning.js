let adminPracticeLearningData=null;
let adminLearningProductId=0;
function renderAdminPracticeLearning(){
  const host=document.getElementById('practice-learning-manager'),data=adminPracticeLearningData;if(!host||!data)return;
  const wasOpen=host.querySelector('details')?.open||false;
  if(!adminLearningProductId && data.products.length)adminLearningProductId=data.products[0].id;
  const product=data.products.find(p=>p.id===adminLearningProductId),e=practiceAdminEscape;
  host.innerHTML=`<details class="admin-card learning-admin" ${wasOpen?'open':''}><summary>产品课程 · 事实卡与三题短课 <small>${data.products.filter(p=>p.published).length} 款已发布</small></summary>
    <p class="hint">从现有产品资料提炼每单元一个知识点，附素材库来源。每单元安排2道资料理解题和1道客户应用题，四单元完整后发布。修改事实卡或题目后须重新检查并发布。</p>
    <div class="admin-row"><div class="field"><label for="learning-admin-product">当前产品</label><select id="learning-admin-product" onchange="adminLearningProductId=Number(this.value);renderAdminPracticeLearning()">${data.products.map(p=>`<option value="${p.id}" ${p.id===adminLearningProductId?'selected':''}>${e(p.name)}${p.published?' · 已发布':''}</option>`).join('')}</select></div></div>
    ${product?`<div class="learning-admin-grid">${data.unit_titles.map((title,i)=>adminLearningUnit(product.id,i+1,title)).join('')}</div><div class="learning-admin-actions"><span>${product.published?'● 已发布，学员可以学习':'○ 草稿，学员暂不可见'}</span><button class="btn btn-primary" onclick="publishAdminLearning(${product.id},this)">检查并发布四单元</button></div>`:'<p class="hint">先在产品管理中创建产品。</p>'}
    </details>`;
}
function adminLearningUnit(productId,unitNo,title){
  const data=adminPracticeLearningData,e=practiceAdminEscape;
  const fact=data.facts.find(f=>f.product_id===productId&&f.unit_no===unitNo);
  const picks=data.assignments.filter(a=>a.product_id===productId&&a.unit_no===unitNo).sort((a,b)=>a.position-b.position);
  const questions=data.questions.filter(q=>q.product_id===productId&&q.fact_id===fact?.id);
  return `<section class="learning-admin-unit" id="learning-admin-unit-${unitNo}"><div class="bank-panel-heading"><div><span class="bank-eyebrow">第${unitNo}单元 · ${fact?.status==='published'?'已发布':'草稿'}</span><h3>${e(title)}</h3></div><span class="hint">${fact?'v'+fact.version:'未填写'}</span></div>
    <div class="field"><label>知识点标题</label><input id="learning-fact-title-${unitNo}" maxlength="100" value="${e(fact?.title||'')}" placeholder="只讲清一个知识点"></div>
    <div class="field"><label>事实卡正文</label><textarea id="learning-fact-body-${unitNo}" maxlength="800" rows="4" placeholder="约1分钟可读完的产品事实">${e(fact?.body||'')}</textarea></div>
    <div class="field"><label>素材库来源链接</label><input id="learning-fact-source-${unitNo}" type="url" maxlength="1000" value="${e(fact?.source_url||'')}" placeholder="https://…"></div>
    <button class="btn btn-secondary btn-sm" onclick="saveAdminLearningFact(${productId},${unitNo},this)">保存事实卡</button>
    <div class="learning-admin-picks"><strong>本单元3道题</strong><p class="hint">选2道资料理解题和1道客户应用题。新增时会自动关联当前产品与事实卡。</p>
    <button class="btn btn-secondary btn-sm" onclick="adminPracticeNewCourseQuestion(${productId},${unitNo})" ${fact?'':'disabled'}>＋ 为本单元新增题目</button>
    ${[0,1,2].map(position=>`<div class="field"><label>${position<2?'资料理解题 '+(position+1):'客户应用题'}</label><select id="learning-pick-${unitNo}-${position}"><option value="">选择题目</option>${questions.map(q=>`<option value="${q.id}" ${picks.find(a=>a.position===position)?.question_id===q.id?'selected':''}>#${q.id} · ${e(q.title.slice(0,60))}</option>`).join('')}</select><button class="btn btn-secondary btn-sm" onclick="adminPracticeEditCourseQuestion(Number(document.getElementById('learning-pick-${unitNo}-${position}').value),${productId},${unitNo})">编辑选中题目</button></div>`).join('')}
    <button class="btn btn-secondary btn-sm" onclick="saveAdminLearningUnit(${productId},${unitNo},this)" ${fact?'':'disabled'}>保存本单元题目</button></div></section>`;
}
async function adminPracticeNewCourseQuestion(productId,unitNo){
  const fact=adminPracticeLearningData?.facts.find(item=>item.product_id===productId&&item.unit_no===unitNo);
  if(!fact || practiceAdminState.busy)return;
  practiceAdminState.stageId=0;
  practiceAdminState.courseReturn={productId,unitNo};
  await loadAdminPractice();
  if(!adminPracticeData || !adminPracticeLearningData){practiceAdminState.courseReturn=null;return;}
  editAdminPracticeQuestion();
  document.getElementById('practice-q-product').value=String(productId);
  practiceProductChanged();
  document.getElementById('practice-q-fact').value=String(fact.id);
  document.getElementById('practice-q-skill').value='product';
  practiceEditorChanged();
  document.getElementById('practice-question-editor').scrollIntoView({block:'start',behavior:'smooth'});
}
async function adminPracticeEditCourseQuestion(questionId,productId,unitNo){
  if(!questionId){showToast('请先选择一道题','info');return;}
  if(practiceAdminState.busy)return;
  practiceAdminState.stageId=0;
  practiceAdminState.courseReturn={productId,unitNo};
  await loadAdminPractice();
  if(!adminPracticeData?.questions.some(q=>q.id===questionId)){practiceAdminState.courseReturn=null;showToast('题目未找到，请刷新后重试','error');return;}
  editAdminPracticeQuestion(questionId);
  document.getElementById('practice-question-editor').scrollIntoView({block:'start',behavior:'smooth'});
}
async function saveAdminLearningFact(productId,unitNo,button){
  button.disabled=true;
  try{const result=await adminPracticeApi(`/learning/products/${productId}/facts/${unitNo}`,{method:'PUT',body:JSON.stringify({title:document.getElementById(`learning-fact-title-${unitNo}`).value,body:document.getElementById(`learning-fact-body-${unitNo}`).value,source_url:document.getElementById(`learning-fact-source-${unitNo}`).value})});
    adminPracticeLearningData=await adminPracticeApi('/learning');renderAdminPracticeLearning();
    showToast(result.needs_review?`事实卡已更新，请检查关联的${result.related_questions.length}道题答案与解析`:'事实卡已保存','success');
  }catch(e){showToast(e.message,'error');button.disabled=false;}
}
async function saveAdminLearningUnit(productId,unitNo,button){
  button.disabled=true;
  try{const question_ids=[0,1,2].map(i=>Number(document.getElementById(`learning-pick-${unitNo}-${i}`).value));
    await adminPracticeApi(`/learning/products/${productId}/units/${unitNo}`,{method:'PUT',body:JSON.stringify({question_ids})});
    adminPracticeLearningData=await adminPracticeApi('/learning');renderAdminPracticeLearning();showToast('本单元题目已保存','success');
  }catch(e){showToast(e.message,'error');button.disabled=false;}
}
async function publishAdminLearning(productId,button){
  button.disabled=true;
  try{await adminPracticeApi(`/learning/products/${productId}/publish`,{method:'POST',body:'{}'});adminPracticeLearningData=await adminPracticeApi('/learning');renderAdminPracticeLearning();showToast('产品课程已发布','success');}
  catch(e){showToast(e.message,'error');button.disabled=false;}
}
