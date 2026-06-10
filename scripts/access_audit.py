#!/usr/bin/env python3
"""
Аудит зон доступа (Phase 0 плана «закрыть фрод-зону»).

Перечисляет ВСЕ креды доступа на всех серверах и проверяет инвариант:
    каждый живой кред ↔ один активный юзер И отзываем.

Находит блайнд-споты ЗАМЕРОМ, а не на глаз. Read-only — ничего не меняет.

Каналы:
  - VLESS clients[] во всех inbound на eu1 (локально) / main / yc (SSH)
  - AmneziaWG peers в runtime (eu1) ↔ peers-table ↔ active users

Классификация VLESS-клиента (по email-маркеру tid_<N>@kronos):
  TRACKED  — tid в active-set (всё ок)
  EXPIRED  — tid в БД, но доступ неактивен (должен был уйти sync'ом → недоотзыв)
  ORPHAN   — tid вообще НЕ в БД (мусор)
  SHARED   — без tid-email (общий UUID) → ФРОД-поверхность

AWG-peer:
  TRACKED      — pubkey в peers-table, юзер активен
  EXPIRED      — pubkey в peers-table, юзер неактивен (недоотзыв)
  LEGACY-LIVE  — нет в таблице, но есть признаки жизни → owner/legacy, НЕ ТРОГАТЬ
  UNUSED       — нет в таблице, без признаков жизни

Запуск на Fornex:
    cd /opt/vpnservice && venv/bin/python scripts/access_audit.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # для импорта соседних скриптов

from sync_xray_users import SERVERS, _ssh_read_file, CONFIG_PATH  # noqa: E402
from sync_eu1_vless import RELAY_PRESERVE  # noqa: E402  релей-креды (yc/yc2→eu1), не фрод
from peers_sync_check import get_awg_dump  # noqa: E402
from bot.database import _conn, _ensure_init  # noqa: E402
from bot.storage import get_all_peers  # noqa: E402

EU1_CONFIG = "/usr/local/etc/xray/config.json"
TID_EMAIL_RE = re.compile(r"tid_(\d+)@kronos")


def _tids(where: str) -> Set[int]:
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            f"SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL {where}"
        ).fetchall()
    return {int(r["telegram_id"]) for r in rows}


def active_tids() -> Set[int]:
    # Тот же фильтр, что enforce_expired / sync_xray_users (grace 12h).
    return _tids("AND active=1 AND (expires_at IS NULL "
                 "OR datetime(expires_at) > datetime('now','-12 hours'))")


def read_config(server_id: str) -> dict:
    if server_id == "eu1":
        return json.loads(Path(EU1_CONFIG).read_text(encoding="utf-8"))
    cfg = SERVERS[server_id]
    return json.loads(_ssh_read_file(cfg["ssh"], CONFIG_PATH, sudo=cfg.get("sudo", "")))


def audit_vless(active: Set[int], in_db: Set[int]) -> Dict:
    out: Dict[str, dict] = {}
    for srv in ("eu1", "main", "yc", "yc2"):  # yc2 — клон yc, те же per-user UUID
        try:
            cfg = read_config(srv)
        except Exception as e:  # noqa: BLE001
            out[srv] = {"error": str(e)[:160]}
            continue
        rec = {"tracked": 0, "shared": 0, "relay": 0, "expired": [], "orphan": [], "inbounds": {}}
        for ib in cfg.get("inbounds", []):
            if ib.get("protocol") != "vless":
                continue
            tag = ib.get("tag", "?")
            s = {"tracked": 0, "shared": 0, "relay": 0, "expired": 0, "orphan": 0}
            for c in (ib.get("settings") or {}).get("clients") or []:
                if c.get("id") in RELAY_PRESERVE:
                    # релей-инфра (yc/yc2 → eu1 vless-ws), НЕ фрод — см. RELAY_PRESERVE
                    s["relay"] += 1
                    rec["relay"] += 1
                    continue
                m = TID_EMAIL_RE.search(c.get("email", "") or "")
                if not m:
                    s["shared"] += 1
                    rec["shared"] += 1
                    continue
                tid = int(m.group(1))
                if tid in active:
                    s["tracked"] += 1
                    rec["tracked"] += 1
                elif tid in in_db:
                    s["expired"] += 1
                    rec["expired"].append(tid)
                else:
                    s["orphan"] += 1
                    rec["orphan"].append(tid)
            rec["inbounds"][tag] = s
        out[srv] = rec
    return out


def audit_awg(active: Set[int]) -> Dict:
    try:
        awg_pubkeys, details = get_awg_dump()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:160]}
    try:
        peers = [p for p in get_all_peers() if p.server_id == "eu1" and p.active]
    except Exception as e:  # noqa: BLE001
        return {"error": f"get_all_peers: {str(e)[:120]}", "runtime": len(awg_pubkeys)}
    pk2tid = {(p.public_key or "").strip(): p.telegram_id for p in peers if p.public_key}
    res = {"runtime": len(awg_pubkeys), "peers_table": len(peers),
           "tracked": 0, "expired": 0, "legacy_live": 0, "unused": 0, "legacy_list": []}
    for pk in awg_pubkeys:
        if pk in pk2tid:
            res["tracked" if pk2tid[pk] in active else "expired"] += 1
        else:
            d = details.get(pk, {})
            alive = (d.get("endpoint", "(none)") not in ("(none)", "")) \
                or d.get("rx", 0) > 0 or d.get("tx", 0) > 0 or (d.get("last_handshake", 0) or 0) > 0
            if alive:
                res["legacy_live"] += 1
                res["legacy_list"].append(pk[:16])
            else:
                res["unused"] += 1
    return res


def _main_wg0_dump() -> Set[str]:
    """pubkey'и main wg0 runtime (legacy WireGuard на Timeweb)."""
    from sync_xray_users import _ssh_run, SERVERS  # noqa: E402
    pks: Set[str] = set()
    r = _ssh_run(SERVERS["main"]["ssh"], "wg show wg0 dump", timeout=15)
    if r.returncode == 0:
        for ln in r.stdout.strip().split("\n")[1:]:  # skip interface-line
            f = ln.split("\t")
            if f and f[0]:
                pks.add(f[0].strip())
    return pks


