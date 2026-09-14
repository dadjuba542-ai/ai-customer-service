const fs = require('fs');
const path = require('path');
const vm = require('vm');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const file = path.join(__dirname, '..', 'static', 'js', 'audio-courses.js');
const code = fs.readFileSync(file, 'utf8');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(`${code}\nthis.__escapeAttr = escapeAttr;`, sandbox);

const escapeAttr = sandbox.__escapeAttr;
assert(typeof escapeAttr === 'function', 'escapeAttr 应可加载');

assert(escapeAttr('a"b') === 'a&quot;b', '双引号应转义');
assert(escapeAttr("a'b") === 'a&#39;b', '单引号应转义');
assert(escapeAttr('<x>&"y"') === '&lt;x&gt;&amp;&quot;y&quot;', '组合应转义');
assert(escapeAttr(null) === '', 'null 应返回空串');
assert(escapeAttr(undefined) === '', 'undefined 应返回空串');
assert(escapeAttr(12.5) === '12.5', '数字应转字符串');

console.log('audio courses frontend tests passed');
