# AI宝儿智能体

AI 智能对话系统，基于 Coze Bot API。

## 项目速查

为了方便后续快速接手项目，已补充项目概览文档：

- [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md)

## 功能

- AI 智能对话（四种咨询类型）
- 快捷功能入口
- 客户案例档案推荐（按症状/产品标签匹配，回答后展示相关案例）
- 图文资讯推送（管理后台发布，支持 HTML 图文混排）
- 管理员后台：资讯管理、智能体配置、Coze API Key 在线更新
- 语音输入：支持阿里云和腾讯云 ASR，语音服务密钥在后台加密保存

## 安全启动

- `SECRET_KEY` 必须设置为至少 32 个字符的随机值；未设置时应用拒绝启动。
- 默认关闭公开注册。首次创建管理员请在部署环境执行：

  ```bash
  python3 scripts/create_admin.py admin
  ```

- 重置现有管理员密码请执行 `python3 scripts/reset_admin_password.py admin8`，密码只在终端交互输入，不会进入 Git。

- 生产环境应将 `DATABASE_DIR` 和 `UPLOAD_DIR` 指向持久化磁盘（Railway 默认是 `/data` 和 `/data/uploads`）。
- 若此前使用过旧版本，请立即轮换 Coze/阿里云凭据；旧数据库备份不得提交到 Git。
