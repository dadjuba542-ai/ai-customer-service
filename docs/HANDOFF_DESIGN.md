# AI 智能回复 → 人工客服 无缝转接模块设计

> 适用项目：`AI宝儿智能体`（单体 Flask + SQLite + Coze）
> 文档目标：定义一套**独立、可插拔**的功能模块，实现「前台用户 → AI 自动回复 → 明确表达转人工 → AI 优先选择 → 后台客服接管」的完整闭环。
> 设计原则：复用现有 `chat_service` / `auth` / `settings` / `db_migrations` 能力，不改动既有聊天主链路；所有转接状态落地到数据库，保证 `gunicorn -w 4` 多进程安全。

---

## 1. 模块边界与文件结构（独立模块）

模块以独立蓝图 `handoff_bp` 承载，与现有 `chat_bp`、`leads_bp` 平级，互不侵入。

```
routes/handoff.py          前台转接接口（入口、状态轮询、发消息、关闭）
routes/admin_handoff.py    独立客服工作台接口（队列、接入、回复、通知）← 复用后台鉴权
services/handoff_service.py 转接核心逻辑：建会话、排队、分配、上下文快照、状态机
models.py                  新增数据访问函数（或直接复用 get_chat_history）
db_migrations.py          新增 3 张表的 migration（保持现有机制）
config.py                 新增 HANDOFF_* 环境变量与校验
static/handoff-intent.js  前台明确转人工意图的确定性识别规则
static/app.js             AI 优先选择面板 + 人工会话视图（建议拆出 handoff 段）
templates/consultant.html  PC 端独立「营养师工作台」页面，不嵌入现有 admin.html
static/consultant/app.js   客服多会话、轮询、未读数和桌面通知
static/consultant/styles.css 客服工作台独立样式
docs/HANDOFF_DESIGN.md    本文件
```

**注册方式（app.py）：**

```python
from routes.handoff import handoff_bp
from routes.admin_handoff import admin_handoff_bp
app.register_blueprint(handoff_bp, url_prefix='/api/handoff')
app.register_blueprint(admin_handoff_bp, url_prefix='/api/admin/handoff')
```

PC 客服工作台页面单独暴露为 `/consultant`：

```python
@app.route('/consultant')
def consultant_page():
    return render_template('consultant.html')
```

页面本身可以公开返回登录壳，但所有会话数据接口都必须通过 `admin_required`，并进一步校验当前用户存在于 `cs_agents`；不能因为知道 `/consultant` 地址就读取咨询数据。

> 与现有 `leads_bp`（「获取方案」异步留资）的关系：两者并存。转人工是由明确语言意图触发的**实时在线会话**，leads 是用户主动点击「获取方案」发起的**异步留资**。

---

## 2. 数据库设计（通过 migration 新增）

沿用 `db_migrations.py` 的有序 migration 列表（不裸 `ALTER TABLE`），新增三张表；状态/角色全部用整型或短字符串，便于索引与统计。

### 2.1 `handoff_sessions`（转接会话主表）

```sql
CREATE TABLE IF NOT EXISTS handoff_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,        -- 对外暴露的随机串，避免暴露自增 id
    user_id TEXT NOT NULL,                  -- 复用 auth 的 user_id（guest 亦可）
    team_name TEXT DEFAULT '',
    member_name TEXT DEFAULT '',
    query_type TEXT DEFAULT '',             -- 触发时的咨询类型
    ai_agent_id TEXT DEFAULT '',           -- 转接前使用的 AI 智能体
    agent_id TEXT DEFAULT '',              -- 被分配的人工客服 user_id（空=排队中）
    status TEXT NOT NULL DEFAULT 'queued', -- queued|assigned|active|closed|abandoned
    service_mode TEXT NOT NULL DEFAULT 'live', -- live|message
    live_deadline_at TIMESTAMP,
    message_converted_at TIMESTAMP,
    ai_context_json TEXT DEFAULT '',       -- AI 阶段对话快照（见 §5）
    priority INTEGER DEFAULT 0,            -- 预留：VIP/指定产品可插队
    enqueued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_at TIMESTAMP,
    closed_at TIMESTAMP,
    close_reason TEXT DEFAULT ''           -- user_cancel|agent_close|timeout|done
);
CREATE INDEX IF NOT EXISTS idx_handoff_status ON handoff_sessions(status, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_handoff_user ON handoff_sessions(user_id, status);
```

### 2.2 `handoff_messages`（会话消息表）

