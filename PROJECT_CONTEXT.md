# AI 宝儿项目速查文档

这份文档的目标不是替代源码，而是给后续接手的人或 Agent 一个足够高密度的项目快照。正常情况下，先读这份文档，再按需打开少量关键文件即可，不必每次全仓通读。

## 1. 项目定位

- 项目名称：`AI宝儿智能体`
- 形态：单体 Flask Web 应用
- 核心能力：
  - 前台 AI 对话
  - 资讯展示与详情阅读
  - 产品资料展示
  - 客户案例档案推荐
  - 社区问答与评论精选
  - 满意度问卷
  - 管理后台（智能体、资讯、配置、统计）
- 外部 AI 依赖：Coze Bot API

一句话总结：这是一个面向业务咨询场景的 AI 客服/内容运营后台一体化系统，前台给用户聊天和看内容，后台给管理员调智能体、配内容、看数据。

## 2. 技术栈与运行方式

- 后端：Flask 3
- 跨域：Flask-CORS
- 鉴权：JWT
- 数据库：SQLite
- HTTP 调用：`requests`
- 图片处理：Pillow
- 部署方式：`gunicorn app:app -b 0.0.0.0:$PORT -w 4`
- Python 版本：
  - `runtime.txt` 指向 `python-3.11`
  - `railway.json` 也指定 `pythonVersion: 3.11`

本地启动常规方式：

```bash
pip install -r requirements.txt
python3 app.py
```

服务默认监听：

- `http://0.0.0.0:5001`

## 3. 目录速览

```text
app.py                  Flask 入口，注册蓝图，补充若干独立接口
config.py               环境变量配置
db_migrations.py        轻量 SQLite migration 执行器
models.py               SQLite 初始化 + 全量数据访问函数
routes/                 各业务路由
services/chat_service.py Coze 对话同步/流式封装
static/                 前台静态页面与脚本样式
static/admin/cases.js   后台案例档案 JS（案例管理、标签库、链接识别、案例库 H5 设置）
templates/consultant.html 独立 PC 营养师客服工作台
static/consultant/      客服台多会话、通知和独立样式
routes/handoff.py       前台转人工与会话恢复接口
routes/admin_handoff.py 客服台队列、接入、回复和通知接口
services/handoff_service.py 排队分配、状态机和 AI 上下文快照
services/image_service.py 图片压缩、缩略图和上传图处理服务
templates/admin.html    管理后台页面
scripts/test_today_features.py 现有冒烟测试
scripts/test_case_documents.py 案例档案冒烟测试
scripts/test_migrations.py SQLite migration 冒烟测试
scripts/test_security.py 安全边界冒烟测试
scripts/create_admin.py 首次管理员初始化脚本
scripts/reset_admin_password.py 管理员密码重置脚本
scripts/optimize_uploaded_images.py 历史上传图片优化脚本
scripts/optimize_news_content_images.py 新闻正文 base64 图片迁移脚本
railway.json            Railway 部署配置
zeabur.json             Zeabur 启动配置
outputs/                历史生成物/设计产物，非主应用运行核心
```

## 4. 启动链路

应用入口在 `app.py`，关键流程如下：

1. 创建 Flask 应用并启用 CORS
2. 校验配置 `Config.validate()`
3. 创建 `static/uploads`
4. 调用 `init_db()` 自动建表、执行轻量 migration、建索引
5. 注册全部蓝图
6. 暴露前台 `/`、后台 `/admin` 以及少量全局接口

这意味着：

- 项目有轻量 SQLite migration 机制：`db_migrations.py`
- `schema_migrations` 表记录已执行版本，历史补列不再靠裸 `ALTER TABLE ... try/except pass`
- 新环境首次启动就会自动初始化数据库

## 5. 前台与后台页面

### 前台

- 路径：`/`
- 静态入口：`static/index.html`
- 主脚本：`static/app.js`
- 主要页面切换由前端单页脚本自己控制

前台当前包含这些视图能力：

- 聊天
- 资讯
- 热门问题/发现
- 产品
- 社区问答
- 聊天回答后的相关案例卡片
- 团队/姓名身份门禁

前台会先请求：

- `/api/agents`
- `/api/waiting-content`
- `/api/default-team`

身份门禁依赖本地缓存 `chat_profile` 和后台配置的团队名单。

