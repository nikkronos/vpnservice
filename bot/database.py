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
PEERS_JSON_PATH = DATA_DIR / "peers.json"

_db_initialized = False


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    # Несколько писателей одновременно (bot + web + cron-скрипты) — ждём
    # освобождения блокировки до 5 с вместо мгновенного "database is locked".
    con.execute("PRAGMA busy_timeout=5000")
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

-- VPN-слоты пользователей (WG/AmneziaWG peers). Раньше жили только в
-- bot/data/peers.json; консолидированы в SQLite (2026-06). Composite-ключ
-- (telegram_id, server_id, platform) повторяет ключ peers.json
-- "{tid}:{server_id}:{platform}". Без FK на users/servers — сохраняем
-- вольность JSON (legacy/синтетические отрицательные tid, peers вне users).
CREATE TABLE IF NOT EXISTS peers (
    telegram_id   INTEGER NOT NULL,
    server_id     TEXT NOT NULL DEFAULT 'rus1',
    platform      TEXT NOT NULL DEFAULT 'pc',       -- 'pc' | 'ios' | 'android'
    wg_ip         TEXT NOT NULL,
    public_key    TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    profile_type  TEXT,                             -- для eu1: 'vpn'|'vpn_gpt'|'unified'
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT,
    PRIMARY KEY (telegram_id, server_id, platform)
);
CREATE INDEX IF NOT EXISTS idx_peers_public_key ON peers (public_key);

-- Именованные устройства (Фаза 2 B). Слот peers ссылается на device_id вместо
-- platform — каждый девайс отдельный (фикс коллизии iPad/iPhone). os = формат
-- доставки. Создаётся также миграцией _migrate_peers_platform_to_device.
CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,
    telegram_id  INTEGER NOT NULL,
    name         TEXT NOT NULL,
    os           TEXT NOT NULL DEFAULT 'pc',          -- 'pc' | 'ios' | 'android'
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_tid ON devices (telegram_id);

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

CREATE TABLE IF NOT EXISTS traffic_accounting (
    public_key   TEXT PRIMARY KEY,
    telegram_id  INTEGER,
    lifetime_rx  INTEGER NOT NULL DEFAULT 0,
    lifetime_tx  INTEGER NOT NULL DEFAULT 0,
    last_rx      INTEGER NOT NULL DEFAULT 0,
    last_tx      INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER,
    email        TEXT,
    provider     TEXT NOT NULL,                     -- 'yookassa' | 'stars' | 'crypto' | 'sbp'
    amount       REAL,
    currency     TEXT NOT NULL DEFAULT 'RUB',
    status       TEXT NOT NULL DEFAULT 'pending',   -- 'pending'|'succeeded'|'canceled'|'failed'
    external_id  TEXT,                              -- id платежа у провайдера
    plan         TEXT,                              -- что куплено
    days         INTEGER,                           -- сколько дней доступа даёт платёж
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT
);

-- Support: тикеты от юзеров. Variant B (двусторонняя переписка через бот).
-- Тикет открывается когда юзер пишет в support; закрывается owner-ом или авто-эскалацией.
CREATE TABLE IF NOT EXISTS support_tickets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id     INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',     -- 'open' | 'closed'
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_message_at TEXT,
    closed_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_support_tickets_tid_status ON support_tickets (telegram_id, status);

CREATE TABLE IF NOT EXISTS support_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id     INTEGER NOT NULL,
    sender        TEXT NOT NULL,                       -- 'user' | 'owner'
    text          TEXT,
    photo_file_id TEXT,                                -- TG file_id если прикреплено фото
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_messages (ticket_id);

-- Donation-style payment claims: юзер жмёт «Я оплатил» → строка pending → владелец
-- решает approve/decline через inline-кнопки в боте. Одна pending-заявка на юзера за раз.
CREATE TABLE IF NOT EXISTS payment_claims (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL,
    days         INTEGER NOT NULL DEFAULT 30,
    device_limit INTEGER NOT NULL DEFAULT 5,         -- тариф: 3 или 5 устройств (несём в approve)
    status       TEXT NOT NULL DEFAULT 'pending',   -- 'pending'|'approved'|'declined'
    source       TEXT,                              -- 'webapp'|'bot' — откуда пришла
    note         TEXT,                              -- свободный текст (например, метод оплаты)
    claimed_at   TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at   TEXT,
    notify_msg_id INTEGER                           -- message_id уведомления владельцу (для edit_message_text)
);
CREATE INDEX IF NOT EXISTS idx_payment_claims_tid_status ON payment_claims (telegram_id, status);

-- iplimit-НАБЛЮДЕНИЕ (Фаза 2 A-Stage1, 2026-06-10): кто с каких IP ходит.
-- Источник — access-log Xray на входах (real client IP + email tid_X@kronos),
-- собирает scripts/ip_usage_watcher.py (cron). ТОЛЬКО ЗАМЕР, без enforcement.
-- distinct IP per юзер за окно = сигнал шеринга (разные люди/локации), НЕ счёт
-- устройств на одной сети. Пороги калибруются по этим данным. Retention ~48ч.
CREATE TABLE IF NOT EXISTS ip_usage (
    telegram_id  INTEGER NOT NULL,
    ip           TEXT NOT NULL,
    server_id    TEXT NOT NULL,                     -- где замечен (eu1/main/yc/yc2)
    first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    hits         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (telegram_id, ip)
);
CREATE INDEX IF NOT EXISTS idx_ip_usage_tid_seen ON ip_usage (telegram_id, last_seen);
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
    _migrate_peers_json_to_sqlite()
    _migrate_add_vless_columns()
    _migrate_add_servers_table()
    _migrate_add_proxy_column()
    _migrate_add_vless_column()
    _migrate_add_vless_server_traffic_table()
    _migrate_add_traffic_snapshots_table()
    _migrate_add_per_user_vless_uuids()
    _migrate_add_vless_user_traffic_table()
    _migrate_add_subscription_columns()
    _migrate_add_password_column()
    _migrate_add_sub_token_column()
    _migrate_add_referral_bonus_paid_column()
    _migrate_add_expiry_notif_columns()
    _migrate_add_migrated_at_column()
    _migrate_add_claim_device_limit()
    # B (Фаза 2): peers platform→device_id + devices. ПОСЛЕДНЕЙ — после того как
    # все peer-данные (json→sqlite и пр.) уже в старом формате, конвертируем 1:1.
    _migrate_peers_platform_to_device()
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


