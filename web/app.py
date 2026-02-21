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
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

# Добавляем путь к модулям бота
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from bot.config import load_config, _parse_env_file
from bot.storage import Peer, User, get_all_peers, get_all_users, find_user

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
    main — локальный вызов wg show; eu1 — по SSH.
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
            interface = cfg.get("interface", "wg0")
            stdout, stderr = execute_server_command(
                server_id,
                f"wg show {interface} dump 2>/dev/null || true",
                timeout=15,
            )
            return _parse_wg_dump_transfer(stdout or "")
        except Exception as e:
            logger.warning("SSH wg show для %s: %s", server_id, e)
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
                rx_tx = transfer.get(peer.public_key)
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
        return jsonify({
            "rows": rows,
            "by_user": [{"telegram_id": k, "username": v["username"], "rx_bytes": v["rx_bytes"], "tx_bytes": v["tx_bytes"]} for k, v in by_user.items()],
            "last_update": datetime.now().isoformat(),
        })
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


if __name__ == "__main__":
    import os
    debug = os.environ.get("FLASK_ENV") == "development"
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=debug)
