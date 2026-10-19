/* One learner-facing entry point; scored games and short courses keep separate sessions. */
const trainingHubState = { identity: null, generation: 0, entry: null, learning: null, scores: null };

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
    Object.assign(trainingHubState, { identity, entry: null, learning: null, scores: null });
  }
  const generation = ++trainingHubState.generation;
  trainingHubNotice('正在整理今天的学习内容…');
  const requests = [practiceApi('/entry'), practiceApi('/scores')];
  if (featureEnabled('practice_learning')) requests.push(learningApi('/home'));
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
  if (trainingHubState.learning) learningState.home = trainingHubState.learning;
  trainingHubNotice(results[2]?.status === 'rejected' ? '产品课程暂时无法加载，可先进行今日问答。' : '');
  renderTrainingHub();
}

function renderTrainingHub() {
  const host = document.getElementById('training-hub-body');
  if (!host) return;
  const entry = trainingHubState.entry, learning = trainingHubState.learning, scores = trainingHubState.scores;
  const learningEnabled = featureEnabled('practice_learning');
  const e = practiceEscape;
  const activity = learning?.activity_days || [];
  const today = learning?.today;
  const week = today ? Array.from({ length: 7 }, (_, index) => {
    const day = new Date(`${today}T12:00:00+08:00`);
    day.setDate(day.getDate() - 6 + index);
    const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
    return `<span class="${activity.includes(key) ? 'lit' : ''}" title="${key}">${'日一二三四五六'[day.getDay()]}</span>`;
  }).join('') : '';
  host.innerHTML = `<div class="training-hub-intro"><span>每天学一点</span><h2>AI宝儿问答课堂</h2><p>${learningEnabled ? '答今日题，学产品知识，再复习容易忘的题。' : '每天10题，边答边学。'}</p>
    ${learning ? `<div class="training-hub-streak"><strong>连续学习 ${learning.streak} 天</strong><div class="learning-week-strip" aria-label="近七天学习记录">${week}</div></div>` : ''}</div>
    <section class="training-hub-section"><div class="training-hub-heading"><h3>今日问答闯关</h3>${scores ? `<span>今日 ${scores.today_points}/100 分</span>` : ''}</div>
      ${entry ? practiceEntryCard(entry) : '<div class="practice-card">今日题目正在准备中。</div>'}</section>
    ${learning ? `<section class="training-hub-section"><div class="training-hub-heading"><h3>产品课程</h3><span>每单元约1分钟＋3题</span></div>
      ${learning?.resume?.kind === 'unit' ? `<button class="training-hub-resume" onclick="resumeLearning('${e(learning.resume.id)}')">继续未完成的产品短课 →</button>` : ''}
      ${learning?.courses?.length ? learning.courses.map(course => `<button class="learning-product" onclick="openLearningProduct(${course.product_id})"><span class="learning-product-icon">▣</span><span><strong>${e(course.name)}</strong><small>${e(course.category)} · ${course.completed_units}/4 单元已完成</small></span><span>→</span></button>`).join('') : '<div class="practice-card">首款产品课程准备中。</div>'}</section>
      <section class="training-hub-section"><div class="training-hub-heading"><h3>到期复习</h3><span>每天最多3题</span></div>
        <button class="learning-review-entry" onclick="openLearningReview()"><span><b>巩固以前答错的知识点</b><small>${learning.resume?.kind === 'review' ? '上次复习尚未完成' : '答错后次日再练，答对后逐步延长间隔'}</small></span><strong>${learning.due_count} 道 →</strong></button></section>` : learningEnabled ? '<div class="practice-card">产品课程暂时无法读取。<button class="training-hub-text-link" onclick="loadTrainingHub()">重新加载 →</button></div>' : ''}
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

