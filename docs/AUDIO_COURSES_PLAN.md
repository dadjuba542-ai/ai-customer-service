# 音频课程推送功能方案（audio_courses）

> 状态：Phase 1 实施中
> 关联：案例系统（`cases`）、功能开关（`docs/FEATURE_FLAGS.md`）

## 1. 目标

新增一个与「案例系统」平级、可独立开关的内容模块「音频课程」：

- 前台提供**独立问答入口**：用户提问 → 返回相关音频课程 + 播放器。
- 课程音频**双来源**：本站上传（`UPLOAD_DIR`）或第三方外链（https）。
- **轻量数据模型**：不做封面图、不做讲师字段。
- 通过统一功能开关 `audio_courses` 控制，**默认关闭**。

## 2. 关键决策

| 项 | 选择 | 说明 |
| --- | --- | --- |
| 投放方式 | 独立问答入口（Phase 1） | 不动聊天链路，不影响聊天延迟；Phase 2 再加 AI 回答后自动推送 |
| 音频来源 | 本站上传 + 外链 | 上传存持久卷；外链支持小鹅通/喜马拉雅等 |
| 匹配方式 | 标签 + 全文检索 | 复用案例打分算法，零额外成本 |
| 默认开关 | 关闭 | 内容就绪后管理员在后台开启 |
| 封面图 | 不做 | 列表用音频图标占位 |
| 讲师 | 不做 | 字段与 UI 均省略 |
| 置顶 | 支持 | `pinned`：排序时置顶优先，后台一键切换 |
| 首页展示 | 支持 | `show_on_home`：只有勾选的进首页 tab，首页固定 6 条 |

## 3. 数据模型（`db_migrations.py`，版本 `202609140001` + `202609140002`）

```sql
CREATE TABLE IF NOT EXISTS audio_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    series TEXT DEFAULT '',
    episode INTEGER DEFAULT 0,
    duration_seconds INTEGER DEFAULT 0,
    audio_url TEXT DEFAULT '',
    external_url TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    content TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    status INTEGER DEFAULT 1,
    pinned INTEGER DEFAULT 0,
    show_on_home INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audio_courses_status_sort
    ON audio_courses(status, sort_order ASC, id DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS audio_courses_fts USING fts5(
    title, series, summary, content, tags, tokenize='trigram'
);
```

- 标签先用逗号分隔文本，Phase 1 不做标准标签库。
- FTS 的增删改与 `case_documents_fts` 保持同一套写法。

## 4. 功能开关

`services/feature_flags.py` 新增：

```python
AUDIO_COURSES = 'audio_courses'
# 开关只控制前台展示；后台管理路径豁免，管理员可先录课程再决定是否开启
_AUDIO_COURSES_ROUTES = ('/api/audio-courses',)
_AUDIO_COURSES_ROUTE_EXEMPT = ('/api/admin/audio-courses',)

FeatureFlag(
    name=AUDIO_COURSES,
    key='audio_courses_enabled',
    env='AUDIO_COURSES_ENABLED',
    default=Config.AUDIO_COURSES_ENABLED,   # 默认 False
    label='音频课程',
    description='音频课程库：独立问答入口、标签/全文检索、后台课程管理、音频上传与外链。',
    routes=_AUDIO_COURSES_ROUTES,
    route_exempt=_AUDIO_COURSES_ROUTE_EXEMPT,
)
```

- **开关语义**：关闭时前台入口与公开接口（`/api/audio-courses`）全停；**后台管理始终可用**，
  避免「关闭状态无法备稿」的死循环。后台侧边栏入口不带 `data-feature`，始终可见。

- `config.py` 增加 `AUDIO_COURSES_ENABLED`（默认 false）。
- 自动继承三层拦截：HTTP 入口 403 (`code=feature_disabled`)、服务层短路、后台侧边栏入口隐藏。
- 后台「功能开关」页零改动即可开关。

## 5. 后端

### 5.1 `models.py`

新增：`create_audio_course`、`update_audio_course`、`delete_audio_course`、
`get_audio_course_by_id`、`get_all_audio_courses`、`get_audio_courses_page`、
`search_audio_courses_page`、`set_audio_course_status`、`get_audio_course_tags`。

- 匹配打分复用案例逻辑：`标签命中 × 100 + FTS × 25 + 正文命中 × 10`。
- 公开查询只返回 `status = 1`。

### 5.2 `routes/audio_courses.py`

公开（开关关闭时 403）：

- `GET /api/audio-courses`（page / limit / tag）
- `GET /api/audio-courses/<id>`
- `GET /api/audio-courses/search?q=`
- `GET /api/audio-courses/tags`

后台（`@admin_required`）：

- `GET /api/admin/audio-courses`
- `POST /api/admin/audio-courses`
- `PUT /api/admin/audio-courses/<id>`
- `DELETE /api/admin/audio-courses/<id>`
- `PUT /api/admin/audio-courses/<id>/status`
- `PUT /api/admin/audio-courses/<id>/flag`（`pinned` / `show_on_home`）
- `POST /api/admin/audio-courses/upload-audio`

