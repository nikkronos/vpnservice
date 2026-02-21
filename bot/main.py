import io
import logging
from pathlib import Path

import telebot
from telebot import types

from .config import load_config
from .storage import (
    User,
    find_peer_by_telegram_id,
    find_user,
    get_all_peers,
    get_all_users,
    is_owner,
    upsert_user,
)
from .wireguard_peers import (
    WireGuardError,
    create_amneziawg_peer_and_config_for_user,
    create_peer_and_config_for_user,
    execute_server_command,
    get_available_servers,
    is_amneziawg_eu1_configured,
    regenerate_peer_and_config_for_user,
    replace_peer_with_profile_type,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_instruction_text(base_dir: Path, name: str) -> str:
    """Загружает текст инструкции из docs/bot-instruction-texts/instruction_<name>_short.txt."""
    path = base_dir / "docs" / "bot-instruction-texts" / f"instruction_{name}_short.txt"
    if not path.exists():
        return f"(Файл инструкции не найден: {path.name})"
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return f"(Не удалось прочитать инструкцию {path.name})"


def _get_amneziawg_instruction_short(config: BotConfig) -> str:
    """Краткая инструкция по AmneziaWG для Европы (ПК + iOS)."""
    path = config.base_dir / "docs" / "bot-instruction-texts" / "instruction_amneziawg_short.txt"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            pass
    return (
        "🌍 <b>Европа (AmneziaWG)</b>\n\n"
        "1. Скачай приложение AmneziaVPN или AmneziaWG: amnezia.org/en/downloads\n"
        "2. Конфиг для Европы выдаётся вручную — напиши владельцу бота.\n"
        "3. На ПК: импортируй .conf в AmneziaVPN.\n"
        "4. На iPhone/iPad: сохрани .conf файл → Файлы → долгое нажатие на файл → Поделиться → AmneziaWG.\n\n"
        "Подробнее: команда /instruction (если настроена инструкция для AmneziaWG)."
    )


def _send_eu1_amneziawg_instruction(
    message: types.Message,
    has_existing_peer: bool,
) -> None:
    """Отправляет инструкцию по AmneziaWG для Европы и текст «конфиг вручную»."""
    config = load_config()
    instr = _get_amneziawg_instruction_short(config)
    extra = ""
    if has_existing_peer:
        extra = "\n\n⚠️ Старый WireGuard конфиг для Европы больше не поддерживается. Для Европы теперь используется AmneziaWG."
    safe_reply(
        message,
        f"{instr}\n\n"
        "Конфиг для Европы (AmneziaWG) выдаётся вручную. Напиши владельцу."
        f"{extra}",
    )


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
            "Привет! Это VPN бот. 🔐",
            "",
            "Сейчас бот в режиме self-service: владелец добавляет пользователей,",
            "а бот выдаёт персональные конфиги (Россия — WireGuard, Европа — AmneziaWG).",
            "",
            "📋 <b>Доступные команды:</b>",
            "/get_config — получить или переслать свой конфиг",
            "/server — выбрать сервер (РФ/EU). Европа = AmneziaWG (импорт в AmneziaVPN).",
            "/regen — запросить обновление конфига (перегенерировать ключи)",
            "/instruction — как подключиться (ПК / iPhone–iPad, в т.ч. AmneziaWG)",
            "/proxy — ссылка для Telegram (прокси при блокировках)",
            "/status — показать базовую информацию о доступе",
            "/help — подробная справка о режимах VPN",
            "/my_config — синоним /get_config",
            "",
            "💡 <b>Серверы:</b>",
            "🇷🇺 Россия — WireGuard. 🇪🇺 Европа — AmneziaWG (работает из РФ, импорт в AmneziaVPN/AmneziaWG).",
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
                # На eu1 проверяем совпадение типа профиля с выбором пользователя
                preferred_pt = getattr(user, "preferred_profile_type", None) if preferred_server_id == "eu1" else None
                current_pt = getattr(peer_on_preferred, "profile_type", None)
                if preferred_server_id == "eu1" and preferred_pt and current_pt != preferred_pt:
                    # Пользователь выбрал другой тип профиля — пересоздаём peer с новым типом
                    peer, client_config = replace_peer_with_profile_type(
                        telegram_id, preferred_server_id, preferred_pt
                    )
                    pt = getattr(peer, "profile_type", None)
                    if pt == "vpn_gpt":
                        filename = f"vpn_{peer.telegram_id}_{peer.server_id}_gpt.conf"
                    elif pt == "unified":
                        filename = f"vpn_{peer.telegram_id}_{peer.server_id}_unified.conf"
                    else:
                        filename = f"vpn_{peer.telegram_id}_{peer.server_id}.conf"
                    _send_config_file(chat_id, client_config, filename)
                    servers_info = get_available_servers()
                    server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
                    profile_note = (
                        "\n\n🟣 <b>Профиль: Универсальный</b>\n"
                        "Один профиль для всего: обычные сайты напрямую, ChatGPT и заблокированные — через Shadowsocks.\n"
                        "Как у крупных VPN‑провайдеров.\n"
                    ) if pt == "unified" else (
                        "\n\n🟢 <b>Профиль: VPN+GPT</b>\n"
                        "HTTP/HTTPS трафик идёт через Shadowsocks для обхода блокировок.\n"
                    ) if pt == "vpn_gpt" else "\n\n🔵 <b>Профиль: Обычный VPN</b>\n"
                    safe_reply(
                        message,
                        f"✅ Профиль переключён на сервере <b>{server_name}</b>.\n"
                        f"IP в VPN-сети: <code>{peer.wg_ip}</code>"
                        f"{profile_note}\n"
                        "📥 Импортируй новый конфиг в WireGuard. Старый конфиг больше не будет работать.\n"
                        f"\n💡 Другой сервер/профиль — /server. Инструкция — /instruction.",
                    )
                    return
                # Peer уже существует, тип профиля совпадает — просто сообщаем
                servers_info = get_available_servers()
                server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
                # Для Европы (eu1) — AmneziaWG: другой текст
                if preferred_server_id == "eu1":
                    if is_amneziawg_eu1_configured():
                        safe_reply(
                            message,
                            f"Для тебя уже создан VPN‑доступ на сервере <b>{server_name}</b> (AmneziaWG).\n"
                            "Если нужен новый конфиг — используй /regen для регенерации.",
                        )
                    else:
                        _send_eu1_amneziawg_instruction(message, has_existing_peer=True)
                else:
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

            # Европа (eu1): выдаём AmneziaWG — через скрипт на сервере или инструкцию вручную
            if preferred_server_id == "eu1":
                if is_amneziawg_eu1_configured():
                    try:
                        peer, client_config = create_amneziawg_peer_and_config_for_user(telegram_id)
                        filename = f"vpn_{peer.telegram_id}_{peer.server_id}_amneziawg.conf"
                        _send_config_file(chat_id, client_config, filename)
                        servers_info = get_available_servers()
                        server_name = servers_info.get("eu1", {}).get("name", "Европа")
                        safe_reply(
                            message,
                            f"✅ Создан VPN‑доступ на сервере <b>{server_name}</b> (AmneziaWG)\n"
                            f"IP в VPN-сети: <code>{peer.wg_ip}</code>\n\n"
                            "📥 Импортируй файл в приложение <b>AmneziaVPN</b> или <b>AmneziaWG</b>.\n"
                            "На iPhone/iPad: Файлы → долгое нажатие на .conf → Поделиться → AmneziaWG.\n"
                            f"\n💡 Инструкция по подключению — /instruction.",
                        )
                    except WireGuardError as exc:
                        logger.exception("Ошибка AmneziaWG для %s: %s", telegram_id, exc)
                        safe_reply(
                            message,
                            "Не удалось создать конфиг AmneziaWG. Попробуй позже или напиши владельцу.\n"
                            "Инструкция по ручной настройке — /instruction.",
                        )
                else:
                    _send_eu1_amneziawg_instruction(message, peer_on_preferred is not None)
                return

            # Тип профиля для eu1: Обычный VPN или VPN+GPT (только для main и других WireGuard-нод)
            profile_type = None
            if preferred_server_id == "eu1":
                profile_type = getattr(user, "preferred_profile_type", None)

            # Создаём новый peer на выбранном сервере (main и др., не eu1 — eu1 обработан выше)
            peer, client_config = create_peer_and_config_for_user(
                telegram_id,
                server_id=preferred_server_id,
                profile_type=profile_type,
            )

        except WireGuardError as exc:
            logger.exception("Ошибка при обработке /get_config для %s: %s", telegram_id, exc)
            safe_reply(
                message,
                "Произошла ошибка при подготовке конфига WireGuard.\n"
                "Попробуй позже или сообщи владельцу, чтобы он проверил логи бота.",
            )
            return

        # Имя файла: для VPN+GPT — _gpt.conf, для Unified — _unified.conf
        pt = getattr(peer, "profile_type", None)
        if pt == "vpn_gpt":
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}_gpt.conf"
        elif pt == "unified":
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}_unified.conf"
        else:
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}.conf"
        _send_config_file(chat_id, client_config, filename)

        servers_info = get_available_servers()
        server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
        profile_note = ""
        if pt == "vpn_gpt":
            profile_note = (
                "\n\n🟢 <b>Профиль: VPN+GPT</b>\n"
                "HTTP/HTTPS трафик идёт через Shadowsocks для обхода блокировок.\n"
                "Подходит для: ChatGPT, заблокированные сайты, все сервисы.\n"
                "⚠️ Может быть немного медленнее из-за двойного туннелирования.\n"
            )
        elif pt == "unified":
            profile_note = (
                "\n\n🟣 <b>Профиль: Универсальный</b>\n"
                "Один профиль для всего: обычные сайты напрямую, ChatGPT и заблокированные — через Shadowsocks.\n"
                "Как у крупных VPN‑провайдеров.\n"
            )
        else:
            profile_note = (
                "\n\n🔵 <b>Профиль: Обычный VPN</b>\n"
                "Весь трафик идёт через VPN-сервер напрямую.\n"
                "Подходит для: YouTube, Instagram, обычные сайты.\n"
            )
        
        safe_reply(
            message,
            f"✅ Создан новый VPN‑доступ на сервере <b>{server_name}</b>\n"
            f"IP в VPN-сети: <code>{peer.wg_ip}</code>"
            f"{profile_note}\n"
            "📥 Импортируй файл в WireGuard и включи туннель.\n"
            f"\n💡 Другой сервер/профиль — /server. Инструкция по подключению — /instruction.",
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

            # Европа (eu1): регенерация AmneziaWG пока не автоматизирована — инструкция
            if preferred_server_id == "eu1":
                safe_reply(
                    message,
                    "Для сервера <b>Европа</b> (AmneziaWG) регенерация конфига пока вручную.\n"
                    "Напиши владельцу бота — он выдаст новый конфиг.",
                )
                return

            preferred_pt = getattr(user, "preferred_profile_type", None) if preferred_server_id == "eu1" else None
            existing_peer = find_peer_by_telegram_id(telegram_id, server_id=preferred_server_id)
            # Если на eu1 пользователь выбрал другой тип профиля — пересоздаём peer с новым типом и IP из нужного пула
            if (
                preferred_server_id == "eu1"
                and preferred_pt
                and existing_peer
                and getattr(existing_peer, "profile_type", None) != preferred_pt
            ):
                peer, client_config = replace_peer_with_profile_type(
                    telegram_id, preferred_server_id, preferred_pt
                )
            else:
                # Регенерируем peer (те же ключи/тот же тип профиля)
                peer, client_config = regenerate_peer_and_config_for_user(
                    telegram_id, server_id=preferred_server_id
                )
            
        except WireGuardError as exc:
            logger.exception("Ошибка при регенерации peer для %s: %s", telegram_id, exc)
            safe_reply(
                message,
                f"Не удалось регенерировать конфиг: {exc}\n"
                "Убедись, что у тебя уже создан VPN‑доступ (используй /get_config для создания).",
            )
            return
        
        # Отправляем новый конфиг (имя файла по типу профиля)
        pt = getattr(peer, "profile_type", None)
        if pt == "vpn_gpt":
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}_gpt.conf"
        elif pt == "unified":
            filename = f"vpn_{peer.telegram_id}_{peer.server_id}_unified.conf"
        else:
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
        
        server_name = servers_info[server_id]["name"]
        server_desc = servers_info[server_id]["description"]

        # Для Европы (eu1) — второй шаг: выбор типа профиля (Обычный VPN / VPN+GPT / Универсальный)
        if server_id == "eu1":
            bot.answer_callback_query(call.id, "Выбери тип профиля", show_alert=False)
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton(
                text="🔵 Обычный VPN",
                callback_data="profile_eu1_vpn",
            ))
            keyboard.add(types.InlineKeyboardButton(
                text="🟢 VPN+GPT (обход блокировок)",
                callback_data="profile_eu1_gpt",
            ))
            keyboard.add(types.InlineKeyboardButton(
                text="🟣 Универсальный (всё в одном)",
                callback_data="profile_eu1_unified",
            ))
            bot.edit_message_text(
                f"<b>{server_name}</b>\n{server_desc}\n\n"
                "<b>Выбери тип профиля:</b>\n\n"
                "🔵 <b>Обычный VPN</b>\n"
                "Весь трафик идёт через VPN-сервер напрямую.\n"
                "Подходит для: YouTube, Instagram, обычные сайты.\n\n"
                "🟢 <b>VPN+GPT</b>\n"
                "Трафик идёт через VPN, а HTTP/HTTPS дополнительно через Shadowsocks.\n"
                "Подходит для: ChatGPT, обход блокировок по IP, все сайты.\n"
                "⚠️ Может быть медленнее из-за двойного туннелирования.\n\n"
                "🟣 <b>Универсальный</b>\n"
                "Один профиль для всего: обычные сайты напрямую, ChatGPT и заблокированные — через Shadowsocks.\n"
                "Как у крупных VPN‑провайдеров.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return

        # Для остальных серверов — сразу сохраняем выбор
        user.preferred_server_id = server_id
        user.preferred_profile_type = None
        upsert_user(user)
        
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
    
    @bot.callback_query_handler(func=lambda call: call.data in ("profile_eu1_vpn", "profile_eu1_gpt", "profile_eu1_unified"))
    def callback_profile_eu1(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Обработчик выбора типа профиля для Европы: Обычный VPN, VPN+GPT или Универсальный."""
        if not call.from_user:
            bot.answer_callback_query(call.id, "Ошибка: не удалось определить пользователя.")
            return
        
        user = find_user(call.from_user.id)
        if not user or not user.active:
            bot.answer_callback_query(call.id, "Ты не зарегистрирован в VPN‑сервисе.")
            return
        
        is_gpt = call.data == "profile_eu1_gpt"
        is_unified = call.data == "profile_eu1_unified"
        if is_unified:
            user.preferred_profile_type = "unified"
        elif is_gpt:
            user.preferred_profile_type = "vpn_gpt"
        else:
            user.preferred_profile_type = "vpn"
        user.preferred_server_id = "eu1"
        upsert_user(user)
        
        if is_unified:
            profile_label = "Универсальный"
            profile_desc = "Один профиль: обычные сайты напрямую, ChatGPT и заблокированные — через Shadowsocks"
        elif is_gpt:
            profile_label = "VPN+GPT"
            profile_desc = "Трафик через VPN + Shadowsocks (обход блокировок ChatGPT и др.)"
        else:
            profile_label = "Обычный VPN"
            profile_desc = "Трафик через VPN напрямую (YouTube, Instagram, обычные сайты)"
        bot.answer_callback_query(call.id, f"Профиль: {profile_label}", show_alert=False)
        
        servers_info = get_available_servers()
        server_name = servers_info.get("eu1", {}).get("name", "Европа")
        bot.edit_message_text(
            f"✅ <b>Сервер выбран</b>\n\n"
            f"Твой предпочтительный сервер: <b>{server_name}</b>\n"
            f"Тип профиля: <b>{profile_label}</b>\n"
            f"<i>{profile_desc}</i>\n\n"
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

    @bot.message_handler(commands=["instruction"])
    def cmd_instruction(message: types.Message) -> None:  # type: ignore[override]
        """Отправляет пошаговую инструкцию по подключению (ПК и iPhone/iPad). Россия — WireGuard, Европа — AmneziaWG."""
        instr_pc = _load_instruction_text(config.base_dir, "pc")
        instr_ios = _load_instruction_text(config.base_dir, "ios")
        instr_amnezia = _get_amneziawg_instruction_short(config)
        safe_reply(
            message,
            f"{instr_pc}\n\n——\n\n{instr_ios}\n\n——\n\n<b>Для сервера Европа (AmneziaWG):</b>\n\n{instr_amnezia}",
        )

    @bot.message_handler(commands=["proxy"])
    def cmd_proxy(message: types.Message) -> None:  # type: ignore[override]
        """Отправляет ссылку MTProto-прокси для Telegram и краткую инструкцию."""
        if config.mtproto_proxy_link:
            instr = _load_instruction_text(config.base_dir, "mtproto")
            safe_reply(
                message,
                f"{config.mtproto_proxy_link}\n\n{instr}",
            )
        else:
            safe_reply(
                message,
                "Ссылка на прокси для Telegram не настроена. Обратись к владельцу бота.",
            )

    @bot.message_handler(commands=["my_config"])
    def cmd_my_config(message: types.Message) -> None:  # type: ignore[override]
        cmd_get_config(message)

    @bot.message_handler(commands=["help"])
    def cmd_help(message: types.Message) -> None:  # type: ignore[override]
        """Отправляет подробную справку о режимах VPN и типах профилей."""
        help_text = (
            "📖 <b>Справка по VPN боту</b>\n\n"
            "🇷🇺 <b>Россия (Timeweb)</b> — WireGuard\n"
            "Импорт конфига в приложение WireGuard. Низкий пинг, высокая скорость.\n\n"
            "🇪🇺 <b>Европа</b> — AmneziaWG\n"
            "Работает из РФ (обфускация). Импорт конфига в AmneziaVPN или AmneziaWG.\n"
            "На iPhone/iPad: Файлы → долгое нажатие на .conf → Поделиться → AmneziaWG.\n\n"
            "📱 <b>Как использовать:</b>\n"
            "1. Выбери сервер: /server\n"
            "2. Получи конфиг: /get_config\n"
            "3. Импортируй по инструкции: /instruction\n\n"
            "💬 <b>Telegram через прокси:</b>\n"
            "Если Telegram заблокирован — /proxy для MTProto-прокси.\n\n"
            "❓ <b>Вопросы?</b> Обратись к владельцу или используй /instruction."
        )
        safe_reply(message, help_text)

    @bot.message_handler(commands=["server_exec"])
    def cmd_server_exec(message: types.Message) -> None:  # type: ignore[override]
        """Выполняет команду на сервере через SSH (только для владельца)."""
        logger.info("Команда /server_exec от пользователя %s", message.from_user.id if message.from_user else "unknown")
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        
        if not is_owner(message.from_user.id, admin_id):
            logger.warning("Попытка использования /server_exec не владельцем: %s", message.from_user.id)
            safe_reply(message, "Эта команда доступна только владельцу VPN.")
            return
        
        # Парсим команду: /server_exec <server_id> <command>
        text = message.text or ""
        parts = text.split(None, 2)
        logger.info("Парсинг команды /server_exec: parts=%s, len=%d", parts, len(parts))
        if len(parts) < 3:
            help_text = (
                "Использование: /server_exec <server_id> <command>\n"
                "Пример: /server_exec eu1 wg show\n"
                "Пример: /server_exec eu1 'iptables -L FORWARD -n -v'"
            )
            logger.info("Отправка справки по /server_exec")
            safe_reply(message, help_text)
            return
        
        server_id = parts[1]
        command = parts[2]
        # Убираем кавычки из начала и конца команды, если они есть
        # Это нужно, потому что Telegram передает кавычки как часть текста
        command = command.strip()
        if (command.startswith("'") and command.endswith("'")) or (command.startswith('"') and command.endswith('"')):
            command = command[1:-1]
        
        try:
            stdout, stderr = execute_server_command(server_id, command, timeout=30)
            
            # Формируем ответ
            result_text = f"<b>Команда на {server_id}:</b> <code>{command}</code>\n\n"
            
            if stdout:
                # Ограничиваем длину вывода (Telegram лимит ~4096 символов)
                stdout_preview = stdout[:3500] + "..." if len(stdout) > 3500 else stdout
                result_text += f"<b>Вывод:</b>\n<pre>{stdout_preview}</pre>\n"
            
            if stderr:
                # systemctl status выводит в stderr, но это не ошибка
                stderr_preview = stderr[:3500] + "..." if len(stderr) > 3500 else stderr
                # Если stderr содержит полезную информацию (не только предупреждения), показываем её
                if "Active:" in stderr or "Loaded:" in stderr or len(stderr.strip()) > 50:
                    result_text += f"<b>Вывод:</b>\n<pre>{stderr_preview}</pre>\n"
                else:
                    result_text += f"<b>Ошибки:</b>\n<pre>{stderr_preview}</pre>\n"
            
            if not stdout and not stderr:
                result_text += "Команда выполнена, но вывода нет."
            
            safe_reply(message, result_text)
            
        except WireGuardError as exc:
            safe_reply(message, f"❌ Ошибка: {exc}")
        except Exception as exc:
            logger.exception("Ошибка при выполнении /server_exec: %s", exc)
            safe_reply(message, f"❌ Неожиданная ошибка: {exc}")

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
            safe_reply(
                message,
                f"Ошибка при чтении данных: {e!r}\n"
                "Проверь на сервере наличие и права на bot/data/users.json и bot/data/peers.json.",
            )
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

