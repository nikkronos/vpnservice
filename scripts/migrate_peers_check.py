#!/usr/bin/env python3
"""
Верификатор миграции peers.json → SQLite (таблица `peers`).

Сама миграция идемпотентна и выполняется автоматически в
`bot.database.init_db()` (`_migrate_peers_json_to_sqlite`). Этот скрипт —
страховка вокруг неё: бэкап критичных файлов ДО и сверка ПОСЛЕ.

Что делает:
  1. (--backup) копирует peers.json + vpn.db в timestamped-бэкапы.
  2. Считает «ожидаемые» слоты из peers.json (нормализованные, с wg_ip+pubkey).
  3. Считает фактические слоты из таблицы peers (db_get_all_peers).
  4. Печатает diff: что есть в JSON но нет в таблице, и наоборот.

Read-only по данным (кроме --backup, который только копирует файлы).
Exit 0 — источники консистентны; exit 1 — есть расхождение.

Запуск на сервере:
    cd /opt/vpnservice && venv/bin/python scripts/migrate_peers_check.py            # сверка
    cd /opt/vpnservice && venv/bin/python scripts/migrate_peers_check.py --backup   # бэкап + сверка
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import storage  # noqa: E402
from bot.database import DB_PATH, db_get_all_peers  # noqa: E402


def _json_expected_keys() -> Dict[str, dict]:
    """Слоты из peers.json, нормализованные так же, как делает миграция."""
    raw = storage._load_raw(storage.PEERS_FILE)
    normalized = storage._migrate_peers_json_on_load(raw)
    out: Dict[str, dict] = {}
    for key, payload in normalized.items():
        parts = str(key).split(":")
        try:
            tid = int(payload.get("telegram_id", parts[0]))
        except (ValueError, TypeError):
            continue
        sid = storage.normalize_peer_server_id(
            payload.get("server_id", parts[1] if len(parts) > 1 else "rus1")
        )
        plat = storage._normalize_platform(
            payload.get("platform", parts[2] if len(parts) > 2 else "pc")
        )
        if not payload.get("wg_ip") or not payload.get("public_key"):
            continue
        out[f"{tid}:{sid}:{plat}"] = payload
    return out


def _table_keys() -> Set[str]:
    keys: Set[str] = set()
    for r in db_get_all_peers():
        sid = storage.normalize_peer_server_id(r.get("server_id"))
        plat = storage._normalize_platform(r.get("platform"))
        keys.add(f'{r["telegram_id"]}:{sid}:{plat}')
    return keys


def _backup() -> None:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    for src in (Path(storage.PEERS_FILE), Path(DB_PATH)):
        if src.exists():
            dst = src.with_name(f"{src.name}.bak.{ts}")
            shutil.copy2(src, dst)
            print(f"[backup] {src.name} → {dst.name}")
        else:
            print(f"[backup] пропуск (нет файла): {src}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Верификатор миграции peers.json → SQLite")
    ap.add_argument("--backup", action="store_true", help="скопировать peers.json + vpn.db в бэкапы")
    args = ap.parse_args()

    if args.backup:
        _backup()

    json_map = _json_expected_keys()
    json_keys = set(json_map.keys())
    table_keys = _table_keys()

    only_json = sorted(json_keys - table_keys)
    only_table = sorted(table_keys - json_keys)

    print(f"\npeers.json (валидных слотов): {len(json_keys)}")
    print(f"таблица peers (строк):        {len(table_keys)}")
    print(f"совпадает:                    {len(json_keys & table_keys)}")

    if only_json:
        print(f"\n⚠ В peers.json есть, в таблице НЕТ ({len(only_json)}):")
        for k in only_json:
            print(f"    {k}")
    if only_table:
        # Норма после Phase 3 / при ручных правках; до Phase 3 быть не должно.
        print(f"\nℹ В таблице есть, в peers.json НЕТ ({len(only_table)}):")
        for k in only_table:
            print(f"    {k}")

    if only_json:
        print("\nРЕЗУЛЬТАТ: ❌ расхождение (есть слоты в JSON, не попавшие в таблицу)")
        return 1
    print("\nРЕЗУЛЬТАТ: ✅ все слоты peers.json присутствуют в таблице")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