def _migrate_peers_platform_to_device(con=None) -> None:
    """
    Фаза 2 B — ключ peers (telegram_id, server_id, platform) → (telegram_id,
    server_id, device_id) + таблица devices. platform → os (свойство устройства,
    не ключ). Миграция 1:1 — клиентские ключи (wg_ip/public_key) НЕ меняются,
    значит старые .conf продолжают работать. Идемпотентна (повторный прогон —
    no-op, если device_id уже есть).

    Зачем: per-OS слот не даёт 2 устройства одной ОС (iPad+iPhone коллизят,
    фидбэк Ани). Именованные device_id это снимают + база под «семейный» тариф.

    ⚠️ НЕ вызывается из init_db до B1 — сначала зелёный тест
    (`scripts/test_per_device_migration.py`) + бэкап vpn.db + go владельца.
    Тогда же обновляются _SCHEMA / storage / wireguard_peers под device_id.
    """
    def _run(c) -> None:
        cols = {r[1] for r in c.execute("PRAGMA table_info(peers)").fetchall()}
        if "device_id" in cols:
            return  # уже мигрировано
        if "platform" not in cols:
            return  # не старый формат — нечего мигрировать
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id    TEXT PRIMARY KEY,
                telegram_id  INTEGER NOT NULL,
                name         TEXT NOT NULL,
                os           TEXT NOT NULL DEFAULT 'pc',   -- 'pc'|'ios'|'android' (формат доставки)
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_devices_tid ON devices (telegram_id)")
        c.execute(
            """
            CREATE TABLE peers_new (
                telegram_id  INTEGER NOT NULL,
                server_id    TEXT NOT NULL DEFAULT 'rus1',
                device_id    TEXT NOT NULL,
                os           TEXT NOT NULL DEFAULT 'pc',
                wg_ip        TEXT NOT NULL,
                public_key   TEXT NOT NULL,
                active       INTEGER NOT NULL DEFAULT 1,
                profile_type TEXT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT,
                PRIMARY KEY (telegram_id, server_id, device_id)
            )
            """
        )
        label = {"pc": "ПК", "ios": "Устройство iOS", "android": "Android-устройство"}
        rows = c.execute(
            "SELECT telegram_id, server_id, platform, wg_ip, public_key, active, "
            "profile_type, created_at, updated_at FROM peers"
        ).fetchall()
        for r in rows:
            plat = (r["platform"] or "pc")
            device_id = secrets.token_hex(4)  # стабильный hex8
            c.execute(
                "INSERT INTO devices (device_id, telegram_id, name, os, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (device_id, r["telegram_id"], label.get(plat, plat), plat,
                 r["created_at"] or None),
            )
            c.execute(
                "INSERT INTO peers_new (telegram_id, server_id, device_id, os, wg_ip, "
                "public_key, active, profile_type, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["telegram_id"], r["server_id"], device_id, plat, r["wg_ip"],
                 r["public_key"], r["active"], r["profile_type"],
                 r["created_at"] or None, r["updated_at"]),
            )
        c.execute("DROP TABLE peers")
        c.execute("ALTER TABLE peers_new RENAME TO peers")
        c.execute("CREATE INDEX IF NOT EXISTS idx_peers_public_key ON peers (public_key)")
        logger.info("Migration B: peers platform→device_id (%d слотов → devices)", len(rows))

    if con is not None:
        _run(con)
    else:
        with _conn() as c:
            _run(c)


def _migrate_add_proxy_column() -> None:
    """Добавляет proxy_requested_at в таблицу users (идемпотентно)."""
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "proxy_requested_at" not in existing:
            con.execute("ALTER TABLE users ADD COLUMN proxy_requested_at TEXT")
            logger.info("Migration: added proxy_requested_at column to users")


def _migrate_add_vless_user_traffic_table() -> None:
    """
    Per-user VLESS трафик (Этап 9 миграции на per-user UUIDs).

    Пишется `scripts/vless_summary_accounting.py` каждые 5 мин из
    `xray api statsquery -pattern='user>>>tid_X@kronos>>>traffic>>>...'`.
    Это работает после Этапа 7 (policy.levels.0.statsUser{Up,Down}link=true
    на main/yc) и Этапа 8 (per-user UUIDs с email-маркером в config).

    Структура аналогична traffic_accounting (AWG):
      - reset-aware: при рестарте Xray счётчики обнуляются, БД продолжает копить
      - composite PK (telegram_id, server_id) — у юзера может быть activity на
        main И yc одновременно

    Используется в /api/traffic для определения status='active' для
    VLESS-only юзеров (закрывает gap «много тихих хотя юзают»).
    """
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS vless_user_traffic (
                telegram_id INTEGER NOT NULL,
                server_id   TEXT NOT NULL,
                lifetime_rx INTEGER NOT NULL DEFAULT 0,
                lifetime_tx INTEGER NOT NULL DEFAULT 0,
                last_rx     INTEGER NOT NULL DEFAULT 0,
                last_tx     INTEGER NOT NULL DEFAULT 0,
                last_seen   TEXT,
                PRIMARY KEY (telegram_id, server_id)
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_vless_user_traffic_tid "
            "ON vless_user_traffic(telegram_id)"
        )


def _migrate_add_per_user_vless_uuids() -> None:
    """
    Per-user VLESS UUIDs на каждом сервере (для замены общих share-UUIDs).

    Колонки:
      - users.vless_uuid_eu1  — для vless-ws на eu1 (CDN канал)
      - users.vless_uuid_main — для vless-tcp REALITY на main (Мегафон/Yota)
      - users.vless_uuid_yc   — для vless-xhttp REALITY на yc (T2/МТС/Билайн)

    Legacy `users.vless_uuid` (+ `vless_short_id`) — НЕ трогаются, остаются
    для совместимости с db_get_vless_creds. Новые поля используются в
    _build_subscription_links и в bot/main.py callback_mobile_operator
    после полной миграции.

    Email-маркер в Xray для per-user телеметрии: `tid_<telegram_id>@kronos`
    (синтетический, без утечки ПД в логи Xray — мы декларируем в Политике
    что трафик не логируем).
    """
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        for col in ("vless_uuid_eu1", "vless_uuid_main", "vless_uuid_yc"):
            if col not in existing:
                con.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
                logger.info("Migration: added %s column to users", col)


def _migrate_add_traffic_snapshots_table() -> None:
    """
    Создаёт таблицу traffic_snapshots для исторических снимков AmneziaWG-трафика
    (`scripts/traffic_accounting.py` пишет каждые 5 мин). Нужна для расследований
    типа «в N мск был лаг — кто качал».

    `traffic_accounting` хранит только cumulative-snapshot (последнее значение
    per pubkey), без истории — реконструировать пики по нему нельзя. Эта таблица
    хранит timeseries: для каждого пика можно посчитать delta (rx_t1 - rx_t0)
    per юзер и найти top-нагружающих.

    Только AWG (per-user pinpoint возможен через telegram_id привязку pubkey).
    VLESS использует общие UUIDs — per-user всё равно невозможно;
    per-server VLESS-history можно достать из journalctl `vless-summary`.

    Rolling-delete: >14 дней удаляется автоматически при каждой записи
    (см. db_record_traffic_snapshot). Объём: ~16 peers × 12 snapshots/час
    × 24 ч × 14 дней ≈ 65k строк (мизер для SQLite).
    """
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS traffic_snapshots (
                ts          TEXT NOT NULL,
                public_key  TEXT NOT NULL,
                telegram_id INTEGER,
                rx          INTEGER NOT NULL,
                tx          INTEGER NOT NULL,
                PRIMARY KEY (ts, public_key)
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_traffic_snapshots_ts ON traffic_snapshots(ts)"
        )


