# Changelog

## 1.1.5.8 (2026-09-14)

### 新增大字档系统切换气泡溢出修复

- 大字档下「已切换到『xxx』」系统气泡标题用 `nowrap` 且父级 `.sb-text` 缺
  `min-width:0`，字号放大后撑破气泡 `max-width:85%` 上限、文字溢出圆角框
- `.sb-text` 补 `min-width:0`；大字档允许 `.sb-title` 换行，保证智能体名完整可读
- 同步升级 `chat.css` / `text-size.css` / `views.js` 缓存版本号

### 新增只读 MCP 集成（内部运营/内容辅助，本地 + 线上）

- 工具逻辑集中在 `services/mcp_service.py`，两种传输共用，**只读**：
  11 个工具 `chat_stats` / `search_chat_history` / `recent_bad_feedback` /
  `list_leads` / `search_products` / `get_product` / `search_cases` / `get_case` /
  `list_news` / `get_news` / `list_agents`
- **线上**：新增 `routes/mcp.py`，`POST /api/mcp`（MCP Streamable HTTP，JSON-RPC 2.0），
  Bearer token 鉴权；未配置 `MCP_TOKEN` 时端点整体关闭（403）；已豁免按 IP 反爬预算
- **本地**：`scripts/mcp_server.py` 纯标准库 stdio，零依赖，直连本地 SQLite
- `opencode.json` 默认接 remote（`{env:MCP_URL}` / `{env:MCP_TOKEN}` 注入，不落明文），
  local 版保留为可选
- 安全：不注册写操作；`list_agents` 不返回 `prompt`/`bot_id`；
  `list_leads` 手机号/微信默认脱敏
- 配置：`config.py` → `Config.MCP_TOKEN`，`.env.example` 增示例
- 方案与用法文档：`docs/MCP_INTEGRATION.md`

### 新增用户调研问卷

- 前台首页「快捷功能」新增「意见反馈」入口，打开多题调研问卷（使用时长 / 常用功能 /
  满意度 / 待改进 / 建议），复用现有满意度弹窗样式
- 新增表 `research_surveys`（迁移版本 `202609140003`），答案以 JSON 存储，异步问题结构可扩展
- 新增 `POST /api/survey/research`（需身份 + 每日限流）与后台
  `GET /api/admin/dashboard/research-surveys`
- 后台「评价看板」新增「用户调研问卷」卡片，展示平均满意度并支持 CSV 导出
- 问卷问题集中维护在 `static/js/research-survey.js` 的 `RESEARCH_QUESTIONS`

### 新增音频课程模块（Phase 1）

- 新增与「案例系统」平级的「音频课程」模块，独立功能开关 `audio_courses`（默认关闭），
  沿用统一三层拦截（HTTP 入口 / 服务层 / 后台入口），后台「功能开关」页可直接开关
- 独立问答入口：前台新增 `audio-view` 页面，输入问题 → 返回相关音频课程；
  首页「快捷功能 / 音频课程」并排 tab（默认快捷功能）
- 后台新增「置顶 `pinned`」「首页展示 `show_on_home`」（迁移版本 `202609140002`）；
  首页只展示勾选首页的课程，固定 6 条，置顶课程排最前
- 匹配算法复用案例打分（标签 ×100 + FTS ×25 + 正文 ×10），新增表
  `audio_courses` 与 FTS `audio_courses_fts`（迁移版本 `202609140001`）
- 音频双来源：后台上传到 `UPLOAD_DIR/audio/`，或填写 https 外链；
  CSP `media-src` 放开 https 以支持外链播放
- 后台新增「音频课程」管理页与 `static/admin/audio-courses.js`；
  前台新增 `static/js/audio-courses.js` 与 `static/css/audio-courses.css`（含大字版适配）
- 数据模型保持轻量：不含封面图、不含讲师字段
- 全局请求体上限放宽到 52MB 以容纳音频，图片上传仍单独限制 8MB
- 回归：新增 `scripts/test_audio_courses.py`，更新 `scripts/test_feature_flags.py`
- 方案文档：`docs/AUDIO_COURSES_PLAN.md`

### 音频课程安全与健壮性加固（评审后）

