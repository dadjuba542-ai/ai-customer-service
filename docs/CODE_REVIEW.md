# 代码评审报告

- 评审范围：`ai-customer-service` 全量 Python 后端（19 个路由 / 11 个服务 / 数据层 / 迁移）+ 前端关键路径抽查
- 代码规模：约 22,600 行（后端 ~4,900 行，前端 ~17,700 行）
- 技术栈：Flask 3.0 + SQLite(WAL) + PyJWT + requests + Pillow + cryptography，gunicorn gthread 部署
- 评审方式：全量通读 + 对 5 处关键结论做了可复现的实测验证（结果见各条目「实测」字段）

---

## 一、总体评价

一个**功能完成度相当高**的 Flask 单体应用：AI 问答（同步 + SSE 流式 + DB 队列兜底）、人工转接工作台、案例库 FTS5 检索、社区、资讯、后台配置一应俱全。分层清晰（`routes/` 只做参数与 HTTP 语义、`services/` 承载业务逻辑、`models.py` 做数据访问），没有把 SQL 写进路由层。

更难得的是**安全意识在线**：SQL 全部参数化、自建 HTML 白名单清洗器、SSRF 防护、密钥加密落库、JWT 分级（user/guest/admin）、多层级限流、完整安全响应头。这些不是"有就行"，而是写得比较到位——说明作者是认真考虑过攻击面的。

主要问题集中在**运行时正确性**和**SQLite 使用方式**上，不是"代码写得糙"，而是"在错误的场景用了 SQLite 的写路径"：

1. **读路径占用全局写锁** —— 人工转接的轮询接口每次都会跑一遍 `BEGIN IMMEDIATE` + 全量对账，把 SQLite 的单写者特性变成了全局串行瓶颈。这是本次评审中**最需要优先处理**的问题。
2. **N+1 连接** —— `get_handoff_settings()` 一次调用开 8 个 SQLite 连接，且被放在了逐行调用的循环里。
3. **两处已实测复现的功能性 bug** —— 富文本清洗器被自闭合标签静默截断、社区浏览量自增被事务回滚。
4. **部署约束风险** —— WAL + 多 worker + 可能是网络卷，组合起来有数据损坏隐患。

维护性方面：文档（README / HANDOFF.md / PROJECT_CONTEXT.md / docs/）写得比多数同类项目扎实，但测试是 8 个自研脚本、无 CI 门禁，且仓库里躺着 75MB 产物。

**结论**：代码质量中上，安全基线良好；建议按「先修 2 个实测 bug 和 1 个掩码问题（1 天内），再动读路径与事务封装（2-4 周），最后决定存储方案（需先确认部署环境事实）」的节奏推进。

---

## 二、优点

| # | 优点 | 证据 |
|---|---|---|
| 1 | **SQL 注入面干净** | 全量参数化；动态 SQL 片段（`where`/`order by`/`tag_column`）均来自字面量或白名单判断，如 `models.py:794`、`handoff_service.py:806-809`、`dashboard.py:141` |
| 2 | **密钥管理成体系** | `services/secret_service.py` 用 Fernet 加密 `coze_api_key`/`tencent_secret_key`，启动时自动迁移明文（`:50-59`），`Config.validate()` 强制 `SECRET_KEY ≥ 32` 位（`config.py:52-57`） |
| 3 | **富文本清洗有出口兜底** | `sanitize_rich_html` 在写入（`routes/news.py:49`）和读取（`routes/news.py:60`）时各调用一次，双保险 |
| 4 | **SSRF 防护认真做过** | `case_recognition_service.py:151-175` 解析 DNS + 判定 private/loopback/link-local/multicast/reserved，并手动跟随跳转时逐跳重校验（覆盖 169.254.169.254 元数据地址） |
| 5 | **限流与并发控制分层完整** | 令牌桶限流（`security_service.py:43`）+ 进程内信号量（`:13-40`）+ DB 队列 + 唯一索引防重复排队（`db_migrations.py:262`） |
| 6 | **迁移框架可靠** | `db_migrations.py` 有版本号、`BEGIN`/`COMMIT` 包裹、异常 `rollback`、已应用集合去重（`:329-355`） |
| 7 | **安全响应头齐全** | `app.py:104-116`：CSP / HSTS / nosniff / X-Frame-Options / Referrer-Policy / Permissions-Policy |
| 8 | **敏感文件未入库** | `.gitignore` 覆盖 `.env`、`*.db*`、`static/uploads/*`；实测 `.env` 与 `ai_customer_service.db` 均**未被 Git 跟踪** |
| 9 | **认证分级设计合理** | `routes/auth.py` 三档装饰器（`identity_required` 允许 guest / `token_required` 仅实名 / `admin_required` 校验 `is_admin`），guest token 无法提权 |
| 10 | **流式响应资源释放严谨** | `routes/chat.py:82-121` 用 `nonlocal` + `Lock` 保证 `release_slot()` 幂等，`finally` 与 `call_on_close` 双重兜底防泄漏 |