```sql
CREATE TABLE IF NOT EXISTS handoff_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    sender_role TEXT NOT NULL,   -- user|ai|agent|system
    sender_id TEXT DEFAULT '',   -- user_id 或 agent user_id
    content TEXT NOT NULL,
    is_ai_context INTEGER DEFAULT 0,  -- 1=AI 历史快照消息（仅客服台可见，前端不重复渲染）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES handoff_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_handoff_msg_session ON handoff_messages(session_id, created_at);
```

### 2.3 `cs_agents`（人工客服坐席表，关联 users）

```sql
CREATE TABLE IF NOT EXISTS cs_agents (
    user_id TEXT PRIMARY KEY,           -- 关联 users(user_id)，客服即后台员工
    display_name TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    online INTEGER DEFAULT 0,           -- 0 离线 / 1 在线
    max_concurrent INTEGER DEFAULT 3,   -- 同时接待上限
    current_load INTEGER DEFAULT 0,     -- 当前进行中会话数（冗余计数，便于排队计算）
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

> 客服身份：复用 `users` 表 + `is_admin`（客服需后台登录）。`cs_agents` 仅描述「坐席在线状态与接待能力」。未出现在 `cs_agents` 或 `online=0` 的管理员不参与分配。

---

## 3. 会话状态机（AI ↔ 人工 切换逻辑）

核心：后端 `handoff_sessions.status` 是唯一可信状态源；`service_mode=live|message` 是与状态正交的服务模式。前台 `mode` 映射为 `ai|queued|assigned|human|message|closed`，用于控制界面和消息路由，但不能单独决定后端行为。

- `live`：同步等待真人，消息只走人工通道。
- `message`：异步留言，不阻塞 AI；营养师首次回复后自动关闭并归档留言会话。
- 在线等待默认 120 秒，可由 `handoff_live_wait_sec` 配置；尚无真人回复且到达 `live_deadline_at` 后自动转为 `message`。

```
        [前台 mode=ai] 深度调理用户明确表达「转人工」并确认
                  │  POST /api/handoff/start（携带 AI 历史）
                  ▼
   ┌───────────────────────────────┐
   │ handoff_sessions.status        │
   │                               │
   │  queued ──有空闲坐席/预分配──▶ assigned ──客服确认接入──▶ active
   │    │                            │                            │
   │    │ 用户取消                  │ 用户取消                   │ 任一方关闭
   │    ▼                            ▼                            ▼
   │  closed(cancel)          closed(cancel)              closed(done/agent_close)
   └───────────────────────────────┘
   排队中若全部坐席离线/满载 → 停留 queued，前端显示排队位次
```

| 状态 | 含义 | 前端表现 | 后端动作 |
|------|------|----------|----------|
| `queued` | 等待分配 | 显示「正在排队，第 N 位，预计 X 分钟」+ 取消按钮 | 计算位次；空闲坐席出现时自动分配 |
| `assigned` | 已预分配坐席、等待客服确认 | 「营养师已收到，正在接入…」 | 写入 `agent_id`、自增坐席 `current_load`；超时未确认则重新排队 |
| `active` | 客服已确认接入，人工对话进行中 | 聊天框标题变「在线营养师·XX」，消息走人工通道 | 客服 `claim` 后进入；消息存 `handoff_messages(role=agent/user)` |
| `closed` | 结束 | 显示结束语 + 「本次对话已结束」 | 自减坐席 `current_load`，触发后续自动分配 |

**切换不变量：**
- 用户确认转人工后，从 `queued` 开始，输入只发往 `/api/handoff/message`，**不再调用 Coze**；排队期间补充的问题也进入人工消息流。
- `assigned` 只是系统预留坐席，只有客服执行 `claim` 后才进入 `active`，不能在客服尚未确认时向用户显示“已接入”。
- AI 的回复以「上下文快照」只读展示给客服，不混入人工消息流。
- 用户可随时「结束对话」→ `closed(user_cancel)`；客服可「结束并归档」。
- 客服掉线/离线：其 `active` 会话保持，但 `current_load` 不释放直到显式关闭；新会话不再分配给离线坐席（自然排队）。

---

## 4. 排队与忙碌机制

**触发分配时机：**
1. `POST /api/handoff/start` 建会话时；
2. 某坐席关闭一个会话（`current_load` 下降）后；
3. 坐席点击「上线」(`online=1`) 时。

**分配算法（`services/handoff_service.assign_next`）：**
```
候选 = cs_agents WHERE online=1 AND current_load < max_concurrent
若候选非空：
    选 current_load 最小者（同负载取最早上线）→ 取队首 queued 会话绑定
    会话 status=assigned, agent_id=该坐席, assigned_at=now
    坐席 current_load += 1
