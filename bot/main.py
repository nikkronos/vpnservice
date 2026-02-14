import io
import logging

import telebot
from telebot import types

from .config import load_config
from .storage import (
    User,
    find_peer_by_telegram_id,
    find_user,
    get_all_users,
    is_owner,
    upsert_user,
)
from .wireguard_peers import (
    WireGuardError,
    create_peer_and_config_for_user,
    get_available_servers,
    regenerate_peer_and_config_for_user,
)


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
            "Сейчас бот в режиме self-service: владелец добавляет пользователей,",
            "а бот выдаёт персональные конфиги WireGuard (по одному на Telegram-аккаунт).",
            "",
            "Доступные команды:",
            "/get_config — получить или переслать свой конфиг",
            "/server — выбрать сервер (РФ/EU)",
            "/regen — запросить обновление конфига (перегенерировать ключи)",
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

    def _send_config_file(chat_id: int, config_text: str, filename: str) -> None:
        """
        Отправляет текстовый конфиг как файл пользователю.
        """
        file_obj = io.BytesIO(config_text.encode("utf-8"))
        file_obj.name = filename
        bot.send_document(chat_id, file_obj, visible_file_name=filename)

    @bot.message_handler(commands=["get_config"])
    def cmd_get_config(message: types.Message) -> None:  # type: ignore[override]
        """
        Self-service логика:
        - проверяем, зарегистрирован ли пользователь;
        - если peer уже есть — формируем конфиг на основе существующих данных;
        - если peer нет — создаём его в WireGuard и сохраняем в peers.json;
        - отправляем пользователю .conf файл.
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

        chat_id = message.chat.id
        telegram_id = message.from_user.id

        # Владелец уже имеет вручную настроенный client1; для него пока оставляем
        # существующий процесс и не создаём нового peer автоматически.
        if telegram_id == admin_id:
            safe_reply(
                message,
                "У тебя (как у владельца) уже есть рабочий доступ client1,\n"
                "подключенный вручную. Для тестирования новых функций добавь отдельного\n"
                "пользователя через /add_user и проверь /get_config от его имени.",
            )
            return

        # Определяем, какой сервер использовать
        preferred_server_id = user.preferred_server_id or "main"  # дефолт — main (РФ)
        
        try:
            # Ищем peer на выбранном сервере
            peer_on_preferred = find_peer_by_telegram_id(telegram_id, server_id=preferred_server_id)
            
            # Также проверяем, есть ли peer на любом другом сервере
            peer_any = find_peer_by_telegram_id(telegram_id, server_id=None)
            
            if peer_on_preferred and peer_on_preferred.active:
                # Peer уже существует на выбранном сервере
                servers_info = get_available_servers()
                server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
                safe_reply(
                    message,
                    f"Для тебя уже создан VPN‑доступ на сервере <b>{server_name}</b> ({preferred_server_id}).\n"
                    "Если у тебя уже импортирован конфиг в приложении WireGuard и всё работает — "
                    "ничего делать не нужно.\n"
                    "Если ты потерял конфиг или нужно его обновить, используй /regen для регенерации.",
                )
                return
            
            # Если есть peer на другом сервере, но пользователь выбрал новый — создаём peer на новом сервере
            # (старый peer будет перезаписан в peers.json, так как ключ — telegram_id)
            if peer_any and peer_any.active and peer_any.server_id != preferred_server_id:
                servers_info = get_available_servers()
                old_server_name = servers_info.get(peer_any.server_id, {}).get("name", peer_any.server_id)
                new_server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
                logger.info(
                    "Пользователь %s переключается с сервера %s на %s, создаём новый peer",
                    telegram_id,
                    peer_any.server_id,
                    preferred_server_id,
                )

            # Создаём новый peer на выбранном сервере
            peer, client_config = create_peer_and_config_for_user(telegram_id, server_id=preferred_server_id)

        except WireGuardError as exc:
            logger.exception("Ошибка при обработке /get_config для %s: %s", telegram_id, exc)
            safe_reply(
                message,
                "Произошла ошибка при подготовке конфига WireGuard.\n"
                "Попробуй позже или сообщи владельцу, чтобы он проверил логи бота.",
            )
            return

        filename = f"vpn_{peer.telegram_id}_{peer.server_id}.conf"
        _send_config_file(chat_id, client_config, filename)

        servers_info = get_available_servers()
        server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
        
        safe_reply(
            message,
            f"Создан новый VPN‑доступ на сервере <b>{server_name}</b> и отправлен конфиг.\n"
            f"IP в VPN-сети: <code>{peer.wg_ip}</code>\n"
            "Импортируй файл в приложение WireGuard на своём устройстве и включи туннель.\n"
            f"\nЧтобы выбрать другой сервер, используй команду /server.",
        )

    @bot.message_handler(commands=["regen"])
    def cmd_regen(message: types.Message) -> None:  # type: ignore[override]
        """
        Команда для регенерации ключей и конфига существующего peer.
        Удаляет старый peer из WireGuard, создаёт новый с новыми ключами и отправляет обновлённый конфиг.
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
        
        chat_id = message.chat.id
        telegram_id = message.from_user.id
        
        # Владелец использует client1 вручную, для него регенерация не нужна
        if telegram_id == admin_id:
            safe_reply(
                message,
                "У тебя (как у владельца) уже есть рабочий доступ client1,\n"
                "подключенный вручную. Для регенерации используй стандартные инструменты WireGuard.",
            )
            return
        
        try:
            # Определяем, на каком сервере искать peer для регенерации
            preferred_server_id = user.preferred_server_id or "main"
            
            # Регенерируем peer (используем server_id существующего peer, если он отличается от preferred)
            peer, client_config = regenerate_peer_and_config_for_user(telegram_id, server_id=preferred_server_id)
            
        except WireGuardError as exc:
            logger.exception("Ошибка при регенерации peer для %s: %s", telegram_id, exc)
            safe_reply(
                message,
                f"Не удалось регенерировать конфиг: {exc}\n"
                "Убедись, что у тебя уже создан VPN‑доступ (используй /get_config для создания).",
            )
            return
        
        # Отправляем новый конфиг
        filename = f"vpn_{peer.telegram_id}_{peer.server_id}.conf"
        _send_config_file(chat_id, client_config, filename)
        
        servers_info = get_available_servers()
        server_name = servers_info.get(peer.server_id, {}).get("name", peer.server_id)
        
        safe_reply(
            message,
            f"✅ Конфиг регенерирован на сервере <b>{server_name}</b>.\n"
            f"IP в VPN-сети: <code>{peer.wg_ip}</code>\n"
            f"Новые ключи сгенерированы, старый peer удалён.\n\n"
            f"⚠️ <b>Важно:</b> Обнови конфиг в приложении WireGuard на всех своих устройствах!\n"
            f"Старый конфиг больше не будет работать.",
        )

    @bot.message_handler(commands=["server"])
    def cmd_server(message: types.Message) -> None:  # type: ignore[override]
        """
        Команда для выбора сервера (ноды) VPN.
        Показывает кнопки с доступными серверами и позволяет пользователю выбрать предпочтительный.
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
        
        servers_info = get_available_servers()
        current_server_id = user.preferred_server_id or "main"
        
        # Создаём inline-кнопки для выбора сервера
        keyboard = types.InlineKeyboardMarkup()
        for server_id, info in servers_info.items():
            label = info["name"]
            if server_id == current_server_id:
                label = f"✅ {label} (текущий)"
            keyboard.add(types.InlineKeyboardButton(
                text=label,
                callback_data=f"server_select_{server_id}"
            ))
        
        current_server_name = servers_info.get(current_server_id, {}).get("name", current_server_id)
        current_desc = servers_info.get(current_server_id, {}).get("description", "")
        
        text_lines = [
            f"<b>Выбор сервера VPN</b>",
            "",
            f"Текущий сервер: <b>{current_server_name}</b>",
            f"{current_desc}",
            "",
            "Выбери сервер, на котором будет создан твой VPN‑доступ:",
        ]
        
        bot.reply_to(message, "\n".join(text_lines), reply_markup=keyboard)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("server_select_"))
    def callback_server_select(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Обработчик выбора сервера через inline-кнопку."""
        if not call.from_user:
            bot.answer_callback_query(call.id, "Ошибка: не удалось определить пользователя.")
            return
        
        user = find_user(call.from_user.id)
        if not user or not user.active:
            bot.answer_callback_query(call.id, "Ты не зарегистрирован в VPN‑сервисе.")
            return
        
        server_id = call.data.replace("server_select_", "")
        servers_info = get_available_servers()
        
        if server_id not in servers_info:
            bot.answer_callback_query(call.id, f"Неизвестный сервер: {server_id}")
            return
        
        # Обновляем предпочтение пользователя
        user.preferred_server_id = server_id
        upsert_user(user)
        
        server_name = servers_info[server_id]["name"]
        server_desc = servers_info[server_id]["description"]
        
        bot.answer_callback_query(
            call.id,
            f"Выбран сервер: {server_name}",
            show_alert=False,
        )
        
        bot.edit_message_text(
            f"✅ <b>Сервер выбран</b>\n\n"
            f"Твой предпочтительный сервер: <b>{server_name}</b>\n"
            f"{server_desc}\n\n"
            f"Теперь при вызове /get_config будет создан доступ на этом сервере.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
        )
    
    @bot.message_handler(commands=["status"])
    def cmd_status(message: types.Message) -> None:  # type: ignore[override]
        """Показывает статус доступа пользователя."""
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
        
        preferred_server_id = user.preferred_server_id or "main"
        servers_info = get_available_servers()
        preferred_server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
        
        # Сначала ищем peer на выбранном сервере
        peer = find_peer_by_telegram_id(message.from_user.id, server_id=preferred_server_id)
        
        # Если не найден на выбранном, ищем на любом сервере (для обратной совместимости)
        if not peer:
            peer = find_peer_by_telegram_id(message.from_user.id, server_id=None)
        
        if peer and peer.active:
            # Показываем информацию о реальном peer (может быть на другом сервере)
            actual_server_name = servers_info.get(peer.server_id, {}).get("name", peer.server_id)
            status_text = (
                f"VPN доступ <b>активен</b>.\n"
                f"Сервер: <b>{actual_server_name}</b> ({peer.server_id})\n"
                f"IP в VPN-сети: <code>{peer.wg_ip}</code>"
            )
            # Если peer на другом сервере, чем выбранный — предупреждаем
            if peer.server_id != preferred_server_id:
                status_text += (
                    f"\n\n"
                    f"⚠️ Твой выбранный сервер: <b>{preferred_server_name}</b> ({preferred_server_id}), "
                    f"но активный доступ на <b>{actual_server_name}</b>.\n"
                    f"Чтобы создать доступ на выбранном сервере, используй /get_config."
                )
        else:
            status_text = (
                f"VPN доступ <b>не создан</b>.\n"
                f"Выбранный сервер: <b>{preferred_server_name}</b> ({preferred_server_id})\n"
                f"Используй /get_config чтобы создать доступ."
            )
        
        safe_reply(message, status_text)

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

    @bot.message_handler(commands=["stats"])
    def cmd_stats(message: types.Message) -> None:  # type: ignore[override]
        """
        Для владельца: сводка — сколько пользователей, сколько выданных конфигов (по серверам).
        """
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not is_owner(message.from_user.id, admin_id):
            safe_reply(message, "Эта команда доступна только владельцу VPN.")
            return

        try:
            users = get_all_users()
            peers = get_all_peers()
        except Exception as e:  # noqa: BLE001
            logger.exception("Ошибка при чтении данных для /stats: %s", e)
            safe_reply(message, "Ошибка при чтении данных. Попробуй позже.")
            return

        users_total = len(users)
        users_active = sum(1 for u in users if u.active)
        peers_total = len(peers)
        peers_active = sum(1 for p in peers if p.active)

        by_server: dict[str, int] = {}
        for p in peers:
            if p.active:
                by_server[p.server_id] = by_server.get(p.server_id, 0) + 1

        servers_info = get_available_servers()
        server_lines = []
        for sid, count in sorted(by_server.items()):
            name = servers_info.get(sid, {}).get("name", sid)
            server_lines.append(f"  • {name} ({sid}): {count}")

        lines = [
            "<b>📊 Сводка VPN</b>",
            "",
            f"<b>Пользователи:</b> {users_active} активных из {users_total} всего",
            f"<b>Выдано конфигов (peers):</b> {peers_active} активных из {peers_total} всего",
            "",
            "<b>По серверам (активные peers):</b>",
            "\n".join(server_lines) if server_lines else "  — пока нет",
            "",
            "<i>Одновременных подключений по устройствам бот не считает — один конфиг может быть на нескольких устройствах, но одновременно активен только один.</i>",
        ]
        safe_reply(message, "\n".join(lines))

    logger.info("Starting VPN Telegram bot (pyTelegramBotAPI)...")
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()

