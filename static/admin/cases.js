// ===== Case Management =====
let caseEditingId = null;
let caseRecognizedFields = null;
let caseTagsCache = [];

function caseTagsHtml(value, cls) {
  return String(value || '').split(',').map(t => t.trim()).filter(Boolean)
    .map(t => `<span class="tag ${cls}">${esc(t)}</span>`).join(' ');
}

function caseTagTypeLabel(type) {
  return type === 'product' ? '产品' : '症状';
}

function resetCaseTagForm() {
  document.getElementById('case-tag-editing-id').value = '';
  document.getElementById('case-tag-type').value = 'symptom';
  document.getElementById('case-tag-name').value = '';
  document.getElementById('case-tag-aliases').value = '';
  document.getElementById('case-tag-sort-order').value = '0';
  document.getElementById('case-tag-status').checked = true;
}

async function loadCaseTags() {
  try {
    const res = await fetch(`${API}/api/admin/case-tags`, {
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    caseTagsCache = data.tags || [];
    renderCaseTagsList();
  } catch { showToast('标签库加载失败', 'error'); }
}

function renderCaseTagsList() {
  const box = document.getElementById('case-tags-list');
  if (!box) return;
  if (!caseTagsCache.length) {
    box.innerHTML = '<div class="empty-state" style="padding:14px"><i class="ph ph-tag"></i>暂无标准标签，保存案例时也会自动创建</div>';
    return;
  }
  box.innerHTML = caseTagsCache.map(tag => `
    <div class="admin-list-item" style="padding:10px 0">
      <div style="min-width:0">
        <div class="item-title">
          <span class="tag ${tag.type === 'product' ? 'tag-emerald' : 'tag-rose'}">${caseTagTypeLabel(tag.type)}</span>
          ${esc(tag.name)}
          ${tag.status ? '' : '<span class="tag tag-rose">已停用</span>'}
        </div>
        <div class="item-meta">别名：${esc(tag.aliases || '无')} · 排序 ${tag.sort_order || 0}</div>
      </div>
      <div class="item-actions">
        <button class="btn btn-secondary btn-sm" onclick="toggleCaseTagStatus(${tag.id}, ${tag.status ? 0 : 1})">${tag.status ? '停用' : '启用'}</button>
        <button class="btn btn-secondary btn-sm" onclick="editCaseTag(${tag.id})">编辑</button>
      </div>
    </div>
  `).join('');
}

function editCaseTag(id) {
  const tag = caseTagsCache.find(item => item.id === id);
  if (!tag) return showToast('标签不存在', 'error');
  document.getElementById('case-tag-editing-id').value = tag.id;
  document.getElementById('case-tag-type').value = tag.type || 'symptom';
  document.getElementById('case-tag-name').value = tag.name || '';
  document.getElementById('case-tag-aliases').value = tag.aliases || '';
  document.getElementById('case-tag-sort-order').value = tag.sort_order || 0;
  document.getElementById('case-tag-status').checked = !!tag.status;
}

async function saveCaseTag() {
  const id = document.getElementById('case-tag-editing-id').value;
  const payload = {
    type: document.getElementById('case-tag-type').value,
    name: document.getElementById('case-tag-name').value.trim(),
    aliases: document.getElementById('case-tag-aliases').value.trim(),
    sort_order: parseInt(document.getElementById('case-tag-sort-order').value || '0', 10),
    status: document.getElementById('case-tag-status').checked ? 1 : 0,
  };
  if (!payload.name) return showToast('请输入标签名称', 'error');
  try {
    const res = await fetch(id ? `${API}/api/admin/case-tags/${id}` : `${API}/api/admin/case-tags`, {
      method: id ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return showToast(data.error || '保存失败', 'error');
    showToast(id ? '标签已更新' : '标签已创建', 'success');
    resetCaseTagForm();
    loadCaseTags();
    loadAdminCases();
  } catch { showToast('保存失败', 'error'); }
}

async function toggleCaseTagStatus(id, status) {
  try {
    const res = await fetch(`${API}/api/admin/case-tags/${id}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ status }),
    });
    if (res.ok) {
      showToast(status ? '标签已启用' : '标签已停用', 'success');
      loadCaseTags();
    }
  } catch { showToast('操作失败', 'error'); }
}

async function recognizeCaseLink() {
  const input = document.getElementById('case-recognize-url');
  const btn = document.getElementById('case-recognize-btn');
  const box = document.getElementById('case-recognize-result');
  const url = input.value.trim();
  if (!url) return showToast('请输入案例链接', 'error');
  btn.disabled = true;
  btn.innerHTML = '<i class="ph ph-spinner"></i> 识别中...';
  box.style.display = 'block';
  box.innerHTML = '<div class="empty-state" style="padding:16px"><i class="ph ph-spinner"></i>正在抓取网页并识别字段...</div>';
  try {
    const res = await fetch(`${API}/api/admin/cases/recognize-link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ url }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      caseRecognizedFields = { status: 1, sort_order: 0 };
      renderCaseRecognitionPreview({
        source_url: url,
        final_url: '',
        fields: caseRecognizedFields,
        raw_excerpt: '',
        warnings: [data.error || '链接识别失败，请手动补充正文'],
      });
      return showToast(data.error || '链接识别失败', 'error');
    }
    caseRecognizedFields = data.fields || {};
    renderCaseRecognitionPreview(data);
    showToast('识别完成，请确认后保存', 'success');
  } catch {
    caseRecognizedFields = { status: 1, sort_order: 0 };
    renderCaseRecognitionPreview({
      source_url: url,
      final_url: '',
      fields: caseRecognizedFields,
      raw_excerpt: '',
      warnings: ['网络错误，已保留链接，请手动补充正文'],
    });
    showToast('识别失败', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="ph ph-sparkle"></i> 识别案例';
  }
}

function renderCaseRecognitionPreview(data) {
  const box = document.getElementById('case-recognize-result');
  const fields = data.fields || {};
  const warnings = data.warnings || [];
  box.style.display = 'block';
  box.innerHTML = `
    <div style="border:1px solid var(--slate-200);border-radius:12px;background:#F8FAFC;padding:12px">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px">
        <div style="min-width:0">
          <div style="font-size:12px;font-weight:700;color:var(--primary);margin-bottom:4px">识别预览</div>
          <div style="font-size:12px;color:var(--slate-500);word-break:break-all">来源：${esc(data.source_url || '')}</div>
          ${data.final_url && data.final_url !== data.source_url ? `<div style="font-size:12px;color:var(--slate-400);word-break:break-all">最终链接：${esc(data.final_url)}</div>` : ''}
        </div>
        <button class="btn btn-secondary btn-sm" onclick="clearCaseRecognitionPreview()"><i class="ph ph-x"></i> 清空</button>
      </div>
      ${warnings.length ? `<div style="background:#FFF7ED;color:#B45309;border:1px solid #FED7AA;border-radius:8px;padding:8px 10px;font-size:12px;margin-bottom:10px">${warnings.map(w => `<div>${esc(w)}</div>`).join('')}</div>` : ''}
      <div class="admin-row">
        <div class="field" style="flex:1"><label>标题</label><input type="text" id="case-preview-title" value="${esc(fields.title || '')}"></div>
        <div class="field" style="width:140px"><label>排序</label><input type="number" id="case-preview-sort-order" value="${Number(fields.sort_order || 0)}"></div>
      </div>
      <div class="admin-row">
        <div class="field"><label>客户画像</label><input type="text" id="case-preview-customer-profile" value="${esc(fields.customer_profile || '')}"></div>
      </div>
      <div class="admin-row">
        <div class="field" style="flex:1"><label>症状标签</label><input type="text" id="case-preview-symptom-tags" value="${esc(fields.symptom_tags || '')}"></div>
        <div class="field" style="flex:1"><label>产品标签</label><input type="text" id="case-preview-product-tags" value="${esc(fields.product_tags || '')}"></div>
      </div>
      <div class="admin-row">
        <div class="field"><label>使用场景</label><input type="text" id="case-preview-scenario" value="${esc(fields.scenario || '')}"></div>
      </div>
      <div class="admin-row">
        <div class="field"><label>摘要</label><textarea id="case-preview-summary" rows="2">${esc(fields.summary || '')}</textarea></div>
      </div>
      <div class="admin-row">
        <div class="field"><label>详细记录</label><textarea id="case-preview-content" rows="5">${esc(fields.content || '')}</textarea></div>
      </div>
      <div class="admin-row">
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--slate-600)">
          <input type="checkbox" id="case-preview-status" ${String(fields.status ?? 1) !== '0' ? 'checked' : ''}> 前台可推荐
        </label>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-secondary" onclick="fillCaseFormFromPreview()"><i class="ph ph-arrow-bend-down-right"></i> 填入当前表单</button>
        <button class="btn btn-primary" onclick="createCaseFromPreview()"><i class="ph ph-check"></i> 确认创建案例</button>
      </div>
      ${data.raw_excerpt ? `<details style="margin-top:10px"><summary style="cursor:pointer;font-size:12px;color:var(--slate-500)">查看网页原文片段</summary><div style="font-size:12px;color:var(--slate-500);line-height:1.6;margin-top:8px;max-height:160px;overflow:auto">${esc(data.raw_excerpt)}</div></details>` : ''}
    </div>`;
}

function clearCaseRecognitionPreview() {
  caseRecognizedFields = null;
  document.getElementById('case-recognize-result').style.display = 'none';
  document.getElementById('case-recognize-result').innerHTML = '';
}

function readCaseRecognitionPreviewFields() {
  const get = id => document.getElementById(id)?.value.trim() || '';
  return {
    title: get('case-preview-title'),
    customer_profile: get('case-preview-customer-profile'),
    symptom_tags: get('case-preview-symptom-tags'),
    product_tags: get('case-preview-product-tags'),
    scenario: get('case-preview-scenario'),
    summary: get('case-preview-summary'),
    content: get('case-preview-content'),
    status: document.getElementById('case-preview-status')?.checked ? 1 : 0,
    sort_order: parseInt(get('case-preview-sort-order') || '0', 10),
  };
}

function applyCaseFieldsToForm(fields, resetEditing = true) {
  if (resetEditing) {
    caseEditingId = null;
    document.getElementById('case-editing-id').value = '';
    document.getElementById('case-form-title').textContent = '新增案例档案';
  }
  document.getElementById('case-title').value = fields.title || '';
  document.getElementById('case-customer-profile').value = fields.customer_profile || '';
  document.getElementById('case-symptom-tags').value = fields.symptom_tags || '';
  document.getElementById('case-product-tags').value = fields.product_tags || '';
  document.getElementById('case-scenario').value = fields.scenario || '';
  document.getElementById('case-summary').value = fields.summary || '';
  document.getElementById('case-content').value = fields.content || '';
  document.getElementById('case-sort-order').value = fields.sort_order || 0;
  document.getElementById('case-status').checked = String(fields.status ?? 1) !== '0';
}

function fillCaseFormFromPreview() {
  const fields = readCaseRecognitionPreviewFields();
  applyCaseFieldsToForm(fields, true);
  showToast('识别结果已填入表单，请确认后保存', 'success');
  document.getElementById('case-form-title').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function createCaseFromPreview() {
  const fields = readCaseRecognitionPreviewFields();
  if (!fields.title) return showToast('请先补充案例标题', 'error');
  applyCaseFieldsToForm(fields, true);
  await saveCase();
}

function resetCaseForm() {
  caseEditingId = null;
  document.getElementById('case-editing-id').value = '';
  document.getElementById('case-form-title').textContent = '新增案例档案';
  document.getElementById('case-title').value = '';
  document.getElementById('case-customer-profile').value = '';
  document.getElementById('case-symptom-tags').value = '';
  document.getElementById('case-product-tags').value = '';
  document.getElementById('case-scenario').value = '';
  document.getElementById('case-summary').value = '';
  document.getElementById('case-content').value = '';
  document.getElementById('case-sort-order').value = '0';
  document.getElementById('case-status').checked = true;
}

async function loadAdminCases() {
  try {
    const res = await fetch(`${API}/api/admin/cases`, {
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    const list = document.getElementById('admin-cases-list');
    const cases = data.cases || [];
    if (!cases.length) {
      list.innerHTML = '<div class="empty-state"><i class="ph ph-files"></i>暂无案例档案</div>';
      return;
    }
    list.innerHTML = cases.map(item => `
      <div class="admin-list-item">
        <div style="display:flex;gap:12px;align-items:flex-start;min-width:0">
          <div style="width:58px;height:58px;border-radius:8px;background:var(--slate-100);display:flex;align-items:center;justify-content:center;color:var(--slate-400)"><i class="ph ph-file-text"></i></div>
          <div style="min-width:0">
            <div class="item-title">${esc(item.title)} ${item.status ? '' : '<span class="tag tag-rose">已隐藏</span>'}</div>
            <div class="item-meta">${esc(item.customer_profile || '')} · 排序 ${item.sort_order || 0}</div>
            <div class="item-meta">${caseTagsHtml(item.symptom_tags, 'tag-rose')} ${caseTagsHtml(item.product_tags, 'tag-emerald')}</div>
            <div class="item-meta" style="max-width:620px;white-space:normal">${esc(item.summary || '')}</div>
          </div>
        </div>
        <div class="item-actions">
          <button class="btn btn-secondary btn-sm" onclick="toggleCaseStatus(${item.id}, ${item.status ? 0 : 1})">${item.status ? '隐藏' : '显示'}</button>
          <button class="btn btn-secondary btn-sm" onclick="editCase(${item.id})">编辑</button>
          <button class="btn btn-danger btn-sm" onclick="deleteCase(${item.id})">删除</button>
        </div>
      </div>
    `).join('');
  } catch { showToast('案例加载失败', 'error'); }
}

async function loadCaseLibraryUrl() {
  const input = document.getElementById('case-library-url-input');
  if (!input) return;
  try {
    const res = await fetch(`${API}/api/admin/settings/case-library-url`, {
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    input.value = data.case_library_url || '';
  } catch { console.error('loadCaseLibraryUrl error'); }
}

async function saveCase() {
  const title = document.getElementById('case-title').value.trim();
  if (!title) return showToast('请输入案例标题', 'error');
  const payload = {
    title,
    customer_profile: document.getElementById('case-customer-profile').value.trim(),
    symptom_tags: document.getElementById('case-symptom-tags').value.trim(),
    product_tags: document.getElementById('case-product-tags').value.trim(),
    scenario: document.getElementById('case-scenario').value.trim(),
    summary: document.getElementById('case-summary').value.trim(),
    content: document.getElementById('case-content').value.trim(),
    status: document.getElementById('case-status').checked ? 1 : 0,
    sort_order: parseInt(document.getElementById('case-sort-order').value || '0', 10),
  };
  const method = caseEditingId ? 'PUT' : 'POST';
  const url = caseEditingId ? `${API}/api/admin/cases/${caseEditingId}` : `${API}/api/admin/cases`;
  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return showToast(data.error || '保存失败', 'error');
    showToast(caseEditingId ? '案例已更新' : '案例已创建', 'success');
    resetCaseForm();
    loadAdminCases();
  } catch { showToast('保存失败', 'error'); }
}

async function editCase(id) {
  try {
    const res = await fetch(`${API}/api/admin/cases`, {
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    const item = (data.cases || []).find(c => c.id === id);
    if (!item) return showToast('案例不存在', 'error');
    caseEditingId = id;
    document.getElementById('case-editing-id').value = id;
    document.getElementById('case-form-title').textContent = '编辑案例档案';
    document.getElementById('case-title').value = item.title || '';
    document.getElementById('case-customer-profile').value = item.customer_profile || '';
    document.getElementById('case-symptom-tags').value = item.symptom_tags || '';
    document.getElementById('case-product-tags').value = item.product_tags || '';
    document.getElementById('case-scenario').value = item.scenario || '';
    document.getElementById('case-summary').value = item.summary || '';
    document.getElementById('case-content').value = item.content || '';
    document.getElementById('case-sort-order').value = item.sort_order || 0;
    document.getElementById('case-status').checked = !!item.status;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch { showToast('案例加载失败', 'error'); }
}

async function toggleCaseStatus(id, status) {
  try {
    const res = await fetch(`${API}/api/admin/cases/${id}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ status }),
    });
    if (res.ok) {
      showToast(status ? '案例已显示' : '案例已隐藏', 'success');
      loadAdminCases();
    }
  } catch { showToast('操作失败', 'error'); }
}

async function deleteCase(id) {
  if (!confirm('确定删除这个案例档案？')) return;
  try {
    const res = await fetch(`${API}/api/admin/cases/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (res.ok) {
      showToast('案例已删除', 'success');
      if (caseEditingId === id) resetCaseForm();
      loadAdminCases();
    }
  } catch { showToast('删除失败', 'error'); }
}

async function saveCaseLibraryUrl() {
  const val = document.getElementById('case-library-url-input').value.trim();
  try {
    const res = await fetch(`${API}/api/admin/settings/case-library-url`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ case_library_url: val }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToast(val ? '案例库链接已保存' : '案例库入口已关闭', 'success');
      document.getElementById('case-library-url-input').value = data.case_library_url || '';
    } else {
      showToast(data.error || '保存失败', 'error');
    }
  } catch { showToast('保存失败', 'error'); }
}


// ===== 批量识别导入 =====
const CB_INPUT_STYLE = 'width:100%;padding:6px 8px;font-size:12px;font-family:inherit;border:1.5px solid var(--slate-200);border-radius:6px;outline:none';
const SHEETJS_CDN = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';

function cbAttr(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function cbVal(id) {
  return (document.getElementById(id)?.value || '').trim();
}

async function ensureSheetJS() {
  if (typeof XLSX !== 'undefined') return;
  await loadScriptOnce(SHEETJS_CDN);
  if (typeof XLSX === 'undefined') throw new Error('表格解析库加载失败，请检查网络');
}

function rowsFromMatrix(matrix) {
  const nonEmpty = (matrix || []).filter(
    row => (row || []).some(cell => String(cell ?? '').trim() !== '')
  );
  if (!nonEmpty.length) return [];
  const header = (nonEmpty[0] || []).map(cell => String(cell ?? '').trim());
  const hasHeader = nonEmpty.length > 1 && header.some(Boolean);
  const body = hasHeader ? nonEmpty.slice(1) : nonEmpty;
  return body.map(cells => (cells || [])
    .map((cell, i) => {
      const value = String(cell ?? '').trim();
      if (!value) return '';
      const key = hasHeader ? header[i] : '';
      return key ? `${key}：${value}` : value;
    })
    .filter(Boolean)
    .join('；')
  ).filter(Boolean);
}

async function loadCaseBatchFile(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  try {
    await ensureSheetJS();
    const buffer = await file.arrayBuffer();
    const workbook = XLSX.read(buffer, { type: 'array' });
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    const matrix = XLSX.utils.sheet_to_json(sheet, { header: 1, blankrows: false, defval: '' });
    const rows = rowsFromMatrix(matrix);
    if (!rows.length) {
      showToast('表格里没有识别到有效行', 'error');
      return;
    }
    document.getElementById('case-batch-text').value = rows.join('\n');
    showToast(`已读取 ${rows.length} 条，点识别开始归纳`, 'success');
  } catch (err) {
    showToast(err?.message || '表格读取失败', 'error');
  } finally {
    input.value = '';
  }
}

async function recognizeCaseBatch() {
  const text = document.getElementById('case-batch-text').value || '';
  const rows = text.split('\n').map(line => line.trim()).filter(Boolean);
  if (!rows.length) return showToast('请先粘贴内容或上传表格', 'error');
  const btn = document.getElementById('case-batch-btn');
  const box = document.getElementById('case-batch-result');
  btn.disabled = true;
  btn.innerHTML = '<i class="ph ph-spinner"></i> 识别中...';
  box.style.display = 'block';
  box.innerHTML = `<div class="empty-state" style="padding:16px"><i class="ph ph-spinner"></i>正在归纳 ${rows.length} 条案例，请稍候...</div>`;
  try {
    const res = await fetch(`${API}/api/admin/cases/recognize-batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ rows }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      box.innerHTML = `<div style="background:#FEF2F2;color:#B91C1C;border:1px solid #FECACA;border-radius:8px;padding:8px 10px;font-size:12px">${esc(data.error || '识别失败')}</div>`;
      return showToast(data.error || '识别失败', 'error');
    }
    renderCaseBatchPreview(data);
    showToast(`识别完成，共 ${(data.cases || []).length} 条，确认后入库`, 'success');
  } catch {
    box.innerHTML = '<div style="background:#FEF2F2;color:#B91C1C;border:1px solid #FECACA;border-radius:8px;padding:8px 10px;font-size:12px">网络错误，识别失败</div>';
    showToast('识别失败，请检查网络', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="ph ph-sparkle"></i> 识别';
  }
}

function cbField(id, label, value, rows) {
  const control = rows > 1
    ? `<textarea id="${id}" rows="${rows}" style="${CB_INPUT_STYLE};resize:vertical">${esc(value || '')}</textarea>`
    : `<input type="text" id="${id}" value="${cbAttr(value || '')}" style="${CB_INPUT_STYLE}">`;
  return `<div class="field" style="flex:1;min-width:0"><label style="font-size:11px">${label}</label>${control}</div>`;
}

function caseBatchCard(item, i) {
  return `
  <div class="case-batch-item" style="border:1px solid var(--slate-200);border-radius:10px;padding:10px;margin-bottom:8px;background:#F8FAFC">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
      <label style="display:flex;align-items:center;gap:6px;font-size:13px;font-weight:600;cursor:pointer;margin:0">
        <input type="checkbox" class="case-batch-pick" data-idx="${i}" checked> 第 ${i + 1} 条
      </label>
    </div>
    <div class="admin-row">
      ${cbField(`cb-title-${i}`, '标题', item.title, 1)}
      ${cbField(`cb-customer-profile-${i}`, '客户画像', item.customer_profile, 1)}
    </div>
    <div class="admin-row">
      ${cbField(`cb-symptom-tags-${i}`, '症状标签（逗号分隔）', item.symptom_tags, 1)}
      ${cbField(`cb-product-tags-${i}`, '产品标签（逗号分隔）', item.product_tags, 1)}
    </div>
    <div class="admin-row">${cbField(`cb-scenario-${i}`, '使用场景', item.scenario, 1)}</div>
    <div class="admin-row">${cbField(`cb-summary-${i}`, '摘要', item.summary, 2)}</div>
    <div class="admin-row">${cbField(`cb-content-${i}`, '详细记录', item.content, 4)}</div>
  </div>`;
}

function renderCaseBatchPreview(data) {
  const items = data.cases || [];
  const warnings = data.warnings || [];
  const box = document.getElementById('case-batch-result');
  if (!items.length) {
    box.innerHTML = '<div class="empty-state" style="padding:16px"><i class="ph ph-table"></i><p>没有识别到案例</p></div>';
    return;
  }
  box.innerHTML = `
    ${warnings.length ? `<div style="background:#FFF7ED;color:#B45309;border:1px solid #FED7AA;border-radius:8px;padding:8px 10px;font-size:12px;margin-bottom:10px">${warnings.map(w => `<div>${esc(w)}</div>`).join('')}</div>` : ''}
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px;flex-wrap:wrap">
      <div style="font-size:13px;color:var(--slate-600)">共识别 <b>${items.length}</b> 条，可就地修改后勾选入库</div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-secondary btn-sm" onclick="toggleCaseBatchAll(true)">全选</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleCaseBatchAll(false)">全不选</button>
        <button class="btn btn-primary btn-sm" id="case-batch-save-btn" onclick="saveSelectedCases()"><i class="ph ph-check"></i> 入库选中</button>
      </div>
    </div>
    ${items.map((item, i) => caseBatchCard(item, i)).join('')}
  `;
}

function toggleCaseBatchAll(checked) {
  document.querySelectorAll('.case-batch-pick').forEach(el => { el.checked = !!checked; });
}

async function saveSelectedCases() {
  const picks = Array.from(document.querySelectorAll('.case-batch-pick:checked'));
  if (!picks.length) return showToast('请先勾选要入库的案例', 'error');
  const btn = document.getElementById('case-batch-save-btn');
  btn.disabled = true;
  btn.innerHTML = '<i class="ph ph-spinner"></i> 入库中...';
  let ok = 0;
  let fail = 0;
  for (const pick of picks) {
    const i = parseInt(pick.dataset.idx, 10);
    const payload = {
      title: cbVal(`cb-title-${i}`),
      customer_profile: cbVal(`cb-customer-profile-${i}`),
      symptom_tags: cbVal(`cb-symptom-tags-${i}`),
      product_tags: cbVal(`cb-product-tags-${i}`),
      scenario: cbVal(`cb-scenario-${i}`),
      summary: cbVal(`cb-summary-${i}`),
      content: cbVal(`cb-content-${i}`),
      status: 1,
      sort_order: 0,
    };
    if (!payload.title) { fail += 1; continue; }
    try {
      const res = await fetch(`${API}/api/admin/cases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        ok += 1;
        pick.checked = false;
        const card = pick.closest('.case-batch-item');
        if (card) card.style.opacity = '0.45';
      } else {
        fail += 1;
      }
    } catch {
      fail += 1;
    }
  }
  btn.disabled = false;
  btn.innerHTML = '<i class="ph ph-check"></i> 入库选中';
  showToast(fail ? `已入库 ${ok} 条，失败 ${fail} 条` : `已入库 ${ok} 条`, fail ? 'error' : 'success');
  if (ok) {
    loadAdminCases();
    loadCaseTags();
  }
}

function clearCaseBatch() {
  document.getElementById('case-batch-text').value = '';
  const box = document.getElementById('case-batch-result');
  box.style.display = 'none';
  box.innerHTML = '';
}

Object.assign(window, {
  resetCaseTagForm,
  loadCaseTags,
  editCaseTag,
  saveCaseTag,
  toggleCaseTagStatus,
  recognizeCaseLink,
  clearCaseRecognitionPreview,
  fillCaseFormFromPreview,
  createCaseFromPreview,
  resetCaseForm,
  loadAdminCases,
  loadCaseLibraryUrl,
  saveCase,
  editCase,
  toggleCaseStatus,
  deleteCase,
  saveCaseLibraryUrl,
  loadCaseBatchFile,
  recognizeCaseBatch,
  toggleCaseBatchAll,
  saveSelectedCases,
  clearCaseBatch,
});
