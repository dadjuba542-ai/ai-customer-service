# Changelog

## 1.1.5.4 (2026-09-07)

### 语音输入交互改版（前台）

- **交互改为点击式**：去掉「按住说话，松手结束」的 press-to-talk 逻辑，改为
  点一下开始录音 → 再点一下结束并转文字；60 秒自动停止逻辑保留
- **语音按钮图标改内联 SVG**（小话筒 / 停止方块 / 转圈），不再用 Phosphor 字体图标，
  修复字体缺失时字形叠加导致图标重叠的问题；三种状态均居中渲染
- 涉及文件：`static/js/voice.js`、`static/js/fetch-util.js`（图标 + 文案）、
  `static/js/core.js`（移除 press 状态字段）、`static/css/chat.css`
  （spinner 动画选择器、touch-action: manipulation）
- 前端缓存版本号：`core.js` / `fetch-util.js` / `voice.js` / `chat.css` → `?v=20260907-voice-toggle1`

### 验证

静态环境（Chrome + playwright DOM 几何校验）：mic / stop / spinner 三态均单 SVG、
44px 按钮内图标居中对齐（偏移 0px）、无页面 JS 错误

## 1.1.5.3 (2026-09-07)

### 富文本编辑器升级（后台资讯 + 产品详情共用）

- 工具栏新增六组排版能力：**格式刷**（单击刷一次 / 双击连刷 / Esc 退出）、**字号**（小/标准/大/特大）、
  **字体颜色**（12 色色板）、**背景高亮**（6 色）、**对齐**（左/居中/右/两端）、**行间距**（1.0–3.0 倍）、
  **段间距**（0–48px），下拉项全部中文化
- 新增 `static/css/rich-text.css`：编辑器与前台共用同一套样式定义，保证「编辑所见 = 前台所见」
  （前台不加载 quill.snow.css，此前对齐/字号的 class 在前台本无样式）
- 后端 `CLASS_PATTERN` 放行 `ql-color/bg/line/para` 前缀；仍不开放 style 属性，XSS 面不变
- 修复存量 bug：字体颜色按钮保存后颜色丢失（Quill 原生颜色走 inline style，被清洗剥掉；
  改走 class 色板后可正常保存）
- 产品详情编辑器一并升级为同一套工具栏

### 产品编辑器修复（2026-09-07）

- **修复：多次编辑产品时，编辑器内容停在上一次打开的产品**（存量 bug）。
  根因：代码调用了 `Quill.destroy()`，而 Quill 2 不存在该方法，抛 TypeError 后内容填充
  永远执行不到。改为惰性单例，实例只创建一次
- **修复：编辑器内容写入绕过数据模型**。三处 `root.innerHTML = ...` 统一改为
  `clipboard.convert + setContents`，Delta 模型与 DOM 保持同步
- **修复：菜单栏错乱**。格式刷按钮改内联 SVG 图标（原 Phosphor 字形缺失时按钮是空位），
  并包进 `.ql-formats` 分组；修复窄窗口下下拉中文标签逐字竖排（如「左对齐」叠成三行——
  工具栏下拉是 float 收缩宽度，中文单字可断行导致宽度被压到单字；现强制整词不换行，
  放不下时整组掉到下一行）
- 前端缓存版本号：`admin.js` → `?v=20260907-prodfix1`；`rich-text.css` → `?v=20260907-prodfix2`

### 验证

真实环境（Flask + Chrome）回归：连续编辑 3 个产品内容逐个正确、新增为空、
Quill Delta 模型与 DOM 同步、控制台零报错、工具栏全程唯一。
