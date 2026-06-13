"""
对外公开 API 的轻量鉴权（预留口子）。

现在的形态：API-Key 白名单从配置读（settings.PUBLIC_API_KEYS，逗号分隔）。
- 没配 key（默认）→ **放行**，并把 user_id 记为 "default"。单用户/开发态完全无感。
- 配了 key → 请求头 `X-API-Key` 必须命中白名单，否则 401。

将来填实：把 key→user_id 的映射改成查库/密钥服务，require_api_key 返回真实 user_id，
下游据此做多租户隔离（见 store/runtime 的 user_id TODO）。这里只锁定"鉴权发生在哪、返回什么"。
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from mirage.app.core.config import settings


def _configured_keys() -> set[str]:
    return {k.strip() for k in (settings.PUBLIC_API_KEYS or "").split(",") if k.strip()}


async def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """对外 API 依赖：校验 X-API-Key，返回 user_id（占位：未接账号体系时统一为 'default'）。

    没配 PUBLIC_API_KEYS 时直接放行（返回 'default'），不影响现有单用户使用。
    """
    keys = _configured_keys()
    if not keys:
        return "default"                       # 未启用鉴权 → 放行
    if not x_api_key or x_api_key not in keys:
        raise HTTPException(status_code=401, detail="无效或缺失的 X-API-Key")
    # TODO(toC): 这里把 key 映射成真实 user_id（查库/密钥服务）；现先用 key 本身当租户标识占位
    return x_api_key