def audit_main_wg0() -> Dict:
    """
    main wg0 (legacy WireGuard, Timeweb) runtime peers. По факту 06-10 они ВНЕ
    таблицы peers (rus1-строки не совпадают с runtime). Классификация по жизни.
    """
    from sync_xray_users import _ssh_run, SERVERS  # noqa: E402
    try:
        r = _ssh_run(SERVERS["main"]["ssh"], "wg show wg0 dump", timeout=15)
        if r.returncode != 0:
            return {"error": (r.stderr or "wg show failed")[:120]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}
    res = {"runtime": 0, "live": 0, "dead": 0, "live_list": []}
    for ln in r.stdout.strip().split("\n")[1:]:
        f = ln.split("\t")
        if len(f) < 7:
            continue
        res["runtime"] += 1
        try:
            hs, rx, tx = int(f[4] or 0), int(f[5] or 0), int(f[6] or 0)
        except ValueError:
            hs = rx = tx = 0
        if hs > 0 or rx > 0 or tx > 0:
            res["live"] += 1
            res["live_list"].append(f"{f[0][:12]}…(tx={tx // 1024 // 1024}MB)")
        else:
            res["dead"] += 1
    return res


def audit_legacy_peer_rows(main_wg0_pks: Set[str]) -> Dict:
    """
    peer-table строки на серверах ВНЕ {eu1} (eu2/rus1/rus2 = legacy). Живы ли
    где-то в runtime (eu1-awg / main-wg0) или мёртвый DB-cruft (доступа не дают).
    """
    try:
        awg_pks, _ = get_awg_dump()
    except Exception:  # noqa: BLE001
        awg_pks = set()
    runtime_all = set(awg_pks) | set(main_wg0_pks)
    rows = [p for p in get_all_peers() if p.server_id not in ("eu1",)]
    res = {"rows": len(rows), "live_elsewhere": 0, "dead_cruft": 0,
           "by_server": {}, "dead_list": []}
    for p in rows:
        res["by_server"][p.server_id] = res["by_server"].get(p.server_id, 0) + 1
        pk = (p.public_key or "").strip()
        if pk and pk in runtime_all:
            res["live_elsewhere"] += 1
        else:
            res["dead_cruft"] += 1
            res["dead_list"].append(f"{p.server_id}:{p.telegram_id}")
    return res


