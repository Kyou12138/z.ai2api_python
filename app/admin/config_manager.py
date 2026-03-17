"""管理后台配置元数据与运行时配置存储辅助函数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.core.config import (
    RUNTIME_MANAGED_KEYS,
    get_runtime_setting_overrides,
    settings,
)
from app.services.runtime_config_dao import get_runtime_config_dao


@dataclass(frozen=True)
class ConfigFieldSpec:
    key: str
    label: str
    description: str
    value_type: str
    default_value: object
    input_type: str = "text"
    placeholder: str = ""
    required: bool = False
    wide: bool = False
    sensitive: bool = False
    editable: bool = True
    min_value: int | None = None
    max_value: int | None = None
    storage_kind: str = "runtime"


@dataclass(frozen=True)
class ConfigSectionSpec:
    id: str
    title: str
    description: str
    fields: tuple[ConfigFieldSpec, ...]


def _field(
    key: str,
    label: str,
    description: str,
    value_type: str,
    default_value: object,
    **kwargs,
) -> ConfigFieldSpec:
    return ConfigFieldSpec(
        key=key,
        label=label,
        description=description,
        value_type=value_type,
        default_value=default_value,
        **kwargs,
    )


CONFIG_SECTIONS: tuple[ConfigSectionSpec, ...] = (
    ConfigSectionSpec(
        id="access",
        title="接入与行为",
        description="数据库持久化的运行时配置，保存后会立即重载到当前实例。",
        fields=(
            ConfigFieldSpec(
                key="API_ENDPOINT",
                label="上游 API 地址",
                description="代理请求实际转发到的上游聊天完成接口。",
                value_type="str",
                default_value="https://chat.z.ai/api/v2/chat/completions",
                input_type="url",
                placeholder="https://chat.z.ai/api/v2/chat/completions",
                required=True,
                wide=True,
            ),
            ConfigFieldSpec(
                key="AUTH_TOKEN",
                label="客户端认证密钥",
                description="敏感配置，改为通过平台环境变量管理。",
                value_type="str",
                default_value="sk-your-api-key",
                input_type="password",
                placeholder="sk-your-api-key",
                wide=True,
                sensitive=True,
                editable=False,
                storage_kind="env",
            ),
            ConfigFieldSpec(
                key="SKIP_AUTH_TOKEN",
                label="跳过客户端认证",
                description="仅建议开发环境使用，开启后不校验 AUTH_TOKEN。",
                value_type="bool",
                default_value=False,
            ),
            ConfigFieldSpec(
                key="TOOL_SUPPORT",
                label="启用 Function Call",
                description="允许 OpenAI 兼容接口使用工具调用能力。",
                value_type="bool",
                default_value=True,
            ),
            ConfigFieldSpec(
                key="SCAN_LIMIT",
                label="工具调用扫描限制",
                description="Function Call 扫描的最大字符数。",
                value_type="int",
                default_value=200000,
                input_type="number",
                min_value=1,
                placeholder="200000",
            ),
        ),
    ),
    ConfigSectionSpec(
        id="server",
        title="平台与运行时",
        description="这些字段由平台环境变量控制，后台仅做只读展示。",
        fields=(
            ConfigFieldSpec(
                key="DATABASE_URL",
                label="数据库连接串",
                description="Vercel / 外部数据库连接串，仅可通过环境变量配置。",
                value_type="str",
                default_value="",
                input_type="password",
                wide=True,
                sensitive=True,
                editable=False,
                storage_kind="env",
            ),
            ConfigFieldSpec(
                key="SERVICE_NAME",
                label="服务名称",
                description="本地进程名称或标识，Vercel 上仅作展示。",
                value_type="str",
                default_value="api-proxy-server",
                editable=False,
                storage_kind="env",
            ),
            ConfigFieldSpec(
                key="LISTEN_PORT",
                label="监听端口",
                description="本地运行端口，Vercel 上由平台接管。",
                value_type="int",
                default_value=8080,
                input_type="number",
                editable=False,
                storage_kind="env",
            ),
            ConfigFieldSpec(
                key="ROOT_PATH",
                label="反向代理路径前缀",
                description="例如 /api，部署在子路径时使用。",
                value_type="str",
                default_value="",
                placeholder="/api",
                editable=False,
                storage_kind="env",
            ),
            ConfigFieldSpec(
                key="DEBUG_LOGGING",
                label="调试日志",
                description="是否输出更详细的控制台日志。",
                value_type="bool",
                default_value=False,
                editable=False,
                storage_kind="env",
            ),
        ),
    ),
    ConfigSectionSpec(
        id="tokens",
        title="Token 池策略",
        description="目录自动导入已移除，仅保留数据库驱动的维护策略。",
        fields=(
            ConfigFieldSpec(
                key="TOKEN_FAILURE_THRESHOLD",
                label="失败阈值",
                description="连续失败多少次后将 Token 标记为不可用。",
                value_type="int",
                default_value=3,
                input_type="number",
                min_value=1,
                required=True,
            ),
            ConfigFieldSpec(
                key="TOKEN_RECOVERY_TIMEOUT",
                label="恢复超时（秒）",
                description="失败 Token 重新参与调度前的等待时间。",
                value_type="int",
                default_value=1800,
                input_type="number",
                min_value=1,
                required=True,
            ),
            ConfigFieldSpec(
                key="TOKEN_AUTO_MAINTENANCE_ENABLED",
                label="启用自动维护",
                description="由 Vercel Cron 定时触发执行维护逻辑。",
                value_type="bool",
                default_value=False,
            ),
            ConfigFieldSpec(
                key="TOKEN_AUTO_MAINTENANCE_INTERVAL",
                label="自动维护间隔（秒）",
                description="Cron 入口最短执行间隔；Vercel 模式下最低 300 秒。",
                value_type="int",
                default_value=1800,
                input_type="number",
                min_value=1,
                required=True,
            ),
            ConfigFieldSpec(
                key="TOKEN_AUTO_REMOVE_DUPLICATES",
                label="自动去重",
                description="自动维护时清理重复 Token。",
                value_type="bool",
                default_value=True,
            ),
            ConfigFieldSpec(
                key="TOKEN_AUTO_HEALTH_CHECK",
                label="自动健康检查",
                description="自动维护时验证 Token 可用性。",
                value_type="bool",
                default_value=True,
            ),
            ConfigFieldSpec(
                key="TOKEN_AUTO_DELETE_INVALID",
                label="自动删除失效 Token",
                description="自动维护时移除已验证为无效的 Token。",
                value_type="bool",
                default_value=False,
            ),
        ),
    ),
    ConfigSectionSpec(
        id="guest",
        title="匿名会话策略",
        description="Vercel 上不再预热长驻池，仅保留按请求懒获取的容量配置。",
        fields=(
            ConfigFieldSpec(
                key="ANONYMOUS_MODE",
                label="启用匿名模式",
                description="无可用用户 Token 时允许使用匿名会话。",
                value_type="bool",
                default_value=True,
            ),
            ConfigFieldSpec(
                key="GUEST_POOL_SIZE",
                label="Guest 池目标容量",
                description="用于限制单实例匿名会话补齐规模。",
                value_type="int",
                default_value=3,
                input_type="number",
                min_value=1,
                required=True,
            ),
        ),
    ),
    ConfigSectionSpec(
        id="models",
        title="模型映射",
        description="映射 OpenAI / Claude 兼容模型名到上游 Z.AI 实际模型名。",
        fields=(
            _field(
                "GLM45_MODEL",
                "GLM 4.5",
                "标准 GLM 4.5 模型标识。",
                "str",
                "GLM-4.5",
                required=True,
            ),
            _field(
                "GLM45_THINKING_MODEL",
                "GLM 4.5 Thinking",
                "推理增强版 GLM 4.5 模型标识。",
                "str",
                "GLM-4.5-Thinking",
                required=True,
            ),
            _field(
                "GLM45_SEARCH_MODEL",
                "GLM 4.5 Search",
                "搜索增强版 GLM 4.5 模型标识。",
                "str",
                "GLM-4.5-Search",
                required=True,
            ),
            _field(
                "GLM45_AIR_MODEL",
                "GLM 4.5 Air",
                "轻量版 GLM 4.5 模型标识。",
                "str",
                "GLM-4.5-Air",
                required=True,
            ),
            _field(
                "GLM46V_MODEL",
                "GLM 4.6V",
                "视觉模型标识。",
                "str",
                "GLM-4.6V",
                required=True,
            ),
            _field(
                "GLM5_MODEL",
                "GLM 5",
                "GLM 5 模型标识。",
                "str",
                "GLM-5",
                required=True,
            ),
            _field(
                "GLM47_MODEL",
                "GLM 4.7",
                "GLM 4.7 主模型标识。",
                "str",
                "GLM-4.7",
                required=True,
            ),
            _field(
                "GLM47_THINKING_MODEL",
                "GLM 4.7 Thinking",
                "GLM 4.7 推理版模型标识。",
                "str",
                "GLM-4.7-Thinking",
                required=True,
            ),
            _field(
                "GLM47_SEARCH_MODEL",
                "GLM 4.7 Search",
                "GLM 4.7 搜索版模型标识。",
                "str",
                "GLM-4.7-Search",
                required=True,
            ),
            _field(
                "GLM47_ADVANCED_SEARCH_MODEL",
                "GLM 4.7 Advanced Search",
                "GLM 4.7 高级搜索模型标识。",
                "str",
                "GLM-4.7-advanced-search",
                required=True,
                wide=True,
            ),
        ),
    ),
    ConfigSectionSpec(
        id="proxy",
        title="代理与后台安全",
        description="这些字段涉及网络出口与敏感凭证，统一通过环境变量托管。",
        fields=(
            _field(
                "HTTP_PROXY",
                "HTTP 代理",
                "例如 http://127.0.0.1:7890。",
                "str",
                "",
                placeholder="http://127.0.0.1:7890",
                wide=True,
                editable=False,
                storage_kind="env",
            ),
            _field(
                "HTTPS_PROXY",
                "HTTPS 代理",
                "例如 http://127.0.0.1:7890。",
                "str",
                "",
                placeholder="http://127.0.0.1:7890",
                wide=True,
                editable=False,
                storage_kind="env",
            ),
            _field(
                "SOCKS5_PROXY",
                "SOCKS5 代理",
                "例如 socks5://127.0.0.1:1080。",
                "str",
                "",
                placeholder="socks5://127.0.0.1:1080",
                wide=True,
                editable=False,
                storage_kind="env",
            ),
            _field(
                "ADMIN_PASSWORD",
                "后台密码",
                "后台登录密码，仅可通过环境变量配置。",
                "str",
                "admin123",
                input_type="password",
                sensitive=True,
                editable=False,
                storage_kind="env",
            ),
            _field(
                "SESSION_SECRET_KEY",
                "会话密钥",
                "用于后台 Cookie 签名的密钥，仅可通过环境变量配置。",
                "str",
                "",
                input_type="password",
                sensitive=True,
                wide=True,
                editable=False,
                storage_kind="env",
            ),
            _field(
                "CRON_SECRET",
                "Cron 密钥",
                "保护内部维护入口的 Bearer 密钥，仅可通过环境变量配置。",
                "str",
                "",
                input_type="password",
                sensitive=True,
                wide=True,
                editable=False,
                storage_kind="env",
            ),
        ),
    ),
)

CONFIG_FIELD_SPECS = {
    field.key: field
    for section in CONFIG_SECTIONS
    for field in section.fields
}


def read_env_content(*args, **kwargs) -> str:
    """兼容旧入口：数据库配置模式下不再直接编辑 .env。"""
    return "# 当前版本已迁移为数据库运行时配置，不再支持在线编辑 .env。"


def validate_env_source(content: str) -> str:
    """兼容旧入口：不再允许直接保存 .env。"""
    raise ValueError("当前版本已迁移为数据库运行时配置，不再支持直接编辑 .env。")


def _build_source_badge(
    field: ConfigFieldSpec,
    runtime_overrides: Mapping[str, str],
) -> tuple[str, str]:
    if field.storage_kind == "env":
        return (
            "环境变量",
            "bg-blue-50 text-blue-700 ring-blue-200",
        )
    if field.key in runtime_overrides:
        return (
            "数据库",
            "bg-emerald-50 text-emerald-700 ring-emerald-200",
        )
    return (
        "默认值",
        "bg-slate-100 text-slate-600 ring-slate-200",
    )


def build_config_page_data(
    *,
    settings_obj: Any = settings,
    runtime_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    overrides = dict(runtime_overrides or get_runtime_setting_overrides())
    sections: list[dict[str, Any]] = []
    total_fields = 0
    editable_fields = 0
    env_fields = 0
    database_overrides = 0
    sensitive_fields = 0

    for section in CONFIG_SECTIONS:
        rendered_fields: list[dict[str, Any]] = []
        for field in section.fields:
            total_fields += 1
            if field.editable:
                editable_fields += 1
            if field.sensitive:
                sensitive_fields += 1
            if field.storage_kind == "env":
                env_fields += 1
            if field.key in overrides:
                database_overrides += 1

            value = getattr(settings_obj, field.key, field.default_value)
            if value is None:
                value = ""

            source_label, source_badge_class = _build_source_badge(field, overrides)
            rendered_fields.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "description": field.description,
                    "value_type": field.value_type,
                    "value": value,
                    "input_type": field.input_type,
                    "placeholder": field.placeholder,
                    "required": field.required,
                    "wide": field.wide,
                    "sensitive": field.sensitive,
                    "editable": field.editable,
                    "storage_kind": field.storage_kind,
                    "min_value": field.min_value,
                    "max_value": field.max_value,
                    "source_label": source_label,
                    "source_badge_class": source_badge_class,
                }
            )

        sections.append(
            {
                "id": section.id,
                "title": section.title,
                "description": section.description,
                "fields": rendered_fields,
                "field_count": len(rendered_fields),
            }
        )

    return {
        "sections": sections,
        "overview": {
            "total_sections": len(CONFIG_SECTIONS),
            "total_fields": total_fields,
            "editable_fields": editable_fields,
            "readonly_fields": total_fields - editable_fields,
            "database_overrides": database_overrides,
            "default_fields": total_fields - database_overrides - env_fields,
            "env_fields": env_fields,
            "sensitive_fields": sensitive_fields,
            "runtime_storage": "PostgreSQL" if settings_obj.uses_postgres else "SQLite",
            "is_vercel": settings_obj.is_vercel,
        },
    }


def build_form_updates(form_data: Mapping[str, Any]) -> dict[str, object]:
    updates: dict[str, object] = {}

    for key in RUNTIME_MANAGED_KEYS:
        field = CONFIG_FIELD_SPECS[key]
        if not field.editable:
            continue

        if field.value_type == "bool":
            updates[key] = key in form_data
            continue

        raw_value = str(form_data.get(key, "") or "").strip()
        if field.required and raw_value == "":
            raise ValueError(f"{field.label} 不能为空。")

        if field.value_type == "int":
            try:
                parsed = int(raw_value)
            except ValueError as exc:
                raise ValueError(f"{field.label} 必须是整数。") from exc

            if field.min_value is not None and parsed < field.min_value:
                raise ValueError(f"{field.label} 不能小于 {field.min_value}。")
            if field.max_value is not None and parsed > field.max_value:
                raise ValueError(f"{field.label} 不能大于 {field.max_value}。")
            if (
                settings.is_vercel
                and key == "TOKEN_AUTO_MAINTENANCE_INTERVAL"
                and parsed < 300
            ):
                raise ValueError("Vercel 模式下自动维护间隔不能小于 300 秒。")
            updates[key] = parsed
            continue

        updates[key] = raw_value

    return updates


async def save_form_config(
    form_data: Mapping[str, Any],
    *,
    reload_callback,
) -> dict[str, object]:
    updates = build_form_updates(form_data)
    dao = get_runtime_config_dao()
    await dao.upsert_settings(updates)
    await reload_callback()
    return updates


async def save_source_config(*args, **kwargs) -> None:
    raise RuntimeError("当前版本已迁移为数据库运行时配置，不再支持直接编辑 .env。")


async def reset_env_to_example(*args, **kwargs) -> None:
    raise RuntimeError("当前版本已迁移为数据库运行时配置，不再支持重置 .env.example。")
