import json
import pathlib
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
PEERS_FILE = DATA_DIR / "peers.json"


def normalize_peer_server_id(server_id: Optional[str]) -> str:
    """main в peers → rus1 для единообразия."""
    if not server_id or server_id == "main":
        return "rus1"
    return server_id


def normalize_preferred_server_id(server_id: Optional[str]) -> str:
    """Дефолт и legacy main → rus1."""
    if not server_id or server_id == "main":
        return "rus1"
    return server_id


def _peer_storage_key(telegram_id: int, server_id: str) -> str:
    return f"{telegram_id}:{normalize_peer_server_id(server_id)}"


def _migrate_peers_json_on_load(data: Dict[str, dict]) -> Dict[str, dict]:
    """
    Старый формат: ключ = только telegram_id (число).
    Новый: ключ = "telegram_id:server_id".
    main → rus1.
    """
    if not data:
        return data
    out: Dict[str, dict] = {}
    for key, payload in data.items():
        sk = str(key)
        payload = dict(payload)
        if ":" in sk:
            tid_str, _, _rest = sk.partition(":")
            sid = normalize_peer_server_id(payload.get("server_id", _rest or "rus1"))
            payload["server_id"] = sid
            nk = f"{tid_str}:{sid}"
            out[nk] = payload
        elif sk.isdigit():
            sid = normalize_peer_server_id(payload.get("server_id", "main"))
            payload["server_id"] = sid
            out[f"{sk}:{sid}"] = payload
        else:
            out[sk] = payload
    return out


@dataclass
class User:
    telegram_id: int
    username: Optional[str]
    role: str = "user"  # "owner" | "user"
    active: bool = True
    preferred_server_id: Optional[str] = None  # rus1 | rus2 | eu1 | eu2 | legacy main
    preferred_profile_type: Optional[str] = None  # для eu1: "vpn" | "vpn_gpt" | "unified"


@dataclass
class Peer:
    """
    Один VPN-подключение. Несколько peers на одного пользователя — разные ключи
    f"{telegram_id}:{server_id}" в peers.json.
    """

    telegram_id: int
    wg_ip: str
    public_key: str
    server_id: str = "rus1"
    active: bool = True
    profile_type: Optional[str] = None


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


def _load_peers_data() -> Dict[str, dict]:
    raw = _load_raw(PEERS_FILE)
    migrated = _migrate_peers_json_on_load(raw)
    if migrated != raw:
        _save_raw(PEERS_FILE, migrated)
    return migrated


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
                    preferred_server_id=payload.get("preferred_server_id"),
                    preferred_profile_type=payload.get("preferred_profile_type"),
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
        preferred_server_id=payload.get("preferred_server_id"),
        preferred_profile_type=payload.get("preferred_profile_type"),
    )


def upsert_user(user: User) -> None:
    data = _load_raw(USERS_FILE)
    payload = asdict(user)
    data[str(user.telegram_id)] = payload
    _save_raw(USERS_FILE, data)


def is_owner(user_id: int, owner_id: int) -> bool:
    return user_id == owner_id


def get_all_peers() -> List[Peer]:
    data = _load_peers_data()
    peers: List[Peer] = []
    for key, payload in data.items():
        try:
            peers.append(
                Peer(
                    telegram_id=int(payload.get("telegram_id", str(key).split(":")[0])),
                    wg_ip=payload["wg_ip"],
                    public_key=payload["public_key"],
                    server_id=normalize_peer_server_id(payload.get("server_id", "rus1")),
                    active=bool(payload.get("active", True)),
                    profile_type=payload.get("profile_type"),
                )
            )
        except (ValueError, KeyError):
            continue
    return peers


def find_peer_by_telegram_id(telegram_id: int, server_id: Optional[str] = None) -> Optional[Peer]:
    """
    Ищет peer. Если server_id задан — точное совпадение слота (rus1, eu2, ...).
    main в запросе нормализуется в rus1.
    Если server_id не указан — приоритет: rus1, eu1, первый найденный.
    """
    data = _load_peers_data()
    if server_id is not None:
        sid = normalize_peer_server_id(server_id)
        key = _peer_storage_key(telegram_id, sid)
        payload = data.get(key)
        if not payload:
            return None
        try:
            return Peer(
                telegram_id=int(payload.get("telegram_id", telegram_id)),
                wg_ip=payload["wg_ip"],
                public_key=payload["public_key"],
                server_id=normalize_peer_server_id(payload.get("server_id", sid)),
                active=bool(payload.get("active", True)),
                profile_type=payload.get("profile_type"),
            )
        except (ValueError, KeyError):
            return None

    prefix = f"{telegram_id}:"
    candidates: List[Peer] = []
    for key, payload in data.items():
        sk = str(key)
        if not sk.startswith(prefix):
            continue
        try:
            candidates.append(
                Peer(
                    telegram_id=int(payload.get("telegram_id", telegram_id)),
                    wg_ip=payload["wg_ip"],
                    public_key=payload["public_key"],
                    server_id=normalize_peer_server_id(payload.get("server_id", sk.split(":")[-1])),
                    active=bool(payload.get("active", True)),
                    profile_type=payload.get("profile_type"),
                )
            )
        except (ValueError, KeyError):
            continue

    if not candidates:
        return None

    order = ["rus1", "rus2", "eu1", "eu2"]
    for sid in order:
        for p in candidates:
            if p.server_id == sid and p.active:
                return p
    for p in candidates:
        if p.active:
            return p
    return candidates[0]


def upsert_peer(peer: Peer) -> None:
    data = _load_peers_data()
    sid = normalize_peer_server_id(peer.server_id)
    peer_norm = Peer(
        telegram_id=peer.telegram_id,
        wg_ip=peer.wg_ip,
        public_key=peer.public_key,
        server_id=sid,
        active=peer.active,
        profile_type=peer.profile_type,
    )
    key = _peer_storage_key(peer_norm.telegram_id, sid)
    data[key] = asdict(peer_norm)
    _save_raw(PEERS_FILE, data)


def delete_peer(telegram_id: int, server_id: str) -> None:
    """Удаляет запись peer из JSON (редко нужно)."""
    data = _load_peers_data()
    key = _peer_storage_key(telegram_id, normalize_peer_server_id(server_id))
    if key in data:
        del data[key]
        _save_raw(PEERS_FILE, data)
