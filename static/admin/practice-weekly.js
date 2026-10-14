const practiceWeeklyState={id:null,data:null,selections:[],search:'',category:'',page:1,dirty:false,generation:0,publishAttempt:null};
async function loadPracticeWeeklyBuilder(id) {
  const generation=++practiceWeeklyState.generation,host=document.getElementById('practice-weekly-builder');
  if(!host)return;host.innerHTML='<p class="hint">正在载入每周选题…</p>';
  try {
    const data=await adminPracticeApi(`/stages/${id}/weekly`);
    if(generation!==practiceWeeklyState.generation || practiceAdminState.stageId!==id)return;
    Object.assign(practiceWeeklyState,{id,data,selections:data.selections.map(s=>({...s})),dirty:false,page:1,publishAttempt:null});
    renderPracticeWeeklyBuilder();
  }catch(e){host.textContent=e.message;}
}
function renderPracticeWeeklyBuilder() {
  const w=practiceWeeklyState,e=practiceAdminEscape,host=document.getElementById('practice-weekly-builder');if(!host || !w.data)return;
  const count=w.selections.length,fresh=w.selections.filter(s=>s.is_new).length;
  const keyword=w.search.trim().toLowerCase();
  const rows=w.data.questions.filter(q=>(!w.category || q.category===w.category) && (!keyword || [q.title,q.explanation,q.method,q.category,...q.options].join(' ').toLowerCase().includes(keyword)));
  const pages=Math.max(1,Math.ceil(rows.length/12));w.page=Math.min(w.page,pages);
  host.innerHTML=`<div class="bank-weekly-workbench"><div class="bank-panel-heading"><div><h3>组建每周主题</h3><p class="hint">每周写5–10道新题，选旧题补足30题；发布时自动分成3组。</p></div><strong class="bank-weekly-count">已选 ${count}/30 · 新题 ${fresh}/5–10</strong></div>
    <div class="bank-buttons"><button class="btn btn-secondary" onclick="beginPracticeNewQuestion()">录入本期新题</button><button class="btn btn-secondary" onclick="openPracticeWeeklyNewImport()">新题 CSV 导入</button><button class="btn btn-secondary" onclick="savePracticeWeeklySelections(this)">保存选题${w.dirty?'（有改动）':''}</button><button class="btn btn-primary" ${count!==30 || fresh<5 || fresh>10?'disabled':''} onclick="publishPracticeWeekly(this)">生成30题主题包</button></div>
    <p class="hint">新题会加入母题库并自动勾选。下面选择旧题；完整的待上架题也可选入主题。本期发布后，母库修改用于下期。</p>
    <div class="bank-filters"><input aria-label="搜索母题库" id="practice-weekly-search" placeholder="搜索客户问题…" value="${e(w.search)}" oninput="filterPracticeWeekly('search',this.value)"><select aria-label="筛选母题库分类" onchange="filterPracticeWeekly('category',this.value)"><option value="">全部分类</option>${[...new Set(w.data.questions.map(q=>q.category))].map(c=>`<option ${c===w.category?'selected':''}>${e(c)}</option>`).join('')}</select><button class="btn btn-secondary btn-sm" onclick="selectPracticeWeeklyPage()">选择本页剩余旧题</button></div>
    <div class="bank-weekly-picks">${rows.slice((w.page-1)*12,w.page*12).map(q=>{const selected=w.selections.find(s=>s.question_id===q.id);return `<div class="bank-weekly-pick"><label><input type="checkbox" ${selected?'checked':''} onchange="choosePracticeWeekly(${q.id},this.checked)"><span><small>#${q.id} · ${e(q.category)}</small><br>${e(q.title)}</span></label>${selected?`<label class="bank-weekly-new"><input type="checkbox" ${selected.is_new?'checked':''} onchange="markPracticeWeeklyNew(${q.id},this.checked)"> 本期新题</label>`:''}</div>`;}).join('') || '<p class="hint">没有符合条件的题目。</p>'}</div>
    <div class="bank-pagination"><button class="btn btn-secondary btn-sm" ${w.page===1?'disabled':''} onclick="practiceWeeklyPage(-1)">上一页</button><span>${w.page}/${pages} · ${rows.length}道母库题</span><button class="btn btn-secondary btn-sm" ${w.page===pages?'disabled':''} onclick="practiceWeeklyPage(1)">下一页</button></div>
    <details class="bank-weekly-selected"><summary>查看已选${count}题</summary>${w.selections.map(s=>{const q=w.data.questions.find(q=>q.id===s.question_id);return `<div class="bank-weekly-selected-row"><span>${s.is_new?'新题':'复用'} · ${e(q?.title || '#'+s.question_id)}</span><button class="btn btn-secondary btn-sm" onclick="choosePracticeWeekly(${s.question_id},false)">移出</button></div>`;}).join('')}</details>
    <div class="bank-buttons"><button class="btn btn-secondary" onclick="previewPracticeWeeklyDraft(this)">预览七天安排与群文案</button><span class="hint">生成题包后，在“设置日期与开关”中开启。</span></div></div>`;
}
function filterPracticeWeekly(key,value) { const input=document.getElementById('practice-weekly-search'),start=input?.selectionStart;practiceWeeklyState[key]=value;practiceWeeklyState.page=1;renderPracticeWeeklyBuilder();if(key==='search'){const next=document.getElementById('practice-weekly-search');next.focus();next.setSelectionRange(start,start);} }
function practiceWeeklyPage(delta) {practiceWeeklyState.page+=delta;renderPracticeWeeklyBuilder();}
function choosePracticeWeekly(id,checked) {
  if(practiceAdminState.busy)return;
  const w=practiceWeeklyState;
  if(checked && !w.selections.some(s=>s.question_id===id)){if(w.selections.length>=30){showToast('本期已选满30题','info');renderPracticeWeeklyBuilder();return;}w.selections.push({question_id:id,is_new:false});}
  if(!checked)w.selections=w.selections.filter(s=>s.question_id!==id);
  w.dirty=true;renderPracticeWeeklyBuilder();
}
function markPracticeWeeklyNew(id,checked) {if(practiceAdminState.busy)return;practiceWeeklyState.selections.find(s=>s.question_id===id).is_new=checked;practiceWeeklyState.dirty=true;renderPracticeWeeklyBuilder();}
function selectPracticeWeeklyPage() {
  if(practiceAdminState.busy)return;
  const w=practiceWeeklyState,keyword=w.search.trim().toLowerCase();
  const rows=w.data.questions.filter(q=>(!w.category || q.category===w.category) && (!keyword || [q.title,q.explanation,q.method,q.category,...q.options].join(' ').toLowerCase().includes(keyword)));
  for(const q of rows.slice((w.page-1)*12,w.page*12)){if(w.selections.length===30)break;if(!w.selections.some(s=>s.question_id===q.id))w.selections.push({question_id:q.id,is_new:false});}
  w.dirty=true;renderPracticeWeeklyBuilder();
}
async function persistPracticeWeekly() {
  const w=practiceWeeklyState;
  const result=await adminPracticeApi(`/stages/${w.id}/weekly/selections`,{method:'PUT',body:JSON.stringify({selections:w.selections})});
  w.dirty=false;return result;
}
async function savePracticeWeeklySelections(button) {
  if(practiceAdminState.busy)return;practiceAdminState.busy=true;button.disabled=true;
  try{await persistPracticeWeekly();renderPracticeWeeklyBuilder();showToast('选题已保存','success');}catch(e){showToast(e.message,'error');}finally{practiceAdminState.busy=false;button.disabled=false;}
}
async function beginPracticeNewQuestion() {
  if(practiceAdminState.busy)return;
  if(adminPracticeData.stages.find(s=>s.id===practiceAdminState.stageId)?.kind==='weekly'){
    try{if(practiceWeeklyState.dirty)await persistPracticeWeekly();}catch(e){showToast(e.message,'error');return;}
  }
  editAdminPracticeQuestion();document.getElementById('practice-question-editor').scrollIntoView({block:'start',behavior:'smooth'});
}
async function openPracticeWeeklyNewImport() {
  if(practiceAdminState.busy)return;
  try{if(practiceWeeklyState.dirty)await persistPracticeWeekly();const panel=document.getElementById('practice-import-panel');panel.hidden=true;togglePracticeImport(true);panel.scrollIntoView({block:'start',behavior:'smooth'});}catch(e){showToast(e.message,'error');}
}
async function publishPracticeWeekly(button) {
  if(practiceAdminState.busy)return;practiceAdminState.busy=true;button.disabled=true;
  const w=practiceWeeklyState,signature=JSON.stringify([w.id,w.selections]);
  if(w.publishAttempt?.signature!==signature)w.publishAttempt={signature,key:practiceAdminId()};
  try{await persistPracticeWeekly();await adminPracticeApi(`/stages/${w.id}/weekly/publish`,{method:'POST',body:JSON.stringify({request_id:w.publishAttempt.key})});await loadAdminPractice();showToast('30题与七天安排已生成，可在阶段设置中开启','success');}
  catch(e){showToast(e.message,'error');}finally{practiceAdminState.busy=false;button.disabled=false;}
}
async function previewPracticeWeeklyDraft(button) {
  if(practiceAdminState.busy)return;button.disabled=true;
  try{const preview=await persistPracticeWeekly();if(!preview.ready)throw new Error(preview.error || '选满30题、标记5–10道新题后可预览');renderPracticeWeeklyBuilder();renderPracticePromotionPreview({stage:practiceWeeklyState.data.stage,schedule:preview.schedule,draft:true});}
  catch(e){showToast(e.message,'error');}finally{button.disabled=false;}
}
async function loadPracticePromotionPreview(id) {
  try{const data=await adminPracticeApi(`/stages/${id}/promotion`);renderPracticePromotionPreview(data);}catch(e){showToast(e.message,'error');}
}
let practicePromotionPreview=null;
function renderPracticePromotionPreview(data) {
  practicePromotionPreview=data;
  const host=document.getElementById('practice-promotion-preview'),e=practiceAdminEscape;
  host.innerHTML=`<div class="bank-weekly-preview"><h4>${e(data.stage.title)} · ${data.draft?'七天安排草稿':'每日推广预览'}</h4>${data.schedule.map((d,i)=>`<div class="bank-weekly-day"><div><small>${d.day} · ${e(d.label)} · 第${d.batch_no}组</small><p>${e(d.question_title)}</p></div><button class="btn btn-secondary btn-sm" ${data.draft?'disabled':''} onclick="copyPracticePromotion(${i})">${data.draft?'生成后可复制':'复制'+(d.day===adminPracticeData.today?'今日':'当天')+'群文案'}</button></div>`).join('') || '<p class="hint">准备好题目后即可预览每日问题。</p>'}</div>`;
  host.scrollIntoView({block:'start',behavior:'smooth'});
}
async function copyPracticePromotion(index) {
  const {stage,schedule}=practicePromotionPreview,d=schedule[index];
  const link=`${window.location.origin}/?practice_theme=${stage.id}`;
  const text=`${stage.kind==='weekly'?'本周练习':'阶段练习'}：${stage.title}\n${d.day} · ${d.label}\n今天这句话，你会怎么接？\n${d.question_title}\n点进去选一下，看看解析：${link}`;
  try {
    if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);
    else throw new Error('fallback');
    showToast('群文案已复制，可自行转发','success');
  }catch {
    const box=document.createElement('textarea');box.value=text;box.style.position='fixed';box.style.opacity='0';document.body.appendChild(box);box.select();const ok=document.execCommand('copy');box.remove();showToast(ok?'群文案已复制':'复制未成功，请手动选取文案',ok?'success':'error');
    if(!ok){const host=document.getElementById('practice-promotion-preview');const field=document.createElement('textarea');field.value=text;field.rows=8;field.style.width='100%';host.appendChild(field);field.select();}
  }
}
function renderPracticeEntryMetrics() {
  const host=document.getElementById('practice-entry-metrics'),data=adminPracticeData,e=practiceAdminEscape;if(!host)return;
  host.innerHTML=`<details class="admin-card"><summary>客户问题入口统计 · 按主题</summary><p class="hint">统计实际展示、点击进入、入口后首次作答及整局完成的独立身份；点击率＝点击人数／展示人数。首题完成率＝首次作答人数／点击人数；整局完成率＝整局完成人数／点击人数。</p><div class="bank-table-scroll"><table class="data-table"><thead><tr><th>主题</th><th>展示</th><th>点击</th><th>点击率</th><th>首题作答</th><th>首题完成率</th><th>整局完成</th><th>整局完成率</th></tr></thead><tbody>${data.entry_metrics.map(m=>`<tr><td>${e(m.stage_id ? data.stages.find(s=>s.id===m.stage_id)?.title || '历史主题' : '常规每日题')}</td><td>${m.impression}</td><td>${m.click}</td><td>${m.impression?Math.round(m.click/m.impression*100)+'%':'—'}</td><td>${m.first_answer}</td><td>${m.click?Math.round(m.first_answer/m.click*100)+'%':'—'}</td><td>${m.complete}</td><td>${m.click?Math.round(m.complete/m.click*100)+'%':'—'}</td></tr>`).join('')}</tbody></table>${data.entry_metrics.length?'':'<p class="hint">用户从问题入口开始练习后，这里会显示数据。</p>'}</div></details>`;
}
