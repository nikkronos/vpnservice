#!/usr/bin/env python3
"""
Диагностика рассинхрона peer-данных AmneziaWG (eu1).

Сравнивает три источника:
  1. БД (vpn.db) — `users` + связанные peer-ключи (если есть).
  2. peers.json — legacy storage, индексирован по telegram_id.
  3. `docker exec amnezia-awg2 awg show awg0 dump` — реальное состояние AWG.

Вывод:
  - Сводка по каждому источнику.
  - Множественные разницы (orphaned in DB / orphaned on server / lost after reboot).
  - Юзеры в БД без peer-а вообще (онбординг-стейдж).

Read-only — ничего не меняет.

Запуск на сервере:
    cd /opt/vpnservice && venv/bin/python scripts/peers_sync_check.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Подключаемся к проекту
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.storage import get_all_peers  # noqa: E402
from bot.database import db_get_all_users  # noqa: E402


AWG_CONTAINER = "amnezia-awg2"
AWG_INTERFACE = "awg0"


def get_awg_dump() -> Tuple[Set[str], Dict[str, dict]]:
    """
    Запускает `docker exec <container> awg show <iface> dump`.

    Returns:
        (set of public_keys, dict public_key → {endpoint, last_handshake, rx, tx, allowed_ips})
    """
    try:
        result = subprocess.run(
            ["docker", "exec", AWG_CONTAINER, "awg", "show", AWG_INTERFACE, "dump"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[!] Не удалось получить awg dump: {e}", file=sys.stderr)
        return set(), {}

    lines = result.stdout.strip().split("\n")
    # Первая строка — server info, остальные — peers.
    # Формат peer-строки: <pubkey>\t<psk>\t<endpoint>\t<allowed-ips>\t<last-hs>\t<rx>\t<tx>\t<keepalive>
    pubkeys: Set[str] = set()
    details: Dict[str, dict] = {}
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        pk = parts[0].strip()
        pubkeys.add(pk)
        try:
            details[pk] = {
                "endpoint": parts[2],
                "allowed_ips": parts[3],
                "last_handshake": int(parts[4]) if parts[4] else 0,
                "rx": int(parts[5]) if parts[5] else 0,
                "tx": int(parts[6]) if parts[6] else 0,
            }
        except (IndexError, ValueError):
            details[pk] = {"raw": line}
    return pubkeys, details


def main() -> int:
    print("=" * 70)
    print("AmneziaWG sync diagnostic (eu1)")
    print("=" * 70)

    # 1. peers.json — legacy storage
    json_peers = [p for p in get_all_peers() if p.server_id == "eu1"]
    json_active = [p for p in json_peers if p.active]
    json_pubkeys: Set[str] = {(p.public_key or "").strip() for p in json_active if p.public_key}
    json_pubkeys.discard("")

    print(f"\n[peers.json]  eu1 peers total: {len(json_peers)}  |  active: {len(json_active)}  |  unique pubkeys: {len(json_pubkeys)}")

    # 2. БД — users
    db_users = db_get_all_users()
    db_tids: Set[int] = {int(u["telegram_id"]) for u in db_users if u.get("telegram_id")}
    json_tids: Set[int] = {p.telegram_id for p in json_active}
    db_no_peer = db_tids - json_tids
    print(f"[vpn.db]      users total: {len(db_users)}  |  with telegram_id: {len(db_tids)}")
    print(f"              users БЕЗ AWG peer-а (eu1): {len(db_no_peer)}")

    # 3. awg show — runtime state
    awg_pubkeys, awg_details = get_awg_dump()
    print(f"[awg show]    peers in container: {len(awg_pubkeys)}")

    # === Сравнение множеств ===
    print("\n" + "=" * 70)
    print("РАЗНИЦЫ")
    print("=" * 70)

    # В peers.json есть, в awg show — нет (lost after reboot)
    lost_after_reboot = json_pubkeys - awg_pubkeys
    print(f"\n[?] peer в peers.json, но НЕТ в awg show ({len(lost_after_reboot)}):")
    if lost_after_reboot:
        for pk in sorted(lost_after_reboot):
            tids = [p.telegram_id for p in json_active if (p.public_key or "").strip() == pk]
            print(f"    {pk[:16]}…  tid={tids}")
    else:
        print("    (нет — все JSON peer-ы существуют в AWG runtime)")

    # В awg show есть, в peers.json — нет (orphans on server)
    orphans_on_server = awg_pubkeys - json_pubkeys
    print(f"\n[?] peer в awg show, но НЕТ в peers.json ({len(orphans_on_server)}):")
    if orphans_on_server:
        for pk in sorted(orphans_on_server):
            d = awg_details.get(pk, {})
            print(f"    {pk[:16]}…  allowed_ips={d.get('allowed_ips', '?')}  endpoint={d.get('endpoint', '?')}")
    else:
        print("    (нет — все runtime peer-ы отражены в JSON)")

    # Юзеры в БД без peer-а (онбординг или сброшенные)
    print(f"\n[?] users в БД БЕЗ AWG peer-а ({len(db_no_peer)}):")
    if db_no_peer:
        sample = list(db_no_peer)[:20]
        for tid in sample:
            user = next((u for u in db_users if int(u.get("telegram_id") or 0) == tid), None)
            if user:
                username = user.get("username") or "—"
                email = user.get("email") or "—"
                migrated = user.get("migrated_at") or "—"
                print(f"    tid={tid:<12}  @{username:<20}  email={email:<30}  migrated={migrated}")
        if len(db_no_peer) > 20:
            print(f"    … и ещё {len(db_no_peer) - 20}")
    else:
        print("    (все юзеры в БД имеют AWG peer)")

    # Совпадения
    matched = json_pubkeys & awg_pubkeys
    print(f"\n[OK] совпадает в peers.json и awg show: {len(matched)}")

    # === Итоговая сводка ===
    print("\n" + "=" * 70)
    print("ИТОГ")
    print("=" * 70)
    print(f"  users в БД           : {len(db_users)}")
    print(f"  peer-ов в peers.json : {len(json_active)} (active eu1)")
    print(f"  peer-ов в awg runtime: {len(awg_pubkeys)}")
    print(f"  users без AWG peer-а : {len(db_no_peer)}")
    print(f"  lost after reboot    : {len(lost_after_reboot)}")
    print(f"  orphans on server    : {len(orphans_on_server)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
