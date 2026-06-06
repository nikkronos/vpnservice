#!/usr/bin/env python3
"""
Backfill: генерирует per-user VLESS UUIDs для всех active юзеров с telegram_id.
Только БД-операция — Xray-config синхронизируется отдельно через sync_xray_users.py.

Idempotent: для юзеров с уже выданным UUID — пропуск, повторно не создаёт.

Запуск (один раз перед удалением shared UUIDs):
    python3 scripts/vless_uuid_backfill.py [--dry-run]

После backfill:
    python3 scripts/sync_xray_users.py --all
    → broadcast → 48 ч → python3 scripts/sync_xray_users.py --all --no-shared
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill per-user VLESS UUIDs")
    parser.add_argument("--dry-run", action="store_true", help="Не пишет в БД, только показывает counts")
    args = parser.parse_args()

    from bot.database import (
        _conn, _ensure_init,
        db_get_or_create_vless_uuid, db_get_per_user_vless_uuid,
    )

    _ensure_init()

    # Все active юзеры с telegram_id
    with _conn() as con:
        rows = con.execute(
            "SELECT telegram_id, username FROM users "
            "WHERE telegram_id IS NOT NULL AND active = 1 "
            "ORDER BY telegram_id"
        ).fetchall()
    print(f"Active users with telegram_id: {len(rows)}")

    # eu1 добавлен 2026-06-06 (Этап 2 закрытия фрод-зоны — перевод eu1 на per-user).
    SERVERS = ["main", "yc", "eu1"]
    stats = {s: {"new": 0, "existing": 0} for s in SERVERS}

    for r in rows:
        tid = int(r["telegram_id"])
        username = r["username"] or "—"
        for s in SERVERS:
            existing = db_get_per_user_vless_uuid(tid, s)
            if args.dry_run:
                stats[s]["existing" if existing else "new"] += 1
                continue
            new = db_get_or_create_vless_uuid(tid, s)
            if existing:
                stats[s]["existing"] += 1
            else:
                stats[s]["new"] += 1
                print(f"  tid={tid} @{username} → {s} UUID created: {new[:8]}...")

    print()
    print(f"{'=' * 60}")
    print("Stats:")
    for s in SERVERS:
        print(f"  {s:<4}: {stats[s]['new']} new, {stats[s]['existing']} existing")
    if args.dry_run:
        print("\n[DRY RUN] Ничего не записано.")
    else:
        print("\nNext step: расширить sync_xray_users на eu1 → sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