---

## 三、问题清单

### 严重（P0）

#### P0-1 高频轮询路径抢占 SQLite 全局写锁

- **位置**：`services/handoff_service.py:389`、`:402`、`:590`、`:608`；事务体在 `:242-253`
- **原因**：`get_current_session()` / `get_user_session()` / `get_agent_me()` / `list_agent_queue()` 四个**读接口**在开头都调用 `assign_available()`，后者执行 `conn.execute('BEGIN IMMEDIATE')`。SQLite 的 `BEGIN IMMEDIATE` 会**立即**获取 RESERVED 锁，无论后续是否真的写入；而 SQLite 是单写者模型，于是所有并发请求在这条路径上被完全串行化。

  前端侧的放大效应（`static/js/handoff.js:391-392`、`static/consultant/app.js:160`）：
  - 每个排队用户每 4 秒调用一次 `/api/handoff/session/<id>` → 1 次写事务
  - 营养师工作台 `pollAll` 每 4 秒调用 `agent/me` + `queue` → **2 次**写事务
  - 心跳每 20 秒调用 `set_agent_status` → 1 次写事务

  即 `N` 个排队用户 + 1 个坐席时，每 4 秒产生约 `N + 2` 次全局写事务。叠加 `busy_timeout=10s`，请求会排队等待而非快速失败，表现为整体响应变慢直到超时。
- **修改方向**：
  1. 把 `_reconcile_locked` 从读路径彻底摘出，改由**后台定时线程**执行（`ChatQueueDispatcher` 已有现成骨架可参考），周期 5–10 秒；
  2. 多进程下用 DB 层 advisory lock（如 `chat_jobs` 风格的租约表，或 SQLite `BEGIN EXCLUSIVE` 抢一个单行锁）保证同一时刻只有一个进程执行对账；
  3. 读接口退化为纯 `SELECT`。

#### P0-2 `_session_payload` 的 N+1 数据库连接

- **位置**：`services/handoff_service.py:280-281`（调用点）、`:46-56`（`get_handoff_settings`）、`:137-139`（`_reconcile_locked` 内也调用一次）、`:657`（`claim_session` 内再调一次）
- **原因**：`get_handoff_settings()` 内部连续调用 8 次 `get_setting()`，而 `models.get_setting()`（`models.py:263-269`）每次都 `get_db_connection()` → 一次 `sqlite3.connect` + 3 条 `PRAGMA`。`_session_payload` 对**每一条**会话记录调用它 1–2 次。
- **实测**（临时库，`models.get_db_connection` 打点计数）：

  | 调用 | 打开连接数 |
  |---|---|
  | `get_handoff_settings()` 单次 | 8 |
  | `list_recent_sessions(user, 5)` | 41 |
  | `list_agent_queue(agent)`，5 条排队 + 1 在线坐席 | 66 |

  且 `_reconcile_locked` 在**已持有 `BEGIN IMMEDIATE`** 的连接上，又额外开 8 个连接去读 settings —— 既浪费，也放大了持锁时间。
- **修改方向**：
  1. `get_handoff_settings(conn=None)` 支持传入连接复用；
  2. 或批量取：`SELECT key, value FROM settings WHERE key IN (...)` 一次拿全；
  3. 叠加进程内短 TTL 缓存（10 秒），`set_setting` / `update_handoff_settings` 时主动失效。

#### P0-3 每次启动静默删除 30 天前的聊天数据

- **位置**：`models.py:224`（调用点）、`:227-232`（实现）
- **原因**：`init_db()` 在末尾无条件执行 `cleanup_old_history()`，硬删除 30 天前的 `chat_history` 与关联的 `nutritionist_review_notes`。而 `init_db()` 由 `app.py:69` 在**模块导入时**调用 —— 意味着每次部署、每次重启、每次崩溃自愈重启都会触发一次不可逆删除。无备份、无开关、无日志，README 与 HANDOFF.md 也只在版本说明里一笔带过。

  注意：`cleanup_old_history()` 位于 `_init_db_locked()` 内部（`models.py:221-224`），因此**受 `fcntl.flock` 保护**，多 worker 并发启动不会打架——这点实现是对的，问题是策略本身。
