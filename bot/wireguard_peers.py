import ipaddress
import logging
import pathlib
import subprocess
from typing import Dict, Optional, Tuple

from .config import _parse_env_file
from .storage import Peer, get_all_peers, upsert_peer


logger = logging.getLogger(__name__)


class WireGuardError(RuntimeError):
    """Ошибка при работе с WireGuard или генерации конфига."""


def _load_env() -> dict:
    """
    Читает env_vars.txt из корня проекта VPN и возвращает словарь переменных.
    """
    base_dir = pathlib.Path(__file__).resolve().parent.parent
    env_file = base_dir / "env_vars.txt"
    return _parse_env_file(env_file)


def _get_server_config(server_id: str, env: dict) -> Dict[str, str]:
    """
    Извлекает конфигурацию для указанной ноды из env_vars.txt.
    
    Формат переменных в env_vars.txt:
    - Для server_id="main": WG_SERVER_PUBLIC_KEY, WG_INTERFACE, WG_NETWORK_CIDR, WG_ENDPOINT_HOST, WG_ENDPOINT_PORT, WG_DNS
    - Для server_id="eu1": WG_EU1_SERVER_PUBLIC_KEY, WG_EU1_INTERFACE, WG_EU1_NETWORK_CIDR, WG_EU1_ENDPOINT_HOST, WG_EU1_ENDPOINT_PORT, WG_EU1_DNS
    - Также для удалённых нод: WG_EU1_SSH_HOST, WG_EU1_SSH_USER (опционально: WG_EU1_SSH_KEY_PATH)
    
    Возвращает словарь с ключами: server_public_key, interface, network_cidr, endpoint_host, endpoint_port, dns, ssh_host, ssh_user, ssh_key_path.
    """
    prefix = "" if server_id == "main" else f"{server_id.upper()}_"
    
    config = {
        "server_public_key": env.get(f"{prefix}WG_SERVER_PUBLIC_KEY") or env.get("WG_SERVER_PUBLIC_KEY"),
        "interface": env.get(f"{prefix}WG_INTERFACE") or env.get("WG_INTERFACE", "wg0"),
        "network_cidr": env.get(f"{prefix}WG_NETWORK_CIDR") or env.get("WG_NETWORK_CIDR", "10.0.0.0/24"),
        "endpoint_host": env.get(f"{prefix}WG_ENDPOINT_HOST") or env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST"),
        "endpoint_port": env.get(f"{prefix}WG_ENDPOINT_PORT") or env.get("WG_ENDPOINT_PORT", "51820"),
        "dns": env.get(f"{prefix}WG_DNS") or env.get("WG_DNS", "1.1.1.1"),
        "ssh_host": env.get(f"{prefix}WG_SSH_HOST"),
        "ssh_user": env.get(f"{prefix}WG_SSH_USER"),
        "ssh_key_path": env.get(f"{prefix}WG_SSH_KEY_PATH"),
    }
    
    if not config["server_public_key"]:
        raise WireGuardError(f"WG_{prefix}SERVER_PUBLIC_KEY не задан в env_vars.txt для сервера {server_id}.")
    if not config["endpoint_host"]:
        raise WireGuardError(f"WG_{prefix}ENDPOINT_HOST или VPN_SERVER_HOST не задан в env_vars.txt для сервера {server_id}.")
    
    return config


def _allocate_ip(network_cidr: str, server_id: str) -> str:
    """
    Находит свободный IP в заданной сети с учётом уже занятых IP в peers.json для указанного сервера.

    На текущем этапе:
    - предполагаем, что сервер использует первый адрес (например, 10.0.0.1);
    - client1 (владелец) занимает второй адрес (например, 10.0.0.2) только на сервере "main";
    - для новых пользователей начинаем с последующих адресов.
    - каждая нода имеет свою подсеть, поэтому IP выделяются независимо для каждой ноды.
    """
    net = ipaddress.ip_network(network_cidr, strict=False)

    # Занятые IP из peers.json только для этого server_id
    used_ips = set()
    for peer in get_all_peers():
        if peer.server_id != server_id:
            continue
        try:
            iface = ipaddress.ip_interface(peer.wg_ip)
            used_ips.add(iface.ip)
        except ValueError:
            continue

    # Резервируем network, broadcast, первый адрес (сервер)
    reserved = {
        net.network_address,
        net.broadcast_address,
    }
    try:
        reserved.add(net.network_address + 1)  # сервер, например 10.0.0.1
        # client1 (владелец) резервируем только на main
        if server_id == "main":
            reserved.add(net.network_address + 2)  # первый peer (client1) на main
    except Exception:  # noqa: BLE001
        # На случай экзотической сети просто игнорируем дополнительные резервы.
        pass

    used_ips |= reserved

    for host in net.hosts():
        if host not in used_ips:
            return f"{host}/{net.prefixlen}"

    raise WireGuardError(f"Не удалось подобрать свободный IP для нового peer в сети WireGuard на сервере {server_id}.")