def _migrate_add_vless_server_traffic_table() -> None:
    """
    Создаёт таблицу vless_server_traffic для per-server summary VLESS-трафика
    через Xray stats API (см. scripts/vless_summary_accounting.py).

    Per-USER телеметрия невозможна пока используются общие UUIDs на серверах
    (см. ROADMAP P2 — «Персональные UUIDs»). Per-INBOUND же доступна сразу
    через `xray api statsquery -pattern=inbound>>>vless` — этого хватает на
    вопрос «через какой сервер сколько прокачано».

    Структура аналогична traffic_accounting для AWG, но первичный ключ
    (server_id, inbound_tag): reset-aware accumulation на каждый Xray-рестарт.
    """
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS vless_server_traffic (
                server_id   TEXT NOT NULL,
                inbound_tag TEXT NOT NULL,
                lifetime_rx INTEGER NOT NULL DEFAULT 0,
                lifetime_tx INTEGER NOT NULL DEFAULT 0,
                last_rx     INTEGER NOT NULL DEFAULT 0,
                last_tx     INTEGER NOT NULL DEFAULT 0,
                updated_at  TEXT,
                PRIMARY KEY (server_id, inbound_tag)
            )
            """
        )


def _migrate_add_vless_column() -> None:
    """
    Добавляет vless_requested_at в таблицу users (идемпотентно).

    Используется как proof-of-life сигнал для VLESS-юзеров — в админ-панели
    статус `idle` ставится по AWG handshake (которого у VLESS-юзеров не бывает).
    Эта отметка пишется при любом hit'е, который означает что клиент юзера
    дёрнул нашу инфру за VLESS:
      - bot/main.py: после выдачи vless:// в `callback_mobile_operator`
      - web/app.py: после выдачи `/api/recovery/mobile-link-by-email`
      - web/app.py: subscription URL `/sub/<sub_token>` hit (включая авто-refresh
        клиентами HAPP/Streisand каждые N часов — это и есть лучший proof-of-life).
    """
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "vless_requested_at" not in existing:
            con.execute("ALTER TABLE users ADD COLUMN vless_requested_at TEXT")
            logger.info("Migration: added vless_requested_at column to users")


def _migrate_add_subscription_columns() -> None:
    """
    Добавляет поля подписки/биллинга/реферала в users (идемпотентно).

    Семантика:
    - expires_at IS NULL → grandfathered (доступ без ограничения; legacy-юзеры
      до ввода enforcement). Доступ активен пока now < expires_at.
    - subscription_status: 'none' | 'trial' | 'active' | 'expired'.
    - trial_used: 0/1 — был ли использован пробный период.
    - referral_code: личный код юзера для приглашений; referred_by — код пригласившего.
    """
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        cols = [
            ("subscription_status", "TEXT DEFAULT 'none'"),
            ("expires_at", "TEXT"),
            ("trial_used", "INTEGER NOT NULL DEFAULT 0"),
            ("plan", "TEXT"),
            ("referral_code", "TEXT"),
            ("referred_by", "TEXT"),
            # device_limit: лимит именованных устройств по тарифу. DEFAULT 5 =
            # грандфазер существующих юзеров + триал (= tariffs.DEFAULT_DEVICE_LIMIT).
            # Новый тариф (199/249/449/599) проставляет 3 или 5 при оплате.
            ("device_limit", "INTEGER NOT NULL DEFAULT 5"),
        ]
        for name, decl in cols:
            if name not in existing:
                try:
                    con.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
                    logger.info("Migration: added %s column to users", name)
                except sqlite3.OperationalError as e:
                    # гонка двух сервисов (vpn-web + vpn-bot) или повторный запуск
                    logger.info("Migration: skip %s (%s)", name, e)


def _migrate_add_claim_device_limit() -> None:
    """Добавляет device_limit в payment_claims (идемпотентно).

    Тариф (3/5 устройств) несётся через claim до approve. Существующие claim'ы
    получают DEFAULT 5.
    """
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(payment_claims)").fetchall()}
        if "device_limit" not in existing:
            try:
                con.execute(
                    "ALTER TABLE payment_claims ADD COLUMN device_limit INTEGER NOT NULL DEFAULT 5"
                )
                logger.info("Migration: added device_limit column to payment_claims")
            except sqlite3.OperationalError as e:
                logger.info("Migration: skip payment_claims.device_limit (%s)", e)


def _migrate_add_password_column() -> None:
    """Добавляет password_hash в users (идемпотентно)."""
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "password_hash" not in existing:
            try:
                con.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
                logger.info("Migration: added password_hash column to users")
            except sqlite3.OperationalError as e:
                logger.info("Migration: skip password_hash (%s)", e)


def _migrate_add_sub_token_column() -> None:
    """Добавляет sub_token (стабильный токен subscription-ссылки) в users (идемпотентно)."""
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "sub_token" not in existing:
            try:
                con.execute("ALTER TABLE users ADD COLUMN sub_token TEXT")
                logger.info("Migration: added sub_token column to users")
            except sqlite3.OperationalError as e:
                logger.info("Migration: skip sub_token (%s)", e)


def _migrate_add_referral_bonus_paid_column() -> None:
    """Флаг: реферал-бонус уже выплачен пригласившему за первую оплату этого юзера (idempotent)."""
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "referral_bonus_paid" not in existing:
            try:
                con.execute("ALTER TABLE users ADD COLUMN referral_bonus_paid INTEGER NOT NULL DEFAULT 0")
                logger.info("Migration: added referral_bonus_paid column to users")
            except sqlite3.OperationalError as e:
                logger.info("Migration: skip referral_bonus_paid (%s)", e)


def _migrate_add_migrated_at_column() -> None:
    """Флаг первого /start в новом боте — для selective reset при миграции на @vpnkronos_bot."""
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        if "migrated_at" not in existing:
            try:
                con.execute("ALTER TABLE users ADD COLUMN migrated_at TEXT")
                logger.info("Migration: added migrated_at column to users")
            except sqlite3.OperationalError as e:
                logger.info("Migration: skip migrated_at (%s)", e)


def _migrate_add_expiry_notif_columns() -> None:
    """
    Флаги отправки напоминаний об окончании подписки (cron expiry_reminder.py):
    notif_7d_sent / notif_3d_sent / notif_0d_sent.
    Сбрасываются при каждом продлении подписки → следующий цикл получит свои напоминания.
    """
    with _conn() as con:
        existing = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
        for col in ("notif_7d_sent", "notif_3d_sent", "notif_0d_sent"):
            if col not in existing:
                try:
                    con.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
                    logger.info("Migration: added %s column to users", col)
                except sqlite3.OperationalError as e:
                    logger.info("Migration: skip %s (%s)", col, e)


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


def _migrate_peers_json_to_sqlite() -> None:
    """
    Переносит bot/data/peers.json → таблицу peers (идемпотентно).

    Пропускает уже существующие слоты по composite-ключу
    (telegram_id, server_id, platform). Нормализация ключей/server_id/platform
    переиспользуется из storage.py (late-import — чистые функции, без БД,
    без циклического импорта). Записи без wg_ip/public_key пропускаются.

    Запускается из init_db() на каждом старте — но реально вставляет строки
    только при первом проходе (или когда в peers.json появился новый слот,
    которого ещё нет в таблице). peers.json остаётся как dual-write зеркало
    на время переходного периода (см. storage.DUAL_WRITE_JSON).
    """
    # Фаза 2 B: если peers уже в device-формате — эта платформенная json-миграция
    # (peers.json мёртв в Phase 3) обсолетна и сломается на колонке platform. Скип.
    with _conn() as con:
        _cols = {r[1] for r in con.execute("PRAGMA table_info(peers)").fetchall()}
    if "device_id" in _cols or "platform" not in _cols:
        return
    if not PEERS_JSON_PATH.exists():
        return
    try:
        raw = json.loads(PEERS_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("peers.json миграция: не удалось прочитать (%s)", e)
        return
    if not raw:
        return
    from .storage import (  # late-import: чистые функции нормализации, без БД
        _migrate_peers_json_on_load,
        normalize_peer_server_id,
        _normalize_platform,
    )
    normalized = _migrate_peers_json_on_load(raw)
    migrated = 0
    with _conn() as con:
        for key, payload in normalized.items():
            parts = str(key).split(":")
            try:
                tid = int(payload.get("telegram_id", parts[0]))
            except (ValueError, TypeError):
                continue
            sid = normalize_peer_server_id(
                payload.get("server_id", parts[1] if len(parts) > 1 else "rus1")
            )
            plat = _normalize_platform(
                payload.get("platform", parts[2] if len(parts) > 2 else "pc")
            )
            wg_ip = payload.get("wg_ip")
            public_key = payload.get("public_key")
            if not wg_ip or not public_key:
                continue
            existing = con.execute(
                "SELECT 1 FROM peers WHERE telegram_id = ? AND server_id = ? AND platform = ?",
                (tid, sid, plat),
            ).fetchone()
            if existing:
                continue
            con.execute(
                """
                INSERT OR IGNORE INTO peers
                    (telegram_id, server_id, platform, wg_ip, public_key, active, profile_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    sid,
                    plat,
                    wg_ip,
                    public_key,
                    1 if payload.get("active", True) else 0,
                    payload.get("profile_type"),
                ),
            )
            migrated += 1
    if migrated:
        logger.info("Мигрировано peers.json → SQLite: %d слотов", migrated)


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


