import logging

import telebot
from telebot import types

from .config import load_config
from .storage import User, find_user, get_all_users, upsert_user, is_owner


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    bot = telebot.TeleBot(config.bot_token, parse_mode="HTML")
    admin_id = config.admin_id

    def safe_reply(message: types.Message, text: str) -> bool:
        """Отправляет ответ; при ошибке логирует и возвращает False."""
        try:
            bot.reply_to(message, text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.exception("Ошибка при отправке ответа: %s", e)
            return False

    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        text_lines = [
            "Привет! Это VPN бот.",
            "",
            "Сейчас бот в режиме MVP и работает только с вручную подготовленным конфигом.",
            "Доступные команды:",
            "/get_config — получить текущий конфиг",
            "/regen — запросить регенерацию конфига (пока только уведомление администратору)",
            "/status — показать базовую информацию о доступе",
            "/my_config — синоним /get_config",
        ]
        safe_reply(message, "\n".join(text_lines))

        # Автоматически регистрируем владельца как пользователя (owner),
        # чтобы в списке /users он тоже отображался.
        if message.from_user and message.from_user.id == admin_id:
            owner = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                role="owner",
                active=True,
            )
            upsert_user(owner)

    @bot.message_handler(commands=["get_config"])
    def cmd_get_config(message: types.Message) -> None:  # type: ignore[override]
        """
        MVP: пока без автоматической генерации на сервере.
        Дальше сюда добавим логику SSH/скриптов для выдачи актуального clientX.conf.
        """
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        user = find_user(message.from_user.id)
        if not user or not user.active:
            safe_reply(
                message,
                "Ты ещё не зарегистрирован в VPN‑сервисе.\n"
                "Попроси владельца добавить тебя командой /add_user.",
            )
            return

        if message.from_user.id != admin_id:
            safe_reply(
                message,
                "Сейчас конфиг для тебя подготовлен вручную.\n"
                "В следующем этапе бот будет выдавать персональный файл и QR.",
            )
            return

        safe_reply(
            message,
            "Сейчас конфиг client1.conf для тебя подготовлен вручную.\n"
            "Дальше научим бота отдавать актуальные конфиги автоматически.",
        )

    @bot.message_handler(commands=["regen"])
    def cmd_regen(message: types.Message) -> None:  # type: ignore[override]
        # На следующем этапе сюда добавим реальную регенерацию peer/конфига на сервере.
        safe_reply(
            message,
            "Запрос на регенерацию конфига принят (MVP: пока только текст). "
            "В будущем здесь будет автоматическое пересоздание ключей и конфигов.",
        )

    @bot.message_handler(commands=["status"])
    def cmd_status(message: types.Message) -> None:  # type: ignore[override]
        # Минимальный статус; позже можно расширить (срок доступа, текущий сервер, статистика).
        safe_reply(
            message,
            "VPN доступ активен.\nТекущая нода: Timeweb (81.200.146.32).",
        )

    @bot.message_handler(commands=["my_config"])
    def cmd_my_config(message: types.Message) -> None:  # type: ignore[override]
        cmd_get_config(message)

    @bot.message_handler(commands=["add_user"])
    def cmd_add_user(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not is_owner(message.from_user.id, admin_id):
            safe_reply(message, "Эта команда доступна только владельцу VPN.")
            return

        # /add_user или /add_user @username или /add_user 123456
        parts = (message.text or "").strip().split(maxsplit=1)
        target_id = None
        target_username = None

        if len(parts) == 1 and message.reply_to_message and message.reply_to_message.from_user:
            # Если команда ответом на сообщение — берём того, кому отвечаем
            target_id = message.reply_to_message.from_user.id
            target_username = getattr(message.reply_to_message.from_user, "username", None) or None
        elif len(parts) == 2:
            arg = parts[1].strip()
            if arg.startswith("@"):
                target_username = arg.lstrip("@")
            else:
                try:
                    target_id = int(arg)
                except ValueError:
                    safe_reply(
                        message,
                        "Не удалось распознать аргумент. Используй:\n"
                        "/add_user <telegram_id> или /add_user @username или ответом на сообщение пользователя.",
                    )
                    return
        else:
            safe_reply(
                message,
                "Как пользоваться:\n"
                "/add_user <telegram_id>\n"
                "/add_user @username\n"
                "или отправь /add_user как ответ на сообщение пользователя.",
            )
            return

        if target_id is None and target_username is None:
            safe_reply(
                message,
                "Не удалось определить пользователя. Попробуй ещё раз: /add_user <telegram_id> или /add_user @username.",
            )
            return

        # Если есть ID — используем его как основной ключ.
        if target_id is None:
            # На этом этапе, если дали только @username без ID, мы не можем 100% сопоставить,
            # поэтому просто сохраняем username, а ID появится, когда пользователь впервые напишет боту.
            safe_reply(
                message,
                "Пользователь добавлен по username. Как только он напишет боту, его Telegram ID будет зафиксирован.",
            )
            # Храним временно с отрицательным ID, чтобы не пересекаться с реальными.
            temp_user = User(telegram_id=-1, username=target_username, role="user", active=True)
            upsert_user(temp_user)
            return

        new_user = find_user(target_id) or User(
            telegram_id=target_id,
            username=target_username,
            role="user",
            active=True,
        )
        # Обновляем username, если появился новый.
        if target_username:
            new_user.username = target_username

        upsert_user(new_user)
        safe_reply(
            message,
            f"Пользователь добавлен/обновлён:\n"
            f"ID: <code>{new_user.telegram_id}</code>\n"
            f"Username: @{new_user.username}" if new_user.username else "без username",
        )

    @bot.message_handler(commands=["users"])
    def cmd_users(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not is_owner(message.from_user.id, admin_id):
            safe_reply(message, "Эта команда доступна только владельцу VPN.")
            return

        try:
            users = get_all_users()
        except Exception as e:  # noqa: BLE001
            logger.exception("Ошибка при чтении списка пользователей: %s", e)
            safe_reply(message, "Произошла ошибка при чтении списка. Попробуй позже.")
            return
        if not users:
            safe_reply(message, "Пока нет зарегистрированных пользователей.")
            return

        lines = ["<b>Пользователи VPN:</b>"]
        for u in users:
            role_label = "👑 owner" if u.role == "owner" else "user"
            status_label = "✅ active" if u.active else "⛔ disabled"
            uname = f"@{u.username}" if u.username else "(без username)"
            lines.append(
                f"- <code>{u.telegram_id}</code> {uname} — {role_label}, {status_label}"
            )

        safe_reply(message, "\n".join(lines))

    logger.info("Starting VPN Telegram bot (pyTelegramBotAPI)...")
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()

