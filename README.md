# z-ai2api_python

基于 FastAPI + Granian 的 GLM 代理服务
适合本地开发、自托管代理、Vercel Serverless 部署、Token 池管理和兼容客户端接入

中文简体 / [English](README_EN.md)  

## 特性

- 兼容 `OpenAI`、`Claude Code`、`Anthropic` 风格请求
- 支持流式响应、工具调用、Thinking 模型
- 内置 Token 池，支持轮询、失败熔断、恢复和健康检查
- 提供后台页面：仪表盘、Token 管理、配置管理、日志查看
- 本地可用 SQLite，Vercel 可切换到 PostgreSQL 持久化 Token、请求日志和运行时配置
- 支持本地运行、Docker / Docker Compose 和 Vercel 部署

## 快速开始

### 环境要求

- Python `3.9` 到 `3.12`
- 推荐使用 `uv`

### 本地启动

```bash
git clone https://github.com/ZyphrZero/z.ai2api_python.git
cd z.ai2api_python

uv sync
cp .env.example .env
uv run python main.py
```

首次启动会自动初始化数据库。

默认地址：

- API 根路径：`http://127.0.0.1:8080`
- OpenAI 文档：`http://127.0.0.1:8080/docs`
- 管理后台：`http://127.0.0.1:8080/admin`

### Docker Compose

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

更多部署说明见 [deploy/README_DOCKER.md](deploy/README_DOCKER.md)。

### 部署到 Vercel

仓库已经包含 [vercel.json](vercel.json) 和根目录入口 [index.py](index.py)，可以直接按 Vercel 当前 FastAPI 方式部署。

部署前请先准备一个外部 PostgreSQL 数据库，然后在 Vercel 项目环境变量中至少配置：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | 外部 PostgreSQL 连接串，Vercel 上不要使用 SQLite |
| `AUTH_TOKEN` | 客户端访问本服务时使用的 Bearer Token |
| `ADMIN_PASSWORD` | 管理后台密码 |
| `SESSION_SECRET_KEY` | 后台 Cookie 签名密钥 |
| `CRON_SECRET` | 保护 `/internal/cron/tokens/maintenance` 的内部 Bearer 密钥 |

部署流程示例：

```bash
vercel
vercel env add DATABASE_URL
vercel env add AUTH_TOKEN
vercel env add ADMIN_PASSWORD
vercel env add SESSION_SECRET_KEY
vercel env add CRON_SECRET
vercel --prod
```

说明：

- `vercel.json` 仅保留内置 Cron；HTTP 请求会直接进入根目录 `index.py` 暴露的 FastAPI 应用。
- Vercel 模式下不再依赖本地 `.env` 在线编辑，配置中心会把可热更新字段写入数据库。
- Token 目录自动导入已移除，请改用后台页面的单个或批量添加。
- 日志页改为查看说明，线上日志请直接在 Vercel Runtime Logs 中查看。
- Serverless 模式下会跳过本地常驻调度器、目录导入和 Guest 池预热。

如果你之前已经在本地 SQLite 中维护过 Token，可以先迁移到目标数据库：

```bash
uv run python migrate_sqlite_to_database.py
```

## 最小配置

至少建议确认这些环境变量：

| 变量 | 说明 |
| --- | --- |
| `AUTH_TOKEN` | 客户端访问本服务使用的 Bearer Token |
| `ADMIN_PASSWORD` | 管理后台登录密码，默认值必须修改 |
| `SESSION_SECRET_KEY` | 管理后台 Cookie 签名密钥 |
| `DATABASE_URL` | 外部 PostgreSQL 连接串；仅本地模式可只使用 `DB_PATH` |
| `CRON_SECRET` | Vercel Cron 调用内部维护接口时使用的 Bearer 密钥 |
| `LISTEN_PORT` | 服务监听端口，默认 `8080` |
| `ANONYMOUS_MODE` | 是否启用匿名模式 |
| `GUEST_POOL_SIZE` | 匿名池容量 |
| `DB_PATH` | 本地 / 自托管模式下的 SQLite 数据库路径 |
| `TOKEN_FAILURE_THRESHOLD` | Token 连续失败阈值 |
| `TOKEN_RECOVERY_TIMEOUT` | Token 恢复等待时间 |

完整配置请看 [.env.example](.env.example)。

## 管理后台

管理后台统一入口：

- `/admin`：仪表盘
- `/admin/tokens`：Token 管理
- `/admin/config`：配置管理
- `/admin/logs`：日志查看说明

## 常用命令

```bash
# 启动服务
uv run python main.py

# 运行测试
uv run pytest

# 运行一个现有 smoke test
uv run python tests/test_simple_signature.py

# Lint
uv run ruff check app tests main.py
```

## 兼容接口

常见接口入口：

- OpenAI 兼容：`/v1/chat/completions`
- Anthropic 兼容：`/v1/messages`
- Claude Code 兼容：`/anthropic/v1/messages`

模型映射和默认模型可在平台环境变量或后台配置页中调整。

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ZyphrZero/z.ai2api_python&type=Date)](https://star-history.com/#ZyphrZero/z.ai2api_python&Date)

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

## 免责声明

- **本项目仅供学习和研究使用，切勿用于其他用途**
- 本项目与 Z.AI 官方无关
- 使用前请确保遵守 Z.AI 的服务条款
- 请勿用于商业用途或违反使用条款的场景
- 用户需自行承担使用风险

---

<div align="center">
Made with ❤️ by the community
</div>
