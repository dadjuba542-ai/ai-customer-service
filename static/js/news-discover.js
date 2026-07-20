/* ===== Survey ===== */
function checkSurvey() {
  const key = 'survey_count';
  let count = parseInt(localStorage.getItem(key) || '0', 10);
  count++;
  localStorage.setItem(key, count);
  if (count % 10 === 0) {
    document.getElementById('survey-overlay').classList.add('active');
  }
}

function submitSurvey(score) {
  document.getElementById('survey-overlay').classList.remove('active');
  fetch(`${API_BASE}/api/survey`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ score }),
  }).catch(() => {});
}

async function submitReply() {
  if (!currentQId) return;
  const content = document.getElementById('qdetail-reply-input').value.trim();
  if (!content) { showToast('请输入回复内容', 'error'); return; }
  try {
    const res = await fetch(`${API_BASE}/api/community/questions/${currentQId}/replies`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ nickname: '匿名用户', content, viewer_id: getViewerId() }),
    });
    if (res.ok) {
      showToast('评论已提交，精选后公开展示', 'success');
      showQDetail(currentQId);
    } else {
      const data = await res.json();
      showToast(data.error || '评论失败', 'error');
    }
  } catch { showToast('网络错误', 'error'); }
}

async function loadSession(itemIds) {
  if (!itemIds || itemIds.length === 0) return;
  const firstItemId = itemIds[0];
  try {
    const res = await fetch(`${API_BASE}/api/history/${firstItemId}`, { headers: authHeaders() });
    if (!res.ok) return;
    const first = await res.json();
    const agent = AGENTS.find(a => a.type === first.query_type) || AGENTS[0];
    if (agent) state.activeAgentId = agent.id;
    renderAgentTabs();
    state.messages = [];
    for (const id of itemIds.reverse()) {
      try {
        const r = await fetch(`${API_BASE}/api/history/${id}`, { headers: authHeaders() });
        if (r.ok) {
          const item = await r.json();
          addMessage({ id: Date.now(), role: 'user', content: item.user_message, time: formatTime(item.created_at, true) });
          if (item.bot_response) addMessage({ id: Date.now() + 1, role: 'bot', content: item.bot_response, time: formatTime(item.created_at, true), agentId: state.activeAgentId, historyId: item.id, feedback: item.feedback });
        }
      } catch {}
    }
    switchView('chat');
  } catch { showToast('加载会话失败', 'error'); }
}

/* ===== News ===== */
async function loadNews() {
  try {
    const [homeRes, bulletinRes] = await Promise.all([
      fetch(`${API_BASE}/api/news?mode=home&limit=3`),
      fetch(`${API_BASE}/api/news?mode=bulletin&limit=3`),
    ]);
    if (homeRes.ok) {
      const home = await homeRes.json();
      const bulletin = bulletinRes.ok ? await bulletinRes.json() : { news: [] };
      renderNews(home.news, bulletin.news);
    }
  } catch {}
}

function renderNews(news, bulletinNews = []) {
  const container = document.getElementById('home-news');
  renderHomeBulletin(bulletinNews);
  if (!news || news.length === 0) {
    container.innerHTML = '<div class="news-empty">暂无资讯</div>';
    return;
  }
  container.innerHTML = news.map(item => `
    <button class="news-card" onclick="showNewsDetail(${item.id})">
      <div class="news-card-img">${item.image_url
        ? renderImage(item.image_url, item.title || '')
        : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <div class="news-card-body">
        <div class="news-card-title">${escapeHtml(item.title)}</div>
        <div class="news-card-summary">${escapeHtml(item.summary || item.content || '')}</div>
        <div class="news-card-time">${formatTime(item.created_at)}</div>
      </div>
    </button>
  `).join('');
}

