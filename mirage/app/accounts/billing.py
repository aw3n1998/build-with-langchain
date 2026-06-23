"""充值/计费 —— 可插拔 PaymentProvider 注册表（mock 默认；Stripe/微信支付/支付宝门控接入）+ 计费服务。

解耦三点：
- 支付渠道可插拔：加渠道 = 写一个 PaymentProvider 子类 + register；BILLING_PROVIDER 选当前默认渠道。
- 核心管线零依赖：扣费只发生在【路由层】（deps.require_credits / charge），pipeline/* 不 import 本模块。
- 门控休眠零回归：BILLING_ENABLED=false → can_afford 恒 True、charge no-op（免费，等于现有开发态）。

积分(credits) = 整数。cost_of(op) 把"一次操作"换算成要扣的积分（env 可配）。
充值幂等：同一支付单号(provider+ref)只入账一次。
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional

from mirage.app.accounts.store import get_accounts_store
from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("accounts.billing")


class BillingError(Exception):
    """计费/支付业务错误（路由层转 4xx/402）。"""


# ── 支付渠道（可插拔）────────────────────────────────────────
class PaymentProvider(ABC):
    name: str = ""

    @abstractmethod
    def create_order(self, *, user_id: str, credits: int, amount_cents: int, **kw) -> dict:
        """下单。返回 {order_id, paid(bool 是否已即时到账), pay_url(跳转支付页), ...}。"""
        raise NotImplementedError

    def verify_callback(self, payload: dict, headers: dict) -> Optional[dict]:
        """支付回调验真 → {user_id, credits, ref, paid} 或 None（未支付/验签失败）。"""
        return None


class _PaymentRegistry:
    def __init__(self) -> None:
        self._p: dict[str, PaymentProvider] = {}
        self._default: Optional[str] = None

    def register(self, prov: PaymentProvider, *, default: bool = False) -> None:
        self._p[prov.name] = prov
        if default or self._default is None:
            self._default = prov.name
        logger.info("[billing] 注册支付渠道 %s（default=%s）", prov.name, default)

    def get(self, name: str = "") -> Optional[PaymentProvider]:
        return self._p.get(name or (self._default or ""))

    def names(self) -> list:
        return list(self._p.keys())


payment_registry = _PaymentRegistry()


class MockPaymentProvider(PaymentProvider):
    """开发/测试渠道：下单即到账（不接真支付）。用来跑通充值→扣费闭环。"""

    name = "mock"

    def create_order(self, *, user_id: str, credits: int, amount_cents: int, **kw) -> dict:
        return {"order_id": "mock_" + uuid.uuid4().hex[:16], "paid": True, "pay_url": "",
                "note": "mock 渠道：积分立即到账（仅开发/测试，勿用于生产）"}

    def verify_callback(self, payload: dict, headers: dict) -> Optional[dict]:
        return {"user_id": payload.get("user_id"), "credits": int(payload.get("credits") or 0),
                "ref": payload.get("order_id") or "", "paid": True}


class StripeProvider(PaymentProvider):
    """Stripe Checkout（国际信用卡）。配 STRIPE_SECRET_KEY 才注册。
    下单 → 返回 Checkout 跳转 url；用户付款后 Stripe webhook 回调 → confirm_recharge 入账。
    ★webhook 验签需 raw body + STRIPE_WEBHOOK_SECRET，生产务必按 Stripe 文档校验（此处给框架）。"""

    name = "stripe"

    def create_order(self, *, user_id: str, credits: int, amount_cents: int, **kw) -> dict:
        import httpx
        key = settings.STRIPE_SECRET_KEY
        if not key:
            raise BillingError("未配置 STRIPE_SECRET_KEY")
        cur = (settings.BILLING_CURRENCY or "usd").lower()
        base = (settings.FRONTEND_BASE_URL or "").rstrip("/")
        data = {
            "mode": "payment",
            "success_url": f"{base}/billing?status=ok" if base else "https://example.com/ok",
            "cancel_url": f"{base}/billing?status=cancel" if base else "https://example.com/cancel",
            "line_items[0][price_data][currency]": cur,
            "line_items[0][price_data][product_data][name]": f"{credits} 积分",
            "line_items[0][price_data][unit_amount]": str(int(amount_cents)),
            "line_items[0][quantity]": "1",
            "metadata[user_id]": user_id,
            "metadata[credits]": str(int(credits)),
        }
        r = httpx.post("https://api.stripe.com/v1/checkout/sessions", data=data,
                       auth=(key, ""), timeout=20)
        j = r.json() if r.content else {}
        if r.status_code >= 300:
            raise BillingError(f"Stripe 下单失败: {(j.get('error') or {}).get('message') or r.status_code}")
        return {"order_id": j.get("id"), "paid": False, "pay_url": j.get("url")}

    def verify_callback(self, payload: dict, headers: dict) -> Optional[dict]:
        # TODO(生产)：用 STRIPE_WEBHOOK_SECRET + Stripe-Signature 头 + raw body 验签防伪造/重放。
        ev = payload if isinstance(payload, dict) else {}
        if ev.get("type") != "checkout.session.completed":
            return None
        obj = (ev.get("data") or {}).get("object") or {}
        if obj.get("payment_status") != "paid":
            return None
        md = obj.get("metadata") or {}
        return {"user_id": md.get("user_id"), "credits": int(md.get("credits") or 0),
                "ref": obj.get("id"), "paid": True}


payment_registry.register(MockPaymentProvider(), default=True)
if settings.STRIPE_SECRET_KEY:
    payment_registry.register(StripeProvider(), default=(settings.BILLING_PROVIDER == "stripe"))


# ── 计费服务 ────────────────────────────────────────────────
def cost_of(op: str, **ctx) -> int:
    """一次操作要扣多少积分（env 可配）。batch_finish 可按镜数 ctx['shots'] 计。"""
    table = {
        "one_click": int(settings.BILLING_COST_ONECLICK or 0),
        "render_shot": int(settings.BILLING_COST_RENDER_SHOT or 0),
        "batch_finish": int(settings.BILLING_COST_BATCH_FINISH or 0),
    }
    base = table.get(op, 0)
    if op == "batch_finish" and base == 0 and ctx.get("shots"):
        return int(settings.BILLING_COST_RENDER_SHOT or 0) * int(ctx["shots"])
    return base


def balance(user_id: str) -> int:
    u = get_accounts_store().get_user(user_id)
    return int(u["balance"]) if u else 0


def can_afford(user_id: str, op: str = "", credits: int = 0, **ctx) -> bool:
    if not settings.BILLING_ENABLED:
        return True
    amount = int(credits or cost_of(op, **ctx))
    return amount <= 0 or balance(user_id) >= amount


def charge(user_id: str, op: str = "", credits: int = 0, reason: str = "", ref: str = "", **ctx) -> dict:
    """扣费（门控关=no-op）。余额不足抛 BillingError（路由层转 402）。"""
    if not settings.BILLING_ENABLED:
        return {"charged": 0, "skipped": "billing_off"}
    amount = int(credits or cost_of(op, **ctx))
    if amount <= 0:
        return {"charged": 0, "balance": balance(user_id)}
    try:
        r = get_accounts_store().adjust_balance(user_id, -amount, type="charge",
                                                reason=reason or op, ref=ref)
    except ValueError as e:
        raise BillingError(str(e))
    return {"charged": amount, "balance": r["balance"], "tx_id": r["tx_id"]}


def grant(user_id: str, credits: int, reason: str = "管理员赠送") -> dict:
    r = get_accounts_store().adjust_balance(user_id, int(credits), type="grant", reason=reason)
    return {"balance": r["balance"], "tx_id": r["tx_id"]}


def _credit(user_id: str, credits: int, *, provider: str, ref: str, reason: str) -> int:
    st = get_accounts_store()
    if ref and st.find_tx_by_ref(provider, ref):   # 幂等：同一支付单不重复入账
        u = st.get_user(user_id)
        return int(u["balance"]) if u else 0
    return st.adjust_balance(user_id, int(credits), type="recharge",
                             reason=reason, provider=provider, ref=ref)["balance"]


def create_recharge(user_id: str, credits: int, provider: str = "") -> dict:
    """发起充值下单。mock 立即到账；Stripe 等返回 pay_url 等回调入账。"""
    credits = int(credits)
    if credits <= 0:
        raise BillingError("充值积分必须为正")
    prov = payment_registry.get(provider or settings.BILLING_PROVIDER or "mock")
    if prov is None:
        raise BillingError(f"支付渠道不可用: {provider or settings.BILLING_PROVIDER}")
    amount_cents = round(credits * float(settings.STRIPE_PRICE_PER_CREDIT or 0.01) * 100)
    order = prov.create_order(user_id=user_id, credits=credits, amount_cents=int(amount_cents))
    out = {"provider": prov.name, "credits": credits, **order}
    if order.get("paid"):   # mock：即时到账
        out["balance"] = _credit(user_id, credits, provider=prov.name,
                                 ref=order.get("order_id") or "", reason="充值")
    return out


def confirm_recharge(provider: str, payload: dict, headers: dict | None = None) -> dict:
    prov = payment_registry.get(provider)
    if prov is None:
        raise BillingError(f"未知支付渠道: {provider}")
    res = prov.verify_callback(payload or {}, headers or {})
    if not res or not res.get("paid"):
        raise BillingError("支付未确认或验签失败")
    bal = _credit(res["user_id"], int(res["credits"]), provider=provider,
                  ref=res.get("ref") or "", reason="充值")
    return {"ok": True, "balance": bal}
