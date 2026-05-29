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

    # В awg show есть, в peers.json — нет. РАЗДЕЛЯЕМ на live и unused.
    # КРИТИЧНО (инцидент 2026-05-29): отсутствие в peers.json НЕ ЗНАЧИТ orphan.
    # Legacy/admin/owner peer-ы создавались до перехода на peers.json и тоже
    # отсутствуют в нём, но активно работают. Удаление таких peer-ов рвёт
    # рабочее подключение.
    not_in_json = awg_pubkeys - json_pubkeys
    live_outside_json: List[str] = []
    unused_outside_json: List[str] = []
    for pk in not_in_json:
        d = awg_details.get(pk, {})
        has_endpoint = d.get("endpoint", "(none)") != "(none)"
        has_traffic = (d.get("rx", 0) > 0) or (d.get("tx", 0) > 0)
        has_handshake = (d.get("last_handshake", 0) or 0) > 0
        if has_endpoint or has_traffic or has_handshake:
            live_outside_json.append(pk)
        else:
            unused_outside_json.append(pk)

    print(f"\n[⚠] LIVE peer-ы вне peers.json ({len(live_outside_json)})  —  НЕ УДАЛЯТЬ без анализа:")
    if live_outside_json:
        for pk in sorted(live_outside_json):
            d = awg_details.get(pk, {})
            hs = d.get("last_handshake", 0) or 0
            hs_str = f"last_hs={hs}" if hs else "last_hs=0"
            print(
                f"    {pk[:16]}…  ips={d.get('allowed_ips', '?')}  "
                f"endpoint={d.get('endpoint', '?')}  rx={d.get('rx', 0)}  tx={d.get('tx', 0)}  {hs_str}"
            )
        print("    ↳ это legacy/owner/admin peers — отражение в peers.json не обязательно, они РАБОТАЮТ.")
    else:
        print("    (нет — все живые runtime peer-ы отражены в peers.json)")

    print(f"\n[?] unused peer-ы вне peers.json ({len(unused_outside_json)})  —  можно зачистить:")
    if unused_outside_json:
        for pk in sorted(unused_outside_json):
            d = awg_details.get(pk, {})
            print(f"    {pk[:16]}…  ips={d.get('allowed_ips', '?')}  endpoint={d.get('endpoint', '?')}")
        print("    ↳ ВСЕГДА: сохрани pubkey + PSK в backup до `awg set ... remove`.")
    else:
        print("    (нет)")

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
    print(f"  LIVE вне peers.json  : {len(live_outside_json)} — НЕ ТРОГАТЬ")
    print(f"  unused вне peers.json: {len(unused_outside_json)} — можно чистить")
    print()
    print("ПРЕДУПРЕЖДЕНИЕ: при любом удалении peer обязательно сохрани")
    print("в backup: pubkey, allowed-ips, ENDPOINT, PSK (из /opt/amnezia/awg/")
    print("wireguard_psk.key — общий PSK на все peers интерфейса).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
