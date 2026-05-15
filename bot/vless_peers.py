"""
VLESS+REALITY peer management для eu1 (Fornex).

Каждый пользователь получает уникальный UUID.
Xray-конфиг на сервере управляется через Python-скрипты
/opt/xray-add-client.py и /opt/xray-remove-client.py.
"""

import logging
import uuid as _uuid_mod
from typing import Optional

from .database import db_get_vless_creds, db_set_vless_creds, db_clear_vless_creds, db_pick_server
from .wireguard_peers import execute_server_command, WireGuardError, _load_env, _get_server_config

logger = logging.getLogger(__name__)

# Скрипты на сервере (относительно сервера eu1; при добавлении eu2 путь может отличаться)
ADD_SCRIPT = "/opt/xray-add-client.py"
REMOVE_SCRIPT = "/opt/xray-remove-client.py"


def get_vless_server_id() -> str:
    """
    Возвращает server_id для VLESS из таблицы servers (наименее загруженный активный).
    Fallback — 'eu1'.
    """
    try:
        return db_pick_server(protocol="vless")
    except Exception as exc:
        logger.warning("get_vless_server_id: ошибка db_pick_server, fallback eu1: %s", exc)
        return "eu1"


def _get_vless_server_params(server_id: Optional[str] = None) -> dict:
    """Возвращает VLESS-параметры из env_vars.txt для указанного (или выбранного) сервера."""
    if server_id is None:
        server_id = get_vless_server_id()
    env = _load_env()
    # Параметры REALITY читаем по server_id; пока env-переменные именуются с префиксом EU1
    # При добавлении eu2 нужно добавить VLESS_EU2_PUBKEY и т.д.
    upper = server_id.upper().replace("-", "_")
    return {
        "pubkey": env.get(f"VLESS_{upper}_PUBKEY", env.get("VLESS_EU1_PUBKEY", "")),
        "short_id": env.get(f"VLESS_{upper}_SHORT_ID", env.get("VLESS_EU1_SHORT_ID", "04d9b6c0")),
        "sni": env.get(f"VLESS_{upper}_SNI", env.get("VLESS_EU1_SNI", "www.microsoft.com")),
        "host": _get_server_config(server_id, env).get("ssh_host", "185.21.8.91"),
        "server_id": server_id,
    }


def build_vless_link(user_uuid: str, host: str, pubkey: str, short_id: str, sni: str) -> str:
    """Строит vless:// ссылку для клиента."""
    return (
        f"vless://{user_uuid}@{host}:443"
        f"?encryption=none&security=reality"
        f"&sni={sni}&fp=chrome"
        f"&pbk={pubkey}&sid={short_id}"
        f"&type=tcp&flow=xtls-rprx-vision"
        f"#EU1-VLESS"
    )


def create_vless_client_for_user(telegram_id: int, server_id: Optional[str] = None) -> str:
    """
    Создаёт VLESS-клиента для пользователя.
    Если уже существует — возвращает существующую ссылку.

    server_id — явный выбор сервера; если None — определяется через db_pick_server().
    Возвращает vless:// ссылку.
    """
    existing = db_get_vless_creds(telegram_id)
    # Определяем сервер один раз — при создании сохраняем, при восстановлении не меняем
    if server_id is None:
        server_id = get_vless_server_id()
    params = _get_vless_server_params(server_id)

    if existing and existing.get("vless_uuid"):
        user_uuid = existing["vless_uuid"]
        short_id = existing.get("vless_short_id") or params["short_id"]
        logger.info("VLESS: пользователь %s уже имеет UUID %s, возвращаем ссылку", telegram_id, user_uuid)
        # Убеждаемся что клиент есть на сервере (idempotent add)
        _run_add_on_server(user_uuid, server_id)
        return build_vless_link(user_uuid, params["host"], params["pubkey"], short_id, params["sni"])

    user_uuid = str(_uuid_mod.uuid4())
    short_id = params["short_id"]

    vless_link = _run_add_on_server(user_uuid, server_id)

    db_set_vless_creds(telegram_id, user_uuid, short_id)
    logger.info("VLESS: создан клиент для пользователя %s, UUID=%s, server=%s", telegram_id, user_uuid, server_id)
    return vless_link


def regenerate_vless_client_for_user(telegram_id: int, server_id: Optional[str] = None) -> str:
    """
    Удаляет старый UUID, создаёт новый. Возвращает новую vless:// ссылку.
    server_id — если None, определяется через db_pick_server().
    """
    if server_id is None:
        server_id = get_vless_server_id()
    existing = db_get_vless_creds(telegram_id)
    if existing and existing.get("vless_uuid"):
        try:
            _run_remove_on_server(existing["vless_uuid"], server_id)
        except WireGuardError as e:
            logger.warning("VLESS regen: не удалось удалить старый UUID %s: %s", existing["vless_uuid"], e)

    db_clear_vless_creds(telegram_id)
    return create_vless_client_for_user(telegram_id, server_id=server_id)


def remove_vless_client_for_user(telegram_id: int, server_id: Optional[str] = None) -> None:
    """Удаляет VLESS-клиента пользователя с сервера и из БД."""
    if server_id is None:
        server_id = get_vless_server_id()
    existing = db_get_vless_creds(telegram_id)
    if not existing or not existing.get("vless_uuid"):
        return
    try:
        _run_remove_on_server(existing["vless_uuid"], server_id)
    except WireGuardError as e:
        logger.warning("VLESS remove: ошибка удаления %s: %s", existing["vless_uuid"], e)
    db_clear_vless_creds(telegram_id)


def _run_add_on_server(user_uuid: str, server_id: Optional[str] = None) -> str:
    """Вызывает xray-add-client.py на указанном сервере. Возвращает vless:// ссылку из stdout."""
    if server_id is None:
        server_id = get_vless_server_id()
    command = f"python3 {ADD_SCRIPT} {user_uuid}"
    stdout, stderr = execute_server_command(server_id, command, timeout=30)
    if stderr:
        logger.debug("VLESS add stderr: %s", stderr.strip())
    link = stdout.strip()
    if not link.startswith("vless://"):
        raise WireGuardError(f"xray-add-client вернул неожиданный вывод: {link!r}")
    return link


def _run_remove_on_server(user_uuid: str, server_id: Optional[str] = None) -> None:
    """Вызывает xray-remove-client.py на указанном сервере."""
    if server_id is None:
        server_id = get_vless_server_id()
    command = f"python3 {REMOVE_SCRIPT} {user_uuid}"
    stdout, stderr = execute_server_command(server_id, command, timeout=30)
    if stderr:
        logger.debug("VLESS remove stderr: %s", stderr.strip())
