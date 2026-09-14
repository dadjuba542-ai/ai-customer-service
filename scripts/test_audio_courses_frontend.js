const fs = require('fs');
const path = require('path');
const vm = require('vm');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const file = path.join(__dirname, '..', 'static', 'js', 'audio-courses.js');
const code = fs.readFileSync(file, 'utf8');

class FakeAudio {
  static instances = [];
  constructor() {
    FakeAudio.instances.push(this);
    this._listeners = {};
    this.currentTime = 0;
    this.duration = 0;
    this.paused = true;
    this.src = '';
    this.playCalls = 0;
    this.pauseCalls = 0;
    this.loadCalls = 0;
  }
  addEventListener(type, handler) {
    (this._listeners[type] = this._listeners[type] || []).push(handler);
  }
  dispatch(type) {
    (this._listeners[type] || []).forEach((handler) => handler());
  }
  play() {
    this.paused = false;
    this.playCalls += 1;
    this.dispatch('play');
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
    this.pauseCalls += 1;
    this.dispatch('pause');
  }
  removeAttribute(name) {
    if (name === 'src') this.src = '';
  }
  load() {
    this.loadCalls += 1;
  }
}

const sandbox = {
  Audio: FakeAudio,
  document: {
    getElementById: () => null,
    createElement: () => ({ style: {}, addEventListener() {}, querySelector: () => null }),
  },
  featureEnabled: () => true,
};
vm.createContext(sandbox);
vm.runInContext(
  `${code}\nthis.__escapeAttr = escapeAttr; this.__fmt = formatAudioDuration; this.__seekBy = seekAudioBy; ` +
  `this.__play = playAudioCourse; this.__stop = stopAudio; this.__close = closeAudioDrawer; this.__state = audioPlayerState;`,
  sandbox,
);

// ---- formatAudioDuration ----
const fmt = sandbox.__fmt;
assert(fmt(20.445745) === '0:20', '小数秒应取整到 0:20');
assert(fmt(1411.1359999999997) === '23:31', '长音频小数秒应取整到 23:31');
assert(fmt(0) === '', '0 应返回空串');

// ---- escapeAttr ----
const escapeAttr = sandbox.__escapeAttr;
assert(typeof escapeAttr === 'function', 'escapeAttr 应可加载');
assert(escapeAttr('a"b') === 'a&quot;b', '双引号应转义');
assert(escapeAttr("a'b") === 'a&#39;b', '单引号应转义');
assert(escapeAttr('<x>&"y"') === '&lt;x&gt;&amp;&quot;y&quot;', '组合应转义');
assert(escapeAttr(null) === '', 'null 应返回空串');
assert(escapeAttr(undefined) === '', 'undefined 应返回空串');
assert(escapeAttr(12.5) === '12.5', '数字应转字符串');

// ---- 单例播放器 ----
const { __play: play, __stop: stop, __close: close, __state: state } = sandbox;
const courseA = { id: 1, title: 'A', audio_url: '/uploads/audio/a.mp3', duration_seconds: 100 };
const courseB = { id: 2, title: 'B', audio_url: '/uploads/audio/b.mp3', duration_seconds: 100 };

play(courseA);
const el = FakeAudio.instances[0];
assert(FakeAudio.instances.length === 1, '应只创建一个 audio 实例');
assert(el.src === '/uploads/audio/a.mp3', '应加载课程 A 音频');
assert(el.playCalls === 1 && state.loaded === true, '应开始播放并标记已加载');

el.currentTime = 30;
el.dispatch('timeupdate');
assert(state.currentTime === 30, 'timeupdate 应同步进度');

// 收起详情：不得暂停、不得归零
close();
assert(state.loaded === true, '收起后仍应为已加载');
assert(state.currentTime === 30, '收起后应保留进度');
assert(el.pauseCalls === 0, '收起不应暂停');

// 重新打开同一课程：不重载、进度保留
play(courseA);
assert(state.currentTime === 30, '同课程重开应保留进度');
assert(el.src === '/uploads/audio/a.mp3', '同课程重开不应换源');

// 切换到另一课程：换源并从头
play(courseB);
assert(el.src === '/uploads/audio/b.mp3', '切换课程应换源');
assert(state.currentTime === 0 && state.id === 2, '切课应从 0 开始');

// 15 秒快退/快进（含边界钳制）
el.currentTime = 5;
state.currentTime = 5;
sandbox.__seekBy(-15);
assert(el.currentTime === 0, '快退不应越过开头');
sandbox.__seekBy(15);
assert(el.currentTime === 15, '快进 15 秒');
sandbox.__seekBy(1000);
assert(el.currentTime === 100, '快进不应越过结尾');

// 显式关闭：暂停 + 清空
stop();
assert(el.pauseCalls >= 1, '显式关闭应暂停');
assert(el.src === '', '显式关闭应清空 src');
assert(state.loaded === false && state.id === null, '显式关闭应清空状态');

// 未加载时快进不应报错
sandbox.__seekBy(15);

console.log('audio courses frontend tests passed');
