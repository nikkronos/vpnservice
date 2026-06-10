import json
import pathlib
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
PEERS_FILE = DATA_DIR / "peers.json"

VALID_PLATFORMS = frozenset({"pc", "ios", "android"})

# Консолидация peers.json → SQLite ЗАВЕРШЕНА (Phase 3, 2026-06-03).
# Источник правды — таблица `peers` в SQLite. Запись в peers.json отключена.
# Существующий peers.json остаётся как статический fallback-снимок (читается
# только если таблица вдруг окажется пустой — см. _load_peers_data). Бэкап
# peer-данных покрывается бэкапом vpn.db. Флаг оставлен на случай отладки.
DUAL_WRITE_JSON = False


def _normalize_platform(platform: Optional[str]) -> str:
    """Нормализует платформу к допустимому значению. По умолчанию 'pc'."""
    if not platform or platform not in VALID_PLATFORMS:
        return "pc"
    return platform


def normalize_peer_server_id(server_id: Optional[str]) -> str:
    """main в peers → rus1 для единообразия."""
    if not server_id or server_id == "main":
        return "rus1"
    return server_id


def normalize_preferred_server_id(server_id: Optional[str]) -> str:
    """Дефолт → eu1 (российские серверы отключены). legacy main/rus1/rus2/eu2 → eu1."""
    if not server_id or server_id in ("main", "rus1", "rus2", "eu2"):
        return "eu1"
    return server_id


def _peer_storage_key(telegram_id: int, server_id: str, platform: str = "pc") -> str:
    """Ключ для peers.json: {telegram_id}:{server_id}:{platform}."""
    return f"{telegram_id}:{normalize_peer_server_id(server_id)}:{_normalize_platform(platform)}"


def _migrate_peers_json_on_load(data: Dict[str, dict]) -> Dict[str, dict]:
    """
    Форматы ключей:
    - Старый: только telegram_id (число).
    - Средний: "telegram_id:server_id" (без platform).
    - Новый: "telegram_id:server_id:platform".

    При миграции:
    - 1 часть (цифры) → добавляем :server_id:pc
    - 2 части → добавляем :pc
    - 3 части → нормализуем server_id и platform
    main → rus1; eu2 → eu1 (нормализация server_id).
    """
    if not data:
        return data
    out: Dict[str, dict] = {}
    for key, payload in data.items():
        sk = str(key)
        payload = dict(payload)
        parts = sk.split(":")

        if len(parts) == 3:
            # Новый формат: tid:sid:platform
            tid_str, old_sid, old_plat = parts
            sid = normalize_peer_server_id(payload.get("server_id", old_sid or "rus1"))
            plat = _normalize_platform(old_plat)
            payload["server_id"] = sid
            payload["platform"] = plat
            nk = f"{tid_str}:{sid}:{plat}"
            out[nk] = payload
        elif len(parts) == 2:
            # Средний формат: tid:sid — добавляем платформу из payload или pc
            tid_str, old_sid = parts
            sid = normalize_peer_server_id(payload.get("server_id", old_sid or "rus1"))
            plat = _normalize_platform(payload.get("platform"))
            payload["server_id"] = sid
            payload["platform"] = plat
            nk = f"{tid_str}:{sid}:{plat}"
            out[nk] = payload
        elif sk.isdigit():
            # Старый формат: только tid
            sid = normalize_peer_server_id(payload.get("server_id", "main"))
            plat = _normalize_platform(payload.get("platform"))
            payload["server_id"] = sid
            payload["platform"] = plat
            out[f"{sk}:{sid}:{plat}"] = payload
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
    email: Optional[str] = None
    email_verified: bool = False


