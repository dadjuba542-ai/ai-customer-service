/* ===== Scroll to Bottom ===== */
function updateScrollBtn() {
  const container = document.getElementById('chat-messages');
  const btn = document.getElementById('scroll-bottom-btn');
  if (!container || !btn) return;
  const isScrolledUp = container.scrollHeight - container.scrollTop - container.clientHeight > 100;
  btn.classList.toggle('active', isScrolledUp);
}

// Enhanced scrollToBottom with smooth behavior
const origScrollToBottom = scrollToBottom;
scrollToBottom = function() {
  const c = document.getElementById('chat-messages');
  if (c) {
    c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' });
    setTimeout(updateScrollBtn, 200);
  }
};

/* ===== Utilities ===== */
function formatTime(dateStr, short) {
  const d = new Date(dateStr);
  if (short) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
  if (!text) return '';
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

function imageThumbUrl(url) {
  const value = String(url || '');
  if (!value.startsWith('/uploads/')) return value;
  const suffixIndex = value.search(/[?#]/);
  const path = suffixIndex >= 0 ? value.slice(0, suffixIndex) : value;
  const suffix = suffixIndex >= 0 ? value.slice(suffixIndex) : '';
  if (path.includes('_thumb.')) return value;
  const dotIndex = path.lastIndexOf('.');
  if (dotIndex < 0) return `${path}_thumb.jpg${suffix}`;
  return `${path.slice(0, dotIndex)}_thumb${path.slice(dotIndex)}${suffix}`;
}

function renderImage(src, alt = '', className = '', options = {}) {
  if (!src) return '';
  const fullSrc = String(src);
  const displaySrc = options.thumb === false ? fullSrc : imageThumbUrl(fullSrc);
  const fallback = displaySrc !== fullSrc ? ` data-fallback-src="${escapeHtml(fullSrc)}" onerror="this.onerror=null;this.src=this.dataset.fallbackSrc;"` : '';
  const loading = options.eager ? 'eager' : 'lazy';
  const priority = options.eager ? ' fetchpriority="high"' : '';
  return `<img${className ? ` class="${escapeHtml(className)}"` : ''} src="${escapeHtml(displaySrc)}" alt="${escapeHtml(alt)}" loading="${loading}" decoding="async"${priority}${fallback}>`;
}

function showToast(msg, type = 'info') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = type;
  requestAnimationFrame(() => requestAnimationFrame(() => t.classList.add('show')));
  clearTimeout(t._timeout);
  t._timeout = setTimeout(() => t.classList.remove('show'), 3000);
}

/* ===== Products ===== */
let currentProductName = '';

async function loadProducts() {
  try {
    const res = await fetch(`${API_BASE}/api/products`);
    if (!res.ok) return;
    const data = await res.json();
    renderProducts(data.products || [], data.categories || []);
  } catch {}
}

function renderProducts(products, categories) {
  const container = document.getElementById('products-content');
  if (!products.length) {
    container.innerHTML = '<div class="products-empty"><i class="ph ph-package"></i><p>暂无产品</p></div>';
    return;
  }

  const grouped = {};
  for (const p of products) {
    const cat = p.category || '其他';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(p);
  }

  const cats = categories || Object.keys(grouped);

  const colors = ['#8B5CF6', '#3B82F6', '#059669', '#EA580C', '#D97706', '#0284C7'];
  let html = '';
  for (const cat of cats) {
    const c = cat.replace(/\s+/g, '');
    html += `<div class="product-category">
      <h3 class="product-category-title">${escapeHtml(cat)}</h3>
      <div class="product-cloud">`;
    for (const p of grouped[cat]) {
      const c = colors[p.id % colors.length];
      html += `<button class="product-name-tag" style="background:${c}15;color:${c};border-color:${c}30" onclick="showProductDetail(${p.id})">${escapeHtml(p.name)}</button>`;
    }
    html += `</div></div>`;
  }
  container.innerHTML = html;
}

async function showProductDetail(id) {
  try {
    const res = await fetch(`${API_BASE}/api/products/${id}`);
    if (!res.ok) return;
    const item = await res.json();
    currentProductName = item.name;
    document.getElementById('product-cta-btn').textContent = `咨询「${item.name}」`;

    const tags = (item.highlights || '').split(',').filter(t => t.trim());
    const container = document.getElementById('product-detail-content');
    container.innerHTML = `
      <div class="product-detail-image">${item.image_url
        ? renderImage(item.image_url, item.name || '', '', { thumb: false })
        : `<div class="placeholder"><i class="ph ph-image"></i></div>`}
      </div>
      <h1 class="product-detail-name">${escapeHtml(item.name)}</h1>
      ${item.summary ? `<p class="product-detail-summary">${escapeHtml(item.summary)}</p>` : ''}
      ${tags.length ? `<div class="product-detail-tags">${tags.map(t => `<span class="product-tag">${escapeHtml(t.trim())}</span>`).join('')}</div>` : ''}
      ${item.content ? `<div class="product-detail-content">${item.content}</div>` : ''}
    `;
    document.getElementById('product-detail-overlay').classList.add('active');
  } catch {}
}

function closeProductDetail() {
  document.getElementById('product-detail-overlay').classList.remove('active');
}

function consultProduct() {
  const name = currentProductName || '';
  closeProductDetail();
  const agent = AGENTS.find(a => a.type === '产品咨询') || AGENTS[0];
  if (agent) {
    state.activeAgentId = agent.id;
    renderAgentTabs();
  }
  document.getElementById('message-input').value = `${name}的配方是什么？有什么功效？怎么用？`;
  switchView('chat');
  sendMessage();
}

document.addEventListener('input', (e) => {
  if (e.target.id === 'message-input') {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  }
});
