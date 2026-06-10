#!/usr/bin/env python3
"""
B0 (Фаза 2 B): тест миграции peers platform→device_id на ВРЕМЕННОЙ БД.
НИЧЕГО прод не трогает (temp-папка). Зелёный тест — гейт на прод-миграцию (B1).

Проверяет:
  1. Миграция: каждый старый слот (tid,server,platform) → строка в devices +
     строка в peers с device_id; os = старый platform.
  2. Клиентские ключи (wg_ip/public_key/active) сохранены 1:1 (старые .conf живут).
  3. Один юзер с pc+ios → 2 устройства (раньше — норма).
  4. НОВЫЙ ключ (tid,server,device_id) допускает 2 устройства ОДНОЙ ОС
     (раньше PK(tid,server,platform) коллизил — баг Ани). ← главная цель B.
  5. Идемпотентность: повторный прогон миграции — no-op.

Запуск:  py -3 scripts/test_per_device_migration.py
"""
from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_FAILED = 0


def check(name: str, cond: bool) -> None:
    global _FAILED
    print(f"  {'✅' if cond else '❌'} {name}")
    if not cond:
        _FAILED += 1


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="perdev_test_"))

    import bot.database as db
    db.DATA_DIR = tmp
    db.DB_PATH = tmp / "vpn.db"
    db.USERS_JSON_PATH = tmp / "users.json"
    db.PEERS_JSON_PATH = tmp / "peers.json"
    db._db_initialized = False

    # init_db создаёт ТЕКУЩУЮ (старую, platform) схему peers (peers.json нет → пусто)
    db.init_db()

    # Синтетические старые слоты (как на проде до B)
    old = [
        (111, "eu1", "pc", "10.8.1.11", "PK111PC", 1, None),
        (111, "eu1", "ios", "10.8.1.12", "PK111IOS", 1, None),   # тот же юзер, 2-я ОС
        (222, "rus1", "pc", "10.0.0.22", "PK222", 1, None),
        (444, "eu1", "android", "10.8.1.44", "PK444", 0, None),  # active=0 сохранить
    ]
    with db._conn() as c:
        for tid, sid, plat, ip, pk, act, pt in old:
            c.execute(
                "INSERT INTO peers (telegram_id, server_id, platform, wg_ip, public_key, "
                "active, profile_type, created_at, updated_at) VALUES (?,?,?,?,?,?,?,datetime('now'),NULL)",
                (tid, sid, plat, ip, pk, act, pt),
            )

    print("0. До миграции")
    with db._conn() as c:
        n_old = c.execute("SELECT COUNT(*) FROM peers").fetchone()[0]
    check("вставлено 4 старых слота", n_old == 4)

    # ── Миграция ──
    db._migrate_peers_platform_to_device()

    print("\n1. Структура после миграции")
    with db._conn() as c:
        pcols = {r[1] for r in c.execute("PRAGMA table_info(peers)").fetchall()}
        check("peers получил device_id", "device_id" in pcols)
        check("peers получил os", "os" in pcols)
        check("peers больше НЕ имеет platform", "platform" not in pcols)
        dev_tbls = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        check("таблица devices создана", "devices" in dev_tbls)
        n_dev = c.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        n_peer = c.execute("SELECT COUNT(*) FROM peers").fetchone()[0]
        check("devices = 4 (по одному на слот)", n_dev == 4)
        check("peers = 4 (1:1)", n_peer == 4)

    print("\n2. Данные клиента сохранены 1:1 (старые .conf живут)")
    with db._conn() as c:
        rows = {(r["telegram_id"], r["public_key"]): r for r in
                c.execute("SELECT telegram_id, public_key, wg_ip, active, os, device_id, server_id FROM peers").fetchall()}
        r_pc = rows.get((111, "PK111PC"))
        check("111/PK111PC: wg_ip + os=pc сохранены", r_pc is not None and r_pc["wg_ip"] == "10.8.1.11" and r_pc["os"] == "pc")
        r_ios = rows.get((111, "PK111IOS"))
        check("111/PK111IOS: os=ios сохранён", r_ios is not None and r_ios["os"] == "ios")
        r_444 = rows.get((444, "PK444"))
        check("444 active=0 сохранён, os=android", r_444 is not None and r_444["active"] == 0 and r_444["os"] == "android")
        r_222 = rows.get((222, "PK222"))
        check("222 server_id=rus1 сохранён", r_222 is not None and r_222["server_id"] == "rus1")

    print("\n3. У юзера 111 — 2 устройства (pc+ios)")
    with db._conn() as c:
        dev111 = c.execute("SELECT os FROM devices WHERE telegram_id=111").fetchall()
        oses = sorted(d["os"] for d in dev111)
        check("111 имеет 2 устройства os=[ios,pc]", oses == ["ios", "pc"])

    print("\n4. ГЛАВНОЕ: новый ключ допускает 2 устройства ОДНОЙ ОС (фикс Ани)")
    collision = False
    try:
        with db._conn() as c:
            new_dev = secrets.token_hex(4)
            c.execute("INSERT INTO devices (device_id, telegram_id, name, os) VALUES (?,?,?,?)",
                      (new_dev, 111, "iPad Ани", "ios"))
            c.execute(
                "INSERT INTO peers (telegram_id, server_id, device_id, os, wg_ip, public_key, active) "
                "VALUES (?,?,?,?,?,?,1)",
                (111, "eu1", new_dev, "ios", "10.8.1.13", "PK111IOS2"),
            )
    except Exception as e:  # noqa: BLE001
        collision = True
        print(f"     (коллизия: {e})")
    check("2-е iOS-устройство добавилось БЕЗ коллизии PK", not collision)
    with db._conn() as c:
        ios_cnt = c.execute("SELECT COUNT(*) FROM peers WHERE telegram_id=111 AND os='ios'").fetchone()[0]
    check("у 111 теперь 2 iOS-слота (раньше было невозможно)", ios_cnt == 2)

    print("\n5. Идемпотентность")
    try:
        db._migrate_peers_platform_to_device()  # device_id уже есть → no-op
        with db._conn() as c:
            n_after = c.execute("SELECT COUNT(*) FROM peers").fetchone()[0]
        check("повторная миграция — no-op (peers=5, без ошибок)", n_after == 5)
    except Exception as e:  # noqa: BLE001
        check(f"повторная миграция без ошибок (got {e})", False)

    print()
    if _FAILED:
        print(f"❌ ПРОВАЛЕНО проверок: {_FAILED}")
        return 1
    print("✅ Все проверки пройдены — миграция platform→device безопасна")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
