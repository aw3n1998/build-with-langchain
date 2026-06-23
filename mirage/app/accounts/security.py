"""账号安全原语：密码哈希(PBKDF2) + 签名令牌(HMAC)。纯 stdlib，不引第三方依赖。

- 密码：pbkdf2_hmac(sha256) + 每用户随机盐，格式 `pbkdf2_sha256$rounds$salt_b64$hash_b64`。
- 令牌：HMAC-SHA256 签名的 `body.sig`（body=base64(json{uid,exp})），自带过期，无需服务端会话表。
  生产务必设强随机 AUTH_SECRET（否则用开发占位密钥，令牌可被伪造）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from mirage.app.core.config import settings

_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, _ROUNDS)
    return f"pbkdf2_sha256${_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, dk_b64 = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(dk, expected)
    except Exception:  # noqa: BLE001
        return False


def _secret() -> bytes:
    return (settings.AUTH_SECRET or "mirage-dev-secret-change-me").encode("utf-8")


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: str, ttl: int = 0) -> str:
    ttl = int(ttl or settings.AUTH_TOKEN_TTL or 604800)
    body = _b64u(json.dumps({"uid": user_id, "exp": int(time.time()) + ttl},
                            separators=(",", ":")).encode("utf-8"))
    sig = _b64u(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> str | None:
    """验签 + 查过期 → 返回 user_id；无效/过期 → None。"""
    try:
        body, sig = (token or "").split(".")
        expected = _b64u(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64u_dec(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload.get("uid") or None
    except Exception:  # noqa: BLE001
        return None
