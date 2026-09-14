// ===== Audio Course Management =====
let audioCoursesCache = [];
let audioCoursePreviewAudio = null;

function fmtAudioDuration(seconds) {
  const total = Number(seconds) || 0;
  if (total <= 0) return '';
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${String(secs).padStart(2, '0')}`;
}

function audioCourseMeta(item) {
  const parts = [];
  if (item.series) parts.push(item.series + (item.episode ? ` 第${item.episode}讲` : ''));
  const duration = fmtAudioDuration(item.duration_seconds);
  if (duration) parts.push(duration);
  if (item.tags) parts.push(item.tags);
  if (!item.audio_url) parts.push('未设置音频');
  return esc(parts.join(' · '));
}

async function loadAdminAudioCourses() {
  try {
    const res = await fetch(`${API}/api/admin/audio-courses`, {
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    audioCoursesCache = data.courses || [];
    renderAudioCoursesList();
  } catch {
    showToast('课程列表加载失败', 'error');
  }
}

function renderAudioCoursesList() {
  const box = document.getElementById('admin-audio-courses-list');
  if (!box) return;
  if (!audioCoursesCache.length) {
    box.innerHTML = '<div class="empty-state" style="padding:14px">暂无音频课程</div>';
    return;
  }
  box.innerHTML = audioCoursesCache.map(item => `
    <div class="admin-list-item" style="padding:10px 0">
      <div style="min-width:0">
        <div class="item-title">
          ${esc(item.title)}
          ${item.pinned ? '<span class="tag">置顶</span>' : ''}
          ${item.show_on_home ? '<span class="tag">首页</span>' : ''}
          ${item.status ? '' : '<span class="tag tag-rose">已隐藏</span>'}
        </div>
        <div class="item-meta">${audioCourseMeta(item)}</div>
      </div>
      <div class="item-actions">
        ${item.audio_url ? `<button class="btn btn-secondary btn-sm" onclick="previewAudioCourse(${item.id})">试听</button>` : ''}
        <button class="btn btn-secondary btn-sm" onclick="toggleAudioCourseFlag(${item.id}, 'pinned', ${item.pinned ? 0 : 1})">${item.pinned ? '取消置顶' : '置顶'}</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleAudioCourseFlag(${item.id}, 'show_on_home', ${item.show_on_home ? 0 : 1})">${item.show_on_home ? '取消首页' : '首页'}</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleAudioCourseStatus(${item.id}, ${item.status ? 0 : 1})">${item.status ? '隐藏' : '显示'}</button>
        <button class="btn btn-secondary btn-sm" onclick="editAudioCourse(${item.id})">编辑</button>
        <button class="btn btn-secondary btn-sm" onclick="deleteAudioCourse(${item.id})">删除</button>
      </div>
    </div>
  `).join('');
}

function previewAudioCourse(id) {
  const item = audioCoursesCache.find(course => course.id === id);
  if (!item || !item.audio_url) return;
  if (audioCoursePreviewAudio) {
    audioCoursePreviewAudio.pause();
  }
  audioCoursePreviewAudio = new Audio(item.audio_url);
  audioCoursePreviewAudio.play().catch(() => showToast('音频播放失败', 'error'));
}

function resetAudioCourseForm() {
  document.getElementById('audio-course-editing-id').value = '';
  document.getElementById('audio-course-form-title').textContent = '新增音频课程';
  ['audio-course-title', 'audio-course-series', 'audio-course-audio-url',
   'audio-course-external-url', 'audio-course-tags', 'audio-course-summary',
   'audio-course-content'].forEach((id) => {
    document.getElementById(id).value = '';
  });
  document.getElementById('audio-course-episode').value = '0';
  document.getElementById('audio-course-duration').value = '0';
  document.getElementById('audio-course-sort-order').value = '0';
  document.getElementById('audio-course-status').checked = true;
  document.getElementById('audio-course-pinned').checked = false;
  document.getElementById('audio-course-home').checked = false;
  document.getElementById('audio-course-audio-file').value = '';
  document.getElementById('audio-course-upload-status').textContent = '';
}

function editAudioCourse(id) {
  const item = audioCoursesCache.find(course => course.id === id);
  if (!item) return showToast('课程不存在', 'error');
  document.getElementById('audio-course-editing-id').value = item.id;
  document.getElementById('audio-course-form-title').textContent = '编辑音频课程';
  document.getElementById('audio-course-title').value = item.title || '';
  document.getElementById('audio-course-series').value = item.series || '';
  document.getElementById('audio-course-episode').value = item.episode || 0;
  document.getElementById('audio-course-duration').value = item.duration_seconds || 0;
  document.getElementById('audio-course-audio-url').value = item.audio_url || '';
  document.getElementById('audio-course-external-url').value = item.external_url || '';
  document.getElementById('audio-course-tags').value = item.tags || '';
  document.getElementById('audio-course-summary').value = item.summary || '';
  document.getElementById('audio-course-content').value = item.content || '';
  document.getElementById('audio-course-sort-order').value = item.sort_order || 0;
  document.getElementById('audio-course-status').checked = !!item.status;
  document.getElementById('audio-course-pinned').checked = !!item.pinned;
  document.getElementById('audio-course-home').checked = !!item.show_on_home;
  document.getElementById('audio-course-upload-status').textContent = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function uploadAudioCourseFile(input) {
  const file = input.files && input.files[0];
  const status = document.getElementById('audio-course-upload-status');
  if (!file) return;
  status.textContent = '上传中...';
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(`${API}/api/admin/audio-courses/upload-audio`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` },
      body: formData,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = '';
      input.value = '';
      let message = data.error;
      if (!message && res.status === 413) {
        message = '音频超过服务器允许的大小（413），请压缩后重试，或让运维调高上传上限';
      }
      if (!message) message = `音频上传失败（${res.status}）`;
      return showToast(message, 'error');
    }
    document.getElementById('audio-course-audio-url').value = data.url || '';
    if (data.duration_seconds) {
      document.getElementById('audio-course-duration').value = data.duration_seconds;
    }
    status.textContent = `已上传：${data.url}`;
  } catch {
    status.textContent = '';
    showToast('音频上传失败', 'error');
  }
}