- **修改方向**：
  1. 关闭启动自动清理，改由独立脚本（放 `scripts/`）+ cron / 定时自动化执行；
  2. 若必须保留启动清理，至少加 `CLEANUP_ON_STARTUP`（默认 `false`）与 `CHAT_RETENTION_DAYS` 两个环境变量，并在执行前后记录被删行数；
  3. 删除前把待删 `id` 范围写进日志，保证可追溯。

#### P0-4 富文本清洗器被自闭合危险标签静默截断（**已实测复现**）

- **位置**：`services/content_security.py:70-71`（`handle_startendtag`）、`:56-60`（`handle_starttag`）
- **原因**：`handle_startendtag` 直接委托给 `handle_starttag`；后者对 `DROP_CONTENT_TAGS`（`script`/`style`/`svg`/`iframe`/`math`/`object`/`canvas`/`template`）只做 `self.drop_depth += 1` 并 `return`。自闭合标签**永远不会触发 `handle_endtag`**，于是 `drop_depth` 永久停留在 1，`handle_data` 因 `if not self.drop_depth` 判定而丢弃其后**全部**内容。
- **实测**：

  | 输入 | 输出 |
  |---|---|
  | `<p>AAA</p><p>BBB</p>` | `<p>AAA</p><p>BBB</p>` |
  | `<p>AAA</p><svg/><p>BBB</p>` | `<p>AAA</p>` ← **BBB 消失** |
  | `<p>AAA</p><svg>x</svg><p>BBB</p>` | `<p>AAA</p><p>BBB</p>` |

  实际影响：管理员从外部编辑器粘贴含 `<svg/>`（图标内联 SVG 很常见）的资讯或案例正文时，**后半篇文章会被静默丢弃，且无任何报错**。
- **修改方向**：
  ```python
  def handle_startendtag(self, tag, attrs):
      tag = tag.lower()
      if tag in DROP_CONTENT_TAGS:
          return                      # 自闭合危险标签：直接丢弃，不改变 drop_depth
      self.handle_starttag(tag, attrs)
      if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
          self.output.append(f'</{tag}>')
  ```
  补单测覆盖 `<svg/>`、`<iframe/>`、`<math/>`、`<img/>`、`<br/>`。

#### P0-5 社区浏览量自增被事务回滚，功能完全失效（**已实测复现**）

- **位置**：`models.py:1419`（UPDATE）、`:1445`（`conn.close()`）
- **原因**：`get_question_detail()` 在第 1419 行执行 `UPDATE questions SET view_count = view_count + 1 WHERE id = ?`，但**整条函数路径上没有任何 `conn.commit()`** —— 第 1445 行直接 `conn.close()`，Python sqlite3 在关闭未提交连接时回滚事务。
- **实测**：创建问题后连续调用 `get_question_detail()` 3 次，`view_count` 仍为 `0`（期望 `3`）。
- **修改方向**（二选一）：
  1. 在第 1419 行 UPDATE 之后立即 `conn.commit()`；
  2. 更干净：抽出 `increment_question_views(question_id)` 单独提交，`get_question_detail` 只负责读。

#### P0-6 WAL + 多 worker + 网络卷的存储组合风险

- **位置**：`models.py:15`（`PRAGMA journal_mode=WAL`）、`railway.json`（`--workers 2`、`DATABASE_DIR=/data` + `volumeMounts`）
- **原因**：SQLite 官方文档明确说明，WAL 依赖共享内存（`-shm` 文件）与可靠的 `fcntl` 字节范围锁，**在网络文件系统（NFS/EFS/SMB）上不成立**。Railway Volume 的底层实现决定了这条约束是否命中——**这一点我无法从代码中判断，需要确认（见第五部分）**。若 `/data` 是网络存储：
  - 多进程并发写可能损坏数据库，或频繁抛 `database is locked`；
  - `models.py:22-27` 的 `fcntl.flock` 只能保护**同一台机器**上的进程，跨副本无效；
  - `railway.json` 的 `numReplicas: 1` 目前规避了跨副本问题，但一旦扩容就会暴露。
