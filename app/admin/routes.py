"""
管理后台路由模块
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.admin.auth import require_auth
from app.admin.config_manager import build_config_page_data
from app.admin.stats import (
    DEFAULT_TREND_WINDOW,
    TREND_WINDOW_OPTIONS,
    collect_admin_stats,
    get_process_uptime,
)
from app.core.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")
DEFAULT_TOKEN_NAMESPACE = "zai"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def dashboard(request: Request):
    """仪表盘首页"""
    stats = await collect_admin_stats(
        DEFAULT_TOKEN_NAMESPACE,
        trend_window=DEFAULT_TREND_WINDOW,
    )
    stats["uptime"] = get_process_uptime()

    context = {
        "request": request,
        "stats": stats,
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trend_windows": TREND_WINDOW_OPTIONS,
    }

    return templates.TemplateResponse("index.html", context)


@router.get(
    "/config",
    response_class=HTMLResponse,
    dependencies=[Depends(require_auth)],
)
async def config_page(request: Request):
    """配置管理页面"""
    page_data = build_config_page_data()

    context = {
        "request": request,
        "sections": page_data["sections"],
        "overview": page_data["overview"],
    }
    return templates.TemplateResponse("config.html", context)


@router.get("/logs", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def logs_page(request: Request):
    """日志查看说明页"""
    context = {
        "request": request,
        "is_vercel": settings.is_vercel,
    }
    return templates.TemplateResponse("logs.html", context)


@router.get(
    "/tokens",
    response_class=HTMLResponse,
    dependencies=[Depends(require_auth)],
)
async def tokens_page(request: Request):
    """Token 管理页面"""
    maintenance_actions: list[str] = []
    if settings.TOKEN_AUTO_REMOVE_DUPLICATES:
        maintenance_actions.append("删除重复 Token")
    if settings.TOKEN_AUTO_HEALTH_CHECK:
        maintenance_actions.append("批量测活")
    if settings.TOKEN_AUTO_DELETE_INVALID:
        maintenance_actions.append("删除失效 Token")

    context = {
        "request": request,
        "automation": {
            "config_url": "/admin/config#tokens",
            "import_supported": not settings.is_vercel,
            "maintenance_enabled": settings.TOKEN_AUTO_MAINTENANCE_ENABLED,
            "maintenance_interval": settings.TOKEN_AUTO_MAINTENANCE_INTERVAL,
            "maintenance_actions": maintenance_actions,
            "has_maintenance_actions": bool(maintenance_actions),
            "is_vercel": settings.is_vercel,
        },
    }
    return templates.TemplateResponse("tokens.html", context)
