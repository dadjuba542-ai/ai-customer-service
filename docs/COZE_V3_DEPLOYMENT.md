# COZE V3 配置、部署与重启说明

适用于本项目的网页聊天服务。代码已支持 V3；本说明用于把改动部署到实际运行的后端，并验证上下文效果。前端接口不需要改动。

当前本地目录是开发版本，生产网页运行在云服务器。本地测试通过不代表服务器已更新；本次诊断应在云服务器上进行，不能拿本地数据库和本地环境变量代替生产配置。

## 1. 设置环境变量

在后端运行环境中设置：

```env
COZE_CHAT_API_VERSION=v3
COZE_V3_CHAT_URL=https://api.coze.cn/v3/chat
CHAT_CONTEXT_ROUNDS=6
CHAT_CONTEXT_MESSAGE_MAX_CHARS=2000
```

- 原有 Bot ID、后台配置的 COZE API Key 可以沿用。智能体需已发布到 API 渠道，令牌需具备 `chat` 权限。
- V3 会通过 `additional_messages` 传递完整历史问答，最后一条为原始当前提问。不会把历史问答拼进当前提问。
- `CHAT_CONTEXT_DELIVERY` 只影响 V2 回退，V3 无需修改这一项。
- 保留现有 `SECRET_KEY`、数据库和上传目录配置，尤其是生产环境的持久化目录。
- **不要把 `COZE_API_URL` 改成 V3 地址**：案例链接识别等独立功能仍使用 V2 地址。

本项目通过 `os.environ` 读取配置，`python3 app.py` 不会自动加载项目里的 `.env`。仅编辑 `.env` 不一定生效；应由部署平台注入环境变量，或在启动终端中执行 `export`。

## 2. 本地启动或重启

在运行后端的终端中，先按 `Ctrl+C` 停止旧进程。进入项目目录并激活你原来使用的 Python 环境，再执行：

```bash
cd /Users/davidlee/Downloads/ai-customer-service
export COZE_CHAT_API_VERSION=v3
export COZE_V3_CHAT_URL=https://api.coze.cn/v3/chat
export CHAT_CONTEXT_ROUNDS=6
export CHAT_CONTEXT_MESSAGE_MAX_CHARS=2000
python3 app.py
```

启动前需已配置 `SECRET_KEY`（至少 32 个字符），以及环境变量或管理后台中的 COZE API Key。沿用原来的有效配置即可。

启动后访问：

- 前台：`http://localhost:5001/`
- 后台：`http://localhost:5001/admin`

如果提示缺少 Python 依赖，在已激活的项目 Python 环境中运行 `python3 -m pip install -r requirements.txt`，然后重新启动。

## 3. 更新并重启云服务器后端

1. 使用现有发布方式，把开发版本中的本次改动更新到服务器的应用目录。本次需包含 `config.py`、`services/chat_service.py`、新增的 `services/coze_diagnostics.py` 和 `scripts/diagnose_coze.py`。不要用本地开发数据库或开发 `.env` 覆盖生产文件。
2. 保留服务器原有 Python 环境、`SECRET_KEY`、COZE 密钥、Bot 绑定和数据库/上传目录。把第 1 节的 V3 变量以及排查用的 `COZE_DIAGNOSTICS_ENABLED=true` 配置到**实际运行后端的服务环境**。
3. 用现有方式重启后端：面板管理的服务在面板中重启；Docker 服务需要将新代码和变量更新到容器配置后重新创建容器；systemd/Supervisor 管理的服务通过对应管理器重启。重启命令中的服务名应使用服务器现有配置，不要凭空创建另一套服务。
4. 检查服务器启动日志，再访问生产网页复现问题；查找 `coze.diagnostic` 摘要。
5. SSH 登录服务器，进入实际应用目录，使用与后端相同的 Python 环境、数据库路径及环境变量，执行第 6 节的对照脚本。

仅在 SSH 终端中执行 `export` 不会更改已由面板、systemd、Supervisor 或 Docker 管理的后端进程。反过来，在服务管理器配置的变量也不一定会自动进入 SSH 终端；运行对照脚本前需确认它使用的是同一套生产配置。脚本会报告 `api_key_source`、`bot_source` 和 `database_state`，用于核对配置来源。

