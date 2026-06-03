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
    Ключ в peers.json: f"{telegram_id}:{server_id}:{platform}".
    Несколько peers на одного пользователя — разные устройства (platform) или серверы.
    """

    telegram_id: int
    wg_ip: str
    public_key: str
    server_id: str = "rus1"
    active: bool = True
    profile_type: Optional[str] = None
    platform: str = "pc"  # "pc" | "ios" | "android"


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
    Возвращает {storage_key: payload} как раньше, но источник правды — таблица
    `peers` в SQLite. storage_key = "{tid}:{server_id}:{platform}".

    Fallback: таблица пуста, а peers.json непустой → читаем JSON. После
    init_db()._migrate_peers_json_to_sqlite этого не должно случаться, но для
    критичных данных (клиентские конфиги) оставляем подстраховку на случай
    если миграция ещё не отработала.
    """
    from .database import db_get_all_peers

    rows = db_get_all_peers()
    if rows:
        out: Dict[str, dict] = {}
        for r in rows:
            sid = normalize_peer_server_id(r.get("server_id"))
            plat = _normalize_platform(r.get("platform"))
            key = f'{r["telegram_id"]}:{sid}:{plat}'
            out[key] = {
                "telegram_id": int(r["telegram_id"]),
                "wg_ip": r["wg_ip"],
                "public_key": r["public_key"],
                "server_id": sid,
                "active": bool(r["active"]),
                "profile_type": r.get("profile_type"),
                "platform": plat,
            }
        return out

    # Fallback на сырой JSON (таблица пуста)
    raw = _load_raw(PEERS_FILE)
    migrated = _migrate_peers_json_on_load(raw)
    if migrated != raw:
        _save_raw(PEERS_FILE, migrated)
    return migrated


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


def get_all_peers() -> List[Peer]:
    data = _load_peers_data()
    peers: List[Peer] = []
    for key, payload in data.items():
        sk = str(key)
        parts = sk.split(":")
        try:
            # platform: из ключа (3-я часть) или из payload
            if len(parts) == 3:
                plat = _normalize_platform(parts[2])
            else:
                plat = _normalize_platform(payload.get("platform"))
            peers.append(
                Peer(
                    telegram_id=int(payload.get("telegram_id", parts[0])),
                    wg_ip=payload["wg_ip"],
                    public_key=payload["public_key"],
                    server_id=normalize_peer_server_id(payload.get("server_id", "rus1")),
                    active=bool(payload.get("active", True)),
                    profile_type=payload.get("profile_type"),
                    platform=plat,
                )
            )
        except (ValueError, KeyError):
            continue
    return peers


def find_peer_by_telegram_id(
    telegram_id: int,
    server_id: Optional[str] = None,
    platform: Optional[str] = None,
) -> Optional[Peer]:
    """
    Ищет peer для пользователя.

    - server_id + platform → точная выборка слота (tid:sid:platform).
    - server_id без platform → ищет среди всех платформ для этого сервера;
      приоритет: pc → ios → android → первый активный.
    - без server_id → приоритет: eu1, первый активный (любая платформа).

    main в server_id нормализуется в rus1.
    """
    data = _load_peers_data()

    if server_id is not None and platform is not None:
        # Точное совпадение: tid:sid:platform
        sid = normalize_peer_server_id(server_id)
        plat = _normalize_platform(platform)
        key = _peer_storage_key(telegram_id, sid, plat)
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
                platform=plat,
            )
        except (ValueError, KeyError):
            return None

    if server_id is not None:
        # Поиск по tid:sid:* — любая платформа, приоритет pc → ios → android
        sid = normalize_peer_server_id(server_id)
        candidates: List[Peer] = []
        for plat_try in ("pc", "ios", "android"):
            key = _peer_storage_key(telegram_id, sid, plat_try)
            payload = data.get(key)
            if payload:
                try:
                    candidates.append(
                        Peer(
                            telegram_id=int(payload.get("telegram_id", telegram_id)),
                            wg_ip=payload["wg_ip"],
                            public_key=payload["public_key"],
                            server_id=normalize_peer_server_id(payload.get("server_id", sid)),
                            active=bool(payload.get("active", True)),
                            profile_type=payload.get("profile_type"),
                            platform=_normalize_platform(payload.get("platform", plat_try)),
                        )
                    )
                except (ValueError, KeyError):
                    continue
        for p in candidates:
            if p.active:
                return p
        return candidates[0] if candidates else None

    # Нет server_id: ищем среди всех peers пользователя
    prefix = f"{telegram_id}:"
    candidates_all: List[Peer] = []
    for key, payload in data.items():
        sk = str(key)
        if not sk.startswith(prefix):
            continue
        parts = sk.split(":")
        try:
            plat = _normalize_platform(parts[2] if len(parts) >= 3 else payload.get("platform"))
            sid_part = parts[1] if len(parts) >= 2 else "rus1"
            candidates_all.append(
                Peer(
                    telegram_id=int(payload.get("telegram_id", telegram_id)),
                    wg_ip=payload["wg_ip"],
                    public_key=payload["public_key"],
                    server_id=normalize_peer_server_id(payload.get("server_id", sid_part)),
                    active=bool(payload.get("active", True)),
                    profile_type=payload.get("profile_type"),
                    platform=plat,
                )
            )
        except (ValueError, KeyError):
            continue

    if not candidates_all:
        return None

    # Приоритет: eu1, первый активный
    for sid in ("eu1",):
        for p in candidates_all:
            if p.server_id == sid and p.active:
                return p
    for p in candidates_all:
        if p.active:
            return p
    return candidates_all[0]


def upsert_peer(peer: Peer) -> None:
    """
    Вставляет/обновляет peer-слот. Источник правды — таблица `peers` в SQLite;
    peers.json зеркалится пока DUAL_WRITE_JSON=True (страховка отката).
    """
    sid = normalize_peer_server_id(peer.server_id)
    plat = _normalize_platform(getattr(peer, "platform", "pc"))
    peer_norm = Peer(
        telegram_id=peer.telegram_id,
        wg_ip=peer.wg_ip,
        public_key=peer.public_key,
        server_id=sid,
        active=peer.active,
        profile_type=peer.profile_type,
        platform=plat,
    )
    from .database import db_upsert_peer

    db_upsert_peer(
        {
            "telegram_id": peer_norm.telegram_id,
            "server_id": sid,
            "platform": plat,
            "wg_ip": peer_norm.wg_ip,
            "public_key": peer_norm.public_key,
            "active": peer_norm.active,
            "profile_type": peer_norm.profile_type,
        }
    )
    if DUAL_WRITE_JSON:
        _upsert_peer_json(peer_norm)


def delete_peer(telegram_id: int, server_id: str, platform: str = "pc") -> None:
    """
    Удаляет peer-слот (редко нужно). Источник правды — SQLite; peers.json
    зеркалится пока DUAL_WRITE_JSON=True.
    """
    sid = normalize_peer_server_id(server_id)
    plat = _normalize_platform(platform)
    from .database import db_delete_peer

    db_delete_peer(telegram_id, sid, plat)
    if DUAL_WRITE_JSON:
        _delete_peer_json(telegram_id, sid, plat)
