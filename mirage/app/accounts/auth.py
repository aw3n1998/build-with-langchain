"""用户认证 —— 可插拔 AuthProvider 注册表（local 默认；OAuth/微信/手机号加一个文件即可接入）+ 高层服务。

与 tts_providers 同款热插拔：新增认证后端 = 写一个 AuthProvider 子类 + register 一行。
core 不依赖本模块；路由层 deps.current_user 用 authenticate_token 解析令牌取用户。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from mirage.app.accounts import security
from mirage.app.accounts.store import get_accounts_store
from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("accounts.auth")


class AuthError(Exception):
    """认证/注册业务错误（路由层转 4xx）。"""


class AuthProvider(ABC):
    name: str = ""
    can_register: bool = False

    @abstractmethod
    def login(self, **credentials) -> Optional[dict]:
        """凭据 → 用户 dict 或 None。"""
        raise NotImplementedError

    def register(self, **data) -> dict:
        raise AuthError(f"{self.name} 不支持自助注册")


class _AuthRegistry:
    def __init__(self) -> None:
        self._p: dict[str, AuthProvider] = {}
        self._default: Optional[str] = None

    def register(self, prov: AuthProvider, *, default: bool = False) -> None:
        self._p[prov.name] = prov
        if default or self._default is None:
            self._default = prov.name
        logger.info("[auth] 注册认证后端 %s（default=%s）", prov.name, default)

    def get(self, name: str = "") -> Optional[AuthProvider]:
        return self._p.get(name or (self._default or ""))

    @property
    def default_name(self) -> str:
        return self._default or ""


auth_registry = _AuthRegistry()


class LocalAuthProvider(AuthProvider):
    """本地账号：邮箱 + 密码（PBKDF2）。"""

    name = "local"
    can_register = True

    def login(self, *, email: str = "", password: str = "", **_) -> Optional[dict]:
        u = get_accounts_store().get_user_by_email(email)
        if not u or u.get("status") != "active":
            return None
        if not security.verify_password(password, u.get("password_hash") or ""):
            return None
        return u

    def register(self, *, email: str = "", password: str = "", display_name: str = "", **_) -> dict:
        em = (email or "").strip().lower()
        if not em or "@" not in em:
            raise AuthError("邮箱格式不正确")
        if len(password or "") < 6:
            raise AuthError("密码至少 6 位")
        st = get_accounts_store()
        if st.get_user_by_email(em):
            raise AuthError("该邮箱已注册")
        # 首个注册用户自动设为 admin（无人值守初始化）。
        role = "admin" if st.count_users() == 0 else "user"
        u = st.create_user(em, security.hash_password(password), display_name,
                           role=role, auth_provider="local")
        bonus = int(settings.BILLING_SIGNUP_BONUS or 0)   # 注册赠送积分（直接走 store，不耦合 billing 服务）
        if bonus > 0:
            try:
                st.adjust_balance(u["id"], bonus, type="grant", reason="注册赠送")
            except Exception:  # noqa: BLE001
                pass
        return st.get_user(u["id"])


auth_registry.register(LocalAuthProvider(), default=True)


# ── 服务层 ────────────────────────────────────────────────
def public_user(u: dict) -> dict:
    """脱敏用户视图（去掉 password_hash 等敏感字段）。"""
    return {k: u.get(k) for k in ("id", "email", "display_name", "role", "status",
                                  "balance", "auth_provider", "created_at")}


def register_user(email: str, password: str, display_name: str = "", provider: str = "") -> dict:
    if not settings.AUTH_ALLOW_REGISTER:
        raise AuthError("已关闭自助注册，请联系管理员开通")
    prov = auth_registry.get(provider or "local")
    if prov is None or not prov.can_register:
        raise AuthError("当前认证后端不支持注册")
    u = prov.register(email=email, password=password, display_name=display_name)
    return {"token": security.make_token(u["id"]), "user": public_user(u)}


def login(email: str, password: str, provider: str = "") -> dict:
    prov = auth_registry.get(provider or "")
    if prov is None:
        raise AuthError("认证后端不可用")
    u = prov.login(email=email, password=password)
    if not u:
        raise AuthError("邮箱或密码错误")
    return {"token": security.make_token(u["id"]), "user": public_user(u)}


def authenticate_token(token: str) -> Optional[dict]:
    """令牌 → 用户 dict（含 balance/role）或 None。"""
    uid = security.verify_token(token)
    if not uid:
        return None
    u = get_accounts_store().get_user(uid)
    if not u or u.get("status") != "active":
        return None
    return u
