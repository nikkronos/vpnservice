#!/usr/bin/env python3
"""
Напоминания об окончании доступа (подписка/триал/тест). Запускается cron'ом раз
в день (12:00 МСК).

ЕЖЕДНЕВНО шлёт юзеру напоминание, начиная за 7 дней до окончания и до дня
окончания включительно (days_left 7→0). Текст меняется по числу оставшихся дней.

Идемпотентность: колонка users.last_reminder_date — не шлём дважды в один
календарный день. После продления days_left становится > 7 → юзер выпадает из
выборки; когда снова опустится до 7 — напоминания пойдут заново (дата != сегодня).

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
from bot import churn  # noqa: E402
from bot.database import (  # noqa: E402
    init_db,
    db_users_due_for_daily_reminder,
    db_mark_daily_reminder_sent,
    db_users_due_for_churn_survey,
    db_mark_churn_asked,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("expiry_reminder")


RECOVERY_URL = "https://supportkronos.online:8443/recovery"

def _message_for(days_left: int) -> str:
    """Текст ежедневного напоминания по числу оставшихся дней (0..7)."""
    if days_left <= 0:
        return (
            "🔴 <b>Доступ к VPN заканчивается сегодня.</b>\n\n"
            "Скоро устройства перестанут подключаться. Продли — и всё снова работает.\n\n"
            "💳 «Продлить подписку» в этом боте."
        )
    word = "день" if days_left == 1 else ("дня" if days_left in (2, 3, 4) else "дней")
    tail = ("Продли заранее, чтобы устройства не отвалились в неподходящий момент."
            if days_left >= 4 else
            "Продление займёт минуту — переведи и подтверди кнопкой.")
    return (
        f"⏰ <b>Доступ к VPN заканчивается через {days_left} {word}.</b>\n\n"
        f"{tail}\n\n"
        f"💳 «Продлить подписку» в этом боте. Либо ЛК: {RECOVERY_URL}"
    )


# Кнопка «Продлить подписку» под напоминаниями (callback pay_show — хендлер в боте).
PAY_REMINDER_MARKUP = {"inline_keyboard": [[
    {"text": "💳 Продлить подписку", "callback_data": "pay_show"},
]]}

# T-0: + «не планирую продлевать» → опрос причин (callback churn_open в боте).
PAY_OR_CHURN_MARKUP = {"inline_keyboard": [
    [{"text": "💳 Продлить подписку", "callback_data": "pay_show"}],
    [{"text": "🤔 Не планирую продлевать", "callback_data": "churn_open"}],
]}


def send_telegram_message(bot_token: str, chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Отправляет HTML-сообщение через TG API. Возвращает True при успехе."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    body = json.dumps(payload).encode("utf-8")
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
    """Ежедневный прогон: (1) напоминания об окончании (0..7 дней, по одному в день),
    (2) T+1 churn-опрос (истёк вчера, не оплатил, не спрошен)."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()

    # 1. Ежедневные напоминания
    users = db_users_due_for_daily_reminder()
    logger.info("Daily reminder: %d candidates", len(users))
    sent = 0
    for u in users:
        tid = u.get("telegram_id")
        exp = u.get("expires_at")
        if not tid or not exp:
            continue
        try:
            exp_date = datetime.fromisoformat(exp).date()
        except (ValueError, TypeError):
            continue
        days_left = (exp_date - today).days
        if days_left < 0 or days_left > 7:
            continue  # подстраховка (SQL уже фильтрует окно)
        markup = PAY_OR_CHURN_MARKUP if days_left == 0 else PAY_REMINDER_MARKUP
        if send_telegram_message(bot_token, int(tid), _message_for(days_left), reply_markup=markup):
            db_mark_daily_reminder_sent(int(tid), today.isoformat())
            sent += 1
        else:
            logger.warning("Will retry daily reminder for tid=%s next run", tid)
    logger.info("Daily reminder: sent %d", sent)

    # 2. Авто T+1 churn-опрос (только 3.2 «пользовавшиеся»)
    due_churn = db_users_due_for_churn_survey()
    logger.info("Churn survey: %d due", len(due_churn))
    csent = 0
    for u in due_churn:
        tid = u.get("telegram_id")
        if not tid:
            continue
        if send_telegram_message(bot_token, int(tid), churn.text_for("churn"),
                                 reply_markup=churn.inline_keyboard_dict("churn")):
            db_mark_churn_asked(int(tid))
            csent += 1
        else:
            logger.warning("Will retry churn survey for tid=%s next run", tid)
    logger.info("Churn survey: sent %d", csent)


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
