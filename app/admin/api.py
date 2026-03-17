"""
管理后台 API 接口
用于 htmx 调用的 HTML 片段返回
"""

import re
from datetime import datetime
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.admin.auth import (
    create_session,
    delete_session,
    get_session_token_from_request,
    require_auth,
)
from app.admin.config_manager import (
    read_env_content,
    save_form_config,
)
from app.admin.stats import collect_admin_stats, normalize_trend_window
from app.core.config import reload_settings_from_sources, settings
from app.services.request_log_dao import get_request_log_dao
from app.utils.logger import logger

router = APIRouter(prefix="/admin/api", tags=["admin-api"])
templates = Jinja2Templates(directory="app/templates")
DEFAULT_TOKEN_NAMESPACE = "zai"


# ==================== 认证 API ====================

@router.post("/login")
async def login(request: Request):
    """管理后台登录"""
    try:
        data = await request.json()
        password = data.get("password", "")

        # 创建 session
        session_token = create_session(password)

        if session_token:
            # 登录成功，设置 cookie
            response = JSONResponse({
                "success": True,
                "message": "登录成功"
            })
            response.set_cookie(
                key="admin_session",
                value=session_token,
                httponly=True,
                max_age=86400,  # 24小时
                samesite="lax",
                secure=settings.is_vercel,
            )
            logger.info("✅ 管理后台登录成功")
            return response
        else:
            # 密码错误
            logger.warning("❌ 管理后台登录失败：密码错误")
            return JSONResponse({
                "success": False,
                "message": "密码错误"
            }, status_code=401)

    except Exception as e:
        logger.error(f"❌ 登录异常: {e}")
        return JSONResponse({
            "success": False,
            "message": "登录失败"
        }, status_code=500)


@router.post("/logout")
async def logout(request: Request):
    """管理后台登出"""
    session_token = get_session_token_from_request(request)
    delete_session(session_token)

    # 清除 cookie
    response = JSONResponse({
        "success": True,
        "message": "已登出"
    })
    response.delete_cookie("admin_session")
    logger.info("✅ 管理后台已登出")
    return response


async def reload_settings():
    from app.utils.logger import setup_logger

    await reload_settings_from_sources()
    setup_logger(
        log_dir="logs",
        debug_mode=settings.DEBUG_LOGGING,
        enable_file_logging=settings.allow_file_logging,
    )

    logger.info(f"🔄 配置已热重载 (DEBUG_LOGGING={settings.DEBUG_LOGGING})")


def _build_alert(
    message: str,
    *,
    title: str,
    level: str,
    status_code: int = 200,
) -> HTMLResponse:
    level_classes = {
        "success": "bg-green-100 border-green-400 text-green-700",
        "warning": "bg-yellow-100 border-yellow-400 text-yellow-700",
        "error": "bg-red-100 border-red-400 text-red-700",
        "info": "bg-blue-100 border-blue-400 text-blue-700",
    }
    classes = level_classes.get(level, level_classes["info"])
    safe_title = escape(title)
    safe_message = escape(message)
    return HTMLResponse(
        f"""
        <div class="{classes} border px-4 py-3 rounded relative" role="alert">
            <strong class="font-bold">{safe_title}</strong>
            <span class="block sm:inline">{safe_message}</span>
        </div>
        """,
        status_code=status_code,
    )


def _with_hx_trigger(response: HTMLResponse, event_name: str) -> HTMLResponse:
    response.headers["HX-Trigger"] = event_name
    return response


