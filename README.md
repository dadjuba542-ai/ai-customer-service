# AI宝儿智能体

AI 智能对话系统，基于 Coze Bot API。

## 部署到 Zeabur（推荐，国内友好）

### 一键部署

[![Deploy on Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/templates/)

### 手动部署步骤

1. **注册** [Zeabur](https://zeabur.com) — 用 GitHub 登录，中文界面

2. **推送代码到 GitHub**
   ```bash
   git init
   git add .
   git commit -m "init"
   ```

3. **Zeabur 新建项目** → 选择 GitHub 仓库 → 自动部署
   - 会自动识别 Python 项目，安装 requirements.txt
   - 使用 gunicorn 启动（已在 zeabur.json 里配置好）

4. **设置环境变量（必须）：**
   - `COZE_API_KEY` — 你的 Coze API 密钥
   - `SECRET_KEY` — 改为随机字符串（安全用途）
   - `ADMIN_USERNAME` — 管理员用户名（默认 `admin8`）
   - `DATABASE_DIR` — 持久化路径（见下一步）

5. **配置持久化存储（防止数据丢失）：**
   - 部署完成后 → Storage 栏 → 创建 Persistent Storage
   - Mount Path 填 `/data`
   - 然后设置环境变量 `DATABASE_DIR=/data`

6. **完成** — 打开 `.zeabur.app` 域名即可使用

### 首次使用

- 注册账号：用用户名 `admin8` 注册 → 自动成为管理员
- 管理员入口：首页顶部头像**快速连击 5 次**
- 管理后台：发布资讯、配置智能体、更新 API Key

## 本地运行

```bash
pip install -r requirements.txt
python app.py
```

访问 http://localhost:5001

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `COZE_API_KEY` | Coze API 密钥 | — |
| `SECRET_KEY` | JWT 加密密钥（改随机串） | 固定值 |
| `ADMIN_USERNAME` | 管理员用户名 | admin8 |
| `BOT_PRODUCT` | 产品咨询 Bot ID | config 默认值 |
| `BOT_FAQ` | 使用答疑 Bot ID | config 默认值 |
| `BOT_MOMENT` | 朋友圈帮写 Bot ID | config 默认值 |
| `BOT_SCRIPT` | 口播文案 Bot ID | config 默认值 |
| `DATABASE_DIR` | 数据库存储目录 | 项目目录 |

## 功能

- AI 智能对话（四种咨询类型）
- 快捷功能入口
- 图文资讯推送（管理后台发布，支持 HTML 图文混排）
- 管理员后台：资讯管理、智能体配置、Coze API Key 在线更新
