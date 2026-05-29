#!/usr/bin/env python3
"""
Health-check / alerting для eu1.

Каждые 15 минут проходит 12 проверок (systemd сервисы, docker контейнеры,
AWG peer-count, peers.json/awg consistency, диск, swap, LE сертификат,
HTTPS endpoint). При **смене статуса** (OK→FAIL или FAIL→OK) шлёт алерт
владельцу в Telegram через прямой HTTP API (urllib, без инстанса бота).

State хранится в /var/lib/vpn-health/state.json — нужен чтобы не спамить
повторными алертами при той же ошибке.

Запуск:
    # Production (cron)
    /opt/vpnservice/venv/bin/python scripts/health_check.py

    # Тест-режим: печать всех проверок на stdout, без state и алертов
    /opt/vpnservice/venv/bin/python scripts/health_check.py --dry-run

ENV (через bot/config.py): BOT_TOKEN, ADMIN_TELEGRAM_ID
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

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
CERT_PATH = "/etc/letsencrypt/live/supportkronos.online/cert.pem"
HTTPS_URL = "https://supportkronos.online:8443/"
# 401/403 — нормально (Flask отвечает, просто нужна авторизация для /)
EXPECTED_HTTP_CODES = {200, 301, 302, 401, 403}

STATE_PATH = pathlib.Path("/var/lib/vpn-health/state.json")
SYSTEMCTL = "/bin/systemctl"
DOCKER = "/usr/bin/docker"


@dataclass
class CheckResult:
    name: str
    status: str  # "OK" | "FAIL"
    message: str
    detail: str = ""


# === Helpers ===

def _run(cmd: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# === Проверки ===

def check_systemd_service(service: str) -> CheckResult:
    try:
        r = _run([SYSTEMCTL, "is-active", service])
        active = r.stdout.strip() == "active"
        if active:
            return CheckResult(service, "OK", "active")
        # Захватим последние строки лога для контекста алерта
        log = _run(["journalctl", "-u", service, "-n", "5", "--no-pager"])
        return CheckResult(
            service,
            "FAIL",
            f"systemctl is-active вернул: {r.stdout.strip() or 'unknown'}",
            log.stdout.strip()[-500:],
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(service, "FAIL", f"check error: {e}")


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


def check_disk(path: str = "/") -> CheckResult:
    name = f"disk_{path}"
    try:
        s = os.statvfs(path)
        used_pct = (1 - s.f_bavail / s.f_blocks) * 100
        free_gb = s.f_bavail * s.f_frsize / 1024**3
        msg = f"used={used_pct:.1f}% free={free_gb:.1f}GB"
        if used_pct > DISK_THRESHOLD_PCT:
            return CheckResult(name, "FAIL", f"диск > {DISK_THRESHOLD_PCT}% ({msg})", msg)
        return CheckResult(name, "OK", msg)
    except Exception as e:  # noqa: BLE001
        return CheckResult(name, "FAIL", f"check error: {e}")


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


# === Запуск всех проверок ===

SYSTEMD_SERVICES = ["vpn-bot.service", "vpn-web.service", "nginx.service", "xray.service"]
DOCKER_CONTAINERS = ["amnezia-awg2", "mtproxy-faketls"]


def run_all_checks(state: Dict) -> tuple[List[CheckResult], Dict]:
    """Возвращает (results, new_state_extras)."""
    prev_peer_count = (state.get("awg_peer_count") or {}).get("count")

    results: List[CheckResult] = []
    state_extras: Dict = {}

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
    parser = argparse.ArgumentParser(description="Health-check для eu1")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только печать на stdout, без state и без TG-алертов",
    )
    args = parser.parse_args()

    state = {} if args.dry_run else load_state()
    results, state_extras = run_all_checks(state)

    # Сводка на stdout
    print("=" * 70)
    print(f"Health-check {'(DRY RUN)' if args.dry_run else ''} — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print("=" * 70)
    for r in results:
        icon = "🟢" if r.status == "OK" else "🔴"
        print(f"{icon} {r.name:<28} {r.status:<6} {r.message}")
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
    new_state: Dict = {}
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
