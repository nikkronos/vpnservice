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

    stats = {"main_new": 0, "main_existing": 0, "yc_new": 0, "yc_existing": 0}

    for r in rows:
        tid = int(r["telegram_id"])
        username = r["username"] or "—"
        # main
        existing_main = db_get_per_user_vless_uuid(tid, "main")
        # yc
        existing_yc = db_get_per_user_vless_uuid(tid, "yc")

        if args.dry_run:
            tag_m = "existing" if existing_main else "WILL CREATE"
            tag_y = "existing" if existing_yc else "WILL CREATE"
            print(f"  tid={tid:<12} @{username:<20} main: {tag_m:<11} | yc: {tag_y}")
            if existing_main:
                stats["main_existing"] += 1
            else:
                stats["main_new"] += 1
            if existing_yc:
                stats["yc_existing"] += 1
            else:
                stats["yc_new"] += 1
            continue

        # Реальный backfill
        new_main = db_get_or_create_vless_uuid(tid, "main")
        if existing_main:
            stats["main_existing"] += 1
        else:
            stats["main_new"] += 1
            print(f"  tid={tid} @{username} → main UUID created: {new_main[:8]}...")

        new_yc = db_get_or_create_vless_uuid(tid, "yc")
        if existing_yc:
            stats["yc_existing"] += 1
        else:
            stats["yc_new"] += 1
            print(f"  tid={tid} @{username} → yc UUID created: {new_yc[:8]}...")

    print()
    print(f"{'=' * 60}")
    print(f"Stats:")
    print(f"  main: {stats['main_new']} new, {stats['main_existing']} existing")
    print(f"  yc:   {stats['yc_new']} new, {stats['yc_existing']} existing")
    if args.dry_run:
        print(f"\n[DRY RUN] Ничего не записано.")
    else:
        print(f"\nNext step: python3 scripts/sync_xray_users.py --all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