否则会话保持 queued
```

**排队位次与预计等待（`GET /api/handoff/session/<id>` 返回）：**
```python
position = 1 + count(status='queued' AND enqueued_at < self.enqueued_at)
est_wait_sec = position * AVG_HANDLE_SECONDS   # 配置项，默认 180s
```
前端每 4~5s 轮询一次刷新位次；分配到人即切 `assigned`/`active`。

**忙碌兜底文案（配置化）：**
- 全部离线：`「当前营养师暂未在线，已为您留言，上线后会第一时间回复」`→ 可降级为留资（复用 leads）或保持排队。
- 满载排队：`「客服忙线中，您前面还有 N 位，预计等待 X 分钟，可先留下问题」`。

---

## 5. AI → 人工 上下文传递

转接发起时，前端把**当前 AI 会话的 history_id 列表**一并传给 `start`，后端：

1. 读取 `get_chat_history(user_id)` 或按 history_id 取最近 N 轮（默认 10 轮）；
2. 序列化为 `ai_context_json`（结构：`[{role:'user'|'ai', text, at}]`）；
3. 存入 `handoff_sessions.ai_context_json`，并在 `handoff_messages` 写入一条 `sender_role='system', is_ai_context=1` 的摘要消息，**仅供客服台侧栏展示**；
4. 用户侧不渲染该快照，避免与人工消息混淆。

客服台会话详情页分两栏：
- 左：AI 对话上下文（只读，灰色）；
- 右：实时人工消息流（user/agent）。

> 这样既满足「用户与 AI 的对话记录需传递给人工客服作为上下文参考」，又不污染人工消息时间线。

---

## 6. 接口设计

### 6.1 前台（`handoff_bp`，需 `identity_required`，guest 可）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/handoff/start` | 发起转人工。body：`{query_type, history_ids:[], note}`；AI 智能体由服务端根据已完成历史和模块配置确定。返回 `{session_id, status, queue_position, est_wait_sec}` |
| GET | `/api/handoff/current` | 查询当前身份尚未结束的会话；页面刷新或重新进入咨询页时恢复状态 |
| GET | `/api/handoff/session/<session_id>` | 轮询状态/位次/客服信息（供排队与 mode 切换） |
| POST | `/api/handoff/message` | 人工阶段用户发消息。body：`{session_id, content}` → 存 `handoff_messages(role=user)` |
| GET | `/api/handoff/messages/<session_id>?after_id=<id>&limit=50` | 增量拉取人工消息，按消息 `id` 升序返回 |
| GET | `/api/handoff/recent?limit=20` | 查询当前身份的近期咨询；已结束会话以只读方式查看 |
| POST | `/api/handoff/close` | 用户结束。`{session_id, reason}` → `closed(user_cancel)` |
| POST | `/api/handoff/defer` | 主动暂时挂起并转为异步留言；后台继续处理，但不再阻塞 AI |
| GET | `/api/handoff/config` | 返回前台安全配置：按钮是否启用、文案、是否在线、专用 AI 的 `agent_id/name/avatar`；不返回 `bot_id` 或密钥 |

### 6.2 后台客服台（`admin_handoff_bp`，需 `admin_required`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/handoff/queue` | 列表：queued + assigned + active 会话，含用户信息、`ai_context` 摘要、等待时长。**前端每 4s 轮询即「实时通知」** |
| POST | `/api/admin/handoff/<session_id>/claim` | 客服确认接入；仅允许领取分配给自己的会话，或通过条件更新领取仍在排队的会话 |
| GET | `/api/admin/handoff/<session_id>/detail` | 完整上下文：AI 快照 + 全部消息 |
| POST | `/api/admin/handoff/<session_id>/reply` | 客服回复 → 存 `handoff_messages(role=agent)` |
| POST | `/api/admin/handoff/<session_id>/close` | 客服结束 → `closed(agent_close)`，释放坐席负载 |
| POST | `/api/admin/handoff/<session_id>/read` | 更新当前客服最后已读消息 ID，用于多会话未读数 |
| POST | `/api/admin/handoff/agent/status` | 坐席上线/下线：`{online:0|1}`；影响分配 |
| GET | `/api/admin/handoff/agent/me` | 当前坐席负载与进行中会话 |
| GET | `/api/admin/handoff/notifications` | 返回新排队、分配给我和新用户消息的通知摘要；客户端依据游标去重 |

