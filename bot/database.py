"""
SQLite слой для VPN-сервиса.

Таблицы: users, otp_codes, telegram_whitelist, web_sessions.
Автоматически мигрирует данные из users.json при первом запуске.
"""

import json
import logging
import pathlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

_BASE_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = _BASE_DIR / "data"
DB_PATH = DATA_DIR / "vpn.db"
USERS_JSON_PATH = DATA_DIR / "users.json"

_db_initialized = False


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ─── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id          INTEGER UNIQUE,
    email                TEXT UNIQUE,
    username             TEXT,
    role                 TEXT NOT NULL DEFAULT 'user',
    active               INTEGER NOT NULL DEFAULT 1,
    preferred_server_id  TEXT DEFAULT 'eu1',
    preferred_profile_type TEXT,
    email_verified       INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS servers (
    id          TEXT PRIMARY KEY,                  -- 'eu1', 'eu2', ...
    name        TEXT NOT NULL DEFAULT '',          -- human-readable label
    protocol    TEXT NOT NULL DEFAULT 'vless',     -- 'vless' | 'awg'
    capacity    INTEGER NOT NULL DEFAULT 100,      -- max users on this server
    active      INTEGER NOT NULL DEFAULT 1         -- 0 = offline / maintenance
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL,
    code        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS telegram_whitelist (
    telegram_id INTEGER PRIMARY KEY,
    note        TEXT DEFAULT '',
    added_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS web_sessions (
    token       TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);
"""


def init_db(whitelist_seed: Optional[List[int]] = None) -> None:
    """
    Создаёт таблицы и мигрирует users.json → SQLite (идемпотентно).
    whitelist_seed — список telegram_id из env (TELEGRAM_ID_WHITELIST),
    которые добавляются в whitelist при первой инициализации.
    """
    global _db_initialized
    with _conn() as con:
        con.executescript(_SCHEMA)
    _migrate_from_json()
    _migrate_add_vless_columns()
    _migrate_add_servers_table()
    if whitelist_seed:
        _seed_whitelist(whitelist_seed)
    _db_initialized = True


def _migrate_add_servers_table() -> None:
    """
    Идемпотентная миграция: создаёт таблицу servers (если нет) и засевает
    eu1 — единственный активный сервер на текущем этапе.
    Вызывается из init_db() после создания основных таблиц.
    """
    with _conn() as con:
        # Таблица уже создана через _SCHEMA — просто сеем начальные данные.
        count = con.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
        if count == 0:
            con.execute(
                """
                INSERT OR IGNORE INTO servers (id, name, protocol, capacity, active)
                VALUES
                    ('eu1', 'Fornex eu1 (Germany)', 'vless', 500, 1),
                    ('eu1-awg', 'Fornex eu1 — AmneziaWG', 'awg', 500, 1)
                """
            )
            logger.info("Migration: seeded servers table with eu1 (vless + awg)")


def _migrate_add_vless_columns() -> None:
    """Добавляет VLESS-поля в таблицу users (идемпотентно)."""
    with _conn() as con:
        existing = {
            row[1]
            for row in con.execute("PRAGMA table_info(users)").fetchall()
        }
        if "vless_uuid" not in existing:
            con.execute("ALTER TABLE users ADD COLUMN vless_uuid TEXT")
            logger.info("Migration: added vless_uuid column to users")
        if "vless_short_id" not in existing:
            con.execute("ALTER TABLE users ADD COLUMN vless_short_id TEXT")
            logger.info("Migration: added vless_short_id column to users")


def _ensure_init() -> None:
    if not _db_initialized:
        init_db()


def _migrate_from_json() -> None:
    """Переносит users.json → SQLite. Пропускает уже существующие записи."""
    if not USERS_JSON_PATH.exists():
        return
    try:
        data = json.loads(USERS_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Не удалось прочитать users.json для миграции: %s", e)
        return
    if not data:
        return
    migrated = 0
    with _conn() as con:
        for key, payload in data.items():
            try:
                tid = int(payload.get("telegram_id", key))
            except (ValueError, TypeError):
                continue
            existing = con.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (tid,)
            ).fetchone()
            if existing:
                continue
            con.execute(
                """
                INSERT OR IGNORE INTO users
                    (telegram_id, email, username, role, active,
                     preferred_server_id, preferred_profile_type, email_verified)
                VALUES (?, NULL, ?, ?, ?, ?, ?, 0)
                """,
                (
                    tid,
                    payload.get("username"),
                    payload.get("role", "user"),
                    1 if payload.get("active", True) else 0,
                    payload.get("preferred_server_id"),
                    payload.get("preferred_profile_type"),
                ),
            )
            migrated += 1
    if migrated:
        logger.info("Мигрировано users.json → SQLite: %d записей", migrated)


def _seed_whitelist(ids: List[int]) -> None:
    """Добавляет telegram_id из env в whitelist (пропускает дубли)."""
    with _conn() as con:
        for tid in ids:
            con.execute(
                "INSERT OR IGNORE INTO telegram_whitelist (telegram_id, note) VALUES (?, 'env seed')",
                (tid,),
            )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _expire_iso(minutes: int) -> str:
    return (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()


# ─── Users ────────────────────────────────────────────────────────────────────

def db_find_user_by_telegram_id(telegram_id: int) -> Optional[Dict]:
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def db_find_user_by_email(email: str) -> Optional[Dict]:
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()
        return dict(row) if row else None


def db_upsert_user(data: Dict) -> int:
    """
    Вставляет или обновляет пользователя. Возвращает DB id.
    Если задан telegram_id — ключ по нему. Иначе по email.
    """
    _ensure_init()
    tid = data.get("telegram_id")
    email_raw = data.get("email")
    email = email_raw.lower().strip() if email_raw else None

    with _conn() as con:
        if tid is not None:
            con.execute(
                """
                INSERT INTO users
                    (telegram_id, email, username, role, active,
                     preferred_server_id, preferred_profile_type, email_verified)
                VALUES (:telegram_id, :email, :username, :role, :active,
                        :preferred_server_id, :preferred_profile_type, :email_verified)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    email                  = COALESCE(:email, email),
                    username               = COALESCE(:username, username),
                    role                   = :role,
                    active                 = :active,
                    preferred_server_id    = COALESCE(:preferred_server_id, preferred_server_id),
                    preferred_profile_type = COALESCE(:preferred_profile_type, preferred_profile_type),
                    email_verified         = MAX(email_verified, :email_verified)
                """,
                {
                    "telegram_id": tid,
                    "email": email,
                    "username": data.get("username"),
                    "role": data.get("role", "user"),
                    "active": 1 if data.get("active", True) else 0,
                    "preferred_server_id": data.get("preferred_server_id"),
                    "preferred_profile_type": data.get("preferred_profile_type"),
                    "email_verified": 1 if data.get("email_verified") else 0,
                },
            )
            row = con.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (tid,)
            ).fetchone()
        elif email:
            con.execute(
                """
                INSERT INTO users
                    (email, username, role, active,
                     preferred_server_id, preferred_profile_type, email_verified)
                VALUES (:email, :username, :role, :active,
                        :preferred_server_id, :preferred_profile_type, :email_verified)
                ON CONFLICT(email) DO UPDATE SET
                    username               = COALESCE(:username, username),
                    role                   = :role,
                    active                 = :active,
                    preferred_server_id    = COALESCE(:preferred_server_id, preferred_server_id),
                    preferred_profile_type = COALESCE(:preferred_profile_type, preferred_profile_type),
                    email_verified         = MAX(email_verified, :email_verified)
                """,
                {
                    "email": email,
                    "username": data.get("username"),
                    "role": data.get("role", "user"),
                    "active": 1 if data.get("active", True) else 0,
                    "preferred_server_id": data.get("preferred_server_id", "eu1"),
                    "preferred_profile_type": data.get("preferred_profile_type"),
                    "email_verified": 1 if data.get("email_verified") else 0,
                },
            )
            row = con.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
        else:
            raise ValueError("db_upsert_user: нужен telegram_id или email")
        return row["id"] if row else 0


def db_get_all_users() -> List[Dict]:
    _ensure_init()
    with _conn() as con:
        rows = con.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def db_get_effective_telegram_id(user_row: Dict) -> int:
    """
    telegram_id для операций с peers.json.
    Бот-пользователи → реальный ID.
    Email-only → -(db_id) (синтетический отрицательный ID).
    """
    tid = user_row.get("telegram_id")
    if tid:
        return int(tid)
    db_id = user_row.get("id", 0)
    return -int(db_id)


# ─── OTP ──────────────────────────────────────────────────────────────────────

def db_create_otp(email: str, code: str, ttl_minutes: int = 10) -> None:
    """Сохраняет OTP-код. Аннулирует предыдущие неиспользованные коды для этого email."""
    _ensure_init()
    email = email.lower().strip()
    expires = _expire_iso(ttl_minutes)
    with _conn() as con:
        con.execute(
            "UPDATE otp_codes SET used = 1 WHERE email = ? AND used = 0", (email,)
        )
        con.execute(
            "INSERT INTO otp_codes (email, code, expires_at) VALUES (?, ?, ?)",
            (email, code, expires),
        )


def db_verify_otp(email: str, code: str) -> bool:
    """Проверяет OTP. Возвращает True если валиден и не просрочен. Помечает как использованный."""
    _ensure_init()
    email = email.lower().strip()
    now = _now_iso()
    with _conn() as con:
        row = con.execute(
            """
            SELECT id FROM otp_codes
            WHERE email = ? AND code = ? AND used = 0 AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (email, code, now),
        ).fetchone()
        if not row:
            return False
        con.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
        return True


# ─── Whitelist ────────────────────────────────────────────────────────────────

def db_is_whitelisted(telegram_id: int) -> bool:
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM telegram_whitelist WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row is not None


def db_add_to_whitelist(telegram_id: int, note: str = "") -> None:
    _ensure_init()
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO telegram_whitelist (telegram_id, note) VALUES (?, ?)",
            (telegram_id, note),
        )