- **修改方向**：
  1. **先确认** `/data` 是本地块存储还是网络卷；
  2. 若为网络卷：改回 `journal_mode=DELETE`（或 `TRUNCATE`）+ `--workers 1`，或直接迁移到 Postgres；
  3. 无论哪种，都应在 `HANDOFF.md` 部署章节写明"不可横向扩容到多副本"的硬约束。

---

### 中等（P1）

#### P1-7 参数类型校验缺失导致 500

- **位置**：
  - `services/handoff_service.py:1018` `max(0, int(message_id or 0))`，配合 `routes/admin_handoff.py:144` 原样透传 `data.get('message_id', 0)` → 客户端传 `"abc"` 即 `ValueError` → 500
  - `routes/products.py:88` `[ (i['id'], i['sort_order']) for i in items ]` → `items` 元素缺 `id` 即 `KeyError` → 500
  - `routes/admin.py:76`、`:93`、`:171`、`:315`、`routes/dashboard.py:216`、`routes/community.py:67`、`:79` 使用 `request.get_json()`（无 `silent=True`）→ 非法/空 body 返回 HTML 400，与全站 JSON 错误格式不一致
  - `routes/dashboard.py:52` `min(..., 90)` 缺 `max(1, ...)`，负数会拼出 `datetime('now','--5 days')` → 返回 NULL
- **修改方向**：全站统一 `request.get_json(silent=True) or {}`；数值参数用 `request.args.get(..., type=int)` 或 `try/except (TypeError, ValueError)` 转 400。

#### P1-8 排队任务超时重排队后可能被执行两次

- **位置**：`services/chat_queue_service.py:96-103`（重置为 queued）、`:203-230`（`complete_job`/`fail_job`）
- **原因**：`_cleanup_locked` 把 `running` 且 `started_at` 超过 180 秒的任务重置为 `queued`，但**不重置 `expires_at`**，也没有作废原执行者的凭证。若原线程仍在运行（Coze 恰好慢于 180 秒），它结束时 `complete_job` 的 `WHERE ... AND status = 'running'` 匹配不到任何行，写入静默丢失；而该任务已被重新认领执行 —— 同一问题被 Coze 计费两次，并产生两条 `chat_history`。
- **修改方向**：增加 `attempt INTEGER` 与 `worker_token TEXT` 字段；重置为 `queued` 时同步延长 `expires_at` 并轮换 `worker_token`；`complete_job`/`fail_job` 增加 `AND worker_token = ?` 条件。

#### P1-9 AI 留言服务：事务未用 try/finally，异常时连接泄漏

- **位置**：`services/ai_review_service.py:202`（`upsert_review_note`）、`:243`（`withdraw_review_note`）
- **原因**：手动 `conn.execute('BEGIN IMMEDIATE')` 后，仅为 `AiReviewError` 这一条已知分支写了 `conn.rollback(); conn.close()`。任何其他异常（如 `sqlite3.OperationalError`、`IntegrityError`）都会**跳过关闭逻辑，连接永不释放**。乐观锁逻辑本身（`:207-213`、`248-250`）写得很到位，但资源管理方式是脆弱的。
- **修改方向**：统一封装事务上下文管理器：
  ```python
  @contextlib.contextmanager
  def transaction():
      conn = get_db_connection()
      try:
          conn.execute('BEGIN IMMEDIATE')
          yield conn
          conn.commit()
      except Exception:
          conn.rollback()
          raise
      finally:
          conn.close()
  ```
  全站替换手写 `BEGIN IMMEDIATE`。

#### P1-10 SSRF 防护存在 TOCTOU（DNS rebinding），且响应体无大小上限

- **位置**：`services/case_recognition_service.py:151-170`（校验）、`:135`（请求）、`:147`（读 body）
- **原因**：
  1. `_assert_safe_url` 先 `socket.getaddrinfo` 校验 IP，随后 `requests.get(current_url, ...)` **独立重新解析** DNS。攻击者用短 TTL DNS（或 rebinding 服务）在两次解析之间把域名指向 `127.0.0.1` / 内网地址即可绕过。跳转循环（`:133-141`）虽逐跳校验，但同样存在这个窗口。
  2. 第 147 行 `response.text[:800000]` —— `response.text` 会**先把完整响应体读进内存**再截断。一个几百 MB 的"网页"即可打爆 worker 内存。