### 6.3 配置（`admin_bp` 下挂，复用 `settings` 表）

| key | 说明 |
|-----|------|
| `handoff_enabled` | 总开关（默认 false，灰度用） |
| `handoff_ai_agent_id` | 营养咨询 AI 阶段独立使用的智能体，对应 `agent_configs.agent_id`；由服务端强制覆盖前端传值 |
| `handoff_button_label` | 按钮文案，默认「联系在线营养师」 |
| `handoff_queue_msg` / `handoff_offline_msg` / `handoff_welcome_msg` | 排队/离线/接入欢迎文案 |
| `handoff_avg_handle_sec` | 预计等待计算用，默认 180 |
| `handoff_live_wait_sec` | 同步在线等待上限，默认 120 秒；超时自动转异步留言 |
| `handoff_business_hours` | 服务时间（JSON），非服务时段引导留资 |

接口：`GET/PUT /api/admin/settings/handoff`。

配置页面提供「营养咨询 AI 智能体」下拉框，选项读取现有 `/api/admin/agents`。保存时服务端必须确认 `agent_id` 存在且有可用 `bot_id`；删除或停用一个智能体前，如果它正在被 `handoff_ai_agent_id` 引用，应拒绝删除或要求管理员先切换配置。

---

## 7. 后台「实时通知」方案

现有后台（dashboard）采用**轮询**，且 `gunicorn -w 4` 多进程下不宜依赖进程内内存态。本模块据此采用：

- **主方案：轮询 + 数据库状态源。** 客服台每 4s 调 `GET /api/admin/handoff/queue`，队列/新会话即时可见。状态全在 SQLite，4 个 worker 共享一致视图，无一致性隐患。
- **增强方案（可选）：SSE 推送。** 新增 `GET /api/admin/handoff/stream`（仅事件通知：新排队、被分配），前端收到通知后再拉 `queue` 详情。SSE 长连由单 worker 承载，但**状态仍读 DB**，不依赖内存，安全。

> 不引入 Redis/消息队列，保持「单体 SQLite」现状；若未来多副本部署再考虑外部状态源。

---

## 8. 前台交互与 UI

在 `static/app.js` 现有聊天视图上扩展，核心是 `mode` 状态与 AI 优先的渐进式转人工入口：

1. **入口触发**：首页和输入框周围不展示人工入口；仅在 `creative`（深度调理答疑）中识别到「转人工、找客服、联系营养师、真人咨询」等明确命令后露出选择面板。
2. **AI 优先选择**：选择面板以「继续用 AI」为主按钮，切换到 `handoff_ai_agent_id`；「仍要联系营养师/给营养师留言」为次按钮，点击后直接 `POST /api/handoff/start`，不再二次确认。
3. **排队态**：聊天区顶部横幅显示位次与在线等待上限，提供「立即转留言」和「取消排队」；此阶段仍可看到 AI 历史，用户补充问题写入人工消息流，不再触发 AI。
4. **预分配态**：显示「营养师已收到，正在接入」，等待客服确认；确认后才显示客服名称。
5. **接入态**：横幅变「已接入营养师·XX」，输入框标题切换为人工会话；用户消息走 `/api/handoff/message`，回复走 `/api/handoff/messages?after_id=...` 增量轮询渲染。
6. **留言态**：用户可点击「暂时挂起/立即转留言」，或等待超时自动进入；前台恢复 AI 和其他页面操作，后台继续显示「留言待处理」。营养师回复后自动归档，前台显示「营养师留言回复：XXXXXX」。
7. **结束态**：任一方关闭后，聊天区显示结束语并自动回到专用营养 AI；旧人工会话保持只读，不直接删除。
8. **状态切换不变量（前端）**：`service_mode=live` 时输入不再触发 Coze；进入 `message` 或结束后恢复 AI。已有留言处理中时不重复发起转接。

> 建议把上述逻辑从 `app.js` 拆为 `static/handoff.js`（与后台 `cases.js` 拆分先例一致），降低大文件维护成本。

---

## 9. 后端实现要点（复用现有能力）