### 后台

- 路径：`/admin`
- 模板：`templates/admin.html`

后台是一个大而全的单页管理台，主要负责：

- 管理员登录
- 智能体配置
- 资讯管理
- 案例档案管理
- 默认团队配置
- Coze API Key 配置
- 等待文案配置
- 屏蔽词配置
- 对话数据统计和反馈分析
- 社区问答审核

独立营养师工作台：

- 路径：`/consultant`
- 支持坐席上线/下线、多人会话、排队、未读数、声音提示和浏览器桌面通知
- 营养咨询 AI 通过 `handoff_ai_agent_id` 独立配置，不跟随首页普通智能体

## 6. 主要后端模块

### 6.1 聊天服务

核心文件：

- `routes/chat.py`
- `services/chat_service.py`

职责：

- 构造 Coze 请求上下文
- 根据 `agent_id` 或 `query_type` 选择 bot
- 支持同步问答 `/api/chat/send`
- 支持流式 SSE `/api/chat/stream`
- 保存聊天记录
- 保存点赞/点踩及差评原因

几个关键点：

- `agent_id` 优先映射到 `agent_configs.bot_id`
- 如果没传 `agent_id` 或查不到，则按 `query_type -> Config.BOT_MAPPING`
- 流式接口会向前端发送 `status`、`delta`、`done`、`error`
- 同步和流式回答都会附带 `related_cases`，前端在机器人回答下方展示案例卡片
- 流式状态大致为：`connected -> searching -> generating -> saving -> done`

### 6.2 鉴权

核心文件：`routes/auth.py`

- 注册：`/api/auth/register`（默认关闭，需显式开启）
- 登录：`/api/auth/login`
- 前台身份会话：`/api/auth/session`（服务端生成不可自选的 guest user id）
- 鉴权方式：JWT Bearer Token
- token 默认有效期：7 天
- 管理员不通过公开注册创建；首次管理员使用 `scripts/create_admin.py`

兼容性细节：

- 老密码哈希可能是 sha256 纯 64 位字符串
- 用户登录成功后会自动升级为 Werkzeug 的现代哈希格式

### 6.3 内容管理

资讯：

- 路由：`routes/news.py`
- 数据表：`news`
- 支持置顶、精选、分类、浏览量

产品：

- 路由：`routes/products.py`
- 数据表：`products`
- 支持分类、排序、高亮描述
- 分类顺序单独存到 `settings.product_category_order`

案例档案：

- 路由：`routes/cases.py`
- 链接识别服务：`services/case_recognition_service.py`
- 数据表：`case_documents`
- 检索表：`case_documents_fts`，使用 SQLite FTS5 trigram
- 支持症状标签、产品标签、客户画像、使用场景、摘要、正文和封面图
- 用户提问后按症状/产品标签优先匹配，再用全文检索兜底，默认推荐 3 条
- 案例只在回答后展示，不参与 Coze prompt
- 前台不做底部导航入口；标签可点击查看同标签更多案例；外部案例库统一通过全局 `case_library_url` 跳转
- 前台案例查看已统一为一个案例抽屉：详情和列表在同一层内切换，标签和“查看相似案例”不会再叠两个弹层
- 聊天回答下方“查看更多”只打开本次问题相关案例，不再默认打开全部案例；如果没有更多相关案例，则不显示“查看更多”
- 支持后台配置全局 `case_library_url`，配置后案例详情底部显示“查看更多客户案例”H5 跳转按钮；未配置则不显示；单条案例不再维护独立外部跳转
- 后台支持“从链接识别案例”：粘贴公开 H5/网页链接后，先抓取网页文本，再用 Coze 做结构化抽取；AI 不可用时降级为规则识别
- 链接识别只返回预览，不直接入库；管理员可编辑预览，再“填入当前表单”或“确认创建案例”
- 链接识别接口有 SSRF 防护：只允许 `http/https`，拒绝 localhost、本地地址、内网地址、保留地址和非文本网页

### 6.4 社区问答

核心文件：`routes/community.py`

能力：

- 问题列表与详情
- 评论回复
- 回复点赞
- 后台审核问题与回复

业务规则：

- 前台回复默认昵称固定为 `匿名用户`
- 新回复创建后状态固定为待审核 `status=0`
- 审核通过后才公开展示
- 回复人自己可以通过 `viewer_id` 看见自己的待审核评论
- 屏蔽词检查依赖 `settings.blocked_keywords`

