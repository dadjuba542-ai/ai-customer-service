function renderAdminStages() {
  const data=adminPracticeData,e=practiceAdminEscape;
  const host=document.getElementById('practice-stage-manager');
  host.innerHTML=`<section class="admin-card bank-stages"><div class="bank-panel-heading"><div><h3>阶段题库</h3><p class="hint">设置开放日期，期间前台主推阶段主题；开启新主题会替换当前主推主题。</p></div><button class="btn btn-secondary" onclick="editPracticeStage()">＋ 创建阶段</button></div>
    <div class="bank-scope"><label for="practice-bank-scope">当前维护的题库</label><select id="practice-bank-scope" onchange="switchPracticeBank(Number(this.value))"><option value="0">常规 · 每日闯关</option>${data.stages.map(s=>`<option value="${s.id}" ${practiceAdminState.stageId===s.id?'selected':''}>${e(s.title)} · ${e(s.status)}</option>`).join('')}</select></div>
    ${data.stages.map(s=>`<div class="bank-stage-row"><div><strong>${e(s.title)} <small>${s.kind==='weekly'?'每周主题 · ':''}${e(s.status)}</small></strong><p class="hint">${s.starts_on} 至 ${s.ends_on} · ${s.question_count}道启用题 · ${s.batch_count}关</p></div><div class="bank-buttons"><button class="btn btn-secondary btn-sm" onclick="switchPracticeBank(${s.id})">维护题目 / 上传</button><button class="btn btn-secondary btn-sm" onclick="loadPracticePromotionPreview(${s.id})">推广预览</button><button class="btn btn-secondary btn-sm" onclick="editPracticeStage(${s.id})">设置日期与开关</button></div></div>`).join('') || '<p class="hint">例如：三伏天、开学季。创建阶段后，进入该题库上传CSV题目。</p>'}
    <div id="practice-stage-editor"></div><div id="practice-weekly-builder"></div><div id="practice-promotion-preview"></div></section>`;
  if(practiceAdminState.stageEditing)renderPracticeStageEditor(practiceAdminState.stageEditing);
  if(data.stages.find(s=>s.id===practiceAdminState.stageId)?.kind==='weekly')loadPracticeWeeklyBuilder(practiceAdminState.stageId);
}
async function switchPracticeBank(id) {
  if(practiceAdminState.busy)return;
  if(typeof practiceWeeklyState!=='undefined' && practiceWeeklyState.dirty && practiceWeeklyState.id===practiceAdminState.stageId){try{await persistPracticeWeekly();}catch(e){showToast(e.message,'error');return;}}
  Object.assign(practiceAdminState,{stageId:id,editing:null,batch:'0',category:'',status:'',search:'',page:1,import:null,stageEditing:null});
  await loadAdminPractice();
}
function editPracticeStage(id) {
  const current=adminPracticeData.stages.find(s=>s.id===id);
  const s=current ? {...current,enabled:Boolean(current.enabled)} : {id:null,title:'',description:'',starts_on:adminPracticeData.today,ends_on:adminPracticeData.today,enabled:false,kind:'seasonal',request_id:practiceAdminId()};
  practiceAdminState.stageEditing=s;renderPracticeStageEditor(s);
}
function renderPracticeStageEditor(s) {
  const e=practiceAdminEscape;
  document.getElementById('practice-stage-editor').innerHTML=`<div class="bank-stage-form"><h4>${s.id?'编辑阶段':'创建阶段'}</h4><div class="field"><label for="practice-stage-kind">主题类型</label><select id="practice-stage-kind" onchange="practiceStageKindChanged()"><option value="seasonal" ${s.kind!=='weekly'?'selected':''}>阶段专题（如三伏天）</option><option value="weekly" ${s.kind==='weekly'?'selected':''}>每周主题（30题，7天）</option></select></div><div class="field"><label for="practice-stage-title">阶段名称</label><input id="practice-stage-title" maxlength="60" value="${e(s.title)}" placeholder="例如：三伏天专题"></div><div class="field"><label for="practice-stage-description">前台简介</label><textarea id="practice-stage-description" maxlength="300" rows="2" placeholder="向伙伴介绍这期练习内容">${e(s.description)}</textarea></div><div class="bank-form-pair"><div class="field"><label for="practice-stage-start">开始日期（北京时间）</label><input id="practice-stage-start" type="date" onchange="practiceStageDateChanged()" value="${s.starts_on}"></div><div class="field"><label for="practice-stage-end">结束日期（含当天）</label><input id="practice-stage-end" type="date" value="${s.ends_on}"></div></div><label class="bank-enable"><input id="practice-stage-enabled" type="checkbox" ${s.enabled?'checked':''} ${s.id?'':'disabled'}> 开启阶段题库</label><p class="hint">先创建主题并准备题目：每周主题生成30题主题包后开启，阶段专题准备完整的10题关卡后开启。日期范围外自动收起；每日积分与常规闯关共用100分。</p><div class="bank-buttons"><button class="btn btn-primary" onclick="savePracticeStage(this)">保存阶段设置</button><button class="btn btn-secondary" onclick="practiceAdminState.stageEditing=null;document.getElementById('practice-stage-editor').innerHTML=''">取消</button></div></div>`;
}
async function savePracticeStage(button) {
  if(practiceAdminState.busy)return;
  const s=practiceAdminState.stageEditing;
  const data={...s,kind:document.getElementById('practice-stage-kind').value,title:document.getElementById('practice-stage-title').value,description:document.getElementById('practice-stage-description').value,starts_on:document.getElementById('practice-stage-start').value,ends_on:document.getElementById('practice-stage-end').value,enabled:document.getElementById('practice-stage-enabled').checked};
  button.disabled=true;practiceAdminState.busy=true;
  try {if(typeof practiceWeeklyState!=='undefined' && practiceWeeklyState.dirty)await persistPracticeWeekly();const r=await adminPracticeApi(s.id?`/stages/${s.id}`:'/stages',{method:s.id?'PUT':'POST',body:JSON.stringify(data)});practiceAdminState.stageEditing=null;practiceAdminState.editing=null;practiceAdminState.stageId=r.id;await loadAdminPractice();showToast('阶段已保存，可维护题目和开放设置','success');}
  catch(e){showToast(e.message,'error');}finally{button.disabled=false;practiceAdminState.busy=false;}
}

function practiceStageKindChanged() {
  if(document.getElementById('practice-stage-kind').value==='weekly') {
    const start=new Date(adminPracticeData.today+'T12:00:00Z');
    start.setUTCDate(start.getUTCDate()+(8-start.getUTCDay())%7);
    document.getElementById('practice-stage-start').value=start.toISOString().slice(0,10);
    practiceStageDateChanged();
  }
}
function practiceStageDateChanged() {
  if(document.getElementById('practice-stage-kind').value!=='weekly')return;
  const value=document.getElementById('practice-stage-start').value;if(!value)return;
  const end=new Date(value+'T12:00:00Z');end.setUTCDate(end.getUTCDate()+6);
  document.getElementById('practice-stage-end').value=end.toISOString().slice(0,10);
}