def db_remove_from_whitelist(telegram_id: int) -> None:
    _ensure_init()
    with _conn() as con:
        con.execute(
            "DELETE FROM telegram_whitelist WHERE telegram_id = ?", (telegram_id,)
        )


def db_get_whitelist() -> List[int]:
    _ensure_init()
    with _conn() as con:
        rows = con.execute("SELECT telegram_id FROM telegram_whitelist ORDER BY telegram_id").fetchall()
        return [r["telegram_id"] for r in rows]


# ─── Web Sessions ─────────────────────────────────────────────────────────────

def db_create_session(email: str, ttl_minutes: int = 60) -> str:
    """Создаёт веб-сессию после верификации OTP. Возвращает токен."""
    _ensure_init()
    email = email.lower().strip()
    token = secrets.token_hex(32)
    expires = _expire_iso(ttl_minutes)
    with _conn() as con:
        # Чистим просроченные сессии
        con.execute(
            "DELETE FROM web_sessions WHERE expires_at < ?", (_now_iso(),)
        )
        con.execute(
            "INSERT INTO web_sessions (token, email, expires_at) VALUES (?, ?, ?)",
            (token, email, expires),
        )
    return token


def db_verify_session(token: str) -> Optional[str]:
    """Проверяет токен сессии. Возвращает email или None."""
    if not token:
        return None
    _ensure_init()
    now = _now_iso()
    with _conn() as con:
        row = con.execute(
            "SELECT email FROM web_sessions WHERE token = ? AND expires_at > ?",
            (token, now),
        ).fetchone()
        return row["email"] if row else None


