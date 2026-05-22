"""
Веб-панель мониторинга VPN-сервиса.

Отображает:
- Статус серверов
- Количество подключённых устройств
- Статистику использования
- Список пользователей (для админа)
"""

import csv
import functools
import io
import json
import logging
import pathlib
import shlex
import socket
import subprocess
import threading
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

# Добавляем путь к модулям бота
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from bot.config import get_effective_mtproto_proxy_link, load_config, _parse_env_file
from bot.storage import Peer, User, get_all_peers, get_all_users, find_user
from bot.database import (
    db_create_otp,
    db_verify_otp,
    db_create_session,
    db_verify_session,
    db_find_user_by_email,
    db_upsert_user,
    db_get_effective_telegram_id,
    db_get_all_users,
    init_db,
)
from bot.email_otp import generate_otp, send_otp_email
from bot.wireguard_peers import (
    WireGuardError,
    create_amneziawg_peer_and_config_for_user,
    execute_server_command,
    generate_vpn_url,
    regenerate_amneziawg_peer_and_config_for_user,
    find_peer_by_telegram_id,
    is_amneziawg_eu1_configured,
)
from bot.vless_peers import create_vless_client_for_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Загружаем конфиг
import os
try:
    config = load_config()
    ADMIN_ID = config.admin_id
    # Инициализируем SQLite DB (включая миграцию users.json)
    init_db(whitelist_seed=config.telegram_id_whitelist or [])
except Exception as e:
    logger.error(f"Ошибка загрузки конфига/БД: {e}")
    ADMIN_ID = None
    config = None

app.secret_key = (getattr(config, "admin_secret", None) or os.urandom(32).hex())

_recovery_lock = threading.Lock()


def _require_admin_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        admin_secret = getattr(config, "admin_secret", None) if config else None
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == "admin" and admin_secret and password == admin_secret:
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Неверный логин или пароль"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _check_recovery_secret() -> Optional[tuple]:
    """
    Проверяет RECOVERY_SECRET из заголовка X-Recovery-Secret или query-параметра recovery_secret.
    Возвращает None если всё ок, или (jsonify(error), status_code) если проверка не прошла.
    Если секрет не задан в env — запрещаем доступ к legacy-эндпоинтам (fail secure).
    """
    secret = getattr(config, "recovery_secret", None) if config else None
    if not secret:
        return jsonify({"error": "Recovery secret not configured on server"}), 503
    provided = (
        request.headers.get("X-Recovery-Secret")
        or request.args.get("recovery_secret")
        or (request.get_json(silent=True) or {}).get("recovery_secret")
    )
    if not provided or provided != secret:
        return jsonify({"error": "Unauthorized"}), 403
    return None


def _parse_tg_proxy_link(link: Optional[str]) -> Dict[str, str]:
    """
    Parse tg://proxy?server=...&port=...&secret=... into dict.
    Returns empty dict if link is missing/invalid.
    """
    if not link:
        return {}
    try:
        # Example: tg://proxy?server=185.21.8.91&port=443&secret=...
        parsed = urllib.parse.urlparse(link)
        if not parsed.query:
            return {}
        qs = urllib.parse.parse_qs(parsed.query)
        out: Dict[str, str] = {}
        for k, v in qs.items():
            if v:
                out[k] = str(v[0])
        return out
    except Exception:
        return {}


def _restart_proxy_container_on_server(server_id: str, candidates: List[str]) -> Dict[str, str]:
    """
    Restarts first docker container that matches any candidate name substring.
    Uses SSH via existing VPN utilities.
    """
    # List running containers
    stdout, stderr = execute_server_command(
        server_id,
        "docker ps --format '{{.Names}}'",
        timeout=25,
    )
    names = []
    for line in (stdout or "").splitlines():
        name = line.strip()
        if name:
            names.append(name)

    matched = None
    for c in candidates:
        for n in names:
            if c in n:
                matched = n
                break
        if matched:
            break

    if not matched:
        return {
            "ok": "false",
            "error": f"No docker container matched candidates on {server_id}. Candidates={candidates}, running={names}",
        }

    # Restart matched container
    stdout2, stderr2 = execute_server_command(
        server_id,
        f"docker restart {matched}",
        timeout=25,
    )
    _ = stdout2  # restart output not always useful
    return {
        "ok": "true",
        "server_id": server_id,
        "container": matched,
        "stderr": (stderr2 or "").strip(),
    }


