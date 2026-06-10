#!/usr/bin/env python3
"""
Инструментовка eu1 vless-tcp shared-UUID для liveness-аудита (2026-06-10).

Добавляет email `auditshare_<id8>@kronos` тем client'ам vless-tcp, у кого НЕТ
email и кто НЕ per-user (`tid_`) и НЕ в RELAY_PRESERVE. Цель: сделать их трафик
видимым per-UUID (access log `email:` + xray stats), чтобы за несколько дней
доказать, живы они или мертвы, ПРЕЖДЕ чем удалять (sync_eu1_vless --no-shared
--force). Безопасно: чисто аддитивно (только добавляет email-метку), UUID/clients
не удаляет и не меняет; релей и per-user не трогает.

Идемпотентно (повторный запуск не дублирует). Backup + validate(-format=json) +
restart + smoke. ТОЛЬКО inbound vless-tcp.

    cd /opt/vpnservice && venv/bin/python scripts/instrument_eu1_shares.py --dry-run
    cd /opt/vpnservice && venv/bin/python scripts/instrument_eu1_shares.py --apply
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sync_eu1_vless import RELAY_PRESERVE  # noqa: E402

CONFIG = "/usr/local/etc/xray/config.json"
TARGET_TAG = "vless-tcp"
EMAIL_PREFIX = "auditshare_"


def main() -> int:
    ap = argparse.ArgumentParser(description="Инструментовать eu1 vless-tcp shared-UUID email-меткой для liveness")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Показать, не применять")
    g.add_argument("--apply", action="store_true", help="Применить (backup+validate+restart)")
    args = ap.parse_args()

    cfg = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
    planned = []  # (uuid, new_email)
    skipped_relay = skipped_peruser = already = 0

    for ib in cfg.get("inbounds", []):
        if ib.get("tag") != TARGET_TAG or ib.get("protocol") != "vless":
            continue
        for c in (ib.get("settings") or {}).get("clients") or []:
            uid = c.get("id") or ""
            email = c.get("email", "") or ""
            if uid in RELAY_PRESERVE:
                skipped_relay += 1
                continue
            if "tid_" in email:
                skipped_peruser += 1
                continue
            if email.startswith(EMAIL_PREFIX):
                already += 1
                continue
            if email:
                # есть какой-то иной email — не трогаем, только сообщаем
                print(f"  ⚠ client {uid[:8]}… уже имеет email '{email}' — пропуск")
                continue
            new_email = f"{EMAIL_PREFIX}{uid[:8]}@kronos"
            planned.append((uid, new_email))
            if args.apply:
                c["email"] = new_email

    print(f"\nИнструментовать (vless-tcp, без email, не relay, не per-user): {len(planned)}")
    print(f"  пропущено: relay={skipped_relay}, per-user={skipped_peruser}, уже инструм.={already}")
    for uid, em in planned:
        print(f"    {uid[:8]}…  → email={em}")

    if not planned:
        print("\nНечего инструментировать (всё уже помечено или пусто).")
        return 0

    if args.dry_run:
        print("\n[DRY RUN] Ничего не записано.")
        return 0

    # backup → tmp → validate → atomic replace → restart → smoke
    ts = int(time.time())
    backup = f"{CONFIG}.bak.instrument.{ts}"
    Path(backup).write_text(Path(CONFIG).read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\nBackup → {backup}")
    tmp = f"/tmp/eu1-instrument.{ts}.json"
    Path(tmp).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(["xray", "run", "-test", "-format=json", "-c", tmp],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        print(f"✗ VALIDATE FAIL (rc={r.returncode}): {r.stderr.strip()[:400]}")
        print(f"  tmp: {tmp} | backup: {backup}")
        return 1
    print("✓ validate OK")

    subprocess.run(["cp", tmp, CONFIG], check=True)
    subprocess.run(["systemctl", "restart", "xray"], check=True)
    time.sleep(3)
    act = subprocess.run(["systemctl", "is-active", "xray"], capture_output=True, text=True)
    if "active" not in act.stdout:
        print("✗ POST-RESTART: xray НЕ active!")
        print(f"  ROLLBACK: cp {backup} {CONFIG} && systemctl restart xray")
        return 1
    listen = subprocess.run(["ss", "-Htnl", "sport = :443"], capture_output=True, text=True)
    print(f"✓ xray active, :443 {'listening' if ':443' in listen.stdout else '?'}")
    print(f"✓ инструментировано {len(planned)} shared-UUID. Наблюдай:")
    print("    journalctl -u xray | grep 'email: auditshare_' | grep -oE 'auditshare_[0-9a-f]+' | sort | uniq -c")
    return 0


if __name__ == "__main__":
    sys.exit(main())
