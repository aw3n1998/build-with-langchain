"""账号/计费存储 —— 全局 SQLite（用户跨工作目录共用，不放 per-workspace 状态库）。

两张表：users（账号 + 积分余额）、transactions（流水账，每笔充值/扣费/赠送可审计）。
余额调整 adjust_balance 是【原子】的：同一把锁 + 单连接里 读余额→校验→更新→记流水，
扣减不足直接抛 ValueError；充值用 ref 幂等（同一支付单号不重复入账）。

auth.py / billing.py 在它之上提供解耦的服务，本文件只管存储、不认识"认证""支付"概念。
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Optional

from mirage.app.core.config import settings
from mirage.app.core.logger import get_logger

logger = get_logger("accounts.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    display_name  TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'user',     -- user / admin
    status        TEXT NOT NULL DEFAULT 'active',    -- active / disabled
    balance       INTEGER NOT NULL DEFAULT 0,        -- 积分余额（整数）
    auth_provider TEXT NOT NULL DEFAULT 'local',     -- local / wechat / oauth_*
    ext_id        TEXT NOT NULL DEFAULT '',          -- 外部账号 id（OAuth/微信 openid）
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_ext   ON users(auth_provider, ext_id);

CREATE TABLE IF NOT EXISTS transactions (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    type          TEXT NOT NULL,            -- recharge / charge / refund / grant
    amount        INTEGER NOT NULL,          -- 正=入账，负=扣减
    balance_after INTEGER NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',  -- 支付渠道（recharge 时）
    ref           TEXT NOT NULL DEFAULT '',  -- 支付单号/外部引用（幂等键）
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_tx_ref  ON transactions(provider, ref);

CREATE TABLE IF NOT EXISTS api_keys (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    key_hash   TEXT UNIQUE NOT NULL,      -- sha256(明文key)，明文只在创建时返回一次
    prefix     TEXT NOT NULL DEFAULT '',  -- 前缀（列表展示用，如 mk_xxxx…）
    name       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',
    last_used  TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_apikeys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_apikeys_user ON api_keys(user_id);
"""


def _hash_key(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _uid() -> str:
    return uuid.uuid4().hex


class AccountsStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        with self._lock, self._conn() as conn:
            conn.executescript(_SCHEMA)
        logger.info("[accounts] 账号库就绪: %s", db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    # ── 用户 ─────────────────────────────────────────────
    def create_user(self, email: str, password_hash: str = "", display_name: str = "",
                    role: str = "user", auth_provider: str = "local", ext_id: str = "") -> dict:
        uid, ts = _uid(), _now()
        em = (email or "").strip().lower()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO users(id,email,password_hash,display_name,role,auth_provider,ext_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (uid, em, password_hash, display_name or (em.split("@")[0] if em else "用户"),
                 role, auth_provider, ext_id, ts, ts),
            )
        return self.get_user(uid)

    def get_user(self, user_id: str) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(r) if r else None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()
        return dict(r) if r else None

    def get_user_by_ext(self, provider: str, ext_id: str) -> Optional[dict]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM users WHERE auth_provider=? AND ext_id=?",
                             (provider, ext_id)).fetchone()
        return dict(r) if r else None

    def set_user_fields(self, user_id: str, **fields) -> Optional[dict]:
        allowed = {"display_name", "role", "status", "password_hash"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return self.get_user(user_id)
        cols = ", ".join(f"{k}=?" for k in sets) + ", updated_at=?"
        with self._lock, self._conn() as conn:
            conn.execute(f"UPDATE users SET {cols} WHERE id=?",
                         (*sets.values(), _now(), user_id))
        return self.get_user(user_id)

    # ── 余额 + 流水（原子）─────────────────────────────────
    def find_tx_by_ref(self, provider: str, ref: str) -> Optional[dict]:
        if not ref:
            return None
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM transactions WHERE provider=? AND ref=? LIMIT 1",
                             (provider, ref)).fetchone()
        return dict(r) if r else None

    def adjust_balance(self, user_id: str, delta: int, *, type: str, reason: str = "",
                       provider: str = "", ref: str = "") -> dict:
        """原子调整余额 + 记一条流水。delta<0 余额不足 → 抛 ValueError。返回 {balance, tx_id}。"""
        delta = int(delta)
        with self._lock, self._conn() as conn:
            r = conn.execute("SELECT balance FROM users WHERE id=?", (user_id,)).fetchone()
            if not r:
                raise ValueError(f"用户不存在: {user_id}")
            new = int(r["balance"]) + delta
            if new < 0:
                raise ValueError(f"余额不足：当前 {int(r['balance'])}，需扣 {-delta}")
            ts, txid = _now(), _uid()
            conn.execute("UPDATE users SET balance=?, updated_at=? WHERE id=?", (new, ts, user_id))
            conn.execute(
                """INSERT INTO transactions(id,user_id,type,amount,balance_after,reason,provider,ref,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (txid, user_id, type, delta, new, reason, provider, ref, ts),
            )
        return {"balance": new, "tx_id": txid}

    def list_transactions(self, user_id: str, limit: int = 50) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (user_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_users(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    # ── API Key（第三方对接，绑用户）─────────────────────
    def create_api_key(self, user_id: str, name: str = "") -> dict:
        """生成一把 API Key，存其 sha256；明文 key 只在这里返回一次（后端不再可读）。"""
        raw = "mk_" + secrets.token_urlsafe(32)
        kid, ts, prefix = _uid(), _now(), "mk_" + raw[3:9]
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO api_keys(id,user_id,key_hash,prefix,name,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (kid, user_id, _hash_key(raw), prefix, name or "key", ts),
            )
        return {"id": kid, "key": raw, "prefix": prefix, "name": name or "key", "created_at": ts}

    def list_api_keys(self, user_id: str) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id,prefix,name,status,last_used,created_at FROM api_keys
                   WHERE user_id=? AND status='active' ORDER BY created_at DESC""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def revoke_api_key(self, user_id: str, key_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("UPDATE api_keys SET status='revoked' WHERE id=? AND user_id=?",
                               (key_id, user_id))
        return cur.rowcount > 0

    def get_user_by_api_key(self, raw_key: str) -> Optional[dict]:
        """API Key 明文 → 该 key 所属用户（active）。顺带更新 last_used。无效→None。"""
        if not raw_key:
            return None
        kh = _hash_key(raw_key)
        with self._lock, self._conn() as conn:
            r = conn.execute("SELECT user_id FROM api_keys WHERE key_hash=? AND status='active'",
                             (kh,)).fetchone()
            if not r:
                return None
            conn.execute("UPDATE api_keys SET last_used=? WHERE key_hash=?", (_now(), kh))
            u = conn.execute("SELECT * FROM users WHERE id=?", (r["user_id"],)).fetchone()
        return dict(u) if u else None


_store: Optional[AccountsStore] = None
_store_lock = threading.Lock()


def get_accounts_store() -> AccountsStore:
    """全局账号库单例（懒加载）。路径：ACCOUNTS_DB_PATH，空则放 pipeline.db 同目录的 accounts.db。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                path = (settings.ACCOUNTS_DB_PATH or "").strip()
                if not path:
                    base = settings.NP2V_DB_PATH or "./mirage_workspace/.agent/pipeline.db"
                    path = os.path.join(os.path.dirname(os.path.abspath(base)), "accounts.db")
                _store = AccountsStore(path)
    return _store