def db_delete_email_only_user(email: str) -> bool:
    """
    Удаляет запись пользователя, у которой есть email, но нет telegram_id.
    Используется при слиянии email-only записи с telegram-записью.
    Возвращает True если запись была удалена.
    """
    _ensure_init()
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM users WHERE email = ? AND (telegram_id IS NULL OR telegram_id = 0)",
            (email.lower().strip(),),
        )
        return cur.rowcount > 0


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


def db_update_proxy_requested_at(telegram_id: int) -> None:
    """Записывает время последнего запроса MTProxy-ссылки пользователем."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE users SET proxy_requested_at = datetime('now') WHERE telegram_id = ?",
            (telegram_id,),
        )


def db_update_vless_requested_at(telegram_id: int) -> None:
    """
    Записывает время последнего hit'а связанного с VLESS пользователем.

    Срабатывает при выдаче vless:// ссылки в боте/ЛК и при subscription URL hit
    (включая авто-refresh HAPP/Streisand-клиентами). Используется в админ-панели
    как `vless_last_seen` сигнал — компенсирует отсутствие AWG-handshake для
    VLESS-юзеров до тех пор пока не сделаем per-user UUID + Xray stats API.
    """
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE users SET vless_requested_at = datetime('now') WHERE telegram_id = ?",
            (telegram_id,),
        )


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


# ─── Peers (VPN-слоты) ──────────────────────────────────────────────────────────
# Источник правды для WG/AmneziaWG peers (раньше — bot/data/peers.json).
# Нормализация server_id/platform делается в storage.py перед вызовом этих
# хелперов — здесь «глупое» хранилище, значения кладутся как есть.

def db_get_all_peers() -> List[Dict]:
    """Все peer-слоты. Возвращает list[dict] (как строки таблицы peers).
    После Фазы 2 B строки содержат device_id + os (вместо platform)."""
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM peers ORDER BY telegram_id, server_id, device_id"
        ).fetchall()
        return [dict(r) for r in rows]


def db_upsert_peer(data: Dict) -> None:
    """
    Вставляет/обновляет peer-слот по ключу (telegram_id, server_id, device_id).
    Ожидает device_id + os (см. storage.upsert_peer). created_at трогает только
    INSERT (сохраняется при обновлении).
    """
    _ensure_init()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO peers
                (telegram_id, server_id, device_id, os, wg_ip, public_key, active, profile_type, updated_at)
            VALUES
                (:telegram_id, :server_id, :device_id, :os, :wg_ip, :public_key, :active, :profile_type, datetime('now'))
            ON CONFLICT(telegram_id, server_id, device_id) DO UPDATE SET
                os           = :os,
                wg_ip        = :wg_ip,
                public_key   = :public_key,
                active       = :active,
                profile_type = :profile_type,
                updated_at   = datetime('now')
            """,
            {
                "telegram_id": int(data["telegram_id"]),
                "server_id": data["server_id"],
                "device_id": data["device_id"],
                "os": data.get("os", "pc"),
                "wg_ip": data["wg_ip"],
                "public_key": data["public_key"],
                "active": 1 if data.get("active", True) else 0,
                "profile_type": data.get("profile_type"),
            },
        )


