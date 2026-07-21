const assert = require('assert');
const { isExplicitHandoffIntent, classifyHandoffInput } = require('../static/handoff-intent.js');

const positives = [
  '转人工',
  '帮我找客服',
  '我还是想联系营养师',
  '这个问题没解决，请转真人客服',
  '可以联系人工客服吗？',
  '我要人工',
  '真人咨询',
];

const negatives = [
  '人工客服有什么作用',
  '怎么培训营养师',
  '帮我写一段客服话术',
  '真人和 AI 有什么区别',
  '这个产品适合人工种植吗',
  '',
];

positives.forEach((text) => assert.strictEqual(isExplicitHandoffIntent(text), true, `应识别：${text}`));
negatives.forEach((text) => assert.strictEqual(isExplicitHandoffIntent(text), false, `不应识别：${text}`));

assert.deepStrictEqual(classifyHandoffInput('转人工'), {
  isHandoffIntent: true, isPureIntent: true, questionText: '',
});
assert.deepStrictEqual(classifyHandoffInput('孕期便秘怎么办，请转人工'), {
  isHandoffIntent: true, isPureIntent: false, questionText: '孕期便秘怎么办',
});
assert.strictEqual(classifyHandoffInput('这个产品怎么使用').isHandoffIntent, false);

console.log('PASS: handoff intent matcher');