def _get_int_query_param(
    request: Request,
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    """解析查询参数中的正整数，非法值回退到默认值。"""
    raw_value = request.query_params.get(name)
    if raw_value is None:
        return default

    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default

    value = max(minimum, value)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _build_pagination(
    *,
    total_items: int,
    page: int,
    page_size: int,
) -> dict:
    """构建分页上下文。"""
    total_items = max(0, int(total_items))
    page_size = max(1, int(page_size))
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    current_page = min(max(1, int(page)), total_pages)

    if total_items == 0:
        start_item = 0
        end_item = 0
    else:
        start_item = (current_page - 1) * page_size + 1
        end_item = min(total_items, current_page * page_size)

    return {
        "current_page": current_page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_previous": current_page > 1,
        "has_next": current_page < total_pages,
        "previous_page": max(1, current_page - 1),
        "next_page": min(total_pages, current_page + 1),
        "start_item": start_item,
        "end_item": end_item,
    }


def _normalize_display_value(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    return normalized


def _is_redundant_source(source: str, client_name: str) -> bool:
    normalized_source = _normalize_display_value(source)
    normalized_client = _normalize_display_value(client_name)
    if not normalized_source:
        return True
    if not normalized_client:
        return False
    return normalized_source == normalized_client


def _humanize_protocol(protocol: str) -> str:
    normalized = str(protocol or "").strip().lower()
    if normalized == "openai":
        return "OpenAI"
    if normalized == "anthropic":
        return "Anthropic"
    if normalized == "unknown":
        return "Unknown"
    return normalized or "Unknown"


@router.get(
    "/dashboard/usage-trend",
    response_class=JSONResponse,
    dependencies=[Depends(require_auth)],
)
async def get_dashboard_usage_trend(request: Request):
    """返回仪表盘趋势图数据。"""
    trend_window = normalize_trend_window(
        request.query_params.get("window")
    )
    dao = get_request_log_dao()
    trend_points = await dao.get_provider_usage_trend(
        DEFAULT_TOKEN_NAMESPACE,
        window=trend_window,
    )
    return JSONResponse(
        {
            "window": trend_window,
            "points": trend_points,
        }
    )


@router.get(
    "/token-pool",
    response_class=HTMLResponse,
    dependencies=[Depends(require_auth)],
)
async def get_token_pool_status(request: Request):
    """获取 Token 池状态（HTML 片段）"""
    from app.utils.token_pool import get_token_pool

    token_pool = get_token_pool()

    if not token_pool:
        # Token 池未初始化
        context = {
            "request": request,
            "tokens": [],
        }
        return templates.TemplateResponse("components/token_pool.html", context)

    # 获取 token 状态统计
    pool_status = token_pool.get_pool_status()
    tokens_info = []

    for idx, token_info in enumerate(pool_status.get("tokens", []), 1):
        is_available = token_info.get("is_available", False)
        is_healthy = token_info.get("is_healthy", False)

        # 确定状态和颜色
        if is_healthy:
            status = "健康"
            status_color = "bg-green-100 text-green-800"
        elif is_available:
            status = "可用"
            status_color = "bg-yellow-100 text-yellow-800"
        else:
            status = "失败"
            status_color = "bg-red-100 text-red-800"

        # 格式化最后使用时间
        last_success = token_info.get("last_success_time", 0)
        if last_success > 0:
            last_used = datetime.fromtimestamp(last_success).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            last_used = "从未使用"

        tokens_info.append({
            "index": idx,
            "key": token_info.get("token", "")[:20] + "...",
            "status": status,
            "status_color": status_color,
            "last_used": last_used,
            "failure_count": token_info.get("failure_count", 0),
            "success_rate": token_info.get("success_rate", "0%"),
            "token_type": token_info.get("token_type", "unknown"),
        })

    context = {
        "request": request,
        "tokens": tokens_info,
    }

    return templates.TemplateResponse("components/token_pool.html", context)


@router.get(
    "/recent-logs",
    response_class=HTMLResponse,
    dependencies=[Depends(require_auth)],
)
async def get_recent_logs(request: Request):
    """获取最近的请求日志（HTML 片段）"""
    dao = get_request_log_dao()
    page_size = _get_int_query_param(
        request,
        "page_size",
        12,
        maximum=50,
    )
    requested_page = _get_int_query_param(request, "page", 1, maximum=100000)
    total_count = await dao.count_logs()
    pagination = _build_pagination(
        total_items=total_count,
        page=requested_page,
        page_size=page_size,
    )

    rows = await dao.get_recent_logs(
        limit=page_size,
        offset=(pagination["current_page"] - 1) * page_size,
    )
    logs = []
    for row in rows:
        timestamp = (
            row.get("timestamp")
            or row.get("created_at")
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        success = bool(row.get("success"))
        status_code = int(
            row.get("status_code") or (200 if success else 500)
        )
        duration_value = float(row.get("duration") or 0.0)
        first_token_value = float(row.get("first_token_time") or 0.0)
        source = row.get("source") or "unknown"
        client_name = row.get("client_name") or "Unknown"
        provider = row.get("provider") or "-"
        source_display = (
            ""
            if _is_redundant_source(source, client_name)
            else source
        )
        provider_display = "" if provider == "zai" else provider
        logs.append(
            {
                "timestamp": timestamp,
                "endpoint": row.get("endpoint") or "-",
                "model": row.get("model") or "-",
                "provider": provider,
                "provider_display": provider_display,
                "source": source,
                "source_display": source_display,
                "protocol": row.get("protocol") or "unknown",
                "protocol_display": _humanize_protocol(
                    row.get("protocol") or "unknown"
                ),
                "client_name": client_name,
                "success": success,
                "status_code": status_code,
                "duration_display": f"{duration_value:.2f}s",
                "first_token_display": (
                    f"{first_token_value:.2f}s"
                    if first_token_value > 0
                    else "--"
                ),
                "input_tokens": int(row.get("input_tokens") or 0),
                "output_tokens": int(row.get("output_tokens") or 0),
                "cache_creation_tokens": int(
                    row.get("cache_creation_tokens") or 0
                ),
                "cache_read_tokens": int(
                    row.get("cache_read_tokens") or 0
                ),
                "error_message": row.get("error_message") or "",
            }
        )

    context = {
        "request": request,
        "logs": logs,
        "page": pagination,
    }

    return templates.TemplateResponse("components/recent_logs.html", context)


@router.post("/config/save", dependencies=[Depends(require_auth)])
async def save_config(request: Request):
    """保存结构化配置并热重载。"""
    try:
        form_data = await request.form()
        await save_form_config(
            form_data,
            reload_callback=reload_settings,
        )
        logger.info("✅ 结构化配置已保存")
        return _with_hx_trigger(
            _build_alert(
                "配置已保存并热重载，页面即将刷新。",
                title="保存成功！",
                level="success",
            ),
            "admin-config-refresh",
        )
    except ValueError as exc:
        return _build_alert(
            str(exc),
            title="校验失败！",
            level="error",
            status_code=400,
        )
    except Exception as exc:
        logger.error(f"❌ 配置保存失败: {exc}")
        return _build_alert(
            f"保存失败: {exc}",
            title="错误！",
            level="error",
            status_code=500,
        )


@router.post("/config/source", dependencies=[Depends(require_auth)])
async def save_config_source(request: Request):
    """兼容旧入口：提示改用数据库配置。"""
    return _build_alert(
        "当前版本已迁移为数据库运行时配置，不再支持直接编辑 .env。",
        title="入口已弃用",
        level="warning",
        status_code=410,
    )


@router.post("/config/reset", dependencies=[Depends(require_auth)])
async def reset_config():
    """兼容旧入口：数据库配置模式下不支持 .env 重置。"""
    return _build_alert(
        "当前版本已迁移为数据库运行时配置，不再支持重置 .env.example。",
        title="入口已弃用",
        level="warning",
        status_code=410,
    )


@router.get("/env-preview", dependencies=[Depends(require_auth)])
async def get_env_preview():
    """兼容旧入口：展示环境变量管理说明。"""
    content = read_env_content()
    return HTMLResponse(f"<pre>{escape(content)}</pre>")


@router.get(
    "/live-logs",
    response_class=HTMLResponse,
    dependencies=[Depends(require_auth)],
)
async def get_live_logs():
    """兼容旧日志面板：提示改看平台日志。"""
    return _build_alert(
        (
            "当前版本不再读取本地日志文件。请在 Vercel 项目面板的 "
            "Runtime Logs 中查看线上日志，本地开发时请直接查看终端输出。"
        ),
        title="日志查看说明",
        level="info",
    )


# ==================== Token 管理 API ====================

@router.get(
    "/tokens/list",
    response_class=HTMLResponse,
    dependencies=[Depends(require_auth)],
)
async def get_tokens_list(request: Request):
    """获取 Token 列表（HTML 片段）"""
    from app.services.token_dao import get_token_dao

    dao = get_token_dao()
    page_size = _get_int_query_param(
        request,
        "page_size",
        20,
        maximum=100,
    )
    requested_page = _get_int_query_param(request, "page", 1, maximum=100000)
    total_count = await dao.count_tokens_by_provider(
        DEFAULT_TOKEN_NAMESPACE,
        enabled_only=False,
    )
    pagination = _build_pagination(
        total_items=total_count,
        page=requested_page,
        page_size=page_size,
    )
    tokens = await dao.get_tokens_by_provider(
        DEFAULT_TOKEN_NAMESPACE,
        enabled_only=False,
        limit=page_size,
        offset=(pagination["current_page"] - 1) * page_size,
    )

    context = {
        "request": request,
        "tokens": tokens,
        "page": pagination,
    }

    return templates.TemplateResponse("components/token_list.html", context)


@router.post("/tokens/add", dependencies=[Depends(require_auth)])
async def add_tokens(request: Request):
    """添加 Token"""
    from app.services.token_dao import get_token_dao
    from app.utils.token_pool import get_token_pool

    form_data = await request.form()
    single_token = form_data.get("single_token", "").strip()
    bulk_tokens = form_data.get("bulk_tokens", "").strip()

    dao = get_token_dao()
    added_count = 0
    failed_count = 0

    # 添加单个 Token（带验证）
    if single_token:
        token_id = await dao.add_token(
            DEFAULT_TOKEN_NAMESPACE,
            single_token,
            validate=True,
        )
        if token_id:
            added_count += 1
        else:
            failed_count += 1

    # 批量添加 Token（带验证）
    if bulk_tokens:
        # 支持换行和逗号分隔
        tokens = []
        for line in bulk_tokens.split('\n'):
            line = line.strip()
            if ',' in line:
                tokens.extend([t.strip() for t in line.split(',') if t.strip()])
            elif line:
                tokens.append(line)

        success, failed = await dao.bulk_add_tokens(
            DEFAULT_TOKEN_NAMESPACE,
            tokens,
            validate=True,
        )
        added_count += success
        failed_count += failed

    # 同步 Token 池状态（如果有新增成功的 Token）
    if added_count > 0:
        pool = get_token_pool()
        if pool:
            await pool.sync_from_database(DEFAULT_TOKEN_NAMESPACE)
            logger.info(f"✅ Token 池已同步，新增 {added_count} 个 Token")

    # 生成响应
    if added_count > 0 and failed_count == 0:
        return _build_alert(
            f"已添加 {added_count} 个有效 Token",
            title="成功！",
            level="success",
        )
    if added_count > 0 and failed_count > 0:
        return _build_alert(
            (
                f"已添加 {added_count} 个 Token，{failed_count} 个失败"
                "（可能是重复、无效或匿名 Token）"
            ),
            title="部分成功！",
            level="warning",
        )
    return _build_alert(
        "所有 Token 添加失败（可能是重复、无效或匿名 Token）",
        title="失败！",
        level="error",
        status_code=400,
    )


@router.post("/tokens/import-directory", dependencies=[Depends(require_auth)])
async def import_tokens_from_directory_api(request: Request):
    """目录导入已弃用。"""
    return _build_alert(
        "当前版本已移除服务端本地目录导入，请改用页面中的手动单个/批量添加 Token。",
        title="目录导入已移除",
        level="warning",
        status_code=410,
    )


@router.post("/tokens/auto-import/save", dependencies=[Depends(require_auth)])
async def save_auto_import_settings(request: Request):
    """兼容旧入口，提示用户改到配置管理页。"""
    return _build_alert(
        "目录自动导入已移除，请改用手动单个/批量导入。",
        title="功能已移除",
        level="info",
    )


@router.post("/tokens/maintenance/save", dependencies=[Depends(require_auth)])
async def save_auto_maintenance_settings(request: Request):
    """兼容旧入口，提示用户改到配置管理页。"""
    return _build_alert(
        "自动维护配置入口已迁移到 /admin/config#tokens，当前页面仅保留手动执行入口。",
        title="入口已迁移",
        level="info",
    )


@router.post("/tokens/maintenance/run", dependencies=[Depends(require_auth)])
async def run_token_maintenance_api(request: Request):
    """立即执行一次 Token 维护。"""
    from app.core.config import settings
    from app.services.token_automation import run_token_maintenance

    form_data = await request.form()
    action_fields = (
        "auto_remove_duplicates",
        "auto_health_check",
        "auto_delete_invalid",
    )
    has_explicit_actions = any(field in form_data for field in action_fields)

    if has_explicit_actions:
        remove_duplicates = "auto_remove_duplicates" in form_data
        run_health_check = "auto_health_check" in form_data
        delete_invalid = "auto_delete_invalid" in form_data
    else:
        remove_duplicates = settings.TOKEN_AUTO_REMOVE_DUPLICATES
        run_health_check = settings.TOKEN_AUTO_HEALTH_CHECK
        delete_invalid = settings.TOKEN_AUTO_DELETE_INVALID

    if not any((remove_duplicates, run_health_check, delete_invalid)):
        return _build_alert(
            (
                "当前没有可执行的维护动作，请先到 "
                "/admin/config#tokens 配置至少一个维护动作。"
            ),
            title="未执行维护！",
            level="warning",
            status_code=400,
        )

    try:
        summary = await run_token_maintenance(
            provider=DEFAULT_TOKEN_NAMESPACE,
            remove_duplicates=remove_duplicates,
            run_health_check=run_health_check,
            delete_invalid_tokens=delete_invalid,
        )
    except RuntimeError as exc:
        return _build_alert(
            str(exc),
            title="维护稍后重试",
            level="warning",
            status_code=409,
        )
    except Exception as exc:
        logger.exception(f"❌ 手动执行 Token 维护失败: {exc}")
        return _build_alert(
            f"Token 维护失败: {exc}",
            title="维护失败！",
            level="error",
            status_code=500,
        )

    return _build_alert(
        (
            f"本次维护共去重 {summary.duplicate_removed_count} 个，"
            f"测活 {summary.checked_count} 个（有效 {summary.valid_count} / "
            f"匿名 {summary.guest_count} / 无效 {summary.invalid_count}），"
            f"删除失效 Token {summary.deleted_invalid_count} 个。"
        ),
        title="维护完成！",
        level="success",
    )


@router.post(
    "/tokens/toggle/{token_id}",
    dependencies=[Depends(require_auth)],
)
async def toggle_token(token_id: int, enabled: bool):
    """切换 Token 启用状态"""
    from app.services.token_dao import get_token_dao
    from app.utils.token_pool import get_token_pool

    dao = get_token_dao()
    await dao.update_token_status(token_id, enabled)

    # 同步 Token 池状态
    pool = get_token_pool()
    if pool:
        provider = await dao.get_token_provider(token_id)
        await pool.sync_from_database(provider)
        logger.info("✅ Token 池已同步")

    # 根据状态返回不同样式的按钮
    if enabled:
        button_class = "bg-green-100 text-green-800 hover:bg-green-200"
        indicator_class = "bg-green-500"
        label = "已启用"
        next_state = "false"
    else:
        button_class = "bg-red-100 text-red-800 hover:bg-red-200"
        indicator_class = "bg-red-500"
        label = "已禁用"
        next_state = "true"

    button_classes = (
        "inline-flex items-center px-2.5 py-0.5 text-xs "
        f"font-semibold rounded-full transition-colors {button_class}"
    )
    return HTMLResponse(f"""
    <button hx-post="/admin/api/tokens/toggle/{token_id}?enabled={next_state}"
            hx-swap="outerHTML"
            class="{button_classes}">
        <span class="h-2 w-2 rounded-full mr-1.5 {indicator_class}"></span>
        {label}
    </button>
    """)


@router.delete(
    "/tokens/delete/{token_id}",
    dependencies=[Depends(require_auth)],
)
async def delete_token(token_id: int):
    """删除 Token"""
    from app.services.token_dao import get_token_dao
    from app.utils.token_pool import get_token_pool

    dao = get_token_dao()

    # 获取 Token 信息以确定提供商
    provider = await dao.get_token_provider(token_id)

    await dao.delete_token(token_id)

    # 同步 Token 池状态
    pool = get_token_pool()
    if pool:
        await pool.sync_from_database(provider)
        logger.info("✅ Token 池已同步")

    return HTMLResponse("")  # 返回空内容，让 htmx 移除元素


@router.get(
    "/tokens/stats",
    response_class=HTMLResponse,
    dependencies=[Depends(require_auth)],
)
async def get_tokens_stats(request: Request):
    """获取 Token 统计信息（HTML 片段）"""
    stats_data = await collect_admin_stats(DEFAULT_TOKEN_NAMESPACE)

    context = {
        "request": request,
        "stats": stats_data,
    }

    return templates.TemplateResponse("components/token_stats.html", context)


@router.post("/tokens/validate", dependencies=[Depends(require_auth)])
async def validate_tokens():
    """批量验证 Token"""
    from app.services.token_dao import get_token_dao
    from app.utils.token_pool import get_token_pool

    dao = get_token_dao()

    # 执行批量验证
    stats = await dao.validate_all_tokens(DEFAULT_TOKEN_NAMESPACE)

    pool = get_token_pool()
    if pool:
        await pool.sync_from_database(DEFAULT_TOKEN_NAMESPACE)

    valid_count = stats.get("valid", 0)
    guest_count = stats.get("guest", 0)
    invalid_count = stats.get("invalid", 0)

    # 生成通知消息
    if guest_count > 0:
        message = (
            f"验证完成：有效 {valid_count} 个，匿名 {guest_count} 个，"
            f"无效 {invalid_count} 个。匿名 Token 已标记。"
        )
        level = "warning"
    elif invalid_count > 0:
        message = f"验证完成：有效 {valid_count} 个，无效 {invalid_count} 个。"
        level = "info"
    else:
        message = f"验证完成：所有 {valid_count} 个 Token 均有效！"
        level = "success"

    return _build_alert(
        message,
        title="批量验证完成！",
        level=level,
    )


@router.post(
    "/tokens/validate-single/{token_id}",
    dependencies=[Depends(require_auth)],
)
async def validate_single_token(request: Request, token_id: int):
    """验证单个 Token 并返回更新后的行"""
    from app.services.token_dao import get_token_dao
    from app.utils.token_pool import get_token_pool

    dao = get_token_dao()

    # 验证 Token
    await dao.validate_and_update_token(token_id)

    pool = get_token_pool()
    if pool:
        await pool.sync_from_database(DEFAULT_TOKEN_NAMESPACE)

    # 获取更新后的 Token 信息
    token = await dao.get_token_with_stats(token_id)

    if token:
        # 返回更新后的单行 HTML
        context = {
            "request": request,
            "token": token,
        }
        # 使用单行模板渲染
        return templates.TemplateResponse("components/token_row.html", context)
    else:
        return HTMLResponse("")


@router.post("/tokens/health-check", dependencies=[Depends(require_auth)])
async def health_check_tokens():
    """执行 Token 池健康检查"""
    from app.utils.token_pool import get_token_pool

    pool = get_token_pool()

    if not pool:
        return _build_alert(
            "Token 池未初始化，请重启服务。",
            title="提示！",
            level="warning",
        )

    # 执行健康检查
    await pool.health_check_all()

    # 获取健康状态
    status = pool.get_pool_status()
    healthy_count = status.get("healthy_tokens", 0)
    total_count = status.get("total_tokens", 0)

    if healthy_count == total_count:
        message = f"所有 {total_count} 个 Token 均健康！"
        level = "success"
    elif healthy_count > 0:
        message = f"健康检查完成：{healthy_count}/{total_count} 个 Token 健康。"
        level = "info"
    else:
        message = f"警告：0/{total_count} 个 Token 健康，请检查配置。"
        level = "error"

    return _build_alert(
        message,
        title="健康检查完成！",
        level=level,
    )


@router.post("/tokens/sync-pool", dependencies=[Depends(require_auth)])
async def sync_token_pool():
    """手动同步 Token 池（从数据库重新加载）"""
    from app.utils.token_pool import get_token_pool

    pool = get_token_pool()

    if not pool:
        return _build_alert(
            "Token 池未初始化，请重启服务。",
            title="提示！",
            level="warning",
        )

    # 从数据库同步
    await pool.sync_from_database(DEFAULT_TOKEN_NAMESPACE)

    # 获取同步后的状态
    status = pool.get_pool_status()
    total_count = status.get("total_tokens", 0)
    available_count = status.get("available_tokens", 0)
    user_count = status.get("user_tokens", 0)

    logger.info(
        "✅ Token 池手动同步完成，总计 {} 个 Token, 可用 {} 个, 认证用户 {} 个",
        total_count,
        available_count,
        user_count,
    )

    if total_count == 0:
        message = "同步完成：当前没有可用 Token，请在数据库中启用 Token。"
        level = "warning"
    elif available_count == 0:
        message = (
            f"同步完成：共 {total_count} 个 Token，但无可用 Token"
            "（可能都已禁用）。"
        )
        level = "warning"
    else:
        message = (
            f"同步完成：共 {total_count} 个 Token，{available_count} 个可用，"
            f"{user_count} 个认证用户。"
        )
        level = "success"

    return _build_alert(
        message,
        title="Token 池同步完成！",
        level=level,
    )
