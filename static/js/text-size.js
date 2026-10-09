/* ============================================================
   大字·清晰版 · 切换逻辑
   三档：'' 标准 / 'l' 大 / 'xl' 超大
   ------------------------------------------------------------
   依赖：index.html 头部内联脚本（防闪烁，先于 CSS 打上 data-ts）
   ⚠️ 修改本文件后同步升级 index.html 里的 ?v= 版本号
   ============================================================ */
(function () {
  'use strict';

  var KEY = 'ui_text_size';
  var KEY_HINT = 'ui_text_size_hinted';
  var VALID = { '': 1, 'l': 1, 'xl': 1 };
  var UNDO_MS = 5000;
  var LONGPRESS_MS = 2000;

  var root = document.documentElement;
  var undoTimer = null;
  var pressTimer = null;

  function isValid(v) {
    return v != null && Object.prototype.hasOwnProperty.call(VALID, v);
  }

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return isValid(v) ? v : '';
    } catch (e) {
      return '';
    }
  }

  function toast(msg, type) {
    if (typeof window.showToast === 'function') {
      window.showToast(msg, type || 'info');
    }
  }

  /* 切档会引发重排，按滚动比例保持阅读位置，避免跳回顶部 */
  function withScrollKept(fn) {
    var containers = document.querySelectorAll(
      '#chat-messages, .home-content, .discover-content, .products-content, .community-content'
    );
    var ratios = [];
    Array.prototype.forEach.call(containers, function (el) {
      var max = el.scrollHeight - el.clientHeight;
      ratios.push(max > 0 ? el.scrollTop / max : 0);
    });

    fn();

    requestAnimationFrame(function () {
      Array.prototype.forEach.call(containers, function (el, i) {
        var max = el.scrollHeight - el.clientHeight;
        if (max > 0) el.scrollTop = ratios[i] * max;
      });
    });
  }

  function syncSheetUI() {
    var cur = read();
    var opts = document.querySelectorAll('.tsize-option');
    Array.prototype.forEach.call(opts, function (btn) {
      var v = btn.getAttribute('data-ts-value') || '';
      btn.classList.toggle('active', v === cur);
    });
  }

  function showUndo() {
    var bar = document.getElementById('tsize-undo');
    if (!bar) return;
    bar.classList.add('active');
    if (undoTimer) clearTimeout(undoTimer);
    undoTimer = setTimeout(hideUndo, UNDO_MS);
  }

  function hideUndo() {
    var bar = document.getElementById('tsize-undo');
    if (bar) bar.classList.remove('active');
    if (undoTimer) { clearTimeout(undoTimer); undoTimer = null; }
  }

  function hideHint() {
    var hint = document.getElementById('tsize-hint');
    if (hint) hint.classList.remove('active');
  }

  /* 首次进入：在字号按钮下方弹一次引导气泡，只出现一次。
     不做常驻提示——老人如果已经调好了，反复弹会烦。 */
  function showFirstHint() {
    try {
      if (localStorage.getItem(KEY_HINT)) return;
    } catch (e) { return; }

    var host = document.getElementById('app-container');
    var hint = document.getElementById('tsize-hint');
    if (!host || !hint) return;

    var anchor = null;
    Array.prototype.forEach.call(document.querySelectorAll('.tsize-btn'), function (btn) {
      if (anchor) return;
      var r = btn.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) anchor = btn;
    });
    if (!anchor) return;

    var b = anchor.getBoundingClientRect();
    var h = host.getBoundingClientRect();
    hint.style.top = (b.bottom - h.top + 10) + 'px';
    hint.style.left = (b.left - h.left + b.width / 2) + 'px';
    /* 动画结束后 keyframes 不再保持，靠 inline transform 维持居中 */
    hint.style.transform = 'translateX(-50%)';
    hint.classList.add('active');

    try { localStorage.setItem(KEY_HINT, '1'); } catch (e) {}
    setTimeout(hideHint, 3200);
  }

  function apply(value) {
    if (!isValid(value)) value = '';
    var prev = read();
    if (prev === value) { syncSheetUI(); return; }

    withScrollKept(function () {
      if (value) {
        root.setAttribute('data-ts', value);
      } else {
        root.removeAttribute('data-ts');
      }
      try { localStorage.setItem(KEY, value); } catch (e) { /* 隐私模式忽略 */ }
      syncSheetUI();
    });

    /* 只在「标准 → 大字」时给后悔条，切回标准不打扰 */
    if (!prev && value) {
      showUndo();
    } else {
      hideUndo();
    }
  }

  function open() {
    syncSheetUI();
    var mask = document.getElementById('tsize-mask');
    if (mask) mask.classList.add('active');
  }

  function close() {
    var mask = document.getElementById('tsize-mask');
    if (mask) mask.classList.remove('active');
  }

  /* ---- 全局出口（供 onclick 调用） ---- */
  window.openTextSizeSheet = open;
  window.closeTextSizeSheet = close;
  window.selectTextSize = function (value) { apply(value); close(); };
  window.resetTextSize = function () { apply(''); close(); toast('已恢复默认字号'); };
  window.undoTextSize = function () { apply(''); hideUndo(); toast('已恢复默认字号'); };

  function init() {
    /* 主脚本可能在防闪脚本之后才跑，这里兜底同步一次 */
    var cur = read();
    if (cur) root.setAttribute('data-ts', cur);
    syncSheetUI();

    var btns = document.querySelectorAll('.tsize-btn');
    Array.prototype.forEach.call(btns, function (btn) {
      btn.addEventListener('click', function () { hideUndo(); hideHint(); open(); });

      /* 长按 2 秒强制还原，给误触用户一条逃生通道 */
      var start = function () {
        if (pressTimer) clearTimeout(pressTimer);
        pressTimer = setTimeout(function () {
          pressTimer = null;
          if (read()) {
            apply('');
            toast('已恢复默认字号');
          }
        }, LONGPRESS_MS);
      };
      var cancel = function () {
        if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
      };
      btn.addEventListener('touchstart', start, { passive: true });
      btn.addEventListener('touchend', cancel);
      btn.addEventListener('touchcancel', cancel);
      btn.addEventListener('mousedown', start);
      btn.addEventListener('mouseup', cancel);
      btn.addEventListener('mouseleave', cancel);
    });

    /* 点遮罩空白处关闭 */
    var mask = document.getElementById('tsize-mask');
    if (mask) {
      mask.addEventListener('click', function (e) {
        if (e.target === mask) close();
      });
    }

    /* 首次引导：等页面稳定后再弹，避免刚打开就跳出来 */
    setTimeout(showFirstHint, 900);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