### 6.5 统计分析

核心文件：`routes/dashboard.py`

统计范围覆盖：

- 总对话量、今日对话量
- 去重用户数
- 各咨询类型使用量
- 最近对话
- 热门问题
- 用户数与管理员数
- 反馈总览、差评原因、按智能体聚合反馈
- 按团队/成员/问题维度汇总提问统计

### 6.6 管理配置

核心文件：`routes/admin.py`

主要配置项：

- `coze_api_key`
- `blocked_keywords`
- `waiting_tips`
- `waiting_steps`
- `default_team_names`
- 兼容老字段 `default_team_name`

文件上传说明：

- 管理后台支持图片上传
- 上传后统一转 JPEG
- 最大上传体积 8MB
- 主图最长边压缩到 1200，并生成 `_thumb` 缩略图
- 保存目录：`static/uploads/`

## 7. 数据库结构速记

数据库文件默认位置：

- `Config.DATABASE_PATH`
- 默认即项目根目录下的 `ai_customer_service.db`

主要表：

- `users`
  - 用户账号、密码哈希、管理员标记
- `chat_history`
  - 聊天记录、反馈、差评原因、团队名、成员名
- `news`
  - 资讯内容、浏览量、置顶、精选、分类
- `products`
  - 产品资料、分类、排序、高亮信息
- `case_documents`
  - 客户案例档案、症状标签、产品标签、客户画像、场景、封面图、显示状态
- `case_tags`
  - 案例标准标签库，区分症状标签和产品标签，支持别名、启停和排序
- `case_document_tags`
  - 案例和标准标签的关联表，服务于标签筛选、别名匹配和后续治理
- `case_documents_fts`
  - 客户案例全文检索索引，服务于聊天后的相关案例推荐
- `agent_configs`
  - 智能体配置、bot_id、图标、聊天文案
- `settings`
  - 各类后台可编辑配置
- `satisfaction_surveys`
  - 满意度问卷打分
- `share_events`
  - 微信端分享图生成记录，记录团队、成员、咨询类型、历史记录和分享类型
- `questions`
  - 社区问题
- `replies`
  - 社区回复、审核状态、作者标识、点赞数

重要实现特征：

- 所有数据库操作基本都集中在 `models.py`
- 没有 ORM
- 读写都是手写 SQL
- 数据库结构变更通过 `db_migrations.py` 中的有序 migration 列表执行，并记录到 `schema_migrations`
- 已建若干索引，重点照顾聊天记录、资讯、问答查询

## 8. 核心接口地图

### 全局/页面

- `GET /`
- `GET /admin`
- `GET /consultant`
- `GET /api/waiting-content`
- `GET /api/default-team`
- `GET /api/case-library-config`
- `GET /api/user/profile`

### 认证

- `POST /api/auth/register`
- `POST /api/auth/login`

### 聊天

- `POST /api/chat/send`
- `POST /api/chat/stream`
- `POST /api/chat/feedback`
- `POST /api/share-events`

### AI 转人工营养咨询

- `GET /api/handoff/config`
- `POST /api/handoff/start`
- `GET /api/handoff/current`
- `GET /api/handoff/session/<session_id>`
- `POST /api/handoff/message`
- `GET /api/handoff/messages/<session_id>`
- `GET /api/handoff/recent`
- `POST /api/handoff/defer`
- `POST /api/handoff/close`
- `GET /api/admin/handoff/queue`
- `POST /api/admin/handoff/<session_id>/claim`
- `GET /api/admin/handoff/<session_id>/detail`
- `POST /api/admin/handoff/<session_id>/reply`
- `POST /api/admin/handoff/<session_id>/close`
- `POST /api/admin/handoff/<session_id>/read`
- `GET/POST /api/admin/handoff/agent/...`
- `GET /api/admin/handoff/notifications`
- `GET /api/admin/handoff/archive`
- `GET /api/admin/handoff/archive/<session_id>`
- `GET /api/admin/handoff/users/<user_id>/history`
- `POST /api/admin/handoff/export`
- `GET/PUT /api/admin/settings/handoff`

### 历史记录

