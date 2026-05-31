#!/usr/bin/env python3
"""
Диагностика трафика AmneziaWG за временное окно: кто качал, сколько.

Источник: таблица traffic_snapshots (заполняется traffic_accounting.py каждые 5 мин,
хранится 14 дней). См. db_record_traffic_snapshot / db_query_traffic_delta.

Использование:
    # Окно "вчера 20-21 МСК" (= 17-18 UTC)
    python3 scripts/traffic_diagnosis.py 2026-05-30 17:00 2026-05-30 18:00

    # Окно "последний час" — короткий вариант
    python3 scripts/traffic_diagnosis.py --last 1h

    # Окно "последние 30 минут"
    python3 scripts/traffic_diagnosis.py --last 30m

Время — UTC (как пишется в БД). МСК = UTC+3.

Вывод: top-15 пользователей по приросту трафика за окно + сводка за окно
(общий объём, средняя скорость, пиковая по 5-минутному интервалу).
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.database import db_query_traffic_delta, _conn, _ensure_init  # type: ignore


def _parse_last(spec: str) -> tuple[str, str]:
    """'1h' / '30m' / '2d' → (start_ts, end_ts) в UTC."""
    m = re.fullmatch(r"(\d+)([hmd])", spec.strip())
    if not m:
        raise SystemExit(f"--last format: '1h' / '30m' / '2d', got: {spec}")
    n, unit = int(m.group(1)), m.group(2)
    delta = {"h": timedelta(hours=n), "m": timedelta(minutes=n), "d": timedelta(days=n)}[unit]
    end = datetime.now(timezone.utc)
    start = end - delta
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


def _fmt_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b/1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"


def _resolve_user(telegram_id):
    """telegram_id → 'username (tid)' для красивого вывода."""
    if not telegram_id:
        return "—"
    _ensure_init()
    with _conn() as con:
        row = con.execute(
            "SELECT username FROM users WHERE telegram_id = ?",
            (int(telegram_id),),
        ).fetchone()
        if row and row["username"]:
            return f"@{row['username']} ({telegram_id})"
        return f"id{telegram_id}"


def _peak_5min(start_ts: str, end_ts: str) -> tuple[str, int]:
    """
    Возвращает (ts_бакета, total_bytes_в_бакете) — 5-минутный интервал с пиковой
    суммарной скоростью в окне. Полезно для «когда внутри окна был пик».
    """
    _ensure_init()
    with _conn() as con:
        # Группируем snapshots по ts → суммируем rx+tx → diff с предыдущим ts.
        rows = con.execute(
            """
            SELECT ts, SUM(rx + tx) AS total
            FROM traffic_snapshots
            WHERE ts >= ? AND ts <= ?
            GROUP BY ts
            ORDER BY ts
            """,
            (start_ts, end_ts),
        ).fetchall()
        if len(rows) < 2:
            return ("—", 0)
        peak_ts, peak_delta = "—", 0
        for i in range(1, len(rows)):
            d = rows[i]["total"] - rows[i - 1]["total"]
            if d > peak_delta:
                peak_delta = d
                peak_ts = rows[i]["ts"]
        return (peak_ts, peak_delta)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Диагностика трафика AWG: кто качал в окне.",
        epilog="Время в UTC. МСК = UTC+3.",
    )
    parser.add_argument("start", nargs="?", help="Дата начала (YYYY-MM-DD)")
    parser.add_argument("start_time", nargs="?", help="Время начала (HH:MM)")
    parser.add_argument("end", nargs="?", help="Дата конца (YYYY-MM-DD)")
    parser.add_argument("end_time", nargs="?", help="Время конца (HH:MM)")
    parser.add_argument("--last", help="Удобный shortcut: 1h / 30m / 2d")
    parser.add_argument("--top", type=int, default=15, help="Top-N юзеров (default 15)")
    args = parser.parse_args()

    if args.last:
        start_ts, end_ts = _parse_last(args.last)
    elif args.start and args.start_time and args.end and args.end_time:
        start_ts = f"{args.start} {args.start_time}:00"
        end_ts = f"{args.end} {args.end_time}:00"
    else:
        parser.print_help()
        return 1

    print(f"Window: {start_ts} .. {end_ts} (UTC)")

    results = db_query_traffic_delta(start_ts, end_ts)

    if not results:
        print("\nNo snapshots in window. (Может быть окно вне 14-дневного retention,")
        print("или traffic_accounting cron не запускался.)")
        return 0

    # Сводка
    total_bytes = sum(r["delta_total"] for r in results)
    window_sec = (
        datetime.strptime(end_ts, "%Y-%m-%d %H:%M:%S")
        - datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
    ).total_seconds()
    avg_mbps = (total_bytes * 8 / window_sec / 1024**2) if window_sec > 0 else 0

    peak_ts, peak_bytes = _peak_5min(start_ts, end_ts)
    peak_mbps = peak_bytes * 8 / 300 / 1024**2  # 5-min bucket = 300s

    print(f"\n=== Сводка за окно ===")
    print(f"Всего за окно: {_fmt_bytes(total_bytes)} ({avg_mbps:.1f} Мбит/с средняя)")
    print(f"Пик (5-мин бакет): {_fmt_bytes(peak_bytes)} в {peak_ts} (~{peak_mbps:.0f} Мбит/с)")

    # Агрегация per telegram_id (у юзера может быть несколько peer'ов при
    # обновлении конфига). Если telegram_id NULL — сохраняем pubkey как ключ.
    by_user: dict = {}
    for r in results:
        key = r["telegram_id"] or f"pk:{r['public_key'][:16]}"
        bucket = by_user.setdefault(key, {
            "telegram_id": r["telegram_id"],
            "delta_rx": 0, "delta_tx": 0, "delta_total": 0,
            "peers": 0,
        })
        bucket["delta_rx"] += r["delta_rx"]
        bucket["delta_tx"] += r["delta_tx"]
        bucket["delta_total"] += r["delta_total"]
        bucket["peers"] += 1
    aggregated = sorted(by_user.values(), key=lambda x: x["delta_total"], reverse=True)

    # Top-N юзеров
    print(f"\n=== Top-{args.top} по приросту трафика (агрегировано per юзер) ===")
    print(f"{'#':>3}  {'user':<28}  {'rx':>10}  {'tx':>10}  {'total':>10}  {'peers':>5}")
    print("-" * 80)
    for i, r in enumerate(aggregated[: args.top], start=1):
        user = _resolve_user(r["telegram_id"])[:28]
        suffix = f" ({r['peers']} peers)" if r["peers"] > 1 else ""
        print(
            f"{i:>3}  {user:<28}  "
            f"{_fmt_bytes(r['delta_rx']):>10}  "
            f"{_fmt_bytes(r['delta_tx']):>10}  "
            f"{_fmt_bytes(r['delta_total']):>10}  "
            f"{r['peers']:>5}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
