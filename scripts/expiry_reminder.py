#!/usr/bin/env python3
"""
Напоминания об окончании подписки. Запускается cron'ом раз в день (рекомендую 12:00 МСК).

Шлёт юзерам сообщения в Telegram-бот через TG HTTP API:
- T-7  → «Подписка заканчивается через 7 дней — продли в боте».
- T-3  → «Через 3 дня. Продли, чтобы не отвалились устройства».
- T-0  → «Подписка закончилась сегодня. Продли — и всё снова работает».

Идемпотентность: для каждого юзера в users есть флаги notif_7d_sent /
notif_3d_sent / notif_0d_sent. После отправки выставляем флаг — повторно
в этом цикле подписки не пошлём. Флаги сбрасываются в db_extend_subscription()
при каждом продлении → следующий цикл получит свои напоминания.

Grandfather (expires_at IS NULL) — пропускаются (бессрочный доступ, нечего напоминать).

ENV: BOT_TOKEN (из env_vars.txt, тот же что и у бота).
"""

import json
import logging
import pathlib
import sys
import urllib.request
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.config import load_config  # noqa: E402
from bot.database import (  # noqa: E402
    init_db,
    db_users_due_for_expiry_notif,
    db_mark_expiry_notif_sent,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("expiry_reminder")


RECOVERY_URL = "https://supportkronos.online:8443/recovery"

# Тексты — менять здесь. {recovery_url} подставится автоматически.
TEMPLATES = {
    7: (
        "⏰ <b>Подписка заканчивается через 7 дней.</b>\n\n"
        "Продли заранее, чтобы устройства не отвалились в неподходящий момент.\n\n"
        "💳 Открой бот и нажми «Продлить подписку» — реквизиты и кнопка «Я перевёл» там же. "
        "Либо через ЛК: {recovery_url}"
    ),
    3: (
        "⏰ <b>Подписка заканчивается через 3 дня.</b>\n\n"
        "Перевести 200 ₽ и подтвердить через кнопку — займёт минуту.\n\n"
        "💳 «Продлить подписку» в этом боте."
    ),
    0: (
        "🔴 <b>Подписка закончилась сегодня.</b>\n\n"
        "Скоро устройства перестанут подключаться. Продли — и всё снова работает.\n\n"
        "💳 «Продлить подписку» в этом боте."
    ),
}


def send_telegram_message(bot_token: str, chat_id: int, text: str) -> bool:
    """Отправляет HTML-сообщение через TG API. Возвращает True при успехе."""
    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok"):
            return True
        logger.warning("TG API not ok: %s", data)
        return False
    except urllib.error.HTTPError as e:
        # 403 Forbidden = юзер заблокировал бота. Не шлём ему больше — выставляем флаг.
        if e.code == 403:
            logger.info("User blocked the bot (403)")
            return True  # считаем «отправлено», чтобы не ретраить
        logger.warning("HTTPError sending to chat_id=%s: %s", chat_id, e)
        return False
    except Exception as e:
        logger.warning("Failed to send to chat_id=%s: %s", chat_id, e)
        return False


def run_reminder_cycle(bot_token: str) -> None:
    """Один прогон по всем трём окнам напоминаний."""
    total_sent = 0
    for days_until in (7, 3, 0):
        users = db_users_due_for_expiry_notif(days_until)
        if not users:
            logger.info("T-%d: nothing to send", days_until)
            continue
        logger.info("T-%d: %d users due", days_until, len(users))
        text_tpl = TEMPLATES[days_until]
        text = text_tpl.format(recovery_url=RECOVERY_URL)
        for u in users:
            tid = u.get("telegram_id")
            if not tid:
                continue
            ok = send_telegram_message(bot_token, int(tid), text)
            if ok:
                db_mark_expiry_notif_sent(int(tid), days_until)
                total_sent += 1
            else:
                logger.warning("Will retry T-%d for tid=%s next run", days_until, tid)
    logger.info("Total sent this cycle: %d", total_sent)


def main() -> int:
    init_db()
    try:
        config = load_config()
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        return 1
    bot_token = getattr(config, "bot_token", None)
    if not bot_token:
        logger.error("BOT_TOKEN missing in config")
        return 1
    run_reminder_cycle(bot_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