def db_delete_peer(telegram_id: int, server_id: str, device_id: str) -> None:
    """Удаляет peer-слот по composite-ключу (telegram_id, server_id, device_id)."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "DELETE FROM peers WHERE telegram_id = ? AND server_id = ? AND device_id = ?",
            (int(telegram_id), server_id, device_id),
        )


# ─── Devices (именованные устройства, Фаза 2 B) ───────────────────────────────

def db_list_devices(telegram_id: int) -> List[Dict]:
    """Устройства пользователя (по порядку создания)."""
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM devices WHERE telegram_id = ? ORDER BY created_at, device_id",
            (int(telegram_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def db_get_device(device_id: str) -> Optional[Dict]:
    _ensure_init()
    with _conn() as con:
        r = con.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return dict(r) if r else None


def db_add_device(telegram_id: int, name: str, os: str = "pc") -> str:
    """Создаёт устройство, возвращает новый device_id (hex8)."""
    _ensure_init()
    device_id = secrets.token_hex(4)
    with _conn() as con:
        con.execute(
            "INSERT INTO devices (device_id, telegram_id, name, os) VALUES (?, ?, ?, ?)",
            (device_id, int(telegram_id), name, os or "pc"),
        )
    return device_id


def db_rename_device(device_id: str, name: str) -> None:
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE devices SET name = ?, updated_at = datetime('now') WHERE device_id = ?",
            (name, device_id),
        )


def db_delete_device(device_id: str) -> None:
    """Удаляет устройство + его peer-слоты (на всех серверах)."""
    _ensure_init()
    with _conn() as con:
        con.execute("DELETE FROM peers WHERE device_id = ?", (device_id,))
        con.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))


def db_count_devices(telegram_id: int) -> int:
    _ensure_init()
    with _conn() as con:
        return con.execute(
            "SELECT COUNT(*) FROM devices WHERE telegram_id = ?", (int(telegram_id),)
        ).fetchone()[0]


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


# ─── Per-user VLESS UUIDs (новая схема, миграция 2026-06-01) ──────────────────

_VLESS_UUID_COLUMNS = {
    "eu1":  "vless_uuid_eu1",
    "main": "vless_uuid_main",
    "yc":   "vless_uuid_yc",
}


def db_get_or_create_vless_uuid(telegram_id: int, server_id: str) -> Optional[str]:
    """
    Возвращает per-user VLESS UUID для указанного сервера. Если ещё не создан —
    генерирует новый (uuid4), сохраняет в БД и возвращает.

    Idempotent: повторный вызов вернёт ТОТ ЖЕ UUID. Никогда не перегенерирует,
    чтобы старый .conf на устройстве юзера продолжал работать.

    Серверы: 'eu1' / 'main' / 'yc'. Возвращает None для неизвестного server_id.

    Sync с Xray runtime НЕ делает (это отдельный шаг: xray api inbounduser add).
    Эта функция — только БД-уровень.
    """
    import uuid as _uuid
    _ensure_init()
    col = _VLESS_UUID_COLUMNS.get(server_id)
    if not col:
        logger.warning("db_get_or_create_vless_uuid: unknown server_id %s", server_id)
        return None
    with _conn() as con:
        row = con.execute(
            f"SELECT {col} FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row and row[col]:
            return row[col]
        # Генерируем новый UUID и сохраняем
        new_uuid = str(_uuid.uuid4())
        con.execute(
            f"UPDATE users SET {col} = ? WHERE telegram_id = ?",
            (new_uuid, telegram_id),
        )
        # Проверяем что UPDATE задел строку (юзер существует)
        check = con.execute(
            f"SELECT {col} FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not check:
            logger.warning("db_get_or_create_vless_uuid: user tid=%s не существует", telegram_id)
            return None
        logger.info("Сгенерирован per-user VLESS UUID для tid=%s server=%s", telegram_id, server_id)
        return new_uuid


def db_get_per_user_vless_uuid(telegram_id: int, server_id: str) -> Optional[str]:
    """Возвращает UUID если он уже создан, иначе None (не создаёт)."""
    _ensure_init()
    col = _VLESS_UUID_COLUMNS.get(server_id)
    if not col:
        return None
    with _conn() as con:
        row = con.execute(
            f"SELECT {col} FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not row:
            return None
        return row[col]


def db_get_all_per_user_vless_uuids() -> List[Dict]:
    """
    Возвращает все per-user VLESS UUIDs для restore-скрипта.
    [{"telegram_id": int, "eu1": uuid|None, "main": uuid|None, "yc": uuid|None}, ...]
    Только active юзеры (т.к. неактивные не подключаются).
    """
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT telegram_id, vless_uuid_eu1, vless_uuid_main, vless_uuid_yc "
            "FROM users WHERE telegram_id IS NOT NULL AND active = 1"
        ).fetchall()
        return [
            {
                "telegram_id": r["telegram_id"],
                "eu1":  r["vless_uuid_eu1"],
                "main": r["vless_uuid_main"],
                "yc":   r["vless_uuid_yc"],
            }
            for r in rows
        ]


def db_accumulate_vless_user_traffic(server_id: str, samples: List[Dict]) -> None:
    """
    Per-user VLESS трафик (reset-aware), вызывается из vless_summary_accounting.py
    после парсинга `xray api statsquery -pattern=user>>>tid_X@kronos>>>...`.

    samples: [{"telegram_id": int, "rx": int, "tx": int}, ...]

    Логика как в db_accumulate_traffic (AWG):
      current < last → reset (Xray restart) → приращение = current
      current ≥ last → приращение = current - last

    last_seen обновляется при любом current > 0 (юзер реально подключался).
    """
    _ensure_init()
    if not samples or not server_id:
        return
    with _conn() as con:
        for s in samples:
            tid = s.get("telegram_id")
            if not tid:
                continue
            rx = int(s.get("rx") or 0)
            tx = int(s.get("tx") or 0)
            row = con.execute(
                "SELECT lifetime_rx, lifetime_tx, last_rx, last_tx "
                "FROM vless_user_traffic "
                "WHERE telegram_id = ? AND server_id = ?",
                (int(tid), server_id),
            ).fetchone()
            seen_clause = "datetime('now')" if (rx > 0 or tx > 0) else "last_seen"
            if row is None:
                con.execute(
                    "INSERT INTO vless_user_traffic "
                    f"(telegram_id, server_id, lifetime_rx, lifetime_tx, "
                    f" last_rx, last_tx, last_seen) "
                    f"VALUES (?, ?, ?, ?, ?, ?, {seen_clause})",
                    (int(tid), server_id, rx, tx, rx, tx),
                )
                continue
            d_rx = rx - row["last_rx"] if rx >= row["last_rx"] else rx
            d_tx = tx - row["last_tx"] if tx >= row["last_tx"] else tx
            con.execute(
                f"UPDATE vless_user_traffic "
                f"SET lifetime_rx = lifetime_rx + ?, "
                f"    lifetime_tx = lifetime_tx + ?, "
                f"    last_rx = ?, last_tx = ?, "
                f"    last_seen = {seen_clause} "
                f"WHERE telegram_id = ? AND server_id = ?",
                (d_rx, d_tx, rx, tx, int(tid), server_id),
            )


def db_get_vless_user_last_seen() -> Dict[int, str]:
    """
    Возвращает {telegram_id: max_last_seen} — самая свежая активность юзера
    по любому из серверов (main, yc, eu1). Для определения status='active'
    в /api/traffic — VLESS-only юзеры, у которых нет AWG handshake.
    """
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT telegram_id, MAX(last_seen) AS last_seen "
            "FROM vless_user_traffic "
            "WHERE last_seen IS NOT NULL "
            "GROUP BY telegram_id"
        ).fetchall()
        return {int(r["telegram_id"]): r["last_seen"] for r in rows}


def db_get_vless_user_lifetime() -> Dict[int, Dict]:
    """
    Возвращает {telegram_id: {rx, tx, total}} — суммарный lifetime VLESS трафик
    юзера по всем серверам. Используется для отображения 'Всего' в админ-панели.
    """
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT telegram_id, "
            "  SUM(lifetime_rx) AS rx, "
            "  SUM(lifetime_tx) AS tx "
            "FROM vless_user_traffic "
            "GROUP BY telegram_id"
        ).fetchall()
        out: Dict[int, Dict] = {}
        for r in rows:
            rx = r["rx"] or 0
            tx = r["tx"] or 0
            out[int(r["telegram_id"])] = {"rx": rx, "tx": tx, "total": rx + tx}
        return out


def db_clear_per_user_vless_uuid(telegram_id: int, server_id: str) -> None:
    """Очищает per-user UUID для конкретного сервера (для enforce_expired hard-revoke)."""
    _ensure_init()
    col = _VLESS_UUID_COLUMNS.get(server_id)
    if not col:
        return
    with _conn() as con:
        con.execute(
            f"UPDATE users SET {col} = NULL WHERE telegram_id = ?",
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


# ─── Traffic accounting ─────────────────────────────────────────────────────────

def db_accumulate_traffic(samples: List[Dict]) -> None:
    """
    Накопительный учёт трафика по счётчикам AmneziaWG (reset-aware).

    samples: [{"public_key": str, "telegram_id": int|None, "rx": int, "tx": int}, ...]
    rx/tx — текущие значения счётчиков из `awg show ... dump`. Они обнуляются при
    рестарте интерфейса/контейнера или перегенерации peer'а. Поэтому если текущее
    значение меньше сохранённого last — считаем, что был сброс, и приращение равно
    текущему значению. Иначе приращение = current - last.

    Важно: вызывать только для peer'ов, реально присутствующих в dump (иначе
    нулевые сэмплы исказят last_* и приведут к двойному учёту).
    """
    _ensure_init()
    if not samples:
        return
    with _conn() as con:
        for s in samples:
            pk = (s.get("public_key") or "").strip()
            if not pk:
                continue
            rx = int(s.get("rx") or 0)
            tx = int(s.get("tx") or 0)
            tid = s.get("telegram_id")
            row = con.execute(
                "SELECT lifetime_rx, lifetime_tx, last_rx, last_tx "
                "FROM traffic_accounting WHERE public_key = ?",
                (pk,),
            ).fetchone()
            if row is None:
                con.execute(
                    """
                    INSERT INTO traffic_accounting
                        (public_key, telegram_id, lifetime_rx, lifetime_tx,
                         last_rx, last_tx, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (pk, tid, rx, tx, rx, tx),
                )
                continue
            d_rx = rx - row["last_rx"] if rx >= row["last_rx"] else rx
            d_tx = tx - row["last_tx"] if tx >= row["last_tx"] else tx
            con.execute(
                """
                UPDATE traffic_accounting
                SET lifetime_rx = lifetime_rx + ?,
                    lifetime_tx = lifetime_tx + ?,
                    last_rx     = ?,
                    last_tx     = ?,
                    telegram_id = COALESCE(?, telegram_id),
                    updated_at  = datetime('now')
                WHERE public_key = ?
                """,
                (d_rx, d_tx, rx, tx, tid, pk),
            )


def db_accumulate_vless_server_traffic(server_id: str, samples: List[Dict]) -> None:
    """
    Накопительный учёт per-inbound VLESS-трафика на сервере (reset-aware).

    samples: [{"inbound_tag": "vless-reality", "rx": int, "tx": int}, ...]
    rx/tx — текущие значения из `xray api statsquery`. Обнуляются при рестарте
    Xray. Логика та же что в db_accumulate_traffic: current < last → reset,
    приращение = current; current ≥ last → приращение = current - last.
    """
    _ensure_init()
    if not samples or not server_id:
        return
    with _conn() as con:
        for s in samples:
            tag = (s.get("inbound_tag") or "").strip()
            if not tag:
                continue
            rx = int(s.get("rx") or 0)
            tx = int(s.get("tx") or 0)
            row = con.execute(
                "SELECT lifetime_rx, lifetime_tx, last_rx, last_tx "
                "FROM vless_server_traffic WHERE server_id = ? AND inbound_tag = ?",
                (server_id, tag),
            ).fetchone()
            if row is None:
                con.execute(
                    """
                    INSERT INTO vless_server_traffic
                        (server_id, inbound_tag, lifetime_rx, lifetime_tx,
                         last_rx, last_tx, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (server_id, tag, rx, tx, rx, tx),
                )
                continue
            d_rx = rx - row["last_rx"] if rx >= row["last_rx"] else rx
            d_tx = tx - row["last_tx"] if tx >= row["last_tx"] else tx
            con.execute(
                """
                UPDATE vless_server_traffic
                SET lifetime_rx = lifetime_rx + ?,
                    lifetime_tx = lifetime_tx + ?,
                    last_rx     = ?,
                    last_tx     = ?,
                    updated_at  = datetime('now')
                WHERE server_id = ? AND inbound_tag = ?
                """,
                (d_rx, d_tx, rx, tx, server_id, tag),
            )


def db_get_vless_server_lifetime() -> Dict[str, Dict]:
    """
    Возвращает накопительный VLESS-трафик по серверам:
    {server_id: {"rx": int, "tx": int, "total": int}}.
    Суммирует по всем inbound'ам сервера (vless-ws + vless-xhttp + vless-reality).
    """
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT server_id,
                   SUM(lifetime_rx) AS rx,
                   SUM(lifetime_tx) AS tx
            FROM vless_server_traffic
            GROUP BY server_id
            """
        ).fetchall()
        out: Dict[str, Dict] = {}
        for r in rows:
            rx = r["rx"] or 0
            tx = r["tx"] or 0
            out[r["server_id"]] = {"rx": rx, "tx": tx, "total": rx + tx}
        return out


