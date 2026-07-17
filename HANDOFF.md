# AI 宝儿智能体｜交接与运维说明

> 面向后续开发者、运维人员和项目接手人。敏感值（`SECRET_KEY`、Coze/腾讯云密钥、管理员密码）只放在服务器环境或数据库哈希中，不写入 Git。

## 1. 当前状态

- 当前发布分支：`1.1.2`
- `1.1`：历史稳定分支，保留不改
- 远程仓库：`origin`
- 当前 `1.1.2` 最新提交：以 `git log -1 --oneline` 为准
- 应用形态：单体 Flask + SQLite + 静态前端
- 正确后台地址：`http://服务器地址/admin`
- 不要直接打开：`file:///.../templates/admin.html`

`file://` 方式没有 Flask API 来源，登录会报 `Failed to fetch`。本地必须通过 Flask 服务访问。

## 2. 技术结构

```text
app.py                  Flask 入口、蓝图注册、全局接口
config.py               环境变量与启动校验
models.py               SQLite 初始化和数据访问
db_migrations.py        可重复执行的数据库迁移
routes/                 认证、聊天、资讯、产品、案例、社区、语音等接口
services/               Coze、ASR、图片、案例识别等服务
static/index.html       前台页面结构
static/app.js           前台交互与 API 调用
static/styles.css       前台样式
static/icon-fallback.css 图标字体不可用时的几何 fallback
templates/admin.html    管理后台页面和后台交互脚本
scripts/                管理员初始化、密码重置和冒烟测试
```

## 3. 本地启动

在项目根目录执行：

```bash
pip install -r requirements.txt
export SECRET_KEY='本地至少32位测试密钥'
export DATABASE_DIR='/tmp/ai-customer-service-local'
export UPLOAD_DIR='/tmp/ai-customer-service-local/uploads'
python3 app.py
```

默认端口：`5001`。

访问：

- 前台：`http://127.0.0.1:5001/`
- 后台：`http://127.0.0.1:5001/admin`

如果修改了 Python 路由或模板，必须重启 Flask；如果修改了前端资源，至少要强制刷新浏览器。

## 4. 生产环境必需配置

生产环境至少确认以下配置：

```bash
SECRET_KEY='固定且至少32位的随机密钥'
DATABASE_DIR='/持久化磁盘/目录'
UPLOAD_DIR='/持久化磁盘/目录/uploads'
PUBLIC_REGISTRATION_ENABLED='false'
```

可选配置：

- `COZE_API_KEY`
- `BOT_PRODUCT`、`BOT_FAQ`、`BOT_MOMENT`、`BOT_SCRIPT`
- 腾讯云 ASR 配置（AppID、SecretId、SecretKey）
- `TRUST_PROXY=true`（反向代理后使用）
- `CORS_ORIGINS`（只填写明确域名，禁止 `*`）

重点：`DATABASE_DIR` 和 `UPLOAD_DIR` 必须指向持久化磁盘，否则重启或重新部署可能丢失文章、产品、聊天记录和图片。

## 5. 管理员账号

管理员不会通过公开注册自动生成。首次初始化：

```bash
python3 scripts/create_admin.py admin8
```

脚本会在终端交互式输入密码，并写入安全哈希。忘记密码时：

```bash
python3 scripts/reset_admin_password.py admin8
```

不要把密码写入脚本、`.env`、README 或 Git。服务器和本地使用的是各自数据库，账号不会自动同步。

## 6. 1.1.2 功能交接重点

### 客户需求记录

- AI 回答操作区提供“获取方案”。
- 记录客户类型、手机号或微信号、关注产品、需求描述、来源问题和来源智能体。
- 后台“客户需求”只做轻量记录查看，不做复杂跟进流程。
- 相关表：`lead_requests`。

### 首页精选资讯

- 首页精选条读取 `category='首页滚动'` 的内容。
- 发现页、首页最新资讯和普通资讯管理列表排除“首页滚动”。
- 后台“首页滚动管理”单独维护，可点击“新增”进入编辑器创建内容。
- 标题最多显示 18 个字符，首页每 4 秒更换一篇。
- 点击精选条仍打开文章详情。

### 首页示例问题

