"""
Синхронизация пользователей VPN-сервиса в Google Sheets.

Требования (env_vars.txt):
    GOOGLE_SERVICE_ACCOUNT_JSON  — путь к JSON-файлу service account
                                   (например /opt/vpnservice/google-sa.json)
    GOOGLE_SHEETS_ID             — ID таблицы Google Sheets
                                   (из URL: /d/<ID>/edit)

Права сервисного аккаунта:
    Откройте таблицу → «Поделиться» → добавьте email сервисного аккаунта
    с правами «Редактор».

Структура листа "Users":
    A: id | B: telegram_id | C: username | D: email | E: role
    F: active | G: preferred_server_id | H: email_verified
    I: has_vless | J: peers_count | K: created_at | L: synced_at
"""

from __future__ import annotations

import logging
import pathlib
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SHEET_NAME = "Users"
_HEADER = [
    "id", "telegram_id", "username", "email", "role",
    "active", "preferred_server_id", "email_verified",
    "has_vless", "peers_count", "created_at", "synced_at",
]


def _load_env() -> Dict[str, str]:
    """Читает env_vars.txt из корня проекта."""
    base = pathlib.Path(__file__).resolve().parent.parent
    env_file = base / "env_vars.txt"
    if not env_file.exists():
        return {}
    result: Dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _build_rows(users: List[Dict], peer_count: Dict[int, int], now_iso: str) -> List[List[Any]]:
    """Конвертирует записи users → строки для Sheets (без заголовка)."""
    rows: List[List[Any]] = []
    for u in users:
        tid = u.get("telegram_id")
        rows.append([
            u.get("id", ""),
            tid if tid is not None else "",
            u.get("username") or "",
            u.get("email") or "",
            u.get("role", "user"),
            "1" if u.get("active") else "0",
            u.get("preferred_server_id") or "",
            "1" if u.get("email_verified") else "0",
            "1" if u.get("vless_uuid") else "0",
            peer_count.get(tid, 0) if tid else 0,
            u.get("created_at") or "",
            now_iso,
        ])
    return rows


def sync_users_to_sheets(
    service_account_path: Optional[str] = None,
    spreadsheet_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Синхронизирует всех пользователей из БД в лист «Users» Google Sheets.

    Параметры можно передать явно или оставить None — тогда берутся из env_vars.txt.

    Возвращает dict:
        {"ok": True, "updated": N, "message": "..."}
        {"ok": False, "error": "..."}
    """
    # ── 0. Импортируем зависимости ─────────────────────────────────────────────
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return {
            "ok": False,
            "error": (
                "Зависимости не установлены. "
                "Выполни: pip install gspread google-auth"
            ),
        }

    # ── 1. Читаем конфиг ───────────────────────────────────────────────────────
    env = _load_env()
    sa_path = service_account_path or env.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    sheet_id = spreadsheet_id or env.get("GOOGLE_SHEETS_ID", "").strip()

    if not sa_path:
        return {"ok": False, "error": "GOOGLE_SERVICE_ACCOUNT_JSON не задан в env_vars.txt"}
    if not sheet_id:
        return {"ok": False, "error": "GOOGLE_SHEETS_ID не задан в env_vars.txt"}
    if not pathlib.Path(sa_path).exists():
        return {"ok": False, "error": f"Service account JSON не найден: {sa_path}"}

    # ── 2. Получаем данные из БД ───────────────────────────────────────────────
    try:
        from .database import db_get_all_users
        from .storage import get_all_peers
    except ImportError:
        from bot.database import db_get_all_users  # type: ignore[no-redef]
        from bot.storage import get_all_peers  # type: ignore[no-redef]

    users = db_get_all_users()
    peers = get_all_peers()
    peer_count: Dict[int, int] = {}
    for p in peers:
        if p.active and p.telegram_id:
            peer_count[p.telegram_id] = peer_count.get(p.telegram_id, 0) + 1

    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = _build_rows(users, peer_count, now_iso)

    # ── 3. Подключаемся к Google Sheets ───────────────────────────────────────
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
        creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(sheet_id)
    except Exception as exc:
        logger.exception("Google Sheets: ошибка подключения: %s", exc)
        return {"ok": False, "error": f"Ошибка подключения к Google Sheets: {exc}"}

    # ── 4. Открываем / создаём лист ────────────────────────────────────────────
    try:
        try:
            ws = spreadsheet.worksheet(_SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=_SHEET_NAME, rows=1000, cols=len(_HEADER))
            logger.info("Google Sheets: создан лист '%s'", _SHEET_NAME)
    except Exception as exc:
        logger.exception("Google Sheets: ошибка доступа к листу: %s", exc)
        return {"ok": False, "error": f"Ошибка доступа к листу: {exc}"}

    # ── 5. Записываем данные (полная перезапись) ───────────────────────────────
    try:
        ws.clear()
        all_data = [_HEADER] + rows
        ws.update(
            range_name="A1",
            values=all_data,
            value_input_option="RAW",
        )
        # Жирный заголовок
        ws.format("A1:L1", {"textFormat": {"bold": True}})
    except Exception as exc:
        logger.exception("Google Sheets: ошибка записи данных: %s", exc)
        return {"ok": False, "error": f"Ошибка записи в таблицу: {exc}"}

    n = len(rows)
    logger.info("Google Sheets: синхронизировано %d пользователей в '%s'", n, _SHEET_NAME)
    return {
        "ok": True,
        "updated": n,
        "message": f"Синхронизировано {n} пользователей → Google Sheets ({now_iso} UTC)",
    }
