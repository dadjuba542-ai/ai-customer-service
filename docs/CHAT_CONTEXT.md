# 网页向 Coze 传递 V3 原生上下文

网页聊天统一经过 `build_chat_context`，同步、流式以及排队任务均使用这个入口。

默认从数据库读取当前用户最近 6 轮已完成问答，按时间顺序排列，允许切换智能体后继续引用前面的对话。不同用户之间不共享。全局清空后不再发送旧历史；单独清空某智能体后，它的旧问答也不会通过其他智能体再次带入。

## 默认 V3 传递方式

`COZE_CHAT_API_VERSION=v3`（默认）调用 `COZE_V3_CHAT_URL`，默认地址为 `https://api.coze.cn/v3/chat`。

请求使用 `user_id`，通过 `additional_messages` 按时间顺序传递完整历史：用户消息为 `role=user/type=question`，历史回答为 `role=assistant/type=answer`，最后一条始终为原始本次提问。历史不会拼到当前输入中，也不使用 V2 的 `query`、`user`、`chat_history`。默认传递最近 6 轮；最多传递 49 轮加本次提问（99 条），避免超过 V3 的消息数量限制。

每次调用由 Coze 创建新会话，不复用 `conversation_id`；上下文以本地数据库窗口为准。这样跨智能体时不会复用另一个 bot 的会话，清空后也不会重新带入远端旧历史。`auto_save_history=true` 保留 Coze 执行记录以便排查，返回的会话标识继续保存在原有历史字段中。

后端统一使用 V3 SSE：网页流式接口转发正式回答的增量；网页同步接口和排队任务在后端收集完整回答后返回原有 JSON 格式，无需修改前端。V3 的非流式接口只返回任务状态，因此不能直接沿用 V2 的同步响应解析。知识库召回、工具调用、推荐问题等消息不会显示为正式回答；失败或中断不会保存成成功问答。

## V2 回退

设置 `COZE_CHAT_API_VERSION=v2` 并重启即可回退。只有 V2 使用 `COZE_API_URL` 和以下 `CHAT_CONTEXT_DELIVERY` 设置；V3 不受此设置影响。

- `CHAT_CONTEXT_DELIVERY=query`（默认）：仅把最近 6 轮中的用户问题按时间顺序列在本次输入前，最后附本次提问。不携带旧回答、角色 JSON 或冗长说明，避免旧回答混入知识库检索。此模式不重复发送 `chat_history`。数据库继续完整保存问答，统计、相关案例检索仍使用原始问题。
- `CHAT_CONTEXT_DELIVERY=history`：保持 `query` 为原始问题，把历史放入 Coze v2 `chat_history`。适用于能正确读取并向下游传递原生历史的 Coze 编排。

## 两个版本共用的上下文窗口

- `CHAT_CONTEXT_ROUNDS=0`：关闭历史传递。默认 `6`。
- `CHAT_CONTEXT_MESSAGE_MAX_CHARS`：每条历史消息的字符上限，默认 `2000`。

配置改动需要重启后端。显式携带历史会增加模型输入量；超过保留轮数或字符上限的内容不会完整传递。

## 验证

本地：运行 `python scripts/test_chat_v3.py` 验证 V3 原生问答历史、同步/流式/排队和网页接口、重复 token、完整回答补齐、非正式回答过滤、异常不入库、清空和隔离。运行 `python scripts/test_chat_context.py` 验证 V2 回退。均使用临时数据库和模拟响应，不调用真实 Coze API。

部署时设置 `COZE_CHAT_API_VERSION=v3`、`COZE_V3_CHAT_URL=https://api.coze.cn/v3/chat`，更新代码并重启后端。沿用原有 bot ID 和 API key；智能体需已发布到 API 渠道，令牌需具备 `chat` 权限。不要把 V3 地址填到 V2 的 `COZE_API_URL` 中，因为案例链接识别等独立功能仍使用 V2。

部署后：复现原先知识库调用失败的对话，再追问“把刚才的回答改短”，并切换另一个智能体追问。检查发出的 `additional_messages`：末条是独立的原始当前问题，前面的历史问答按角色分别传递。检查 Coze 正式回答节点确实读取了历史，并核对知识库实际检索内容及召回结果；原生传参不保证检索节点会自动选出最佳检索词。清空对话后再追问，应不再包含清空前的历史。

V2 的 `query` 模式只带历史问题，会削弱“把刚才的回答改短”等依赖旧回答的追问能力。V3 及 V2 原生 `history` 模式都传递完整历史问答。

此修复保证网页发出的请求携带历史。Coze 内部如果另行改写或截断输入、或工作流对输入格式有固定要求，仍需检查实际子智能体节点收到的内容；本地模拟测试不代表 Coze 线上编排已验证。
