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

from bot.config import load_config
from bot.storage import Peer, User, get_all_peers, get_all_users

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