function renderHomeBulletin(news) {
  const bulletin = document.getElementById('home-bulletin');
  const track = document.getElementById('home-bulletin-track');
  if (!bulletin || !track) return;
  const items = (news || []).slice(0, 3);
  if (bulletinTimer) {
    clearInterval(bulletinTimer);
    bulletinTimer = null;
  }
  if (!items.length) {
    track.innerHTML = '';
    bulletin.hidden = true;
    return;
  }
  const renderItem = (item) => {
    const title = String(item.title || '查看最新内容').trim();
    const chars = Array.from(title);
    const shortTitle = chars.length > 18 ? `${chars.slice(0, 17).join('')}…` : title;
    track.innerHTML = `<button class="bulletin-item" title="${escapeHtml(title)}" onclick="showNewsDetail(${Number(item.id)})"><span>${escapeHtml(shortTitle)}</span></button>`;
    track.classList.remove('bulletin-enter');
    void track.offsetWidth;
    track.classList.add('bulletin-enter');
  };
  renderItem(items[0]);
  bulletin.hidden = false;
  if (items.length > 1) {
    let index = 0;
    bulletinTimer = setInterval(() => {
      index = (index + 1) % items.length;
      renderItem(items[index]);
    }, 4000);
  }
}

/* ===== Discover ===== */
let discoverPage = 1;
let discoverTotal = 0;
let discoverPages = 0;
let carouselTimer = null;
let carouselIdx = 0;
let currentCategory = '';
const newsDetailCache = new Map();