- `GET /api/history`
- `GET /api/history/<id>`
- `GET /api/history/sessions`
- `POST /api/history/batch-delete`
- `GET /api/history/hot-questions`

### 智能体

- `GET /api/agents`
- `GET/POST/PUT/DELETE /api/admin/agents...`

### 资讯

- `GET /api/news`
- `GET /api/news/<id>`
- `POST/PUT/DELETE /api/news...`
- `PUT /api/news/<id>/pin`
- `PUT /api/news/<id>/feature`

### 产品

- `GET /api/products`
- `GET /api/products/<id>`
- `POST/PUT/DELETE /api/products...`
- `POST /api/products/category-order`
- `POST /api/products/reorder`

### 案例档案

- `GET /api/cases`
- `GET /api/cases/<id>`
- `GET /api/cases/search`
- `GET /api/admin/cases`
- `POST /api/admin/cases/recognize-link`
- `POST /api/admin/cases`
- `PUT /api/admin/cases/<id>`
- `DELETE /api/admin/cases/<id>`
- `PUT /api/admin/cases/<id>/status`
- `GET /api/admin/case-tags`
- `POST /api/admin/case-tags`
- `PUT /api/admin/case-tags/<id>`
- `PUT /api/admin/case-tags/<id>/status`
- `GET/PUT /api/admin/settings/case-library-url`

### 社区

- `GET /api/community/questions`
- `GET /api/community/questions/<id>`
- `POST /api/community/questions/<id>/replies`
- `GET /api/community/categories`
- `POST /api/community/replies/<id>/like`
- `GET/POST/PUT/DELETE /api/community/admin/...`

### 问卷

- `POST /api/survey`

### 仪表盘

- `GET /api/admin/dashboard/stats`
- `GET /api/admin/dashboard/trends`
- `GET /api/admin/dashboard/agent-usage`
- `GET /api/admin/dashboard/recent`
- `GET /api/admin/dashboard/hot-questions`
- `GET /api/admin/dashboard/user-stats`
- `GET /api/admin/dashboard/feedback-stats`
- `GET /api/admin/dashboard/feedback-overview`
- `GET /api/admin/dashboard/feedback-by-agent`
- `GET /api/admin/dashboard/negative-feedback`
- `GET /api/admin/dashboard/feedback-reasons`
- `POST /api/admin/dashboard/hot-questions/save`
- `GET /api/admin/dashboard/team-question-stats`

## 9. 环境变量与配置重点

关键环境变量在 `config.py`：

- `SECRET_KEY`
- `COZE_API_URL`
- `COZE_API_KEY`
- `DATABASE_DIR`
- `CORS_ORIGINS`
- `PUBLIC_REGISTRATION_ENABLED`
- `UPLOAD_DIR`
- `TRUST_PROXY`
- `BOT_PRODUCT`
- `BOT_FAQ`
- `BOT_MOMENT`
- `BOT_SCRIPT`
- `HANDOFF_ENABLED`
- `HANDOFF_AI_AGENT_ID`
- `HANDOFF_AVG_HANDLE_SEC`
- `HANDOFF_QUEUE_POLL_SEC`
- `HANDOFF_AGENT_STALE_SEC`
- `HANDOFF_CLAIM_TIMEOUT_SEC`

注意：

- `SECRET_KEY` 必须至少 32 个字符，否则应用拒绝启动
- 生产环境应显式设置 `DATABASE_DIR=/data` 和 `UPLOAD_DIR=/data/uploads`
- `CORS_ORIGINS` 默认为空；需要跨域时必须填写明确来源，不能使用 `*`
- Coze API Key 可以走环境变量，也可以被后台加密写入 `settings`

## 10. 部署现状

### Railway

- 配置文件：`railway.json`
- 使用持久卷挂载到 `/data`
- 当前 `railway.json` 已将 `DATABASE_DIR` 和 `UPLOAD_DIR` 指向 `/data` 持久卷

### Zeabur

- 配置文件：`zeabur.json`
- 启动命令同样是 Gunicorn

## 11. 测试与当前可验证状态

现有测试脚本：

- `scripts/test_today_features.py`
- `scripts/test_case_documents.py`
- `scripts/test_migrations.py`
- `scripts/test_security.py`

验收清单：

- `docs/CASE_ARCHIVE_V1_ACCEPTANCE.md`

我在当前环境实际执行过：