- **缓解因素**：该接口为 `@admin_required`（`routes/cases.py:59`），需管理员权限，实际利用门槛较高。
- **修改方向**：
  1. 自行解析出 IP 后，通过自定义 `HTTPAdapter` 把连接 pin 到该 IP（保留 `Host` 头），消除二次解析；
  2. 改用 `iter_content(chunk_size=65536)` 累计到 800KB 即停止读取；
  3. 或引入 `requests` 的 `max_size` 中间件 / 直接换 `httpx` 并设 `limits`。

#### P1-11 Coze API Key 掩码泄露 12 位，与另一处实现不一致

- **位置**：`routes/admin.py:164` vs `:250-256`
- **原因**：`coze-api-key` 接口用 `current_key[:8] + '****' + current_key[-4:]`，泄露前 8 + 后 4 共 12 位；而同文件 `_mask_secret()`（用于腾讯云密钥）只泄露 4 + 4。Coze Key 通常带固定前缀（如 `czs_`），前 8 位几乎不含熵，但后 4 位 + 已知前缀仍缩小了暴力/撞库空间。两处实现不一致，属疏漏而非有意设计。
- **修改方向**：`coze_api_key` 改用 `_mask_secret()`；`_mask_secret` 按长度自适应：
  ```python
  def _mask_secret(value):
      value = (value or '').strip()
      if not value:
          return ''
      if len(value) <= 12:
          return '****'
      return value[:4] + '****' + value[-4:]
  ```

#### P1-12 SECRET_KEY 轮换即导致全站 AI 不可用，且无降级路径

- **位置**：`services/secret_service.py:16-18`（派生）、`:34-38`（解密失败抛错）、`:41-43`（回落条件）
- **原因**：Fernet 密钥由 `sha256(SECRET_KEY)` 派生。`SECRET_KEY` 一旦变更，库中所有 `enc:v1:` 密文无法解密，`decrypt_secret` 抛 `RuntimeError`。而 `get_secret_setting(key, default)` 仅当 `raw` 为**空字符串**时才回落到 `default`（环境变量值）—— 解密失败不会回落，直接 500。

  影响面：Coze Key 解密失败 → `chat_service.py:87-89` 抛 `AI 服务尚未配置` → 全站 AI 502；腾讯云密钥同理导致语音全挂。
- **修改方向**：
  1. `get_secret_setting` 捕获解密失败，记 `logger.error` 后回落到 `default`（环境变量），保证服务可用；
  2. 提供 `scripts/rekey_secrets.py`：接受 `OLD_SECRET_KEY` + `NEW_SECRET_KEY`，重新加密所有 `SECRET_SETTING_KEYS`；
  3. `HANDOFF.md` 明确写出"`SECRET_KEY` 不可直接轮换，必须先跑 rekey 脚本"。

#### P1-13 限流桶只增不减，存在无界内存增长

- **位置**：`services/security_service.py:9`（`defaultdict(deque)`）、`:54-57`（清理时机）
- **原因**：`_request_buckets` 仅在**同一个 key 再次被访问时**才清理过期项。匿名接口（`/api/auth/login:178`、`/api/auth/session:206`）按 `request.remote_addr` 建 key；移动端 IP 频繁变化会留下大量只访问一次的条目，永不回收。长期运行下是无界内存增长。
- **修改方向**：改用有上限的 LRU（`OrderedDict` + `move_to_end`，上限 10,000），并在写入时顺带做一次批量清扫；生产建议直接换 Redis（`INCR` + `EXPIRE`）。

#### P1-14 流式并发限制是进程级的，全局上限与配置不成正比

- **位置**：`services/security_service.py:13-40`、`config.py:22-25`、`routes/chat.py:23`
- **原因**：`_stream_limiter` 是模块级单例，故实际全局并发 = `CHAT_STREAM_MAX_CONCURRENT_PER_WORKER × workers`。当前部署 2 worker → 实际 6，而非配置中的 3。`.env.example` 只注释了"应小于 `--threads`"，未提示 worker 数的乘积关系，运维极易误判对 Coze 的实际压力。
- **修改方向**：`.env.example` 注释改为"全局并发上限 = 本值 × gunicorn workers，请据此评估 Coze 配额"；若需硬上限，改用 DB/Redis 原子计数（可参考 `chat_jobs` 表的 `uq_chat_jobs_user_active` 思路）。

#### P1-15 `rate_limit` 依赖装饰器书写顺序，无任何保护

