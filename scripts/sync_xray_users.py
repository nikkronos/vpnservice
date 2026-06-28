#!/usr/bin/env python3
"""
Синхронизация Xray-конфига на удалённых серверах с БД per-user VLESS UUIDs.

Подход — НЕ runtime API (`xray api adu/rmu` молча fail'ится на наших версиях),
а прямая правка config.json + xray run -test (validate) + systemctl restart.

Source of truth — БД (users.vless_uuid_main, users.vless_uuid_yc).
config.json для нужного inbound полностью перезаписывается списком clients[]
из БД + общий share-UUID (если ENABLE_SHARED=True — для legacy юзеров до
broadcast+48h).

Запуск:
    # Sync main (REALITY tag=vless-tcp на main)
    python3 scripts/sync_xray_users.py --server main

    # Sync yc (REALITY tag=vless-xhttp на yc)
    python3 scripts/sync_xray_users.py --server yc

    # Sync yc2 (РФ-резерв, клон yc — те же UUID из колонки vless_uuid_yc)
    python3 scripts/sync_xray_users.py --server yc2

    # Все серверы (main + yc + yc2)
    python3 scripts/sync_xray_users.py --all

    # Dry-run — показать какой config был бы записан, не применяя
    python3 scripts/sync_xray_users.py --server yc --dry-run

    # Удалить общие share-UUIDs (после broadcast+48h)
    python3 scripts/sync_xray_users.py --all --no-shared

Email-маркер для per-user телеметрии: tid_<telegram_id>@kronos.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from typing import Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# ── Конфигурация серверов ──
# server_id → (ssh_args, inbound_tag_to_sync, flow, shared_uuid)
# eu1 пока НЕ трогаем — vless-ws (CDN канал), отдельная задача.
SSH_OPTS = [
    "-o", "ConnectTimeout=8",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
]
SERVERS = {
    "main": {
        "ssh": ["ssh", "-i", "/root/.ssh/id_ed25519_main"] + SSH_OPTS + ["root@81.200.146.32"],
        "inbound_tag": "vless-tcp",
        "flow": "xtls-rprx-vision",  # откат 2026-06-06: xHTTP-миграция впустую (проблема IP, не транспорт)
        "shared_uuid": "359e23cc-f90c-4e43-97af-bd1b662ff043",
        "db_column": "vless_uuid_main",
        "sudo": "",  # root user, sudo не нужен
    },
    # yc/yc2 убраны 2026-06-28 (снос YC — VLESS воскрешён на eu1/main, SESSION_SUMMARY_2026-06-28).
    # eu1 синкается отдельно (sync_eu1_vless.py).
}

CONFIG_PATH = "/usr/local/etc/xray/config.json"


def _ssh_run(ssh_args: List[str], remote_cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """SSH wrapper. remote_cmd — единственная строка, передаётся через ssh argv."""
    cmd = ssh_args + [remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _ssh_read_file(ssh_args: List[str], path: str, sudo: str = "") -> str:
    """Читает файл с сервера через cat (с опциональным sudo)."""
    r = _ssh_run(ssh_args, f"{sudo}cat {path}")
    if r.returncode != 0:
        raise RuntimeError(f"ssh cat {path} failed (rc={r.returncode}): {r.stderr.strip()[:200]}")
    return r.stdout


def _ssh_write_file(ssh_args: List[str], path: str, content: str, sudo: str = "") -> None:
    """Пишет файл на сервер. base64 для избежания escape-проблем."""
    import base64
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    # sudo tee нужен потому что redirect `>` после sudo не работает (sudo
    # применяется только к команде до пайпа). sudo tee — стандартный паттерн.
    if sudo:
        cmd = f"echo {b64} | base64 -d | sudo tee {path} > /dev/null"
    else:
        cmd = f"echo {b64} | base64 -d > {path}"
    r = _ssh_run(ssh_args, cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ssh write {path} failed: {r.stderr.strip()[:200]}")


def fetch_db_users_for_server(server_id: str) -> List[Dict]:
    """
    Берёт из БД юзеров с per-user UUID для указанного сервера, у которых
    активный доступ (с учётом grace 12h — тем же условием что enforce_expired.py).

    Условие active:
      - users.active = 1
      - telegram_id IS NOT NULL
      - UUID для сервера IS NOT NULL
      - expires_at IS NULL (grandfather) ИЛИ
        datetime(expires_at) > datetime('now', '-12 hours') (активный или в grace)

    Юзеры с истёкшей подпиской > 12h автоматически исключаются → при следующем
    sync их UUID пропадёт из Xray clients[] → старая ссылка перестанет работать.
    При оплате (db_extend_subscription) → expires_at в будущем → юзер снова
    попадает в SQL → следующий sync восстановит UUID.

    Это VLESS-аналог soft-revoke для AWG (commit a2d8c88).
    """
    from bot.database import _conn, _ensure_init
    _ensure_init()
    col = SERVERS[server_id]["db_column"]
    with _conn() as con:
        rows = con.execute(
            f"SELECT telegram_id, {col} AS uuid FROM users "
            f"WHERE telegram_id IS NOT NULL AND active = 1 AND {col} IS NOT NULL "
            f"  AND (expires_at IS NULL "
            f"       OR datetime(expires_at) > datetime('now', '-12 hours'))"
        ).fetchall()
    return [{"telegram_id": int(r["telegram_id"]), "uuid": r["uuid"]} for r in rows]


def build_clients(server_id: str, db_users: List[Dict], include_shared: bool) -> List[Dict]:
    """
    Формирует clients[] для VLESS inbound.

    Per-user: {id, flow, email: tid_X@kronos}
    + если include_shared=True — общий share-UUID для legacy юзеров (тот же
    flow, без email — статичный клиент без stats).
    """
    cfg = SERVERS[server_id]
    flow = cfg["flow"]
    clients = []

    # Per-user клиенты
    for u in db_users:
        client = {
            "id": u["uuid"],
            "email": f"tid_{u['telegram_id']}@kronos",
        }
        if flow:
            client["flow"] = flow
        clients.append(client)

    # Общий share-UUID (для legacy — до broadcast+48h)
    if include_shared and cfg["shared_uuid"]:
        shared_client = {"id": cfg["shared_uuid"]}
        if flow:
            shared_client["flow"] = flow
        clients.append(shared_client)

    return clients


def sync_one_server(server_id: str, include_shared: bool, dry_run: bool) -> bool:
    """
    Синхронизирует один сервер. Возвращает True если успех.

    Шаги:
    1. SSH read config.json
    2. Найти VLESS inbound с нужным tag
    3. Заменить clients[] на свежий список из БД (+ shared если flag)
    4. Bashup на сервере + перезаписать config.json (через base64)
    5. xray run -test -c config.json — validate
    6. Если validate OK — systemctl restart xray
    7. Проверить: systemctl is-active xray + порт LISTEN
    """
    cfg = SERVERS[server_id]
    ssh = cfg["ssh"]
    inbound_tag = cfg["inbound_tag"]
    sudo = cfg.get("sudo", "")

    print(f"\n=== Sync server '{server_id}' (inbound tag '{inbound_tag}') ===")
    print(f"  include_shared: {include_shared}, dry_run: {dry_run}, sudo: {'yes' if sudo else 'no'}")

    db_users = fetch_db_users_for_server(server_id)
    print(f"  Users from DB with per-user UUID: {len(db_users)}")
    if db_users:
        print(f"    sample: tid={db_users[0]['telegram_id']}, uuid={db_users[0]['uuid'][:8]}...")

    # 1. Прочитать удалённый config
    print(f"  Fetching {CONFIG_PATH} from {server_id}...")
    config_text = _ssh_read_file(ssh, CONFIG_PATH, sudo=sudo)
    config = json.loads(config_text)

    # 2. Найти inbound
    inbounds = config.get("inbounds", [])
    target_idx = None
    for i, ib in enumerate(inbounds):
        if ib.get("tag") == inbound_tag:
            target_idx = i
            break
    if target_idx is None:
        raise RuntimeError(f"Inbound tag '{inbound_tag}' not found in {server_id} config")

    old_clients = (inbounds[target_idx].get("settings") or {}).get("clients") or []
    old_clients_count = len(old_clients)
    print(f"  Current clients[] count in {inbound_tag}: {old_clients_count}")

    # 3. Заменить clients
    new_clients = build_clients(server_id, db_users, include_shared)
    print(f"  New clients[] count: {len(new_clients)} ({len(db_users)} per-user + {1 if include_shared else 0} shared)")

    if "settings" not in inbounds[target_idx]:
        inbounds[target_idx]["settings"] = {}
    inbounds[target_idx]["settings"]["clients"] = new_clients
    # decryption обязательно для VLESS — должно быть уже в конфиге, не трогаем

    # 3a. Гарантируем policy.levels.0.statsUser* для per-user телеметрии
    # (без этого `xray api statsquery -pattern=user>>>` возвращает пусто).
    # Idempotent: если уже выставлено — ничего не меняет.
    policy_changed = False
    if "policy" not in config:
        config["policy"] = {}
    if "levels" not in config["policy"]:
        config["policy"]["levels"] = {}
    if "0" not in config["policy"]["levels"]:
        config["policy"]["levels"]["0"] = {}
        policy_changed = True
    level0 = config["policy"]["levels"]["0"]
    if not level0.get("statsUserUplink"):
        level0["statsUserUplink"] = True
        policy_changed = True
    if not level0.get("statsUserDownlink"):
        level0["statsUserDownlink"] = True
        policy_changed = True
    if policy_changed:
        print(f"  Added policy.levels.0.statsUser{{Uplink,Downlink}} = true (per-user telemetry)")

    # Guard «нет изменений → не рестартим Xray»: clients[] поддерживается этим же
    # скриптом, поэтому сравниваем по содержимому (order-independent). Нужно для
    # перевода cron на ежечасный sync без лишних рестартов (раньше КАЖДЫЙ прогон
    # рестартил всегда → ~5с downtime ×3 сервера). 2026-06-11.
    def _norm_clients(cl):
        return sorted(json.dumps(c, sort_keys=True, ensure_ascii=False) for c in cl)
    no_change = (not policy_changed) and _norm_clients(new_clients) == _norm_clients(old_clients)

    new_config_text = json.dumps(config, indent=2, ensure_ascii=False)

    if dry_run:
        print(f"\n  [DRY RUN] no_change={no_change}"
              + ("  (изменений нет → реальный прогон пропустил бы рестарт)" if no_change
                 else "  (есть изменения → реальный прогон обновил бы config + рестарт)"))
        print("  [DRY RUN] Resulting clients[] preview:")
        for c in new_clients[:5]:
            print(f"    {c}")
        if len(new_clients) > 5:
            print(f"    ... и ещё {len(new_clients) - 5}")
        print("\n  [DRY RUN] Не записываем, не рестартим.")
        return True

    # Guard: ничего не изменилось — не трогаем config и НЕ рестартим Xray.
    if no_change:
        print("  ✓ Нет изменений (clients/policy) — config не трогаем, Xray не рестартим.")
        return True

    # 4. Backup + write
    ts = int(time.time())
    backup_path = f"{CONFIG_PATH}.bak.sync.{ts}"
    print(f"  Backup → {backup_path}")
    r = _ssh_run(ssh, f"{sudo}cp {CONFIG_PATH} {backup_path}")
    if r.returncode != 0:
        raise RuntimeError(f"backup failed: {r.stderr}")

    print("  Writing new config.json (tmp)...")
    # Tmp файл в /tmp (любой user может писать), потом sudo mv в /usr/local/etc
    tmp_path = f"/tmp/xray-sync.{ts}.json"
    _ssh_write_file(ssh, tmp_path, new_config_text, sudo="")  # /tmp не нужен sudo

    # 5. Validate
    print("  Validating with `xray run -test`...")
    r = _ssh_run(ssh, f"{sudo}xray run -test -format=json -c {tmp_path}", timeout=20)
    if r.returncode != 0:
        print(f"  ✗ VALIDATE FAIL (rc={r.returncode})")
        print(f"  stderr: {r.stderr.strip()[:500]}")
        print(f"  Tmp config оставлен: {tmp_path}")
        print(f"  Backup исходного: {backup_path}")
        return False
    print("  ✓ Validate OK")

    # 6. Atomic replace + restart
    print("  Replacing config.json + restart xray...")
    r = _ssh_run(ssh, f"{sudo}mv {tmp_path} {CONFIG_PATH} && {sudo}systemctl restart xray")
    if r.returncode != 0:
        print(f"  ✗ Replace/restart failed: {r.stderr}")
        return False
    time.sleep(3)

    # 7. Smoke-test
    r = _ssh_run(ssh, "systemctl is-active xray && ss -Htnl 'sport = :443' | head -1")
    if r.returncode != 0 or "active" not in r.stdout:
        print(f"  ✗ POST-RESTART CHECK FAILED:")
        print(f"  stdout: {r.stdout[:500]}")
        print(f"  stderr: {r.stderr[:300]}")
        rollback_user = "root" if not sudo else ""
        print(f"  ⚠ ROLLBACK: ssh {server_id} '{sudo}cp {backup_path} {CONFIG_PATH} && {sudo}systemctl restart xray'")
        return False
    print(f"  ✓ xray active, :443 listening")
    print(f"  ✓ {server_id} synced successfully")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync per-user VLESS UUIDs to Xray config.json on main/yc")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--server", choices=["main"], help="Sync only this server")
    g.add_argument("--all", action="store_true", help="Sync all servers (main; yc/yc2 убраны 06-28)")
    parser.add_argument("--no-shared", action="store_true",
                        help="Don't include legacy shared UUID (use AFTER broadcast+48h, etap 7)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be written, don't apply")
    args = parser.parse_args()

    targets = ["main"] if args.all else [args.server]  # yc/yc2 убраны 06-28 (снос YC)
    include_shared = not args.no_shared

    ok_count = 0
    fail_count = 0
    for srv in targets:
        try:
            if sync_one_server(srv, include_shared=include_shared, dry_run=args.dry_run):
                ok_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"\n  ✗ EXCEPTION on {srv}: {e}")
            import traceback
            traceback.print_exc()
            fail_count += 1

    print(f"\n{'=' * 60}")
    print(f"Итого: {ok_count} OK, {fail_count} FAIL")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
