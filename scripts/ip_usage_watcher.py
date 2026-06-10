#!/usr/bin/env python3
"""
iplimit-НАБЛЮДЕНИЕ (Фаза 2 A-Stage1, 2026-06-10) — ТОЛЬКО ЗАМЕР, без enforcement.

Парсит access-log Xray на ВСЕХ входах (eu1 локально + main/yc/yc2 по SSH),
вытаскивает (real client IP, telegram_id) из строк
    from <IP>:<port> accepted ... email: tid_<N>@kronos
и копит в таблицу ip_usage (upsert по (tid, ip)). Релей-строки (`from 127.0.0.1`,
yc/yc2 → eu1) пропускаются — там не реальный клиент.

Цель: за неделю собрать РЕАЛЬНОЕ распределение «сколько разных IP у юзера», чтобы
КАЛИБРОВАТЬ пороги анти-шеринга по данным, а не на глаз (урок инцидента 06-10).
distinct IP per юзер за окно = сигнал шеринга (разные люди/локации), НЕ счёт
устройств на одной сети.

Запуск (Fornex):
    cron:    venv/bin/python scripts/ip_usage_watcher.py            # парс+запись+prune
    отчёт:   venv/bin/python scripts/ip_usage_watcher.py --report   # распределение из БД
    превью:  venv/bin/python scripts/ip_usage_watcher.py --dry-run  # парс без записи
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

PARSE_WINDOW = "11 minutes ago"  # cron */10 + 1 мин overlap
RETENTION_HOURS = 48
REPORT_WINDOWS = (15, 60, 1440)  # минуты для distinct-IP отчёта
ALERT_DISTINCT_15M = 8           # явный шеринг для лога/отчёта (НЕ enforcement)

SSH_OPTS = ["-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
# server_id -> (ssh_argv|None локально, sudo-префикс)
ENTRY_SERVERS: Dict[str, Tuple[Optional[List[str]], str]] = {
    "eu1":  (None, ""),
    "main": (["ssh", "-i", "/root/.ssh/id_ed25519_main"] + SSH_OPTS + ["root@81.200.146.32"], ""),
    "yc":   (["ssh"] + SSH_OPTS + ["yc"], "sudo "),
    "yc2":  (["ssh"] + SSH_OPTS + ["yc2"], "sudo "),
}

LINE_RE = re.compile(r"from (\S+):\d+ accepted .*?email: tid_(\d+)@kronos")


def norm_ip(ip: str) -> str:
    ip = ip.strip("[]")
    if ":" in ip:  # IPv6 → /64 (приватные адреса в /64 крутятся — один девайс)
        return ":".join(ip.split(":")[:4]) + "::/64"
    return ip


def fetch_log_lines(server_id: str) -> List[str]:
    ssh_argv, sudo = ENTRY_SERVERS[server_id]
    remote = (f"{sudo}journalctl -u xray --since '{PARSE_WINDOW}' --no-pager "
              f"| grep -E 'accepted .*email: tid_'")
    try:
        if ssh_argv is None:
            r = subprocess.run(["sh", "-c", remote], capture_output=True, text=True, timeout=30)
        else:
            r = subprocess.run(ssh_argv + [remote], capture_output=True, text=True, timeout=30)
        return r.stdout.splitlines()
    except Exception as e:  # noqa: BLE001
        print(f"  {server_id}: ОШИБКА сбора лога — {str(e)[:120]}")
        return []


def parse_entries() -> List[Tuple[int, str, str]]:
    """Возвращает [(tid, ip, server_id), ...] из свежих логов всех входов."""
    out: List[Tuple[int, str, str]] = []
    for srv in ENTRY_SERVERS:
        lines = fetch_log_lines(srv)
        kept = 0
        for ln in lines:
            m = LINE_RE.search(ln)
            if not m:
                continue
            ip = norm_ip(m.group(1))
            if ip in ("127.0.0.1", "::1", "::1::/64"):  # релей/локальное — не клиент
                continue
            out.append((int(m.group(2)), ip, srv))
            kept += 1
        print(f"  {srv}: строк {len(lines)} → событий {kept}")
    return out


def record(entries: List[Tuple[int, str, str]]) -> int:
    from bot.database import _conn, _ensure_init
    _ensure_init()
    if not entries:
        return 0
    with _conn() as con:
        for tid, ip, srv in entries:
            con.execute(
                "INSERT INTO ip_usage (telegram_id, ip, server_id) VALUES (?, ?, ?) "
                "ON CONFLICT(telegram_id, ip) DO UPDATE SET "
                "  last_seen = datetime('now'), hits = hits + 1, server_id = excluded.server_id",
                (tid, ip, srv),
            )
        con.execute(
            f"DELETE FROM ip_usage WHERE last_seen < datetime('now', '-{RETENTION_HOURS} hours')"
        )
    return len(entries)


def report() -> None:
    from bot.database import _conn, _ensure_init
    _ensure_init()
    print("distinct IP на юзера (окна по last_seen):")
    with _conn() as con:
        for w in REPORT_WINDOWS:
            rows = con.execute(
                "SELECT telegram_id, COUNT(DISTINCT ip) AS d FROM ip_usage "
                "WHERE last_seen > datetime('now', ?) GROUP BY telegram_id "
                "HAVING d > 1 ORDER BY d DESC LIMIT 15",
                (f"-{w} minutes",),
            ).fetchall()
            label = f"{w}м" if w < 1440 else "24ч"
            top = ", ".join(f"{r['telegram_id']}:{r['d']}" for r in rows[:15]) or "—"
            flagged = [r["telegram_id"] for r in rows if w == 15 and r["d"] >= ALERT_DISTINCT_15M]
            print(f"  [{label}] >1 IP: {len(rows)} юзеров; топ: {top}")
            if flagged:
                print(f"      ⚠ ≥{ALERT_DISTINCT_15M} IP/15м (кандидаты на шеринг): {flagged}")
        total = con.execute("SELECT COUNT(*) FROM ip_usage").fetchone()[0]
        print(f"  всего строк в ip_usage: {total}")


def main() -> int:
    ap = argparse.ArgumentParser(description="iplimit observe — сбор IP↔юзер с логов входов (без enforcement)")
    ap.add_argument("--report", action="store_true", help="Показать распределение distinct-IP из БД")
    ap.add_argument("--dry-run", action="store_true", help="Парсить и показать, не писать")
    args = ap.parse_args()

    if args.report:
        report()
        return 0

    print(f"Сбор IP↔юзер за окно '{PARSE_WINDOW}' со всех входов:")
    entries = parse_entries()
    uniq_tids = len({t for t, _, _ in entries})
    uniq_ips = len({i for _, i, _ in entries})
    print(f"Итого событий: {len(entries)} (юзеров {uniq_tids}, IP {uniq_ips})")

    if args.dry_run:
        print("[DRY RUN] не пишем.")
        return 0

    n = record(entries)
    print(f"Записано/обновлено: {n}; retention {RETENTION_HOURS}ч применён.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