@dataclass
class Peer:
    """
    Один VPN-слот для одного устройства пользователя.
    Ключ (Фаза 2 B): (telegram_id, server_id, device_id). `os` — формат доставки
    ('pc'|'ios'|'android'). `platform` оставлен как legacy-алиас `os`, чтобы
    старые вызовы `Peer(platform=...)` и чтение `peer.platform` в боте/ЛК
    продолжали работать без правок (backward-compat shim до B3-UX).
    """

    telegram_id: int
    wg_ip: str
    public_key: str
    server_id: str = "rus1"
    active: bool = True
    profile_type: Optional[str] = None
    device_id: Optional[str] = None
    os: Optional[str] = None
    platform: Optional[str] = None  # legacy-алиас os

    def __post_init__(self) -> None:
        # os приоритетнее; если не задан — берём из platform (legacy). Держим
        # platform синхронным с os для старых читателей (peer.platform).
        self.os = _normalize_platform(self.os or self.platform)
        self.platform = self.os


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
    """
    {storage_key: payload} из таблицы peers (источник правды — SQLite).
    storage_key = "{tid}:{server_id}:{device_id}" (Фаза 2 B). payload содержит
    device_id + os. peers.json-fallback убран (на проде JSON мёртв, Phase 3).
    """
    from .database import db_get_all_peers

    out: Dict[str, dict] = {}
    for r in db_get_all_peers():
        sid = normalize_peer_server_id(r.get("server_id"))
        did = r.get("device_id") or ""
        out[f'{r["telegram_id"]}:{sid}:{did}'] = {
            "telegram_id": int(r["telegram_id"]),
            "wg_ip": r["wg_ip"],
            "public_key": r["public_key"],
            "server_id": sid,
            "active": bool(r["active"]),
            "profile_type": r.get("profile_type"),
            "device_id": did,
            "os": _normalize_platform(r.get("os")),
        }
    return out


def _upsert_peer_json(peer_norm: "Peer") -> None:
    """Зеркалит один слот в peers.json (read-modify-write сырого файла)."""
    data = _migrate_peers_json_on_load(_load_raw(PEERS_FILE))
    key = _peer_storage_key(peer_norm.telegram_id, peer_norm.server_id, peer_norm.platform)
    data[key] = asdict(peer_norm)
    _save_raw(PEERS_FILE, data)


def _delete_peer_json(telegram_id: int, server_id: str, platform: str) -> None:
    """Удаляет один слот из peers.json-зеркала."""
    data = _migrate_peers_json_on_load(_load_raw(PEERS_FILE))
    key = _peer_storage_key(
        telegram_id, normalize_peer_server_id(server_id), _normalize_platform(platform)
    )
    if key in data:
        del data[key]
        _save_raw(PEERS_FILE, data)


def _user_from_db_row(row: dict) -> User:
    """Конвертирует строку из SQLite → User."""
    return User(
        telegram_id=int(row["telegram_id"]) if row.get("telegram_id") else -int(row.get("id", 0)),
        username=row.get("username"),
        role=row.get("role", "user"),
        active=bool(row.get("active", True)),
        preferred_server_id=row.get("preferred_server_id"),
        preferred_profile_type=row.get("preferred_profile_type"),
        email=row.get("email"),
        email_verified=bool(row.get("email_verified", False)),
    )


def get_all_users() -> List[User]:
    from .database import db_get_all_users
    rows = db_get_all_users()
    users: List[User] = []
    for row in rows:
        try:
            users.append(_user_from_db_row(row))
        except (ValueError, KeyError):
            continue
    return users


def find_user(telegram_id: int) -> Optional[User]:
    from .database import db_find_user_by_telegram_id
    row = db_find_user_by_telegram_id(telegram_id)
    if not row:
        return None
    return _user_from_db_row(row)


def upsert_user(user: User) -> None:
    from .database import db_upsert_user
    data: dict = {
        "telegram_id": user.telegram_id if user.telegram_id > 0 else None,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "active": user.active,
        "preferred_server_id": user.preferred_server_id,
        "preferred_profile_type": user.preferred_profile_type,
        "email_verified": user.email_verified,
    }
    db_upsert_user(data)
    # users.json-зеркало удалено в Phase 3 (2026-06-03): SQLite — единственный
    # источник правды для users; users.json больше не пишется.


def is_owner(user_id: int, owner_id: int) -> bool:
    return user_id == owner_id


def _device_label(os_: str) -> str:
    return {"pc": "ПК", "ios": "Устройство iOS", "android": "Android-устройство"}.get(os_, os_)