- **位置**：`services/security_service.py:48`（读 `g.request_identity`）
- **原因**：该装饰器通过 `g.request_identity` 取用户标识，只有当 `@admin_required` / `@identity_required` 写在 `rate_limit` **之上**时才生效。当前所有调用点顺序都是正确的（`routes/chat.py:26-28`、`routes/admin_handoff.py:80-82` 等），但这是一个**隐式契约**，既无注释也无断言。后续维护者一旦调换顺序，用户级限流会静默退化为按 IP 限流 —— 登录用户即可绕过针对单账号的频率限制。
- **修改方向**：在 `rate_limit` 内加保护：
  ```python
  identity = getattr(g, 'request_identity', None)
  if identity is None and scope.startswith(('chat', 'handoff', 'lead')):
      logger.warning('rate_limit scope=%s without identity; falling back to IP', scope)
  ```
  或更彻底：改成 `rate_limit(scope, limit, window_seconds, subject_key=lambda: ...)` 显式传参。

#### P1-16 首页每次请求重新读文件并做 11 次字符串替换

- **位置**：`app.py:120-148`
- **原因**：`index()` 每次请求都 `open().read()` 整个 `static/index.html`，然后执行 11 次 `str.replace`；其中 `get_setting()` 又各自开一次 DB 连接（`share_title` / `share_description` / `share_image_url` 共 3 次）。首页是最高频路径，响应头还设了 `no-cache`（`app.py:96-97`），无法利用浏览器缓存。
- **修改方向**：用 `functools.lru_cache` + 配置版本号（写 share 设置时递增）缓存渲染结果，或改用 Jinja 模板 + 缓存。

#### P1-17 图片上传缺少解压炸弹防护

- **位置**：`services/image_service.py:110-126`（`_open_image`）、`:29-31`（`is_allowed_image_filename`）
- **原因**：
  1. `image.load()` 会对 8MB 以内的 PNG 完整解压。Pillow 默认 `MAX_IMAGE_PIXELS ≈ 89,478,485`，且**仅在超过 2 倍时才抛 `DecompressionBombError`**，1–2 倍区间只发 warning。一个高度压缩的 8MB PNG 可解压到上亿像素 → 单次上传吃掉数 GB 内存 → worker OOM。
  2. `is_allowed_image_filename` 对**无扩展名**的文件名（`filename.rsplit('.',1)[1] if '.' in filename else 'jpg'`）默认返回 `jpg` → 放行。实际风险低（后续用 PIL 重编码为 JPEG 存储，无 RCE），但属于不严谨。
- **修改方向**：在 `_open_image` 中加显式像素上限（如 5,000 万）并 `raise ValueError('图片尺寸过大')`；扩展名缺失时直接拒绝。

#### P1-18 `speech_service` 使用 `__import__` 且 `utcfromtimestamp` 已废弃

- **位置**：`services/speech_service.py:81-82`
- **原因**：`int(__import__('time').time())` 与 `__import__('datetime').datetime.utcfromtimestamp(...)`。`datetime.utcfromtimestamp` 自 Python 3.12 起标记 `DeprecationWarning`，`runtime.txt` 指定 `python-3.11` 当前无碍，但升级后会告警直至移除。
- **修改方向**：顶部 `import time` / `from datetime import datetime, timezone`；改用 `datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%d')`。

---

### 轻微（P2）

#### P2-19 8 处裸 `except:`，会吞掉真实错误

- **位置**：`app.py:171`、`:173`、`:198`；`models.py:529`、`:1347`；`routes/admin.py:323`、`:325`、`:352`
- **说明**：这 8 处全部是包裹 `json.loads` 的，本意是"解析失败用默认值"，但裸 `except:` 会一并吞掉 `KeyboardInterrupt`、`SystemExit`、`MemoryError` 和编码类异常。
- **修改方向**：统一改为 `except (TypeError, ValueError):`。

#### P2-20 超长函数（AST 统计）

| 行数 | 位置 | 函数 |
|---:|---|---|
| 195 | `models.py:30` | `_init_db_locked()` |
| 106 | `services/chat_service.py:180` | `iter_coze_stream()` |
| 103 | `services/handoff_service.py:137` | `_reconcile_locked()` |
| 83 | `services/handoff_service.py:303` | `start_handoff()` |
| 83 | `routes/chat.py:40` | `stream_to_coze()` |
| 73 | `services/ai_review_service.py:116` | `list_ai_reviews()` |
| 72 | `services/handoff_service.py:891` | `export_archived_sessions()` |