```bash
node --check static/app.js
python3 -m py_compile services/case_recognition_service.py routes/cases.py
python3 -m py_compile db_migrations.py models.py scripts/test_migrations.py
python3 scripts/test_migrations.py
python3 scripts/test_case_documents.py
python3 scripts/test_today_features.py
python3 scripts/test_security.py
```

结果通过，覆盖了这些近期开关点：

- 默认团队配置读写
- 团队统计过滤
- 成员名通配符转义
- 社区问题公开/隐藏状态
- 待审核评论仅作者可见
- 评论审核通过后公开
- 评论点赞计数
- 案例表和 FTS 表初始化
- 5 条虚拟案例 seed
- 症状/产品标签推荐匹配
- 隐藏案例不参与推荐
- `/api/chat/send` 返回 `related_cases`
- 案例公开详情和标签列表接口
- 后台案例 CRUD、显示/隐藏、删除
- 案例链接识别鉴权
- 非 HTTP、本地和内网链接拒绝
- 模拟 H5 页面识别
- AI 结构化抽取成功路径
- AI 失败时规则降级
- 识别预览不直接入库，确认保存后可搜索
- SQLite migration 空库初始化
- 旧库缺字段自动补齐
- 重复执行 `init_db()` 不重复记录 migration
- migration 失败时回滚且不写入版本记录
- 案例标准标签表和关联表初始化
- 现有案例逗号标签会回填为标准标签和关联关系
- 案例标签别名可归一到标准标签
- 按别名筛选和搜索可命中标准标签案例

当前本地运行状态：

- 正确后台入口是 `http://127.0.0.1:5001/admin`
- 不要直接打开 `file:///Users/test/Downloads/ai-customer-service/templates/admin.html`，否则登录会因为 `fetch` 不能访问后端接口而显示 `Failed to fetch`
- 当前 Flask 开发服务需要在项目根目录运行 `python3 app.py`，默认端口 `5001`
- 2026-06-30 自动化验收已通过；当前已启动 Flask 服务，`GET /admin`、`GET /api/cases` 可响应，后台登录后的人工点验仍需继续
- 最新已推送 GitHub：以 `git log -1 --oneline` 为准；当前最新功能批次包含案例标签标准化、后台案例 JS 拆分和图片加载性能优化。
- 当前工作区在最新提交后应保持干净；如有本地改动，先确认是否为新的未提交工作。

## 12. 2026-06-30 新增内容快照

今天主要新增和调整了案例档案能力：

- 新增独立案例档案模块，前台不新增主栏目，只在 AI 回答后推荐相关案例卡片。
- 新增 `case_documents` 和 `case_documents_fts`，使用症状标签、产品标签和全文检索混合匹配。
- 新增 5 条虚拟案例 seed，用于验证便秘、腹胀、口臭、免疫力、皮肤状态等场景。
- 聊天同步和流式接口都会返回 `related_cases`，案例不参与 Coze prompt。
- 前台案例查看从“双弹层”改成统一 `case-drawer`，支持详情、列表、标签筛选、相似案例和返回上级列表。
- 后台“案例档案”支持新增、编辑、删除、显示/隐藏和封面图；外部跳转统一走全局客户案例库 H5 链接。
- 后台新增“从链接识别案例”入口，面向公开 H5/网页案例链接，先预览再保存。
- 简化前台案例交互：不做搜索、不默认看全部案例；“查看更多”只展示本次问题相关的更多案例。
- 新增外部客户案例库 H5 跳转配置：后台填写链接后，只在案例详情底部显示“查看更多客户案例”按钮，不放首页和底部导航。
- 新增测试脚本 `scripts/test_case_documents.py`，覆盖案例推荐、CRUD、链接识别和聊天接口回归。
- 新增验收清单 `docs/CASE_ARCHIVE_V1_ACCEPTANCE.md`，记录后台案例管理、链接识别、前台抽屉、移动端 UI 和发布前检查项。
- 新增轻量 SQLite migration 机制：`db_migrations.py` + `schema_migrations`，历史补列不再靠 `ALTER TABLE ... try/except pass`。
- 新增测试脚本 `scripts/test_migrations.py`，覆盖空库、旧库、重复初始化和失败回滚。
- 新增案例标签轻量标准化：`case_tags` + `case_document_tags`，保留原逗号文本字段做兼容展示。
- 后台“案例设置”增加标签库，可维护症状/产品标准标签、别名、排序和启停。
- 后台案例 JS 拆分 v1 已完成：案例管理、标签库、链接识别、案例库 H5 设置已从 `templates/admin.html` 迁到 `static/admin/cases.js`。

