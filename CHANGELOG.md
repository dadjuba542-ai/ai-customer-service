# Changelog

## 1.1.5.6 (2026-09-08)

### 全站图标改为内联 SVG（告别 Phosphor 字体图标）

- **问题**：全站 187 处图标用 Phosphor `<i class="ph ph-xxx">` 写法，但 Phosphor CDN
  实际未引入，浏览器渲染的是 `icon-fallback.css` 里的 Unicode 兜底字符（◆ ⌂ □ 之类），
  不是矢量图标，字号/颜色/粗细都不可控
- **方案**：手写 67 枚 SVG（24 网格、实心、`fill="currentColor"`），三层落地：
  1. **HTML 静态 113 处** → 内联 `<svg class="icon icon-{name}">`，零额外请求，
     `width/height: 1em` 继承父级字号、`currentColor` 继承父级颜色
     - 前台 `static/index.html` 32 处（底部导航 5 + 其余 27）
     - 后台 `templates/admin.html` 81 处（品牌位 + 侧边栏 15 + 其余 66）
  2. **JS 动态生成 74 处** → CSS mask 兜底：`i[class*="ph-"]` 用
     `--ico: url(/icons/{name}.svg)` + `mask-image` + `background-color: currentColor`，
     一次定义全覆盖，且能兜住以后新写的 `.ph-*`；同时 `::before { content: none }`
     清掉原来的 Unicode 兜底字符
  3. **spinner 补动画**：新增 `@keyframes icon-spin`，`.icon-spinner` / `i.ph-spinner`
     等 0.9s 匀速旋转（原来根本不会转）
- **新增** `static/icons/`：67 枚独立 SVG 文件（供 mask 兜底与后续复用），
  全部 `viewBox="0 0 24 24"`、绘制元素显式 `currentColor`
- **样式**：`icon-fallback.css` 新增 `.icon` 基线（1em / inline-block / `-0.125em`
  基线对齐 / `flex-shrink:0` / `pointer-events:none`）；`news-nav.css`、`admin.css`
  的图标选择器扩展为同时命中 `i` 与 `.icon`
- **不动布局与交互**：只换图标节点，未改任何 class 结构或事件绑定
- 前端缓存版本号：`icon-fallback.css` / `css/news-nav.css` / `css/admin.css`
  → `?v=20260908-icons1`
- 校验：67 枚 SVG 全部通过 XML / viewBox / currentColor / 坐标边界检查；
  Flask 冒烟（`/icons/*.svg`、`/`、`/admin`）全 200，页面残留 `<i class="ph"` = 0

## 1.1.5.5 (2026-09-08)

### 案例系统 / 人工客服系统 独立启用开关

- 新增统一开关模块 `services/feature_flags.py`：一个开关 = 名字 + settings key + 环境变量 +
  代码默认值，全部登记在 `FLAGS` 注册表（新增开关只需加一行）
  - `cases`（案例系统）：key `cases_enabled`，env `CASES_ENABLED`，**默认开启**
  - `handoff`（人工客服系统）：key `handoff_enabled`，env `HANDOFF_ENABLED`，**默认关闭**
    （沿用原有约定；现网 DB 里已是 `1`，行为不变）
  - 取值优先级：settings 表 > 环境变量 > 默认值；读取结果带 `source` 字段说明来源
- 统一配置入口：后台新增「功能开关」页（两个独立开关，实时显示状态/来源/默认值）；
  接口 `GET /api/feature-flags`（前台只读）、`GET|PUT /api/admin/feature-flags`（管理员读写，
  支持单个 `{name, enabled}` 或批量 `{flags: {...}}`）
- 关闭后三层拦截：
  1. HTTP 入口：`app.before_request` 按注册表前缀统一拦截（页面给说明页 403，接口给
     `code=feature_disabled` 的 403 JSON），cases / handoff / admin_handoff 三个 blueprint
     再各带一层 `before_request` 兜底
  2. 调用链路：`chat_service.find_related_cases()` 短路（不再推荐相关案例）；
     handoff 的 start/message/close/defer、坐席上下线/接单/回复等服务函数直接抛 403
  3. 定时任务：派单线程在开关关闭时不启动，运行期被关掉则每轮跳过
     （`assign_available()` 返回 0）；后台打开开关会补启动线程
- 前端：首页拉取 `/api/feature-flags`，关闭的系统不渲染入口、不发请求；
  后台侧边栏对应入口（案例档案 / 人工客服 / 营养师工作台）自动隐藏
- 豁免：`/api/handoff/config` 始终可读，前台靠它拿到 `enabled=false` 来隐藏转人工入口
- 业务约束保留：开启人工客服系统仍需先配置营养咨询 AI 智能体（原校验迁移到开关层）
- 回归测试：`scripts/test_feature_flags.py`
- 前端缓存版本号：`core.js` / `handoff.js` / `chat.js` / `admin.js` → `?v=20260908-featureflags1`

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
