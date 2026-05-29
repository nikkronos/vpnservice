#!/usr/bin/env python3
"""
Идемпотентный патч Xray config.json для включения stats API.

Назначение: per-inbound summary трафика (рассмотреть `xray api stats`) для
панели мониторинга. Per-user UUID-телеметрия отдельная задача (ROADMAP P2 —
«Персональные UUIDs для main REALITY»), эта операция её НЕ требует.

Что делает (всё идемпотентно — повторный запуск не сломает):
  1. Бэкап `{path}.bak.{timestamp}` (с PSK-сертификатом config, поэтому
     сохраняем все исходные данные).
  2. Добавляет блоки `stats: {}`, `api`, `policy` если их нет.
  3. Проставляет тег `vless-{network}` (vless-ws / vless-xhttp / vless-reality)
     каждому vless-inbound у которого нет своего tag — нужен для per-inbound
     stats. Если у inbound уже есть tag — не трогает.
  4. Добавляет inbound `api` (dokodemo-door на 127.0.0.1:10085) если его нет.
  5. Добавляет outbound `freedom` с tag=api если нет.
  6. Добавляет routing rule «api inbound → api outbound» если нет.
  7. Validate новой конфы через `xray test -config <tmp>`.
  8. Если validate OK — заменяет исходный файл; иначе — оставляет старый файл
     нетронутым и выходит с rc=1, backup остаётся для разбора.

Использование:
    python3 patch_xray_stats.py /usr/local/etc/xray/config.json
    python3 patch_xray_stats.py --dry-run /usr/local/etc/xray/config.json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Any


API_PORT = 10085
API_INBOUND = {
    "listen": "127.0.0.1",
    "port": API_PORT,
    "protocol": "dokodemo-door",
    "settings": {"address": "127.0.0.1"},
    "tag": "api",
}
API_OUTBOUND = {"protocol": "freedom", "tag": "api"}
STATS_BLOCK = {}
API_BLOCK = {"tag": "api", "services": ["StatsService"]}
POLICY_BLOCK = {
    "system": {
        "statsInboundUplink": True,
        "statsInboundDownlink": True,
    },
}
ROUTING_API_RULE = {
    "type": "field",
    "inboundTag": ["api"],
    "outboundTag": "api",
}


def patch_config(cfg: Dict[str, Any]) -> List[str]:
    """Идемпотентно правит cfg на месте. Возвращает list of changes для лога."""
    changes: List[str] = []

    if "stats" not in cfg:
        cfg["stats"] = STATS_BLOCK
        changes.append("added stats: {}")

    if "api" not in cfg:
        cfg["api"] = API_BLOCK
        changes.append("added api block")
    elif cfg["api"].get("tag") != "api" or "StatsService" not in (cfg["api"].get("services") or []):
        # Не перезаписываем чужой api блок, но логируем что не тронули.
        changes.append(f"api block present but unexpected, left as-is: {cfg['api']}")

    if "policy" not in cfg:
        cfg["policy"] = POLICY_BLOCK
        changes.append("added policy.system stats flags")
    else:
        # policy уже есть — добавляем system.statsInbound* если не выставлено
        sys_pol = cfg["policy"].setdefault("system", {})
        if not sys_pol.get("statsInboundUplink"):
            sys_pol["statsInboundUplink"] = True
            changes.append("added policy.system.statsInboundUplink=true")
        if not sys_pol.get("statsInboundDownlink"):
            sys_pol["statsInboundDownlink"] = True
            changes.append("added policy.system.statsInboundDownlink=true")

    # Теги для vless inbound'ов
    inbounds = cfg.setdefault("inbounds", [])
    for ib in inbounds:
        if ib.get("protocol") == "vless" and not ib.get("tag"):
            network = (ib.get("streamSettings") or {}).get("network") or "unknown"
            tag = f"vless-{network}"
            ib["tag"] = tag
            changes.append(f"tagged inbound :{ib.get('port')} → {tag}")

    # API inbound — добавить если ещё нет
    has_api_inbound = any(ib.get("tag") == "api" for ib in inbounds)
    if not has_api_inbound:
        inbounds.append(API_INBOUND.copy())
        changes.append(f"added api inbound on 127.0.0.1:{API_PORT}")

    # API outbound — Xray ожидает freedom-outbound с tag=api для маршрутизации
    outbounds = cfg.setdefault("outbounds", [])
    has_api_outbound = any(ob.get("tag") == "api" for ob in outbounds)
    if not has_api_outbound:
        outbounds.append(API_OUTBOUND.copy())
        changes.append("added api outbound (freedom, tag=api)")

    # Routing rule
    routing = cfg.setdefault("routing", {})
    rules = routing.setdefault("rules", [])
    has_api_rule = any(
        r.get("type") == "field"
        and "api" in (r.get("inboundTag") or [])
        and r.get("outboundTag") == "api"
        for r in rules
    )
    if not has_api_rule:
        # Вставляем в начало — api-правило должно сработать раньше любых других.
        rules.insert(0, ROUTING_API_RULE.copy())
        changes.append("added routing rule: api inbound → api outbound")

    return changes


def xray_test(config_path: str) -> tuple[bool, str]:
    """Запускает `xray run -test -format=json -c <path>`. Возвращает (ok, msg)."""
    try:
        r = subprocess.run(
            ["xray", "run", "-test", "-format=json", "-c", config_path],
            capture_output=True, text=True, timeout=20,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, "xray binary not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "xray test timeout"


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotent Xray stats config patcher")
    parser.add_argument("config_path", help="Path to Xray config.json")
    parser.add_argument("--dry-run", action="store_true", help="Print proposed changes and validate, but don't write")
    args = parser.parse_args()

    path = pathlib.Path(args.config_path)
    if not path.exists():
        print(f"ERROR: {path} does not exist", file=sys.stderr)
        return 1

    cfg = json.loads(path.read_text())
    changes = patch_config(cfg)

    if not changes:
        print(f"OK: {path} already has stats configured, no changes needed")
        return 0

    print(f"Changes for {path}:")
    for c in changes:
        print(f"  - {c}")

    new_text = json.dumps(cfg, indent=2, ensure_ascii=False)
    tmp_path = pathlib.Path(f"{path}.tmp.{int(time.time())}")
    tmp_path.write_text(new_text)

    ok, msg = xray_test(str(tmp_path))
    print(f"\nxray test: {'OK' if ok else 'FAIL'}")
    if msg:
        print(msg)

    if not ok:
        print(f"\nNot replacing {path}. Tmp config left at {tmp_path} for inspection.")
        return 1

    if args.dry_run:
        tmp_path.unlink()
        print("\n(dry-run: config validates OK, but not replacing)")
        return 0

    # Backup
    backup = pathlib.Path(f"{path}.bak.{int(time.time())}")
    shutil.copy2(path, backup)
    print(f"\nBackup: {backup}")

    # Atomic replace
    os.replace(tmp_path, path)
    print(f"Replaced: {path}")
    print("\nNext step: `systemctl restart xray` and verify with `xray api statsquery --server=127.0.0.1:10085`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