# ─── VLESS ────────────────────────────────────────────────────────────────────

def db_get_vless_creds(telegram_id: int) -> Optional[Dict]:
    """Возвращает {'vless_uuid': ..., 'vless_short_id': ...} или None."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT vless_uuid, vless_short_id FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not row or not row["vless_uuid"]:
            return None
        return dict(row)


def db_set_vless_creds(telegram_id: int, uuid: str, short_id: str) -> None:
    """Сохраняет UUID и shortId VLESS для пользователя."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE users SET vless_uuid = ?, vless_short_id = ? WHERE telegram_id = ?",
            (uuid, short_id, telegram_id),
        )


def db_clear_vless_creds(telegram_id: int) -> None:
    """Очищает VLESS credentials пользователя (при регенерации)."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE users SET vless_uuid = NULL, vless_short_id = NULL WHERE telegram_id = ?",
            (telegram_id,),
        )


# ─── Servers ──────────────────────────────────────────────────────────────────

def db_get_server(server_id: str) -> Optional[Dict]:
    """Возвращает строку сервера из таблицы servers или None."""
    _ensure_init()
    with _conn() as con:
        row = con.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
        return dict(row) if row else None


def db_get_active_servers(protocol: Optional[str] = None) -> List[Dict]:
    """
    Возвращает все активные серверы (active=1).
    Если задан protocol — фильтрует по нему.
    """
    _ensure_init()
    with _conn() as con:
        if protocol:
            rows = con.execute(
                "SELECT * FROM servers WHERE active = 1 AND protocol = ? ORDER BY id",
                (protocol,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM servers WHERE active = 1 ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]


def db_pick_server(protocol: str = "vless") -> str:
    """
    Выбирает наименее загруженный активный сервер для протокола.

    Для protocol='vless'  нагрузка = кол-во пользователей с vless_uuid IS NOT NULL.
    Для protocol='awg'    нагрузка = кол-во пользователей с preferred_server_id = server.id.

    Возвращает server_id (str). Если активных серверов нет — возвращает 'eu1' как fallback.
    """
    _ensure_init()
    servers = db_get_active_servers(protocol=protocol)
    if not servers:
        logger.warning("db_pick_server: нет активных серверов protocol=%s, fallback eu1", protocol)
        return "eu1"

    if len(servers) == 1:
        return servers[0]["id"]

    # Считаем нагрузку для каждого сервера
    with _conn() as con:
        load: Dict[str, int] = {}
        for srv in servers:
            sid = srv["id"]
            if protocol == "vless":
                # VLESS: пользователи с vless_uuid != NULL
                # Все VLESS-пользователи пока на eu1, поэтому считаем общий счётчик
                cnt = con.execute(
                    "SELECT COUNT(*) FROM users WHERE vless_uuid IS NOT NULL AND active = 1"
                ).fetchone()[0]
            else:
                # AWG / WG: пользователи с preferred_server_id = sid
                cnt = con.execute(
                    "SELECT COUNT(*) FROM users WHERE preferred_server_id = ? AND active = 1",
                    (sid,),
                ).fetchone()[0]
            load[sid] = cnt

    # Выбираем сервер с наибольшим остатком: capacity - load
    best = min(servers, key=lambda s: load.get(s["id"], 0) / max(s["capacity"], 1))
    logger.info(
        "db_pick_server(protocol=%s): выбран %s (load=%d/%d)",
        protocol, best["id"], load.get(best["id"], 0), best["capacity"],
    )
    return best["id"]


def db_upsert_server(server_id: str, name: str, protocol: str, capacity: int, active: bool = True) -> None:
    """Создаёт или обновляет запись сервера."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO servers (id, name, protocol, capacity, active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name     = excluded.name,
                protocol = excluded.protocol,
                capacity = excluded.capacity,
                active   = excluded.active
            """,
            (server_id, name, protocol, capacity, 1 if active else 0),
        )