## 12.1 2026-07-01 图片与加载速度优化快照

本次针对服务器部署后图片加载慢做了轻量优化，不引入 CDN/对象存储：

- 新增 `services/image_service.py`，后台上传图片时统一压缩为优化 JPEG，并生成 `_thumb.jpg` 缩略图。
- `/api/admin/upload` 仍返回兼容字段 `url`，额外返回 `thumb_url`、图片尺寸和压缩后体积。
- 前台 `static/app.js` 新增统一 `renderImage()`，案例、资讯、发现页列表优先加载缩略图，详情页加载主图。
- 前台图片增加 `loading="lazy"` 和 `decoding="async"`，首屏轮播/头像保留 eager 加载。
- Flask 增加静态资源缓存头：上传图片强缓存，普通图片/CSS/JS 短期缓存，HTML 不强缓存。
- 新增 `scripts/optimize_uploaded_images.py`，默认 dry-run；`--apply` 时会先备份 SQLite，再生成优化图并更新本地 `/uploads/...` 数据库引用。
- 生成保留透明通道的首屏压缩头像 `static/avatar-optimized.png`，首页从原 `avatar.png` 改为引用压缩版；`static/bot-avatar-optimized.png` 已生成备用。
- 本地 dry-run 显示当前已引用历史上传图可优化 18 张，预计主图体积节省约 38MB；尚未自动执行 `--apply`。

## 12.2 2026-07-06 新闻详情打开速度优化快照

本次定位到新闻详情慢的主要原因是历史正文里保存了 `data:image/base64` 内嵌图：

- 本地曾有 2 篇新闻正文包含 base64 图片，其中最大一篇正文约 5MB，点击详情时会把整张图塞进 JSON 返回。
- 新增 `scripts/optimize_news_content_images.py`，默认 dry-run；`--apply` 时先备份 SQLite，再把新闻正文内嵌图片转为 `/uploads/...` 文件 URL。
- 后台新闻 Quill 编辑器的图片按钮、粘贴和拖入图片都改为走 `/api/admin/upload`，不再让正文存 base64。
- 保存新闻前会拦截 `data:image` 正文，提示管理员通过上传方式插入图片。
- 前台新闻详情改为点击后立即打开加载态，详情加载成功后再填充内容；同一篇新闻二次打开走内存缓存。
- 新闻详情正文里的图片会补 `loading="lazy"` 和 `decoding="async"`，减少正文多图时的加载阻塞。

服务器更新这次改动时，拉取最新代码后需要在真实持久化数据库上执行：

```bash
git pull origin main
python3 scripts/optimize_news_content_images.py
python3 scripts/optimize_news_content_images.py --apply
```

如果生产环境使用 Railway/Zeabur 持久卷，先确认 `DATABASE_DIR` 指向真实数据目录，例如 Railway 常见为 `/data`。`--apply` 会自动生成 `ai_customer_service.db.bak.news-content.*` 备份；确认新闻详情正常后保留一段时间再清理备份。

## 12.3 2026-07-06 微信端回答结果分享卡 v1

本次新增面向微信 H5 的单条回答分享图，不接微信 JS-SDK：

- 每条机器人回答的操作区增加 `生成分享图`，用于把单次问答生成适合微信长按保存/转发的竖版 PNG。
- 分享图包含 AI 宝儿标识、当前智能体、用户问题、AI 回答摘要、最相关案例摘要和当前 H5 链接提示。
- 回答过长会自动截断，避免图片无限拉长；有相关案例时展示第一条案例，没有案例则不留空白。
- 复用现有 `html2canvas` 和分享弹层，保留右上角“分享对话”原功能。
- 新增 `share_events` 表和 `POST /api/share-events`，只记录“生成分享图”行为，不追踪微信真实转发完成。

## 12.4 2026-07-06 微信端 H5 语音输入 v1

本次新增独立语音转文字能力，不接微信 JS-SDK：

