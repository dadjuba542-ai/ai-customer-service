/* One learner-facing entry point; scored games and short courses keep separate sessions. */
const trainingHubState = { identity: null, generation: 0, entry: null, learning: null, path: null, scores: null };

function trainingHubNotice(message = '') {
  const host = document.getElementById('training-hub-notice');
  if (host) host.textContent = message;
}

async function loadTrainingHub() {
  const host = document.getElementById('training-hub-body');
  if (!host || !featureEnabled('practice')) return;
  const identity = state.sessionToken || state.token;
  if (!identity) return;
  if (trainingHubState.identity !== identity) {
    Object.assign(trainingHubState, { identity, entry: null, learning: null, path: null, scores: null });
  }
  const generation = ++trainingHubState.generation;
  trainingHubNotice('正在整理今天的学习内容…');
  const requests = [practiceApi('/entry'), practiceApi('/scores')];
  if (featureEnabled('practice_learning')) requests.push(learningApi('/home'), learningApi('/path'));
  const results = await Promise.allSettled(requests);
  if (generation !== trainingHubState.generation || identity !== (state.sessionToken || state.token)) return;
  if (results[0].status !== 'fulfilled') {
    trainingHubNotice(results[0].reason.message || '暂时无法读取今日练习');
    host.innerHTML = '<button class="practice-button" onclick="loadTrainingHub()">重新加载</button>';
    return;
  }
  trainingHubState.entry = results[0].value.entry;
  practiceState.entryData = trainingHubState.entry;
  trainingHubState.scores = results[1].status === 'fulfilled' ? results[1].value : null;
  trainingHubState.learning = results[2]?.status === 'fulfilled' ? results[2].value : null;
  trainingHubState.path = results[3]?.status === 'fulfilled' ? results[3].value : null;
  if (trainingHubState.learning) learningState.home = trainingHubState.learning;
  trainingHubNotice(results[2]?.status === 'rejected' ? '产品课程暂时无法加载，可先进行今日问答。' : '');
  renderTrainingHub();
}

function renderTrainingHub() {
  const host = document.getElementById('training-hub-body');
  if (!host) return;
  const entry = trainingHubState.entry, learning = trainingHubState.learning, path = trainingHubState.path, scores = trainingHubState.scores;
  const learningEnabled = featureEnabled('practice_learning');
  const e = practiceEscape;
  const next=path?.next_unit;
  const pathTotal = path?.available ? Math.max(1, path.units.length) : 0;
  const dailyCount = Math.max(0, Math.min(10, Number(entry?.answered_count) || 0));
  const dailyDone = entry?.mode === 'free' && entry.action !== 'resume';
  const progressMax = pathTotal || 10;
  const progressCount = pathTotal ? Math.max(0, Math.min(pathTotal, Number(path.completed_count) || 0)) : dailyDone ? 10 : dailyCount;
  const progressLabel = pathTotal ? `主线 ${progressCount}/${progressMax} 单元` : dailyDone ? '今日闯关已完成' : `今日闯关 ${progressCount}/10 题`;
  host.innerHTML = `<div class="training-hub-summary"><div class="training-hub-summary-heading"><h2>AI宝儿问答课堂</h2><span>${progressLabel}</span></div><div class="training-hub-progress" role="progressbar" aria-label="${pathTotal ? '主线学习进度' : '今日闯关进度'}" aria-valuemin="0" aria-valuemax="${progressMax}" aria-valuenow="${progressCount}"><span style="width:${progressCount / progressMax * 100}%"></span></div></div>
    ${path?.available ? `<section class="training-hub-section"><div class="training-hub-heading"><h3>学习主线</h3><span>${path.completed_count}/${path.units.length} 单元已完成</span></div>
      <button class="learning-path-primary" onclick="openNextLearning()"><span class="learning-path-eyebrow">${next ? `第${next.position}单元 · ${e(next.level_label)}` : '全部单元已完成'}</span><strong>${next ? e(next.title) : '主线已点亮，继续巩固所学'}</strong><small>${next ? e(next.subtitle) : '可做今日10题或复习错题'}</small><b>${next ? path.resume_id ? '继续这一单元' : '开始下一单元' : '查看今日练习'} →</b></button>
      <div class="learning-path-nodes" aria-label="学习主线进度">${path.units.map(unit=>`<span class="${unit.completed?'done':next?.id===unit.id?'current':''}" title="${e(unit.title)}">${unit.completed?'✓':unit.position}</span>`).join('')}</div></section>` : ''}
    <section class="training-hub-section"><div class="training-hub-heading"><h3>今日问答闯关</h3>${scores ? `<span>今日 ${scores.today_points}/100 分</span>` : ''}</div>
      ${entry ? path?.available ? `<button class="learning-daily-link" onclick="openPracticeEntry()" data-practice-entry-button><span><strong>${e(entry.stage_title || '每日10题')}</strong><small>${e(entry.question_title)} · ${entry.mode==='free'?'本轮不计分':'最高100分'}</small></span><b>进入 →</b></button>` : practiceEntryCard(entry) : '<div class="practice-card">今日题目正在准备中。</div>'}</section>
    ${learning && !path?.available ? `<section class="training-hub-section"><div class="training-hub-heading"><h3>产品课程</h3><span>每单元约1分钟＋3题</span></div>
      ${learning?.resume?.kind === 'unit' ? `<button class="training-hub-resume" onclick="resumeLearning('${e(learning.resume.id)}')">继续未完成的产品短课 →</button>` : ''}
      ${learning?.courses?.length ? learning.courses.map(course => `<button class="learning-product" onclick="openLearningProduct(${course.product_id})"><span class="learning-product-icon">▣</span><span><strong>${e(course.name)}</strong><small>${e(course.category)} · ${course.completed_units}/4 单元已完成</small></span><span>→</span></button>`).join('') : '<div class="practice-card">首款产品课程准备中。</div>'}</section>` : ''}
    ${learning ? `<section class="training-hub-section"><div class="training-hub-heading"><h3>到期复习</h3><span>每天最多3题</span></div><button class="learning-review-entry" onclick="openLearningReview()"><span><b>复习容易忘的题</b><small>${learning.resume?.kind === 'review' ? '上次复习尚未完成' : '巩固已学知识点'}</small></span><strong>${learning.due_count} 道 →</strong></button></section>` : learningEnabled ? '<div class="practice-card">学习进度暂时无法读取。<button class="training-hub-text-link" onclick="loadTrainingHub()">重新加载 →</button></div>' : ''}
    <section class="training-hub-section"><div class="training-hub-heading"><h3>我的学习</h3></div>
      <div class="training-hub-links"><button onclick="openPracticeSection('records')">◷ 闯关记录 <span>→</span></button><button onclick="openPracticeSection('ranking')">✦ 团队周榜 <span>→</span></button></div></section>`;
  if (entry && state.currentView === 'training') recordPracticeEntryImpression(entry, host.querySelector('[data-practice-entry-button]'));
  if (practiceState.linkStage && entry?.stage_id !== practiceState.linkStage) trainingHubNotice('该活动已结束，已为你展示当前可练内容。');
  practiceState.linkStage = null;
  practiceState.linkLanding = false;
}

function openPracticeSection(tab) {
  practiceState.tab = tab;
  practiceState.session = null;
  switchView('practice');
}