- **AI 阶段**：直接复用 `services/chat_service.py` 的 `build_chat_context` + `execute_sync_chat` / `iter_coze_stream`，仅把 `agent_id` 设为配置项 `handoff_ai_agent_id`；AI 回复仍经 `save_chat_history` 落库，便于 §5 取上下文。
- **鉴权**：前台接口用 `identity_required`（guest 用户可转人工，与现有聊天一致）；后台接口用 `admin_required`。
- **限流**：对 `start` 与 `message` 套用 `services/security_service.rate_limit`（如 `handoff-start` 限 5/600s、`handoff-msg` 限 20/60s），防刷。
- **权限校验**：`handoff_messages` 写入时校验 `session_id` 属于当前 `user_id`；客服回复时校验其为该会话 `agent_id` 或管理员。
- **数据访问**：在 `models.py` 新增 `create_handoff_session / get_handoff_session / update_handoff_status / append_handoff_message / list_handoff_queue / claim_handoff_session / close_handoff_session / upsert_cs_agent` 等函数，集中管理（符合现有「全量 SQL 在 models.py」约定）。

---

## 10. 配置项（config.py）

```python
HANDOFF_ENABLED = os.environ.get('HANDOFF_ENABLED', 'false').lower() == 'true'
HANDOFF_AI_AGENT_ID = os.environ.get('HANDOFF_AI_AGENT_ID', '')
HANDOFF_AVG_HANDLE_SEC = int(os.environ.get('HANDOFF_AVG_HANDLE_SEC', '180'))
HANDOFF_QUEUE_POLL_SEC = int(os.environ.get('HANDOFF_QUEUE_POLL_SEC', '4'))
```
`Config.validate()` 中可不做强校验（默认关闭即可），但读取 `coze_api_key` 的逻辑保持——AI 阶段依赖它。

---

## 11. 安全与边界

- 不泄露 `agent_id` 映射之外的内部信息；`session_id` 用随机串（`uuid.uuid4().hex`）避免枚举。
- 用户只能读自己的会话；客服只能操作分配给自己的或管理员可见的会话。
- 转人工前若 `coze_api_key` 未配置，AI 阶段降级提示，但转人工链路独立可用。
- 排队/分配全程 DB 事务，避免并发重复分配（SQLite 串行写天然安全，分配函数内用单连接提交）。

---

## 12. 实施步骤（建议顺序）

1. `db_migrations.py` 加 3 张表 migration + `models.py` 数据访问函数。
2. `config.py` 加配置项；`settings` 加 handoff 配置读写。
3. `services/handoff_service.py`：建会话、上下文快照、排队分配状态机。
4. `routes/handoff.py`：前台 8 个接口。
5. `routes/admin_handoff.py`：客服台 9 个接口 + 配置接口。
6. `app.py` 注册两个蓝图。
7. 前台 `static/app.js`（或拆 `handoff.js`）：按钮 + 模式切换 + 轮询。
8. 新建 `templates/consultant.html`、`static/consultant/app.js` 和 `static/consultant/styles.css`：独立 PC 客服工作台、通知和多会话面板。
9. 测试脚本 `scripts/test_handoff.py`：覆盖建会话/排队/分配/上下文/回复/关闭/权限。
10. 在 `PROJECT_CONTEXT.md` §8 接口地图补录，并在 §13 风险点注明「人工会话态依赖 DB，多副本需外部状态源」。

---

## 13. 验收要点（建议）

- 用户明确表达转人工并选择真人 → AI 历史随转接请求送达客服台。
- 客服离线时用户进入排队，位次/预计等待正确刷新。
- 客服上线/结束会话触发自动分配，无重复分配。
- `mode` 切换后用户消息不再触达 Coze，客服回复实时出现。
- 任一方关闭后负载正确释放、后续会话可继续分配。
- 越权访问（看他人会话、替他人回复）被拒。
- `/consultant` 可独立登录和运行；非坐席管理员不能读取客服会话。
- 新排队、分配给我、非当前会话新消息能产生一次且仅一次的页面通知；授权后桌面通知可点击定位到对应会话。
- 管理员切换 `handoff_ai_agent_id` 后，新 AI 提问使用新智能体；伪造前端 `agent_id` 不能改变服务端实际使用的智能体。

---

## 14. 营养师客服台与用户人工咨询界面

### 14.1 营养师客服台（三栏工作台）

客服台不是普通内容管理列表，而是一个能同时处理多位用户的独立聊天工作台：

