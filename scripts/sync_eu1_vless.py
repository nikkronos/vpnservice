#!/usr/bin/env python3
"""
Sync per-user VLESS UUIDs в eu1 Xray config (Этап 2 закрытия фрод-зоны, 2026-06-06).

eu1 — ЛОКАЛЬНЫЙ (скрипт гоняется на Fornex, который и есть eu1), 3 VLESS inbound:
  vless-tcp (REALITY 443, flow=vision) / vless-ws (CDN /vpn) / vless-xhttp.
Source of truth — users.vless_uuid_eu1 (backfill сделан 2026-06-06).

ВАРИАНТ A (решение владельца): CDN-канал обхода СОХРАНЯЕМ — per-user-им все inbound,
ничего из методов обхода не удаляем.

⛔⛔ ИНЦИДЕНТ 2026-06-10 — НЕ ЗАПУСКАТЬ `--no-shared` ВСЛЕПУЮ ⛔⛔
eu1 vless-ws — НЕ только клиентский CDN-канал, но и ПРИЁМНИК РЕЛЕЯ:
**yc и yc2 (Яндекс-входы) релеят ВЕСЬ трафик в eu1 vless-ws** (их outbound vless+ws
→ 185.21.8.91:80/vpn). Релей-credential = `359e23cc-f90c-4e43-97af-bd1b662ff043`
(RELAY_PRESERVE ниже). У него НЕТ tid-email → access_audit метит его «SHARED», но
это НЕ фрод, а несущая инфра. `--no-shared` 06-10 снёс его → выход Европы (yc/yc2)
перерубило, откатывали из бэкапа. Урок: [[feedback_no_delete_runtime_blind]].
Теперь RELAY_PRESERVE бережётся ВСЕГДА; `--no-shared` требует `--force`. Прочие
eu1-shared (9 на vless-tcp) — статус не доказан, не трогать без поштучной проверки.

Режимы:
  (default = grace): per-user clients ДОБАВЛЯЮТСЯ, существующие (legacy/shared)
                     СОХРАНЯЮТСЯ → старые ссылки работают до broadcast+грейса.
  --no-shared:       только per-user (после грейса старые/shared удаляются).
  --dry-run:         показать, не применять.

Отдельный скрипт (НЕ sync_xray_users) — чтобы не рисковать рабочим main/yc sync.
Источник истины тот же фильтр active (grace 12h), что enforce_expired / sync_xray_users.

Запуск на Fornex (root):
    cd /opt/vpnservice && venv/bin/python scripts/sync_eu1_vless.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CONFIG = "/usr/local/etc/xray/config.json"
DB_COLUMN = "vless_uuid_eu1"
# tag → flow. ОТКАТ 2026-06-06: xHTTP-миграция оказалась впустую (проблема не транспорт,
# а IP-блок), вернули tcp+vision. vless-tcp = REALITY tcp с vision; ws/xhttp без flow.
INBOUNDS = {
    "vless-tcp": "xtls-rprx-vision",
    "vless-ws": "",
    "vless-xhttp": "",
}

# UUID, которые НИКОГДА не удаляются (даже в --no-shared) — несущая инфра, не фрод.
# 359e23cc… = релей-credential: yc И yc2 релеят весь трафик в eu1 vless-ws этим UUID.
# Снос (инцидент 2026-06-10) → выход Европы умирает. См. докстринг сверху.
RELAY_PRESERVE = {
    "359e23cc-f90c-4e43-97af-bd1b662ff043",  # yc/yc2 → eu1 vless-ws relay
}


def fetch_active_users() -> list[dict]:
    """active=1, доступ в силе (grace 12h), есть vless_uuid_eu1 — как enforce_expired."""
    from bot.database import _conn, _ensure_init
    _ensure_init()
    with _conn() as con:
        rows = con.execute(
            f"SELECT telegram_id, {DB_COLUMN} AS uuid FROM users "
            f"WHERE telegram_id IS NOT NULL AND active=1 AND {DB_COLUMN} IS NOT NULL "
            f"  AND (expires_at IS NULL "
            f"       OR datetime(expires_at) > datetime('now','-12 hours'))"
        ).fetchall()
    return [{"tid": int(r["telegram_id"]), "uuid": r["uuid"]} for r in rows]


def build_clients(users: list[dict], flow: str, existing: list[dict], include_shared: bool) -> list[dict]:
    per_user_uuids = {u["uuid"] for u in users}
    clients: list[dict] = []
    for u in users:
        c = {"id": u["uuid"], "email": f"tid_{u['tid']}@kronos"}
        if flow:
            c["flow"] = flow
        clients.append(c)
    if include_shared:
        # грейс: сохраняем существующих НЕ-per-user (legacy/shared) — старые ссылки живут
        for c in existing:
            if c.get("id") not in per_user_uuids:
                clients.append(c)
    else:
        # --no-shared: shared снимаем, НО релей-credential'ы (RELAY_PRESERVE) бережём
        # ВСЕГДА — иначе перерубается выход Европы (yc/yc2 → eu1). Инцидент 2026-06-10.
        for c in existing:
            if c.get("id") in RELAY_PRESERVE and c.get("id") not in per_user_uuids:
                clients.append(c)
    # dedup по id
    seen, out = set(), []
    for c in clients:
        cid = c.get("id")
        if cid in seen:
            continue
        seen.add(cid)
        out.append(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync per-user VLESS UUIDs в eu1 Xray config")
    ap.add_argument("--no-shared", action="store_true",
                    help="Только per-user (ОПАСНО: см. докстринг; требует --force; релей бережётся)")
    ap.add_argument("--force", action="store_true",
                    help="Подтвердить осознанный --no-shared (без него реальный прогон отказывает)")
    ap.add_argument("--dry-run", action="store_true", help="Показать, не применять")
    args = ap.parse_args()

    # Гейт: --no-shared на eu1 опасен (06-10 перерубил выход Европы, удалив релей-
    # credential). RELAY_PRESERVE теперь бережёт релей, но прочие eu1-shared не
    # доказаны как мусор → реальный --no-shared только с явным --force. dry-run можно.
    if args.no_shared and not args.dry_run and not args.force:
        print("⛔ ОТКАЗ: --no-shared на eu1 без --force.")
        print("   eu1 vless-ws — приёмник релея yc/yc2 (см. докстринг, инцидент 2026-06-10).")
        print("   Релей-credential защищён RELAY_PRESERVE, но прочие shared не проверены.")
        print("   Если точно понимаешь — добавь --force. Сначала прогони с --dry-run.")
        return 2

    include_shared = not args.no_shared

    users = fetch_active_users()
    print(f"Active eu1 users (per-user UUID, grace 12h): {len(users)}")
    print(f"Режим: {'GRACE (per-user + сохраняем старые)' if include_shared else 'NO-SHARED (только per-user)'}, "
          f"dry_run={args.dry_run}")

    cfg = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
    changes = []
    for ib in cfg.get("inbounds", []):
        tag = ib.get("tag")
        if ib.get("protocol") != "vless" or tag not in INBOUNDS:
            continue
        existing = (ib.get("settings") or {}).get("clients") or []
        new = build_clients(users, INBOUNDS[tag], existing, include_shared)
        per_user = sum(1 for c in new if "@kronos" in (c.get("email", "") or ""))
        changes.append((tag, len(existing), len(new), per_user))
        if not args.dry_run:
            ib.setdefault("settings", {})["clients"] = new

    # policy.levels.0.statsUser* — per-user телеметрия (idempotent)
    pol = cfg.setdefault("policy", {}).setdefault("levels", {}).setdefault("0", {})
    if not args.dry_run:
        pol["statsUserUplink"] = True
        pol["statsUserDownlink"] = True

    print("\nInbound (tag: existing → new, из них per-user):")
    for tag, old, new, pu in changes:
        print(f"  {tag:<12}: {old} → {new}  (per-user={pu})")
    if not changes:
        print("  ⚠ ни один из inbound не найден — проверь теги!")
        return 1

    if args.dry_run:
        print("\n[DRY RUN] Ничего не записано, xray не трогали.")
        return 0

    # backup → tmp → validate → atomic replace → restart → smoke
    ts = int(time.time())
    backup = f"{CONFIG}.bak.eu1sync.{ts}"
    Path(backup).write_text(Path(CONFIG).read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\nBackup → {backup}")
    tmp = f"/tmp/eu1-xray-sync.{ts}.json"
    Path(tmp).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(["xray", "run", "-test", "-format=json", "-c", tmp],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        print(f"✗ VALIDATE FAIL (rc={r.returncode}): {r.stderr.strip()[:400]}")
        print(f"  tmp оставлен: {tmp} | backup: {backup}")
        return 1
    print("✓ validate OK")

    subprocess.run(["cp", tmp, CONFIG], check=True)
    subprocess.run(["systemctl", "restart", "xray"], check=True)
    time.sleep(3)
    act = subprocess.run(["systemctl", "is-active", "xray"], capture_output=True, text=True)
    if "active" not in act.stdout:
        print(f"✗ POST-RESTART: xray НЕ active!")
        print(f"  ROLLBACK: cp {backup} {CONFIG} && systemctl restart xray")
        return 1
    listen = subprocess.run(["ss", "-Htnl", "sport = :443"], capture_output=True, text=True)
    print(f"✓ xray active, :443 {'listening' if ':443' in listen.stdout else '?'}")
    print("✓ eu1 synced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