- 前台新增 `escapeAttr()`，属性位置全部转义；标签按钮改事件委托，移除内联 `onclick` 拼接
- 服务端 `sanitize_audio_url()` 收紧为仅 `http(s)://` 或 `/uploads/`，拒绝引号/尖括号/空白
- 公开列表 / 首页 / 搜索改返回精简投影，不再下发文字稿与音频地址
- 删除课程或替换音频时清理本地音频文件；新增 `scripts/cleanup_audio_uploads.py`（默认 dry-run）
- 上传改为流式落盘 + `content_length` 预检，避免整包读入内存
- 更新接口改为合并式 PUT，标签筛选补 LIKE 转义
- 新增前端回归 `scripts/test_audio_courses_frontend.js`

### 音频课程开关语义调整

- `audio_courses` 开关改为只控制前台展示：关闭时前台入口与公开接口全停，
  **后台管理（`/api/admin/audio-courses`）豁免、侧边栏入口常驻**，避免关闭状态下无法备稿
- 首页在没有任何「首页展示」课程时不渲染音频课程 tab

### 音频课程迷你播放器（Phase 1）

- 播放状态与详情抽屉解耦：单例 `<audio>` 不随抽屉销毁，关闭详情继续播放
- 新增常驻「迷你播放条」（底部导航之上）：播放/暂停、标题、进度、时间、关闭
- 详情抽屉去掉点遮罩关闭，只保留关闭按钮；关闭按钮仅收起 UI，不停止播放
- 迷你条与详情统一自定义播放控件；显式关闭迷你条才会停止并归零
- 会话内续播：重新打开同一课程接着上次进度；切换课程从头
- 修复播放时间显示小数（`20.445745`）问题：时长/进度取整为 `m:ss`
- 回归：`scripts/test_audio_courses_frontend.js` 覆盖收起保留进度、切课、显式关闭

### 音频课程播放页增强（Phase 1.1）

- 点详情面板外改为**收起为迷你条**（继续播放），不再需要精确点关闭按钮
- 详情页新增 **15 秒快退 / 快进**按钮，`seekAudioBy()` 做 `[0, duration]` 边界钳制
- 修复迷你条点关闭后不消失：`.audio-mini-player` 的 `display:flex` 覆盖了 `[hidden]`，补 `[hidden]{display:none}`
- 缓存版本：`audio-courses.js/css` -> `20260914-audio7`/`audio8`

### 音频课程进度条拖动（Phase 1.2）

- 迷你条与详情进度条支持拖动跳转（Pointer Events + scrubbing 状态，拖动中不被 `timeupdate` 覆盖）
- 进度条新增圆形把手、`touch-action: none`（避免触屏拖动触发页面滚动）
- 无障碍：`role="slider"` + `aria-valuenow` + 左右方向键 ±5 秒
- 缓存版本：`audio-courses.js/css` -> `20260914-audio10`

### 修复音频课程「查看全部」看不到课程

- `.audio-content` 未设为可滚动容器（`#app-container` 为 `overflow:hidden`），列表被裁掉无法滚动
- 补齐 `flex:1; min-height:0; overflow-y:auto` 与底部留白（100px），与发现页/社区页一致
- 缓存版本：`audio-courses.css` -> `20260914-audio11`

### 修复音频课程页空白（缓存版本号漏升）

- `views.js` 增加 `loadAudioCoursesPage()` 后未升 `?v=`，浏览器缓存旧文件导致切到音频页不加载
- 补 `views.js?v=20260914-audio12`

## 1.1.5.6 (2026-09-08 ~ 09-10)
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

### 新增「大字·清晰版」一键字号切换（适老化）

中老年用户占比高，原全站字号硬编码 12–14px、且 `viewport` 禁止双指缩放，阅读困难。
对外命名「大字·清晰版」，按钮文案为中文「字号」，全程不出现老年/长辈/关怀字样。

- **机制**：CSS 变量 `--fs-scale` + `calc(Npx * var(--fs-scale))`。
  选它而非 rem —— 全站 230 处 px 无 rem 根字号，rem 需逐个人工重算；
  calc 方案可用脚本机械替换，且 `--fs-scale=1` 时计算结果与原值像素级一致，
  天然具备回归基准。也没用 `zoom`，那会让 480px 定宽容器横向溢出、点击坐标错位。