async function saveAudioCourse() {
  const editingId = document.getElementById('audio-course-editing-id').value;
  const payload = {
    title: document.getElementById('audio-course-title').value.trim(),
    series: document.getElementById('audio-course-series').value.trim(),
    episode: Number(document.getElementById('audio-course-episode').value) || 0,
    duration_seconds: Number(document.getElementById('audio-course-duration').value) || 0,
    audio_url: document.getElementById('audio-course-audio-url').value.trim(),
    external_url: document.getElementById('audio-course-external-url').value.trim(),
    tags: document.getElementById('audio-course-tags').value.trim(),
    summary: document.getElementById('audio-course-summary').value.trim(),
    content: document.getElementById('audio-course-content').value.trim(),
    sort_order: Number(document.getElementById('audio-course-sort-order').value) || 0,
    status: document.getElementById('audio-course-status').checked ? 1 : 0,
    pinned: document.getElementById('audio-course-pinned').checked ? 1 : 0,
    show_on_home: document.getElementById('audio-course-home').checked ? 1 : 0,
  };
  if (!payload.title) return showToast('请填写标题', 'error');
  if (!payload.audio_url && !payload.external_url) {
    return showToast('请上传音频或填写音频地址', 'error');
  }
  const url = editingId
    ? `${API}/api/admin/audio-courses/${editingId}`
    : `${API}/api/admin/audio-courses`;
  try {
    const res = await fetch(url, {
      method: editingId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return showToast(data.error || '保存失败', 'error');
    showToast(editingId ? '课程已更新' : '课程已创建', 'success');
    resetAudioCourseForm();
    loadAdminAudioCourses();
  } catch {
    showToast('保存失败', 'error');
  }
}

async function toggleAudioCourseStatus(id, status) {
  try {
    const res = await fetch(`${API}/api/admin/audio-courses/${id}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) return showToast('操作失败', 'error');
    loadAdminAudioCourses();
  } catch {
    showToast('操作失败', 'error');
  }
}

async function toggleAudioCourseFlag(id, flag, value) {
  try {
    const res = await fetch(`${API}/api/admin/audio-courses/${id}/flag`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getToken()}` },
      body: JSON.stringify({ flag, value }),
    });
    if (!res.ok) return showToast('操作失败', 'error');
    loadAdminAudioCourses();
  } catch {
    showToast('操作失败', 'error');
  }
}

async function deleteAudioCourse(id) {
  if (!confirm('确定删除该课程？')) return;
  try {
    const res = await fetch(`${API}/api/admin/audio-courses/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${getToken()}` },
    });
    if (!res.ok) return showToast('删除失败', 'error');
    showToast('课程已删除', 'success');
    loadAdminAudioCourses();
  } catch {
    showToast('删除失败', 'error');
  }
}
