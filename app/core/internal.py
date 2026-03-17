"""内部运维接口。"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.services.runtime_config_dao import acquire_runtime_job, get_runtime_config_dao
from app.services.token_automation import run_token_maintenance

router = APIRouter(prefix="/internal", tags=["internal"])


def _require_cron_secret(authorization: str | None) -> None:
    expected = str(settings.CRON_SECRET or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET 未配置")

    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="未授权的内部调用")


@router.get("/cron/tokens/maintenance")
async def run_scheduled_token_maintenance(
    authorization: str | None = Header(default=None),
):
    """供 Vercel Cron 调用的 Token 自动维护入口。"""
    _require_cron_secret(authorization)

    if not settings.TOKEN_AUTO_MAINTENANCE_ENABLED:
        return JSONResponse(
            {"ok": True, "status": "disabled", "message": "自动维护未开启"}
        )

    if not any(
        (
            settings.TOKEN_AUTO_REMOVE_DUPLICATES,
            settings.TOKEN_AUTO_HEALTH_CHECK,
            settings.TOKEN_AUTO_DELETE_INVALID,
        )
    ):
        return JSONResponse(
            {"ok": True, "status": "no-op", "message": "未配置任何维护动作"}
        )

    minimum_interval_seconds = int(settings.TOKEN_AUTO_MAINTENANCE_INTERVAL or 0)
    if settings.is_vercel:
        minimum_interval_seconds = max(300, minimum_interval_seconds)

    acquired = await acquire_runtime_job(
        "token_maintenance",
        minimum_interval_seconds,
        status="running",
        message="scheduled start",
    )
    if not acquired:
        return JSONResponse(
            {"ok": True, "status": "skipped", "message": "未达到最小执行间隔"}
        )

    dao = get_runtime_config_dao()
    try:
        summary = await run_token_maintenance(
            provider="zai",
            remove_duplicates=settings.TOKEN_AUTO_REMOVE_DUPLICATES,
            run_health_check=settings.TOKEN_AUTO_HEALTH_CHECK,
            delete_invalid_tokens=settings.TOKEN_AUTO_DELETE_INVALID,
        )
        await dao.update_job_run(
            "token_maintenance",
            status="success",
            message=(
                f"dedupe={summary.duplicate_removed_count}, "
                f"checked={summary.checked_count}, "
                f"deleted={summary.deleted_invalid_count}"
            ),
        )
        return JSONResponse(
            {
                "ok": True,
                "status": "success",
                "summary": {
                    "checked_count": summary.checked_count,
                    "duplicate_removed_count": summary.duplicate_removed_count,
                    "valid_count": summary.valid_count,
                    "guest_count": summary.guest_count,
                    "invalid_count": summary.invalid_count,
                    "deleted_invalid_count": summary.deleted_invalid_count,
                },
            }
        )
    except Exception as exc:
        await dao.update_job_run(
            "token_maintenance",
            status="failed",
            message=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"自动维护失败: {exc}") from exc