```
┌────────────会话列表────────────┬────────────当前聊天────────────┬────────用户与上下文────────┐
│ 排队中（2）                    │ 在线营养师 · 张老师            │ 姓名 / 团队 / 咨询类型      │
│ ● 王女士  等待 01:32           │ [AI 历史分隔线，默认折叠]       │ 当前状态 / 等待时长          │
│   赵先生  等待 00:48           │ 用户：我肠胃不舒服……           │ AI 对话摘要                  │
│                                │ 客服：请问持续多久了？          │                              │
│ 我的会话（3/3）                │ 用户：大约三天                  │ [确认接入] [结束并归档]      │
│ ③ 李女士  2 条未读             │                                │                              │
│   陈先生  等待回复             │ [输入框................][发送]  │                              │
└───────────────────────────────┴───────────────────────────────┴───────────────────────────┘
```

交互规则：

- 左栏分为「排队中」「分配给我」「进行中」三组；每条显示等待时间、最后一条消息、未读数和状态。
- 中栏一次只打开一个会话，但后台持续刷新全部会话摘要；切换会话不会关闭其他会话。
- AI 历史位于人工消息流之前，用明显分隔线标记为「转人工前的 AI 对话」，默认折叠、可展开，禁止在其中直接回复。
- 右栏展示用户身份、咨询类型、使用的 AI 智能体及控制按钮。只有 `cs_agents` 中的有效坐席可以接入和回复。
- 当 `current_load >= max_concurrent` 时，禁用新的「确认接入」，但已有会话仍可正常回复和结束。
- 客服发送消息时必须绑定当前 `session_id`；服务端再次校验 `agent_id`，不能依赖前端当前选中的标签页，避免串线。
- 每次打开会话调用 `read` 接口更新 `agent_last_read_message_id`；未读数按该 ID 之后的用户消息计算。

### 14.2 用户侧人工咨询视图

前台不增加首页卡片或常驻按钮。用户必须先在 `creative` 中明确表达转人工意图；选择「继续用 AI」后进入专用营养咨询视图，并从 `/api/handoff/config` 取得专用 `agent_id`。用户仍可正常切换到资讯等其他页面，不跳转到无法恢复状态的外部页面：

- 顶部状态栏：展示排队、预分配、已接入、已结束以及客服名称。
- 消息区：保留原 AI 对话；下方插入「以下为人工咨询」分隔线，再展示人工消息。
- 输入区：`ai` 时显示「向 AI 提问」；`queued/assigned/active` 时显示「给营养师留言」。
- 排队时允许继续补充问题，但这些问题只保存到 `handoff_messages`，不会再次发送给 AI。
- 页面不在前台时，如收到客服回复，通过导航红点/未读数提示；重新进入后从最后消息 ID 增量补齐。

为支持未读数和恢复，建议在 migration 中为 `handoff_sessions` 补充：

```sql
last_message_at TIMESTAMP,
user_last_read_message_id INTEGER DEFAULT 0,
agent_last_read_message_id INTEGER DEFAULT 0,
agent_claim_deadline TIMESTAMP
```

消息索引调整为 `INDEX(session_id, id)`，所有列表排序使用
`priority DESC, enqueued_at ASC, id ASC`，避免同一秒产生多条记录时顺序不稳定。

### 14.3 独立 PC 页面与通知提示

营养师使用独立地址 `/consultant`，不进入现有 `/admin` 内容管理页面。它复用管理员登录接口和 JWT，但登录后只加载客服工作台所需资源，适配常见 PC 浏览器宽屏布局；普通内容管理员如果不在 `cs_agents` 表中，只能看到“尚未开通客服权限”，不能进入会话列表。

通知分三层实现：

1. **页面内通知（必做）**：新用户排队、会话分配给当前客服、当前会话之外出现新消息时，显示右上角 Toast；左侧会话增加红点和未读数。
2. **声音提示（默认开启，可关闭）**：播放项目本地的短提示音；首次点击「上线接单」时初始化音频，满足浏览器必须由用户手势启用声音的限制。相同事件只响一次。
3. **系统桌面通知（用户授权后启用）**：客服主动点击「开启桌面通知」后调用浏览器 Notification API。页面位于后台标签时，显示「新的营养咨询」「用户有新回复」；点击通知聚焦 `/consultant` 并打开对应会话。

建议触发规则：

