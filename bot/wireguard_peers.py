import ipaddress
import logging
import pathlib
import subprocess
from typing import Tuple

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


def _allocate_ip(network_cidr: str) -> str:
    """
    Находит свободный IP в заданной сети с учётом уже занятых IP в peers.json.

    На текущем этапе:
    - предполагаем, что сервер использует первый адрес (например, 10.0.0.1);
    - client1 (владелец) занимает второй адрес (например, 10.0.0.2);
    - для новых пользователей начинаем с последующих адресов.
    """
    net = ipaddress.ip_network(network_cidr, strict=False)

    # Занятые IP из peers.json
    used_ips = set()
    for peer in get_all_peers():
        try:
            iface = ipaddress.ip_interface(peer.wg_ip)
            used_ips.add(iface.ip)
        except ValueError:
            continue

    # Резервируем network, broadcast, первый и второй адреса (сервер и client1)
    reserved = {
        net.network_address,
        net.broadcast_address,
    }
    try:
        reserved.add(net.network_address + 1)  # сервер, например 10.0.0.1
        reserved.add(net.network_address + 2)  # первый peer (client1)
    except Exception:  # noqa: BLE001
        # На случай экзотической сети просто игнорируем дополнительные резервы.
        pass

    used_ips |= reserved

    for host in net.hosts():
        if host not in used_ips:
            return f"{host}/{net.prefixlen}"

    raise WireGuardError("Не удалось подобрать свободный IP для нового peer в сети WireGuard.")


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


def _add_peer_to_wireguard(interface: str, public_key: str, wg_ip: str) -> None:
    """
    Добавляет peer в текущую конфигурацию WireGuard через `wg set`.

    ВАЖНО: это обновляет только runtime-конфигурацию. Для устойчивости через перезапуск
    позже можно добавить отдельную процедуру синхронизации с /etc/wireguard/wg0.conf.
    """
    try:
        subprocess.run(
            ["wg", "set", interface, "peer", public_key, "allowed-ips", wg_ip],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.exception("Ошибка при добавлении peer в WireGuard: %s", exc)
        raise WireGuardError("Не удалось добавить peer в WireGuard.") from exc


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


def create_peer_and_config_for_user(telegram_id: int) -> Tuple[Peer, str]:
    """
    Создаёт нового peer для заданного Telegram ID и возвращает (Peer, client_config_text).

    - Выбирает свободный IP в сети WG_NETWORK_CIDR.
    - Генерирует ключи для peer.
    - Добавляет peer в WireGuard через `wg set`.
    - Сохраняет информацию о peer в peers.json (без приватного ключа).
    - Формирует и возвращает текст клиентского конфига.
    """
    env = _load_env()

    server_public_key = env.get("WG_SERVER_PUBLIC_KEY")
    network_cidr = env.get("WG_NETWORK_CIDR", "10.0.0.0/24")
    interface = env.get("WG_INTERFACE", "wg0")

    endpoint_host = env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST")
    endpoint_port = env.get("WG_ENDPOINT_PORT", "51820")
    dns = env.get("WG_DNS", "1.1.1.1")

    if not server_public_key:
        raise WireGuardError("WG_SERVER_PUBLIC_KEY не задан в env_vars.txt.")
    if not endpoint_host:
        raise WireGuardError("WG_ENDPOINT_HOST или VPN_SERVER_HOST не задан в env_vars.txt.")

    wg_ip = _allocate_ip(network_cidr)
    private_key, public_key = _generate_keypair()

    # Применяем изменения к WireGuard
    _add_peer_to_wireguard(interface=interface, public_key=public_key, wg_ip=wg_ip)

    # Сохраняем peer в локальное хранилище (без приватного ключа)
    peer = Peer(
        telegram_id=telegram_id,
        wg_ip=wg_ip,
        public_key=public_key,
        server_id="main",
        active=True,
    )
    upsert_peer(peer)

    # Формируем текст клиентского конфига
    client_config = _build_client_config(
        private_key=private_key,
        wg_ip=wg_ip,
        server_public_key=server_public_key,
        endpoint_host=endpoint_host,
        endpoint_port=str(endpoint_port),
        dns=dns,
    )

    return peer, client_config

