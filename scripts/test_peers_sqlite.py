#!/usr/bin/env python3
"""
Self-contained тест консолидации peers.json → SQLite.

Работает на временной БД во временной папке — НИЧЕГО продакшн не трогает.
Проверяет:
  1. Авто-миграцию peers.json → таблица peers (init_db), включая нормализацию
     старого/среднего/нового форматов ключей и пропуск битых записей.
  2. Идемпотентность миграции (повторный прогон не плодит дубли).
  3. storage.get_all_peers() / find_peer_by_telegram_id() поверх БД.
  4. upsert_peer / delete_peer: запись в БД + dual-write зеркало peers.json.

Запуск (где есть python3):
    cd /opt/vpnservice && venv/bin/python scripts/test_peers_sqlite.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # Windows-консоль (cp1251) не должна ронять вывод на emoji/стрелках
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
    tmp = Path(tempfile.mkdtemp(prefix="peers_test_"))
    peers_json = tmp / "peers.json"

    # Синтетический peers.json со смесью форматов ключей.
    synthetic = {
        "111:eu1:pc": {"telegram_id": 111, "wg_ip": "10.8.1.11", "public_key": "PK111PC", "server_id": "eu1", "active": True, "platform": "pc"},
        "111:eu1:ios": {"telegram_id": 111, "wg_ip": "10.8.1.12", "public_key": "PK111IOS", "server_id": "eu1", "active": True, "platform": "ios"},
        "222:main": {"telegram_id": 222, "wg_ip": "10.0.0.22", "public_key": "PK222", "server_id": "main", "active": True},  # main→rus1, +pc
        "333": {"telegram_id": 333, "wg_ip": "10.8.1.33", "public_key": "PK333", "server_id": "eu1", "active": True},        # старый формат
        "444:eu1:android": {"telegram_id": 444, "wg_ip": "10.8.1.44", "public_key": "PK444", "server_id": "eu1", "active": False, "platform": "android"},
        "555:eu1:pc": {"telegram_id": 555, "wg_ip": "10.8.1.55", "server_id": "eu1", "active": True, "platform": "pc"},      # без public_key → пропуск
    }
    peers_json.write_text(json.dumps(synthetic, ensure_ascii=False, indent=2), encoding="utf-8")

    # Перенаправляем пути модулей на временную папку ДО любых вызовов.
    import bot.database as db
    import bot.storage as storage

    db.DATA_DIR = tmp
    db.DB_PATH = tmp / "vpn.db"
    db.USERS_JSON_PATH = tmp / "users.json"
    db.PEERS_JSON_PATH = peers_json
    db._db_initialized = False
    storage.DATA_DIR = tmp
    storage.PEERS_FILE = peers_json
    storage.USERS_FILE = tmp / "users.json"

    # ── 1. Миграция ─────────────────────────────────────────────────────────
    db.init_db()
    rows = db.db_get_all_peers()
    keys = {f'{r["telegram_id"]}:{r["server_id"]}:{r["platform"]}' for r in rows}

    print("1. Авто-миграция peers.json → SQLite")
    check("мигрировано 5 валидных слотов (битый 555 пропущен)", len(rows) == 5)
    check("111:eu1:pc присутствует", "111:eu1:pc" in keys)
    check("111:eu1:ios присутствует", "111:eu1:ios" in keys)
    check("222 нормализован main→rus1, +pc (222:rus1:pc)", "222:rus1:pc" in keys)
    check("333 старый формат → 333:eu1:pc", "333:eu1:pc" in keys)
    check("555 (без public_key) НЕ мигрирован", "555:eu1:pc" not in keys)
    p444 = next((r for r in rows if r["telegram_id"] == 444), None)
    check("444 active=False сохранён", p444 is not None and p444["active"] == 0)

    # ── 2. Идемпотентность ──────────────────────────────────────────────────
    db._migrate_peers_json_to_sqlite()
    check("повторная миграция не плодит дубли", len(db.db_get_all_peers()) == 5)

    print("\n2. storage API поверх БД")
    all_peers = storage.get_all_peers()
    check("get_all_peers() вернул 5", len(all_peers) == 5)

    exact = storage.find_peer_by_telegram_id(111, server_id="eu1", platform="pc")
    check("точная выборка 111/eu1/pc", exact is not None and exact.public_key == "PK111PC")

    prio = storage.find_peer_by_telegram_id(111, server_id="eu1")
    check("приоритет pc при server_id без platform", prio is not None and prio.platform == "pc")

    any_peer = storage.find_peer_by_telegram_id(333)
    check("поиск без server_id находит активный eu1", any_peer is not None and any_peer.server_id == "eu1")

    # ── 3. upsert + dual-write ──────────────────────────────────────────────
    print("\n3. upsert_peer / delete_peer + dual-write зеркало")
    storage.DUAL_WRITE_JSON = True  # включаем зеркало для теста capability (в проде Phase 3 = False)
    storage.upsert_peer(storage.Peer(
        telegram_id=888, wg_ip="10.8.1.88", public_key="PK888", server_id="eu1", active=True, platform="pc",
    ))
    rows_after = db.db_get_all_peers()
    check("upsert добавил строку в БД", any(r["telegram_id"] == 888 for r in rows_after))
    json_after = json.loads(peers_json.read_text(encoding="utf-8"))
    check("upsert зеркалирован в peers.json", "888:eu1:pc" in json_after)

    # update существующего (тот же ключ, новый pubkey)
    storage.upsert_peer(storage.Peer(
        telegram_id=888, wg_ip="10.8.1.88", public_key="PK888_NEW", server_id="eu1", active=True, platform="pc",
    ))
    upd = storage.find_peer_by_telegram_id(888, server_id="eu1", platform="pc")
    check("повторный upsert обновил pubkey (не дубль)", upd is not None and upd.public_key == "PK888_NEW")
    check("update не увеличил число строк", len(db.db_get_all_peers()) == 6)

    storage.delete_peer(888, "eu1", "pc")
    check("delete убрал из БД", not any(r["telegram_id"] == 888 for r in db.db_get_all_peers()))
    json_del = json.loads(peers_json.read_text(encoding="utf-8"))
    check("delete убрал из peers.json-зеркала", "888:eu1:pc" not in json_del)

    # ── 3b. DUAL_WRITE_JSON=False (прод-дефолт Phase 3): json НЕ пишется ──────
    storage.DUAL_WRITE_JSON = False
    storage.upsert_peer(storage.Peer(
        telegram_id=889, wg_ip="10.8.1.89", public_key="PK889", server_id="eu1", active=True, platform="pc",
    ))
    check("upsert при False добавил в БД", any(r["telegram_id"] == 889 for r in db.db_get_all_peers()))
    json_off = json.loads(peers_json.read_text(encoding="utf-8"))
    check("upsert при DUAL_WRITE_JSON=False НЕ пишет в peers.json", "889:eu1:pc" not in json_off)

    print()
    if _FAILED:
        print(f"❌ ПРОВАЛЕНО проверок: {_FAILED}")
        return 1
    print("✅ Все проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
