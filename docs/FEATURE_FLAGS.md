# 功能开关（案例系统 / 人工客服系统）

两套系统各有独立开关，互不影响。所有开关集中登记在 `services/feature_flags.py` 的
`FLAGS` 注册表里，**新增开关只需要加一行**。

## 开关清单

| 名字 | 说明 | settings key | 环境变量 | 默认值 |
| --- | --- | --- | --- | --- |
| `cases` | 案例系统：相关案例推荐、前台案例抽屉、后台案例/标签管理、链接识别 | `cases_enabled` | `CASES_ENABLED` | **开启** |
| `handoff` | 人工客服系统：转接/留言、坐席工作台、后台队列与坐席管理、派单定时任务 | `handoff_enabled` | `HANDOFF_ENABLED` | **关闭** |

人工客服系统的 key 沿用原有的 `handoff_enabled`，后台「AI 与转接设置」里改的是同一个值，
不会出现两个开关打架。

## 状态怎么读

优先级：**settings 表（后台改过）> 环境变量 > 注册表默认值**。

```python
from services import feature_flags

feature_flags.is_enabled('cases')      # -> bool，未知名字一律按 False 处理
feature_flags.state_of('handoff')      # -> 含 enabled / source / default / setting_key 的 dict
feature_flags.list_states()            # -> 所有开关状态（后台接口用）
feature_flags.set_enabled('cases', False)   # 写入 settings 表
```

`source` 字段说明当前状态来自哪里：`database` / `environment` / `default`，排查「我明明在后台关了却还开着」时先看它。

HTTP 接口：

- `GET /api/feature-flags` —— 前台只读，只给 `{name, label, enabled}`
- `GET /api/admin/feature-flags` —— 管理员读全量状态
- `PUT /api/admin/feature-flags` —— 管理员写入，支持单个 `{"name": "cases", "enabled": false}`
  或批量 `{"flags": {"cases": false, "handoff": true}}`

## 关闭时会发生什么

三层拦截，缺一不可：

1. **HTTP 入口**：`install_request_guard(app)` 注册的 `before_request` 按注册表里的路径前缀拦截
   （接口返回 `403 + code=feature_disabled`，页面返回说明页）。`cases` / `handoff` /
   `admin_handoff` 三个 blueprint 各带一层 `before_request` 兜底，防止前缀漏配。
   先匹配路径再查库，普通请求（含静态资源）不产生额外查询。
2. **调用链路**：服务层自己判断一次，内部调用和后台任务绕不过去
   - `chat_service.find_related_cases()`：案例系统关闭时直接返回空列表
   - handoff 的 `start_handoff` / `append_user_message` / `close_user_session` /
     `defer_user_session` / `set_agent_status` / `claim_session` / `append_agent_reply`
     直接抛 403 `HandoffError`
3. **定时任务**：`start_handoff_reconciler()` 在开关关闭时不启动；运行期被关掉后
   `_reconcile_loop` 每轮跳过，`assign_available()` 返回 0。后台重新打开开关会补启动线程。

豁免路径：`/api/handoff/config` 始终可读——前台靠它拿到 `enabled=false` 来决定是否隐藏转人工入口。

前台（`static/js/core.js`）启动时拉 `/api/feature-flags`，关闭的系统不渲染入口、不发请求；
后台侧边栏里带 `data-feature` 的入口（案例档案 / 人工客服 / 营养师工作台）会自动隐藏。

## 业务约束

开启人工客服系统仍需先配置营养咨询 AI 智能体（校验在 `_handoff_validate`，
后台「功能开关」页直接开启时同样生效）。

## 回归

`scripts/test_feature_flags.py` 覆盖默认状态、双向独立开关、入口/调用链/定时任务禁用、
批量更新、未知开关 404。