- 后台“智能体配置/系统配置”新增语音输入开关和 ASR 服务配置；支持 `aliyun_asr` 和 `tencent_asr`，默认 provider 为 `aliyun_asr`。
- 阿里云一句话识别使用 `speech_provider`、`aliyun_nls_app_key`、`aliyun_access_key_id`、`aliyun_access_key_secret`；Secret 后台只脱敏回显，留空保存时不覆盖旧值。
- 语音识别不再提供 Coze 兼容入口；Coze 仅继续用于系统原有的对话和案例识别功能。
- 前台启动时读取 `/api/speech/config`；只有后台开启后，聊天输入框才显示麦克风按钮。
- 前端使用 H5 `MediaRecorder` 录音，最长 30 秒；识别成功后只填入输入框，不自动发送。
- 后端新增 `POST /api/speech/transcribe`，接收 `multipart/form-data` 的 `audio` 文件，限制 10MB。
- `services/speech_service.py` 会先用 ffmpeg 把浏览器录音统一转为 `16kHz / mono / WAV`，再提交给阿里云 ASR。
- 腾讯云识别使用 TC3-HMAC-SHA256 签名调用 `SentenceRecognition`，SecretKey 只加密保存并脱敏回显。
- 服务器必须安装 `ffmpeg`；Railway/Nixpacks 配置已补系统包。可用 `ALIYUN_NLS_TOKEN_URL`、`ALIYUN_NLS_ASR_URL` 覆盖阿里云接口地址。
- 微信 iOS 兼容性需要真机验证；如果 `MediaRecorder` 不可用，前台会提示使用文字或常见问题卡片。

## 13. 已知实现特点与风险点

这些不是马上要改的 bug 清单，但后续接手时最好脑子里有数：

- `models.py` 过于集中，承担了全部数据访问，继续扩展会越来越重。
- 数据库 migration 目前是轻量 Python 列表机制，适合当前 SQLite 单实例；如果以后迁移复杂化，再考虑 Alembic。
- SQLite 适合当前体量，但多副本部署、重写入、复杂分析都会撞墙。
- 人工咨询状态依赖同一份 SQLite 数据库；当前适合单实例、少量坐席和几十个活跃会话，多副本或更高并发应迁移到 PostgreSQL/Redis 与专用推送通道。
- 客服桌面通知基于页面轮询与浏览器 Notification API；关闭浏览器后不能继续通知，如需离线提醒应接入 Web Push 或企业消息平台。
- 管理后台图片上传依赖 Pillow，当前 `requirements.txt` 已显式写入 `Pillow==10.2.0`。
- 前台 `static/app.js` 是大体量单文件脚本，后续维护成本会继续上升。
- 后台案例 JS 已拆到 `static/admin/cases.js`；`templates/admin.html` 仍包含其它后台模块的大量内联脚本，继续扩功能时仍需逐步拆分。
- 历史图片优化脚本默认只 dry-run；服务器执行 `--apply` 前要确认 `DATABASE_DIR` 指向真实持久化 SQLite，并保留脚本生成的 `.bak` 数据库备份。
- 新闻正文图片必须走上传 URL，不要让 Quill 保存 `data:image/base64`；如果详情再次变慢，先用 `scripts/optimize_news_content_images.py` 检查。
- 上传目录由 `UPLOAD_DIR` 控制；Railway 默认使用 `/data/uploads`，图片量继续增长后再考虑对象存储/CDN。
- 案例链接识别依赖目标网页可公开访问；小程序私有路径、登录后页面、强反爬页面只能保留外链并手动补正文。
- 案例链接识别复用 Coze API 做结构化抽取；未配置 API Key 或 Coze 失败时会降级，但标签质量需要人工确认。
- `outputs/` 目录看起来是历史设计/生成产物，不属于主业务运行链路，清理前先确认是否还有人依赖。

## 14. 下次排查时优先读哪些文件

如果以后只想快速恢复上下文，按下面顺序读就够：

### 想了解整体

1. `PROJECT_CONTEXT.md`
2. `README.md`
3. `app.py`
4. `config.py`

### 想看聊天链路

1. `routes/chat.py`
2. `services/chat_service.py`
3. `models.py` 中 `save_chat_history` 相关函数

### 想看后台配置

1. `templates/admin.html`
2. `routes/admin.py`
3. `routes/dashboard.py`

