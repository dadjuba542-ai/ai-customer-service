/* ===== Audio Courses (前台独立问答入口) ===== */
const audioCourseState = { tag: '', query: '', loadedTags: false };
let audioCoursePlayback = null;

/* 属性专用转义：escapeHtml 不转义引号，不能用于 src/href/data-* 等属性位置。 */
function escapeAttr(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

function formatAudioDuration(seconds) {
  const total = Number(seconds) || 0;
  if (total <= 0) return '';
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${String(secs).padStart(2, '0')}`;
}

function audioCourseCardHtml(item) {
  const meta = [];
  if (item.series) meta.push(item.series + (item.episode ? ` 第${item.episode}讲` : ''));
  const duration = formatAudioDuration(item.duration_seconds);
  if (duration) meta.push(duration);
  return `<div class="audio-course-card" role="button" tabindex="0" onclick="openAudioCourse(${Number(item.id)})">
    <span class="audio-course-play" aria-hidden="true"><svg class="icon icon-play" viewBox="0 0 24 24" width="24" height="24" fill="none"><path d="M8 5.4 18.6 12 8 18.6V5.4z" fill="currentColor"/></svg></span>
    <div class="audio-course-body">
      <div class="audio-course-title">${escapeHtml(item.title || '')}</div>
      ${meta.length ? `<div class="audio-course-meta">${escapeHtml(meta.join(' · '))}</div>` : ''}
      ${item.summary ? `<div class="audio-course-summary">${escapeHtml(item.summary)}</div>` : ''}
    </div>
  </div>`;
}

function renderAudioCourseList(items, host) {
  if (!host) return;
  if (!items || !items.length) {
    host.innerHTML = '';
    return;
  }
  host.innerHTML = items.map(audioCourseCardHtml).join('');
}

let homeAudioTabLoaded = false;
let homeAudioPrefetched = false;

function initHomeAudioTab() {
  if (!featureEnabled('audio_courses')) return;
  prefetchHomeAudioCourses();
}

function hideHomeAudioTab() {
  const btn = document.querySelector('.home-tab-btn[data-tab="audio"]');
  if (btn) btn.hidden = true;
  const audio = document.getElementById('home-tab-audio');
  if (audio && !audio.hidden) switchHomeTab('quick');
}

async function prefetchHomeAudioCourses() {
  if (homeAudioPrefetched) return;
  homeAudioPrefetched = true;
  try {
    const res = await fetch(`${API_BASE}/api/audio-courses?mode=home&limit=6`);
    if (!res.ok) return;
    const data = await res.json();
    const items = data.items || [];
    if (!items.length) {
      hideHomeAudioTab();
      return;
    }
    homeAudioTabLoaded = true;
    renderAudioCourseList(items, document.getElementById('home-audio-list'));
  } catch {
    /* 预取失败保留入口，点击时再试 */
  }
}

function switchHomeTab(mode) {
  const isAudio = mode === 'audio';
  if (isAudio && !featureEnabled('audio_courses')) return;
  document.querySelectorAll('.home-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === mode);
  });
  const quick = document.getElementById('home-tab-quick');
  const audio = document.getElementById('home-tab-audio');
  if (quick) quick.hidden = isAudio;
  if (audio) audio.hidden = !isAudio;
  if (isAudio && !homeAudioTabLoaded) {
    loadHomeAudioCourses();
  }
}

async function loadHomeAudioCourses() {
  if (!featureEnabled('audio_courses')) return;
  const host = document.getElementById('home-audio-list');
  if (!host) return;
  host.innerHTML = '<div class="audio-loading">加载中...</div>';
  try {
    const res = await fetch(`${API_BASE}/api/audio-courses?mode=home&limit=6`);
    if (!res.ok) throw new Error('load failed');
    const data = await res.json();
    const items = data.items || [];
    if (!items.length) {
      host.innerHTML = '<div class="audio-empty">暂无音频课程</div>';
      return;
    }
    homeAudioTabLoaded = true;
    renderAudioCourseList(items, host);
  } catch {
    host.innerHTML = '<div class="audio-empty">音频课程加载失败</div>';
  }
}

async function loadAudioCoursesPage() {
  if (!featureEnabled('audio_courses')) return;
  bindAudioTagEvents();
  await loadAudioCourseTags();
  await loadAudioCourseList();
}

function bindAudioTagEvents() {
  const host = document.getElementById('audio-tags');
  if (!host || host.dataset.bound === '1') return;
  host.dataset.bound = '1';
  host.addEventListener('click', (event) => {
    const btn = event.target.closest('.audio-tag');
    if (!btn) return;
    filterAudioCourseTag(btn.dataset.tag || '');
  });
}

async function loadAudioCourseTags() {
  const host = document.getElementById('audio-tags');
  if (!host || audioCourseState.loadedTags) return;
  try {
    const res = await fetch(`${API_BASE}/api/audio-courses/tags`);
    if (!res.ok) return;
    const data = await res.json();
    const tags = (data.tags || []).slice(0, 12);
    audioCourseState.loadedTags = true;
    host.innerHTML = tags.map(tag => `
      <button type="button" class="audio-tag" data-tag="${escapeAttr(tag)}">${escapeHtml(tag)}</button>
    `).join('');
  } catch {
    /* 标签加载失败不阻塞列表 */
  }
}

async function loadAudioCourseList() {
  const host = document.getElementById('audio-list');
  const empty = document.getElementById('audio-empty');
  if (!host) return;
  if (!featureEnabled('audio_courses')) return;
  host.innerHTML = '<div class="audio-loading">加载中...</div>';
  if (empty) empty.hidden = true;
  const params = new URLSearchParams();
  if (audioCourseState.query) params.set('q', audioCourseState.query);
  else if (audioCourseState.tag) params.set('tag', audioCourseState.tag);
  params.set('limit', '30');
  const url = audioCourseState.query
    ? `${API_BASE}/api/audio-courses/search?${params.toString()}`
    : `${API_BASE}/api/audio-courses?${params.toString()}`;
  try {
    const res = await fetch(url);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '加载失败');
    const items = data.items || [];
    renderAudioCourseList(items, host);
    if (!items.length) {
      host.innerHTML = '';
      if (empty) empty.hidden = false;
    }
  } catch {
    host.innerHTML = '';
    showToast('音频课程加载失败', 'error');
  }
}

function audioCourseSearch() {
  const input = document.getElementById('audio-search-input');
  audioCourseState.query = (input?.value || '').trim();
  audioCourseState.tag = '';
  document.querySelectorAll('.audio-tag').forEach(el => el.classList.remove('active'));
  loadAudioCourseList();
}

function filterAudioCourseTag(tag) {
  audioCourseState.tag = tag;
  audioCourseState.query = '';
  const input = document.getElementById('audio-search-input');
  if (input) input.value = '';
  document.querySelectorAll('.audio-tag').forEach(el => {
    el.classList.toggle('active', el.dataset.tag === tag);
  });
  loadAudioCourseList();
}

function stopAudioCoursePlayback() {
  if (audioCoursePlayback) {
    audioCoursePlayback.pause();
    audioCoursePlayback = null;
  }
}

function ensureAudioDrawer() {
  let overlay = document.getElementById('audio-drawer-overlay');
  if (overlay) return overlay;
  overlay = document.createElement('div');
  overlay.id = 'audio-drawer-overlay';
  overlay.className = 'audio-drawer-overlay';
  overlay.innerHTML = `
    <div class="audio-drawer-panel" onclick="event.stopPropagation()">
      <div class="audio-drawer-header">
        <div class="audio-drawer-kicker">音频课程</div>
        <button type="button" class="audio-drawer-close" aria-label="关闭" onclick="closeAudioDrawer()">
          <svg class="icon icon-x" viewBox="0 0 24 24" width="24" height="24" fill="none"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12 19 6.41z" fill="currentColor"/></svg>
        </button>
      </div>
      <div class="audio-drawer-body" id="audio-drawer-body"></div>
    </div>`;
  overlay.addEventListener('click', () => closeAudioDrawer());
  document.body.appendChild(overlay);
  return overlay;
}

async function openAudioCourse(id) {
  if (!featureEnabled('audio_courses')) return;
  ensureAudioDrawer();
  const body = document.getElementById('audio-drawer-body');
  if (body) body.innerHTML = '<div class="audio-loading">加载中...</div>';
  try {
    const res = await fetch(`${API_BASE}/api/audio-courses/${id}`);
    const item = await res.json();
    if (!res.ok) {
      showToast(item.error || '课程不存在', 'error');
      closeAudioDrawer();
      return;
    }
    renderAudioCourseDetail(item);
  } catch {
    showToast('音频加载失败', 'error');
    closeAudioDrawer();
  }
}

function renderAudioCourseDetail(item) {
  const body = document.getElementById('audio-drawer-body');
  if (!body) return;
  const meta = [];
  if (item.series) meta.push(item.series + (item.episode ? ` 第${item.episode}讲` : ''));
  const duration = formatAudioDuration(item.duration_seconds);
  if (duration) meta.push(duration);
  stopAudioCoursePlayback();
  body.innerHTML = `
    <h2 class="audio-detail-title">${escapeHtml(item.title || '')}</h2>
    ${meta.length ? `<div class="audio-detail-meta">${escapeHtml(meta.join(' · '))}</div>` : ''}
    ${item.audio_url ? `<audio class="audio-detail-player" id="audio-detail-player" controls preload="none" src="${escapeAttr(item.audio_url)}"></audio>` : ''}
    ${item.summary ? `<div class="audio-detail-section"><strong>课程简介</strong><p>${escapeHtml(item.summary)}</p></div>` : ''}
    ${item.content ? `<div class="audio-detail-section"><strong>课程内容</strong><p>${escapeHtml(item.content).replace(/\n/g, '<br>')}</p></div>` : ''}
    ${item.external_url ? `<a class="audio-detail-external" href="${escapeAttr(item.external_url)}" target="_blank" rel="noopener noreferrer">在外部页面收听</a>` : ''}
  `;
  const player = document.getElementById('audio-detail-player');
  if (player) {
    audioCoursePlayback = player;
    player.play().catch(() => {});
  }
}

function closeAudioDrawer() {
  stopAudioCoursePlayback();
  const overlay = document.getElementById('audio-drawer-overlay');
  if (overlay) overlay.remove();
}
