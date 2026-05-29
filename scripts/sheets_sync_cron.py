#!/usr/bin/env python3
"""
Cron-обёртка для синхронизации БД пользователей в Google Sheets.

Запускается каждые 6 часов через cron на Fornex:
    0 */6 * * * cd /opt/vpnservice && /opt/vpnservice/venv/bin/python scripts/sheets_sync_cron.py 2>&1 | logger -t sheets-sync

Параллельно остаётся ручной триггер в боте (`⚙️ Администратор → 📊 Sync Google Sheets`)
как fallback / refresh-по-запросу.

Логика:
- Импортирует `bot.google_sheets.sync_users_to_sheets`.
- Запускает, печатает результат (cron его подхватит через `logger`).
- При ошибке (включая отсутствие конфигурации Sheets) — exit 1, чтобы cron поднял шум.

ENV: GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEETS_ID — из env_vars.txt.
"""

import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sheets_sync_cron")


def main() -> int:
    try:
        from bot.google_sheets import sync_users_to_sheets
    except ImportError as e:
        logger.error("bot.google_sheets не импортируется: %s", e)
        return 1

    try:
        result = sync_users_to_sheets()
    except Exception as e:  # noqa: BLE001
        logger.exception("sync_users_to_sheets упал: %s", e)
        return 1

    if not result.get("ok"):
        logger.error("sync_users_to_sheets вернул ошибку: %s", result.get("error") or result)
        return 1

    updated = result.get("updated")
    msg = result.get("message") or ""
    logger.info("Sheets sync OK: updated=%s %s", updated, msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