- **修改方向**：`_init_db_locked` 拆为 `_create_tables` / `_apply_indexes` / `_seed_defaults`；`_reconcile_locked` 拆为 `_expire_live_sessions` / `_release_stale_claims` / `_refresh_agent_load` / `_assign_queued`（拆分后也更便于单测）。

#### P2-21 8 处函数内延迟 import，其中部分完全多余

- **位置**：`app.py:166-167`（`waiting_content` 内 `from models import get_setting; import json` —— 两者在模块顶部**已导入**）、`app.py:180`、`:191`、`:208`、`routes/speech.py:18` 等
- **修改方向**：清理多余项；确为打破循环依赖的（如 `chat_service.py:77` 导入 `handoff_service`）加注释说明原因。

#### P2-22 社区回复路由存在误导性死代码

- **位置**：`routes/community.py:34-37`
- **原因**：`status = 0 if not check_content(content) else 1` 计算出的 `status` 只用于第 35 行的判断，第 37 行仍**硬编码传 `0`**。实际语义是"一律待审核"，但代码看起来像"审核通过就公开"。
- **修改方向**：
  ```python
  if not check_content(content):
      return jsonify({'error': '内容包含限制词汇', 'blocked': True}), 400
  id = create_reply(qid, '匿名用户', content, 0, viewer_id)
  ```

#### P2-23 dashboard 中 5 处未使用的变量

- **位置**：`routes/dashboard.py:124`（`feedback_stats`）、`:134`（`feedback_overview`）、`:153`（`feedback_by_agent`）、`:188`（`negative_feedback`）、`:225`（`team_question_stats`）
- **原因**：这些函数先算 `dclause, dparams = date_filter()`，但内部模型函数（`get_feedback_stats` 等）自己按 `start_date`/`end_date` 重新过滤，导致 `dclause/dparams` 从未被使用。
- **修改方向**：删除未使用变量，或让模型函数直接接受 `clause/params`。

#### P2-24 仓库内含 75MB 产物与疑似废弃文件

- **位置**：`outputs/`（63 个文件被 Git 跟踪，75MB）、`static/styles.old.css`（963 行）、`static/index.old.html`（197 行）
- **修改方向**：确认后清理，或移入 Git LFS / 归档目录。

#### P2-25 测试为 8 个自研脚本，无 pytest、无 CI

- **位置**：`scripts/test_*.py`（security / migrations / handoff / chat_queue / chat_capacity / case_documents / today_features），`.github/` **不存在**，`requirements.txt` 无测试依赖
- **说明**：脚本质量不差（`test_security.py` 覆盖了公开注册关闭、未授权访问、guest token 等），但需手动执行，无回归门禁。本次发现的 P0-4、P0-5 正是这类脚本可以覆盖的场景。
- **修改方向**：引入 `pytest`，把现有脚本改造为标准测试函数；配 GitHub Actions 至少跑 `test_security.py` / `test_migrations.py` / `test_handoff.py`。

#### P2-26 前端 XSS 面总体可控，但缺少统一约束

- **位置**：`static/js/` 下 12 个文件使用 `innerHTML`
- **说明**：绝大多数已配合 `escapeHtml()`（`news-discover.js`、`history-community.js`、`admin-share.js` 覆盖得相当好）。风险点是 `static/js/admin.js`（1913 行）与 `static/js/chat.js`（718 行）体积大、模板拼接多，人工审查难以全覆盖。服务端 `sanitize_rich_html` 已做第一道防线。
- **修改方向**：对注入富文本的 `innerHTML` 统一包一层 `sanitizeHtml()`；新增代码禁用裸 `innerHTML`，可用 ESLint `no-unsanitized` 规则约束。

#### P2-27 坐席与管理员权限未分离

- **位置**：`routes/auth.py:129-146`（`admin_required` 只判 `is_admin`）、`db_migrations.py:190-199`（`cs_agents` 表无角色字段）
- **原因**：任何管理员都能自开坐席（`routes/admin_handoff.py:150`）并查看/导出全部咨询档案。当前管理员数量少，暂不构成问题；但若后续有多管理员（如运营 + 营养师），则无最小权限可言。
- **修改方向**：`cs_agents` 增加 `role` 字段，或用独立的 `admin_permissions` 表；导出接口增加二次确认/审计（审计表 `handoff_export_logs` 已存在，可直接复用）。

---

## 四、改进建议

### 按优先级排序的执行计划