- 首页“不知道怎么问？试试这些”支持后台编辑。
- 后台入口位于数据看板配置区域。
- 接口：`GET /api/example-questions`、`GET/PUT /api/admin/settings/example-questions`。

### 其他保留能力

- 产品、资讯、案例、社区、聊天、语音和分享功能保持原有入口。
- 语音服务统一使用腾讯云 ASR：实时识别为主，同一段录音批量转写为兜底，不再提供阿里云或 Coze 语音入口。
- 图标字体不可用时使用 CSS 几何 fallback，避免出现方块字符。

## 7. 数据与迁移

数据库默认文件名：`ai_customer_service.db`。

应用启动时会执行：

1. 建立缺失的数据表和索引。
2. 执行 `db_migrations.py` 中尚未执行的 migration。
3. 在 `schema_migrations` 中记录版本。

发布前建议备份：

```bash
cp "$DATABASE_DIR/ai_customer_service.db" \
   "$DATABASE_DIR/ai_customer_service.db.bak.$(date +%Y%m%d-%H%M%S)"
```

至少备份：数据库文件、`UPLOAD_DIR` 图片目录和当前部署版本信息。

## 8. 发布与回滚

### 发布 `1.1.2`

```bash
git fetch origin
git checkout 1.1.2
git pull --ff-only origin 1.1.2
python3 -m py_compile app.py models.py db_migrations.py routes/*.py services/*.py
python3 scripts/test_migrations.py
python3 scripts/test_security.py
```

然后按服务器的进程管理方式重启 Gunicorn/Flask 服务。

### 回滚到 `1.1`

```bash
git fetch origin
git checkout 1.1
git pull --ff-only origin 1.1
```

不要删除或强推 `1.1`。数据库备份和上传目录不要跟着代码回滚覆盖。

## 9. 发布后验收

按顺序检查：

1. `/admin` 能打开，管理员能登录。
2. 首页能加载，精选资讯能显示并点击详情。
3. 发现页不出现“首页滚动”分类。
4. 后台“首页滚动管理”能新增、编辑、移除。
5. 后台普通资讯列表不混入首页滚动。
6. 产品、文章、案例、聊天、语音入口可用。
7. 图片能加载，上传目录仍指向持久化磁盘。
8. 服务器日志没有 migration、SECRET_KEY、数据库锁或静态资源 404 错误。

## 10. 常见故障排查

### 登录提示 `Failed to fetch`

通常是直接打开了 `file:///.../templates/admin.html`。改用 `/admin` 服务地址。

### 登录提示账号或密码错误

确认当前服务使用的 `DATABASE_DIR`，再查询该数据库是否有管理员；必要时运行 `reset_admin_password.py`。本地数据库和服务器数据库互不相同。

### 页面仍显示旧按钮或旧布局

1. 确认 Flask 已重启（模板有缓存）。
2. 浏览器执行强制刷新：Mac `Command + Shift + R`，Windows `Ctrl + F5`。
3. 检查 HTML 中的 CSS/JS 查询版本是否更新。

### 数据重启后消失

优先检查 `DATABASE_DIR`、`UPLOAD_DIR` 是否落在临时目录；生产环境不要使用项目目录临时 SQLite 或容器临时盘。

### 精选资讯和发现页互相影响

检查 `routes/news.py` 的 `mode=bulletin`、`mode=discover`、`mode=content` 分流；不要把首页滚动内容改回普通资讯查询。

## 11. 安全底线

- 不提交 `.env`、数据库文件、数据库备份、API Key、SECRET_KEY、管理员明文密码。
- 不在生产环境使用公开注册。
- 不为了修复登录直接把管理员密码写进代码。
- 服务器发布前先备份数据库和上传目录。
- 涉及数据库删除、批量更新、迁移调整时先确认影响范围。

## 12. 后续维护建议

1. 将 `models.py` 按用户、聊天、资讯、产品、社区等领域拆分。
2. 将 `static/app.js` 按聊天、资讯、社区、分享等模块拆分。
3. 将 `templates/admin.html` 内联脚本继续迁移到独立 JS 文件。
4. 为首页滚动内容增加排序字段，而不是长期依赖创建时间排序。
5. 服务器部署逐步统一到持久化目录和明确的进程管理配置。