def _generate_keypair() -> Tuple[str, str]:
    """
    Генерирует ключи для нового peer через утилиты wg/wg pubkey.

    Возвращает (private_key, public_key).
    """
    try:
        private_key = subprocess.check_output(["wg", "genkey"], text=True).strip()
        result = subprocess.run(
            ["wg", "pubkey"],
            input=f"{private_key}\n",
            capture_output=True,
            text=True,
            check=True,
        )
        public_key = result.stdout.strip()
        return private_key, public_key
    except subprocess.CalledProcessError as exc:
        logger.exception("Ошибка при генерации ключей WireGuard: %s", exc)
        raise WireGuardError("Не удалось сгенерировать ключи WireGuard.") from exc


def _add_peer_to_wireguard(interface: str, public_key: str, wg_ip: str, ssh_host: Optional[str] = None, ssh_user: Optional[str] = None, ssh_key_path: Optional[str] = None) -> None:
    """
    Добавляет peer в конфигурацию WireGuard через `wg set`.
    
    Если ssh_host указан — выполняет команду на удалённом сервере через SSH.
    Если ssh_host не указан — выполняет локально (для ноды "main").
    
    ВАЖНО: это обновляет только runtime-конфигурацию. Для устойчивости через перезапуск
    позже можно добавить отдельную процедуру синхронизации с /etc/wireguard/wg0.conf.
    """
    cmd = ["wg", "set", interface, "peer", public_key, "allowed-ips", wg_ip]
    
    try:
        if ssh_host:
            # Удалённая нода через SSH
            # Формируем команду для выполнения на удалённом сервере
            remote_cmd = " ".join(cmd)
            ssh_target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
            
            ssh_cmd = ["ssh"]
            if ssh_key_path:
                ssh_cmd.extend(["-i", ssh_key_path])
            # Добавляем опции для неинтерактивного режима
            ssh_cmd.extend(["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"])
            ssh_cmd.append(ssh_target)
            ssh_cmd.append(remote_cmd)
            
            logger.info("Добавляю peer на удалённую ноду %s через SSH: %s", ssh_host, remote_cmd)
            subprocess.run(ssh_cmd, check=True)
        else:
            # Локальная нода
            logger.info("Добавляю peer на локальную ноду: %s", " ".join(cmd))
            subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        logger.exception("Ошибка при добавлении peer в WireGuard: %s", exc)
        raise WireGuardError(f"Не удалось добавить peer в WireGuard на сервере {ssh_host or 'local'}.") from exc


def _build_client_config(
    private_key: str,
    wg_ip: str,
    server_public_key: str,
    endpoint_host: str,
    endpoint_port: str,
    dns: str,
) -> str:
    """
    Формирует текст клиентского WireGuard-конфига для нового пользователя.
    """
    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {wg_ip}\n"
        f"DNS = {dns}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"Endpoint = {endpoint_host}:{endpoint_port}\n"
        "AllowedIPs = 0.0.0.0/0\n"
        "PersistentKeepalive = 25\n"
    )


def create_peer_and_config_for_user(telegram_id: int, server_id: str = "main") -> Tuple[Peer, str]:
    """
    Создаёт нового peer для заданного Telegram ID на указанной ноде и возвращает (Peer, client_config_text).

    - Выбирает свободный IP в сети указанной ноды.
    - Генерирует ключи для peer.
    - Добавляет peer в WireGuard через `wg set` (локально или через SSH для удалённых нод).
    - Сохраняет информацию о peer в peers.json (без приватного ключа).
    - Формирует и возвращает текст клиентского конфига с endpoint выбранной ноды.
    
    Args:
        telegram_id: Telegram ID пользователя.
        server_id: Идентификатор ноды ("main" для РФ, "eu1" для Европы и т.п.).
    """
    env = _load_env()
    server_config = _get_server_config(server_id, env)

    wg_ip = _allocate_ip(server_config["network_cidr"], server_id)
    private_key, public_key = _generate_keypair()

    # Применяем изменения к WireGuard (локально или через SSH)
    _add_peer_to_wireguard(
        interface=server_config["interface"],
        public_key=public_key,
        wg_ip=wg_ip,
        ssh_host=server_config.get("ssh_host"),
        ssh_user=server_config.get("ssh_user"),
        ssh_key_path=server_config.get("ssh_key_path"),
    )

    # Сохраняем peer в локальное хранилище (без приватного ключа)
    peer = Peer(
        telegram_id=telegram_id,
        wg_ip=wg_ip,
        public_key=public_key,
        server_id=server_id,
        active=True,
    )
    upsert_peer(peer)

    # Формируем текст клиентского конфига
    client_config = _build_client_config(
        private_key=private_key,
        wg_ip=wg_ip,
        server_public_key=server_config["server_public_key"],
        endpoint_host=server_config["endpoint_host"],
        endpoint_port=str(server_config["endpoint_port"]),
        dns=server_config["dns"],
    )

    return peer, client_config


def get_available_servers() -> Dict[str, Dict[str, str]]:
    """
    Возвращает словарь доступных серверов с их метаданными (название, описание).
    
    Формат: {"server_id": {"name": "...", "description": "..."}}
    """
    # Список серверов можно расширять через env_vars.txt или конфиг-файл.
    # Пока хардкодим базовые варианты.
    return {
        "main": {
            "name": "Россия (Timeweb)",
            "description": "Низкий пинг, высокая скорость. Подходит для YouTube, Instagram и других сервисов.",
        },
        "eu1": {
            "name": "Европа",
            "description": "Доступ к ChatGPT и другим сервисам, недоступным в РФ. Пинг выше (~50-120 мс).",
        },
    }

