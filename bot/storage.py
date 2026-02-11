import json
import pathlib
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
PEERS_FILE = DATA_DIR / "peers.json"


@dataclass
class User:
    telegram_id: int
    username: Optional[str]
    role: str = "user"  # "owner" | "user"
    active: bool = True


@dataclass
class Peer:
    """
    Описание одного VPN-подключения (peer) в WireGuard, привязанного к Telegram-пользователю.

    На текущем этапе предполагается один активный peer на один Telegram-аккаунт.
    """

    telegram_id: int
    wg_ip: str  # например, "10.0.0.2/32"
    public_key: str
    server_id: str = "main"  # идентификатор ноды/сервера, пока одна нода
    active: bool = True


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_raw(path: pathlib.Path) -> Dict[str, dict]:
    _ensure_data_dir()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_raw(path: pathlib.Path, data: Dict[str, dict]) -> None:
    _ensure_data_dir()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_all_users() -> List[User]:
    data = _load_raw(USERS_FILE)
    users: List[User] = []
    for key, payload in data.items():
        try:
            users.append(
                User(
                    telegram_id=int(payload.get("telegram_id", key)),
                    username=payload.get("username"),
                    role=payload.get("role", "user"),
                    active=bool(payload.get("active", True)),
                )
            )
        except ValueError:
            continue
    return users


def find_user(telegram_id: int) -> Optional[User]:
    data = _load_raw(USERS_FILE)
    payload = data.get(str(telegram_id))
    if not payload:
        return None
    return User(
        telegram_id=int(payload.get("telegram_id", telegram_id)),
        username=payload.get("username"),
        role=payload.get("role", "user"),
        active=bool(payload.get("active", True)),
    )


def upsert_user(user: User) -> None:
    data = _load_raw(USERS_FILE)
    payload = asdict(user)
    # ключ — telegram_id как строка
    data[str(user.telegram_id)] = payload
    _save_raw(USERS_FILE, data)


def is_owner(user_id: int, owner_id: int) -> bool:
    return user_id == owner_id


def get_all_peers() -> List[Peer]:
    """
    Возвращает список всех peers (VPN-подключений), известных системе.
    """
    data = _load_raw(PEERS_FILE)
    peers: List[Peer] = []
    for key, payload in data.items():
        try:
            peers.append(
                Peer(
                    telegram_id=int(payload.get("telegram_id", key)),
                    wg_ip=payload["wg_ip"],
                    public_key=payload["public_key"],
                    server_id=payload.get("server_id", "main"),
                    active=bool(payload.get("active", True)),
                )
            )
        except (ValueError, KeyError):
            # Если данные повреждены или неполные — пропускаем запись,
            # чтобы не ломать работу бота.
            continue
    return peers


def find_peer_by_telegram_id(telegram_id: int) -> Optional[Peer]:
    """
    Ищет peer, связанный с указанным Telegram ID.
    На текущем этапе предполагается максимум один активный peer на пользователя.
    """
    data = _load_raw(PEERS_FILE)
    payload = data.get(str(telegram_id))
    if not payload:
        return None
    try:
        return Peer(
            telegram_id=int(payload.get("telegram_id", telegram_id)),
            wg_ip=payload["wg_ip"],
            public_key=payload["public_key"],
            server_id=payload.get("server_id", "main"),
            active=bool(payload.get("active", True)),
        )
    except (ValueError, KeyError):
        return None


def upsert_peer(peer: Peer) -> None:
    """
    Создаёт или обновляет peer, привязанный к Telegram-пользователю.

    Ключом служит telegram_id (строка).
    """
    data = _load_raw(PEERS_FILE)
    payload = asdict(peer)
    data[str(peer.telegram_id)] = payload
    _save_raw(PEERS_FILE, data)

