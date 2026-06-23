"""FastAPI 依赖 —— 鉴权 + 计费守卫。这是【唯一】把账号/计费接进 API 的地方，核心管线不碰。

门控休眠零回归：
- AUTH_ENABLED=false → current_user 返回内置 dev 用户（开放访问，等于现有单用户开发态）。
- BILLING_ENABLED=false → ensure_credits / charge_quietly 全 no-op（免费）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request

from mirage.app.accounts import auth as auth_mod
from mirage.app.accounts import billing
from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("accounts.deps")

# 关闭鉴权时的内置开发者用户（管理员、余额充裕）——让现有面板免登录直接用。
_DEV_USER = {"id": "dev", "email": "dev@local", "display_name": "开发者", "role": "admin",
             "status": "active", "balance": 10 ** 9, "auth_provider": "dev"}


def _token_from(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-Auth-Token") or "").strip()


def _user_from_request(request: Request) -> Optional[dict]:
    token = _token_from(request)
    return auth_mod.authenticate_token(token) if token else None


async def current_user(request: Request) -> dict:
    """要求已登录（AUTH 开启时）。关闭时返回 dev 用户。"""
    if not settings.AUTH_ENABLED:
        return _DEV_USER
    u = _user_from_request(request)
    if not u:
        raise HTTPException(status_code=401, detail="未登录或令牌无效，请先登录")
    return u


async def optional_user(request: Request) -> dict:
    """尽力取用户（取不到也不报错，用于公开页/可选登录）。"""
    if not settings.AUTH_ENABLED:
        return _DEV_USER
    return _user_from_request(request) or {}


def require_admin(user: dict = Depends(current_user)) -> dict:
    if (user or {}).get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def ensure_credits(user: dict, op: str, **ctx) -> None:
    """计费门控：余额不足直接 402（在下发 GPU 任务【之前】调，省算力）。BILLING 关=放行。"""
    if not settings.BILLING_ENABLED:
        return
    if not billing.can_afford(user["id"], op=op, **ctx):
        need = billing.cost_of(op, **ctx)
        raise HTTPException(status_code=402,
                            detail=f"积分不足：「{op}」需 {need} 积分，当前余额 {billing.balance(user['id'])}。请先充值。")


def charge_quietly(user: dict, op: str, ref: str = "", **ctx) -> None:
    """任务下发后扣费（已 ensure_credits 预检，这里失败只记日志、不回滚响应）。BILLING 关=no-op。"""
    if not settings.BILLING_ENABLED:
        return
    try:
        billing.charge(user["id"], op=op, ref=ref, **ctx)
    except Exception as e:  # noqa: BLE001
        logger.warning("[billing] 扣费失败 user=%s op=%s: %s", (user or {}).get("id"), op, e)