以下命令应在**云服务器实际应用目录**执行，不是本地开发目录：

```bash
# 使用服务器后端的 Python 环境；若环境的命令为 python，请将 python3 替换为 python
python3 scripts/diagnose_coze.py --agent-id translator
python3 scripts/diagnose_coze.py --agent-id translator --live
```

本地只需开发和运行模拟回归测试；真实对照在云服务器执行。脚本不会远程连接云服务器，修改本地变量也不会改变生产网页。

### Railway / Zeabur 托管部署（仅适用于这些平台）

1. 将包含本次 V3 改动的项目代码更新到实际部署使用的代码来源。
2. 在**后端服务**的环境变量配置中填入第 1 节的四项变量，保留已有密钥、Bot ID 和持久化目录配置。
3. 保存配置后重新部署后端服务，确保新进程运行的是更新后的代码。只有重启旧代码不会获得 V3 支持；仅刷新网页也不会更新后端配置。
4. 查看部署日志，确认启动成功，没有密钥校验失败、依赖缺失或数据库路径错误。

项目的 `railway.json` 和 `zeabur.json` 已配置 Gunicorn 启动命令，迁移 V3 不需要修改它们。Railway 当前使用 `/data` 和 `/data/uploads`，应保留对应持久化卷。

如果是在其他服务器上通过进程管理器运行 Gunicorn，把变量配置到该服务的启动环境，再通过原有进程管理器重新启动服务。终端里的 `export` 不会自动更新另一个已运行服务的环境。

## 4. 确认 V3 和上下文生效

在与后端相同的 Python 环境、相同的环境变量配置下，可检查非敏感配置：

```bash
python3 -c 'from config import Config; print("聊天接口版本:", Config.COZE_CHAT_API_VERSION); print("V3 地址:", Config.COZE_V3_CHAT_URL); print("历史轮数:", Config.CHAT_CONTEXT_ROUNDS)'
```

预期分别为 `v3`、`https://api.coze.cn/v3/chat` 和 `6`。这个命令仅检查当前命令环境；仍需通过下面的实际对话确认正在运行的服务。

1. 在网页发起一个问题，收到回答后追问“把刚才的回答改短”。
2. 切换另一个智能体继续追问，确认能理解前面的内容。
3. 在 COZE 执行记录中检查正式回答节点的上下文；知识库检索节点需要另查实际检索词和召回结果，推荐问题节点收到历史不代表正式回答节点也正确使用了历史。
4. 若能检查后端上游请求，确认地址为 `/v3/chat`，`additional_messages` 包含分开的历史用户消息、历史回答和最后一条当前问题。聊天请求不再使用 V2 的 `query`、`user`、`chat_history` 字段。
5. 清空网页对话，再追问旧内容，确认不会继续带入清空前的历史。

V3 原生传参解决的是历史和当前问题的传递方式；知识库是否恢复正常，仍以实际调用结果为准。

## 5. 本地回归与回退

在项目目录、已安装依赖的 Python 环境中运行：

```bash
python3 scripts/test_chat_v3.py
python3 scripts/test_chat_context.py
python3 scripts/test_chat_queue.py
```

这些测试使用临时数据库和模拟响应，不调用真实 COZE，也不能替代线上验收。`test_chat_context.py` 专门验证 V2 回退路径。

若上线后需要暂时恢复 V2，在后端运行环境设置：

```env
COZE_CHAT_API_VERSION=v2
```

随后重新部署或重启后端。V2 将使用原有 `COZE_API_URL` 和 `CHAT_CONTEXT_DELIVERY` 配置；默认 `query` 模式只携带历史问题，无法完整支持依赖旧回答的追问。

## 6. 平台成功、网页拒答时的诊断对照

先把包含诊断模块和脚本的新代码部署到服务器，在后端服务的环境变量中设置：

```env
COZE_DIAGNOSTICS_ENABLED=true
```

