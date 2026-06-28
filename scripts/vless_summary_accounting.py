#!/usr/bin/env python3
"""
Периодический сэмплер VLESS-трафика → накопительный учёт в SQLite.

Запускается по cron каждые 5 минут на Fornex. Для каждого сервера (eu1
локально, main и yc через SSH) вызывает `xray api statsquery` и забирает:
  1. inbound>>>vless-*>>>traffic>>>uplink/downlink → vless_server_traffic
     (per-server aggregate — для шапки админки)
  2. user>>>tid_X@kronos>>>traffic>>>uplink/downlink → vless_user_traffic
     (per-user — для статуса юзеров в админке, доступно с 2026-06-03
     после Этапа 7 — добавили policy.levels.0.statsUser* + per-user UUIDs)

Накопление reset-aware (при рестарте Xray счётчики обнуляются, БД продолжает
копить lifetime).

eu1 пока без per-user телеметрии — там общие UUIDs ещё (отдельная задача).
Per-user пишется только для main/yc.
"""

import json
import pathlib
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.database import (
    db_accumulate_vless_server_traffic,
    db_accumulate_vless_user_traffic,
    init_db,
)

# Email-маркер per-user UUID: tid_<telegram_id>@kronos
_USER_EMAIL_RE = re.compile(r"^tid_(\d+)@kronos$")

# Команды SSH для удалённых серверов — те же опции что в health_check.py.
SSH_OPTS = [
    "-o", "ConnectTimeout=5",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ServerAliveInterval=3",
    "-o", "ServerAliveCountMax=1",
]
REMOTE_SSH: Dict[str, List[str]] = {
    "main": ["ssh", "-i", "/root/.ssh/id_ed25519_main"] + SSH_OPTS + ["root@81.200.146.32"],
    # yc убран 2026-06-28 (снос YC)
}

# Какие серверы пинговать (eu1 — локально, через docker/локальный xray).
XRAY_API_ADDR = "127.0.0.1:10085"


def _query_xray_stats(server: str, pattern: str) -> Optional[Dict]:
    """
    Универсальный wrapper для `xray api statsquery -pattern=...`.
    Возвращает parsed JSON `{"stat": [...]}` или None при ошибке.
    """
    try:
        if server == "eu1":
            r = subprocess.run(
                ["xray", "api", "statsquery",
                 f"--server={XRAY_API_ADDR}",
                 f"-pattern={pattern}"],
                capture_output=True, text=True, timeout=15,
            )
        else:
            ssh = REMOTE_SSH.get(server)
            if not ssh:
                print(f"vless_summary: unknown server {server}", flush=True)
                return None
            # SSH: pattern в одинарных кавычках чтобы `>>>` не интерпретировался shell
            remote_cmd = (
                f"xray api statsquery --server={XRAY_API_ADDR} "
                f"'-pattern={pattern}'"
            )
            r = subprocess.run(
                ssh + [remote_cmd],
                capture_output=True, text=True, timeout=15,
            )
    except subprocess.TimeoutExpired:
        print(f"vless_summary: timeout querying {server} pattern={pattern!r}", flush=True)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"vless_summary: error querying {server}: {e}", flush=True)
        return None

    if r.returncode != 0:
        print(f"vless_summary: {server} statsquery rc={r.returncode}: {r.stderr.strip()[:200]}", flush=True)
        return None

    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        print(f"vless_summary: {server} JSON parse error: {e}", flush=True)
        return None


def _query_inbound_samples(server: str) -> Optional[List[Dict]]:
    """Per-inbound (server-aggregate) samples — для vless_server_traffic."""
    data = _query_xray_stats(server, "inbound>>>vless")
    if data is None:
        return None
    by_tag: Dict[str, Dict[str, int]] = {}
    for stat in data.get("stat") or []:
        name = stat.get("name") or ""
        value = int(stat.get("value") or 0)
        parts = name.split(">>>")
        if len(parts) != 4 or parts[0] != "inbound" or parts[2] != "traffic":
            continue
        tag = parts[1]
        direction = parts[3]
        bucket = by_tag.setdefault(tag, {"rx": 0, "tx": 0})
        if direction == "uplink":
            bucket["rx"] = value
        elif direction == "downlink":
            bucket["tx"] = value
    return [
        {"inbound_tag": tag, "rx": v["rx"], "tx": v["tx"]}
        for tag, v in by_tag.items()
    ]


def _query_user_samples(server: str) -> Optional[List[Dict]]:
    """
    Per-user samples для main/yc — vless_user_traffic.
    Парсит email-маркеры `tid_<telegram_id>@kronos`.
    Возвращает [{"telegram_id": int, "rx": int, "tx": int}, ...].
    """
    data = _query_xray_stats(server, "user>>>")
    if data is None:
        return None
    by_tid: Dict[int, Dict[str, int]] = {}
    for stat in data.get("stat") or []:
        name = stat.get("name") or ""
        value = int(stat.get("value") or 0)
        # name: user>>>tid_<X>@kronos>>>traffic>>>uplink|downlink
        parts = name.split(">>>")
        if len(parts) != 4 or parts[0] != "user" or parts[2] != "traffic":
            continue
        m = _USER_EMAIL_RE.match(parts[1])
        if not m:
            continue
        tid = int(m.group(1))
        direction = parts[3]
        bucket = by_tid.setdefault(tid, {"rx": 0, "tx": 0})
        if direction == "uplink":
            bucket["rx"] = value
        elif direction == "downlink":
            bucket["tx"] = value
    return [
        {"telegram_id": tid, "rx": v["rx"], "tx": v["tx"]}
        for tid, v in by_tid.items()
    ]


def main() -> int:
    init_db()
    servers_processed = 0
    total_rx_tx_this_run = 0
    total_user_samples = 0

    for server in ["eu1", "main"]:  # yc убран 2026-06-28 (снос YC)
        # 1. Per-inbound aggregate (для шапки админки — vless_server_traffic)
        inbound_samples = _query_inbound_samples(server)
        if inbound_samples is None:
            continue
        servers_processed += 1
        db_accumulate_vless_server_traffic(server, inbound_samples)
        per_server = sum(s["rx"] + s["tx"] for s in inbound_samples)
        total_rx_tx_this_run += per_server
        tags_summary = ", ".join(
            f"{s['inbound_tag']}={(s['rx']+s['tx'])/1024**2:.1f}MB"
            for s in inbound_samples if (s["rx"] + s["tx"]) > 0
        ) or "all-zero"

        # 2. Per-user (для статуса VLESS-юзеров — vless_user_traffic).
        # Только main (eu1 пока на общих UUIDs, телеметрия = inbound-aggregate; yc убран 06-28).
        user_count = 0
        if server == "main":
            user_samples = _query_user_samples(server)
            if user_samples:
                db_accumulate_vless_user_traffic(server, user_samples)
                user_count = sum(1 for s in user_samples if (s["rx"] + s["tx"]) > 0)
                total_user_samples += user_count

        suffix = f", per-user={user_count} active" if server == "main" else ""
        print(f"vless_summary[{server}]: {tags_summary}{suffix}", flush=True)

    print(
        f"vless_summary: done — {servers_processed}/2 servers, "
        f"total rx+tx={total_rx_tx_this_run / 1024**2:.1f} MB, "
        f"per-user samples with traffic={total_user_samples}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