def db_record_traffic_snapshot(samples: List[Dict]) -> None:
    """
    Сохраняет snapshot текущих rx/tx значений AmneziaWG-peer'ов.
    Вызывается каждые 5 мин из traffic_accounting.py после db_accumulate_traffic.

    samples — тот же формат что и в db_accumulate_traffic:
    [{"public_key": str, "telegram_id": int|None, "rx": int, "tx": int}, ...].

    Auto-cleanup: удаляет записи старше 14 дней при каждом вызове (cheap WHERE
    по индексу idx_traffic_snapshots_ts). 65k строк за 14 дней — SQLite это
    не нагружает.
    """
    _ensure_init()
    if not samples:
        return
    # timezone-aware UTC (Python 3.12+ deprecates utcnow); храним как
    # naive string в SQLite-формате, как и весь остальной datetime в БД.
    from datetime import timezone as _tz
    ts = datetime.now(_tz.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as con:
        for s in samples:
            pk = (s.get("public_key") or "").strip()
            if not pk:
                continue
            con.execute(
                """
                INSERT OR REPLACE INTO traffic_snapshots
                    (ts, public_key, telegram_id, rx, tx)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, pk, s.get("telegram_id"), int(s.get("rx") or 0), int(s.get("tx") or 0)),
            )
        con.execute(
            "DELETE FROM traffic_snapshots WHERE ts < datetime('now', '-14 days')"
        )


def db_query_traffic_delta(start_ts: str, end_ts: str) -> List[Dict]:
    """
    Возвращает delta-трафик per public_key за окно [start_ts, end_ts].
    delta = rx/tx в последней записи окна минус первая запись окна, per pubkey.

    Отрицательные значения = был reset (рестарт контейнера/перегенерация peer'а)
    — в этом случае возвращаем последнюю запись как нижнюю оценку прироста.

    Возвращает list of dict, отсортированный по убыванию (delta_rx + delta_tx).
    Полезно для «кто качал в окне X-Y».
    """
    _ensure_init()
    with _conn() as con:
        # Получаем для каждого peer'а первое и последнее значения в окне.
        rows = con.execute(
            """
            SELECT public_key, telegram_id,
                   MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                   COUNT(*) AS samples
            FROM traffic_snapshots
            WHERE ts >= ? AND ts <= ?
            GROUP BY public_key
            """,
            (start_ts, end_ts),
        ).fetchall()

        results = []
        for r in rows:
            first = con.execute(
                "SELECT rx, tx FROM traffic_snapshots WHERE ts = ? AND public_key = ?",
                (r["first_ts"], r["public_key"]),
            ).fetchone()
            last = con.execute(
                "SELECT rx, tx FROM traffic_snapshots WHERE ts = ? AND public_key = ?",
                (r["last_ts"], r["public_key"]),
            ).fetchone()
            if not first or not last:
                continue
            # reset-aware: если last < first, считаем что был reset и
            # delta = last (что прокачано после reset'а).
            delta_rx = last["rx"] - first["rx"] if last["rx"] >= first["rx"] else last["rx"]
            delta_tx = last["tx"] - first["tx"] if last["tx"] >= first["tx"] else last["tx"]
            results.append({
                "public_key": r["public_key"],
                "telegram_id": r["telegram_id"],
                "samples": r["samples"],
                "first_ts": r["first_ts"],
                "last_ts": r["last_ts"],
                "delta_rx": delta_rx,
                "delta_tx": delta_tx,
                "delta_total": delta_rx + delta_tx,
            })

        results.sort(key=lambda x: x["delta_total"], reverse=True)
        return results


def db_get_lifetime_by_user() -> Dict[int, Dict]:
    """
    Возвращает накопительный трафик по пользователям:
    {telegram_id: {"rx": int, "tx": int, "total": int}}.
    Суммирует по всем peer'ам пользователя (включая удалённые/перегенерированные).
    """
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT telegram_id,
                   SUM(lifetime_rx) AS rx,
                   SUM(lifetime_tx) AS tx
            FROM traffic_accounting
            WHERE telegram_id IS NOT NULL
            GROUP BY telegram_id
            """
        ).fetchall()
        out: Dict[int, Dict] = {}
        for r in rows:
            rx = r["rx"] or 0
            tx = r["tx"] or 0
            out[int(r["telegram_id"])] = {"rx": rx, "tx": tx, "total": rx + tx}
        return out


# ─── Subscription / billing / referral ──────────────────────────────────────────
# Фаза 0: модель аккаунта. Функции готовы, но НЕ вызываются из логики доступа
# (enforcement) — это включаем в Фазе 4. Сейчас доступ у всех без ограничений.

def db_get_subscription(telegram_id: int) -> Optional[Dict]:
    """Возвращает поля подписки/реферала пользователя или None."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT subscription_status, expires_at, trial_used, plan, "
            "referral_code, referred_by FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


def db_is_access_active(telegram_id: int) -> bool:
    """
    True если у пользователя активный доступ.
    expires_at IS NULL → grandfathered (legacy-юзеры до ввода биллинга, доступ без ограничения).
    Иначе доступ активен, пока now < expires_at (UTC).
    """
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT expires_at FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    if not row:
        return False
    exp = row["expires_at"]
    if not exp:
        return True  # grandfathered
    try:
        return datetime.utcnow() < datetime.fromisoformat(exp)
    except (ValueError, TypeError):
        return False


def db_extend_subscription(
    telegram_id: int,
    days: int,
    plan: Optional[str] = None,
    status: str = "active",
    device_limit: Optional[int] = None,
) -> Optional[str]:
    """
    Продлевает доступ на N дней от max(now, текущий expires_at).
    Возвращает новый expires_at (ISO). Используется и для оплаты, и для бонусов (реферал).
    `device_limit` (если задан) проставляет лимит устройств по тарифу; None —
    не трогаем (бонусы/реферал не меняют тариф).
    """
    _ensure_init()
    now = datetime.utcnow()
    with _conn() as con:
        row = con.execute(
            "SELECT expires_at FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not row:
            return None
        base = now
        if row["expires_at"]:
            try:
                cur = datetime.fromisoformat(row["expires_at"])
                if cur > now:
                    base = cur
            except (ValueError, TypeError):
                pass
        new_exp = (base + timedelta(days=days)).isoformat()
        # При каждом продлении сбрасываем флаги напоминаний — следующий цикл
        # должен получить свои T-7 / T-3 / T-0 события заново.
        con.execute(
            "UPDATE users SET expires_at = ?, subscription_status = ?, "
            "plan = COALESCE(?, plan), device_limit = COALESCE(?, device_limit), "
            "notif_7d_sent = 0, notif_3d_sent = 0, "
            "notif_0d_sent = 0 WHERE telegram_id = ?",
            (new_exp, status, plan, device_limit, telegram_id),
        )
    return new_exp


def db_get_device_limit(telegram_id: int) -> int:
    """Лимит устройств юзера по тарифу. Дефолт 5 (грандфазер/триал) если не задан/NULL."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT device_limit FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    if not row or row["device_limit"] is None:
        return 5
    try:
        return int(row["device_limit"])
    except (ValueError, TypeError):
        return 5


def db_start_trial(telegram_id: int, days: int) -> Optional[str]:
    """
    Активирует пробный период, если не использован. Возвращает expires_at или None.
    """
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT trial_used FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not row or row["trial_used"]:
            return None
    new_exp = db_extend_subscription(telegram_id, days, plan="trial", status="trial")
    if new_exp:
        with _conn() as con:
            con.execute(
                "UPDATE users SET trial_used = 1 WHERE telegram_id = ?", (telegram_id,)
            )
    return new_exp


def db_ensure_signup_trial(telegram_id: int, days: int = 14) -> Optional[str]:
    """
    Авто-активация триала при первой регистрации.
    Активирует только если:
      - expires_at IS NULL (т.е. не grandfather и не платил),
      - trial_used == 0 (не использовал ранее).
    Idempotent: для grandfather/триал-использованных/платящих ничего не делает.
    Возвращает новый expires_at или None.
    """
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT expires_at, trial_used FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] is not None:
            return None  # grandfather или уже есть подписка
        if row["trial_used"]:
            return None  # триал уже был
    return db_start_trial(telegram_id, days)


def db_ensure_referral_code(telegram_id: int) -> Optional[str]:
    """Возвращает реферальный код пользователя, создаёт уникальный если нет."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT referral_code FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not row:
            return None
        if row["referral_code"]:
            return row["referral_code"]
        for _ in range(10):
            code = secrets.token_urlsafe(6)[:8]
            exists = con.execute(
                "SELECT 1 FROM users WHERE referral_code = ?", (code,)
            ).fetchone()
            if not exists:
                con.execute(
                    "UPDATE users SET referral_code = ? WHERE telegram_id = ?",
                    (code, telegram_id),
                )
                return code
    return None


def db_get_user_by_referral_code(code: str) -> Optional[Dict]:
    """Находит пользователя по его реферальному коду."""
    _ensure_init()
    if not code:
        return None
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE referral_code = ?", (code,)
        ).fetchone()
        return dict(row) if row else None


def db_count_referrals(code: str) -> int:
    """Сколько пользователей пришло по этому реферальному коду."""
    _ensure_init()
    if not code:
        return 0
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE referred_by = ?", (code,)
        ).fetchone()
        return row["n"] if row else 0


def db_set_password(telegram_id: int, password_hash: str) -> None:
    """Устанавливает/меняет хэш пароля пользователя."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE users SET password_hash = ? WHERE telegram_id = ?",
            (password_hash, telegram_id),
        )