def _determine_target_server_id_from_env(proxy_server_ip: str) -> Optional[str]:
    """
    Map proxy server IP to our internal server_id ("main" or "eu1") using env_vars.txt.
    """
    base = pathlib.Path(__file__).parent.parent
    env = _parse_env_file(base / "env_vars.txt")
    if not proxy_server_ip:
        return None

    main_host = env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST")
    eu1_host = env.get("WG_EU1_ENDPOINT_HOST") or env.get("WG_EU1_SSH_HOST")

    if eu1_host and proxy_server_ip == eu1_host:
        return "eu1"
    if main_host and proxy_server_ip == main_host:
        return "main"
    return None


def check_server_status(server_id: str, endpoint_host: Optional[str] = None) -> Dict[str, any]:
    """
    Проверяет статус VPN-сервера.
    
    Returns:
        dict с полями: status (online/offline), ping_ms, last_check
    """
    if not endpoint_host:
        return {
            "status": "unknown",
            "ping_ms": None,
            "last_check": datetime.now().isoformat(),
            "error": "Endpoint host not specified"
        }
    
    try:
        # Простая проверка ping (может не работать на всех системах)
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", endpoint_host],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # Парсим время ответа из вывода ping
            ping_ms = None
            for line in result.stdout.split("\n"):
                if "time=" in line:
                    try:
                        ping_ms = float(line.split("time=")[1].split(" ")[0])
                        break
                    except (IndexError, ValueError):
                        pass
            
            return {
                "status": "online",
                "ping_ms": ping_ms,
                "last_check": datetime.now().isoformat()
            }
        else:
            return {
                "status": "offline",
                "ping_ms": None,
                "last_check": datetime.now().isoformat(),
                "error": "Ping failed"
            }
    except Exception as e:
        logger.exception(f"Ошибка проверки сервера {server_id}: {e}")
        return {
            "status": "error",
            "ping_ms": None,
            "last_check": datetime.now().isoformat(),
            "error": str(e)
        }


def _parse_wg_dump_transfer(stdout: str) -> Dict[str, tuple]:
    """Парсит dump → public_key -> (rx_bytes, tx_bytes)."""
    result: Dict[str, tuple] = {}
    for line in stdout.strip().split("\n")[1:]:
        parts = line.split("\t")
        if len(parts) >= 7:
            try:
                result[parts[0].strip()] = (int(parts[5]), int(parts[6]))
            except (ValueError, IndexError):
                continue
    return result


def _parse_wg_dump_full(stdout: str) -> Dict[str, Dict]:
    """Парсит dump → public_key -> {rx, tx, last_handshake}."""
    result: Dict[str, Dict] = {}
    for line in stdout.strip().split("\n")[1:]:
        parts = line.split("\t")
        if len(parts) >= 7:
            try:
                result[parts[0].strip()] = {
                    "rx": int(parts[5]),
                    "tx": int(parts[6]),
                    "last_handshake": int(parts[4]),
                }
            except (ValueError, IndexError):
                continue
    return result


