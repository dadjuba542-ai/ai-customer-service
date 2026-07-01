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
        <div class="field"><label>封面图 URL</label><input type="text" id="case-preview-image-url" value="${esc(fields.image_url || '')}"></div>
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
    image_url: get('case-preview-image-url'),
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
  const preview = document.getElementById('case-image-preview');
  if (fields.image_url) {
    preview.src = fields.image_url;
    preview.dataset.url = fields.image_url;
    preview.classList.remove('hidden');
    document.getElementById('case-upload-placeholder').classList.add('hidden');
  } else {
    preview.src = '';
    preview.dataset.url = '';
    preview.classList.add('hidden');
    document.getElementById('case-upload-placeholder').classList.remove('hidden');
  }
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
  const preview = document.getElementById('case-image-preview');
  preview.src = '';
  preview.dataset.url = '';
  preview.classList.add('hidden');
  document.getElementById('case-upload-placeholder').classList.remove('hidden');
  document.getElementById('case-image-input').value = '';
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
          ${item.image_url ? `<img src="${esc(item.image_url)}" style="width:58px;height:58px;border-radius:8px;object-fit:cover">` : `<div style="width:58px;height:58px;border-radius:8px;background:var(--slate-100);display:flex;align-items:center;justify-content:center;color:var(--slate-400)"><i class="ph ph-file-text"></i></div>`}
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
  const preview = document.getElementById('case-image-preview');
  const payload = {
    title,
    customer_profile: document.getElementById('case-customer-profile').value.trim(),
    symptom_tags: document.getElementById('case-symptom-tags').value.trim(),
    product_tags: document.getElementById('case-product-tags').value.trim(),
    scenario: document.getElementById('case-scenario').value.trim(),
    summary: document.getElementById('case-summary').value.trim(),
    content: document.getElementById('case-content').value.trim(),
    image_url: preview.classList.contains('hidden') ? '' : (preview.dataset.url || ''),
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
    const preview = document.getElementById('case-image-preview');
    if (item.image_url) {
      preview.src = item.image_url;
      preview.dataset.url = item.image_url;
      preview.classList.remove('hidden');
      document.getElementById('case-upload-placeholder').classList.add('hidden');
    } else {
      preview.src = '';
      preview.dataset.url = '';
      preview.classList.add('hidden');
      document.getElementById('case-upload-placeholder').classList.remove('hidden');
    }
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

async function uploadCaseImage(input) {
  if (!input.files[0]) return;
  const formData = new FormData();
  formData.append('file', input.files[0]);
  try {
    const res = await fetch(`${API}/api/admin/upload`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) return showToast(data.error || '上传失败', 'error');
    const preview = document.getElementById('case-image-preview');
    preview.src = data.url;
    preview.dataset.url = data.url;
    preview.classList.remove('hidden');
    document.getElementById('case-upload-placeholder').classList.add('hidden');
  } catch { showToast('上传失败', 'error'); }
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
  uploadCaseImage,
  saveCaseLibraryUrl,
});