def db_has_password(telegram_id: int) -> bool:
    """True, если у пользователя установлен пароль."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT password_hash FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    return bool(row and row["password_hash"])


def db_ensure_sub_token(telegram_id: int) -> Optional[str]:
    """Возвращает стабильный токен subscription-ссылки пользователя, создаёт если нет."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT sub_token FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not row:
            return None
        if row["sub_token"]:
            return row["sub_token"]
        for _ in range(10):
            tok = secrets.token_hex(16)
            exists = con.execute(
                "SELECT 1 FROM users WHERE sub_token = ?", (tok,)
            ).fetchone()
            if not exists:
                con.execute(
                    "UPDATE users SET sub_token = ? WHERE telegram_id = ?",
                    (tok, telegram_id),
                )
                return tok
    return None


def db_find_user_by_sub_token(token: str) -> Optional[Dict]:
    """Находит пользователя по токену subscription-ссылки."""
    _ensure_init()
    if not token:
        return None
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE sub_token = ?", (token,)
        ).fetchone()
        return dict(row) if row else None


def db_set_referred_by(telegram_id: int, code: str) -> bool:
    """
    Привязывает пригласившего (по его referral_code), если ещё не привязан,
    код существует и это не сам пользователь. Возвращает True при успехе.
    """
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT referred_by, referral_code FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not row or row["referred_by"]:
            return False
        if row["referral_code"] and row["referral_code"] == code:
            return False  # нельзя пригласить самого себя
        inviter = con.execute(
            "SELECT 1 FROM users WHERE referral_code = ?", (code,)
        ).fetchone()
        if not inviter:
            return False
        con.execute(
            "UPDATE users SET referred_by = ? WHERE telegram_id = ?",
            (code, telegram_id),
        )
        return True


def db_record_payment(
    provider: str,
    amount: float,
    currency: str = "RUB",
    telegram_id: Optional[int] = None,
    email: Optional[str] = None,
    external_id: Optional[str] = None,
    plan: Optional[str] = None,
    days: Optional[int] = None,
    status: str = "pending",
) -> int:
    """Создаёт запись платежа. Возвращает её id."""
    _ensure_init()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO payments
                (telegram_id, email, provider, amount, currency, status,
                 external_id, plan, days, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (telegram_id, email, provider, amount, currency, status, external_id, plan, days),
        )
        return cur.lastrowid


def db_update_payment_status(external_id: str, status: str) -> bool:
    """Обновляет статус платежа по external_id провайдера."""
    _ensure_init()
    if not external_id:
        return False
    with _conn() as con:
        cur = con.execute(
            "UPDATE payments SET status = ?, updated_at = datetime('now') WHERE external_id = ?",
            (status, external_id),
        )
        return cur.rowcount > 0


def db_find_payment_by_external_id(external_id: str) -> Optional[Dict]:
    """Находит платёж по external_id провайдера (для idempotency)."""
    _ensure_init()
    if not external_id:
        return None
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM payments WHERE external_id = ? LIMIT 1",
            (external_id,),
        ).fetchone()
        return dict(row) if row else None


def db_apply_referral_bonus(telegram_id: int, reward_days: int) -> Optional[int]:
    """
    Если у telegram_id есть referred_by и бонус ещё не выплачен — продлевает обоим
    подписку на reward_days дней. Возвращает telegram_id пригласившего или None.
    Idempotent: при повторном вызове ничего не делает (флаг referral_bonus_paid).
    """
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT referred_by, referral_bonus_paid FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not row or row["referral_bonus_paid"] or not row["referred_by"]:
            return None
        inviter = con.execute(
            "SELECT telegram_id, active FROM users WHERE referral_code = ?",
            (row["referred_by"],),
        ).fetchone()
        if not inviter or not inviter["active"] or not inviter["telegram_id"]:
            return None
        inviter_tid = int(inviter["telegram_id"])
        # Помечаем как выплаченный СРАЗУ (защита от гонки при дубликате)
        con.execute(
            "UPDATE users SET referral_bonus_paid = 1 WHERE telegram_id = ?",
            (telegram_id,),
        )
    # Продлеваем обоим (вне транзакции, чтобы не держать блокировку SQLite)
    db_extend_subscription(telegram_id, days=reward_days, plan="referral_bonus")
    db_extend_subscription(inviter_tid, days=reward_days, plan="referral_bonus")
    return inviter_tid


# ── Donation-flow: payment claims ─────────────────────────────────────────────

