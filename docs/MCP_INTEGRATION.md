# MCP 集成（只读数据源）

> 状态：**本地 + 线上均可用** ｜ 更新日期：2026-09-23
> 定位：把本站的数据与内容以 MCP 工具形式暴露给 opencode / Claude Desktop 等
> MCP host，用于运营分析、客服质检、文案/资讯/案例创作辅助。

## 一、边界与原则

- **只读**：所有工具都不写库。
- **内部用**：面向运营/开发，不是 C 端能力；**绝不接入前台客服链路**。
- **敏感信息脱敏**：`list_leads` 的手机号/微信默认打码；`list_agents` 不返回
  `prompt` / `bot_id`。即便脱敏，这些内容仍会进入模型上下文，请按内部数据对待。
- 工具实现集中在 `services/mcp_service.py`，两种传输共用。

## 二、两种传输

| 模式 | 入口 | 适用 | 鉴权 |
|---|---|---|---|
| **remote（线上，推荐）** | `POST /api/mcp`（Streamable HTTP） | opencode 连服务器读生产数据 | `Authorization: Bearer <MCP_TOKEN>` |
| **local（本地 stdio）** | `python3 scripts/mcp_server.py` | 本机开发、离线调试 | 无（只读本地库） |

## 三、线上启用（remote）

1. 在服务器环境变量里设置 `MCP_TOKEN`（留空则 `/api/mcp` 返回 403，端点关闭）：

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   # 把输出写进 MCP_TOKEN
   ```

   同时确保 `SECRET_KEY` 已配置（token 也支持加密存进 settings 表的 `mcp_token`）。

2. 重新部署 / 重启服务。

3. 自测：

   ```bash
   curl -s https://你的域名/api/mcp \
     -H "Authorization: Bearer $MCP_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```

   - 无 token / 错 token → `401`
   - 未配置 `MCP_TOKEN` → `403 MCP endpoint disabled`
   - 正常 → `200` + 工具列表

4. 本地准备 token 文件（**已被 `.gitignore` 忽略，不进仓库**）：

   ```bash
   printf '%s' '<与服务器一致的 MCP_TOKEN>' > .mcp_token   # 注意结尾不要换行
   ```

   `opencode.json` 已配好 remote，token 用 `{file:...}` 从本地文件读取：

   ```json
   {
     "mcp": {
       "ai-customer-service": {
         "type": "remote",
         "url": "https://aibao.jzzbaizhushou.com/api/mcp",
         "headers": { "Authorization": "Bearer {file:./.mcp_token}" },
         "enabled": true
       }
     }
   }
   ```

   > 若你的 opencode 版本不支持 `{file:...}`，改用 `{env:MCP_TOKEN}`，并先
   > `export MCP_TOKEN=...` 再启动 opencode。

5. **退出并重启 opencode**（配置只在启动时加载）。

### 本地先用 remote 自测（不部署也行）

本机跑起 Flask（`MCP_TOKEN=... python3 app.py`），把 `opencode.json` 的 `url`
临时改成 `http://127.0.0.1:5001/api/mcp` 即可。

## 四、本地启用（stdio，备用）

把 `opencode.json` 里 `ai-customer-service-local` 的 `enabled` 改成 `true`
（同时可把 remote 改成 `false`），重启 opencode 即可。它直连本地 SQLite，
与主程序共用 `DATABASE_DIR`。

手动自测：

```bash
printf '%s\n' \
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
'{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
| python3 scripts/mcp_server.py
```

## 五、工具清单

| 工具 | 参数 | 说明 |
|---|---|---|
| `chat_stats` | `days=7` | 问答量、独立用户、类型/智能体分布、赞踩数 |
| `search_chat_history` | `keyword`(必填), `days=30`, `limit=20` | 关键词搜历史问答 |
| `top_user_questions` | `days=30`, `limit=20`, `min_count=1` | 用户提问频次排行榜（归一化后计数） |
| `recent_bad_feedback` | `days=30`, `limit=20` | 被点踩的回答及原因 |
| `list_leads` | `status`, `limit=20` | 留资线索（联系方式已脱敏） |
| `search_products` | `keyword`, `limit=20` | 搜产品，返回名称/简介/卖点 |
| `get_product` | `product_id`(必填) | 产品完整详情（富文本正文） |
| `search_cases` | `query`(必填), `limit=10` | 搜案例库要点 |
| `get_case` | `case_id`(必填) | 案例完整内容 |
| `list_news` | `limit=20` | 资讯清单 |
| `get_news` | `news_id`(必填) | 资讯完整正文 |
| `list_agents` | — | 已配置智能体（不含 prompt/bot_id） |

## 六、安全与运维提醒

- token 泄露等于生产数据可被读取：请用高熵随机串，定期轮换，不要提交到仓库。
- `/api/mcp` 已豁免按 IP 的反爬预算（走 token 鉴权）；如需更严格，可在网关再限流。
- 端点仅支持 `application/json` 响应，不提供 GET/SSE 服务端推送（GET 返回 405，符合规范）。
- 如需撤销访问：清空 `MCP_TOKEN` 并重启即可整体关闭。
