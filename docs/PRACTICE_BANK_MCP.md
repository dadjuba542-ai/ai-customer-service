# 题库管理 MCP

本地 AI 助手通过独立的管理 MCP 连接服务器题库。服务端入口为
`POST /api/mcp/practice-bank`，使用专用 Bearer 令牌；原有 `/api/mcp`
继续只读，原有令牌不能管理题库。管理工具直接复用后台的题目校验、版本检查、
CSV 预检与原子导入。题目修改后，新练习使用新版本，已创建会话保留原快照。

## 启用服务器

在部署环境新增 `PRACTICE_BANK_MCP_TOKEN`，使用至少 32 位的独立随机值，
不能与 `MCP_TOKEN` 相同。留空时管理端点返回 403。生成令牌的示例：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

部署包含本功能的代码并设置环境变量后，在本机将同一令牌保存到项目根目录的
`.mcp_bank_token`。文件已加入 `.gitignore`；建议仅本人可读：

```bash
chmod 600 .mcp_bank_token
```

`opencode.json` 已预置 `ai-practice-bank-manager` 的远程连接。
在令牌和服务器就绪后，将该条目的 `enabled` 改成 `true` 并重启本地助手。
若服务器地址不同，修改配置中的 `url`。只读 MCP 仍可同时使用。

如果本地助手只支持 stdio，可运行零额外依赖的转发脚本。以 Claude Desktop
配置格式为例，路径按实际目录修改：

```json
{
  "mcpServers": {
    "ai-practice-bank": {
      "command": "python3",
      "args": ["/Users/davidlee/Downloads/ai-customer-service/scripts/practice_bank_mcp_bridge.py"],
      "env": {
        "PRACTICE_BANK_MCP_TOKEN_FILE": "/Users/davidlee/Downloads/ai-customer-service/.mcp_bank_token"
      }
    }
  }
}
```

转发脚本默认连接 `https://aibao.jzzbaizhushou.com/api/mcp/practice-bank`；
可用 `PRACTICE_BANK_MCP_URL` 指向其他服务器。公网地址必须使用 HTTPS。

## 工具

| 工具 | 用途 |
|---|---|
| `practice_bank_overview` | 查看母题库、主题题库、关卡题量、分类和能力标签 |
| `practice_list_questions` | 分页按关键词、题库、关卡、启用状态搜题 |
| `practice_get_question` | 获取完整题目、推荐答案及 `updated_at` 版本 |
| `practice_list_products` / `practice_get_product_context` | 查产品编号、培训事实卡及来源，供产品题核对依据 |
| `practice_learning_guidelines` | 读取五级难度定义、七单元梯度、四选一出题规则和审核流程；本地AI建题前先调用 |
| `practice_learning_outline` | 查看课堂独立录入的产品名称、七个进阶单元、知识卡和选题情况 |
| `practice_suggest_placement` | 提交学习目标、五级难度和单元归属建议，等待后台负责人审核 |
| `practice_create_question` | 新增题目，默认停用；`request_id` 防止重试重复创建 |
| `practice_update_question` | 按版本局部修改题目，冲突时重新读取 |
| `practice_preview_csv` | 批量导入预检，不写库 |
| `practice_import_csv` | 合并导入，整批原子写入；`request_id` 防止重复导入 |

单题可编辑字段：`batch_no`、`category`、`title`、`options`（四项）、
`answer_index`（0–3）、`explanation`、`method`、`sources`、`enabled`、
`product_id`、`skill_code`、`fact_id`。不能通过修改题目转移所属题库。
学习目标、难度（1识别事实、2理解判断、3场景应用、4组织回答、5综合应对）和建议单元须通过
`practice_suggest_placement` 提交，不能由 MCP 直接写入正式分级。
进阶主线的产品名称、知识卡和产品问题在课堂后台单独输入，不读取产品板块内容。
本地 AI 应先读取 `practice_learning_guidelines` 的完整规则，再用 `practice_learning_outline` 取得当前单元 ID、知识卡和题目缺口。提交后到后台
「进阶学习主线」确认分级、选入单元并发布，MCP 建议本身不发布课程。
每周主题的已发布分组仍由后台组题流程管理；可以通过
`weekly_new_import=true` 向每周主题导入新题草稿。CSV 导入不提供整库替换。

| 难度 | 学员要完成的判断 | 默认主线单元 |
|---|---|---|
| 1 识别事实 | 从知识卡定位一项直接事实 | 认识产品 |
| 2 理解判断 | 解读、比较配料或规格信息 | 配料与规格 |
| 3 场景应用 | 根据客户情境决定先问什么、查什么 | 判断客户需求、使用方法 |
| 4 组织回答 | 用已知依据给出完整回复和下一步 | 准确回答与核实、客户常见提问 |
| 5 综合应对 | 同时处理多个顾虑，安排沟通顺序 | 处理异议与后续跟进 |

每题只考一个学习目标。四个选项应是可信的不同判断，推荐答案应能由该单元知识卡支持；解析说清关键依据，`method` 给一条可实际使用的参考回复。产品知识不足时，围绕“先核实再回复”出题，不补造产品事实。AI 创建题目时使用母题库 `stage_id=0`，保持停用，随后通过 `practice_suggest_placement` 提交分级建议；负责人审核后才选入主线。`batch_no` 只表示每日10题的题组编号，与五级难度无关。

给本地 AI 助手的任务可以直接这样写：

> 先调用 `practice_learning_guidelines` 和 `practice_learning_outline`，读取出题规则、目标单元 ID 与独立录入的知识卡。为第 N 单元查重并补足到 3 道四选一题；每题只考一个学习目标，按该单元难度编写题干、四选项、唯一推荐答案、解析和参考回复。先创建停用题，再提交分级与单元建议，最后列出题号和仍需负责人补充的知识卡信息。不要替我发布课程。

常见操作顺序：

1. 建设主线时，先调用 `practice_learning_guidelines` 和 `practice_learning_outline`，再查重或补题；普通题库维护可从 `practice_bank_overview` 开始。
2. 修改现有题时，先 `practice_get_question` 取得 `updated_at`，再调用
   `practice_update_question` 只提交需要修改的字段。
3. 新题先创建为停用，检查题干、四个选项、答案和解析，再开启。
4. 批量修改先 `practice_preview_csv`，确认错误为空，再以同一 CSV 调用
   `practice_import_csv`。CSV 表头与后台导出的题库一致；修改已有题需带
   `id` 和导出时的 `版本`。

## 连通性检查

配置好后让助手列出 `ai-practice-bank-manager` 的工具，调用
`practice_bank_overview`。如果只读 MCP 能用但管理工具不可用，先检查
服务器是否已部署新代码、`PRACTICE_BANK_MCP_TOKEN` 与本地令牌是否一致、
以及本地助手是否已重新加载配置。服务端对跨站 `Origin` 请求拒绝访问；
普通桌面 MCP 客户端无需设置 `Origin`。

该 HTTP 入口沿用项目现有的 JSON-RPC MCP 实现，支持 `initialize`、
`tools/list`、`tools/call` 和通知。GET 返回 405，表示不提供 SSE 推送；
这符合 [MCP Streamable HTTP 传输说明](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)。