def db_get_pending_claim(telegram_id: int) -> Optional[Dict]:
    """Возвращает текущую pending-заявку юзера (или None)."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM payment_claims WHERE telegram_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


def db_create_payment_claim(
    telegram_id: int,
    days: int = 30,
    source: str = "webapp",
    note: Optional[str] = None,
    device_limit: int = 5,
) -> Optional[int]:
    """
    Создаёт новую pending-заявку. Если уже есть pending — возвращает её id
    (не плодим дубликаты при повторных нажатиях). `device_limit` несёт тариф
    (3/5 устройств) до approve.
    """
    _ensure_init()
    existing = db_get_pending_claim(telegram_id)
    if existing:
        # Уже есть pending — обновляем тариф (последний выбор юзера побеждает),
        # не плодим дубли. id сохраняется → кнопки approve у владельца валидны.
        with _conn() as con:
            con.execute(
                "UPDATE payment_claims SET days = ?, device_limit = ? WHERE id = ?",
                (days, device_limit, int(existing["id"])),
            )
        return int(existing["id"])
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO payment_claims (telegram_id, days, device_limit, status, source, note)
            VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (telegram_id, days, device_limit, source, note),
        )
        return cur.lastrowid


def db_get_claim_by_id(claim_id: int) -> Optional[Dict]:
    """Возвращает заявку по id."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM payment_claims WHERE id = ? LIMIT 1", (claim_id,)
        ).fetchone()
        return dict(row) if row else None


def db_set_claim_notify_msg(claim_id: int, message_id: int) -> None:
    """Сохраняет message_id уведомления владельцу (для последующего edit_message_text)."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE payment_claims SET notify_msg_id = ? WHERE id = ?",
            (message_id, claim_id),
        )


def db_decide_claim(claim_id: int, status: str) -> Optional[Dict]:
    """
    Помечает claim как approved/declined и возвращает обновлённую запись.
    Возвращает None если заявка не найдена или уже не pending.
    """
    _ensure_init()
    if status not in ("approved", "declined"):
        raise ValueError("status must be 'approved' or 'declined'")
    with _conn() as con:
        cur = con.execute(
            "UPDATE payment_claims SET status = ?, decided_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            (status, claim_id),
        )
        if cur.rowcount == 0:
            return None
        row = con.execute(
            "SELECT * FROM payment_claims WHERE id = ?", (claim_id,)
        ).fetchone()
        return dict(row) if row else None


# ── Expiry notifications (cron) ───────────────────────────────────────────────

def db_users_due_for_expiry_notif(days_until: int) -> List[Dict]:
    """
    Возвращает юзеров, у которых:
      - подписка истекает через days_until календарных дней (округление до даты, не часа),
      - флаг notif_{days_until}d_sent ещё не выставлен,
      - expires_at IS NOT NULL (не grandfather).
    Используется cron-скриптом expiry_reminder.py.
    """
    _ensure_init()
    if days_until not in (7, 3, 0):
        raise ValueError("days_until must be 7, 3, or 0")
    flag_col = f"notif_{days_until}d_sent"
    today = datetime.utcnow().date()
    target = (today + timedelta(days=days_until)).isoformat()
    next_day = (today + timedelta(days=days_until + 1)).isoformat()
    with _conn() as con:
        rows = con.execute(
            f"SELECT telegram_id, email, expires_at FROM users "
            f"WHERE expires_at IS NOT NULL "
            f"AND date(expires_at) = date(?) "
            f"AND {flag_col} = 0 "
            f"AND telegram_id IS NOT NULL "
            f"AND active = 1",
            (target,),
        ).fetchall()
        # next_day помогает быть строгим к дате (на случай зон), но date(expires_at) уже округлит.
        _ = next_day
        return [dict(r) for r in rows]


def db_mark_migrated(telegram_id: int) -> bool:
    """
    Помечает юзера как «прошёл /start в новом боте». Idempotent.
    Возвращает True если флаг впервые выставлен (= это первый /start), False если уже был.
    """
    _ensure_init()
    with _conn() as con:
        cur = con.execute(
            "UPDATE users SET migrated_at = datetime('now') "
            "WHERE telegram_id = ? AND migrated_at IS NULL",
            (telegram_id,),
        )
        return cur.rowcount > 0


def db_is_migrated(telegram_id: int) -> bool:
    """True если у юзера выставлен migrated_at (т.е. он /start'нул новый бот)."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT migrated_at FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return bool(row and row["migrated_at"])


def db_get_non_migrated_users() -> List[Dict]:
    """
    Возвращает активных юзеров, у которых migrated_at IS NULL.
    Используется командой /migrate_reset для selective сброса конфигов.
    """
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, telegram_id, username, email, vless_uuid, sub_token "
            "FROM users "
            "WHERE active = 1 AND telegram_id IS NOT NULL "
            "AND migrated_at IS NULL "
            "ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def db_clear_sub_token(telegram_id: int) -> None:
    """Сбрасывает sub_token у юзера (для selective reset). Следующий вызов db_ensure_sub_token сгенерит новый."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE users SET sub_token = NULL WHERE telegram_id = ?",
            (telegram_id,),
        )


def db_clear_vless_uuid(telegram_id: int) -> None:
    """Сбрасывает vless_uuid у юзера (для selective reset)."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE users SET vless_uuid = NULL, vless_short_id = NULL WHERE telegram_id = ?",
            (telegram_id,),
        )


# ── Support tickets ───────────────────────────────────────────────────────────

def db_get_open_ticket(telegram_id: int) -> Optional[Dict]:
    """Возвращает текущий открытый тикет юзера (или None если нет)."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM support_tickets WHERE telegram_id = ? AND status = 'open' "
            "ORDER BY id DESC LIMIT 1",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None


def db_create_ticket(telegram_id: int) -> int:
    """Создаёт новый тикет. Если уже есть открытый — возвращает его id (idempotent)."""
    _ensure_init()
    existing = db_get_open_ticket(telegram_id)
    if existing:
        return int(existing["id"])
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO support_tickets (telegram_id, status) VALUES (?, 'open')",
            (telegram_id,),
        )
        return cur.lastrowid


def db_get_ticket_by_id(ticket_id: int) -> Optional[Dict]:
    """Возвращает тикет по id."""
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None


def db_close_ticket(ticket_id: int) -> None:
    """Закрывает тикет."""
    _ensure_init()
    with _conn() as con:
        con.execute(
            "UPDATE support_tickets SET status = 'closed', closed_at = datetime('now') "
            "WHERE id = ? AND status = 'open'",
            (ticket_id,),
        )


def db_add_support_message(
    ticket_id: int,
    sender: str,
    text: Optional[str] = None,
    photo_file_id: Optional[str] = None,
) -> int:
    """Добавляет сообщение в тикет. sender = 'user' | 'owner'. Возвращает id сообщения."""
    _ensure_init()
    if sender not in ("user", "owner"):
        raise ValueError("sender must be 'user' or 'owner'")
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO support_messages (ticket_id, sender, text, photo_file_id) "
            "VALUES (?, ?, ?, ?)",
            (ticket_id, sender, text, photo_file_id),
        )
        con.execute(
            "UPDATE support_tickets SET last_message_at = datetime('now') WHERE id = ?",
            (ticket_id,),
        )
        return cur.lastrowid


def db_get_ticket_messages(ticket_id: int, limit: int = 50) -> List[Dict]:
    """Возвращает сообщения тикета по возрастанию created_at."""
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM support_messages WHERE ticket_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (ticket_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def db_get_open_tickets() -> List[Dict]:
    """Список всех открытых тикетов (для /support_list админа)."""
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            "SELECT t.*, u.username, u.email "
            "FROM support_tickets t LEFT JOIN users u ON u.telegram_id = t.telegram_id "
            "WHERE t.status = 'open' "
            "ORDER BY COALESCE(t.last_message_at, t.created_at) DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def db_mark_expiry_notif_sent(telegram_id: int, days_until: int) -> None:
    """Помечает что напоминание T-{days_until} отправлено этому юзеру."""
    _ensure_init()
    if days_until not in (7, 3, 0):
        raise ValueError("days_until must be 7, 3, or 0")
    flag_col = f"notif_{days_until}d_sent"
    with _conn() as con:
        con.execute(
            f"UPDATE users SET {flag_col} = 1 WHERE telegram_id = ?",
            (telegram_id,),
        )
