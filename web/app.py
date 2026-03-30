"""
Веб-панель мониторинга VPN-сервиса.

Отображает:
- Статус серверов
- Количество подключённых устройств
- Статистику использования
- Список пользователей (для админа)
"""

import json
import logging
import pathlib
import socket
import subprocess
import threading
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

# Добавляем путь к модулям бота
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from bot.config import get_effective_mtproto_proxy_link, load_config, _parse_env_file
from bot.storage import Peer, User, get_all_peers, get_all_users, find_user
from bot.wireguard_peers import (
    create_amneziawg_peer_and_config_for_user,
    create_peer_and_config_for_user,
    execute_server_command,
    regenerate_amneziawg_peer_and_config_for_user,
    regenerate_peer_and_config_for_user,
    find_peer_by_telegram_id,
    is_amneziawg_eu1_configured,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Загружаем конфиг
try:
    config = load_config()
    ADMIN_ID = config.admin_id
except Exception as e:
    logger.error(f"Ошибка загрузки конфига: {e}")
    ADMIN_ID = None

_recovery_lock = threading.Lock()


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
    """
    Парсит вывод `wg show <interface> dump`.
    Возвращает dict: public_key -> (rx_bytes, tx_bytes).
    Формат dump: первая строка — интерфейс, далее по строке на peer (табы):
    public_key, preshared_key, endpoint, allowed_ips, latest_handshake, transfer_rx, transfer_tx, ...
    """
    result: Dict[str, tuple] = {}
    lines = stdout.strip().split("\n")
    for line in lines[1:]:  # пропускаем строку интерфейса
        parts = line.split("\t")
        if len(parts) >= 7:
            try:
                pubkey = parts[0].strip()
                rx = int(parts[5])
                tx = int(parts[6])
                result[pubkey] = (rx, tx)
            except (ValueError, IndexError):
                continue
    return result


def _get_wg_transfer_for_server(server_id: str) -> Dict[str, tuple]:
    """
    Получает трафик (rx, tx в байтах) по каждому pubkey для указанной ноды.
    main — локальный вызов wg show; eu1 — по SSH (wg или awg для AmneziaWG).
    """
    base = pathlib.Path(__file__).parent.parent
    env = _parse_env_file(base / "env_vars.txt")
    if server_id == "main":
        interface = env.get("WG_INTERFACE", "wg0")
        try:
            out = subprocess.run(
                ["wg", "show", interface, "dump"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode != 0:
                return {}
            return _parse_wg_dump_transfer(out.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.warning("Локальный wg show для %s: %s", server_id, e)
            return {}
    else:
        try:
            from bot.wireguard_peers import execute_server_command, _get_server_config, _load_env
            env = _load_env()
            cfg = _get_server_config(server_id, env)
            # eu1 может использовать AmneziaWG (интерфейс awg0) — тогда нужна команда awg
            awg_interface = env.get("AMNEZIAWG_EU1_INTERFACE", "").strip()
            interface = awg_interface or cfg.get("interface", "wg0")
            use_awg = interface.startswith("awg") or bool(awg_interface)
            cmd = f"awg show {interface} dump 2>/dev/null" if use_awg else f"wg show {interface} dump 2>/dev/null"
            fallback_cmd = f"wg show {interface} dump 2>/dev/null" if use_awg else None
            stdout, stderr = execute_server_command(server_id, f"{cmd} || true", timeout=15)
            result = _parse_wg_dump_transfer(stdout or "")
            if not result and fallback_cmd:
                stdout2, _ = execute_server_command(server_id, f"{fallback_cmd} || true", timeout=15)
                result = _parse_wg_dump_transfer(stdout2 or "")
            return result
        except Exception as e:
            logger.warning("SSH wg/awg show для %s: %s", server_id, e)
            return {}


def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Проверяет доступность TCP-порта на хосте."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


@app.route("/")
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
            display_name = user.username or f"Пользователь {i + 1}"
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
    return render_template("recovery.html", stats={})


@app.route("/api/servers")
def api_servers():
    """API: статус серверов."""
    try:
        from bot.wireguard_peers import get_available_servers
        from bot.config import _parse_env_file
        
        servers_info = get_available_servers()
        env = _parse_env_file(pathlib.Path(__file__).parent.parent / "env_vars.txt")
        
        servers_status = {}
        for server_id, info in servers_info.items():
            # Получаем endpoint host из env
            if server_id == "main":
                endpoint_host = env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST")
            else:
                endpoint_host = env.get(f"WG_{server_id.upper()}_ENDPOINT_HOST")
            
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
    """API: статус сервисов (WireGuard, AmneziaWG, Shadowsocks, MTProto) по нодам."""
    try:
        from bot.wireguard_peers import get_available_servers
        from bot.config import _parse_env_file
        
        servers_info = get_available_servers()
        env = _parse_env_file(pathlib.Path(__file__).parent.parent / "env_vars.txt")
        
        services_list: List[Dict] = []
        
        for server_id, info in servers_info.items():
            if server_id == "main":
                host = env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST")
            else:
                host = env.get(f"WG_{server_id.upper()}_ENDPOINT_HOST")
            
            if not host:
                continue
            
            server_name = info.get("name", server_id)
            
            # WireGuard: по пингу хоста (UDP 51820 не проверяем отдельно)
            wg_status = check_server_status(server_id, host)
            services_list.append({
                "server_id": server_id,
                "server_name": server_name,
                "service": "WireGuard",
                "status": wg_status["status"],
                "note": "Низкий пинг, высокая скорость" if server_id == "main" else "Из РФ может не работать (используйте AmneziaWG)",
            })
            
            # Для eu1: AmneziaWG (тот же хост), Shadowsocks (8388), MTProto (443)
            if server_id == "eu1":
                services_list.append({
                    "server_id": server_id,
                    "server_name": server_name,
                    "service": "AmneziaWG",
                    "status": wg_status["status"],
                    "note": "Доступ из РФ, обфускация",
                })
                # Shadowsocks — проверка порта 8388
                ss_ok = check_port(host, 8388)
                services_list.append({
                    "server_id": server_id,
                    "server_name": server_name,
                    "service": "Shadowsocks",
                    "status": "online" if ss_ok else "offline",
                    "note": "Порт 8388",
                })
                # MTProto — проверка порта 443
                mt_ok = check_port(host, 443)
                services_list.append({
                    "server_id": server_id,
                    "server_name": server_name,
                    "service": "MTProto (Telegram)",
                    "status": "online" if mt_ok else "offline",
                    "note": "Порт 443",
                })
        
        return jsonify({"services": services_list})
    except Exception as e:
        logger.exception(f"Ошибка API сервисов: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/users")
def api_users():
    """API: список пользователей (только для админа)."""
    # Простая проверка админа через query параметр (в продакшене использовать сессии)
    admin_key = request.args.get("admin_key")
    if admin_key != str(ADMIN_ID):
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
    """API: трафик по пользователям и пирам (rx/tx с нод WireGuard)."""
    try:
        from bot.wireguard_peers import get_available_servers
        peers = get_all_peers()
        servers = get_available_servers()
        rows: List[Dict] = []
        for server_id in servers:
            transfer = _get_wg_transfer_for_server(server_id)
            for peer in peers:
                if peer.server_id != server_id or not peer.active:
                    continue
                # Сопоставление по public_key (нормализуем пробелы/переносы из JSON)
                pk = (peer.public_key or "").strip()
                rx_tx = transfer.get(pk)
                if rx_tx is None and pk:
                    rx_tx = transfer.get(peer.public_key)  # без strip на случай другого формата
                if rx_tx is None:
                    rx_tx = (0, 0)
                rx_bytes, tx_bytes = rx_tx
                user = find_user(peer.telegram_id)
                username = user.username if user else None
                rows.append({
                    "telegram_id": peer.telegram_id,
                    "username": username,
                    "server_id": server_id,
                    "wg_ip": peer.wg_ip,
                    "rx_bytes": rx_bytes,
                    "tx_bytes": tx_bytes,
                })
        # Суммы по пользователям
        by_user: Dict[int, Dict] = {}
        for r in rows:
            uid = r["telegram_id"]
            if uid not in by_user:
                by_user[uid] = {"username": r["username"], "rx_bytes": 0, "tx_bytes": 0}
            by_user[uid]["rx_bytes"] += r["rx_bytes"]
            by_user[uid]["tx_bytes"] += r["tx_bytes"]
        resp = jsonify({
            "rows": rows,
            "by_user": [{"telegram_id": k, "username": v["username"], "rx_bytes": v["rx_bytes"], "tx_bytes": v["tx_bytes"]} for k, v in by_user.items()],
            "last_update": datetime.now().isoformat(),
        })
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    except Exception as e:
        logger.exception(f"Ошибка API трафика: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    """API: статистика использования."""
    try:
        peers = get_all_peers()
        users = get_all_users()
        
        active_peers = [p for p in peers if p.active]
        active_users = [u for u in users if u.active]
        
        # Группировка по серверам
        by_server: Dict[str, int] = {}
        for peer in active_peers:
            by_server[peer.server_id] = by_server.get(peer.server_id, 0) + 1
        
        # Группировка по типам профилей
        by_profile_type: Dict[str, int] = {}
        for peer in active_peers:
            profile_type = getattr(peer, "profile_type", None) or "vpn"
            by_profile_type[profile_type] = by_profile_type.get(profile_type, 0) + 1
        
        return jsonify({
            "total_users": len(users),
            "active_users": len(active_users),
            "total_peers": len(peers),
            "active_peers": len(active_peers),
            "by_server": by_server,
            "by_profile_type": by_profile_type,
            "last_update": datetime.now().isoformat()
        })
    except Exception as e:
        logger.exception(f"Ошибка API статистики: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/recovery/telegram-proxy", methods=["POST"])
def api_recovery_telegram_proxy():
    """
    Recovery endpoint:
    - Auth by telegram_id existence in bot storage (users.json)
    - Restarts telegram proxy container on the corresponding server (eu1/main)
    """
    try:
        body = request.get_json() or {}
        telegram_id = body.get("telegram_id")
        if telegram_id is None:
            return jsonify({"error": "telegram_id is required"}), 400
        try:
            telegram_id = int(telegram_id)
        except (TypeError, ValueError):
            return jsonify({"error": "telegram_id must be integer"}), 400

        user = find_user(telegram_id)
        if not user or not user.active:
            return jsonify({"error": "Unauthorized: user not found or inactive"}), 403

        # Avoid concurrent restarts
        if not _recovery_lock.acquire(blocking=False):
            return jsonify({"error": "Recovery already running"}), 409

        try:
            cfg = globals().get("config")
            effective_link = (
                get_effective_mtproto_proxy_link(cfg)  # type: ignore[arg-type]
                if cfg is not None
                else None
            )
            proxy_parts = _parse_tg_proxy_link(effective_link)
            proxy_server_ip = proxy_parts.get("server", "")
            if not proxy_server_ip:
                return jsonify({"error": "MTPROTO_PROXY_LINK is not configured (tg://proxy... missing server)"}), 500

            candidates = ["mtproto-proxy", "mtproxy-faketls"]

            preferred = _determine_target_server_id_from_env(proxy_server_ip)
            servers_to_try: List[str] = []
            if preferred:
                servers_to_try.append(preferred)
            # Always try both, because proxy server IP mapping may be incomplete.
            for sid in ["main", "eu1"]:
                if sid not in servers_to_try:
                    servers_to_try.append(sid)

            last_r: Dict[str, str] = {}
            for sid in servers_to_try:
                try:
                    r = _restart_proxy_container_on_server(sid, candidates)
                    last_r = r
                    if r.get("ok") == "true":
                        return jsonify(r), 200
                except Exception as e:
                    last_r = {"ok": "false", "server_id": sid, "error": str(e)}
                    # Continue fallback to other server.

            # Nothing worked
            return jsonify(last_r), 502
        finally:
            _recovery_lock.release()
    except Exception as e:
        logger.exception("Ошибка recovery/telegram-proxy: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/recovery/vpn", methods=["POST"])
def api_recovery_vpn():
    """
    VPN recovery endpoint:
    - Auth by telegram_id existence in bot storage (users.json)
    - Regenerate (or create) VPN config for user's preferred server
    - Returns config text so user can import in client apps without Telegram
    """
    try:
        body = request.get_json() or {}
        telegram_id = body.get("telegram_id")
        android_safe = bool(body.get("android_safe", False))

        if telegram_id is None:
            return jsonify({"error": "telegram_id is required"}), 400
        try:
            telegram_id = int(telegram_id)
        except (TypeError, ValueError):
            return jsonify({"error": "telegram_id must be integer"}), 400

        user = find_user(telegram_id)
        if not user or not user.active:
            return jsonify({"error": "Unauthorized: user not found or inactive"}), 403

        preferred_server_id = user.preferred_server_id or "main"

        # If AmneziaWG on eu1 isn't configured, don't attempt to generate configs.
        if preferred_server_id == "eu1" and not is_amneziawg_eu1_configured():
            return jsonify({"error": "eu1 AmneziaWG is not configured on server. Try later or ask owner."}), 503

        peer = find_peer_by_telegram_id(telegram_id, server_id=preferred_server_id)
        if preferred_server_id == "eu1":
            if peer and peer.active:
                peer, cfg = regenerate_amneziawg_peer_and_config_for_user(
                    telegram_id, android_safe=android_safe
                )
            else:
                peer, cfg = create_amneziawg_peer_and_config_for_user(
                    telegram_id, android_safe=android_safe
                )
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}_amneziawg.conf"
            return jsonify({"ok": True, "filename": filename, "config": cfg})

        # main/other WireGuard nodes
        if peer and peer.active:
            peer, cfg = regenerate_peer_and_config_for_user(
                telegram_id, server_id=preferred_server_id, android_safe=android_safe
            )
        else:
            # profile_type is mostly relevant for eu1 in this codebase; for main keep it None.
            peer, cfg = create_peer_and_config_for_user(
                telegram_id, server_id=preferred_server_id, profile_type=None, android_safe=android_safe
            )

        pt = getattr(peer, "profile_type", None)
        if pt == "vpn_gpt":
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}_gpt.conf"
        elif pt == "unified":
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}_unified.conf"
        else:
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}.conf"

        return jsonify({"ok": True, "filename": filename, "config": cfg})
    except Exception as e:
        logger.exception("Ошибка recovery/vpn: %s", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import os
    debug = os.environ.get("FLASK_ENV") == "development"
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug)