| 事件 | 通知对象 | 页面 Toast | 声音 | 桌面通知 |
|------|----------|------------|------|----------|
| 新会话进入 `queued` | 当前在线且有容量的客服 | 是 | 轻提示一次 | 页面不在前台时显示 |
| 会话进入 `assigned` | 被分配的客服 | 是 | 强提示一次 | 始终显示（已授权时） |
| 用户发送新消息 | 该会话所属客服 | 是 | 非当前打开会话时提示 | 页面不在前台时显示 |
| 用户取消/结束 | 该会话所属客服 | 是 | 否 | 否 |

客户端每 4 秒轮询 `/queue` 和 `/notifications`，使用 `session_id + event_type + last_message_id` 作为去重键，并把最近通知游标保存在 `localStorage`。页面标题同步显示未读数，例如 `(3) 营养师工作台`。客服点击某会话后调用 `read`，清除该会话未读数。

必须明确能力边界：轮询方案只能在 `/consultant` 页面仍处于打开状态时提供通知；浏览器完全退出后无法继续接收。如果未来要求浏览器关闭仍通知，需要再引入 Web Push、企业微信/钉钉通知或外部消息服务，不属于当前 SQLite MVP。

---

## 15. 等待、切入、切出与重新进入逻辑

这里必须区分三种用户动作，它们的业务含义不同：

| 用户动作 | 是否关闭人工会话 | 服务端状态 | 再次进入后的结果 |
|----------|------------------|------------|------------------|
| 离开聊天页/切到资讯等页面 | 否 | 保持 `queued/assigned/active` | 调 `/current` 恢复，看到全部历史和期间的新回复 |
| 点击「取消排队」 | 是 | `queued/assigned → closed(user_cancel)` | 旧记录只读；自动回到专用营养 AI |
| 点击「结束人工咨询」 | 是 | `active → closed(done)` | 旧记录只读；自动回到专用营养 AI |

### 15.1 首次切入人工咨询

1. 用户在 `creative` 中明确输入「转人工」或同义命令；该句仅标记为 `handoffIntent`，不发送给 Coze。
2. 前端弹出 AI 优先选择面板。选择 AI 时切换到 `handoff_ai_agent_id` 并继续提问；选择真人时直接进入下一步。
3. 前端停止接收尚未完成的 AI 流式回答，迟到内容不得继续写入人工消息流。
4. 调用 `/api/handoff/start`。服务端先查找该用户已有的未结束会话；存在则直接返回，避免重复排队。
5. 服务端保存最后 N 轮**已完成**的 AI 对话快照；`handoffIntent` 不进入快照或转接备注。
6. 前端进入 `queued`，显示位次；之后发送的内容全部进入人工消息流。

### 15.2 等待和预分配

- `queued`：允许留言、取消排队、离开页面；不允许 AI 自动回复。
- `assigned`：坐席获得短期预留，用户看到「正在接入」，客服须在 `agent_claim_deadline` 前确认。
- 预留超时：事务内清空 `agent_id`、释放 `current_load`、状态返回 `queued`，继续保留原排队时间，避免用户被排到队尾。
- 坐席确认后：进入 `active`，写入系统消息「营养师 XX 已接入」。
- `live` 模式超过在线等待上限且仍无真人回复时自动切换为 `message`；用户也可随时调用 `/api/handoff/defer` 主动切换。
- `message` 模式允许继续使用 AI 或浏览其他模块；客服首次回复后自动进入 `closed(message_replied)`。

### 15.3 切出页面后再回来

- 前端将 `session_id` 和 `last_message_id` 存在本地，只用于加速恢复，不能作为唯一状态源。
- 每次进入聊天页先调用 `/api/handoff/current`；若存在未结束会话，以服务端状态覆盖本地 `mode`。
- 随后请求 `/messages/<session_id>?after_id=<last_message_id>`；本地没有游标时取最近 50 条，再按需向前加载。
- 用户离开页面不释放客服容量，因为会话仍可能收到回复；只有明确取消/结束或超时归档才释放。
- 已结束的会话通过 `/recent` 查看，AI 历史和人工消息均保留为只读，因此用户回来后仍能看到之前的提问。
- 上述恢复依赖同一个登录/guest 身份；如果用户清除了浏览器身份令牌，不能仅凭姓名访问旧会话，避免越权泄露。

---

## 16. AI 回答、打断与发送真人的路由规则

前端只能有一个统一的 `routeConsultationMessage()` 入口，禁止 AI 发送按钮和人工发送按钮各自维护一套判断。每次发送前根据服务端会话状态决定通道：