### 想看 AI 转人工与营养师工作台

1. `docs/HANDOFF_DESIGN.md`
2. `services/handoff_service.py`
3. `routes/handoff.py`、`routes/admin_handoff.py`
4. `templates/consultant.html`、`static/consultant/`
5. `scripts/test_handoff.py`

### 想看前台体验

1. `static/index.html`
2. `static/app.js`
3. `static/styles.css`
4. `services/image_service.py`
5. `scripts/optimize_uploaded_images.py`
6. `scripts/optimize_news_content_images.py`

### 想看社区问答

1. `routes/community.py`
2. `models.py` 中 `questions/replies` 相关函数
3. `scripts/test_today_features.py`

### 想看案例档案

1. `routes/cases.py`
2. `services/case_recognition_service.py`
3. `models.py` 中 `case_documents` 相关函数
4. `static/app.js` 中 `relatedCases/caseDrawer` 相关函数
5. `static/admin/cases.js` 中后台案例管理、标签库和链接识别逻辑
6. `templates/admin.html` 中案例页 HTML 结构
7. `scripts/test_case_documents.py`

## 15. 推荐的后续整理方向

如果以后要继续维护，这几个方向最值：

1. 把 `models.py` 按领域拆分，至少分成 chat/news/product/community/user。
2. 把前台大脚本拆模块，至少把聊天、资讯、社区、后台 API 调用拆开。
3. 继续拆后台大模板，案例模块已经拆出；下一步优先拆仍在 `templates/admin.html` 里的产品管理和资讯管理。
4. 给部署环境补明确说明，尤其是 `DATABASE_DIR=/data` 这类持久化配置。

## 16. 一句话接手建议

这是个能跑、功能齐、但结构偏“单体堆叠式演进”的 Flask 项目。后续任何改动，先确认你碰的是聊天链路、内容链路、还是社区链路，再定点读文件，不要一上来全仓乱翻。

## 17. 2026-07-17 v1.1.3 腾讯云原生级语音输入

- 语音服务统一为腾讯云 ASR；旧版阿里云配置不再由前后台读取，历史配置字段暂不删除，避免升级时破坏现有数据库。
- 默认使用“实时优先、失败自动转写”模式。浏览器直连腾讯云实时 WebSocket，发送 `16kHz / 16bit / mono PCM`，约每 200ms 一包，文字实时写入当前光标位置。
- `POST /api/speech/realtime/session` 在服务端生成 5 分钟有效的单次签名地址；腾讯云 SecretKey 不下发浏览器。
- 实时录音期间同步保留本地 PCM。连接中断时，同一段录音自动提交腾讯云 `SentenceRecognition` 完成转写，用户无需重新说一遍。
- 后台支持 `auto / realtime / batch` 三种模式，实时模式需配置 AppID、SecretId、SecretKey；SecretKey 继续加密保存且仅脱敏回显。
- 前台新增连接、录音、音量、时长、收尾和转写状态；支持主动取消并恢复原草稿。识别结果只进入输入框，不自动发送。
- 每位用户的实时会话独立生成 `voice_id` 和 WebSocket，音频不经过 Flask 代理，多人同时使用不会串音或共享录音状态。

## 18. 2026-07-20 v1.1.4 AI 转人工营养咨询

- 人工入口改为 AI 优先的明确意图触发，仅“深度调理答疑”支持转人工；普通提及不会误触发。
- 新增独立 PC 营养师工作台 `/consultant`，支持坐席上下线、多会话排队接待、未读提醒、声音与桌面通知。
- 营养咨询 AI 使用 `handoff_ai_agent_id` 独立配置；人工接管时停止 Coze 路由，结束后自动恢复 AI。
- 在线等待默认 120 秒；无人回复时自动转为异步留言，也支持用户主动挂起。留言不阻塞 AI，营养师回复后自动归档。
- 新增咨询档案、筛选分页、只读详情和同一用户历史回复。
- 新增单次、多选和筛选 CSV 导出，限制 5,000 条，支持 UTF-8 BOM、公式注入防护和 `handoff_export_logs` 审计；不导出转人工前 AI 对话。
- 数据库迁移新增人工咨询相关表、留言模式字段和导出审计表；完整回归入口为 `scripts/test_handoff.py` 与 `scripts/test_handoff_intent.js`。