def _peer_from_payload(payload: dict) -> Peer:
    return Peer(
        telegram_id=int(payload["telegram_id"]),
        wg_ip=payload["wg_ip"],
        public_key=payload["public_key"],
        server_id=normalize_peer_server_id(payload.get("server_id", "rus1")),
        active=bool(payload.get("active", True)),
        profile_type=payload.get("profile_type"),
        device_id=payload.get("device_id"),
        os=_normalize_platform(payload.get("os") or payload.get("platform")),
    )


def _pick_active(cands: List[Peer]) -> Optional[Peer]:
    for p in cands:
        if p.active:
            return p
    return cands[0] if cands else None


def get_all_peers() -> List[Peer]:
    peers: List[Peer] = []
    for payload in _load_peers_data().values():
        try:
            peers.append(_peer_from_payload(payload))
        except (ValueError, KeyError):
            continue
    return peers


def find_peer_by_telegram_id(
    telegram_id: int,
    server_id: Optional[str] = None,
    platform: Optional[str] = None,
    device_id: Optional[str] = None,
) -> Optional[Peer]:
    """
    Ищет peer-слот пользователя (Фаза 2 B).

    - device_id → точный слот по device_id (server опционален).
    - platform (legacy-shim) → слот с os==platform (на server, если задан).
    - server_id без platform/device → приоритет pc→ios→android, затем активный.
    - без всего → eu1-приоритет, первый активный.
    main в server_id → rus1.
    """
    sid = normalize_peer_server_id(server_id) if server_id is not None else None
    mine = [p for p in get_all_peers() if p.telegram_id == int(telegram_id)]
    if sid is not None:
        mine = [p for p in mine if p.server_id == sid]

    if device_id is not None:
        return _pick_active([p for p in mine if p.device_id == device_id])

    if platform is not None:
        plat = _normalize_platform(platform)
        return _pick_active([p for p in mine if p.os == plat])

    if sid is not None:
        for plat in ("pc", "ios", "android"):
            picked = _pick_active([p for p in mine if p.os == plat])
            if picked:
                return picked
        return _pick_active(mine)

    eu1 = _pick_active([p for p in mine if p.server_id == "eu1"])
    return eu1 if eu1 else _pick_active(mine)


def upsert_peer(peer: Peer) -> None:
    """
    Вставляет/обновляет peer-слот (источник правды — таблица peers, Фаза 2 B).
    Ключ — device_id. Backward-compat shim: если device_id не задан (старый
    вызов с platform/os), берём device_id существующего слота этого юзера на
    этом сервере с тем же os; иначе создаём новое устройство (db_add_device).
    Так бот/ЛК работают без правок до B3-UX.
    """
    from .database import db_upsert_peer, db_add_device

    sid = normalize_peer_server_id(peer.server_id)
    os_ = _normalize_platform(peer.os or peer.platform)
    device_id = peer.device_id
    if not device_id:
        existing = find_peer_by_telegram_id(peer.telegram_id, server_id=sid, platform=os_)
        device_id = existing.device_id if (existing and existing.device_id) \
            else db_add_device(peer.telegram_id, _device_label(os_), os_)

    db_upsert_peer({
        "telegram_id": peer.telegram_id,
        "server_id": sid,
        "device_id": device_id,
        "os": os_,
        "wg_ip": peer.wg_ip,
        "public_key": peer.public_key,
        "active": peer.active,
        "profile_type": peer.profile_type,
    })


def delete_peer(telegram_id: int, server_id: str, platform: Optional[str] = "pc",
                device_id: Optional[str] = None) -> None:
    """
    Удаляет peer-слот. По device_id (точно) либо по platform (legacy-shim:
    слот этого юзера на сервере с os==platform). Само устройство (devices) НЕ
    удаляется — у него могут быть слоты на других серверах (см. db_delete_device).
    """
    from .database import db_delete_peer

    sid = normalize_peer_server_id(server_id)
    if not device_id:
        existing = find_peer_by_telegram_id(telegram_id, server_id=sid,
                                            platform=_normalize_platform(platform))
        if not existing or not existing.device_id:
            return
        device_id = existing.device_id
    db_delete_peer(int(telegram_id), sid, device_id)
