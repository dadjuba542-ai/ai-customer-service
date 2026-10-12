# COZE V3 配置、部署与重启说明

适用于本项目的网页聊天服务。代码已支持 V3；本说明用于把改动部署到实际运行的后端，并验证上下文效果。前端接口不需要改动。

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

## 3. 部署到 Railway / Zeabur

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

更多实现细节见 [上下文传递说明](CHAT_CONTEXT.md)。
