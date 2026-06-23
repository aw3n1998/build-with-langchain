"""FastAPI 依赖 —— 鉴权 + 计费守卫。这是【唯一】把账号/计费接进 API 的地方，核心管线不碰。

门控休眠零回归：
- AUTH_ENABLED=false → current_user 返回内置 dev 用户（开放访问，等于现有单用户开发态）。
- BILLING_ENABLED=false → ensure_credits / charge_quietly 全 no-op（免费）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

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


def _bind_ws(u: dict) -> dict:
    """把用户绑到 runtime 上下文 → set_workspace 自动用其专属目录（每个用户单独工作目录）。"""
    try:
        from mirage.app.pipeline.runtime import bind_user
        bind_user((u or {}).get("id"))
    except Exception:  # noqa: BLE001
        pass
    return u


async def current_user(request: Request) -> dict:
    """要求已登录（AUTH 开启时）。关闭时返回 dev 用户。★顺带把用户绑到 runtime → 每个用户单独工作目录。"""
    if not settings.AUTH_ENABLED:
        return _DEV_USER
    u = _user_from_request(request)
    if not u:
        raise HTTPException(status_code=401, detail="未登录或令牌无效，请先登录")
    return _bind_ws(u)


async def optional_user(request: Request) -> dict:
    """尽力取用户（取不到也不报错，用于公开页/可选登录）。"""
    if not settings.AUTH_ENABLED:
        return _DEV_USER
    return _bind_ws(_user_from_request(request) or {})


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


# ── 第三方 API 鉴权（X-API-Key）——填实 core.auth 的 key→user TODO ──
def api_key_user(x_api_key: str = Header(default=None)) -> dict:
    """X-API-Key → 绑定的用户 dict。优先查【用户绑定 key】(accounts.api_keys)；
    回退兼容 env 白名单 PUBLIC_API_KEYS（命中/未配=放行 dev 用户），否则 401。"""
    raw = (x_api_key or "").strip()
    if raw:
        from mirage.app.accounts.store import get_accounts_store
        u = get_accounts_store().get_user_by_api_key(raw)
        if u:
            return u
    keys = {k.strip() for k in (settings.PUBLIC_API_KEYS or "").split(",") if k.strip()}
    if not keys:                       # 未配任何 key → 放行（向后兼容单用户）
        return _DEV_USER
    if raw and raw in keys:
        return _DEV_USER
    raise HTTPException(status_code=401, detail="无效或缺失的 X-API-Key")


def api_key_user_id(user: dict = Depends(api_key_user)) -> str:
    """只取 user_id（兼容 v1_public 旧签名 `user_id: str = Depends(require_api_key)`）。"""
    return user.get("id") or "default"
