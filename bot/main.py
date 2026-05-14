import io
import logging
import subprocess
import time
from pathlib import Path

import telebot
from telebot import types

from .config import (
    BotConfig,
    environment_for_mtproxy_rotate,
    get_effective_mtproto_proxy_link,
    load_config,
)
from .database import (
    db_add_to_whitelist,
    db_get_whitelist,
    db_is_whitelisted,
    db_remove_from_whitelist,
    db_create_otp,
    db_verify_otp,
    db_get_vless_creds,
    init_db,
)
from .vless_peers import (
    create_vless_client_for_user,
    regenerate_vless_client_for_user,
    remove_vless_client_for_user,
)
from .email_otp import generate_otp, send_otp_email
from .storage import (
    User,
    find_peer_by_telegram_id,
    find_user,
    get_all_peers,
    get_all_users,
    is_owner,
    normalize_preferred_server_id,
    upsert_user,
)
from .wireguard_peers import (
    WireGuardError,
    create_amneziawg_peer_and_config_for_user,
    create_peer_and_config_for_user,
    execute_server_command,
    generate_vpn_url,
    get_available_servers,
    is_amneziawg_eu1_configured,
    regenerate_amneziawg_peer_and_config_for_user,
    regenerate_peer_and_config_for_user,
    replace_peer_with_profile_type,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _parse_mtproto_link_from_rotate_stdout(stdout: str) -> str | None:
    """Ищет строку tg://proxy или MTPROTO_LINK=tg://... в выводе скрипта ротации."""
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("MTPROTO_LINK="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val.startswith("tg://proxy"):
                return val
        if line.startswith("tg://proxy"):
            return line
    return None


def _build_proxy_rotate_failure_message(returncode: int, combined_output: str) -> str:
    """Формирует понятное сообщение об ошибке ротации MTProxy для владельца."""
    lower = combined_output.lower()
    port_conflict_markers = (
        "failed to bind host port",
        "address already in use",
        "0.0.0.0:443",
        ":443/tcp",
    )
    has_port_conflict = any(marker in lower for marker in port_conflict_markers)

    if has_port_conflict:
        return (
            "Скрипт ротации не смог запустить MTProxy на порту 443: порт уже занят на сервере.\n\n"
            "Это не ошибка парсинга ссылки — контейнер не стартовал из-за конфликта порта.\n\n"
            "Проверь на сервере Fornex, кто слушает 443:\n"
            "<code>docker ps --format \"table {{.Names}}\\t{{.Ports}}\"</code>\n"
            "<code>ss -ltnp | grep :443</code>\n\n"
            "После освобождения 443 повтори /proxy_rotate.\n\n"
            f"Код скрипта: {returncode}"
        )

    tail = combined_output[-3500:] if len(combined_output) > 3500 else combined_output
    return (
        f"Скрипт завершился с кодом {returncode}. Новую ссылку разобрать не удалось.\n\n"
        f"{tail}"
    )


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
    """Краткая инструкция по AmneziaWG для Европы (ПК, iOS, Android)."""
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
        "3. ПК: импортируй .conf в AmneziaVPN.\n"
        "4. iPhone/iPad: сохрани .conf → Файлы → долгое нажатие → Поделиться → AmneziaWG.\n"
        "5. Android: AmneziaVPN из Google Play → Импорт из файла или буфера обмена.\n\n"
        "Подробнее: команда /instruction."
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
    # Инициализируем SQLite DB и мигрируем users.json
    init_db(whitelist_seed=config.telegram_id_whitelist or [])

    bot = telebot.TeleBot(config.bot_token, parse_mode="HTML")
    admin_id = config.admin_id

    def safe_reply(message: types.Message, text: str, reply_markup=None) -> bool:
        """Отправляет ответ; при ошибке логирует и возвращает False.
        Если reply_markup не задан, автоматически использует _back_markup из message (если есть).
        """
        effective_markup = reply_markup or getattr(message, "_back_markup", None)
        try:
            bot.reply_to(message, text, reply_markup=effective_markup)
            return True
        except Exception as e:  # noqa: BLE001
            logger.exception("Ошибка при отправке ответа: %s", e)
            return False

    def _back_to_menu_markup() -> types.InlineKeyboardMarkup:
        """Inline-клавиатура с одной кнопкой возврата в главное меню."""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        return markup

    # Состояние ожидания ввода ID пользователя от администратора (для add_user через кнопку)
    _pending_add_user: set[int] = set()

    # Email-link flow: {telegram_id: {"state": "email"|"otp", "email": str}}
    _email_link_state: dict[int, dict] = {}

    def _is_authorized(telegram_id: int) -> bool:
        """Пользователь разрешён, если: в whitelist ИЛИ есть запись в базе и active=True."""
        if db_is_whitelisted(telegram_id):
            return True
        user = find_user(telegram_id)
        return user is not None and user.active

    def _needs_email_link(telegram_id: int) -> bool:
        """True если пользователь авторизован, но email ещё не привязан."""
        user = find_user(telegram_id)
        return user is not None and not user.email_verified and not db_is_whitelisted(telegram_id)

    def _send_main_menu(chat_id: int, from_user, *, new_message: bool = True) -> None:
        """Отправляет или редактирует главное меню."""
        if not from_user:
            return
        uid = from_user.id
        recovery_url = getattr(config, "vpn_recovery_url", None) or "http://185.21.8.91:5001/recovery"
        authorized = _is_authorized(uid)

        if not authorized:
            text = (
                "Привет! Это VPN-бот. 🔐\n\n"
                "Доступ открыт для всех — зарегистрируйся через email.\n\n"
                f"🌐 Также можно получить конфиг на сайте: {recovery_url}"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("📧 Войти по email", callback_data="email_register")
            )
        else:
            text = (
                "Привет! Это VPN-бот. 🔐\n\n"
                f"🌐 Сайт (если Telegram не работает): {recovery_url}"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📲 Получить VPN", callback_data="menu_get_config"),
                types.InlineKeyboardButton("🔄 Обновить конфиг", callback_data="menu_regen"),
                types.InlineKeyboardButton("📖 Инструкции", callback_data="menu_instruction"),
                types.InlineKeyboardButton("📊 Мой статус", callback_data="menu_status"),
                types.InlineKeyboardButton("📡 Прокси Telegram", callback_data="menu_proxy"),
                types.InlineKeyboardButton("📱 Мобильный VPN", callback_data="menu_mobile_vpn"),
            )
            if is_owner(uid, admin_id):
                markup.add(types.InlineKeyboardButton("⚙️ Администратор", callback_data="admin_panel"))
            elif _needs_email_link(uid):
                markup.add(types.InlineKeyboardButton("🔗 Привязать email", callback_data="email_link"))

        if new_message:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        else:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        _send_main_menu(message.chat.id, message.from_user)

        # Автоматически регистрируем владельца как пользователя (owner)
        if message.from_user.id == admin_id:
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

    def _deliver_config(
        message: types.Message,
        config_text: str,
        filename: str,
        platform: str,
        success_text: str,
    ) -> None:
        """
        Доставляет конфиг в зависимости от платформы.
        pc    → .conf файл (стандартный импорт в AmneziaVPN/AmneziaWG)
        ios   → конфиг текстом в <code> блоке (копировать → AmneziaWG → Импорт из буфера)
        android → vpn:// deep link (тап → AmneziaVPN импортирует автоматически)
        """
        import html as _html
        chat_id = message.chat.id
        if platform == "android":
            vpn_link = generate_vpn_url(config_text)
            bot.send_message(chat_id, success_text, parse_mode="HTML")
            bot.send_message(
                chat_id,
                "👇 Нажми на ссылку — <b>AmneziaVPN</b> откроет и импортирует конфиг:",
                parse_mode="HTML",
            )
            bot.send_message(chat_id, vpn_link, parse_mode=None)
        elif platform == "ios":
            _send_config_file(chat_id, config_text, filename)
            bot.send_message(
                chat_id,
                success_text + "\n\n"
                "📂 Нажми на файл → иконка «Поделиться» → выбери <b>AmneziaWG</b> → «Создать из файла».",
                parse_mode="HTML",
            )
        else:  # pc
            _send_config_file(chat_id, config_text, filename)
            bot.send_message(chat_id, success_text, parse_mode="HTML")

    def _deliver_vless_link(message: types.Message, vless_link: str, success_text: str) -> None:
        """Отправляет vless:// ссылку пользователю: сначала сообщение, потом ссылка в code-блоке."""
        chat_id = message.chat.id
        bot.send_message(chat_id, success_text, parse_mode="HTML")
        bot.send_message(chat_id, f"<code>{vless_link}</code>", parse_mode="HTML")

    def _show_platform_keyboard(chat_id: int, action: str) -> None:
        """Отправляет клавиатуру выбора платформы перед выдачей конфига."""
        label = "получения" if action == "get_config" else "обновления"
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("💻 ПК", callback_data=f"{action}_pc"),
            types.InlineKeyboardButton("🍎 iOS", callback_data=f"{action}_ios"),
            types.InlineKeyboardButton("🤖 Android", callback_data=f"{action}_android"),
        )
        markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        bot.send_message(
            chat_id,
            f"📲 Выбери устройство для {label} VPN:",
            reply_markup=markup,
        )

    def _do_get_config(message: types.Message, android_safe: bool, platform: str = "pc") -> None:
        """
        Self-service: выдача конфига.
        platform: "pc" | "ios" | "android" — способ доставки.
        android_safe=True — один DNS (обход ErrorCode 1000 на Android).
        """
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not _is_authorized(message.from_user.id):
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📧 Войти по email", callback_data="email_register"))
            safe_reply(message, "У тебя пока нет доступа.\nЗарегистрируйся по email:", reply_markup=markup)
            return
        user = find_user(message.from_user.id)

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

        # Логический слот: rus1/rus2/eu1/eu2 (legacy main → rus1)
        preferred_server_id = normalize_preferred_server_id(user.preferred_server_id)

        try:
            # Ищем peer на выбранном слоте и платформе
            peer_on_preferred = find_peer_by_telegram_id(
                telegram_id, server_id=preferred_server_id, platform=platform
            )

            # Также проверяем, есть ли peer на любом другом сервере (для информации при переключении)
            peer_any = find_peer_by_telegram_id(telegram_id, server_id=None)
            
            if peer_on_preferred and peer_on_preferred.active:
                # На eu1 проверяем совпадение типа профиля с выбором пользователя
                preferred_pt = getattr(user, "preferred_profile_type", None) if preferred_server_id == "eu1" else None
                current_pt = getattr(peer_on_preferred, "profile_type", None)
                if preferred_server_id == "eu1" and preferred_pt and current_pt != preferred_pt:
                    # Пользователь выбрал другой тип профиля — пересоздаём peer с новым типом
                    peer, client_config = replace_peer_with_profile_type(
                        telegram_id, preferred_server_id, preferred_pt,
                        android_safe=android_safe, platform=platform,
                    )
                    pt = getattr(peer, "profile_type", None)
                    if pt == "vpn_gpt":
                        filename = f"wg_{peer.server_id}_gpt.conf"
                    elif pt == "unified":
                        filename = f"wg_{peer.server_id}_uni.conf"
                    else:
                        filename = f"wg_{peer.server_id}.conf"
                    servers_info = get_available_servers()
                    server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
                    profile_note = (
                        "\n\n🟣 <b>Профиль: Универсальный</b>\n"
                        "Один профиль для всего: обычные сайты напрямую, ChatGPT и заблокированные — через Shadowsocks.\n"
                    ) if pt == "unified" else (
                        "\n\n🟢 <b>Профиль: VPN+GPT</b>\n"
                        "HTTP/HTTPS трафик идёт через Shadowsocks для обхода блокировок.\n"
                    ) if pt == "vpn_gpt" else "\n\n🔵 <b>Профиль: Обычный VPN</b>\n"
                    _deliver_config(
                        message, client_config, filename, platform,
                        f"✅ Профиль переключён на сервере <b>{server_name}</b>.\n"
                        f"IP в VPN-сети: <code>{peer.wg_ip}</code>"
                        f"{profile_note}",
                    )
                    return
                # Peer уже существует, тип профиля совпадает — просто сообщаем
                servers_info = get_available_servers()
                server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
                # Европа (eu1/eu2) — AmneziaWG
                platform_label = {"pc": "ПК", "ios": "iOS", "android": "Android"}.get(platform, platform)
                if preferred_server_id == "eu1":
                    # Пользователь уже имеет VLESS-доступ — отдаём существующую ссылку
                    try:
                        vless_link = create_vless_client_for_user(telegram_id)
                        _deliver_vless_link(
                            message, vless_link,
                            f"Для тебя уже создан VPN‑доступ на сервере <b>{server_name}</b> (VLESS+REALITY).\n"
                            "Вот твоя ссылка — импортируй в Hiddify / FoXray / V2Box / v2rayNG.\n"
                            "Если хочешь новую — используй /regen.",
                        )
                    except WireGuardError as exc:
                        logger.exception("Ошибка получения VLESS для %s: %s", telegram_id, exc)
                        safe_reply(message, "Не удалось получить ссылку. Попробуй /regen или напиши владельцу.")
                else:
                    safe_reply(
                        message,
                        f"Для тебя уже создан VPN‑доступ на сервере <b>{server_name}</b> ({preferred_server_id}) "
                        f"для <b>{platform_label}</b>.\n"
                        "Если у тебя уже импортирован конфиг и всё работает — ничего делать не нужно.\n"
                        "Если потерял конфиг или нужно обновить, используй /regen.",
                    )
                return
            
            # Если есть peer на другом слоте, но выбран новый — создаём peer на новом слоте (старые записи не трогаем)
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

            # Европа (eu1): VLESS+REALITY
            if preferred_server_id == "eu1":
                try:
                    vless_link = create_vless_client_for_user(telegram_id)
                    _deliver_vless_link(
                        message, vless_link,
                        "✅ Создан VPN‑доступ на сервере <b>Европа</b> (VLESS+REALITY)\n"
                        "Работает на всех платформах: iOS, Android, ПК.",
                    )
                except WireGuardError as exc:
                    logger.exception("Ошибка VLESS для %s: %s", telegram_id, exc)
                    safe_reply(
                        message,
                        "Не удалось создать VPN‑доступ. Попробуй позже или напиши владельцу.",
                    )
                return

            # WireGuard: rus1/rus2 (eu1/eu2 обработаны выше как AmneziaWG)
            profile_type = None

            # Создаём новый peer на выбранном слоте (rus1/rus2)
            peer, client_config = create_peer_and_config_for_user(
                telegram_id,
                server_id=preferred_server_id,
                profile_type=profile_type,
                android_safe=android_safe,
                platform=platform,
            )

        except WireGuardError as exc:
            logger.exception("Ошибка при обработке /get_config для %s: %s", telegram_id, exc)
            safe_reply(
                message,
                "Произошла ошибка при подготовке конфига WireGuard.\n"
                "Попробуй позже или сообщи владельцу, чтобы он проверил логи бота.",
            )
            return

        pt = getattr(peer, "profile_type", None)
        if pt == "vpn_gpt":
            filename = f"wg_{peer.server_id}_gpt.conf"
        elif pt == "unified":
            filename = f"wg_{peer.server_id}_uni.conf"
        else:
            filename = f"wg_{peer.server_id}.conf"

        servers_info = get_available_servers()
        server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
        _deliver_config(
            message, client_config, filename, platform,
            f"✅ Создан новый VPN‑доступ на сервере <b>{server_name}</b>\n"
            f"IP в VPN-сети: <code>{peer.wg_ip}</code>",
        )

    @bot.message_handler(commands=["get_config"])
    def cmd_get_config(message: types.Message) -> None:  # type: ignore[override]
        _show_platform_keyboard(message.chat.id, "get_config")

    def _do_regen(message: types.Message, android_safe: bool, platform: str = "pc") -> None:
        """Регенерация конфига. platform: "pc" | "ios" | "android"."""
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not _is_authorized(message.from_user.id):
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📧 Войти по email", callback_data="email_register"))
            safe_reply(message, "У тебя пока нет доступа.\nЗарегистрируйся по email:", reply_markup=markup)
            return
        user = find_user(message.from_user.id)

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
            preferred_server_id = normalize_preferred_server_id(user.preferred_server_id)

            # Европа (eu1): VLESS+REALITY
            if preferred_server_id == "eu1":
                try:
                    vless_link = regenerate_vless_client_for_user(telegram_id)
                    _deliver_vless_link(
                        message, vless_link,
                        "✅ VPN‑доступ обновлён на сервере <b>Европа</b> (VLESS+REALITY)\n"
                        "⚠️ Старая ссылка больше не работает — импортируй новую.",
                    )
                except WireGuardError as exc:
                    logger.exception("Ошибка регенерации VLESS для %s: %s", telegram_id, exc)
                    safe_reply(
                        message,
                        f"Не удалось обновить VPN‑доступ: {exc}\n"
                        "Попробуй позже или напиши владельцу.",
                    )
                return

            preferred_pt = getattr(user, "preferred_profile_type", None) if preferred_server_id == "eu1" else None
            existing_peer = find_peer_by_telegram_id(
                telegram_id, server_id=preferred_server_id, platform=platform
            )
            # Если на eu1 пользователь выбрал другой тип профиля — пересоздаём peer с новым типом и IP из нужного пула
            if (
                preferred_server_id == "eu1"
                and preferred_pt
                and existing_peer
                and getattr(existing_peer, "profile_type", None) != preferred_pt
            ):
                peer, client_config = replace_peer_with_profile_type(
                    telegram_id, preferred_server_id, preferred_pt,
                    android_safe=android_safe, platform=platform,
                )
            else:
                # Регенерируем peer (тот же IP/профиль, новые ключи)
                peer, client_config = regenerate_peer_and_config_for_user(
                    telegram_id, server_id=preferred_server_id,
                    android_safe=android_safe, platform=platform,
                )
            
        except WireGuardError as exc:
            logger.exception("Ошибка при регенерации peer для %s: %s", telegram_id, exc)
            safe_reply(
                message,
                f"Не удалось регенерировать конфиг: {exc}\n"
                "Убедись, что у тебя уже создан VPN‑доступ (используй /get_config для создания).",
            )
            return
        
        pt = getattr(peer, "profile_type", None)
        if pt == "vpn_gpt":
            filename = f"wg_{peer.server_id}_gpt.conf"
        elif pt == "unified":
            filename = f"wg_{peer.server_id}_uni.conf"
        else:
            filename = f"wg_{peer.server_id}.conf"

        servers_info = get_available_servers()
        server_name = servers_info.get(peer.server_id, {}).get("name", peer.server_id)
        _deliver_config(
            message, client_config, filename, platform,
            f"✅ Конфиг регенерирован на сервере <b>{server_name}</b>.\n"
            f"IP в VPN-сети: <code>{peer.wg_ip}</code>\n\n"
            "⚠️ Старый конфиг больше не работает — импортируй новый.",
        )

    @bot.message_handler(commands=["regen"])
    def cmd_regen(message: types.Message) -> None:  # type: ignore[override]
        _show_platform_keyboard(message.chat.id, "regen")

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

    # ──────────────────────────────────────────────────────────────
    # Callbacks: главное меню (/start кнопки)
    # ──────────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
    def callback_main_menu(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Обрабатывает нажатия кнопок главного меню /start."""
        bot.answer_callback_query(call.id)
        # call.message.from_user — это бот, а не пользователь.
        # Подставляем реального пользователя, нажавшего кнопку.
        call.message.from_user = call.from_user
        # Все safe_reply внутри команд автоматически добавят кнопку "« Главное меню"
        call.message._back_markup = _back_to_menu_markup()
        action = call.data
        if action == "menu_get_config":
            _show_platform_keyboard(call.message.chat.id, "get_config")
        elif action == "menu_regen":
            _show_platform_keyboard(call.message.chat.id, "regen")
        elif action == "menu_instruction":
            cmd_instruction(call.message)
        elif action == "menu_proxy":
            cmd_proxy(call.message)
        elif action == "menu_mobile_vpn":
            cmd_mobile_vpn(call.message)
        elif action == "menu_status":
            cmd_status(call.message)

    # ──────────────────────────────────────────────────────────────
    # Callbacks: выбор платформы для получения / обновления конфига
    # ──────────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data in (
        "get_config_pc", "get_config_ios", "get_config_android",
        "regen_pc", "regen_ios", "regen_android",
    ))
    def callback_platform_select(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        call.message.from_user = call.from_user
        action, platform = call.data.rsplit("_", 1)
        android_safe = (platform == "android")
        if action == "get_config":
            _do_get_config(call.message, android_safe=android_safe, platform=platform)
        else:
            _do_regen(call.message, android_safe=android_safe, platform=platform)

    # ──────────────────────────────────────────────────────────────
    # Email-авторизация и привязка
    # ──────────────────────────────────────────────────────────────

    def _start_email_flow(chat_id: int, uid: int, mode: str) -> None:
        """Запускает email-flow (register или link). mode: 'register' | 'link'."""
        _email_link_state[uid] = {"state": "email", "mode": mode}
        text = (
            "Введи свой email — отправим код подтверждения:"
            if mode == "register"
            else "Введи email, который хочешь привязать к аккаунту:"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✕ Отмена", callback_data="email_cancel"))
        bot.send_message(chat_id, text, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data in ("email_register", "email_link"))
    def callback_email_start(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        mode = "link" if call.data == "email_link" else "register"
        _start_email_flow(call.message.chat.id, call.from_user.id, mode)

    @bot.callback_query_handler(func=lambda call: call.data == "email_cancel")
    def callback_email_cancel(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if call.from_user:
            _email_link_state.pop(call.from_user.id, None)
        bot.send_message(call.message.chat.id, "Отменено.")

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _email_link_state
    )
    def handle_email_flow(message: types.Message) -> None:  # type: ignore[override]
        """Обрабатывает ввод email и OTP-кода в рамках email-flow."""
        if not message.from_user:
            return
        uid = message.from_user.id
        state_data = _email_link_state.get(uid)
        if not state_data:
            return

        state = state_data.get("state")
        text = (message.text or "").strip()

        if state == "email":
            # Проверяем минимальный формат email
            if "@" not in text or "." not in text.split("@")[-1]:
                bot.reply_to(message, "Похоже, это не email. Попробуй ещё раз:")
                return

            email = text.lower()
            if not config.resend_api_key:
                bot.reply_to(
                    message,
                    "Email-авторизация не настроена на сервере. Обратись к владельцу.",
                )
                _email_link_state.pop(uid, None)
                return

            code = generate_otp()
            db_create_otp(email, code)

            sent = send_otp_email(
                to_email=email,
                code=code,
                api_key=config.resend_api_key,
                from_email=config.resend_from_email,
            )
            if not sent:
                bot.reply_to(
                    message,
                    "Не удалось отправить письмо. Проверь адрес или попробуй позже.",
                )
                return

            _email_link_state[uid] = {"state": "otp", "mode": state_data["mode"], "email": email}
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✕ Отмена", callback_data="email_cancel"))
            bot.reply_to(
                message,
                f"Код отправлен на <b>{email}</b>.\nВведи 6-значный код из письма:",
                reply_markup=markup,
            )

        elif state == "otp":
            email = state_data.get("email", "")
            mode = state_data.get("mode", "register")
            code = text.replace(" ", "")

            if not db_verify_otp(email, code):
                bot.reply_to(message, "Неверный или просроченный код. Попробуй ещё раз:")
                return

            _email_link_state.pop(uid, None)

            # Создаём или обновляем пользователя в БД
            from .database import db_upsert_user
            existing = find_user(uid)
            if existing:
                existing.email = email
                existing.email_verified = True
                upsert_user(existing)
            else:
                # Новый пользователь через email
                db_upsert_user({
                    "telegram_id": uid,
                    "email": email,
                    "username": message.from_user.username,
                    "role": "user",
                    "active": True,
                    "preferred_server_id": "eu1",
                    "email_verified": True,
                })

            action_text = "Email привязан" if mode == "link" else "Регистрация завершена"
            bot.reply_to(
                message,
                f"✅ {action_text}!\n<b>{email}</b> подтверждён.\n\nТеперь ты можешь пользоваться VPN.",
            )
            # Показываем главное меню
            _send_main_menu(message.chat.id, message.from_user)

    # ──────────────────────────────────────────────────────────────
    # Callbacks: админ-панель
    # ──────────────────────────────────────────────────────────────

    def _send_users_list(chat_id: int) -> None:
        """Отправляет список пользователей в указанный чат."""
        try:
            users = get_all_users()
        except Exception as e:  # noqa: BLE001
            bot.send_message(chat_id, f"Ошибка при чтении списка: {e!r}", parse_mode="HTML")
            return
        if not users:
            bot.send_message(chat_id, "Пока нет зарегистрированных пользователей.")
            return
        lines = ["<b>Пользователи VPN:</b>"]
        for u in users:
            role_label = "👑 owner" if u.role == "owner" else "user"
            status_label = "✅ active" if u.active else "⛔ disabled"
            uname = f"@{u.username}" if u.username else "(без username)"
            lines.append(f"- <code>{u.telegram_id}</code> {uname} — {role_label}, {status_label}")
        bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

    def _do_proxy_rotate(chat_id: int) -> None:
        """Выполняет ротацию MTProxy и отправляет результат в указанный чат."""
        script = config.mtproxy_rotate_script
        if not script:
            bot.send_message(
                chat_id,
                "Ротация не настроена: добавь MTPROXY_ROTATE_SCRIPT в env_vars.txt.",
                parse_mode="HTML",
            )
            return
        script_path = Path(script).expanduser()
        if not script_path.is_file():
            bot.send_message(chat_id, f"Файл скрипта не найден: <code>{script_path}</code>", parse_mode="HTML")
            return
        try:
            argv = ["/bin/bash", str(script_path)] if script_path.suffix == ".sh" else [str(script_path)]
            completed = subprocess.run(  # noqa: S603
                argv, capture_output=True, text=True, timeout=180, check=False,
                env=environment_for_mtproxy_rotate(config.base_dir),
            )
        except subprocess.TimeoutExpired:
            bot.send_message(chat_id, "Ротация: тайм-аут 180 с. Проверь Docker и логи.")
            return
        except Exception as e:  # noqa: BLE001
            bot.send_message(chat_id, f"Не удалось запустить скрипт: {e}")
            return
        link = _parse_mtproto_link_from_rotate_stdout(completed.stdout or "")
        if completed.returncode != 0 or not link:
            combined = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
            bot.send_message(chat_id, _build_proxy_rotate_failure_message(completed.returncode, combined), parse_mode="HTML")
            return
        data_dir = config.base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        override_path = data_dir / "mtproto_proxy_link.txt"
        try:
            override_path.write_text(link.strip() + "\n", encoding="utf-8")
        except OSError as e:
            bot.send_message(chat_id, f"Ссылка получена, но не записана в файл ({e}). Сохрани вручную:\n\n{link}")
            return
        bot.send_message(
            chat_id,
            "✅ MTProxy пересобран. Новая ссылка — следующим сообщением.\n\n"
            "Команда /proxy уже отдаёт эту ссылку всем.",
            parse_mode="HTML",
        )
        bot.send_message(chat_id, link, parse_mode=None)

    def _admin_panel_markup() -> types.InlineKeyboardMarkup:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
            types.InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
            types.InlineKeyboardButton("🔄 Ротация прокси", callback_data="admin_proxy_rotate"),
            types.InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user"),
            types.InlineKeyboardButton("🔓 Whitelist ID", callback_data="admin_whitelist"),
            types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        )
        markup.add(types.InlineKeyboardButton("« Назад", callback_data="admin_back"))
        return markup

    @bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
    def callback_admin_panel(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Показывает админ-панель (только для владельца)."""
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            "⚙️ <b>Панель администратора</b>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=_admin_panel_markup(),
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_back")
    def callback_admin_back(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Возврат из админ-панели в главное меню."""
        bot.answer_callback_query(call.id)
        _send_main_menu(call.message.chat.id, call.from_user)

    @bot.callback_query_handler(func=lambda call: call.data == "go_main_menu")
    def callback_go_main_menu(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Отправляет главное меню новым сообщением (возврат из любого экрана)."""
        bot.answer_callback_query(call.id)
        _send_main_menu(call.message.chat.id, call.from_user)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
    def callback_admin_stats(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        # Переиспользуем логику /stats
        try:
            users = get_all_users()
            peers = get_all_peers()
        except Exception as e:  # noqa: BLE001
            bot.send_message(call.message.chat.id, f"Ошибка при чтении данных: {e!r}", parse_mode="HTML")
            return
        users_total = len(users)
        users_active = sum(1 for u in users if u.active)
        peers_active = sum(1 for p in peers if p.active)
        by_server: dict[str, int] = {}
        for p in peers:
            if p.active:
                by_server[p.server_id] = by_server.get(p.server_id, 0) + 1
        servers_info = get_available_servers()
        server_lines = [
            f"  • {servers_info.get(sid, {}).get('name', sid)} ({sid}): {count}"
            for sid, count in sorted(by_server.items())
        ]
        text = (
            "<b>📊 Сводка VPN</b>\n\n"
            f"<b>Пользователи:</b> {users_active} активных из {users_total}\n"
            f"<b>Активных конфигов:</b> {peers_active}\n\n"
            "<b>По серверам:</b>\n"
            + ("\n".join(server_lines) if server_lines else "  — пока нет")
        )
        bot.send_message(call.message.chat.id, text, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_users")
    def callback_admin_users(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        # Переиспользуем логику /users — отправляем как новое сообщение
        _send_users_list(call.message.chat.id)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_proxy_rotate")
    def callback_admin_proxy_rotate(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id, "Запускаю ротацию...")
        # Создаём фиктивный message-объект для переиспользования cmd_proxy_rotate
        # Проще отправить результат напрямую через send_message
        _do_proxy_rotate(call.message.chat.id)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_add_user")
    def callback_admin_add_user(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        _pending_add_user.add(call.from_user.id)
        bot.send_message(
            call.message.chat.id,
            "➕ Напиши Telegram ID или @username пользователя, которого хочешь добавить:",
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_whitelist")
    def callback_admin_whitelist(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Показывает текущий whitelist и кнопки управления."""
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        ids = db_get_whitelist()
        if ids:
            lines = [f"<code>{tid}</code>" for tid in ids]
            text = "🔓 <b>Whitelist (без email-авторизации):</b>\n\n" + "\n".join(lines)
        else:
            text = "🔓 <b>Whitelist пуст.</b>\n\nID в этом списке могут пользоваться ботом без email."
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("➕ Добавить ID", callback_data="admin_whitelist_add"),
            types.InlineKeyboardButton("➖ Удалить ID", callback_data="admin_whitelist_remove"),
        )
        markup.add(types.InlineKeyboardButton("« Назад", callback_data="admin_panel"))
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=markup)

    _pending_whitelist_add: set[int] = set()
    _pending_whitelist_remove: set[int] = set()

    @bot.callback_query_handler(func=lambda call: call.data == "admin_whitelist_add")
    def callback_whitelist_add_start(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        _pending_whitelist_add.add(call.from_user.id)
        bot.send_message(call.message.chat.id, "Введи Telegram ID для добавления в whitelist:")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_whitelist_remove")
    def callback_whitelist_remove_start(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        _pending_whitelist_remove.add(call.from_user.id)
        bot.send_message(call.message.chat.id, "Введи Telegram ID для удаления из whitelist:")

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _pending_whitelist_add
    )
    def handle_whitelist_add(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        _pending_whitelist_add.discard(message.from_user.id)
        text = (message.text or "").strip()
        try:
            tid = int(text)
        except ValueError:
            bot.reply_to(message, "Некорректный ID. Должно быть число.")
            return
        db_add_to_whitelist(tid, note=f"added by owner")
        bot.reply_to(message, f"✅ <code>{tid}</code> добавлен в whitelist.")

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _pending_whitelist_remove
    )
    def handle_whitelist_remove(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        _pending_whitelist_remove.discard(message.from_user.id)
        text = (message.text or "").strip()
        try:
            tid = int(text)
        except ValueError:
            bot.reply_to(message, "Некорректный ID. Должно быть число.")
            return
        db_remove_from_whitelist(tid)
        bot.reply_to(message, f"✅ <code>{tid}</code> удалён из whitelist.")

    @bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
    def callback_admin_broadcast(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Да, разослать", callback_data="admin_broadcast_confirm"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="admin_panel"),
        )
        bot.edit_message_text(
            "⚠️ <b>Разослать уведомление всем активным пользователям?</b>\n\n"
            "Это отправит сообщение о проблемах с VPN каждому пользователю в базе.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast_confirm")
    def callback_admin_broadcast_confirm(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id, "Рассылка запущена...")
        bot.edit_message_text(
            "📢 Рассылка запущена...",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
        )
        try:
            users = get_all_users()
        except Exception as e:  # noqa: BLE001
            bot.send_message(call.message.chat.id, f"Ошибка при чтении пользователей: {e!r}")
            return
        recovery_url = getattr(config, "vpn_recovery_url", None) or "http://185.21.8.91:5001/recovery"
        broadcast_text = (
            BROADCAST_VPN_ISSUE_TEXT
            + "\n\nЕсли Telegram снова не отвечает — восстановление доступно на сайте.\n"
            + f"Ссылка: {recovery_url}\n"
            + "На странице введите свой Telegram ID и нажмите «Восстановить VPN (конфиг)»."
        )
        sent = 0
        failed = 0
        for u in users:
            try:
                bot.send_message(u.telegram_id, broadcast_text, parse_mode="HTML")
                sent += 1
                time.sleep(0.05)
            except Exception as e:  # noqa: BLE001
                logger.warning("Broadcast: не отправлено %s: %s", u.telegram_id, e)
                failed += 1
        bot.send_message(
            call.message.chat.id,
            f"✅ Рассылка завершена: отправлено <b>{sent}</b>, не доставлено <b>{failed}</b>.",
            parse_mode="HTML",
        )

    # ──────────────────────────────────────────────────────────────
    # Обработчик текстовых сообщений: ввод пользователя для add_user
    # ──────────────────────────────────────────────────────────────

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _pending_add_user
    )
    def handle_pending_add_user(message: types.Message) -> None:  # type: ignore[override]
        """Получает ID/username от владельца после нажатия кнопки ➕ Добавить пользователя."""
        if not message.from_user:
            return
        _pending_add_user.discard(message.from_user.id)
        # Подставляем аргумент и вызываем существующую логику /add_user
        message.text = f"/add_user {message.text}"
        cmd_add_user(message)

    @bot.message_handler(commands=["status"])
    def cmd_status(message: types.Message) -> None:  # type: ignore[override]
        """Показывает статус доступа пользователя."""
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not _is_authorized(message.from_user.id):
            safe_reply(message, "Нет доступа. Войди по email через /start.")
            return
        user = find_user(message.from_user.id)
        
        preferred_server_id = normalize_preferred_server_id(user.preferred_server_id)
        servers_info = get_available_servers()
        preferred_server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)

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
        """Показывает выбор платформы для инструкции по подключению."""
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("📱 iOS", callback_data="instr_ios"),
            types.InlineKeyboardButton("🤖 Android", callback_data="instr_android"),
            types.InlineKeyboardButton("💻 Windows", callback_data="instr_windows"),
        )
        markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        bot.reply_to(
            message,
            "📖 <b>Инструкции по подключению</b>\n\nВыбери своё устройство:",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("instr_"))
    def callback_instruction_platform(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Отправляет инструкцию для выбранной платформы."""
        bot.answer_callback_query(call.id)
        platform = call.data.replace("instr_", "")
        name_map = {"ios": "ios", "android": "android", "windows": "windows"}
        file_key = name_map.get(platform)
        if not file_key:
            bot.send_message(call.message.chat.id, "Неизвестная платформа.")
            return
        instr = _load_instruction_text(config.base_dir, file_key)
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("📱 iOS", callback_data="instr_ios"),
            types.InlineKeyboardButton("🤖 Android", callback_data="instr_android"),
            types.InlineKeyboardButton("💻 Windows", callback_data="instr_windows"),
        )
        markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        bot.send_message(call.message.chat.id, instr, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(commands=["proxy"])
    def cmd_proxy(message: types.Message) -> None:  # type: ignore[override]
        """Отправляет ссылку MTProto-прокси для Telegram и краткую инструкцию."""
        fresh = load_config()
        link = get_effective_mtproto_proxy_link(fresh)
        if link:
            instr = _load_instruction_text(fresh.base_dir, "mtproto")
            safe_reply(
                message,
                f"{link}\n\n{instr}",
            )
        else:
            safe_reply(
                message,
                "Ссылка на прокси для Telegram не настроена. Обратись к владельцу бота.",
            )

    @bot.message_handler(commands=["proxy_rotate"])
    def cmd_proxy_rotate(message: types.Message) -> None:  # type: ignore[override]
        """
        Владелец: запускает скрипт ротации MTProxy (новый секрет + контейнер), сохраняет ссылку в data/mtproto_proxy_link.txt.
        Требует MTPROXY_ROTATE_SCRIPT в env и Linux/Docker на хосте бота.
        """
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not is_owner(message.from_user.id, admin_id):
            safe_reply(message, "Команда только для владельца бота.")
            return

        script = config.mtproxy_rotate_script
        if not script:
            safe_reply(
                message,
                "Ротация не настроена: добавь в env_vars.txt на сервере бота переменную "
                "MTPROXY_ROTATE_SCRIPT (путь к скрипту). Пример: docs/scripts/mtproxy-faketls-rotate.sh.example\n\n"
                "Полная инструкция: docs/mtproxy-proxy-rotation.md",
            )
            return

        script_path = Path(script).expanduser()
        if not script_path.is_file():
            safe_reply(message, f"Файл скрипта не найден: <code>{script_path}</code>")
            return

        try:
            argv = ["/bin/bash", str(script_path)] if script_path.suffix == ".sh" else [str(script_path)]
            completed = subprocess.run(  # noqa: S603
                argv,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                env=environment_for_mtproxy_rotate(config.base_dir),
            )
        except subprocess.TimeoutExpired:
            safe_reply(message, "Ротация: тайм-аут 180 с. Проверь Docker и логи на сервере бота.")
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("proxy_rotate subprocess: %s", e)
            safe_reply(message, f"Не удалось запустить скрипт: {e}")
            return

        link = _parse_mtproto_link_from_rotate_stdout(completed.stdout or "")
        combined = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()

        if completed.returncode != 0 or not link:
            safe_reply(
                message,
                _build_proxy_rotate_failure_message(completed.returncode, combined),
            )
            return

        data_dir = config.base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        override_path = data_dir / "mtproto_proxy_link.txt"
        try:
            override_path.write_text(link.strip() + "\n", encoding="utf-8")
        except OSError as e:
            logger.exception("proxy_rotate write override: %s", e)
            try:
                bot.send_message(
                    message.chat.id,
                    f"Ссылка получена, но не записана в файл ({e}). Сохрани вручную:\n\n{link}",
                    parse_mode=None,
                )
            except Exception:  # noqa: BLE001
                safe_reply(message, f"Ссылка: {link}")
            return

        safe_reply(
            message,
            "✅ MTProxy пересобран. Новая ссылка — <b>следующим сообщением</b> (открой в Telegram).\n\n"
            "Команда /proxy уже отдаёт эту ссылку всем. Старый прокси в клиенте с прежним секретом перестанет работать — "
            "можно добавить новый рядом, не удаляя старый.",
        )
        try:
            bot.send_message(message.chat.id, link, parse_mode=None)
        except Exception as e:  # noqa: BLE001
            logger.exception("proxy_rotate send link: %s", e)

    @bot.message_handler(commands=["mobile_vpn"])
    def cmd_mobile_vpn(message: types.Message) -> None:  # type: ignore[override]
        """
        Резервный доступ через VLESS+REALITY (TCP) для мобильных сетей.
        Ссылка отправляется вторым сообщением без HTML, чтобы сохранить символы & в query string.
        """
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return

        if not _is_authorized(message.from_user.id):
            safe_reply(message, "Нет доступа. Войди по email через /start.")
            return

        url = config.vless_reality_share_url
        if not url:
            safe_reply(
                message,
                "Резервный мобильный профиль (VLESS+REALITY) пока не настроен на сервере бота.\n"
                "Напиши владельцу или используй AmneziaWG по Wi‑Fi: /get_config после выбора Европы в /server.",
            )
            return

        instr = _load_instruction_text(config.base_dir, "vless_reality")
        safe_reply(message, instr)
        try:
            import html as _html
            safe_url = _html.escape(url)
            bot.send_message(message.chat.id, f"<code>{safe_url}</code>", parse_mode="HTML")
        except Exception as e:  # noqa: BLE001
            logger.exception("Не удалось отправить VLESS ссылку: %s", e)
            safe_reply(
                message,
                "Не удалось отправить ссылку. Напиши владельцу.",
            )

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

    # Базовый текст уведомления о проблеме VPN и решении через /regen (рассылается по /broadcast)
    BROADCAST_VPN_ISSUE_TEXT = (
        "⚠️ <b>В данный момент наблюдается проблема с VPN.</b>\n\n"
        "Если она затронула вас и у вас появилась ошибка «Не удалось установить соединение», "
        "то необходимо ввести команду /regen, чтобы бот выдал новый конфиг.\n\n"
        "Старый конфиг удалите и замените новым."
    )

    @bot.message_handler(commands=["broadcast"])
    def cmd_broadcast(message: types.Message) -> None:  # type: ignore[override]
        """
        Для владельца: отправить всем пользователям уведомление о проблеме VPN и решении через /regen.
        """
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not is_owner(message.from_user.id, admin_id):
            safe_reply(message, "Эта команда доступна только владельцу VPN.")
            return

        # Временно отключаем рассылку, чтобы команда ничего не отправляла.
        # Увключить обратно можно будет отдельным коммитом.
        safe_reply(message, "Команда /broadcast временно отключена (рассылки приостановлены).")
        return

        try:
            users = get_all_users()
        except Exception as e:  # noqa: BLE001
            logger.exception("Ошибка при чтении списка пользователей для рассылки: %s", e)
            safe_reply(message, "Произошла ошибка при чтении списка. Попробуй позже.")
            return

        if not users:
            safe_reply(message, "Нет зарегистрированных пользователей для рассылки.")
            return

        recovery_url = getattr(config, "vpn_recovery_url", None) or "http://185.21.8.91:5001/recovery"
        broadcast_text = (
            BROADCAST_VPN_ISSUE_TEXT
            + "\n\n"
            + "Если Telegram снова не отвечает — восстановление доступно на сайте.\n"
            + f"Ссылка: {recovery_url}\n"
            + "На странице введите свой Telegram ID и нажмите «Восстановить VPN (конфиг)»."
        )

        sent = 0
        failed = 0
        for u in users:
            try:
                bot.send_message(u.telegram_id, broadcast_text, parse_mode="HTML")
                sent += 1
                time.sleep(0.05)  # снижение риска rate limit от Telegram
            except Exception as e:  # noqa: BLE001
                logger.warning("Не удалось отправить broadcast пользователю %s: %s", u.telegram_id, e)
                failed += 1

        safe_reply(
            message,
            f"Рассылка завершена: отправлено {sent}, не доставлено {failed} (возможно, пользователь заблокировал бота).",
        )

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

