function practiceAdminEscape(value) { return esc(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
let adminPracticeData = null;
const practiceAdminState = { batch: '0', category: '', status: '', search: '', page: 1, editing: null, import: null, busy: false, attempt: null, importGeneration: 0, stageId: 0, stageEditing: null, weeklyNewImport: false };
function practiceAdminId() { return crypto.randomUUID ? crypto.randomUUID() : `bank${Date.now()}_${Math.random().toString(36).slice(2)}`; }
async function adminPracticeApi(path = '', options = {}) {
  const scope = `${path.includes('?')?'&':'?'}stage_id=${practiceAdminState.stageId}`;
  const response = await fetch(`${API}/api/admin/practice${path}${scope}`, {
    ...options, headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || '操作失败');
  return data;
}
function practiceAdminBatches() { return [...new Set(adminPracticeData.questions.map(q => q.batch_no))].sort((a,b) => a-b); }
function practiceAdminNextBatch() { const last=Math.max(0,...practiceAdminBatches()); return last && adminPracticeData.questions.filter(q=>q.batch_no===last).length<10 ? last : last+1; }
async function loadAdminPractice() {
  const host = document.getElementById('admin-practice-content');
  host.innerHTML = '<div class="admin-card">正在加载题库…</div>';
  try {
    adminPracticeData = await adminPracticeApi();
    const data = adminPracticeData, selectedStage=data.stages?.find(s=>s.id===practiceAdminState.stageId), enabled = data.questions.filter(q => q.enabled).length;
    host.innerHTML = `<div class="bank-heading"><div><span class="bank-eyebrow">内容工作台</span><h2>${practiceAdminEscape(selectedStage ? selectedStage.title+' · 阶段题库' : '每日闯关题库')}</h2><p>查找场景、完善解析，把团队经验变成可练习的题目。</p></div><span class="bank-status">${data.enabled ? '● 闯关已开启' : '○ 闯关未开启'}</span></div>
      <div class="bank-stats"><div><b>${data.questions.length}</b><span>全部题目</span></div><div><b>${enabled}</b><span>启用题目</span></div><div><b>${data.batches.length}</b><span>可练关卡</span></div><div><b>${data.questions.length-enabled}</b><span>待完善 / 停用</span></div></div>
      <div class="bank-toolbar"><div class="bank-buttons"><button class="btn btn-primary" onclick="beginPracticeNewQuestion()">＋ 新增题目</button><button class="btn btn-secondary" onclick="togglePracticeImport()">批量导入</button><button class="btn btn-secondary" onclick="exportPracticeBank(this)">导出 CSV</button><button class="btn btn-secondary" onclick="downloadPracticeTemplate()">下载模板</button></div><span class="hint">每关启用10题后自动进入练习列表</span></div>
      <div id="practice-stage-manager"></div><div id="practice-entry-metrics"></div><div id="practice-import-panel" hidden></div>
      <div class="bank-workspace"><section class="admin-card bank-library"><div class="bank-panel-heading"><h3>题目列表</h3><span id="practice-filter-count" class="hint"></span></div>
        <div class="bank-search"><label for="practice-bank-search">搜索题目或解析</label><input id="practice-bank-search" placeholder="输入产品、场景或关键词…" value="${practiceAdminEscape(practiceAdminState.search)}" oninput="filterAdminPractice('search',this.value)"></div>
        <div class="bank-filters"><select aria-label="按关卡查看" id="practice-admin-filter" onchange="filterAdminPractice('batch',this.value)"><option value="0">全部关卡</option>${practiceAdminBatches().map(b => `<option value="${b}" ${String(b)===practiceAdminState.batch ? 'selected' : ''}>第${b}关</option>`).join('')}</select>
        <select aria-label="按分类查看" onchange="filterAdminPractice('category',this.value)"><option value="">全部分类</option>${data.categories.map(c => `<option ${c===practiceAdminState.category?'selected':''}>${practiceAdminEscape(c)}</option>`).join('')}</select>
        <select aria-label="按状态查看" onchange="filterAdminPractice('status',this.value)"><option value="">全部状态</option><option value="1" ${practiceAdminState.status==='1'?'selected':''}>启用</option><option value="0" ${practiceAdminState.status==='0'?'selected':''}>停用</option></select></div>
        <div id="practice-question-list"></div><div id="practice-bank-pagination" class="bank-pagination"></div></section>
        <section class="admin-card bank-editor" id="practice-question-editor"></section></div>
      <details class="admin-card bank-team-summary"><summary>团队学习概况 <small>${data.summary.length}个团队 · 累计数据</small></summary><p class="hint">开始率＝开始人数／访问人数；访问含问题卡片展示和练习页访问。完成率＝完成局数／开始局数。次日回访统计第二天再次访问，七日再练统计后续七天再次开始练习。</p><div class="bank-table-scroll"><table class="data-table"><thead><tr><th>团队</th><th>访问</th><th>参与</th><th>开始率</th><th>开始局数</th><th>完成局数</th><th>完成率</th><th>次日回访</th><th>七日再练</th></tr></thead><tbody>${data.summary.map(s => `<tr><td>${practiceAdminEscape(s.team_name || '未选择团队')}</td><td>${s.visitors}</td><td>${s.participants}</td><td>${s.visitors?Math.round(s.participants/s.visitors*100)+'%':'—'}</td><td>${s.started}</td><td>${s.completed}</td><td>${s.started?Math.round(s.completed/s.started*100)+'%':'—'}</td><td>${s.next_day_returns}</td><td>${s.seven_day_returns}</td></tr>`).join('')}</tbody></table>${data.summary.length?'':'<p class="hint">开始试用后，这里会显示团队学习情况。</p>'}</div></details>`;
    renderAdminStages(); renderAdminPracticeQuestions();
    renderPracticeEntryMetrics();
    if (practiceAdminState.editing) renderAdminPracticeEditor(practiceAdminState.editing);
    else renderPracticeEditorEmpty();
  } catch (error) { host.innerHTML = `<div class="admin-card">${practiceAdminEscape(error.message)} <button class="btn btn-secondary" onclick="loadAdminPractice()">重试</button></div>`; }
}
function filterAdminPractice(key, value) { practiceAdminState[key]=value; practiceAdminState.page=1; renderAdminPracticeQuestions(); }
function renderAdminPracticeQuestions() {
  const st = practiceAdminState, keyword = st.search.trim().toLowerCase();
  const rows = adminPracticeData.questions.filter(q => (!Number(st.batch) || q.batch_no===Number(st.batch)) && (!st.category || q.category===st.category) &&
    (!st.status || Boolean(q.enabled)===(st.status==='1')) && (!keyword || [q.title,q.explanation,q.method,...q.options].join(' ').toLowerCase().includes(keyword)));
  const pages = Math.max(1,Math.ceil(rows.length/15)); st.page=Math.min(st.page,pages);
  document.getElementById('practice-filter-count').textContent = `${rows.length}道题`;
  document.getElementById('practice-question-list').innerHTML = rows.slice((st.page-1)*15,st.page*15).map(q =>
    `<button class="bank-question ${st.editing?.id===q.id?'selected':''}" onclick="editAdminPracticeQuestion(${q.id})"><span class="bank-question-meta"><span>#${q.id} · 第${q.batch_no}关</span><span class="bank-question-status ${q.enabled?'on':''}">${q.enabled?'启用':'停用'}</span></span><strong>${practiceAdminEscape(q.title)}</strong><span class="bank-question-category">${practiceAdminEscape(q.category)}</span></button>`).join('') || '<div class="bank-empty">没有找到题目，试试其他关键词或筛选条件。</div>';
  document.getElementById('practice-bank-pagination').innerHTML = `<button class="btn btn-secondary btn-sm" ${st.page===1?'disabled':''} onclick="practiceAdminPage(-1)">上一页</button><span>${st.page} / ${pages}</span><button class="btn btn-secondary btn-sm" ${st.page===pages?'disabled':''} onclick="practiceAdminPage(1)">下一页</button>`;
}
function practiceAdminPage(delta) { practiceAdminState.page+=delta; renderAdminPracticeQuestions(); document.querySelector('.bank-library')?.scrollIntoView({block:'start'}); }
function renderPracticeEditorEmpty() { document.getElementById('practice-question-editor').innerHTML='<div class="bank-empty"><div class="bank-empty-icon">✎</div><h3>选择一道题开始编辑</h3><p>左侧查找场景，右侧编辑题目和解析。<br>也可以新增题目或导入整批内容。</p><button class="btn btn-primary" onclick="beginPracticeNewQuestion()">新增第一道题</button></div>'; }
function practiceEditorValue() {
  const value = key => document.getElementById('practice-q-'+key).value;
  return { ...practiceAdminState.editing, title:value('title'), category:value('category'), batch_no:Number(value('batch')),
    options:[0,1,2,3].map(i=>value('option-'+i)), answer_index:Number(value('answer')), explanation:value('explanation'), method:value('method'), enabled:document.getElementById('practice-q-enabled').checked };
}
function practiceEditorChanged() { if (document.getElementById('practice-q-title')) practiceAdminState.editing=practiceEditorValue(); if(document.querySelector('.bank-preview[open]'))renderPracticeAdminPreview(); }
function editAdminPracticeQuestion(id, copy=false) {
  if (practiceAdminState.busy) return;
  const source = adminPracticeData.questions.find(q=>q.id===id) || adminPracticeData.draft_questions?.find(q=>q.id===id);
  const q = source ? {...source, options:[...source.options], enabled:Boolean(source.enabled)} :
    {id:null,stage_id:practiceAdminState.stageId,batch_no:practiceAdminNextBatch(),category:practiceAdminState.category || adminPracticeData.categories[0],title:'',options:['','','',''],answer_index:0,explanation:'',method:'',sources:[],enabled:false};
  if (copy) { q.id=null; delete q.updated_at; q.title+='（副本）'; q.enabled=false; q.batch_no=practiceAdminNextBatch(); }
  practiceAdminState.editing=q; practiceAdminState.attempt=null;
  renderAdminPracticeEditor(q); renderAdminPracticeQuestions();
  document.getElementById('practice-q-title').focus();
}
function renderAdminPracticeEditor(q) {
  const e=practiceAdminEscape,weekly=adminPracticeData.stages.find(s=>s.id===practiceAdminState.stageId)?.kind==='weekly',sourceDraft=weekly && (!q.id || q.stage_id===0);
  document.getElementById('practice-question-editor').innerHTML=`<div class="bank-panel-heading"><div><span class="bank-eyebrow">${q.id?'题目 #'+q.id:'新增题目'}</span><h3>${q.id?'编辑客户场景':'把经验写成一道题'}</h3></div>${q.id?`<button class="btn btn-secondary btn-sm" onclick="editAdminPracticeQuestion(${q.id},true)">复制新增</button>`:''}</div>
    <div class="bank-editor-form" oninput="practiceEditorChanged()" onchange="practiceEditorChanged()"><div class="bank-form-pair"><div class="field"><label for="practice-q-category">产品分类</label>${practiceAdminState.stageId && adminPracticeData.stages.find(s=>s.id===practiceAdminState.stageId)?.kind!=='weekly' ? `<input id="practice-q-category" maxlength="40" value="${e(q.category)}" placeholder="例如：三伏天、夏季沟通">` : `<select id="practice-q-category">${adminPracticeData.categories.map(c=>`<option ${c===q.category?'selected':''}>${e(c)}</option>`).join('')}</select>`}</div><div class="field"><label for="practice-q-batch">所属关卡</label><input id="practice-q-batch" type="number" min="1" max="10000" value="${q.batch_no}" ${weekly?'disabled':''}>${sourceDraft?'<small class="hint">本期发布时自动分组</small>':''}</div></div>
    <div class="field"><label for="practice-q-title">客户场景</label><textarea id="practice-q-title" rows="2" maxlength="500" placeholder="客户会怎样问？请写一个具体场景。">${e(q.title)}</textarea></div>
    <div class="bank-editor-label">四个处理方式 <small>用具体动作写选项</small></div><div class="bank-option-fields">${q.options.map((o,i)=>`<div class="field"><label for="practice-q-option-${i}"><span>${'ABCD'[i]}</span></label><textarea id="practice-q-option-${i}" rows="2" maxlength="500">${e(o)}</textarea></div>`).join('')}</div>
    <div class="bank-form-pair"><div class="field"><label for="practice-q-answer">推荐答案</label><select id="practice-q-answer">${q.options.map((_,i)=>`<option value="${i}" ${q.answer_index===i?'selected':''}>${'ABCD'[i]}</option>`).join('')}</select></div><label class="bank-enable" ${sourceDraft?'hidden':''}><input id="practice-q-enabled" type="checkbox" ${q.enabled?'checked':''}> 启用这道题</label></div>
    <div class="field"><label for="practice-q-explanation">为什么这样选</label><textarea id="practice-q-explanation" rows="3" maxlength="2000" placeholder="说明判断方法，而不只是重复答案。">${e(q.explanation)}</textarea></div>
    <div class="field"><label for="practice-q-method">下一句可以这样说</label><textarea id="practice-q-method" rows="2" maxlength="1000" placeholder="写一句伙伴可以直接参考的回复。">${e(q.method)}</textarea></div></div>
    <details class="bank-preview"><summary onclick="renderPracticeAdminPreview()">查看学员看到的内容</summary><div id="practice-admin-preview"></div></details>
    <div class="bank-editor-actions"><span class="hint">保存后用于新练习，已有练习保留原版本。</span><div><button class="btn btn-secondary" onclick="closePracticeEditor()">收起</button><button class="btn btn-primary" onclick="saveAdminPracticeQuestion(this)">保存题目</button></div></div>`;
}
function closePracticeEditor() { if(practiceAdminState.busy)return; practiceAdminState.editing=null; renderPracticeEditorEmpty(); renderAdminPracticeQuestions(); }
function renderPracticeAdminPreview() { const q=practiceEditorValue(),e=practiceAdminEscape; document.getElementById('practice-admin-preview').innerHTML=`<h4>${e(q.title)}</h4>${q.options.map((o,i)=>`<p class="bank-preview-option ${i===q.answer_index?'answer':''}">${'ABCD'[i]} · ${e(o)}</p>`).join('')}<p>${e(q.explanation)}</p><blockquote>${e(q.method)}</blockquote>`; }
async function saveAdminPracticeQuestion(button) {
  if(practiceAdminState.busy)return;
  const q=practiceEditorValue(), payload={...q}; delete payload.id;
  const serial=JSON.stringify(payload);
  if(!q.id) {
    if(practiceAdminState.attempt?.serial!==serial)practiceAdminState.attempt={serial,key:practiceAdminId()};
    payload.request_id=practiceAdminState.attempt.key;
  }
  practiceAdminState.busy=true;button.disabled=true;
  try {
    const result=await adminPracticeApi(q.id?`/questions/${q.id}`:'/questions',{method:q.id?'PUT':'POST',body:JSON.stringify(payload)});
    const id=q.id || result.id;
    practiceAdminState.editing=null; await loadAdminPractice();
    editAdminPracticeQuestionAfterSave(id);
    showToast('题目已保存','success');
  } catch(error){showToast(error.message,'error');}
  finally{practiceAdminState.busy=false;button.disabled=false;}
}
function editAdminPracticeQuestionAfterSave(id) { const q=adminPracticeData.questions.find(q=>q.id===id) || adminPracticeData.draft_questions?.find(q=>q.id===id);practiceAdminState.editing={...q,enabled:Boolean(q.enabled)};renderAdminPracticeEditor(practiceAdminState.editing);renderAdminPracticeQuestions(); }
function downloadPracticeCsv(text,name) { const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }
async function exportPracticeBank(button) {
  button.disabled=true;
  try { const r=await fetch(`${API}/api/admin/practice/export?stage_id=${practiceAdminState.stageId}`,{headers:{Authorization:`Bearer ${getToken()}`}});if(!r.ok)throw new Error('导出失败');downloadPracticeCsv(await r.text(),'闯关题库.csv'); }
  catch(e){showToast(e.message,'error');}finally{button.disabled=false;}
}
function downloadPracticeTemplate() {
  const columns=['id','关卡','分类','客户场景','A','B','C','D','推荐答案','解析','参考回复','启用','参考资料','版本'];
  const row=['',practiceAdminNextBatch(),practiceAdminState.stageId && adminPracticeData.stages.find(s=>s.id===practiceAdminState.stageId)?.kind!=='weekly' ? (adminPracticeData.stages.find(s=>s.id===practiceAdminState.stageId)?.title.slice(0,40) || '阶段主题') : '益生菌','客户说价格太贵，先怎么回应？','问清比较的规格与需求','立即发优惠券','只讲品牌知名度','直接推荐大套餐','A','先对齐比较对象，再解释具体差异。','您比较的是哪款、多少份装？','0','',''];
  downloadPracticeCsv('\uFEFF'+[columns,row].map(r=>r.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(',')).join('\r\n'),'题库导入模板.csv');
}
function togglePracticeImport(weeklyNew=false) {
  practiceAdminState.weeklyNewImport=weeklyNew;
  const host=document.getElementById('practice-import-panel');host.hidden=!host.hidden; practiceAdminState.importGeneration++; practiceAdminState.import=null;
  if(!host.hidden)host.innerHTML=`<div class="admin-card"><div class="bank-panel-heading"><h3>${weeklyNew?'录入本期新题 · 自动加入母库':'批量导入题库'}</h3><button class="btn btn-secondary btn-sm" onclick="togglePracticeImport()">收起</button></div><p class="hint">下载模板新增题，或导出题库后批量修改。新增题留空id；修改题保留id和版本。每关安排10道启用题，新增题默认停用。</p>${practiceAdminState.stageId && !practiceAdminState.weeklyNewImport && adminPracticeData.stages.find(s=>s.id===practiceAdminState.stageId)?.kind!=='weekly' ? '<label class="bank-replace"><input id="practice-import-replace" type="checkbox" onchange="previewPracticeCsv(document.getElementById(\'practice-csv-file\'))"> 替换整个阶段题库（保留旧练习记录）</label>' : ''}<label class="bank-file-label" for="practice-csv-file">选择 UTF-8 CSV 文件</label><input id="practice-csv-file" type="file" accept=".csv,text/csv" onchange="previewPracticeCsv(this)"><div id="practice-import-preview"></div></div>`;
}
async function previewPracticeCsv(input) {
  practiceAdminState.import=null; const generation=++practiceAdminState.importGeneration;
  const file=input.files[0],host=document.getElementById('practice-import-preview');if(!file)return;
  host.textContent='正在检查题目…';
  try {
    if(file.size>2000000)throw new Error('请使用不超过2MB的CSV文件');
    const replace=Boolean(document.getElementById('practice-import-replace')?.checked);
    const csv=await file.text(),result=await adminPracticeApi('/import/preview',{method:'POST',body:JSON.stringify({csv,replace,weekly_new_import:practiceAdminState.weeklyNewImport})});
    if(generation!==practiceAdminState.importGeneration)return;
    practiceAdminState.import={csv,replace,weekly_new_import:practiceAdminState.weeklyNewImport,key:practiceAdminId()};
    host.innerHTML=`<div class="bank-import-result"><strong>新增 ${result.added} 道 · 更新 ${result.updated} 道</strong>${result.errors.length?`<ul>${result.errors.map(e=>`<li>第${e.row}行：${practiceAdminEscape(e.message)}</li>`).join('')}</ul><p>修改文件或调整选题后，可重新检查。</p><button class="btn btn-secondary" onclick="previewPracticeCsv(document.getElementById('practice-csv-file'))">重新检查文件</button>`:`<p class="hint">预览前${result.items.length}道题：</p>${result.items.map(q=>`<p class="bank-import-row">${q.id?'更新 #'+q.id:'新增'} · 第${q.batch_no}关 · ${practiceAdminEscape(q.title)}</p>`).join('')}<button class="btn btn-primary" onclick="applyPracticeImport(this)">写入这 ${result.total} 道题</button>`}</div>`;
  }catch(e){host.textContent=e.message;}
}
async function applyPracticeImport(button) {
  if(practiceAdminState.busy || !practiceAdminState.import)return;
  button.disabled=true;practiceAdminState.busy=true;
  try {const pending=practiceAdminState.import;const result=await adminPracticeApi('/import',{method:'POST',body:JSON.stringify({csv:pending.csv,replace:pending.replace,weekly_new_import:pending.weekly_new_import,request_id:pending.key})});practiceAdminState.import=null;practiceAdminState.editing=null;await loadAdminPractice();showToast(`已新增${result.added}道、更新${result.updated}道`,'success');}
  catch(e){showToast(e.message,'error');}finally{practiceAdminState.busy=false;button.disabled=false;}
}