重新部署或重启后端，再在网页复现问题。服务日志中查找 `coze.diagnostic`，每次调用会有同一个 `request_id` 对应的 `request` 和 `result` 两条 JSON 摘要。同步、流式和排队都覆盖；排队请求的 `request_id` 沿用原任务标识。

摘要记录实际 `api_version`、`api_url`、`bot_id`、`publish_status`、`bot_version`、`history_message_count`、`current_question_independent`、`conversation_id`、`chat_id`、事件计数、工具名称及错误类别/码。发布状态与版本为未显式指定时的默认请求语义，不代表已读取远端发布配置。`outcome=success` 只说明收到并保存正式回答，不代表答案正确或知识库召回成功。

`messages_by_type` 按消息 ID 去重；`message_events` 统计每类消息的事件次数。`knowledge_content_chars` 仅为已完成知识库消息的正文字符数，不是召回切片数，也不能把 `[]` 等内容认定为有效召回。没有 `knowledge` 消息不能单独证明未检索：检索可能通过 `function_call` 与 `tool_output` / `tool_response` 完成。`tool_names` 有助于识别实际工具，但不会记录工具参数或结果正文。

这些诊断不会输出 Authorization、API Key、用户标识、当前问题、完整历史或工具参数。URL 的凭据、query 和 fragment 也会去掉。诊断默认关闭；启用期间以 WARNING 级别输出，确保默认服务日志级别下可见，日志级别不代表调用失败。

### 服务器端直接对照

在服务器中、与后端相同的 Python 环境、相同的环境变量和数据库目录下执行。脚本不会自动加载 `.env`。

```bash
# 默认只读配置，不发起 COZE 请求
python3 scripts/diagnose_coze.py --agent-id translator

# 显式调用 V3 已发布版本；默认就是本次失败的原始问题
python3 scripts/diagnose_coze.py --agent-id translator --live
```

默认问题为“今天想发一个咖啡灌肠每日坚持的文案”。默认读取后台数据库绑定的 Bot ID 和密钥，优先级与网页一致；输出只显示密钥是否配置及其来源。如果数据库密钥无法解密，会像网页一样回退环境变量，并在来源字段中标明这一情况。数据库缺失时会显示 `database_state=missing` 和 Bot 回退来源，不能把本地缺库环境当作线上配置。

`--live` 直接读取原始 V3 SSE，输出正式回答及事件摘要，不使用网页回答拼接/过滤逻辑，不保存本地问答，也不会清空现有对话。它固定 `publish_status=published_online`，只发送一个原始问题，不携带历史；会产生一次真实 COZE 调用及远端执行记录。

默认使用独立诊断用户，因此若 Bot 依赖用户变量或个人记忆，可能与实际网页用户不同。需要严格对照时，可由运维在服务器中用 `--user-id` 指定失败调用的同一 COZE 用户标识；脚本不把该标识输出到报告中。另可用 `--message` 测试其他问题，或用 `--bot-id` 覆盖 Bot，但输出会明确标记 `bot_source=command_line`。

### 如何判读

- 直接 API 成功、网页拒答：按实际版本、地址、Bot、历史数量及当前问题独立性比较请求；若不同用户，先排除用户变量差异。
- 直接 API 与网页均拒答、编辑页预览成功：使用 COZE 已发布版本的 API 测试再对照，检查发布配置、模型及知识库绑定。
- 存在知识库或相关工具事件但回答仍拒答：通过报告中的 `conversation_id` / `chat_id` 查对应 COZE 执行详情，区分召回为空、工具错误和模型未采用资料。
- `outcome=error`、`timeout`、`network_error` 或 `interrupted`：先检查错误类别、错误码和链路中断，不能当成知识库未调用。

结束后把 `COZE_DIAGNOSTICS_ENABLED` 改回 `false` 并重启。回归测试可运行 `python3 scripts/test_coze_diagnostics.py`，它模拟上游，验证日志脱敏、事件统计、回答保持一致以及对照脚本不写入数据库。

更多实现细节见 [上下文传递说明](CHAT_CONTEXT.md)。