- **三档**：标准 1.0 / 大 1.3（正文 14→18.2px，达工信部正文 ≥18px 要求）/ 超大 1.55（→21.7px）
- **批量改造**：新增 `scripts/apply_font_scale.py`，一次性改写前台 12 个 CSS 共 **171 处**
  `font-size: Npx` → `calc(Npx * var(--fs-scale))`
  - 排除 `text-size.css`（按钮/面板尺寸刻意不缩放）与 `admin.css`（后台不加载 base.css，
    无 `--fs-scale` 变量，改了会失效）
  - `rich-text.css` 的 `ql-size-*` 本就是 em 相对单位，无需改动
  - `body` 增加基准字号 `calc(16px * var(--fs-scale))`，让未显式声明字号的元素也跟随
- **入口 6 处**：进门遮罩、首页（头像左侧）、聊天页（清空左侧）、产品/发现/社区页（标题右侧）
- **入口文案**：6 处按钮由 `Aa` 改为中文「字号」，形态改胶囊（原 36px 圆形）
  - 原因：中老年用户对 `Aa` 符号识别率低，常误以为英文或 AA 制。
    功能名要含蓄，但按钮本身必须一眼看懂，这两件事不矛盾
  - 按钮文字用 `min(15px, calc(13px * var(--fs-scale)))` 限幅：大字档下从 13px 提到 15px
    便于看清，同时外形尺寸保持稳定（防误触设计要求按钮不随字号缩放）
- **首次引导气泡**：首次进入时在按钮下方弹一次「字看不清？点这里调大」，3.2 秒后自动消失，
  `localStorage['ui_text_size_hinted']` 标记后不再出现；点按钮也会立即收起
- **防误触四道保险**（误触后切不回来比不做更糟）：
  1. 字号按钮尺寸固定、不参与缩放，位置不飘
  2. 「标准 → 大字」时弹 5 秒后悔条「已放大 · 点这里恢复」，点击立即还原；切回标准不打扰
  3. 面板内「标准」档置顶标注「默认显示」，底部另有「恢复默认设置」
  4. 长按字号按钮 2 秒强制还原
  - 兜底：档位只靠 `<html data-ts>` 生效，JS 失效即回落标准档，不会被困在大字模式
- **补充层**（`static/css/text-size.css`，只放大字会撑破容器）：
  行距全局 1.7、聊天正文 1.8；导航/图标按钮热区 ≥44px（WCAG 2.5.5）；
  底部导航高度 72→88px 且中文标签禁止折行；非标准档把 `--slate-400` 从 #9CA3AF
  提到 #6B7280（白底对比度 2.5:1 → 4.8:1）
- **无障碍修正**：`viewport` 去掉 `user-scalable=no`、`maximum-scale` 改为 5.0
  （原设置禁止双指缩放，违反 WCAG 1.4.4）；输入框用 `max(16px, …)` 兜底，
  避免 iOS Safari 聚焦时自动放大整页
- **防闪烁**：`<head>` 内联脚本先于所有样式表读取 localStorage 并打上 `data-ts`，
  否则会出现「标准字号先渲染、再跳成大字」的跳变
- **其他**：热门问题词云（`news-discover.js`）硬编码字号接入缩放系数；
  `.memory-header` 改为 flex 以容纳右侧入口
- 缓存版本号：**12 个被改动的样式表** + `news-discover.js` → `?v=20260910-textsize1`；
  `text-size.css` / `text-size.js` 因按钮文案改中文与首次引导二次改动 → `?v=20260910-textsize2`
  - 踩坑：首版只升了 `base.css` / `community.css`，其余 10 个仍走浏览器旧缓存，
    表现是「只有词云变了、其他界面毫无变化」——因为词云在 JS 里而那个 JS 升了版本号。
    批量改 CSS 后必须逐个升版本号，漏一个就白改。
  - 校验脚本 `scripts/check_font_scale.py`：真实浏览器实测各界面的 computed font-size，
    确认切换前后精确 ×1.30（产品详情 22→28.6、资讯详情 15→19.5、问答气泡 14→18.2）
  - 注：聊天输入框因 `max(16px, …)` 下限，比例是 ×1.14 而非 ×1.30，属预期
- 方案与排期文档：`docs/TEXT_SIZE_PLAN.md`

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
