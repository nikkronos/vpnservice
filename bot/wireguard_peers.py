import ipaddress
import logging
import pathlib
import shlex
import subprocess
from typing import Dict, Optional, Tuple

from .config import _parse_env_file
from .storage import Peer, get_all_peers, upsert_peer, find_peer_by_telegram_id


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
    - Для server_id="main":
      WG_SERVER_PUBLIC_KEY, WG_INTERFACE, WG_NETWORK_CIDR, WG_ENDPOINT_HOST, WG_ENDPOINT_PORT, WG_DNS
    - Для server_id="eu1":
      WG_EU1_SERVER_PUBLIC_KEY, WG_EU1_INTERFACE, WG_EU1_NETWORK_CIDR, WG_EU1_ENDPOINT_HOST, WG_EU1_ENDPOINT_PORT, WG_EU1_DNS
      (также опционально: WG_EU1_SSH_HOST, WG_EU1_SSH_USER, WG_EU1_SSH_KEY_PATH)
    
    Возвращает словарь с ключами:
    server_public_key, interface, network_cidr, endpoint_host, endpoint_port, dns, ssh_host, ssh_user, ssh_key_path, mtu (опционально).
    """
    if server_id == "main":
        # Базовая нода использует "плоские" переменные без префикса.
        config = {
            "server_public_key": env.get("WG_SERVER_PUBLIC_KEY"),
            "interface": env.get("WG_INTERFACE", "wg0"),
            "network_cidr": env.get("WG_NETWORK_CIDR", "10.0.0.0/24"),
            "endpoint_host": env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST"),
            "endpoint_port": env.get("WG_ENDPOINT_PORT", "51820"),
            "dns": env.get("WG_DNS", "1.1.1.1, 8.8.8.8"),
            "ssh_host": env.get("WG_SSH_HOST"),
            "ssh_user": env.get("WG_SSH_USER"),
            "ssh_key_path": env.get("WG_SSH_KEY_PATH"),
            "mtu": env.get("WG_MTU") or None,
        }
    else:
        # Для дополнительных нод используем схему WG_<SERVERID>_* (как в env_vars.example.txt).
        upper_id = server_id.upper()
        prefix = f"WG_{upper_id}_"

        def _get(name: str, fallback_main: Optional[str] = None, default: Optional[str] = None) -> Optional[str]:
            if prefix + name in env:
                return env[prefix + name]
            if fallback_main and fallback_main in env:
                return env[fallback_main]
            return default

        config = {
            "server_public_key": _get("SERVER_PUBLIC_KEY", fallback_main="WG_SERVER_PUBLIC_KEY"),
            "interface": _get("INTERFACE", fallback_main="WG_INTERFACE", default="wg0"),
            "network_cidr": _get("NETWORK_CIDR", fallback_main="WG_NETWORK_CIDR", default="10.0.0.0/24"),
            "endpoint_host": _get("ENDPOINT_HOST", fallback_main="WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST"),
            "endpoint_port": _get("ENDPOINT_PORT", fallback_main="WG_ENDPOINT_PORT", default="51820"),
            "dns": _get("DNS", fallback_main="WG_DNS", default="1.1.1.1, 8.8.8.8"),
            "ssh_host": _get("SSH_HOST"),
            "ssh_user": _get("SSH_USER"),
            "ssh_key_path": _get("SSH_KEY_PATH"),
            "mtu": _get("MTU"),
        }
        # Для удалённых нод: если SSH_HOST не задан — используем ENDPOINT_HOST (тот же хост)
        if server_id != "main" and config.get("endpoint_host") and not config.get("ssh_host"):
            config["ssh_host"] = config["endpoint_host"]
            if not config.get("ssh_user"):
                config["ssh_user"] = "root"
            logger.info("Для ноды %s SSH_HOST не задан в env, используем endpoint_host=%s", server_id, config["ssh_host"])
        # Скрипт добавления редиректа для VPN+GPT (только eu1)
        config["add_ss_redirect_script"] = _get("ADD_SS_REDIRECT_SCRIPT", None, "/opt/vpnservice/scripts/add-ss-redirect.sh")
    
    prefix = "WG_" if server_id == "main" else f"WG_{server_id.upper()}_"
    if not config["server_public_key"]:
        raise WireGuardError(f"{prefix}SERVER_PUBLIC_KEY не задан в env_vars.txt для сервера {server_id}.")
    if not config["endpoint_host"]:
        raise WireGuardError(f"{prefix}ENDPOINT_HOST или VPN_SERVER_HOST не задан в env_vars.txt для сервера {server_id}.")
    
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


def _allocate_ip_in_pool(
    network_cidr: str,
    server_id: str,
    last_octet_start: int,
    last_octet_end: int,
    profile_type_filter: str = "vpn_gpt",
    exclude_octet_start: Optional[int] = None,
    exclude_octet_end: Optional[int] = None,
) -> str:
    """
    Выделяет свободный IP из пула last_octet_start..last_octet_end в последнем октете (для 10.1.0.0/24).
    Для VPN+GPT на eu1: пул 8–254 с исключением 20–50 (резерв под Unified).
    Учитываются только peer'ы с server_id и profile_type=profile_type_filter.
    """
    net = ipaddress.ip_network(network_cidr, strict=False)
    if net.prefixlen != 24:
        raise WireGuardError("Пул поддерживается только для подсети /24.")
    used_ips = set()
    for peer in get_all_peers():
        if peer.server_id != server_id or getattr(peer, "profile_type", None) != profile_type_filter:
            continue
        try:
            iface = ipaddress.ip_interface(peer.wg_ip)
            used_ips.add(iface.ip.packed[-1])
        except (ValueError, IndexError):
            continue
    for last in range(last_octet_start, min(last_octet_end + 1, 255)):
        if exclude_octet_start is not None and exclude_octet_end is not None:
            if exclude_octet_start <= last <= exclude_octet_end:
                continue
        if last in used_ips:
            continue
        parts = list(net.network_address.packed)
        parts[-1] = last
        host = ipaddress.IPv4Address(bytes(parts))
        if host in (net.network_address, net.broadcast_address):
            continue
        return f"{host}/32"
    raise WireGuardError(
        f"Нет свободных IP в пуле (10.1.0.{last_octet_start}–10.1.0.{last_octet_end}) на сервере {server_id}."
    )


def _allocate_ip_unified_pool(network_cidr: str, server_id: str) -> str:
    """
    Выделяет свободный IP из пула Unified на eu1: 10.1.0.20–10.1.0.50.
    Учитываются только peer'ы с server_id и profile_type=unified.
    """
    return _allocate_ip_in_pool(
        network_cidr, server_id, 20, 50, profile_type_filter="unified"
    )


def _run_add_ss_redirect(
    ssh_host: str,
    ssh_user: str,
    ssh_key_path: Optional[str],
    script_path: str,
    client_ip: str,
) -> None:
    """
    Выполняет на удалённом сервере (eu1) скрипт add-ss-redirect.sh <client_ip>.
    client_ip — IP без маски, например 10.1.0.8.
    """
    ssh_target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
    remote_cmd = f"sudo {script_path} {client_ip}"
    ssh_cmd = ["ssh"]
    if ssh_key_path:
        ssh_cmd.extend(["-i", ssh_key_path])
    ssh_cmd.extend(["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"])
    ssh_cmd.append(ssh_target)
    ssh_cmd.append(remote_cmd)
    logger.info("Запуск add-ss-redirect на %s: %s", ssh_host, remote_cmd)
    try:
        subprocess.run(ssh_cmd, check=True)
    except subprocess.CalledProcessError as exc:
        logger.exception("Ошибка при вызове add-ss-redirect.sh на %s: %s", ssh_host, exc)
        raise WireGuardError(f"Не удалось добавить редирект Shadowsocks на сервере {ssh_host}. Обратись к владельцу.") from exc


def execute_server_command(
    server_id: str,
    command: str,
    timeout: int = 30,
) -> Tuple[str, str]:
    """
    Выполняет команду на указанном сервере через SSH.
    
    Args:
        server_id: Идентификатор сервера ("main", "eu1" и т.п.)
        command: Команда для выполнения на сервере
        timeout: Таймаут выполнения команды в секундах
    
    Returns:
        (stdout, stderr) — вывод команды
    
    Raises:
        WireGuardError: если команда не выполнена или сервер недоступен
    """
    env = _load_env()
    server_config = _get_server_config(server_id, env)
    
    ssh_host = server_config.get("ssh_host")
    ssh_user = server_config.get("ssh_user")
    ssh_key_path = server_config.get("ssh_key_path")
    
    if not ssh_host:
        raise WireGuardError(f"SSH_HOST не настроен для сервера {server_id}")
    
    ssh_target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
    ssh_cmd = ["ssh"]
    if ssh_key_path:
        ssh_cmd.extend(["-i", ssh_key_path])
    ssh_cmd.extend(["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}"])
    ssh_cmd.append(ssh_target)
    # Используем bash для выполнения команды с правильным PATH
    # Устанавливаем полный PATH для non-interactive shell, чтобы находить системные утилиты
    # Используем двойные кавычки для bash -c и экранируем специальные символы внутри команды
    # Экранируем двойные кавычки и обратные кавычки в команде
    escaped_command = command.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
    ssh_cmd.append(f'bash -c "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH && {escaped_command}"')
    
    logger.info("Выполнение команды на %s (%s): %s", server_id, ssh_host, command)
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,  # Не бросаем исключение при ненулевом коде возврата
        )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        raise WireGuardError(f"Команда на сервере {server_id} превысила таймаут ({timeout} сек)")
    except Exception as exc:
        logger.exception("Ошибка при выполнении команды на %s: %s", server_id, exc)
        raise WireGuardError(f"Не удалось выполнить команду на сервере {server_id}: {exc}") from exc


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
    if not (wg_ip and wg_ip.strip()):
        raise WireGuardError("Недопустимый пустой адрес peer (allowed-ips); проверь peers.json и network_cidr в env.")
    cmd = ["wg", "set", interface, "peer", public_key, "allowed-ips", wg_ip.strip()]
    
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


def _remove_peer_from_wireguard(interface: str, public_key: str, ssh_host: Optional[str] = None, ssh_user: Optional[str] = None, ssh_key_path: Optional[str] = None) -> None:
    """
    Удаляет peer из конфигурации WireGuard через `wg set ... peer ... remove`.
    
    Если ssh_host указан — выполняет команду на удалённом сервере через SSH.
    Если ssh_host не указан — выполняет локально (для ноды "main").
    
    ВАЖНО: это обновляет только runtime-конфигурацию. Для устойчивости через перезапуск
    позже можно добавить отдельную процедуру синхронизации с /etc/wireguard/wg0.conf.
    """
    cmd = ["wg", "set", interface, "peer", public_key, "remove"]
    
    try:
        if ssh_host:
            # Удалённая нода через SSH
            remote_cmd = " ".join(cmd)
            ssh_target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
            
            ssh_cmd = ["ssh"]
            if ssh_key_path:
                ssh_cmd.extend(["-i", ssh_key_path])
            ssh_cmd.extend(["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"])
            ssh_cmd.append(ssh_target)
            ssh_cmd.append(remote_cmd)
            
            logger.info("Удаляю peer с удалённой ноды %s через SSH: %s", ssh_host, remote_cmd)
            subprocess.run(ssh_cmd, check=True)
        else:
            # Локальная нода
            logger.info("Удаляю peer с локальной ноды: %s", " ".join(cmd))
            subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        logger.exception("Ошибка при удалении peer из WireGuard: %s", exc)
        # Не бросаем исключение, если peer уже не существует (это нормально при регенерации)
        # Просто логируем предупреждение
        logger.warning("Возможно, peer уже не существует в WireGuard (это нормально при регенерации)")


def _build_client_config(
    private_key: str,
    wg_ip: str,
    server_public_key: str,
    endpoint_host: str,
    endpoint_port: str,
    dns: str,
    mtu: Optional[str] = None,
    exclude_server_ip: bool = True,
) -> str:
    """
    Формирует текст клиентского WireGuard-конфига для нового пользователя.
    Если задан mtu (например WG_EU1_MTU=1280), в [Interface] добавляется строка MTU.
    Если exclude_server_ip=True, SSH-трафик к серверу не будет идти через VPN (Split Tunneling).
    """
    interface_lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {wg_ip}",
        f"DNS = {dns}",
    ]
    if mtu and mtu.strip():
        interface_lines.append(f"MTU = {mtu.strip()}")
    
    # AllowedIPs: если exclude_server_ip=True, пытаемся исключить IP сервера из VPN (для SSH)
    # WireGuard на Windows не поддерживает синтаксис !IP/32 для исключения IP.
    # Проблема: 0.0.0.0/1, 128.0.0.0/1 не исключает конкретный IP - трафик к серверу всё равно идёт через VPN.
    # Временное решение: отключаем split tunneling, пусть SSH идёт через VPN.
    # Для работы с сервером используем команду /server_exec в боте или другой метод доступа.
    if exclude_server_ip:
        # Временно отключаем split tunneling - используем стандартный 0.0.0.0/0
        # SSH будет идти через VPN, но это позволит проверить стабильность VPN соединения
        # Для работы с сервером используем /server_exec в боте или другой метод доступа
        allowed_ips = "AllowedIPs = 0.0.0.0/0\n"
        # TODO: Реализовать правильное исключение IP через вычисление диапазонов или другой метод
    else:
        allowed_ips = "AllowedIPs = 0.0.0.0/0\n"
    
    return (
        "\n".join(interface_lines)
        + "\n\n"
        "[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"Endpoint = {endpoint_host}:{endpoint_port}\n"
        + allowed_ips
        + "PersistentKeepalive = 25\n"
    )


def create_peer_and_config_for_user(
    telegram_id: int,
    server_id: str = "main",
    profile_type: Optional[str] = None,
) -> Tuple[Peer, str]:
    """
    Создаёт нового peer для заданного Telegram ID на указанной ноде и возвращает (Peer, client_config_text).

    - Выбирает свободный IP: обычный пул; для eu1 VPN+GPT — 8–254 (исключая 20–50); для eu1 Unified — 20–50.
    - Генерирует ключи для peer.
    - Добавляет peer в WireGuard через `wg set` (локально или через SSH для удалённых нод).
    - Для eu1 и profile_type="vpn_gpt" после добавления peer вызывает на сервере add-ss-redirect.sh.
    - Для eu1 и profile_type="unified" редирект на сервере делается через ipset (скрипты setup-unified-iptables, update-unified-ss-ips).
    - Сохраняет информацию о peer в peers.json (без приватного ключа).
    - Формирует и возвращает текст клиентского конфига с endpoint выбранной ноды.

    Args:
        telegram_id: Telegram ID пользователя.
        server_id: Идентификатор ноды ("main" для РФ, "eu1" для Европы и т.п.).
        profile_type: Для eu1 — "vpn_gpt" (пул 8–19/51–254 + add-ss-redirect.sh), "unified" (пул 20–50, ipset на сервере) или None/"vpn".
    """
    env = _load_env()
    server_config = _get_server_config(server_id, env)

    use_gpt_pool = server_id == "eu1" and profile_type == "vpn_gpt"
    use_unified_pool = server_id == "eu1" and profile_type == "unified"
    if use_unified_pool:
        wg_ip = _allocate_ip_unified_pool(server_config["network_cidr"], server_id)
    elif use_gpt_pool:
        # Пул 8–254 с исключением 20–50 (резерв под Unified)
        wg_ip = _allocate_ip_in_pool(
            server_config["network_cidr"], server_id, 8, 254,
            exclude_octet_start=20, exclude_octet_end=50,
        )
    else:
        wg_ip = _allocate_ip(server_config["network_cidr"], server_id)

    logger.info(
        "Создаю peer для telegram_id=%s на ноде server_id=%s, profile_type=%s, wg_ip=%s",
        telegram_id, server_id, profile_type, wg_ip,
    )

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

    # Для VPN+GPT на eu1 добавляем редирект TCP 80/443 на ss-redir.
    # Для Unified редирект на сервере делается через ipset (скрипты setup-unified-iptables, update-unified-ss-ips).
    if use_gpt_pool:
        script_path = server_config.get("add_ss_redirect_script") or "/opt/vpnservice/scripts/add-ss-redirect.sh"
        client_ip = wg_ip.split("/")[0].strip()
        _run_add_ss_redirect(
            ssh_host=server_config["ssh_host"],
            ssh_user=server_config.get("ssh_user") or "root",
            ssh_key_path=server_config.get("ssh_key_path"),
            script_path=script_path,
            client_ip=client_ip,
        )

    # Сохраняем peer в локальное хранилище (без приватного ключа)
    if use_unified_pool:
        pt = "unified"
    elif use_gpt_pool:
        pt = "vpn_gpt"
    else:
        pt = None
    peer = Peer(
        telegram_id=telegram_id,
        wg_ip=wg_ip,
        public_key=public_key,
        server_id=server_id,
        active=True,
        profile_type=pt,
    )
    upsert_peer(peer)

    # Формируем текст клиентского конфига (с Split Tunneling для SSH)
    client_config = _build_client_config(
        private_key=private_key,
        wg_ip=wg_ip,
        server_public_key=server_config["server_public_key"],
        endpoint_host=server_config["endpoint_host"],
        endpoint_port=str(server_config["endpoint_port"]),
        dns=server_config["dns"],
        mtu=server_config.get("mtu"),
        exclude_server_ip=True,  # SSH не будет идти через VPN
    )

    return peer, client_config


def regenerate_peer_and_config_for_user(telegram_id: int, server_id: Optional[str] = None) -> Tuple[Peer, str]:
    """
    Регенерирует ключи и конфиг для существующего peer.
    
    Процесс:
    1. Находит существующий peer по telegram_id (и server_id, если указан).
    2. Удаляет старый peer из WireGuard.
    3. Генерирует новые ключи.
    4. Добавляет новый peer в WireGuard с теми же IP и server_id.
    5. Обновляет запись в peers.json.
    6. Возвращает новый конфиг.
    
    Args:
        telegram_id: Telegram ID пользователя.
        server_id: Идентификатор ноды. Если не указан, используется server_id существующего peer.
    
    Returns:
        (Peer, client_config_text) — новый peer и клиентский конфиг.
    
    Raises:
        WireGuardError: если peer не найден или произошла ошибка при работе с WireGuard.
    """
    # Находим существующий peer
    existing_peer = find_peer_by_telegram_id(telegram_id, server_id=server_id)
    if not existing_peer or not existing_peer.active:
        raise WireGuardError(f"Не найден активный peer для пользователя {telegram_id} на сервере {server_id or 'любом'}.")
    
    # Используем server_id существующего peer, если не был указан явно
    target_server_id = server_id or existing_peer.server_id
    if target_server_id != existing_peer.server_id:
        raise WireGuardError(
            f"Существующий peer находится на сервере {existing_peer.server_id}, "
            f"а запрошена регенерация на {target_server_id}. Используй /get_config для создания peer на другом сервере."
        )
    
    env = _load_env()
    server_config = _get_server_config(target_server_id, env)
    
    # Удаляем старый peer из WireGuard
    try:
        _remove_peer_from_wireguard(
            interface=server_config["interface"],
            public_key=existing_peer.public_key,
            ssh_host=server_config.get("ssh_host"),
            ssh_user=server_config.get("ssh_user"),
            ssh_key_path=server_config.get("ssh_key_path"),
        )
    except WireGuardError:
        # Если удаление не удалось (peer уже не существует), продолжаем — это не критично
        logger.warning("Не удалось удалить старый peer из WireGuard, продолжаем регенерацию")
    
    # Генерируем новые ключи
    private_key, public_key = _generate_keypair()
    
    # Используем тот же IP, что был у старого peer
    wg_ip = existing_peer.wg_ip
    
    # Добавляем новый peer в WireGuard с новыми ключами
    _add_peer_to_wireguard(
        interface=server_config["interface"],
        public_key=public_key,
        wg_ip=wg_ip,
        ssh_host=server_config.get("ssh_host"),
        ssh_user=server_config.get("ssh_user"),
        ssh_key_path=server_config.get("ssh_key_path"),
    )
    
    # Обновляем peer в локальном хранилище (сохраняем profile_type при регенерации)
    new_peer = Peer(
        telegram_id=telegram_id,
        wg_ip=wg_ip,
        public_key=public_key,
        server_id=target_server_id,
        active=True,
        profile_type=getattr(existing_peer, "profile_type", None),
    )
    upsert_peer(new_peer)
    
    # Формируем новый клиентский конфиг (с Split Tunneling для SSH)
    client_config = _build_client_config(
        private_key=private_key,
        wg_ip=wg_ip,
        server_public_key=server_config["server_public_key"],
        endpoint_host=server_config["endpoint_host"],
        endpoint_port=str(server_config["endpoint_port"]),
        dns=server_config["dns"],
        mtu=server_config.get("mtu"),
        exclude_server_ip=True,  # SSH не будет идти через VPN
    )
    
    logger.info(
        "Регенерирован peer для пользователя %s на сервере %s (новый public_key: %s...)",
        telegram_id,
        target_server_id,
        public_key[:20],
    )
    
    return new_peer, client_config


def get_available_servers() -> Dict[str, Dict[str, str]]:
    """
    Возвращает словарь доступных серверов с их метаданными (название, описание).
    
    Формат: {"server_id": {"name": "...", "description": "..."}}
    """
    # Базовый сервер "main" всегда доступен.
    servers: Dict[str, Dict[str, str]] = {
        "main": {
            "name": "Россия (Timeweb)",
            "description": "Низкий пинг, высокая скорость. Подходит для YouTube, Instagram и других сервисов.",
        },
    }

    # Попытаться включить дополнительные ноды на основе env_vars.txt.
    try:
        env = _load_env()
    except Exception:
        env = {}

    # Нода "eu1" (Европа) считается доступной, только если явно задан её публичный ключ и endpoint.
    has_eu1 = bool(
        env.get("WG_EU1_SERVER_PUBLIC_KEY")
        and (env.get("WG_EU1_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST"))
    )
    if has_eu1:
        servers["eu1"] = {
            "name": "Европа",
            "description": "Доступ к ChatGPT и другим сервисам, недоступным в РФ. Пинг выше (~50–120 мс).",
        }

    return servers

