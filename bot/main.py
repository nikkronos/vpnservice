import logging

import telebot
from telebot import types

from .config import load_config


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    bot = telebot.TeleBot(config.bot_token, parse_mode="HTML")
    admin_id = config.admin_id

    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message) -> None:  # type: ignore[override]
        text_lines = [
            "Привет! Это VPN бот.",
            "",
            "Сейчас бот в режиме MVP и работает только с вручную подготовленным конфигом.",
            "Доступные команды:",
            "/get_config — получить текущий конфиг",
            "/regen — запросить регенерацию конфига (пока только уведомление администратору)",
            "/status — показать базовую информацию о доступе",
        ]
        bot.reply_to(message, "\n".join(text_lines))

    @bot.message_handler(commands=["get_config"])
    def cmd_get_config(message: types.Message) -> None:  # type: ignore[override]
        """
        MVP: пока без автоматической генерации на сервере.
        Дальше сюда добавим логику SSH/скриптов для выдачи актуального clientX.conf.
        """
        if message.from_user.id != admin_id:
            bot.reply_to(
                message,
                "Пока что автоматическая выдача конфига доступна только владельцу. "
                "Позже здесь появится полноценный self‑service.",
            )
            return

        bot.reply_to(
            message,
            "Сейчас конфиг для тебя подготовлен вручную (client1.conf). "
            "В следующем этапе мы научим бота выдавать свежий конфиг и QR прямо отсюда.",
        )

    @bot.message_handler(commands=["regen"])
    def cmd_regen(message: types.Message) -> None:  # type: ignore[override]
        # На следующем этапе сюда добавим реальную регенерацию peer/конфига на сервере.
        bot.reply_to(
            message,
            "Запрос на регенерацию конфига принят (MVP: пока только текст). "
            "В будущем здесь будет автоматическое пересоздание ключей и конфигов.",
        )

    @bot.message_handler(commands=["status"])
    def cmd_status(message: types.Message) -> None:  # type: ignore[override]
        # Минимальный статус; позже можно расширить (срок доступа, текущий сервер, статистика).
        bot.reply_to(
            message,
            "VPN доступ активен.\nТекущая нода: Timeweb (81.200.146.32).",
        )

    logger.info("Starting VPN Telegram bot (pyTelegramBotAPI)...")
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()

