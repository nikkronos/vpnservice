#!/usr/bin/env python3
"""
Поштучная forensics по VLESS-UUID на eu1, которые НЕ per-user (без tid_X@kronos).
Read-only. Цель: для каждого такого UUID понять ЧТО он — релей-инфра, мульти-
серверный кред или одиночный eu1 client-share-link, ПРЕЖДЕ чем что-то удалять.

Решающий метод — кросс-референс по ВСЕМ серверам (eu1/main/yc/yc2):
  - где UUID встречается как INBOUND client (точка входа);
  - где как OUTBOUND user — это РЕЛЕЙ-credential (yc/yc2 так ходят в eu1).
UUID, используемый хоть где-то как outbound → несущая инфра, НЕ удалять.
Это ровно тот шаг, который поймал бы 359e23cc до инцидента 2026-06-10.

Запуск на Fornex:
    cd /opt/vpnservice && venv/bin/python scripts/vless_uuid_forensics.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sync_xray_users import SERVERS, _ssh_read_file, CONFIG_PATH  # noqa: E402
from sync_eu1_vless import RELAY_PRESERVE  # noqa: E402

EU1_CONFIG = "/usr/local/etc/xray/config.json"
SERVERS_ALL = ["eu1", "main", "yc", "yc2"]


def read_config(server_id: str) -> dict:
    if server_id == "eu1":
        return json.loads(Path(EU1_CONFIG).read_text(encoding="utf-8"))
    cfg = SERVERS[server_id]
    return json.loads(_ssh_read_file(cfg["ssh"], CONFIG_PATH, sudo=cfg.get("sudo", "")))


def short(u: str | None) -> str:
    return (u or "")[:8]


def main() -> int:
    inbound_clients: dict = defaultdict(list)   # uuid -> [(server, tag, email)]
    outbound_users: dict = defaultdict(list)    # uuid -> [(server, tag->addr)]
    configs: dict = {}

    for srv in SERVERS_ALL:
        try:
            configs[srv] = read_config(srv)
        except Exception as e:  # noqa: BLE001
            print(f"  {srv}: ОШИБКА чтения — {str(e)[:120]}")
            continue
        cfg = configs[srv]
        for ib in cfg.get("inbounds", []):
            if ib.get("protocol") != "vless":
                continue
            tag = ib.get("tag", "?")
            for c in (ib.get("settings") or {}).get("clients") or []:
                inbound_clients[c.get("id")].append((srv, tag, c.get("email", "") or ""))
        for ob in cfg.get("outbounds", []):
            if ob.get("protocol") != "vless":
                continue
            tag = ob.get("tag", "?")
            for vn in (ob.get("settings") or {}).get("vnext") or []:
                addr = f"{vn.get('address')}:{vn.get('port')}"
                for u in vn.get("users") or []:
                    outbound_users[u.get("id")].append((srv, f"{tag}->{addr}"))

    # Все outbound-креды на всех серверах = вселенная релей-кредов
    print("=" * 72)
    print("РЕЛЕЙ-КРЕДЫ (vless OUTBOUND user-id на всех серверах)")
    print("=" * 72)
    if not outbound_users:
        print("  (нет vless-outbound ни на одном сервере)")
    for uid, places in outbound_users.items():
        print(f"  {short(uid)}…  → {', '.join(f'{s}:{d}' for s, d in places)}")

    # Целевые: eu1 inbound clients без @kronos (не per-user)
    eu1cfg = configs.get("eu1", {})
    targets: list = []
    seen: set = set()
    for ib in eu1cfg.get("inbounds", []):
        if ib.get("protocol") != "vless":
            continue
        for c in (ib.get("settings") or {}).get("clients") or []:
            uid = c.get("id")
            if "@kronos" in (c.get("email", "") or ""):
                continue
            if uid in seen:
                continue
            seen.add(uid)
            targets.append(uid)

    print("\n" + "=" * 72)
    print(f"НЕ-PER-USER UUID НА eu1: {len(targets)} шт — поштучный вердикт")
    print("=" * 72)
    counts = {"relay": 0, "multi": 0, "candidate": 0}
    for uid in targets:
        ib_here = inbound_clients.get(uid, [])
        ob_here = outbound_users.get(uid, [])
        eu1_tags = sorted({t for (s, t, e) in ib_here if s == "eu1"})
        other_srv = sorted({s for (s, t, e) in ib_here if s != "eu1"})

        if uid in RELAY_PRESERVE:
            verdict = "🔵 RELAY (известный, в RELAY_PRESERVE) — НЕ ТРОГАТЬ"
            counts["relay"] += 1
        elif ob_here:
            verdict = "🔵 RELAY (исп. как OUTBOUND: " + ", ".join(f"{s}:{d}" for s, d in ob_here) + ") — НЕ ТРОГАТЬ, добавить в RELAY_PRESERVE"
            counts["relay"] += 1
        elif other_srv:
            verdict = f"🟡 МУЛЬТИ-СЕРВЕР (также вход на {other_srv}) — разобрать, не удалять вслепую"
            counts["multi"] += 1
        else:
            verdict = "🟠 EU1-ONLY client-share — кандидат на удаление (далее: проверить трафик/liveness)"
            counts["candidate"] += 1

        print(f"\n  {short(uid)}…  eu1 inbounds={eu1_tags}")
        print(f"      {verdict}")

    print("\n" + "=" * 72)
    print(f"ИТОГ: relay/инфра={counts['relay']}  мульти-сервер={counts['multi']}  "
          f"eu1-only-кандидаты={counts['candidate']}")
    print("Удалять можно ТОЛЬКО 🟠 eu1-only — и то после проверки liveness (трафик).")
    print("(UUID — первые 8 символов; полные в конфигах на серверах.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