**第一批（1–2 天，纯 bug 修复，风险极低）**

| 项 | 内容 | 预估 |
|---|---|---|
| P0-4 | 修 `content_security.py:70-71` 自闭合标签截断 | 15 分钟 |
| P0-5 | 修 `models.py:1419` 缺失的 commit | 5 分钟 |
| P1-11 | Coze Key 掩码改用 `_mask_secret()` | 10 分钟 |
| P2-19 | 8 处裸 `except:` 改为具体异常 | 20 分钟 |
| P1-7 | 补齐 `silent=True` 与数值参数校验 | 2 小时 |

**第二批（2–4 周，架构性调整，需回归测试）**

| 项 | 内容 | 预估 |
|---|---|---|
| P0-3 | 关闭启动自动清理，改独立任务 | 0.5 天 |
| P0-2 | `get_handoff_settings` 批量取 + 连接复用 + 短缓存 | 1 天 |
| P0-1 | 对账逻辑移出读路径，改后台定时线程 + DB 租约 | 3 天 |
| P1-9 | 统一事务上下文管理器，全站替换手写 BEGIN | 1 天 |
| P1-8 | `chat_jobs` 增加 `attempt`/`worker_token` | 1 天 |
| P1-12 | 解密失败回落 + rekey 脚本 | 1 天 |
| P2-25 | 引入 pytest + GitHub Actions | 1 天 |

**第三批（持续，安全与运维加固）**

- P0-6 存储方案决策（**依赖第五部分的确认结果**）
- P1-10 SSRF TOCTOU + 响应体大小上限
- P1-13 限流桶改 LRU / Redis
- P1-14 / P1-15 并发与限流的部署文档补全
- P2-20 超长函数拆分
- P2-24 仓库产物清理

### 工程实践建议

1. **给性能敏感路径加埋点**：`chat_service.py` 已经用结构化日志记录了 `first_token_ms` / `coze_connect_ms` / `total_ms`，这个习惯很好，但 `handoff_service` 完全没有。建议对 `assign_available()`、各轮询接口加上耗时日志，P0-1 / P0-2 的问题在生产上会立刻暴露。
2. **为 SQLite 写路径建立约束检查**：在 CI 中加一条静态检查 —— 凡是在 `GET`/只读接口中调用 `BEGIN IMMEDIATE` 的，直接失败。可以从根上防止 P0-1 复现。
3. **配置文档化**：`config.py` 现有 20+ 个环境变量，`README.md` 未集中说明。建议补一张「配置项 → 默认值 → 影响面」表格，P1-14 这类"配置语义与部署耦合"的问题会更容易被发现。

---

## 五、需要补充的上下文（以下无法从代码判断，未做臆测）

| # | 待确认问题 | 影响 |
|---|---|---|
| 1 | Railway 的 `/data` 卷是**本地块存储**还是**网络文件系统**（NFS/EFS）？ | 直接决定 P0-6 是"严重隐患"还是"可接受"。若为网络卷，WAL + 多 worker 有数据损坏风险，需立即调整。 |
| 2 | 预期并发规模：同时排队用户峰值、坐席数量？ | 决定 P0-1 / P0-2 何时实际触雷。若峰值 < 5 人排队，可降级为 P1 观察；若 > 20 人，应立刻处理。 |
| 3 | 是否有横向扩容到多个副本的计划？（`railway.json` 当前 `numReplicas: 1`，但 `volumeMounts` 在多副本下行为未定义） | 决定是否需要提前迁移到 Postgres。 |
| 4 | `outputs/` 下 63 个文件（75MB）是有意归档的中间产物，还是误提交？ | 决定是否执行 P2-24 清理。 |
| 5 | 是否存在响应时长超过 gunicorn `--timeout 120` 的 Coze 工作流机器人？（当前代码里最长 `timeout=(5, 90)`） | 若有，流式请求会被 gunicorn 强杀，表现为前端随机断流。 |
| 6 | 管理员账号的实际数量与分工？ | 决定 P2-27 权限分离的优先级。 |
| 7 | `railway.json` 已安装 `ffmpeg`，但代码在 `speech_service.py:167` 才 `shutil.which('ffmpeg')`。生产镜像是否确实包含？ | 若缺失，批量语音转写会直接返回"服务器未安装音频转换工具"。 |

---

*报告基于 2026-08-31 的代码快照。所有标「实测」的结论均在本机临时数据库上复现通过，复现方式见各条目。*
