#!/usr/bin/env python3
"""
Периодический сэмплер per-server VLESS-трафика → накопительный учёт в SQLite.

Запускается по cron каждые 5 минут на Fornex. Для каждого сервера (eu1
локально, main и yc через SSH) вызывает `xray api statsquery` и забирает
текущие значения `inbound>>>vless-*>>>traffic>>>uplink/downlink`. Накопление
reset-aware (как traffic_accounting.py для AWG) — при рестарте Xray счётчики
обнуляются, наша БД продолжает копить lifetime.

Per-USER телеметрию этот скрипт НЕ покрывает (на серверах общие UUIDs;
per-user UUID — отдельная задача в ROADMAP P2).

Зачем cron: API endpoint /api/stats не дёргает stats при каждом запросе
(SSH-вызовы дорогие), а cron гарантирует freshness независимо от того,
смотрит ли кто-то админку.
"""

import json
import pathlib
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.database import db_accumulate_vless_server_traffic, init_db

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
    "yc":   ["ssh"] + SSH_OPTS + ["yc"],
}

# Какие серверы пинговать (eu1 — локально, через docker/локальный xray).
XRAY_API_ADDR = "127.0.0.1:10085"


def _query_xray_stats(server: str) -> Optional[List[Dict]]:
    """
    Вызывает `xray api statsquery --server=127.0.0.1:10085 -pattern=inbound>>>vless`.
    Локально для eu1, через SSH для main/yc.

    Возвращает [{"inbound_tag": "vless-reality", "rx": int, "tx": int}, ...]
    или None при ошибке.
    """
    # `>>>` shell интерпретирует как redirect — для локального передаём argv
    # списком (без shell), для SSH — кавычим pattern.
    try:
        if server == "eu1":
            r = subprocess.run(
                ["xray", "api", "statsquery",
                 f"--server={XRAY_API_ADDR}",
                 "-pattern=inbound>>>vless"],
                capture_output=True, text=True, timeout=15,
            )
        else:
            ssh = REMOTE_SSH.get(server)
            if not ssh:
                print(f"vless_summary: unknown server {server}", flush=True)
                return None
            remote_cmd = (
                f"xray api statsquery --server={XRAY_API_ADDR} "
                f"'-pattern=inbound>>>vless'"
            )
            r = subprocess.run(
                ssh + [remote_cmd],
                capture_output=True, text=True, timeout=15,
            )
    except subprocess.TimeoutExpired:
        print(f"vless_summary: timeout querying {server}", flush=True)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"vless_summary: error querying {server}: {e}", flush=True)
        return None

    if r.returncode != 0:
        print(f"vless_summary: {server} statsquery rc={r.returncode}: {r.stderr.strip()[:200]}", flush=True)
        return None

    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        print(f"vless_summary: {server} JSON parse error: {e}", flush=True)
        return None

    # Группируем uplink/downlink в один sample на inbound_tag.
    # Имя счётчика: inbound>>>{tag}>>>traffic>>>{uplink|downlink}
    by_tag: Dict[str, Dict[str, int]] = {}
    for stat in data.get("stat") or []:
        name = stat.get("name") or ""
        value = int(stat.get("value") or 0)
        parts = name.split(">>>")
        if len(parts) != 4 or parts[0] != "inbound" or parts[2] != "traffic":
            continue
        tag = parts[1]
        direction = parts[3]  # uplink | downlink
        bucket = by_tag.setdefault(tag, {"rx": 0, "tx": 0})
        if direction == "uplink":
            bucket["rx"] = value
        elif direction == "downlink":
            bucket["tx"] = value

    samples = [
        {"inbound_tag": tag, "rx": v["rx"], "tx": v["tx"]}
        for tag, v in by_tag.items()
    ]
    return samples


def main() -> int:
    init_db()
    servers_processed = 0
    total_rx_tx_this_run = 0

    for server in ["eu1", "main", "yc"]:
        samples = _query_xray_stats(server)
        if samples is None:
            continue
        servers_processed += 1
        db_accumulate_vless_server_traffic(server, samples)
        per_server = sum(s["rx"] + s["tx"] for s in samples)
        total_rx_tx_this_run += per_server
        # Краткий per-server отчёт для journal.
        tags_summary = ", ".join(
            f"{s['inbound_tag']}={(s['rx']+s['tx'])/1024**2:.1f}MB"
            for s in samples if (s["rx"] + s["tx"]) > 0
        ) or "all-zero"
        print(f"vless_summary[{server}]: {tags_summary}", flush=True)

    print(
        f"vless_summary: done — {servers_processed}/3 servers, "
        f"total rx+tx={total_rx_tx_this_run / 1024**2:.1f} MB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