### 5.3 音频上传 `services/audio_service.py`

- 允许扩展名：`mp3 / m4a / aac / wav / ogg / mp4`。
- 存 `UPLOAD_DIR/audio/`，uuid 命名，返回 `/uploads/audio/...`。
- 有 `ffprobe` 时自动识别时长，否则管理员手填。
- 大小上限由 `Config.AUDIO_MAX_UPLOAD_BYTES` 控制。

### 5.4 `services/content_security.py`

新增 `sanitize_audio_url()`：仅允许同源 `/uploads/` 相对路径或 `http/https`。

### 5.5 `app.py`

- 注册 `audio_courses_bp`（`url_prefix='/api'`）。
- CSP `media-src` 从 `'self' blob:` 扩展为 `'self' blob: https:`（支持外链音频）。

## 6. 前台（独立问答入口）

- `static/index.html`：
  - 首页「快捷功能 / 音频课程」为并排 tab，默认显示快捷功能；点「音频课程」懒加载 `?mode=home&limit=6`。
  - 新增 `audio-view` 独立页面。
  - 引入 `audio-courses.js` 与 `audio-courses.css`（带新缓存版本号）。
  - 发现页增加音频课程入口。
- `static/js/audio-courses.js`：提问框 → `/search`；标签 chips；课程列表；点击开详情抽屉，内含 `<audio controls>` 播放器 + 文字稿 + 外链按钮。
- `static/js/core.js`：`FEATURE_FLAGS` 增加 `audio_courses`；关闭时不渲染、不发请求。
- `static/css/audio-courses.css`：字号用 `calc(Npx * var(--fs-scale))`，兼容大字版。

## 7. 管理后台

- `templates/admin.html`：侧边栏新增 `data-page="audio-courses" data-feature="audio_courses"` 入口；新增 `page-audio-courses` 页面。
- `static/js/admin.js`：`switchPage` 标题与加载分发增加 `audio-courses`。
- `static/js/admin-audio-courses.js`：列表 + 新增/编辑表单（标题 / 系列 / 讲次 / 时长 / 音频上传或外链 / 外部播放页 / 摘要 / 文字稿 / 标签 / 状态 / 排序）。

## 8. 安全与部署

- 所有写入接口 `@admin_required`；公开接口只读 `status=1`。
- 音频 URL 统一走 `sanitize_audio_url`，拒绝 `javascript:`、`file:`、`data:` 等。
- `UPLOAD_DIR` 在 Railway/Zeabur 指向持久卷（`/data/uploads`）。
- 音频体积较大，全局 `MAX_CONTENT_LENGTH` 需放宽（图片接口仍单独限制 8MB）。

## 9. 测试与验收

- 新增 `scripts/test_audio_courses.py`：建表 / FTS、标签与全文命中、隐藏不返回、CRUD、鉴权、开关关闭三层拦截、音频上传扩展名与大小校验。
- 更新 `scripts/test_feature_flags.py` 覆盖新开关。
- 回归 `test_case_documents.py`、`test_today_features.py`。

## 10. 分期

- **Phase 1（本次）**：开关 + 建表 + 音频上传 + 后台管理 + 独立问答入口 + 播放器。
- **Phase 2**：AI 回答后自动推送（模式 A，复用同一检索）+ 链接识别入库 + 系列聚合页 + 播放量统计 + 标准标签库。

## 11. 文档更新

- 本文档、`docs/FEATURE_FLAGS.md` 开关表、`PROJECT_CONTEXT.md`、`README.md`、`CHANGELOG.md`。

## 12. 安全与健壮性加固（评审后）

- **属性转义**：前台新增 `escapeAttr()`（`static/js/audio-courses.js`），用于 `src`/`href`/`data-*`；
  标签按钮改为 `data-tag` + 事件委托，移除内联 `onclick` 拼接。
- **服务端 URL 收紧**：`sanitize_audio_url()` 仅允许 `http(s)://` 或 `/uploads/`，并显式拒绝
  引号、尖括号与空白，作为前端转义之外的第二道防线。
- **精简投影**：公开 `list / home / search` 返回 `_audio_course_preview`，不含文字稿 `content`
  与 `audio_url`；详情与后台仍返回完整字段。
- **文件清理**：删除课程、替换音频时删除对应的本地音频文件（`delete_local_audio`，
  严格限制在 `UPLOAD_DIR/audio` 内）；另提供 `scripts/cleanup_audio_uploads.py`
  （默认 dry-run，`--apply` 前备份 DB）清理历史孤儿文件。
- **上传**：`save_uploaded_audio` 改为流式落盘后再校验大小，不再整包读入内存；
  路由按 `request.content_length` 预检，超限直接 413。
- **PUT 合并式更新**：只覆盖请求中显式出现的字段，避免部分更新清空数据。
- **LIKE 转义**：标签筛选对 `% _ \` 做转义并加 `ESCAPE`。
- **缓存版本**：`audio-courses.js/css` → `?v=20260914-audio3`，后台 → `?v=20260914-audio2`。
