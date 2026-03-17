#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from granian import Granian

from app.admin import api as admin_api
from app.admin import routes as admin_routes
from app.core import claude, internal, openai
from app.core.config import reload_settings_from_sources, settings
from app.core.upstream import UpstreamClient
from app.services.postgres_backend import close_postgres_pool
from app.services.request_log_dao import init_request_log_dao
from app.services.runtime_config_dao import init_runtime_config_storage
from app.utils.logger import setup_logger
from app.utils.reload_config import RELOAD_CONFIG

logger = setup_logger(
    log_dir="logs",
    debug_mode=settings.DEBUG_LOGGING,
    enable_file_logging=settings.allow_file_logging,
)


async def warmup_upstream_client():
    """可选预热上游适配器，提前初始化动态依赖。"""
    try:
        client = UpstreamClient()
        logger.info(
            f"✅ 上游适配器已就绪，支持 {len(client.get_supported_models())} 个模型"
        )
    except Exception as exc:
        logger.warning(f"⚠️ 上游适配器预热失败: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.token_automation import (
        run_directory_import,
        start_token_automation_scheduler,
        stop_token_automation_scheduler,
    )
    from app.services.token_dao import get_token_dao
    from app.utils.token_pool import initialize_token_pool_from_db

    await init_runtime_config_storage()
    await get_token_dao().init_database()
    request_log_dao = init_request_log_dao()
    await request_log_dao.init_database()
    await reload_settings_from_sources()
    setup_logger(
        log_dir="logs",
        debug_mode=settings.DEBUG_LOGGING,
        enable_file_logging=settings.allow_file_logging,
    )

    if (
        not settings.is_serverless
        and settings.TOKEN_AUTO_IMPORT_ENABLED
        and settings.TOKEN_AUTO_IMPORT_SOURCE_DIR.strip()
    ):
        try:
            await run_directory_import(
                settings.TOKEN_AUTO_IMPORT_SOURCE_DIR,
                provider="zai",
            )
            logger.info("✅ 启动阶段已完成一次目录自动导入")
        except Exception as exc:
            logger.warning(f"⚠️ 启动阶段目录自动导入失败: {exc}")

    token_pool = await initialize_token_pool_from_db(
        provider="zai",
        failure_threshold=settings.TOKEN_FAILURE_THRESHOLD,
        recovery_timeout=settings.TOKEN_RECOVERY_TIMEOUT,
    )

    if not token_pool and not settings.ANONYMOUS_MODE:
        logger.warning("⚠️ 未找到可用 Token 且未启用匿名模式，服务可能无法正常工作")

    if settings.ANONYMOUS_MODE and not settings.is_serverless:
        from app.utils.guest_session_pool import initialize_guest_session_pool

        guest_pool = await initialize_guest_session_pool(
            pool_size=settings.GUEST_POOL_SIZE,
        )
        guest_status = guest_pool.get_pool_status()
        logger.info(
            "🫥 匿名会话池已就绪: "
            f"{guest_status.get('valid_sessions', 0)} 个可用会话"
        )

    if not settings.is_serverless:
        await warmup_upstream_client()
        await start_token_automation_scheduler()

    yield

    logger.info("🔄 应用正在关闭...")

    if not settings.is_serverless:
        await stop_token_automation_scheduler()

        if settings.ANONYMOUS_MODE:
            from app.utils.guest_session_pool import close_guest_session_pool

            await close_guest_session_pool()

    if settings.uses_postgres:
        await close_postgres_pool()


def _mount_static_files(app: FastAPI) -> None:
    static_dir = Path("app/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        return

    if settings.is_serverless:
        logger.warning("⚠️ 未找到 app/static，Vercel 模式下跳过 /static 挂载")
        return

    os.makedirs("app/static/css", exist_ok=True)
    os.makedirs("app/static/js", exist_ok=True)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, root_path=settings.ROOT_PATH)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    _mount_static_files(app)

    app.include_router(openai.router)
    app.include_router(claude.router)
    app.include_router(admin_routes.router)
    app.include_router(admin_api.router)
    app.include_router(internal.router)

    @app.options("/")
    async def handle_options():
        return Response(status_code=200)

    @app.get("/")
    async def root():
        return {"message": "OpenAI Compatible API Server"}

    return app


app = create_app()


def run_server():
    service_name = settings.SERVICE_NAME

    logger.info(f"🚀 启动 {service_name} 服务...")
    logger.info(f"📡 监听地址: 0.0.0.0:{settings.LISTEN_PORT}")
    logger.info(f"🔧 调试模式: {'开启' if settings.DEBUG_LOGGING else '关闭'}")
    logger.info(f"🔐 匿名模式: {'开启' if settings.ANONYMOUS_MODE else '关闭'}")

    try:
        Granian(
            "main:app",
            interface="asgi",
            address="0.0.0.0",
            port=settings.LISTEN_PORT,
            reload=False,
            process_name=service_name,
            **RELOAD_CONFIG,
        ).serve()
    except KeyboardInterrupt:
        logger.info("🛑 收到中断信号，正在关闭服务...")
    except Exception as exc:
        logger.error(f"❌ 服务启动失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    run_server()
