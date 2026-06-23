"""第三方 OAuth 登录 —— Google（可插拔；GitHub/微信同款套路加一个文件即接入）。

配 GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET 才启用。流程：
  前端跳 google_authorize_url() → 用户在 Google 授权 → 回调 redirect_uri 带 code
  → google_exchange_login(code) 换 token + 拉用户信息 → 找/建用户 → 发我们自己的签名令牌。
统一落到同一套 users 表 + 令牌，与 local 邮箱密码并存（auth_provider 区分）。
"""
from __future__ import annotations

import urllib.parse

from mirage.app.accounts import security
from mirage.app.accounts.store import get_accounts_store
from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("accounts.oauth")

_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


class OAuthError(Exception):
    """OAuth 业务错误。"""


def google_enabled() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _redirect_uri() -> str:
    if settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI
    base = (settings.FRONTEND_BASE_URL or "").rstrip("/")
    return f"{base}/api/auth/google/callback" if base else ""


def google_authorize_url(state: str = "") -> str:
    if not google_enabled():
        raise OAuthError("未配置 Google OAuth（GOOGLE_CLIENT_ID/SECRET）")
    q = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state or "",
    }
    return _GOOGLE_AUTH + "?" + urllib.parse.urlencode(q)


def google_exchange_login(code: str) -> dict:
    """授权码 code → tokens → userinfo → 找/建用户 → {token, user}。"""
    import httpx
    if not google_enabled():
        raise OAuthError("未配置 Google OAuth")
    tr = httpx.post(_GOOGLE_TOKEN, data={
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }, timeout=20)
    if tr.status_code >= 300:
        raise OAuthError(f"Google 换取 token 失败: {tr.text[:200]}")
    access = (tr.json() or {}).get("access_token")
    if not access:
        raise OAuthError("Google 未返回 access_token")
    ur = httpx.get(_GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"}, timeout=20)
    if ur.status_code >= 300:
        raise OAuthError(f"Google 获取用户信息失败: {ur.text[:200]}")
    info = ur.json() or {}
    sub = info.get("sub")
    email = (info.get("email") or "").strip().lower()
    name = info.get("name") or (email.split("@")[0] if email else "Google 用户")
    if not sub:
        raise OAuthError("Google 用户信息缺 sub")
    st = get_accounts_store()
    u = st.get_user_by_ext("google", sub) or (st.get_user_by_email(email) if email else None)
    if not u:
        role = "admin" if st.count_users() == 0 else "user"
        u = st.create_user(email or f"{sub}@google.local", "", name,
                           role=role, auth_provider="google", ext_id=sub)
        bonus = int(settings.BILLING_SIGNUP_BONUS or 0)
        if bonus > 0:
            try:
                st.adjust_balance(u["id"], bonus, type="grant", reason="Google 注册赠送")
            except Exception:  # noqa: BLE001
                pass
    from mirage.app.accounts.auth import public_user
    return {"token": security.make_token(u["id"]), "user": public_user(u)}
