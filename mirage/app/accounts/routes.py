"""账号 API —— /auth/*（注册/登录/我）+ /billing/*（余额/流水/充值/回调/管理员赠送）。

挂载：main_api `app.include_router(accounts_router, prefix="/api")` → /api/auth/...、/api/billing/...。
鉴权用 deps.current_user；门控关时全部以 dev 用户放行，前端可不接登录也能跑。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from mirage.app.accounts import auth as auth_mod
from mirage.app.accounts import billing
from mirage.app.accounts import deps
from mirage.app.accounts import oauth as oauth_mod
from mirage.app.accounts.store import get_accounts_store
from mirage.app.core.config import settings

router = APIRouter(tags=["accounts"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/register")
async def auth_register(req: RegisterRequest):
    try:
        return auth_mod.register_user(req.email, req.password, req.display_name)
    except auth_mod.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/auth/login")
async def auth_login(req: LoginRequest):
    try:
        return auth_mod.login(req.email, req.password)
    except auth_mod.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/auth/me")
async def auth_me(user: dict = Depends(deps.current_user)):
    return {"user": auth_mod.public_user(user), "auth_enabled": settings.AUTH_ENABLED,
            "billing_enabled": settings.BILLING_ENABLED}


@router.get("/auth/providers")
async def auth_providers():
    """前端用：可用登录方式 + 是否开放注册。无需登录。"""
    return {"local": True, "google": oauth_mod.google_enabled(),
            "register_open": settings.AUTH_ALLOW_REGISTER, "auth_enabled": settings.AUTH_ENABLED}


@router.get("/auth/google/login")
async def auth_google_login(state: str = ""):
    """返回 Google 授权跳转 URL（前端 window.location 跳过去）。"""
    try:
        return {"url": oauth_mod.google_authorize_url(state)}
    except oauth_mod.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/auth/google/callback")
async def auth_google_callback(code: str = "", state: str = ""):
    """Google 回调：换 token → 发我们自己的令牌 → 重定向回前端（URL 带 oauth_token）。"""
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")
    try:
        res = oauth_mod.google_exchange_login(code)
    except oauth_mod.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    base = (settings.FRONTEND_BASE_URL or "").rstrip("/")
    return RedirectResponse(url=f"{base}/?oauth_token={res['token']}")


# ── API Key（第三方对接；需登录管理）────────────────────
class ApiKeyCreate(BaseModel):
    name: str = ""


@router.get("/account/keys")
async def list_keys(user: dict = Depends(deps.current_user)):
    return {"keys": get_accounts_store().list_api_keys(user["id"])}


@router.post("/account/keys")
async def create_key(req: ApiKeyCreate, user: dict = Depends(deps.current_user)):
    """新建 API Key；明文 key 只在此返回一次，请妥善保存。"""
    return get_accounts_store().create_api_key(user["id"], req.name)


@router.delete("/account/keys/{key_id}")
async def revoke_key(key_id: str, user: dict = Depends(deps.current_user)):
    if not get_accounts_store().revoke_api_key(user["id"], key_id):
        raise HTTPException(status_code=404, detail="key 不存在或非本人")
    return {"ok": True}


# ── 计费 ─────────────────────────────────────────────────
class RechargeRequest(BaseModel):
    credits: int
    provider: str = ""


@router.get("/billing/config")
async def billing_config():
    """前端用：是否开计费、可用渠道、各操作积分单价。无需登录。"""
    return {
        "enabled": settings.BILLING_ENABLED,
        "providers": billing.payment_registry.names(),
        "default_provider": settings.BILLING_PROVIDER,
        "costs": {"one_click": billing.cost_of("one_click"),
                  "render_shot": billing.cost_of("render_shot")},
        "price_per_credit": settings.STRIPE_PRICE_PER_CREDIT,
        "currency": settings.BILLING_CURRENCY,
        "signup_bonus": settings.BILLING_SIGNUP_BONUS,
    }


@router.get("/billing/balance")
async def billing_balance(user: dict = Depends(deps.current_user)):
    return {"balance": billing.balance(user["id"]),
            "transactions": get_accounts_store().list_transactions(user["id"], limit=20)}


@router.get("/billing/transactions")
async def billing_transactions(limit: int = 50, user: dict = Depends(deps.current_user)):
    return {"transactions": get_accounts_store().list_transactions(user["id"], limit=min(limit, 200))}


@router.post("/billing/recharge")
async def billing_recharge(req: RechargeRequest, user: dict = Depends(deps.current_user)):
    try:
        return billing.create_recharge(user["id"], req.credits, req.provider)
    except billing.BillingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/billing/recharge/callback/{provider}")
async def billing_recharge_callback(provider: str, request: Request):
    """支付渠道异步回调（webhook）。验签在各 PaymentProvider.verify_callback 里做。"""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    try:
        return billing.confirm_recharge(provider, payload, dict(request.headers))
    except billing.BillingError as e:
        raise HTTPException(status_code=400, detail=str(e))


class GrantRequest(BaseModel):
    user_id: str = ""
    email: str = ""
    credits: int = 0
    reason: str = "管理员赠送"


@router.post("/billing/admin/grant")
async def billing_admin_grant(req: GrantRequest, _admin: dict = Depends(deps.require_admin)):
    st = get_accounts_store()
    target = None
    if req.user_id:
        target = st.get_user(req.user_id)
    elif req.email:
        target = st.get_user_by_email(req.email)
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    try:
        return billing.grant(target["id"], int(req.credits), req.reason)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
