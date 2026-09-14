/* ===== Research Survey =====
 * 调研问卷：问题定义在此处统一维护，前台弹窗与后台展示共用。
 * type: single（单选）| multi（多选）| rating（1-5 评分）| text（开放题）
 */
const RESEARCH_QUESTIONS = [
  {
    id: 'duration',
    type: 'single',
    required: true,
    title: '你使用 AI宝儿多久了？',
    options: ['刚开始用', '1个月以内', '1-3个月', '3-6个月', '半年以上'],
  },
  {
    id: 'usage',
    type: 'multi',
    required: true,
    title: '你经常使用哪些功能？',
    options: ['AI 问答', '产品资料', '健康资讯', '社区问答', '转人工营养师'],
  },
  {
    id: 'satisfaction',
    type: 'rating',
    required: true,
    title: '整体体验满意度（1-5 分）',
    options: ['1', '2', '3', '4', '5'],
  },
  {
    id: 'improve',
    type: 'multi',
    required: false,
    title: '你希望我们优先改进哪些方面？',
    options: ['回答更准确', '回复更及时', '界面更好用', '内容更丰富', '增加新功能', '暂时没有'],
  },
  {
    id: 'comment',
    type: 'text',
    required: false,
    title: '还有什么想告诉我们的？',
    placeholder: '选填，你的建议对我们很重要',
  },
];

function researchQuestionById(qid) {
  return RESEARCH_QUESTIONS.find(q => q.id === qid) || null;
}

function escapeResearch(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

let researchAnswers = {};
let researchBound = false;

function openResearchSurvey() {
  const overlay = document.getElementById('research-overlay');
  if (!overlay) return;
  researchAnswers = {};
  renderResearchQuestions();
  const contact = document.getElementById('research-contact');
  if (contact) contact.value = '';
  const submit = document.getElementById('research-submit');
  if (submit) submit.disabled = false;
  overlay.classList.add('active');
}

function closeResearchSurvey() {
  const overlay = document.getElementById('research-overlay');
  if (overlay) overlay.classList.remove('active');
}

function renderResearchQuestions() {
  const body = document.getElementById('research-body');
  if (!body) return;
  body.innerHTML = RESEARCH_QUESTIONS.map((q, i) => {
    const hint = q.type === 'multi' ? '<span class="research-q-hint">可多选</span>' : '';
    const requiredMark = q.required ? '<span class="research-q-required">*</span>' : '';
    let input;
    if (q.type === 'text') {
      input = `<textarea class="research-text" id="research-q-${escapeResearch(q.id)}" maxlength="500" placeholder="${escapeResearch(q.placeholder || '')}"></textarea>`;
    } else {
      input = `<div class="research-options">${q.options.map(opt =>
        `<button type="button" class="research-option" data-qid="${escapeResearch(q.id)}" data-value="${escapeResearch(opt)}">${escapeResearch(opt)}</button>`
      ).join('')}</div>`;
    }
    return `<div class="research-q"><div class="research-q-title"><span class="research-q-index">${i + 1}</span>${requiredMark}${escapeResearch(q.title)}${hint}</div>${input}</div>`;
  }).join('');
  if (!researchBound) {
    body.addEventListener('click', onResearchOptionClick);
    researchBound = true;
  }
}

function onResearchOptionClick(event) {
  const btn = event.target.closest('.research-option');
  if (!btn) return;
  const qid = btn.dataset.qid;
  const value = btn.dataset.value;
  const question = researchQuestionById(qid);
  if (!question) return;
  const container = btn.parentElement;
  if (question.type === 'multi') {
    const values = Array.isArray(researchAnswers[qid]) ? researchAnswers[qid] : [];
    const idx = values.indexOf(value);
    if (idx >= 0) values.splice(idx, 1); else values.push(value);
    researchAnswers[qid] = values;
    btn.classList.toggle('active', values.includes(value));
  } else {
    researchAnswers[qid] = value;
    container.querySelectorAll('.research-option').forEach(item => {
      item.classList.toggle('active', item === btn);
    });
  }
}

async function submitResearchSurvey() {
  const answers = {};
  RESEARCH_QUESTIONS.forEach(q => {
    if (q.type === 'text') {
      const el = document.getElementById(`research-q-${q.id}`);
      const value = (el && el.value ? el.value : '').trim();
      if (value) answers[q.id] = value;
    } else if (researchAnswers[q.id] !== undefined) {
      answers[q.id] = researchAnswers[q.id];
    }
  });

  for (const q of RESEARCH_QUESTIONS) {
    if (!q.required) continue;
    const value = answers[q.id];
    if (value === undefined || (Array.isArray(value) && value.length === 0)) {
      if (typeof showToast === 'function') showToast('请先完成带 * 的问题', 'error');
      return;
    }
  }

  const contactEl = document.getElementById('research-contact');
  const payload = { answers, contact: (contactEl && contactEl.value ? contactEl.value : '').trim() };
  const submit = document.getElementById('research-submit');
  if (submit) submit.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/survey/research`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('failed');
    closeResearchSurvey();
    if (typeof showToast === 'function') showToast('感谢反馈，我们会认真参考', 'success');
  } catch (error) {
    if (typeof showToast === 'function') showToast('提交失败，请稍后再试', 'error');
    if (submit) submit.disabled = false;
  }
}