def _get_awg_dump_eu1() -> str:
    """awg живёт внутри Docker-контейнера amnezia-awg2."""
    try:
        out = subprocess.run(
            ["docker", "exec", "amnezia-awg2", "awg", "show", "awg0", "dump"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return ""


def _get_wg_transfer_for_server(server_id: str) -> Dict[str, tuple]:
    """Трафик по pubkey для eu1 (локально, панель на том же хосте)."""
    if server_id == "eu1":
        stdout = _get_awg_dump_eu1()
        if stdout:
            return _parse_wg_dump_transfer(stdout)
        return {}
    return {}


def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Проверяет доступность TCP-порта на хосте."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


@app.route("/")
@_require_admin_auth
def index():
    """Главная страница с общей статистикой."""
    try:
        peers = get_all_peers()
        users = get_all_users()
        
        # Статистика
        active_peers = [p for p in peers if p.active]
        active_users = [u for u in users if u.active]
        
        # Группировка по серверам
        by_server: Dict[str, int] = {}
        for peer in active_peers:
            by_server[peer.server_id] = by_server.get(peer.server_id, 0) + 1
        
        # Сводка по пользователям (без telegram_id): имя/псевдоним, серверы, кол-во пиров
        users_summary: List[Dict] = []
        for i, user in enumerate(users):
            user_peers = [p for p in peers if p.telegram_id == user.telegram_id]
            if not user_peers:
                continue
            servers = list({p.server_id for p in user_peers if p.active})
            if user.username:
                display_name = f"@{user.username}"
            elif user.telegram_id:
                display_name = f"ID {user.telegram_id}"
            elif user.email:
                display_name = user.email
            else:
                display_name = f"Пользователь {i + 1}"
            users_summary.append({
                "display_name": display_name,
                "servers": sorted(servers),
                "peer_count": len([p for p in user_peers if p.active]),
            })
        
        stats = {
            "total_users": len(users),
            "active_users": len(active_users),
            "total_peers": len(peers),
            "active_peers": len(active_peers),
            "by_server": by_server,
            "users_summary": users_summary,
        }
        
        return render_template("index.html", stats=stats)
    except Exception as e:
        logger.exception(f"Ошибка на главной странице: {e}")
        return f"Ошибка: {e}", 500


@app.route("/recovery")
def recovery_page():
    """Отдельная страница для восстановления (Telegram proxy / VPN конфиг)."""
    recovery_secret = getattr(config, "recovery_secret", "") if config else ""
    return render_template("recovery.html", stats={}, recovery_secret=recovery_secret)


@app.route("/api/servers")
def api_servers():
    """API: статус серверов."""
    try:
        from bot.wireguard_peers import get_available_servers, canonical_env_server_id
        from bot.config import _parse_env_file

        servers_info = get_available_servers()
        env = _parse_env_file(pathlib.Path(__file__).parent.parent / "env_vars.txt")

        servers_status = {}
        for server_id, info in servers_info.items():
            physical = canonical_env_server_id(server_id)
            if physical == "main":
                endpoint_host = env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST")
            else:
                endpoint_host = env.get(f"WG_{physical.upper()}_ENDPOINT_HOST")

            status = check_server_status(server_id, endpoint_host)
            servers_status[server_id] = {
                "name": info["name"],
                "description": info.get("description", ""),
                "endpoint": endpoint_host,
                **status
            }
        
        return jsonify(servers_status)
    except Exception as e:
        logger.exception(f"Ошибка API серверов: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/services")
def api_services():
    """API: статус сервисов eu1 (AmneziaWG локально + VLESS порт)."""
    try:
        env = _parse_env_file(pathlib.Path(__file__).parent.parent / "env_vars.txt")
        eu1_host = env.get("WG_EU1_ENDPOINT_HOST") or env.get("WG_EU1_SSH_HOST") or "185.21.8.91"

        dump = _get_awg_dump_eu1()
        awg_ok = bool(dump.strip())

        vless_port = 443
        vless_ok = check_port("158.160.0.1", vless_port, timeout=2.0)
        try:
            yc_host = env.get("VLESS_YC_HOST") or ""
            if yc_host:
                vless_ok = check_port(yc_host, vless_port, timeout=2.0)
        except Exception:
            pass

        services_list = [
            {
                "service": "AmneziaWG",
                "status": "online" if awg_ok else "offline",
                "note": "eu1 — обход блокировок из РФ",
            },
            {
                "service": "VLESS+REALITY (мобильный)",
                "status": "online" if vless_ok else "unknown",
                "note": "YC VM → eu1, для LTE/5G",
            },
        ]
        return jsonify({"services": services_list})
    except Exception as e:
        logger.exception(f"Ошибка API сервисов: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/users")
def api_users():
    """API: список пользователей (только для админа)."""
    admin_secret = getattr(config, "admin_secret", None) if config else None
    if not admin_secret:
        return jsonify({"error": "Admin secret not configured on server"}), 503
    admin_key = request.args.get("admin_key")
    if not admin_key or admin_key != admin_secret:
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        users = get_all_users()
        peers = get_all_peers()
        
        # Группируем пиры по пользователям
        users_data = []
        for user in users:
            user_peers = [p for p in peers if p.telegram_id == user.telegram_id]
            users_data.append({
                "telegram_id": user.telegram_id,
                "username": user.username,
                "role": user.role,
                "active": user.active,
                "peers_count": len(user_peers),
                "active_peers": [p.server_id for p in user_peers if p.active]
            })
        
        return jsonify(users_data)
    except Exception as e:
        logger.exception(f"Ошибка API пользователей: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/traffic")
def api_traffic():
    """API: трафик по пользователям с last_handshake."""
    try:
        peers = get_all_peers()
        dump_stdout = _get_awg_dump_eu1()
        full_data = _parse_wg_dump_full(dump_stdout) if dump_stdout else {}

        proxy_ts: Dict[int, Optional[str]] = {
            u["telegram_id"]: u.get("proxy_requested_at")
            for u in db_get_all_users()
            if u.get("telegram_id")
        }

        by_user: Dict[int, Dict] = {}
        for peer in peers:
            if peer.server_id != "eu1" or not peer.active:
                continue
            pk = (peer.public_key or "").strip()
            d = full_data.get(pk) or {"rx": 0, "tx": 0, "last_handshake": 0}
            uid = peer.telegram_id
            if uid not in by_user:
                user = find_user(uid)
                by_user[uid] = {
                    "telegram_id": uid,
                    "username": user.username if user else None,
                    "wg_ip": peer.wg_ip,
                    "rx_bytes": 0,
                    "tx_bytes": 0,
                    "last_handshake": 0,
                    "platform": peer.platform or "pc",
                    "proxy_requested_at": proxy_ts.get(uid),
                }
            by_user[uid]["rx_bytes"] += d["rx"]
            by_user[uid]["tx_bytes"] += d["tx"]
            # Платформа — та, у которой самый свежий last_handshake
            if d["last_handshake"] > by_user[uid]["last_handshake"]:
                by_user[uid]["last_handshake"] = d["last_handshake"]
                by_user[uid]["platform"] = peer.platform or "pc"

        # Сортировка: сначала по последней активности (handshake ИЛИ нажатие прокси),
        # потом по трафику. Так "только-прокси-юзеры" поднимаются вверх и видны.
        def _activity_ts(u: Dict) -> int:
            hs = u.get("last_handshake") or 0
            proxy_ts = u.get("proxy_requested_at") or ""
            proxy_unix = 0
            if proxy_ts:
                try:
                    proxy_unix = int(datetime.strptime(proxy_ts, "%Y-%m-%d %H:%M:%S").timestamp())
                except (ValueError, TypeError):
                    pass
            return max(hs, proxy_unix)

        users_list = sorted(
            by_user.values(),
            key=lambda x: (_activity_ts(x), x["rx_bytes"] + x["tx_bytes"]),
            reverse=True,
        )
        resp = jsonify({
            "users": users_list,
            "last_update": datetime.now().isoformat(),
        })
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    except Exception as e:
        logger.exception(f"Ошибка API трафика: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    """
    API: сводная статистика активности.

    Активность по handshake AmneziaWG на eu1 + использование MTProxy.
    Метрики:
      - total_users / active_users (флаг active в БД)
      - email_verified_users
      - active_24h / active_7d / active_30d (handshake свежее N часов/дней)
      - proxy_requests_30d (пользователей, нажимавших MTProxy за 30 дней)
      - total_rx_bytes / total_tx_bytes (агрегат за время существования peer'ов)
    """
    try:
        import time as _t
        peers = get_all_peers()
        users = get_all_users()
        db_users = db_get_all_users()

        active_peers = [p for p in peers if p.active]
        active_users = [u for u in users if u.active]

        by_server: Dict[str, int] = {}
        for peer in active_peers:
            by_server[peer.server_id] = by_server.get(peer.server_id, 0) + 1

        # Activity windows: handshake по живым peer'ам eu1
        dump_stdout = _get_awg_dump_eu1()
        full_data = _parse_wg_dump_full(dump_stdout) if dump_stdout else {}

        now_ts = int(_t.time())
        win_24h = now_ts - 86400
        win_7d = now_ts - 7 * 86400
        win_30d = now_ts - 30 * 86400

        # tg_id → самый свежий handshake
        latest_hs_by_user: Dict[int, int] = {}
        total_rx = 0
        total_tx = 0
        for peer in active_peers:
            if peer.server_id != "eu1":
                continue
            d = full_data.get((peer.public_key or "").strip())
            if not d:
                continue
            hs = d.get("last_handshake", 0) or 0
            total_rx += d.get("rx", 0) or 0
            total_tx += d.get("tx", 0) or 0
            prev = latest_hs_by_user.get(peer.telegram_id, 0)
            if hs > prev:
                latest_hs_by_user[peer.telegram_id] = hs

        active_24h = sum(1 for hs in latest_hs_by_user.values() if hs >= win_24h)
        active_7d = sum(1 for hs in latest_hs_by_user.values() if hs >= win_7d)
        active_30d = sum(1 for hs in latest_hs_by_user.values() if hs >= win_30d)

        # Email-verified
        email_verified = sum(1 for u in db_users if u.get("email_verified"))

        # MTProxy: пользователей нажимавших за 30 дней
        proxy_requests_30d = 0
        for u in db_users:
            proxy_ts = u.get("proxy_requested_at")
            if not proxy_ts:
                continue
            try:
                t = int(datetime.strptime(proxy_ts, "%Y-%m-%d %H:%M:%S").timestamp())
                if t >= win_30d:
                    proxy_requests_30d += 1
            except (ValueError, TypeError):
                continue

        return jsonify({
            "total_users": len(users),
            "active_users": len(active_users),
            "total_peers": len(peers),
            "active_peers": len(active_peers),
            "email_verified_users": email_verified,
            "active_24h": active_24h,
            "active_7d": active_7d,
            "active_30d": active_30d,
            "proxy_requests_30d": proxy_requests_30d,
            "total_rx_bytes": total_rx,
            "total_tx_bytes": total_tx,
            "by_server": by_server,
            "last_update": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.exception(f"Ошибка API статистики: {e}")
        return jsonify({"error": str(e)}), 500


def _verify_email_session(body: dict) -> tuple:
    """
    Универсальный auth по email-token (для всех recovery endpoints с email-flow).
    Возвращает (user_row, telegram_id) при успехе или (None, error_response) при отказе.
    """
    token = (body.get("token") or "").strip()
    if not token:
        return None, (jsonify({"error": "token обязателен"}), 401)

    email = db_verify_session(token)
    if not email:
        return None, (jsonify({"error": "Сессия недействительна или истекла. Войди заново."}), 401)

    user_row = db_find_user_by_email(email)
    if not user_row or not user_row.get("active"):
        return None, (jsonify({"error": "Пользователь не найден или заблокирован."}), 403)

    telegram_id = user_row.get("telegram_id")
    if not telegram_id:
        return None, (jsonify({"error": "Учётная запись не привязана к Telegram. Обратись к владельцу бота."}), 403)

    return (user_row, int(telegram_id)), None


@app.route("/api/recovery/proxy-link-by-email", methods=["POST"])
def api_recovery_proxy_link_by_email():
    """
    Возвращает актуальную tg://proxy ссылку (как /proxy в боте), без перезапуска контейнера.
    Auth: email-token из активной OTP-сессии.
    Тело: {token}
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err

        fresh_cfg = load_config()
        effective_link = get_effective_mtproto_proxy_link(fresh_cfg) or ""
        effective_link = effective_link.strip()
        if not effective_link.startswith("tg://proxy"):
            return jsonify({"error": "MTPROTO proxy link is not configured"}), 503

        return jsonify({
            "ok": True,
            "mtproto_proxy_link": effective_link,
            "hint": (
                "Та же ссылка, что по команде /proxy в боте. "
                "Нажми кнопку, чтобы открыть её прямо в Telegram, или скопируй вручную."
            ),
        })
    except Exception as e:
        logger.exception("Ошибка api/recovery/proxy-link-by-email: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/recovery/awg-config-by-email", methods=["POST"])
def api_recovery_awg_config_by_email():
    """
    Основной VPN (AmneziaWG eu1) с выбором платформы. Auth: email-token.
    Тело: {token, platform: "pc" | "ios" | "android"}
    Ответ: {ok, filename, config, vpn_url?}
        - config: текст .conf файла
        - vpn_url: vpn:// deep link (только для platform=android — для удобного импорта в AmneziaVPN)
        - filename: рекомендуемое имя файла (awg_eu1.conf)
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        _user_row, telegram_id = auth

        platform = str(body.get("platform") or "pc").strip().lower()
        if platform not in ("pc", "ios", "android"):
            return jsonify({"error": "platform must be one of: pc, ios, android"}), 400

        if not is_amneziawg_eu1_configured():
            return jsonify({"error": "AmneziaWG is not configured on server. Try later or ask owner."}), 503

        android_safe = (platform == "android")
        peer = find_peer_by_telegram_id(telegram_id, server_id="eu1", platform=platform)
        if peer and peer.active:
            peer, cfg = regenerate_amneziawg_peer_and_config_for_user(
                telegram_id, android_safe=android_safe, server_id="eu1", platform=platform
            )
        else:
            peer, cfg = create_amneziawg_peer_and_config_for_user(
                telegram_id, android_safe=android_safe, server_id="eu1", platform=platform
            )

        response = {
            "ok": True,
            "filename": f"awg_{peer.server_id}.conf",
            "config": cfg,
            "platform": platform,
        }
        if platform == "android":
            try:
                response["vpn_url"] = generate_vpn_url(cfg)
            except Exception as e:
                logger.warning("Не удалось сгенерировать vpn:// deep link: %s", e)
        return jsonify(response)
    except Exception as e:
        logger.exception("Ошибка api/recovery/awg-config-by-email: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/recovery/mobile-link-by-email", methods=["POST"])
def api_recovery_mobile_link_by_email():
    """
    Мобильный резерв (VLESS+REALITY) с выбором оператора. Auth: email-token.
    Тело: {token, operator: "megafon" | "yota" | "beeline" | "mts" | "tele2" | "tmobile" | "other"}
    Ответ: {ok, vless_url, operator, hint}

    Routing:
        - megafon | yota → vless_cdn_tls_share_url (main REALITY, SNI=cloud.mail.ru) — работает при БС
        - другие → vless_reality_share_url (eu1/yc REALITY, SNI=www.microsoft.com)
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err

        operator = str(body.get("operator") or "").strip().lower()
        if operator not in ("megafon", "yota", "beeline", "mts", "tele2", "tmobile", "other"):
            return jsonify({"error": "operator must be one of: megafon, yota, beeline, mts, tele2, tmobile, other"}), 400

        fresh_cfg = load_config()
        if operator in ("megafon", "yota"):
            vless_url = (
                getattr(fresh_cfg, "vless_cdn_tls_share_url", None)
                or getattr(fresh_cfg, "vless_cdn_share_url", None)
                or getattr(fresh_cfg, "vless_reality_share_url", None)
            )
            hint = (
                "Резервная ссылка для Мегафон/Yota — работает при активных белых списках РКН. "
                "Скопируй vless://... целиком и импортируй в приложение."
            )
        else:
            vless_url = getattr(fresh_cfg, "vless_reality_share_url", None)
            hint = (
                "Резервный мобильный VPN. Скопируй vless://... целиком. "
                "Android: v2rayNG или Hiddify → «+» → «Импорт из буфера». "
                "iOS: Streisand, FoXray, V2Box или Hiddify → импорт ссылки."
            )

        if not vless_url:
            return jsonify({"error": "VLESS link is not configured on server"}), 503

        return jsonify({
            "ok": True,
            "vless_url": vless_url.strip(),
            "operator": operator,
            "hint": hint,
        })
    except Exception as e:
        logger.exception("Ошибка api/recovery/mobile-link-by-email: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/send-otp", methods=["POST"])
def api_auth_send_otp():
    """Отправляет OTP-код на указанный email. Создаёт пользователя если нет."""
    try:
        body = request.get_json() or {}
        email = (body.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return jsonify({"error": "Некорректный email"}), 400

        if not config or not config.resend_api_key:
            return jsonify({"error": "Email-сервис не настроен. Обратись к администратору."}), 503

        user_row = db_find_user_by_email(email)
        if not user_row:
            db_upsert_user({
                "email": email,
                "role": "user",
                "active": True,
                "preferred_server_id": "eu1",
                "email_verified": False,
            })

        code = generate_otp()
        db_create_otp(email, code)

        sent = send_otp_email(
            to_email=email,
            code=code,
            api_key=config.resend_api_key,
            from_email=config.resend_from_email,
        )
        if not sent:
            return jsonify({"error": "Не удалось отправить письмо. Проверь адрес или попробуй позже."}), 502

        return jsonify({"ok": True, "message": f"Код отправлен на {email}"})
    except Exception as e:
        logger.exception("Ошибка api/auth/send-otp: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/verify-otp", methods=["POST"])
def api_auth_verify_otp():
    """Проверяет OTP. При успехе возвращает session token (60 мин)."""
    try:
        body = request.get_json() or {}
        email = (body.get("email") or "").strip().lower()
        code = (body.get("code") or "").strip().replace(" ", "")

        if not email or not code:
            return jsonify({"error": "email и code обязательны"}), 400

        if not db_verify_otp(email, code):
            return jsonify({"error": "Неверный или просроченный код"}), 401

        db_upsert_user({"email": email, "email_verified": True, "active": True})
        token = db_create_session(email, ttl_minutes=60)
        return jsonify({"ok": True, "token": token})
    except Exception as e:
        logger.exception("Ошибка api/auth/verify-otp: %s", e)
        return jsonify({"error": str(e)}), 500


def _check_admin_secret() -> Optional[tuple]:
    """
    Проверяет ADMIN_SECRET из query-параметра admin_key или заголовка X-Admin-Key.
    Возвращает None если ок, иначе (jsonify(error), status_code).
    """
    admin_secret = getattr(config, "admin_secret", None) if config else None
    if not admin_secret:
        return jsonify({"error": "Admin secret not configured on server"}), 503
    provided = (
        request.headers.get("X-Admin-Key")
        or request.args.get("admin_key")
        or (request.get_json(silent=True) or {}).get("admin_key")
    )
    if not provided or provided != admin_secret:
        return jsonify({"error": "Unauthorized"}), 403
    return None


@app.route("/api/admin/users.csv")
def api_admin_users_csv():
    """
    Экспортирует всех пользователей в CSV.
    Защищено admin_key (query-параметр или X-Admin-Key header).

    Поля: id, telegram_id, username, email, role, active, preferred_server_id,
          email_verified, has_vless, peers_count, created_at
    """
    err = _check_admin_secret()
    if err is not None:
        return err
    try:
        from bot.database import db_get_all_users
        users = db_get_all_users()
        peers = get_all_peers()

        # Индекс: telegram_id → кол-во активных пиров
        peer_count: Dict[int, int] = {}
        for p in peers:
            if p.active:
                peer_count[p.telegram_id] = peer_count.get(p.telegram_id, 0) + 1

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "telegram_id", "username", "email", "role",
            "active", "preferred_server_id", "email_verified",
            "has_vless", "peers_count", "created_at",
        ])
        for u in users:
            tid = u.get("telegram_id")
            writer.writerow([
                u.get("id", ""),
                tid or "",
                u.get("username", ""),
                u.get("email", ""),
                u.get("role", "user"),
                "1" if u.get("active") else "0",
                u.get("preferred_server_id", ""),
                "1" if u.get("email_verified") else "0",
                "1" if u.get("vless_uuid") else "0",
                peer_count.get(tid, 0) if tid else 0,
                u.get("created_at", ""),
            ])

        csv_data = output.getvalue()
        filename = f"vpn_users_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            csv_data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Ошибка /api/admin/users.csv: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/sync-sheets", methods=["POST"])
def api_admin_sync_sheets():
    """
    Запускает синхронизацию пользователей в Google Sheets.
    Защищено admin_key.
    Возвращает {ok, updated, message} или {ok: false, error}.
    """
    err = _check_admin_secret()
    if err is not None:
        return err
    try:
        from bot.google_sheets import sync_users_to_sheets
        result = sync_users_to_sheets()
        status = 200 if result.get("ok") else 502
        return jsonify(result), status
    except ImportError:
        return jsonify({"ok": False, "error": "bot.google_sheets модуль не найден"}), 500
    except Exception as e:
        logger.exception("Ошибка /api/admin/sync-sheets: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    import os
    debug = os.environ.get("FLASK_ENV") == "development"
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug)