| 当前状态 | 用户消息发送到 | AI 是否回答 | 说明 |
|----------|----------------|-------------|------|
| 无人工会话 / 人工会话刚结束 | `/api/chat/stream`，强制使用 `handoff_ai_agent_id` | 是 | 自动恢复正常 AI 咨询阶段 |
| `queued` | `/api/handoff/message` | 否 | 作为排队留言，客服接入后可立即看到 |
| `assigned` | `/api/handoff/message` | 否 | 坐席正在确认，消息继续累计 |
| `active` | `/api/handoff/message` | 否 | 完全由真人回答 |
| `service_mode=message` | `/api/chat/stream` | 是 | 留言由后台异步处理；真人回复通过人工消息轮询单独展示 |

伪代码：

```javascript
async function routeConsultationMessage(content) {
  const session = await getOrRefreshCurrentHandoff();
  if (session && ['queued', 'assigned', 'active'].includes(session.status)) {
    return sendHandoffMessage(session.session_id, content);
  }
  return streamAiMessage(content, handoffConfig.ai_agent_id);
}
```

### 16.1 何时打断 AI

- 用户在底部选择面板明确选择真人时立即打断前端 AI 展示：调用 `AbortController.abort()`，并用 `request_epoch` 丢弃已经到达但属于旧请求的 SSE 事件。
- 如果 Coze 请求已经在服务端完成，允许其正常落 `chat_history`，但转人工确认后的迟到内容不再渲染到人工消息流。
- `start` 只快照已完成的历史记录；这样客服看到的是完整问答，不会看到半截 AI 回复。
- `start` 同时把转接前最后一个有效问题写入人工消息流；即使 AI 历史因身份或保存时序未能取回，客服仍能立即看到用户要咨询的内容。转人工命令本身不作为问题传递。
- 转人工后禁止后台静默让 AI 继续替真人回复。将来若增加「AI 辅助客服」，也只能生成客服可编辑的草稿，必须由客服确认后才发送给用户。

### 16.2 何时恢复 AI

- 人工会话成为 `closed` 后立即自动恢复专用营养 AI，无需用户再次点击。
- 恢复后创建新的 AI 前端会话段，旧 AI 对话和人工咨询仍可回看；只有再次识别到明确转人工意图时才重新展示选择面板。
- 新的 AI 提问不应自动重新打开已关闭的人工会话；再次联系真人必须重新执行 `/start`。

### 16.3 服务端兜底

- `/api/handoff/message` 只接受属于当前用户且状态为 `queued|assigned|active` 的会话。
- `reply` 只接受状态为 `active` 且分配给当前坐席的会话。
- `/start` 必须幂等：同一用户已有未关闭会话时返回原会话。
- 营养咨询视图调用 `/api/chat/stream` 时额外携带 `channel='nutrition_consultation'`；聊天路由发现当前用户存在未结束的人工会话时返回 `409`，防止前端状态过期导致 AI 与真人同时回答。
- 前端状态仅负责体验；服务端必须依据数据库状态拒绝错通道、已关闭会话写入和越权请求。

### 16.4 营养咨询 AI 的独立智能体配置

营养咨询模块不跟随首页当前选中的普通智能体，统一读取 `settings.handoff_ai_agent_id`：

1. 管理员在 `/admin` 的转人工设置中，从现有智能体列表选择一个「营养咨询 AI」。
2. `PUT /api/admin/settings/handoff` 保存时，通过 `get_agent_config(agent_id)` 校验记录和 `bot_id`；非法配置返回 `400`。
3. `/api/handoff/config` 只向前端返回安全展示字段 `{agent_id, name, avatar_url, chat_desc}`，不返回真实 `bot_id`、提示词或 Coze 密钥。
4. 营养咨询 AI 请求虽然携带公开 `agent_id`，但服务端必须忽略用户伪造值，并用当前 `handoff_ai_agent_id` 覆盖后再调用 `build_chat_context`。
5. 每次 AI 聊天记录保存实际使用的 `agent_id`；发起转人工时将它写入 `handoff_sessions.ai_agent_id`，保证客服看到的是本次咨询真正使用的智能体。

配置变更规则：新配置只影响变更后的下一条 AI 请求；已经进入 `queued/assigned/active` 的人工会话不切换、不重新生成 AI 回复。如果未配置智能体、智能体不存在或没有 `bot_id`，前端禁用 AI 输入并提示「营养咨询 AI 暂未配置」，但仍可按业务配置决定是否允许直接联系真人。