def main() -> int:
    print("=" * 72)
    print("АУДИТ ЗОН ДОСТУПА (Phase 0)")
    print("=" * 72)
    active = active_tids()
    in_db = _tids("")
    print(f"Активных юзеров (доступ, grace 12h): {len(active)}  |  всего в БД: {len(in_db)}\n")

    print("── VLESS (по серверам / inbound) ──")
    v = audit_vless(active, in_db)
    tot_shared = tot_orphan = tot_expired = tot_relay = 0
    for srv, r in v.items():
        if "error" in r:
            print(f"  {srv}: ОШИБКА {r['error']}")
            continue
        print(f"  {srv}: tracked={r['tracked']} shared={r['shared']} relay={r.get('relay', 0)} "
              f"expired={len(r['expired'])} orphan={len(r['orphan'])}")
        for tag, s in r["inbounds"].items():
            flag = "  🔴" if (s["shared"] or s["expired"] or s["orphan"]) else ""
            relay_str = f" relay={s['relay']}" if s.get("relay") else ""
            print(f"      [{tag}] tracked={s['tracked']} shared={s['shared']}{relay_str} "
                  f"expired={s['expired']} orphan={s['orphan']}{flag}")
        if r["expired"]:
            print(f"      expired tids: {sorted(set(r['expired']))[:12]}")
        if r["orphan"]:
            print(f"      orphan tids: {sorted(set(r['orphan']))[:12]}")
        tot_shared += r["shared"]
        tot_relay += r.get("relay", 0)
        tot_orphan += len(set(r["orphan"]))
        tot_expired += len(set(r["expired"]))

    print("\n── AmneziaWG (eu1) ──")
    a = audit_awg(active)
    if "error" in a:
        print(f"  ОШИБКА: {a['error']}")
    else:
        print(f"  runtime={a['runtime']} peers-table={a['peers_table']} | "
              f"tracked={a['tracked']} expired={a['expired']} "
              f"legacy-live={a['legacy_live']} (НЕ ТРОГАТЬ) unused={a['unused']}")
        if a["legacy_list"]:
            print(f"      legacy-live pubkeys: {a['legacy_list']}")

    print("\n── WireGuard main (wg0, legacy Timeweb) ──")
    mw = audit_main_wg0()
    main_pks = _main_wg0_dump() if "error" not in mw else set()
    if "error" in mw:
        print(f"  ОШИБКА: {mw['error']}")
    else:
        print(f"  runtime={mw['runtime']} | live={mw['live']} (вне таблицы — НЕ атрибутированы) "
              f"dead={mw['dead']}")
        if mw["live_list"]:
            print(f"      live peers: {mw['live_list']}  ← untracked-зона, разобрать кто это")

    print("\n── Legacy peer-строки (server вне eu1) ──")
    lg = audit_legacy_peer_rows(main_pks)
    print(f"  строк={lg['rows']} by_server={lg['by_server']} | "
          f"live-где-то={lg['live_elsewhere']} мёртвый-cruft={lg['dead_cruft']}")
    if lg["dead_list"]:
        print(f"      DEAD-cruft (нет ни в одном runtime → можно чистить): {lg['dead_list']}")

    print("\n" + "=" * 72)
    print("ИТОГ — НЕОТСЛЕЖИВАЕМАЯ / НЕДООТЗЫВАЕМАЯ ПОВЕРХНОСТЬ")
    print("=" * 72)
    print(f"  VLESS RELAY   (инфра yc/yc2→eu1, НЕ фрод)   : {tot_relay}")
    print(f"  VLESS SHARED  (общие UUID — фрод-зона)      : {tot_shared}")
    print(f"  VLESS EXPIRED (в конфиге, но доступ истёк)  : {tot_expired}")
    print(f"  VLESS ORPHAN  (tid не в БД — мусор)         : {tot_orphan}")
    awg_exp = a.get("expired", 0) if "error" not in a else "?"
    awg_leg = a.get("legacy_live", 0) if "error" not in a else "?"
    print(f"  AWG EXPIRED   (в runtime, доступ истёк)     : {awg_exp}")
    print(f"  AWG legacy-live eu1 (вне таблицы, работают) : {awg_leg}  — известны, отдельно")
    mw_live = mw.get("live", 0) if "error" not in mw else "?"
    print(f"  WG main-wg0 live (вне таблицы, untracked)   : {mw_live}  — разобрать кто это")
    print(f"  Legacy peer-cruft (мёртвые DB-строки)       : {lg['dead_cruft']}  — можно чистить")
    problems = tot_shared + tot_expired + tot_orphan + (awg_exp if isinstance(awg_exp, int) else 0)
    print(f"\n  Проблемных кредов (SHARED+EXPIRED+ORPHAN)   : {problems}")
    print("  Цель миграции: довести SHARED/EXPIRED/ORPHAN до 0 (legacy-live AWG — разбирать вручную).")
    return 0 if problems == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
