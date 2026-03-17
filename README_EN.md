# z-ai2api_python

GLM proxy service based on FastAPI + Granian
Suitable for local development, self-hosted proxy, Vercel Serverless deployment, Token pool management, and compatible client access

English / [中文简体](README.md)

## Features

- Compatible with `OpenAI`, `Claude Code`, `Anthropic` style requests
- Supports streaming responses, tool calls, Thinking models
- Built-in Token pool, supports polling, failure circuit breaker, recovery, and health checks
- Provides admin panel: Dashboard, Token management, Configuration management, and log guidance
- Uses SQLite locally and can switch to PostgreSQL on Vercel for Tokens, request logs, and runtime config
- Supports local running, Docker / Docker Compose, and Vercel deployment

## Quick Start

### Environment Requirements

- Python `3.9` to `3.12`
- Recommend using `uv`

### Local Startup

```bash
git clone https://github.com/ZyphrZero/z.ai2api_python.git
cd z.ai2api_python

uv sync
cp .env.example .env
uv run python main.py
```

First startup will automatically initialize the database.

Default addresses:

- API root path: `http://127.0.0.1:8080`
- OpenAI docs: `http://127.0.0.1:8080/docs`
- Admin panel: `http://127.0.0.1:8080/admin`

### Docker Compose

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

More deployment instructions see [deploy/README_DOCKER.md](deploy/README_DOCKER.md).

### Deploy to Vercel

This repository already includes [vercel.json](vercel.json) and the root entrypoint [index.py](index.py), so it can be deployed directly using Vercel's current FastAPI flow.

Before deploying, prepare an external PostgreSQL database and configure at least these environment variables in your Vercel project:

| Variable | Description |
| --- | --- |
| `DATABASE_URL` | External PostgreSQL connection string. Do not use SQLite on Vercel |
| `AUTH_TOKEN` | Bearer Token used by clients to access this service |
| `ADMIN_PASSWORD` | Admin panel password |
| `SESSION_SECRET_KEY` | Signing key for admin cookies |
| `CRON_SECRET` | Bearer secret for `/internal/cron/tokens/maintenance` |

Example deployment flow:

```bash
vercel
vercel env add DATABASE_URL
vercel env add AUTH_TOKEN
vercel env add ADMIN_PASSWORD
vercel env add SESSION_SECRET_KEY
vercel env add CRON_SECRET
vercel --prod
```

Notes:

- `vercel.json` now only keeps the built-in Cron; HTTP traffic goes directly to the FastAPI app exposed from the root `index.py`.
- In Vercel mode, the admin config page stores hot-reloadable fields in the database instead of editing `.env`.
- Directory-based Token import has been removed. Use single or bulk Token entry from the admin panel instead.
- The logs page now points you to Vercel Runtime Logs for production diagnostics.
- Serverless mode skips local background schedulers, directory import, and Guest pool prewarming.

If you already have Tokens in a local SQLite database, migrate them before switching environments:

```bash
uv run python migrate_sqlite_to_database.py
```

## Minimum Configuration

At least suggest confirming these environment variables:

| Variable | Description |
| --- | --- |
| `AUTH_TOKEN` | Bearer Token used by clients to access this service |
| `ADMIN_PASSWORD` | Admin panel login password, default value must be changed |
| `SESSION_SECRET_KEY` | Signing key for admin cookies |
| `DATABASE_URL` | External PostgreSQL connection string; local mode can still use `DB_PATH` |
| `CRON_SECRET` | Bearer secret used by the internal Vercel Cron endpoint |
| `LISTEN_PORT` | Service listening port, default `8080` |
| `ANONYMOUS_MODE` | Whether to enable anonymous mode |
| `GUEST_POOL_SIZE` | Anonymous pool capacity |
| `DB_PATH` | SQLite database path for local / self-hosted mode |
| `TOKEN_FAILURE_THRESHOLD` | Token consecutive failure threshold |
| `TOKEN_RECOVERY_TIMEOUT` | Token recovery wait time |

Complete configuration please see [.env.example](.env.example).

## Admin Panel

Admin panel unified entry:

- `/admin`: Dashboard
- `/admin/tokens`: Token management
- `/admin/config`: Configuration management
- `/admin/logs`: Log guidance page

## Common Commands

```bash
# Start service
uv run python main.py

# Run tests
uv run pytest

# Run an existing smoke test
uv run python tests/test_simple_signature.py

# Lint
uv run ruff check app tests main.py
```

## Compatible Interfaces

Common interface entries:

- OpenAI compatible: `/v1/chat/completions`
- Anthropic compatible: `/v1/messages`
- Claude Code compatible: `/anthropic/v1/messages`

Model mapping and default model can be adjusted through platform environment variables or the admin configuration page.

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ZyphrZero/z.ai2api_python&type=Date)](https://star-history.com/#ZyphrZero/z.ai2api_python&Date)

## License

This project uses MIT license - see [LICENSE](LICENSE) file for details.

## Disclaimer

- **This project is for learning and research use only, do not use for other purposes**
- This project is not affiliated with Z.AI official
- Please ensure compliance with Z.AI's terms of service before use
- Do not use for commercial purposes or scenarios that violate terms of service
- Users must bear their own usage risks

---

<div align="center">
Made with ❤️ by the community
</div>
