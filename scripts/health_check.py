#!/usr/bin/env python3
"""
Health-check / alerting для VPN-инфраструктуры (Fornex + main + yc + yc2).

Каждые 15 минут проходит ~33 проверки:
  * Fornex (14, инициируются локально): systemd сервисы, docker контейнеры,
    AWG peer-count, peers.json/awg consistency, диск, swap, LE сертификат,
    HTTPS endpoint, vless_config_consistency (БД ↔ config на main/yc/yc2),
    vless_traffic_flow (реальный VLESS-трафик на yc+yc2 — детектор сетевого
    блока транспорта при живом сервисе).
  * main (Timeweb, 7, через SSH): reachable, xray, wg-quick@wg0, fail2ban,
    :443/tcp, :51820/udp, диск.
  * yc (Yandex Cloud, 6, через SSH): reachable, xray, fail2ban, :443/tcp,
    :8443/tcp (socat sub-forward), диск.
  * yc2 (Yandex Cloud, РФ-резерв, 6, через SSH): reachable, xray, fail2ban,
    :443/tcp, :8443/tcp (socat sub-forward), диск.

При **смене статуса** (OK→FAIL или FAIL→OK) шлёт алерт владельцу в Telegram
через прямой HTTP API (urllib, без инстанса бота — алерт уйдёт даже если упал
сам vpn-bot.service).

State хранится в /var/lib/vpn-health/state.json — нужен чтобы не спамить
повторными алертами при той же ошибке. Ключи remote-проверок имеют префикс
`<host>:` (например `yc:xray.service`); локальные имена не меняются (backward
compat с baseline 2026-05-29).

При FAIL `<host>:reachable` остальные проверки этого хоста **скипаются**
(не запускаются и в state не пишутся) — чтобы один сетевой провал не
давал каскад из 5+ алертов.

Запуск:
    # Production (cron)
    /opt/vpnservice/venv/bin/python scripts/health_check.py

    # Тест-режим: печать всех проверок на stdout, без state и алертов
    /opt/vpnservice/venv/bin/python scripts/health_check.py --dry-run

ENV (через bot/config.py): BOT_TOKEN, ADMIN_TELEGRAM_ID
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import pathlib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Project root для импортов bot.* (нужен только в production-режиме)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("health_check")


# === Пороги ===
DISK_THRESHOLD_PCT = 85
SWAP_THRESHOLD_PCT = 80
CERT_THRESHOLD_DAYS = 7
AWG_PEER_DROP_THRESHOLD_PCT = 50  # падение > 50% от прошлой проверки = FAIL
VLESS_TRAFFIC_STALE_SEC = 3 * 3600  # 0 реальных VLESS-коннектов на ОБОИХ воркхорсах (yc+yc2) дольше = FAIL
CERT_PATH = "/etc/letsencrypt/live/supportkronos.online/cert.pem"
HTTPS_URL = "https://supportkronos.online:8443/"
# 401/403 — нормально (Flask отвечает, просто нужна авторизация для /)
EXPECTED_HTTP_CODES = {200, 301, 302, 401, 403}

STATE_PATH = pathlib.Path("/var/lib/vpn-health/state.json")
LOCK_PATH = pathlib.Path("/var/lock/vpn-health.lock")
SYSTEMCTL = "/bin/systemctl"
DOCKER = "/usr/bin/docker"

# === Remote: SSH-команды и план проверок ===
# BatchMode=yes блокирует любые prompt'ы (passphrase/yes-no);
# ConnectTimeout=5 — быстрый fail при сетевой проблеме;
# StrictHostKeyChecking=accept-new — авто-добавление новых host keys (для
# первого запуска после смены IP/перенастройки), но запрет на silent-обновление
# при подмене ключа (защита от MITM).
SSH_OPTS = [
    "-o", "ConnectTimeout=5",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ServerAliveInterval=3",
    "-o", "ServerAliveCountMax=1",
]
REMOTE_HOSTS: Dict[str, List[str]] = {
    "main": ["ssh", "-i", "/root/.ssh/id_ed25519_main"] + SSH_OPTS + ["root@81.200.146.32"],
    "yc":   ["ssh"] + SSH_OPTS + ["yc"],
    "yc2":  ["ssh"] + SSH_OPTS + ["yc2"],  # РФ-резерв, клон yc
}

# План проверок на каждом удалённом хосте.
# Tuple-форма: ("systemd", "<unit>") | ("port", <int>, "tcp"|"udp") | ("disk", "<path>")
REMOTE_CHECK_PLAN: Dict[str, List[Tuple]] = {
    "main": [
        ("systemd", "xray.service"),
        ("systemd", "wg-quick@wg0.service"),
        ("systemd", "fail2ban.service"),  # SSH brute-force mitigation (2026-06-11)
        ("port",    443,   "tcp"),
        ("port",    51820, "udp"),
        ("disk",    "/"),
    ],
    "yc": [
        ("systemd", "xray.service"),
        ("systemd", "fail2ban.service"),  # SSH brute-force mitigation (2026-06-11)
        ("port",    443,   "tcp"),
        ("port",    8443,  "tcp"),   # socat sub-forward (ЛК/подписка через Яндекс-фронт, 2026-06-10)
        ("disk",    "/"),
    ],
    "yc2": [
        ("systemd", "xray.service"),
        ("systemd", "fail2ban.service"),  # SSH brute-force mitigation (2026-06-11)
        ("port",    443,   "tcp"),
        ("port",    8443,  "tcp"),   # socat sub-forward
        ("disk",    "/"),
    ],
}


@dataclass
class CheckResult:
    name: str
    status: str  # "OK" | "FAIL"
    message: str
    detail: str = ""


# === Helpers ===

def _run(cmd: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _run_remote(host: str, remote_cmd: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """
    Выполнить shell-команду на удалённом хосте через SSH.

    `remote_cmd` передаётся как ОДИН аргумент в ssh — клиент сам пробрасывает
    его в shell на удалённой стороне, экранирование сохраняется.
    """
    ssh_cmd = REMOTE_HOSTS[host] + [remote_cmd]
    return subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)


def _run_remote_resilient(
    host: str, remote_cmd: str, timeout: int = 15,
    attempts: int = 3, backoff: float = 2.0,
) -> subprocess.CompletedProcess:
    """`_run_remote` с ретраем транзиентных SSH-сбоев (rc=255 / timeout).

    Ночью yc/yc2 ловят SSH brute-force флуд (fail2ban не стоит); sshd упирается
    в MaxStartups и отдельный коннект отбивается с rc=255 → false-FAIL чека
    `vless_config_consistency` (Xray при этом обслуживает, юзеры не отваливаются —
    инцидент 2026-06-11 02:00 UTC). Ретрай на 255/timeout это гасит; реальные
    ошибки команды (rc!=0 и !=255) не маскируются — возвращаются как есть.
    Всегда возвращает CompletedProcess (на исчерпанном timeout — синтетический rc=255).
    """
    last: Optional[subprocess.CompletedProcess] = None
    for i in range(attempts):
        try:
            r = _run_remote(host, remote_cmd, timeout=timeout)
            if r.returncode != 255:
                return r
            last = r
        except subprocess.TimeoutExpired:
            last = subprocess.CompletedProcess(
                args=REMOTE_HOSTS[host], returncode=255, stdout="", stderr="ssh timeout")
        if i < attempts - 1:
            time.sleep(backoff)
    return last  # type: ignore[return-value]


# === Проверки (local + remote, параметризованные по host) ===

def _qualify(name: str, host: Optional[str]) -> str:
    """Имя проверки для state-key. Локально — как есть, для backward compat
    с baseline; remote — с префиксом `<host>:`."""
    return f"{host}:{name}" if host else name


def check_systemd_service(service: str, host: Optional[str] = None) -> CheckResult:
    qname = _qualify(service, host)
    try:
        if host is None:
            r = _run([SYSTEMCTL, "is-active", service])
        else:
            r = _run_remote(host, f"systemctl is-active {service}")
        active = r.stdout.strip() == "active"
        if active:
            return CheckResult(qname, "OK", "active")
        # Захватим последние строки лога для контекста алерта
        if host is None:
            log = _run(["journalctl", "-u", service, "-n", "5", "--no-pager"])
            detail = log.stdout.strip()[-500:]
        else:
            log = _run_remote(host, f"journalctl -u {service} -n 5 --no-pager")
            detail = log.stdout.strip()[-500:]
        return CheckResult(
            qname,
            "FAIL",
            f"systemctl is-active вернул: {r.stdout.strip() or 'unknown'}",
            detail,
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(qname, "FAIL", f"check error: {e}")


def check_docker_container(name: str) -> CheckResult:
    try:
        r = _run([DOCKER, "inspect", "-f", "{{.State.Running}}", name])
        if r.returncode != 0:
            return CheckResult(name, "FAIL", f"docker inspect failed: {r.stderr.strip()[:200]}")
        running = r.stdout.strip() == "true"
        return CheckResult(name, "OK" if running else "FAIL", r.stdout.strip())
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}")


def check_awg_peer_count(prev_count: Optional[int]) -> tuple[CheckResult, Optional[int]]:
    name = "awg_peer_count"
    try:
        r = _run([DOCKER, "exec", "amnezia-awg2", "awg", "show", "awg0", "dump"])
        if r.returncode != 0:
            return CheckResult(name, "FAIL", f"awg show failed: {r.stderr.strip()[:200]}"), None
        lines = r.stdout.strip().split("\n")
        count = max(0, len(lines) - 1)  # минус server-line
        if prev_count and count < prev_count * (1 - AWG_PEER_DROP_THRESHOLD_PCT / 100):
            return CheckResult(
                name,
                "FAIL",
                f"peer count {count} (упало > {AWG_PEER_DROP_THRESHOLD_PCT}% от prev={prev_count})",
                f"current={count} prev={prev_count}",
            ), count
        return CheckResult(name, "OK", f"peers={count}", f"prev={prev_count}"), count
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}"), None


def check_peers_consistency() -> CheckResult:
    """
    Все peer-ы из peers.json должны существовать в AWG runtime.
    Если нет — это lost-after-reboot (см. memory persistent_state_after_reboot).

    Обратное направление НЕ проверяем (legacy owner-peers вне peers.json — норма,
    см. инцидент 2026-05-29).
    """
    name = "peers_json_vs_awg"
    try:
        from bot.storage import get_all_peers

        json_active = {
            p.public_key.strip()
            for p in get_all_peers()
            if p.server_id == "eu1" and p.active and p.public_key
        }

        r = _run([DOCKER, "exec", "amnezia-awg2", "awg", "show", "awg0", "dump"])
        if r.returncode != 0:
            return CheckResult(name, "FAIL", f"awg show failed: {r.stderr.strip()[:200]}")
        awg_keys = set()
        for line in r.stdout.strip().split("\n")[1:]:
            parts = line.split("\t")
            if parts:
                awg_keys.add(parts[0].strip())

        lost = json_active - awg_keys
        if lost:
            sample = "\n".join(f"  {k[:16]}…" for k in sorted(lost)[:5])
            return CheckResult(
                name,
                "FAIL",
                f"{len(lost)} peer из peers.json пропали из AWG runtime (lost-after-reboot?)",
                sample,
            )
        return CheckResult(name, "OK", f"json:{len(json_active)} ⊆ awg:{len(awg_keys)}")
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}")


def check_disk(path: str = "/", host: Optional[str] = None) -> CheckResult:
    qname = _qualify(f"disk_{path}", host)
    try:
        if host is None:
            s = os.statvfs(path)
            used_pct = (1 - s.f_bavail / s.f_blocks) * 100
            free_gb = s.f_bavail * s.f_frsize / 1024**3
        else:
            # Парсим `df -P <path>` (вторая строка, 5-я колонка = "NN%",
            # 4-я колонка = available в 1024-блоках).
            r = _run_remote(host, f"df -P {path}")
            if r.returncode != 0:
                return CheckResult(qname, "FAIL", f"df failed: {r.stderr.strip()[:200]}")
            lines = [ln for ln in r.stdout.strip().split("\n") if ln.strip()]
            if len(lines) < 2:
                return CheckResult(qname, "FAIL", f"df output unexpected: {r.stdout.strip()[:200]}")
            parts = lines[1].split()
            if len(parts) < 5:
                return CheckResult(qname, "FAIL", f"df row unparseable: {lines[1][:200]}")
            used_pct = float(parts[4].rstrip("%"))
            free_gb = int(parts[3]) / 1024 / 1024  # 1K-blocks → GB
        msg = f"used={used_pct:.1f}% free={free_gb:.1f}GB"
        if used_pct > DISK_THRESHOLD_PCT:
            return CheckResult(qname, "FAIL", f"диск > {DISK_THRESHOLD_PCT}% ({msg})", msg)
        return CheckResult(qname, "OK", msg)
    except Exception as e:  # noqa: BLE001
        return CheckResult(qname, "FAIL", f"check error: {e}")


def check_port_listening(port: int, proto: str, host: Optional[str] = None) -> CheckResult:
    """
    Проверка LISTEN (TCP) / UNCONN (UDP) на нужном порту.
    Локально — `ss` без SSH; удалённо — `ss` через SSH-обёртку.
    Считаем OK, если вывод `ss -H{tu}nl 'sport = :PORT'` непустой.
    """
    qname = _qualify(f"port_{port}_{proto}", host)
    flag = "tnl" if proto == "tcp" else "unl"
    cmd_str = f"ss -H{flag} 'sport = :{port}'"
    try:
        if host is None:
            r = _run(["sh", "-c", cmd_str])
        else:
            r = _run_remote(host, cmd_str)
        if r.returncode != 0:
            return CheckResult(qname, "FAIL", f"ss failed: {r.stderr.strip()[:200]}")
        output = r.stdout.strip()
        if not output:
            return CheckResult(qname, "FAIL", f"no listener on :{port}/{proto}")
        first_line = output.split("\n", 1)[0][:120]
        return CheckResult(qname, "OK", f":{port}/{proto} listening", first_line)
    except Exception as e:  # noqa: BLE001
        return CheckResult(qname, "FAIL", f"check error: {e}")


def check_memory_swap() -> CheckResult:
    name = "memory_swap"
    try:
        info: Dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k.strip()] = int(v.strip().split()[0])  # в KB

        swap_total = info.get("SwapTotal", 0)
        swap_free = info.get("SwapFree", 0)
        mem_total = info.get("MemTotal", 0)
        mem_avail = info.get("MemAvailable", 0)

        swap_pct = (1 - swap_free / swap_total) * 100 if swap_total else 0
        mem_pct = (1 - mem_avail / mem_total) * 100 if mem_total else 0

        msg = f"RAM used={mem_pct:.0f}%, swap used={swap_pct:.0f}%"
        if swap_pct > SWAP_THRESHOLD_PCT:
            return CheckResult(name, "FAIL", f"swap > {SWAP_THRESHOLD_PCT}% ({msg})", msg)
        return CheckResult(name, "OK", msg)
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}")


def check_le_cert() -> CheckResult:
    name = "le_cert_expiry"
    try:
        r = _run(["openssl", "x509", "-in", CERT_PATH, "-noout", "-enddate"])
        if r.returncode != 0:
            return CheckResult(name, "FAIL", f"openssl failed: {r.stderr.strip()[:200]}")
        # формат: notAfter=May 27 14:23:45 2026 GMT
        line = r.stdout.strip()
        date_str = line.split("=", 1)[1].strip()
        exp_dt = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_left = (exp_dt - now).days
        msg = f"истекает через {days_left} дн ({date_str})"
        if days_left < CERT_THRESHOLD_DAYS:
            return CheckResult(name, "FAIL", f"LE cert < {CERT_THRESHOLD_DAYS} дн ({msg})", msg)
        return CheckResult(name, "OK", msg)
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}")


def check_vless_config_consistency() -> CheckResult:
    """
    Cross-server consistency check: count(per-user UUIDs в БД) vs count(clients[]
    в Xray config.json на main, yc и yc2). Если разошлось > 2 (буфер для гонок
    sync) — FAIL: значит cron safety net (`sync_xray_users.py --all --no-shared`)
    не сработал или sync упал.

    yc2 — клон yc (та же колонка vless_uuid_yc), поэтому сверяется с db_yc.
    Это главный детектор дрейфа статичного клона: если yc2 выпал из sync,
    оплаты/истечения на yc разойдутся с застывшим yc2 → здесь поймаем.

    Допуск ±2: один юзер может быть в процессе оплаты/revoke между БД и config,
    плюс возможна гонка между sync_xray_users и health_check.
    """
    name = "vless_config_consistency"
    try:
        from bot.database import _conn, _ensure_init
        _ensure_init()
        with _conn() as con:
            row = con.execute(
                "SELECT "
                "  SUM(CASE WHEN vless_uuid_main IS NOT NULL "
                "           AND (expires_at IS NULL "
                "                OR datetime(expires_at) > datetime('now', '-12 hours')) "
                "      THEN 1 ELSE 0 END) AS db_main, "
                "  SUM(CASE WHEN vless_uuid_yc IS NOT NULL "
                "           AND (expires_at IS NULL "
                "                OR datetime(expires_at) > datetime('now', '-12 hours')) "
                "      THEN 1 ELSE 0 END) AS db_yc "
                "FROM users "
                "WHERE telegram_id IS NOT NULL AND active = 1"
            ).fetchone()
        db_main = (row["db_main"] or 0) if row else 0
        db_yc = (row["db_yc"] or 0) if row else 0

        # SSH к main, yc, yc2 — забираем count(clients) из config.json.
        # yc2 — клон yc (vless-xhttp), сверяется с db_yc.
        # _run_remote_resilient: ретрай транзиентных SSH-дропов (ночной brute-force
        # флуд на yc/yc2 упирает sshd в MaxStartups → rc=255 → раньше был
        # false-FAIL, инцидент 2026-06-11 02:00 UTC).
        cmd_main = "jq '[.inbounds[] | select(.tag==\"vless-tcp\") | .settings.clients[]] | length' /usr/local/etc/xray/config.json"
        cmd_yc = "sudo jq '[.inbounds[] | select(.tag==\"vless-xhttp\") | .settings.clients[]] | length' /usr/local/etc/xray/config.json"
        cmd_yc2 = cmd_yc  # yc2 — тот же inbound-tag vless-xhttp

        r_m = _run_remote_resilient("main", cmd_main)
        r_y = _run_remote_resilient("yc", cmd_yc)
        r_y2 = _run_remote_resilient("yc2", cmd_yc2)

        try:
            cfg_main = int(r_m.stdout.strip()) if r_m.returncode == 0 else -1
        except ValueError:
            cfg_main = -1
        try:
            cfg_yc = int(r_y.stdout.strip()) if r_y.returncode == 0 else -1
        except ValueError:
            cfg_yc = -1
        try:
            cfg_yc2 = int(r_y2.stdout.strip()) if r_y2.returncode == 0 else -1
        except ValueError:
            cfg_yc2 = -1

        if cfg_main < 0 or cfg_yc < 0 or cfg_yc2 < 0:
            return CheckResult(
                name, "FAIL",
                f"не удалось прочитать count(clients) на main/yc/yc2",
                f"main_rc={r_m.returncode} yc_rc={r_y.returncode} yc2_rc={r_y2.returncode}",
            )

        diff_main = abs(db_main - cfg_main)
        diff_yc = abs(db_yc - cfg_yc)
        diff_yc2 = abs(db_yc - cfg_yc2)  # yc2 = клон yc → сверяем с db_yc
        msg = (
            f"db_main={db_main} cfg_main={cfg_main} (diff {diff_main}), "
            f"db_yc={db_yc} cfg_yc={cfg_yc} (diff {diff_yc}), "
            f"cfg_yc2={cfg_yc2} (diff {diff_yc2})"
        )

        if diff_main > 2 or diff_yc > 2 or diff_yc2 > 2:
            return CheckResult(name, "FAIL", f"разошлось > 2 ({msg})", msg)
        return CheckResult(name, "OK", msg)
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}")


# Возраст (сек) последней реальной @kronos-строки в access.log (+ротация .1) на узле.
# Печатает целое (возраст), NOLOG (нет kronos-трафика вовсе) или PARSEFAIL.
# TZ-safe: и `date -d`, и `date +%s` берут TZ узла → разница TZ сокращается
# (yc/yc2 логируют в UTC; здесь это и так UTC). access.log под root → sudo.
_VLESS_AGE_PROBE = (
    'F=/var/log/xray/access.log; '
    'L=$(sudo grep -a kronos "$F" 2>/dev/null | tail -1 | cut -c1-19); '
    '[ -z "$L" ] && L=$(sudo grep -a kronos "$F".1 2>/dev/null | tail -1 | cut -c1-19); '
    'if [ -z "$L" ]; then echo NOLOG; '
    'else T=$(date -d "$(echo "$L" | tr / -)" +%s 2>/dev/null); '
    'if [ -z "$T" ]; then echo PARSEFAIL; else echo $(( $(date +%s) - T )); fi; fi'
)


def check_vless_traffic_flow() -> CheckResult:
    """
    Детектор «сервис жив, но реальный VLESS-трафик не идёт» — слепое пятно
    остальных проверок (порт LISTEN + xray active ≠ юзеры реально подключаются).

    Вскрыто 2026-06-26: РКН/ТСПУ начал резать VLESS-REALITY/443 на уровне
    потребительских ISP (memory project_vpn_rkn_reality_dpi_block_0625). Весь
    флот лёг 25.06 ~14:00 МСК, а health-check 26ч был зелёным — порты слушали,
    xray active. Чек смотрит ВОЗРАСТ последнего реального коннекта (@kronos в
    access.log) на воркхорс-узлах yc и yc2.

    FAIL только если ОБА (yc И yc2) надёжно прочитаны и ОБА молчат ≥
    VLESS_TRAFFIC_STALE_SEC — подпись флот-сбоя; одиночный тихий узел (юзеры
    мигрировали на другой) не алертит. Узел не прочитался по SSH (rc≠0) — НЕ
    учитываем: reachable-gate сам покроет сетевую проблему, не плодим двойной
    алерт (ср. memory project_vpn_main_ssh_double_alert).
    """
    name = "vless_traffic_flow"
    try:
        states: Dict[str, str] = {}   # host -> "fresh" | "stale" (только надёжные)
        ages: Dict[str, int] = {}
        for host in ("yc", "yc2"):
            r = _run_remote_resilient(host, _VLESS_AGE_PROBE)
            if r.returncode != 0:
                continue  # SSH-проблема — пропускаем (gate покроет)
            out = r.stdout.strip()
            if out == "NOLOG":
                states[host] = "stale"
            elif out.isdigit():
                ages[host] = int(out)
                states[host] = "stale" if int(out) > VLESS_TRAFFIC_STALE_SEC else "fresh"
            # PARSEFAIL / мусор — unknown, не учитываем

        def _fmt(h: str) -> str:
            return f"{h}={ages[h] // 60}м" if h in ages else f"{h}={states.get(h, '?')}"
        msg = f"{_fmt('yc')} {_fmt('yc2')} (порог {VLESS_TRAFFIC_STALE_SEC // 3600}ч)"

        if states.get("yc") == "stale" and states.get("yc2") == "stale":
            return CheckResult(
                name, "FAIL",
                f"VLESS-трафик не идёт ≥{VLESS_TRAFFIC_STALE_SEC // 3600}ч на yc И yc2 "
                f"(xray active, но 0 реальных коннектов — вероятен сетевой блок транспорта)",
                msg,
            )
        return CheckResult(name, "OK", msg)
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}")


def check_https_endpoint() -> CheckResult:
    name = "https_endpoint"
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(HTTPS_URL, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                code = resp.status
        except urllib.error.HTTPError as e:
            code = e.code  # это нормально для 401/403 — Flask отвечает
        if code in EXPECTED_HTTP_CODES:
            return CheckResult(name, "OK", f"HTTP {code}")
        return CheckResult(name, "FAIL", f"unexpected HTTP {code}")
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"connection error: {e}")


# === Remote: batch-выполнение всех проверок одним SSH-вызовом ===
#
# Раньше каждая remote-проверка делала отдельный ssh-коннект. На main это
# давало ложные FAIL'ы (Connection closed by ... port 22) — провайдер
# rate-limit'ит входящие SSH-соединения. Один batch-вызов = один коннект =
# нет rate-limit.

def _spec_to_shell_cmd(spec: Tuple) -> str:
    """Преобразует tuple-спецификацию проверки в shell-команду для batch."""
    kind = spec[0]
    if kind == "systemd":
        return f"systemctl is-active {spec[1]}"
    if kind == "port":
        flag = "tnl" if spec[2] == "tcp" else "unl"
        return f"ss -H{flag} 'sport = :{spec[1]}'"
    if kind == "disk":
        return f"df -P {spec[1]}"
    return "true"


def _build_batch_script(plan: List[Tuple]) -> str:
    """
    Формирует один shell-скрипт со всеми проверками + маркерами для парсинга.
    Первая команда — reachable (`echo ok`), служит и gate'ом и timing'ом.
    """
    parts = [
        # Reachable — индекс 0; echo всегда успешный, факт что мы получили
        # его вывод подтверждает что весь batch выполнился.
        "echo '<<<BEGIN:0>>>'; echo ok; echo \"<<<END:0:$?>>>\""
    ]
    for i, spec in enumerate(plan, start=1):
        cmd = _spec_to_shell_cmd(spec)
        parts.append(f"echo '<<<BEGIN:{i}>>>'; {cmd}; echo \"<<<END:{i}:$?>>>\"")
    return "; ".join(parts)


def _parse_batch_output(output: str, count: int) -> List[Tuple[int, str]]:
    """Возвращает [(rc, output), ...] для каждой команды (count = len(plan) + 1)."""
    results: List[Tuple[int, str]] = []
    for i in range(count):
        begin_marker = f"<<<BEGIN:{i}>>>\n"
        end_prefix = f"<<<END:{i}:"
        try:
            start_pos = output.index(begin_marker) + len(begin_marker)
            end_pos = output.index(end_prefix, start_pos)
            content = output[start_pos:end_pos].rstrip("\n")
            rc_start = end_pos + len(end_prefix)
            rc_end = output.index(">>>", rc_start)
            rc = int(output[rc_start:rc_end])
            results.append((rc, content))
        except (ValueError, IndexError):
            results.append((-1, "(batch marker missing — partial ssh output)"))
    return results


def _spec_to_check_result(host: str, spec: Tuple, rc: int, output: str) -> CheckResult:
    """
    Конвертирует output batch-команды в CheckResult с применением той же логики
    что в одиночных check_systemd_service / check_port_listening / check_disk.
    """
    kind = spec[0]
    output = output.strip()

    if kind == "systemd":
        qname = _qualify(spec[1], host)
        if rc == -1:
            return CheckResult(qname, "FAIL", "batch missing")
        active = output == "active"
        if active:
            return CheckResult(qname, "OK", "active")
        return CheckResult(
            qname, "FAIL",
            f"systemctl is-active вернул: {output or 'unknown'}",
        )

    if kind == "port":
        port, proto = spec[1], spec[2]
        qname = _qualify(f"port_{port}_{proto}", host)
        if rc == -1:
            return CheckResult(qname, "FAIL", "batch missing")
        if rc != 0 and not output:
            return CheckResult(qname, "FAIL", f"ss failed (rc={rc})")
        if not output:
            return CheckResult(qname, "FAIL", f"no listener on :{port}/{proto}")
        first_line = output.split("\n", 1)[0][:120]
        return CheckResult(qname, "OK", f":{port}/{proto} listening", first_line)

    if kind == "disk":
        path = spec[1]
        qname = _qualify(f"disk_{path}", host)
        if rc == -1:
            return CheckResult(qname, "FAIL", "batch missing")
        if rc != 0:
            return CheckResult(qname, "FAIL", f"df failed (rc={rc}): {output[:200]}")
        lines = [ln for ln in output.split("\n") if ln.strip()]
        if len(lines) < 2:
            return CheckResult(qname, "FAIL", f"df output unexpected: {output[:200]}")
        parts = lines[1].split()
        if len(parts) < 5:
            return CheckResult(qname, "FAIL", f"df row unparseable: {lines[1][:200]}")
        try:
            used_pct = float(parts[4].rstrip("%"))
            free_gb = int(parts[3]) / 1024 / 1024
        except (ValueError, IndexError):
            return CheckResult(qname, "FAIL", f"df parse error: {lines[1][:200]}")
        msg = f"used={used_pct:.1f}% free={free_gb:.1f}GB"
        if used_pct > DISK_THRESHOLD_PCT:
            return CheckResult(qname, "FAIL", f"диск > {DISK_THRESHOLD_PCT}% ({msg})", msg)
        return CheckResult(qname, "OK", msg)

    return CheckResult(f"{host}:unknown", "FAIL", f"unknown check kind: {kind}")


def collect_remote_results(host: str, plan: List[Tuple]) -> List[CheckResult]:
    """
    Выполняет все проверки хоста ОДНИМ SSH-вызовом (batch), возвращает
    [CheckResult(<host>:reachable), ...checks].

    Если batch упал целиком (timeout / connection refused / любой ssh-уровень
    failure) — возвращает только <host>:reachable FAIL, остальные проверки
    НЕ возвращаются (gate-логика: их state не трогается, на следующем cron
    когда SSH восстановится — пройдут как обычно).
    """
    reach_qname = f"{host}:reachable"
    script = _build_batch_script(plan)
    last_err = ""
    output = ""
    for attempt in (1, 2):
        try:
            r = _run_remote(host, script, timeout=30)
            output = r.stdout
            # Считаем batch успешным если на выходе есть хотя бы reachable-маркер.
            # rc от ssh при этом может быть != 0 (если одна из проверок упала),
            # это нормально — главное что мы получили output.
            if "<<<BEGIN:0>>>" in output and "<<<END:0:" in output:
                results: List[CheckResult] = [CheckResult(reach_qname, "OK", "ssh reachable")]
                parsed = _parse_batch_output(output, count=len(plan) + 1)
                for spec, (rc, out) in zip(plan, parsed[1:]):
                    results.append(_spec_to_check_result(host, spec, rc, out))
                return results
            # Output есть, но нет наших маркеров — частичный/обрезанный.
            last_err = (r.stderr.strip() or output.strip() or "no markers in output")[:200]
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {30}s"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:200]
        if attempt == 1:
            time.sleep(2)
    return [CheckResult(reach_qname, "FAIL", f"ssh unreachable: {last_err}")]


# === Запуск всех проверок ===

SYSTEMD_SERVICES = ["vpn-bot.service", "vpn-web.service", "nginx.service", "xray.service"]
DOCKER_CONTAINERS = ["amnezia-awg2", "mtproxy-faketls"]


def run_all_checks(state: Dict) -> tuple[List[CheckResult], Dict]:
    """Возвращает (results, new_state_extras)."""
    prev_peer_count = (state.get("awg_peer_count") or {}).get("count")

    results: List[CheckResult] = []
    state_extras: Dict = {}

    # --- Локальные (Fornex) ---
    for svc in SYSTEMD_SERVICES:
        results.append(check_systemd_service(svc))
    for ctn in DOCKER_CONTAINERS:
        results.append(check_docker_container(ctn))

    awg_res, awg_count = check_awg_peer_count(prev_peer_count)
    results.append(awg_res)
    if awg_count is not None:
        state_extras["awg_peer_count"] = {"count": awg_count}

    results.append(check_peers_consistency())
    results.append(check_disk("/"))
    results.append(check_memory_swap())
    results.append(check_le_cert())
    results.append(check_https_endpoint())
    results.append(check_vless_config_consistency())
    results.append(check_vless_traffic_flow())

    # --- Remote (main, yc): batch-вызов на хост, gate по reachable ---
    # Все проверки одного хоста выполняются ОДНИМ SSH-вызовом через
    # collect_remote_results. Это решает проблему «Connection closed by ...
    # port 22» которая давала ложные FAIL'ы на 5-6-м SSH-коннекте подряд
    # (вероятно rate-limit на стороне провайдера main).
    for host in REMOTE_HOSTS:
        host_results = collect_remote_results(host, REMOTE_CHECK_PLAN[host])
        results.extend(host_results)
        # Если reachable FAIL — collect_remote_results вернул только один
        # элемент (gate), остальные проверки скипнуты автоматически.
        if len(host_results) == 1 and host_results[0].status == "FAIL":
            logger.warning("Skipping %s remote checks: %s", host, host_results[0].message)

    return results, state_extras


# === State ===

def load_state() -> Dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: Dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# === TG алерты ===

def send_tg(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:  # noqa: BLE001
        logger.error("Не удалось отправить TG-алерт: %s", e)
        return False


def format_fail_alert(r: CheckResult) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = (
        f"🔴 <b>ALERT: {r.name}</b>\n"
        f"<i>{now_str}</i>\n\n"
        f"{r.message}"
    )
    if r.detail:
        text += f"\n\n<pre>{r.detail[:1500]}</pre>"
    return text


def format_resolve_alert(r: CheckResult, prev_changed_at: Optional[str]) -> str:
    downtime = ""
    if prev_changed_at:
        try:
            prev_dt = datetime.fromisoformat(prev_changed_at)
            delta_min = max(1, int((datetime.now(timezone.utc) - prev_dt).total_seconds() / 60))
            downtime = f"\n\nБыл DOWN: {delta_min} мин"
        except (ValueError, TypeError):
            pass
    return f"🟢 <b>RESOLVED: {r.name}</b>\n\n{r.message}{downtime}"


# === Main ===

def main() -> int:
    parser = argparse.ArgumentParser(description="Health-check для VPN-инфраструктуры (Fornex + main + yc)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только печать на stdout, без state и без TG-алертов",
    )
    args = parser.parse_args()

    # Single-instance guard: при overlap cron + manual run (или двух cron'ов
    # если предыдущий прогон затянулся из-за SSH-таймаутов) race condition
    # приводил к двойным алертам — два процесса читали один state, оба
    # отправляли RESOLVE/ALERT. Lock закрывает.
    # Dry-run пропускает блокировку — он безопасен (не пишет state, не шлёт).
    lock_fp = None
    if not args.dry_run:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_fp = open(LOCK_PATH, "w")
        try:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("Another health_check instance is running, exiting cleanly")
            lock_fp.close()
            return 0

    state = {} if args.dry_run else load_state()
    results, state_extras = run_all_checks(state)

    # Сводка на stdout
    print("=" * 70)
    print(f"Health-check {'(DRY RUN)' if args.dry_run else ''} — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print("=" * 70)
    for r in results:
        icon = "🟢" if r.status == "OK" else "🔴"
        print(f"{icon} {r.name:<32} {r.status:<6} {r.message}")
        if r.status == "FAIL" and r.detail:
            for line in r.detail.split("\n"):
                print(f"     {line}")

    if args.dry_run:
        print("\n(dry-run: state не записан, алерты не отправлены)")
        return 0

    # === Production: сверка со state + алерты ===
    from bot.config import load_config

    config = load_config()
    if not config.bot_token or not config.admin_id:
        logger.error("BOT_TOKEN / ADMIN_TELEGRAM_ID не настроены — алерты не уйдут")
        return 1

    now_iso = datetime.now(timezone.utc).isoformat()
    # Стартуем с прежнего state — для skipped-проверок (gate-FAIL) их
    # прошлый статус сохранится без изменений.
    new_state: Dict = {k: v for k, v in state.items() if isinstance(v, dict)}
    alerts: List[tuple[str, CheckResult, Optional[str]]] = []

    for r in results:
        prev = state.get(r.name, {})
        prev_status = prev.get("status", "OK")  # первый запуск = OK по умолчанию
        prev_changed = prev.get("changed_at")

        if r.status != prev_status:
            alerts.append((r.status, r, prev_changed))
            new_state[r.name] = {"status": r.status, "changed_at": now_iso}
        else:
            new_state[r.name] = prev or {"status": r.status, "changed_at": now_iso}

    # Сохраняем extras (peer count для следующей проверки)
    for k, v in state_extras.items():
        new_state.setdefault(k, {}).update(v)

    # Отправка
    for kind, r, prev_changed in alerts:
        if kind == "FAIL":
            text = format_fail_alert(r)
        else:
            text = format_resolve_alert(r, prev_changed)
        ok = send_tg(config.bot_token, str(config.admin_id), text)
        logger.info("Alert %s sent=%s for %s", kind, ok, r.name)

    save_state(new_state)

    failed = sum(1 for r in results if r.status == "FAIL")
    logger.info(
        "Health-check done: %d OK, %d FAIL, %d alerts sent",
        len(results) - failed,
        failed,
        len(alerts),
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