async function loadDiscover(category) {
  if (category !== undefined) currentCategory = category || '';
  try {
    let url = `${API_BASE}/api/news?mode=discover&page=1&limit=10`;
    if (currentCategory) url += `&category=${encodeURIComponent(currentCategory)}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    discoverPage = data.page.page;
    discoverTotal = data.page.total;
    discoverPages = data.page.pages;
    renderCategories(data.categories || []);
    renderCarousel(data.pinned || []);
    renderDiscoverList(data.news || []);
    const more = document.getElementById('discover-more-wrap');
    more.style.display = discoverPage < discoverPages ? 'flex' : 'none';
  } catch {}
}

function renderCategories(categories) {
  const container = document.getElementById('category-tabs');
  container.innerHTML = `<button class="category-tab${currentCategory === '' ? ' active' : ''}" onclick="filterCategory('')">全部</button>` +
    categories.map(c => `<button class="category-tab${currentCategory === c ? ' active' : ''}" onclick="filterCategory('${escapeHtml(c)}')">${escapeHtml(c)}</button>`).join('');
}

function filterCategory(cat) {
  currentCategory = cat;
  document.querySelectorAll('.category-tab').forEach(b => b.classList.toggle('active', b.textContent === (cat || '全部')));
  loadDiscover();
}

function renderCarousel(pinned) {
  const wrap = document.getElementById('discover-carousel-wrap');
  const container = document.getElementById('discover-carousel');
  const dots = document.getElementById('carousel-dots');
  if (!pinned.length) { wrap.style.display = 'none'; stopCarouselAuto(); return; }
  wrap.style.display = 'block';
  carouselIdx = 0;

  container.innerHTML = pinned.map(p => `
    <button class="carousel-slide" onclick="showNewsDetail(${p.id})">
      <div class="carousel-img">${p.image_url
        ? renderImage(p.image_url, p.title || '', '', { eager: true })
        : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <div class="carousel-caption">
        <div class="carousel-pin">📌 置顶</div>
        <div class="carousel-title">${escapeHtml(p.title)}</div>
      </div>
    </button>
  `).join('');

  dots.innerHTML = pinned.map((_, i) => `<span class="carousel-dot${i === 0 ? ' active' : ''}"></span>`).join('');

  container.addEventListener('scroll', () => {
    const idx = Math.round(container.scrollLeft / container.clientWidth);
    if (idx !== carouselIdx) { carouselIdx = idx; updateCarouselDots(); }
  }, { once: false });

  stopCarouselAuto();
  if (pinned.length > 1) startCarouselAuto();
}

function updateCarouselDots() {
  document.querySelectorAll('.carousel-dot').forEach((d, i) => d.classList.toggle('active', i === carouselIdx));
}

function startCarouselAuto() {
  carouselTimer = setInterval(() => {
    const c = document.getElementById('discover-carousel');
    if (!c) return;
    carouselIdx = (carouselIdx + 1) % c.children.length;
    c.scrollTo({ left: carouselIdx * c.clientWidth, behavior: 'smooth' });
    updateCarouselDots();
  }, 4000);
}

function stopCarouselAuto() {
  clearInterval(carouselTimer);
  carouselTimer = null;
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopCarouselAuto();
    if (state.speech.phase === 'recording') stopVoiceRecording();
    else if (state.speech.phase === 'connecting') cancelVoiceInput();
  }
  else if (state.currentView === 'discover') startCarouselAuto();
});

window.addEventListener('pagehide', () => {
  if (state.speech.controller) state.speech.controller.cancel();
  if (state.speech.stream) state.speech.stream.getTracks().forEach((track) => track.stop());
});

function renderDiscoverList(news) {
  const container = document.getElementById('discover-list');
  if (!news || news.length === 0) {
    container.innerHTML = '<div class="discover-empty">暂无更多资讯</div>';
    return;
  }
  container.innerHTML = news.map(item => `
    <button class="news-card" onclick="showNewsDetail(${item.id})">
      <div class="news-card-img">${item.image_url
        ? renderImage(item.image_url, item.title || '')
        : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <div class="news-card-body">
        <div class="news-card-title">${escapeHtml(item.title)}</div>
        <div class="news-card-summary">${escapeHtml(item.summary || item.content || '')}</div>
        <div class="news-card-time">${formatTime(item.created_at)}</div>
      </div>
    </button>
  `).join('');
}

async function loadMoreNews() {
  if (discoverPage >= discoverPages) return;
  const btn = document.querySelector('.discover-more-btn');
  btn.textContent = '加载中...';
  btn.disabled = true;
  try {
    let url = `${API_BASE}/api/news?mode=discover&page=${discoverPage + 1}&limit=10`;
    if (currentCategory) url += `&category=${encodeURIComponent(currentCategory)}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();
    discoverPage = data.page.page;
    const existing = document.getElementById('discover-list');
    data.news.forEach(item => {
      const el = document.createElement('button');
      el.className = 'news-card';
      el.onclick = () => showNewsDetail(item.id);
      el.innerHTML = `
        <div class="news-card-img">${item.image_url
          ? renderImage(item.image_url, item.title || '')
          : `<div class="img-placeholder"><i class="ph ph-image"></i></div>`}
        </div>
        <div class="news-card-body">
          <div class="news-card-title">${escapeHtml(item.title)}</div>
          <div class="news-card-summary">${escapeHtml(item.summary || item.content || '')}</div>
          <div class="news-card-time">${formatTime(item.created_at)}</div>
        </div>`;
      existing.appendChild(el);
    });
    btn.textContent = '加载更多';
    btn.disabled = false;
    if (discoverPage >= discoverPages) {
      document.getElementById('discover-more-wrap').style.display = 'none';
    }
  } catch {
    btn.textContent = '加载失败，重试';
    btn.disabled = false;
  }
}

/* ===== Hot Questions ===== */
async function loadHotQuestions() {
  try {
    const res = await fetch(`${API_BASE}/api/history/hot-questions`);
    if (res.ok) {
      const data = await res.json();
      renderHotQuestions(data.questions);
    }
  } catch {}
}

async function loadExampleQuestions() {
  const container = document.getElementById('example-question-list');
  if (!container) return;
  try {
    const res = await fetch(`${API_BASE}/api/example-questions`);
    const data = await res.json();
    const questions = Array.isArray(data.questions) ? data.questions : [];
    container.innerHTML = questions.map((question, index) => {
      const agentId = index === 1 ? 'coder' : index === 3 ? 'translator' : 'aura';
      return `<button onclick="quickSend('${agentId}', '${escapeHtml(question).replace(/'/g, "\\'")}')">${escapeHtml(question)}</button>`;
    }).join('');
  } catch {
    container.innerHTML = '';
  }
}

function renderHotQuestions(questions) {
  const container = document.getElementById('hot-tags');
  if (!questions || questions.length === 0) {
    container.innerHTML = '<div class="news-empty">暂无热门问题</div>';
    return;
  }
  const maxCount = Math.max(...questions.map(q => q.count));
  container.innerHTML = questions.map(q => {
    const ratio = q.count / maxCount;
    const size = 12 + Math.round(ratio * 6);
    const opacity = 0.5 + ratio * 0.5;
    return `<span class="hot-tag" style="font-size:${size}px;opacity:${opacity}" onclick="quickSend('aura','${escapeHtml(q.text)}')">${escapeHtml(q.text)}</span>`;
  }).join('');
}

/* ===== News Detail ===== */
async function showNewsDetail(id) {
  const cached = newsDetailCache.get(Number(id));
  if (cached) {
    renderNewsDetail(cached);
    document.getElementById('news-detail-overlay').classList.add('active');
    refreshNewsDetail(id);
    return;
  }
  renderNewsDetailLoading();
  document.getElementById('news-detail-overlay').classList.add('active');
  try {
    const res = await fetch(`${API_BASE}/api/news/${id}`);
    if (!res.ok) throw new Error('新闻加载失败');
    const item = await res.json();
    newsDetailCache.set(Number(id), item);
    renderNewsDetail(item);
  } catch {
    renderNewsDetailError(id);
  }
}

async function refreshNewsDetail(id) {
  try {
    const res = await fetch(`${API_BASE}/api/news/${id}`);
    if (!res.ok) return;
    const item = await res.json();
    newsDetailCache.set(Number(id), item);
  } catch {}
}

function renderNewsDetailLoading() {
  const container = document.getElementById('news-detail-content');
  if (!container) return;
  container.innerHTML = `
    <div class="news-detail-image"><div class="placeholder"><i class="ph ph-newspaper"></i></div></div>
    <h1 class="news-detail-title">正在加载资讯...</h1>
    <div class="news-detail-meta">请稍候</div>
    <div class="news-detail-body"><p>正在打开内容。</p></div>
  `;
}

function renderNewsDetailError(id) {
  const container = document.getElementById('news-detail-content');
  if (!container) return;
  container.innerHTML = `
    <div class="news-detail-image"><div class="placeholder"><i class="ph ph-warning-circle"></i></div></div>
    <h1 class="news-detail-title">加载失败</h1>
    <div class="news-detail-body"><p>资讯加载失败，请检查网络后重试。</p><button class="discover-more-btn" onclick="showNewsDetail(${Number(id)})">重新加载</button></div>
  `;
}

function renderNewsDetail(item) {
  const container = document.getElementById('news-detail-content');
  if (!container) return;
  container.innerHTML = `
    <div class="news-detail-image">${item.image_url
      ? renderImage(item.image_url, item.title || '', '', { thumb: false })
      : `<div class="placeholder"><i class="ph ph-image"></i></div>`}
    </div>
    <h1 class="news-detail-title">${escapeHtml(item.title)}</h1>
    <div class="news-detail-meta">${formatTime(item.created_at)}</div>
    <div class="news-detail-body">${prepareNewsDetailContent(item.content || item.summary || '暂无内容')}</div>
  `;
}

function prepareNewsDetailContent(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  div.querySelectorAll('img').forEach(img => {
    img.setAttribute('loading', 'lazy');
    img.setAttribute('decoding', 'async');
  });
  return div.innerHTML;
}

function closeNewsDetail() {
  document.getElementById('news-detail-overlay').classList.remove('active');
}

