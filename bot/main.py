"""Telegram-бот VPN Kronos — хендлеры и UX.

НАВИГАЦИЯ (файл большой, ~4 тыс строк): грепай баннер «# ═══ §N» чтобы
прыгнуть в нужную секцию, не читая весь файл. Почти вся логика — внутри
main() как вложенные функции/хендлеры (замыкания над bot и состоянием).

  §0  Модульные хелперы (вне main): proxy-rotate, инструкции
  §1  Auth / меню / доступ
  §2  Онбординг / use_case / churn
  §3  Restore / реферал
  §4  /start
  §5  Доставка конфигов (AmneziaWG)
  §6  Профили / устройства
  §7  Email-флоу (регистрация/привязка)
  §8  Admin-панель (inline)
  §9  Команды: статус/ЛК/инструкции/proxy
  §10 Мобильный VLESS (под оператора)
  §11 Owner-команды / обслуживание
  §12 Платежи (Stars + donation-claim)
  §13 Support / helpdesk
  §14 Polling / bootstrap
"""

import io
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

import telebot
from telebot import types

from .config import (
    BotConfig,
    environment_for_mtproxy_rotate,
    get_effective_mtproto_proxy_link,
    load_config,
)
from . import tariffs
from . import churn
from .formatting import format_subscription_status
from .database import (
    db_list_devices,
    db_get_device,
    db_add_device,
    db_delete_device,
    db_count_devices,
    db_device_autoname,
    db_get_device_limit,
    db_set_use_case,
    db_get_use_case,
    db_is_test_used,
    db_get_trial_data_status,
    db_mark_test_used,
    db_users_by_segment,
    db_set_drop_reason,
    db_mark_churn_asked,
    db_append_drop_detail,
    db_add_to_whitelist,
    db_get_whitelist,
    db_is_whitelisted,
    db_remove_from_whitelist,
    db_create_otp,
    db_verify_otp,
    db_get_vless_creds,
    db_update_proxy_requested_at,
    db_update_vless_requested_at,
    db_get_or_create_vless_uuid,
    db_get_per_user_vless_uuid,
    db_record_payment,
    db_extend_subscription,
    db_bulk_extend_active,
    db_count_active_users,
    db_find_payment_by_external_id,
    db_apply_referral_bonus,
    db_set_referred_by,
    db_get_user_by_referral_code,
    db_get_claim_by_id,
    db_decide_claim,
    db_get_pending_claim,
    db_create_payment_claim,
    db_get_subscription,
    db_is_access_active,
    db_find_user_by_telegram_id,
    db_ensure_sub_token,
    db_mark_migrated,
    db_is_migrated,
    db_get_non_migrated_users,
    db_clear_sub_token,
    db_clear_vless_uuid,
    db_ensure_signup_trial,
    db_get_open_ticket,
    db_create_ticket,
    db_get_ticket_by_id,
    db_close_ticket,
    db_add_support_message,
    db_get_ticket_messages,
    db_get_open_tickets,
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
    delete_amneziawg_device,
    execute_server_command,
    generate_vpn_url,
    get_available_servers,
    is_amneziawg_eu1_configured,
    regenerate_amneziawg_peer_and_config_for_user,
    regenerate_peer_and_config_for_user,
    replace_peer_with_profile_type,
    restore_user_revoked_peers,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═════════ §0 · МОДУЛЬНЫЕ ХЕЛПЕРЫ (вне main): proxy-rotate, инструкции ═════════
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

    # Menu Button → Mini App (ЛК открывается прямо внутри Telegram).
    # При запуске бота через Telegram.WebApp клиент шлёт initData → auto-login по telegram_id.
    # Set глобально (для всех юзеров бота). Идемпотентно — повтор не вреден.
    recovery_url = getattr(config, "vpn_recovery_url", None) or "https://supportkronos.online:8443/recovery"
    # Левая кнопка input bar — нативное «Меню» с командами бота (set_my_commands).
    # Mini App остаётся доступным через инлайн-кнопку «🌐 Открыть личный кабинет»
    # в основном меню /start.
    try:
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands(type="commands"))
        logger.info("Menu Button set to Commands (left bar)")
    except Exception as e:
        logger.warning("set_chat_menu_button failed: %s", e)
    try:
        bot.set_my_commands([
            types.BotCommand("start", "Меню"),
            types.BotCommand("lk", "Личный кабинет"),
            types.BotCommand("status", "Статус подписки"),
        ])
        logger.info("Bot commands set: /start, /lk, /status")
    except Exception as e:
        logger.warning("set_my_commands failed: %s", e)

    # ════════════════════════ §1 · AUTH / МЕНЮ / ДОСТУП ════════════════════════
    def safe_reply(message: types.Message, text: str, reply_markup=None) -> bool:
        """Отправляет ответ; при ошибке логирует и возвращает False.
        Если reply_markup не задан, автоматически использует _back_markup из message (если есть).
        """
        # Если явный markup не задан и нет _back_markup (callback-путь) — всё равно
        # даём «Главное меню», чтобы у typed-команд (/status, /proxy и т.п.) не было тупика.
        effective_markup = reply_markup or getattr(message, "_back_markup", None) or _back_to_menu_markup()
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

    def _check_access_or_block(chat_id: int, telegram_id: int) -> bool:
        """
        Гейт на VPN-конфиги. Возвращает True если доступ активен (или enforcement выключен).
        Если доступ неактивен — отправляет юзеру блокирующее сообщение и возвращает False.
        """
        if not config.enforcement_enabled:
            return True
        if db_is_access_active(telegram_id):
            return True
        # Доступ неактивен. Если триал ещё НЕ использован — предлагаем активировать
        # его бесплатно (новичок не должен видеть «заплати» вместо бесплатного триала).
        # Если триал уже использован — предлагаем оплату.
        trial_available = False
        try:
            sub = db_get_subscription(telegram_id) or {}
            trial_available = not sub.get("trial_used")
        except Exception as e:
            logger.debug("_check_access_or_block trial check failed: %s", e)

        markup = types.InlineKeyboardMarkup(row_width=1)
        if trial_available:
            markup.add(
                types.InlineKeyboardButton(f"🎁 Бесплатно: {tariffs.TRIAL_DAYS} дн / {tariffs.TRIAL_DATA_LIMIT_GB} ГБ", callback_data="menu_trial_activate"),
                types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"),
            )
            text = (
                f"🎁 <b>Сначала активируй бесплатный период — {tariffs.TRIAL_DAYS} дней / {tariffs.TRIAL_DATA_LIMIT_GB} ГБ.</b>\n\n"
                "Нажми кнопку ниже — и VPN сразу заработает. Без оплаты."
            )
        else:
            markup.add(
                types.InlineKeyboardButton("💳 Продлить подписку", callback_data="pay_show"),
                types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"),
            )
            text = (
                "🔴 <b>Подписка неактивна.</b>\n\n"
                "Продли — и VPN снова заработает. Текущие конфиги останутся теми же, "
                "перенастраивать ничего не надо."
            )
        try:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            logger.warning("_check_access_or_block: send_message failed: %s", e)
        return False

    # Состояние ожидания ввода ID пользователя от администратора (для add_user через кнопку)
    _pending_add_user: set[int] = set()

    # Состояние ожидания ввода «tid days [note]» для ручного зачисления дней через кнопку
    _pending_credit_user: set[int] = set()

    # Support: юзер ввёл сообщение в режим support (после нажатия «🆘 Поддержка»).
    # {tid: {step: 'awaiting_message', ticket_id: int}}
    _support_user_state: dict[int, dict] = {}

    # Support: owner-режим ответа на тикет. {admin_id: {ticket_id, user_tid}}
    _support_reply_state: dict[int, dict] = {}

    # Состояние ожидания ввода ID для генерации AmneziaWG конфига (через кнопку в админке)
    _pending_awg_conf: set[int] = set()

    # Состояние ожидания текста для рассылки
    _pending_broadcast: set[int] = set()
    _pending_grant_all: set[int] = set()  # admin: ожидание ввода «дать всем N дней»
    # Выбранный сегмент рассылки (owner uid → segment key). См. db_users_by_segment.
    _broadcast_segment: dict[int, str] = {}
    _SEGMENT_LABELS = {
        "all": "Все",
        "active": "Активные (есть доступ)",
        "inactive": "Неактивные (все)",
        "inactive_no_onboarding": "Неактивные · не прошли онбординг",
        "inactive_used": "Неактивные · пользовавшиеся",
        "test": "🧪 Тест (только мой 2-й акк)",
    }

    # Email-link flow: {telegram_id: {"state": "email"|"otp", "email": str}}
    _email_link_state: dict[int, dict] = {}

    # Onboarding flow (Phase 3b proper, под ONBOARDING_ENABLED): {tid: {"step": "email"|"otp", "email": str}}
    # "disclaimer" фаза не нужна в state — она показывается один раз через cmd_start без ожидания текстового ввода,
    # дальнейшие шаги — через callback'и + сообщения.
    _onboarding_state: dict[int, dict] = {}
    # Открытый онбординг-вопрос «для чего VPN»: uid → ждём свободный ответ.
    _use_case_state: dict[int, dict] = {}
    # Churn-опрос: uid → {kind, code} ждём уточняющий свободный текст (не работало/другое).
    _drop_detail_state: dict[int, dict] = {}

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

        greeting = (
            "Привет! Это VPN Kronos - бот. 🔐\n\n"
            f'🌐 <a href="{recovery_url}">Личный кабинет - сайт (если телеграм не работает)</a>\n'
            '⌛️ <a href="https://t.me/vpnkronos">Канал с обновлениями</a>'
        )

        if not authorized:
            text = greeting
            markup = types.InlineKeyboardMarkup()
            # Mini App-кнопка для незарегистрированных тоже работает —
            # auto-login по telegram_id; внутри Mini App юзер может пройти email-OTP.
            markup.add(
                types.InlineKeyboardButton(
                    "🌐 Открыть личный кабинет",
                    web_app=types.WebAppInfo(url=recovery_url),
                ),
            )
            markup.add(
                types.InlineKeyboardButton("📧 Войти по email", callback_data="email_register"),
            )
        else:
            text = greeting
            markup = types.InlineKeyboardMarkup(row_width=2)
            # Mini App кнопка первая — заметная альтернатива списку инлайн-кнопок.
            markup.add(
                types.InlineKeyboardButton(
                    "🌐 Открыть личный кабинет",
                    web_app=types.WebAppInfo(url=recovery_url),
                ),
            )
            markup.add(
                types.InlineKeyboardButton("🔗 Подключить VPN", callback_data="menu_get_vpn", style="primary"),
                types.InlineKeyboardButton("💳 Продлить подписку", callback_data="pay_show", style="success"),
                types.InlineKeyboardButton("📊 Статус подписки", callback_data="menu_status"),
                types.InlineKeyboardButton("📖 Инструкции", callback_data="menu_instruction"),
                types.InlineKeyboardButton("📨 Proxy для Telegram", callback_data="menu_proxy"),
                types.InlineKeyboardButton("🆘 Поддержка", callback_data="menu_support", style="danger"),
            )
            # Кнопка активации триала если он ещё не использован И нет активной подписки.
            # Видна и после онбординга с «Пропустить», и при истёкшей подписке (если триал не был активирован).
            try:
                sub = db_get_subscription(uid) or {}
                if not sub.get("trial_used"):
                    expires_at = sub.get("expires_at")
                    days_left = 0
                    if expires_at:
                        import math
                        from datetime import datetime as _dt
                        try:
                            delta = _dt.fromisoformat(expires_at) - _dt.utcnow()
                            days_left = max(0, math.ceil(delta.total_seconds() / 86400.0))
                        except (ValueError, TypeError):
                            days_left = 0
                    if not expires_at or days_left == 0:
                        markup.add(
                            types.InlineKeyboardButton(
                                f"🎁 Бесплатно: {tariffs.TRIAL_DAYS} дн / {tariffs.TRIAL_DATA_LIMIT_GB} ГБ",
                                callback_data="menu_trial_activate",
                            ),
                        )
            except Exception as e:
                logger.debug("trial_available check failed: %s", e)

            if is_owner(uid, admin_id):
                markup.add(types.InlineKeyboardButton("⚙️ Администратор", callback_data="admin_panel"))
            elif _needs_email_link(uid):
                markup.add(types.InlineKeyboardButton("🔗 Привязать email", callback_data="email_link"))

        if new_message:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup,
                             disable_web_page_preview=True)
        else:
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup,
                             disable_web_page_preview=True)

    # ── Онбординг при /start в новом боте (под ENV-флагом ONBOARDING_ENABLED) ─

    _DISCLAIMER_TEXT = (
        "Привет! Это <b>VPN Kronos</b>.\n\n"
        "Сервис даёт защищённое сетевое соединение для повседневного доступа "
        "с телефона и компьютера.\n\n"
        "Сейчас:\n\n"
        "1. подтвердим email;\n"
        f"2. активируем {tariffs.TRIAL_DAYS} дней бесплатного доступа;\n"
        "3. выдадим конфигурацию и инструкцию под твоё устройство.\n\n"
        "Важно: торренты не поддерживаются, чтобы не создавать лишнюю нагрузку на каналы."
    )

    # ════════════════════ §2 · ОНБОРДИНГ / USE_CASE / CHURN ════════════════════
    def _onboarding_needed(telegram_id: int) -> bool:
        """
        Запускать ли онбординг при /start.
        Триггерим, если ENV-флаг включён И юзер не ЗАВЕРШИЛ онбординг (email_verified+migrated_at).
        Так если на каком-то шаге был сбой (например OTP не отправился из-за неверного api_key),
        повторный /start снова запустит FSM, а не уведёт сразу в меню.
        """
        if not config.onboarding_enabled:
            return False
        user = find_user(telegram_id)
        if not user:
            return True
        # Завершённый онбординг = real email_verified=True И migrated_at IS NOT NULL.
        # Синтетические email (tg_<id>@kronos.internal от Mini App) считаются как «не собран».
        if not user.email_verified:
            return True
        if _is_synthetic_email(user.email):
            return True
        if not db_is_migrated(telegram_id):
            return True
        return False

    def _start_onboarding(chat_id: int, telegram_id: int) -> None:
        """Показывает дисклеймер. Дальше — по нажатию кнопки `onb_ack`."""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Начать настройку", callback_data="onb_ack"))
        try:
            bot.send_message(
                chat_id,
                _DISCLAIMER_TEXT,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.exception("_start_onboarding send_message failed: %s", e)

    def _mask_email(email: str) -> str:
        """user@example.com → u***@example.com (для отображения уже привязанного email)."""
        if not email or "@" not in email:
            return email or "—"
        local, _, domain = email.partition("@")
        if len(local) <= 1:
            return f"{local}***@{domain}"
        return f"{local[0]}***@{domain}"

    def _is_synthetic_email(email: str | None) -> bool:
        """Синтетические email вида tg_<id>@kronos.internal генерятся при Mini App auto-login.
        Считаем их как «email не собран» — гонят юзера ввести настоящий."""
        return bool(email) and email.endswith("@kronos.internal")

    def _post_disclaimer_step(chat_id: int, telegram_id: int) -> None:
        """После дисклеймера: если REAL email уже есть — предлагаем оставить/сменить; иначе запрашиваем."""
        user = find_user(telegram_id)
        existing_email = (
            user.email
            if (user and user.email_verified and not _is_synthetic_email(user.email))
            else None
        )
        if existing_email:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(
                    f"✅ Использовать {_mask_email(existing_email)}",
                    callback_data="onb_keep_email",
                ),
                types.InlineKeyboardButton(
                    "✏️ Ввести другой email",
                    callback_data="onb_new_email",
                ),
            )
            bot.send_message(
                chat_id,
                f"📧 У тебя уже привязан email: <b>{_mask_email(existing_email)}</b>\n\n"
                f"Использовать его, или ввести другой?",
                parse_mode="HTML",
                reply_markup=markup,
            )
        else:
            _onboarding_state[telegram_id] = {"step": "email"}
            bot.send_message(
                chat_id,
                "📧 Введи свой email — пришлём одноразовый код для подтверждения.",
            )

    def _finalize_onboarding(chat_id: int, telegram_id: int) -> None:
        """
        Завершение email-онбординга. Отмечаем migrated_at, дальше предлагаем триал (через onb_trial_choice).
        db_mark_migrated идёт ИМЕННО ЗДЕСЬ (а не в /start) — у новых юзеров запись в users
        появляется только после db_upsert_user в OTP-шаге, до этого UPDATE затрагивает 0 строк.
        """
        # Pending ref-код от /start ref_<code> deeplink — применяем сейчас,
        # когда юзер реально создан в БД и прошёл OTP. db_set_referred_by
        # idempotent (вернёт False если уже привязан) — повторного уведомления не будет.
        state = _onboarding_state.get(telegram_id) or {}
        pending_ref_code = state.get("pending_ref_code")
        if pending_ref_code:
            try:
                if db_set_referred_by(telegram_id, pending_ref_code):
                    _notify_inviter_about_signup_from_bot(pending_ref_code)
            except Exception as e:
                logger.warning("pending_ref attribution failed for %s: %s", telegram_id, e)

        _onboarding_state.pop(telegram_id, None)
        try:
            db_mark_migrated(telegram_id)
        except Exception as e:
            logger.warning("db_mark_migrated (finalize) failed for %s: %s", telegram_id, e)

        # Если триал ещё не использован и нет активной подписки → даём выбор активировать или пропустить.
        sub = db_get_subscription(telegram_id) or {}
        if not sub.get("trial_used") and not sub.get("expires_at"):
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(f"🎁 Бесплатно: {tariffs.TRIAL_DAYS} дн / {tariffs.TRIAL_DATA_LIMIT_GB} ГБ", callback_data="onb_trial_yes"),
                types.InlineKeyboardButton("⏭ Пропустить", callback_data="onb_trial_skip"),
            )
            bot.send_message(
                chat_id,
                "✅ Email подтверждён.\n\n"
                f"🎁 Тебе доступно <b>бесплатно: {tariffs.TRIAL_DAYS} дней или {tariffs.TRIAL_DATA_LIMIT_GB} ГБ</b> — активировать сейчас? "
                "Можно пропустить и активировать позже из меню.",
                parse_mode="HTML",
                reply_markup=markup,
            )
            return

        # У юзера уже есть подписка (grandfather после reset, активный платящий) → сразу в меню.
        bot.send_message(chat_id, "✅ Готово! Открываю меню.")
        _send_main_menu_for_tid(chat_id, telegram_id)

    def _send_main_menu_for_tid(chat_id: int, telegram_id: int) -> None:
        """Хелпер: показывает главное меню по telegram_id (без объекта from_user)."""
        from types import SimpleNamespace
        user_row = db_find_user_by_telegram_id(telegram_id) or {}
        fake_from_user = SimpleNamespace(
            id=telegram_id,
            username=user_row.get("username"),
        )
        _send_main_menu(chat_id, fake_from_user)

    @bot.callback_query_handler(func=lambda call: call.data == "onb_trial_yes")
    def callback_onb_trial_yes(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        tid = call.from_user.id
        new_exp = db_ensure_signup_trial(tid, days=tariffs.TRIAL_DAYS)
        if new_exp:
            exp_str = new_exp[:10]
            bot.send_message(
                call.message.chat.id,
                f"🎁 Триал активирован. Подписка активна до <b>{exp_str}</b>.",
                parse_mode="HTML",
            )
            _send_subscription(call.message.chat.id, tid)  # сразу выдаём подписку (Happ), не оставляем в меню
        _send_main_menu_for_tid(call.message.chat.id, tid)

    @bot.callback_query_handler(func=lambda call: call.data == "onb_trial_skip")
    def callback_onb_trial_skip(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        tid = call.from_user.id
        # Помечаем подписку как «истёкшую сейчас» — иначе expires_at IS NULL = grandfather =
        # бесплатный безграничный доступ. Триал остаётся доступным (trial_used не трогаем).
        try:
            from .database import _conn
            with _conn() as con:
                con.execute(
                    "UPDATE users SET expires_at = datetime('now'), subscription_status = 'expired' "
                    "WHERE telegram_id = ? AND expires_at IS NULL",
                    (tid,),
                )
        except Exception as e:
            logger.warning("onb_trial_skip set-expired failed: %s", e)
        bot.send_message(
            call.message.chat.id,
            f"⏭ Триал не активирован. Можешь активировать его в любой момент через меню → «🎁 Активировать {tariffs.TRIAL_DAYS} дней».",
        )
        # Вопрос-сегментацию задаём и при пропуске триала (не только при активации).
        _send_main_menu_for_tid(call.message.chat.id, tid)

    # Кнопка активации триала из главного меню бота (если триал доступен).
    @bot.callback_query_handler(func=lambda call: call.data == "menu_trial_activate")
    def callback_menu_trial_activate(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        tid = call.from_user.id
        # db_start_trial: проверяет только trial_used (не требует expires_at IS NULL).
        # Это позволяет активировать триал и после "Пропустить" в онбординге (где expires_at=NOW).
        from .database import db_start_trial
        new_exp = db_start_trial(tid, days=tariffs.TRIAL_DAYS)
        if new_exp:
            exp_str = new_exp[:10]
            bot.send_message(
                call.message.chat.id,
                f"🎁 Триал активирован. Подписка активна до <b>{exp_str}</b>.",
                parse_mode="HTML",
            )
            _send_subscription(call.message.chat.id, tid)  # сразу выдаём подписку (Happ), не оставляем в меню
        else:
            bot.send_message(
                call.message.chat.id,
                "Триал уже был использован раньше или у тебя уже активна подписка.",
            )
        _send_main_menu_for_tid(call.message.chat.id, tid)

    # ── Онбординг-сегментация: открытый вопрос «для чего VPN» (по желанию) ──────
    def _maybe_ask_use_case(chat_id: int, uid: int) -> bool:
        """Если ответ ещё не сохранён — задаёт открытый вопрос. True = задали
        (меню отправим после ответа/пропуска), False = уже отвечал → дальше сразу."""
        try:
            if db_get_use_case(uid):
                return False
        except Exception:
            return False
        _use_case_state[uid] = {"step": "await"}
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✍️ Ответить", callback_data="usecase_answer"),
            types.InlineKeyboardButton("⏭ Пропустить", callback_data="usecase_skip"),
        )
        bot.send_message(
            chat_id,
            "🙋 Один короткий вопрос: <b>для чего тебе VPN в первую очередь?</b>\n\n"
            "Это поможет сделать сервис лучше под тебя.",
            parse_mode="HTML", reply_markup=markup,
        )
        return True

    @bot.callback_query_handler(func=lambda call: call.data == "usecase_answer")
    def callback_usecase_answer(call: types.CallbackQuery) -> None:  # type: ignore[override]
        # «Ответить» → показываем примеры и ждём свободный текст (state уже стоит,
        # но переустановим на случай если был сброшен). Юзер пишет и отправляет.
        bot.answer_callback_query(call.id)
        if call.from_user:
            _use_case_state[call.from_user.id] = {"step": "await"}
        bot.send_message(
            call.message.chat.id,
            "Напиши одним сообщением — YouTube, работа, нейросети, музыка, сайты, что угодно.",
        )

    @bot.callback_query_handler(func=lambda call: call.data == "usecase_skip")
    def callback_usecase_skip(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if call.from_user:
            _use_case_state.pop(call.from_user.id, None)
            _send_main_menu_for_tid(call.message.chat.id, call.from_user.id)

    @bot.message_handler(
        func=lambda msg: (msg.from_user is not None and msg.from_user.id in _use_case_state
                          and bool(getattr(msg, "text", None)) and not msg.text.startswith("/"))
    )
    def handle_use_case_answer(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        uid = message.from_user.id
        _use_case_state.pop(uid, None)
        try:
            db_set_use_case(uid, message.text or "")
        except Exception as e:
            logger.warning("db_set_use_case failed for %s: %s", uid, e)
        bot.send_message(message.chat.id, "Спасибо! 🙌 Учтём.")
        _send_main_menu_for_tid(message.chat.id, uid)

    # ── Churn-опрос: причины отвала (kind=churn, 3.2) / недо-онбординга (kind=onb, 3.1) ──
    def _send_churn_survey(chat_id: int, kind: str) -> None:
        kb = types.InlineKeyboardMarkup(row_width=1)
        for code, label in churn.reasons_for(kind):
            kb.add(types.InlineKeyboardButton(label, callback_data=f"drop:{kind}:{code}"))
        bot.send_message(chat_id, churn.text_for(kind), reply_markup=kb)

    def _drop_followup(chat_id: int, kind: str, code: str) -> None:
        """Win-back / закрытие после выбранной причины (тейлоред по причине)."""
        kb = types.InlineKeyboardMarkup(row_width=1)
        if kind == "churn":
            if code == "expensive":
                kb.add(
                    types.InlineKeyboardButton("💳 Тарифы / продлить", callback_data="pay_show"),
                )
                bot.send_message(chat_id, "Спасибо! Если дело в цене — посмотри тарифы 👇", reply_markup=kb)
            elif code == "forgot":
                kb.add(types.InlineKeyboardButton("💳 Продлить", callback_data="pay_show"))
                bot.send_message(chat_id, "Спасибо! Продлить — пара тапов 👇", reply_markup=kb)
            elif code == "not_working":
                kb.add(types.InlineKeyboardButton("🆘 Поддержка", callback_data="menu_support"))
                bot.send_message(chat_id, "Спасибо! Давай починим — опиши проблему в поддержке, поможем 👇", reply_markup=kb)
            else:  # not_needed / found_other / other
                bot.send_message(chat_id, "Спасибо за интерес 🙌 Будем рады вернуть.")
        else:  # onb (не прошли онбординг)
            if code in ("too_hard", "no_email", "other"):
                bot.send_message(chat_id, "Спасибо! Закончить настройку — минута: жми /start, поможем.")
            else:  # changed_mind / just_looking
                bot.send_message(chat_id, "Спасибо! Передумаешь — жми /start, всё под рукой.")

    @bot.callback_query_handler(func=lambda call: call.data == "churn_open")
    def callback_churn_open(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if call.from_user:
            try:
                db_mark_churn_asked(call.from_user.id)  # дедуп: не дублировать авто-T+1
            except Exception:
                pass
            _send_churn_survey(call.message.chat.id, "churn")

    @bot.callback_query_handler(func=lambda call: bool(call.data) and call.data.startswith("drop:"))
    def callback_drop_reason(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        uid = call.from_user.id
        try:
            _, kind, code = call.data.split(":", 2)
        except ValueError:
            return
        label = churn.label_for(kind, code)
        if not label:
            return
        try:
            db_set_drop_reason(uid, label)
            db_mark_churn_asked(uid)
        except Exception as e:
            logger.warning("db_set_drop_reason failed for %s: %s", uid, e)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        if churn.needs_free_text(kind, code):
            _drop_detail_state[uid] = {"kind": kind, "code": code}
            bot.send_message(call.message.chat.id, "Спасибо! Расскажи в двух словах — что именно? (одним сообщением)")
            return
        _drop_followup(call.message.chat.id, kind, code)

    @bot.message_handler(
        func=lambda msg: (msg.from_user is not None and msg.from_user.id in _drop_detail_state
                          and bool(getattr(msg, "text", None)) and not msg.text.startswith("/"))
    )
    def handle_drop_detail(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        uid = message.from_user.id
        st = _drop_detail_state.pop(uid, None) or {}
        try:
            db_append_drop_detail(uid, message.text or "")
        except Exception as e:
            logger.warning("db_append_drop_detail failed for %s: %s", uid, e)
        _drop_followup(message.chat.id, st.get("kind", "churn"), st.get("code", "other"))

    @bot.callback_query_handler(func=lambda call: call.data == "onb_ack")
    def callback_onb_ack(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        tid = call.from_user.id
        # На всякий случай ставим migrated_at если ещё не выставлен (на случай гонки)
        try:
            db_mark_migrated(tid)
        except Exception as e:
            logger.warning("db_mark_migrated failed: %s", e)
        _post_disclaimer_step(call.message.chat.id, tid)

    @bot.callback_query_handler(func=lambda call: call.data == "onb_keep_email")
    def callback_onb_keep_email(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        # Email уже верифицирован, никаких OTP не нужно — финализируем
        _finalize_onboarding(call.message.chat.id, call.from_user.id)

    @bot.callback_query_handler(func=lambda call: call.data == "onb_new_email")
    def callback_onb_new_email(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        tid = call.from_user.id
        _onboarding_state[tid] = {"step": "email"}
        bot.send_message(
            call.message.chat.id,
            "📧 Введи новый email — пришлём одноразовый код для подтверждения.",
        )

    # Текстовый ввод во время онбординга (email или OTP)
    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _onboarding_state
    )
    def handle_onboarding_input(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        tid = message.from_user.id
        state = _onboarding_state.get(tid) or {}
        step = state.get("step")
        text = (message.text or "").strip()

        if step == "email":
            email = text.lower()
            if "@" not in email or "." not in email.split("@")[-1]:
                bot.send_message(message.chat.id, "Это не похоже на email. Попробуй ещё раз.")
                return
            # Создаём OTP и отправляем письмо (переиспользуем существующую логику)
            try:
                otp = generate_otp()
                db_create_otp(email, otp)
                sent = send_otp_email(
                    to_email=email,
                    code=otp,
                    api_key=config.resend_api_key,
                    from_email=config.resend_from_email,
                )
                if not sent:
                    raise RuntimeError("send_otp_email returned False")
            except Exception as e:
                logger.exception("onboarding: send_otp failed: %s", e)
                bot.send_message(
                    message.chat.id,
                    "❌ Не удалось отправить код. Попробуй позже или напиши @nikkronos.",
                )
                return
            _onboarding_state[tid] = {"step": "otp", "email": email}
            bot.send_message(
                message.chat.id,
                "🔢 Введи 6 цифр из письма (проверь спам, если не пришло за минуту).",
            )
            return

        if step == "otp":
            code = text.replace(" ", "")
            email = state.get("email", "")
            if not db_verify_otp(email, code):
                bot.send_message(message.chat.id, "❌ Код неверный или истёк. Попробуй ещё раз.")
                return
            # Помечаем email верифицированным в БД
            from .database import db_upsert_user
            db_upsert_user({
                "telegram_id": tid,
                "email": email,
                "email_verified": True,
                "active": True,
            })
            _finalize_onboarding(message.chat.id, tid)
            return

        # Неизвестный шаг — чистим состояние
        _onboarding_state.pop(tid, None)

    # ══════════════════════════ §3 · RESTORE / РЕФЕРАЛ ══════════════════════════
    def _restore_and_notify(telegram_id: int) -> None:
        """
        Hook после успешного db_extend_subscription: возвращает revoked AWG peer'ы
        в runtime + триггерит async sync VLESS UUIDs (если у юзера есть) +
        уведомляет юзера. Idempotent.

        Используется во всех payment-handlers (Stars, donation, admin_credit).
        Без этого юзер после оплаты должен был бы сам нажать «Получить VPN»
        для нового конфига — теперь старый .conf и subscription снова работают.
        """
        # 1. AWG soft-restore (как было)
        restored_awg = []
        try:
            restored_awg = restore_user_revoked_peers(telegram_id)
        except Exception as e:
            logger.exception("restore_user_revoked_peers failed for tid=%s: %s", telegram_id, e)

        # 2. VLESS soft-restore (NEW) — async sync_xray_users.py если у юзера есть UUIDs.
        # sync_xray_users.py забирает только active юзеров (с учётом grace 12h);
        # после db_extend_subscription expires_at в будущем → юзер попадает в active
        # → UUID возвращается в Xray clients[] → старая ссылка снова работает.
        restored_vless = False
        try:
            if db_get_per_user_vless_uuid(telegram_id, "main") or db_get_per_user_vless_uuid(telegram_id, "yc"):
                import subprocess as _sp
                import pathlib as _pl
                script_path = _pl.Path(__file__).resolve().parent.parent / "scripts" / "sync_xray_users.py"
                _sp.Popen(
                    [sys.executable, str(script_path), "--all", "--no-shared"],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                    start_new_session=True,
                )
                restored_vless = True
                logger.info("Spawned async sync_xray_users for VLESS auto-restore tid=%s", telegram_id)
        except Exception as e:
            logger.warning("VLESS auto-restore sync failed for tid=%s: %s", telegram_id, e)

        # 3. Уведомить юзера — только если хоть что-то восстановилось
        if not (restored_awg or restored_vless):
            return
        try:
            bot.send_message(
                telegram_id,
                "✅ <b>Доступ восстановлен.</b>\n\n"
                "Твой существующий конфиг снова работает — переподключаться не нужно.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("notify restored user failed for tid=%s: %s", telegram_id, e)

    def _notify_inviter_about_signup_from_bot(ref_code: str) -> None:
        """
        Уведомляет пригласителя в TG, что по его реф-ссылке зарегистрировался
        новый пользователь (через bot deeplink /start ref_X, либо после
        завершения онбординга с pending_ref_code).
        Не падает при ошибках — это вспомогательное уведомление, не критичный
        функционал. db_set_referred_by уже привязал к этому моменту.
        """
        try:
            if not ref_code:
                return
            inviter = db_get_user_by_referral_code(ref_code)
            if not inviter:
                return
            inviter_tid = inviter.get("telegram_id")
            if not inviter_tid:
                return
            bot.send_message(
                int(inviter_tid),
                "👋 <b>По твоей реф-ссылке зарегистрировался новый пользователь.</b>\n\n"
                "Бонус +14 дней начислится тебе и ему, когда он впервые "
                "оплатит подписку.",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.exception("notify inviter (bot) failed: %s", e)

    # ═══════════════════════════════ §4 · /START ═══════════════════════════════
    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return

        tid = message.from_user.id

        # Deeplink: /start support → сразу в Support-флоу (минуя меню), если онбординг пройден.
        # /start ref_<code> → сохраняем реф-код для привязки в конце онбординга
        # (основной flow рефералов идёт через Mini App startapp=ref_X, см. /api/auth/tg-webapp;
        # этот /start fallback нужен для тех, кто открыл ссылку без Mini App).
        start_arg = ""
        if message.text and " " in message.text:
            start_arg = message.text.split(maxsplit=1)[1].strip()

        # Сохраняем ref-код для привязки после успешного OTP-verify в FSM.
        # state доступен через _onboarding_state[tid] — set'аем заранее, чтобы
        # на этапе finalize-onboarding можно было применить db_set_referred_by.
        if start_arg.lower().startswith("ref_"):
            ref_code = start_arg[4:]  # сохраняем исходный регистр кода
            if ref_code:
                _onboarding_state.setdefault(tid, {})["pending_ref_code"] = ref_code

        start_arg_lower = start_arg.lower()

        # Если онбординг включён и юзер ещё не «прошёл» — запускаем FSM, не показывая обычное меню.
        # Support deeplink имеет приоритет ТОЛЬКО для уже-онбордившихся юзеров.
        if _onboarding_needed(tid):
            try:
                # Помечаем юзера как мигрировавшего сразу при первом /start (даже если он дисклеймер не дочитает —
                # selective reset не должен его задеть, раз он хотя бы зашёл в новый бот).
                db_mark_migrated(tid)
            except Exception as e:
                logger.warning("db_mark_migrated on /start failed: %s", e)
            _start_onboarding(message.chat.id, tid)
            return

        if start_arg_lower == "support":
            _open_support_flow(message.chat.id, tid)
            return

        # Если юзер уже-онбордившийся и пришёл по реф-ссылке — применяем сразу
        # (привязки можно делать idempotent: db_set_referred_by вернёт False
        # если уже привязан, и тогда уведомление не уйдёт).
        if start_arg_lower.startswith("ref_"):
            try:
                ref_code = start_arg[4:]
                if ref_code and db_set_referred_by(tid, ref_code):
                    _notify_inviter_about_signup_from_bot(ref_code)
            except Exception as e:
                logger.warning("/start ref attribution failed: %s", e)

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

    # ════════════════════ §5 · ДОСТАВКА КОНФИГОВ (AmneziaWG) ════════════════════
    def _send_config_file(chat_id: int, config_text: str, filename: str) -> None:
        """
        Отправляет текстовый конфиг как файл пользователю.
        """
        file_obj = io.BytesIO(config_text.encode("utf-8"))
        file_obj.name = filename
        bot.send_document(chat_id, file_obj, visible_file_name=filename)

    def _awg_success_text(platform: str) -> str:
        """Текст-инструкция для AmneziaWG-конфига по платформам."""
        mobile_warn = (
            "\n\n⚠️ AmneziaWG — для <b>ПК / Wi-Fi</b>. На мобильном интернете "
            "подключайся через «🔗 Подключить» (одна ссылка)."
        )
        if platform == "pc":
            return (
                "✅ Готово. Файл скачан.\n\n"
                "📂 <b>Установка:</b>\n"
                "1. Поставь <a href=\"https://amnezia.org\">AmneziaVPN</a>.\n"
                "2. В приложении: <b>«+»</b> → <b>«Импорт из файла»</b> → выбери скачанный <code>.conf</code>.\n"
                "3. Включи туннель." + mobile_warn
            )
        if platform == "ios":
            return (
                "✅ Готово. Файл скачан.\n\n"
                "📱 <b>Установка:</b>\n"
                "1. Поставь <b>AmneziaWG</b> из App Store.\n"
                "2. Нажми на файл → «Поделиться» → выбери <b>AmneziaWG</b> → «Создать из файла».\n"
                "3. Включи туннель." + mobile_warn
            )
        # android
        return (
            "✅ Готово.\n\n"
            "🤖 <b>Установка:</b>\n"
            "Тапни ссылку ниже — <b>AmneziaVPN</b> откроет и импортирует конфиг автоматически.\n"
            "Если приложение ещё не установлено — поставь <a href=\"https://amnezia.org\">AmneziaVPN</a> "
            "из Google Play." + mobile_warn
        )

    def _not_working_kb() -> types.InlineKeyboardMarkup:
        """Клавиатура под выданным конфигом: быстрый переход в «Не работает» + меню.
        Чтобы юзер получил конфиг и сразу мог нажать исправление, если не заработало."""
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🔄 Не работает", callback_data="menu_regen"),
            types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"),
        )
        return kb

    def _deliver_config(
        message: types.Message,
        config_text: str,
        filename: str,
        platform: str,
        success_text: str | None = None,
    ) -> None:
        """
        Доставляет AmneziaWG-конфиг в зависимости от платформы.
        pc/ios → .conf файл, текст-инструкция отдельным сообщением.
        android → vpn:// deep link + текст-инструкция.
        success_text=None → используем стандартный _awg_success_text(platform).
        """
        chat_id = message.chat.id
        text = success_text if success_text is not None else _awg_success_text(platform)
        if platform == "android":
            vpn_link = generate_vpn_url(config_text)
            bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
            bot.send_message(chat_id, vpn_link, parse_mode=None, reply_markup=_not_working_kb())
        else:  # pc / ios
            _send_config_file(chat_id, config_text, filename)
            bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True,
                             reply_markup=_not_working_kb())

    def _deliver_vless_link(message: types.Message, vless_link: str, success_text: str) -> None:
        """Отправляет vless:// ссылку пользователю: сначала сообщение, потом ссылка в code-блоке."""
        chat_id = message.chat.id
        bot.send_message(chat_id, success_text, parse_mode="HTML")
        bot.send_message(chat_id, f"<code>{vless_link}</code>", parse_mode="HTML",
                         reply_markup=_not_working_kb())

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
                # Peer уже существует, тип профиля совпадает.
                # Для eu1 (AmneziaWG) — регенерируем (тот же IP, новые ключи) и выдаём свежий conf.
                # Это «получить конфиг повторно» — если юзер потерял или хочет на новое устройство.
                servers_info = get_available_servers()
                server_name = servers_info.get(preferred_server_id, {}).get("name", preferred_server_id)
                platform_label = {"pc": "ПК", "ios": "iOS", "android": "Android"}.get(platform, platform)
                if preferred_server_id == "eu1":
                    try:
                        peer, client_config = regenerate_amneziawg_peer_and_config_for_user(
                            telegram_id,
                            android_safe=android_safe,
                            server_id="eu1",
                            platform=platform,
                        )
                        filename = f"awg_{peer.server_id}.conf"
                        _deliver_config(message, client_config, filename, platform)
                    except WireGuardError as exc:
                        logger.exception("AmneziaWG regen for %s: %s", telegram_id, exc)
                        safe_reply(
                            message,
                            "Не удалось получить конфиг. Попробуй позже или напиши владельцу.",
                        )
                else:
                    safe_reply(
                        message,
                        f"Для тебя уже создан VPN‑доступ на сервере <b>{server_name}</b> ({preferred_server_id}) "
                        f"для <b>{platform_label}</b>.\n"
                        "Если потерял конфиг или нужно обновить, используй «🔄 Обновить конфиг» в меню.",
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

            # Европа (eu1): AmneziaWG (Резервный VPN — отдельный .conf для AmneziaWG/AmneziaVPN).
            if preferred_server_id == "eu1":
                try:
                    peer, client_config = create_amneziawg_peer_and_config_for_user(
                        telegram_id,
                        android_safe=android_safe,
                        server_id="eu1",
                        platform=platform,
                    )
                    filename = f"awg_{peer.server_id}.conf"
                    _deliver_config(message, client_config, filename, platform)
                except WireGuardError as exc:
                    logger.exception("Ошибка AmneziaWG для %s: %s", telegram_id, exc)
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

            # Европа (eu1): регенерация AmneziaWG peer (новые ключи, тот же IP).
            if preferred_server_id == "eu1":
                try:
                    peer, client_config = regenerate_amneziawg_peer_and_config_for_user(
                        telegram_id,
                        android_safe=android_safe,
                        server_id="eu1",
                        platform=platform,
                    )
                    filename = f"awg_{peer.server_id}.conf"
                    # Предупреждение, что старый отвалится — отдельной строкой перед стандартной инструкцией.
                    warn = "⚠️ Старый конфиг больше не работает — импортируй новый.\n\n"
                    _deliver_config(
                        message, client_config, filename, platform,
                        warn + _awg_success_text(platform),
                    )
                except WireGuardError as exc:
                    logger.exception("Ошибка регенерации AmneziaWG для %s: %s", telegram_id, exc)
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

    # ════════════════════════ §6 · ПРОФИЛИ / УСТРОЙСТВА ════════════════════════
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
        if action == "menu_get_vpn":
            # Главный путь — «Подключить VPN» (подписка, работает на всех устройствах,
            # включая мобильный). Сразу отдаём ссылку/QR (как в ЛК — главное на
            # первом экране). AmneziaWG и Мобильный — под кнопкой «Другие способы»
            # (она в разметке callback_vpn_quick).
            callback_vpn_quick(call)
        elif action == "menu_other_connect":
            other_markup = types.InlineKeyboardMarkup(row_width=1)
            other_markup.add(
                types.InlineKeyboardButton("💻 AmneziaWG — макс. скорость (ПК / Wi-Fi)", callback_data="menu_get_config"),
                types.InlineKeyboardButton("🖥 Мои устройства (AmneziaWG)", callback_data="dev_list"),
                types.InlineKeyboardButton("📡 Мобильный — под оператора", callback_data="menu_mobile_vpn"),
                types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"),
            )
            other_text = (
                "Другие способы подключения:\n\n"
                "💻 <b>AmneziaWG</b> — отдельный конфиг, макс. скорость на ПК / Wi-Fi. "
                "⚠️ Не работает на мобильном интернете.\n\n"
                "📡 <b>Мобильный</b> — отдельная ссылка под конкретного оператора."
            )
            bot.send_message(call.message.chat.id, other_text, parse_mode="HTML", reply_markup=other_markup)
        elif action == "menu_get_config":
            if not _check_access_or_block(call.message.chat.id, call.from_user.id):
                return
            _show_platform_keyboard(call.message.chat.id, "get_config")
        elif action == "menu_regen":
            # Разводка по проблеме: AmneziaWG (ПК) vs «Подключить» (телефон).
            fix_markup = types.InlineKeyboardMarkup(row_width=1)
            fix_markup.add(
                types.InlineKeyboardButton("💻 Сбросить конфиг AmneziaWG (ПК/Wi-Fi)", callback_data="menu_regen_awg"),
                types.InlineKeyboardButton("📱 Телефон / «Подключить» не работает", callback_data="menu_repair_sub"),
                types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"),
            )
            fix_text = (
                "Что не работает?\n\n"
                "💻 <b>AmneziaWG-конфиг (ПК / Wi-Fi)</b> — пересоздадим конфиг, импортируешь заново.\n\n"
                "📱 <b>Телефон / «Подключить»</b> — дадим ссылку. Достаточно удалить старый "
                "профиль в приложении (HAPP) и добавить новую ссылку."
            )
            bot.send_message(call.message.chat.id, fix_text, parse_mode="HTML", reply_markup=fix_markup)
        elif action == "menu_regen_awg":
            # Подтверждение перед сбросом AmneziaWG-конфига.
            confirm_markup = types.InlineKeyboardMarkup(row_width=1)
            confirm_markup.add(
                types.InlineKeyboardButton("✅ Да, пересоздать", callback_data="menu_regen_confirm"),
                types.InlineKeyboardButton("« Отмена", callback_data="go_main_menu"),
            )
            confirm_text = (
                "⚠️ <b>Пересоздать конфиг AmneziaWG?</b>\n\n"
                "Текущий <code>.conf</code> перестанет работать на всех устройствах. "
                "Получишь новый файл — импортируй его в AmneziaWG/AmneziaVPN заново.\n"
                "<i>На «Подключить» (ссылку) это не влияет.</i>"
            )
            bot.send_message(call.message.chat.id, confirm_text, parse_mode="HTML", reply_markup=confirm_markup)
        elif action == "menu_repair_sub":
            if not _check_access_or_block(call.message.chat.id, call.from_user.id):
                return
            bot.send_message(
                call.message.chat.id,
                "📱 Если на телефоне отвалилось: <b>удали старый профиль</b> в приложении (HAPP) "
                "и <b>добавь ссылку заново</b>. Обновлять ссылку не нужно — она обновляется сама.",
                parse_mode="HTML",
            )
            callback_vpn_quick(call)
        elif action == "menu_regen_confirm":
            if not _check_access_or_block(call.message.chat.id, call.from_user.id):
                return
            _show_platform_keyboard(call.message.chat.id, "regen")
        elif action == "menu_instruction":
            cmd_instruction(call.message)
        elif action == "menu_proxy":
            cmd_proxy(call.message)  # MTProxy не гейтим — открыт для всех
        elif action == "menu_mobile_vpn":
            if not _check_access_or_block(call.message.chat.id, call.from_user.id):
                return
            cmd_mobile_vpn(call.message)
        elif action == "menu_status":
            cmd_status(call.message)
        elif action == "menu_support":
            _open_support_flow(call.message.chat.id, call.from_user.id)

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
    # Callbacks: «Мои устройства» (Фаза 2 B — именованные AmneziaWG-слоты)
    # ──────────────────────────────────────────────────────────────
    _OS_LABEL = {"pc": "💻 ПК", "ios": "🍎 iOS", "android": "🤖 Android"}

    def _render_device_list(chat_id: int, uid: int) -> None:
        devices = db_list_devices(uid)
        cap = db_get_device_limit(uid)  # лимит по тарифу (3/5; грандфазер/триал = 5)
        kb = types.InlineKeyboardMarkup(row_width=2)
        for d in devices:
            did = d["device_id"]
            kb.add(types.InlineKeyboardButton(
                f"{_OS_LABEL.get(d['os'], d['os'])} · {d['name']}", callback_data="dev_noop"))
            kb.add(
                types.InlineKeyboardButton("🔄 Обновить", callback_data=f"devregen_{did}"),
                types.InlineKeyboardButton("🗑 Удалить", callback_data=f"devdel_{did}"),
            )
        if len(devices) < cap:
            kb.add(types.InlineKeyboardButton("➕ Добавить устройство", callback_data="dev_add"))
        else:
            kb.add(types.InlineKeyboardButton(f"Лимит {cap} устройств", callback_data="dev_noop"))
        kb.add(types.InlineKeyboardButton("« Назад", callback_data="menu_other_connect"))
        text = ("🖥 <b>Мои устройства (AmneziaWG)</b>\n\n" + (
            f"Устройств: {len(devices)} из {cap}. Каждое — отдельный конфиг; "
            "«Обновить» одно не ломает другие.\n⚠️ AmneziaWG — для ПК/Wi-Fi, не для мобильного."
            if devices else
            "Пока нет устройств. Добавь первое — каждому девайсу свой независимый конфиг."))
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

    def _add_device_and_deliver(message: types.Message, uid: int, os_: str) -> None:
        if os_ not in ("pc", "ios", "android"):
            return
        cap = db_get_device_limit(uid)
        if db_count_devices(uid) >= cap:
            bot.send_message(
                message.chat.id,
                f"Достигнут лимит {cap} устройств по твоему тарифу. Удали лишнее"
                + (" или оформи тариф на 5 устройств." if cap < 5 else "."))
            return
        name = db_device_autoname(uid, os_)
        device_id = db_add_device(uid, name, os_)
        try:
            _, cfg = create_amneziawg_peer_and_config_for_user(
                uid, android_safe=(os_ == "android"), server_id="eu1", platform=os_, device_id=device_id)
        except WireGuardError as exc:
            logger.exception("dev add %s os=%s: %s", uid, os_, exc)
            db_delete_device(device_id)  # откат записи устройства, раз peer не создан
            bot.send_message(message.chat.id, "Не удалось создать конфиг устройства. Попробуй позже.")
            return
        _deliver_config(message, cfg, f"awg_eu1_{os_}.conf", os_,
                        f"✅ Добавлено устройство «{name}». Импортируй конфиг в AmneziaWG/AmneziaVPN.")
        _render_device_list(message.chat.id, uid)

    def _regen_device(message: types.Message, uid: int, did: str) -> None:
        dev = db_get_device(did)
        if not dev or int(dev["telegram_id"]) != uid:
            bot.send_message(message.chat.id, "Устройство не найдено.")
            return
        os_ = dev["os"]
        try:
            _, cfg = regenerate_amneziawg_peer_and_config_for_user(
                uid, android_safe=(os_ == "android"), server_id="eu1", device_id=did)
        except WireGuardError as exc:
            logger.exception("dev regen %s did=%s: %s", uid, did[:8], exc)
            bot.send_message(message.chat.id, "Не удалось обновить конфиг. Попробуй позже.")
            return
        _deliver_config(message, cfg, f"awg_eu1_{os_}.conf", os_,
                        f"🔄 Конфиг «{dev['name']}» пересоздан. Импортируй заново.")

    @bot.callback_query_handler(func=lambda c: c.data in ("dev_list", "dev_add", "dev_noop")
                                or c.data.startswith(("devadd_", "devregen_", "devdel_", "devdelyes_")))
    def callback_devices(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        call.message.from_user = call.from_user
        uid = call.from_user.id
        chat_id = call.message.chat.id
        data = call.data
        if data == "dev_noop":
            return
        if not _check_access_or_block(chat_id, uid):
            return
        if data == "dev_list":
            _render_device_list(chat_id, uid)
        elif data == "dev_add":
            kb = types.InlineKeyboardMarkup(row_width=3)
            kb.add(
                types.InlineKeyboardButton("💻 ПК", callback_data="devadd_pc"),
                types.InlineKeyboardButton("🍎 iOS", callback_data="devadd_ios"),
                types.InlineKeyboardButton("🤖 Android", callback_data="devadd_android"),
            )
            kb.add(types.InlineKeyboardButton("« Назад", callback_data="dev_list"))
            bot.send_message(chat_id, "Тип нового устройства (для формата конфига):", reply_markup=kb)
        elif data.startswith("devadd_"):
            _add_device_and_deliver(call.message, uid, data.split("_", 1)[1])
        elif data.startswith("devregen_"):
            _regen_device(call.message, uid, data.split("_", 1)[1])
        elif data.startswith("devdelyes_"):
            did = data.split("_", 1)[1]
            dev = db_get_device(did)
            if dev and int(dev["telegram_id"]) == uid:
                delete_amneziawg_device(uid, did)
                bot.send_message(chat_id, f"🗑 Устройство «{dev['name']}» удалено.")
            _render_device_list(chat_id, uid)
        elif data.startswith("devdel_"):
            did = data.split("_", 1)[1]
            dev = db_get_device(did)
            if not dev or int(dev["telegram_id"]) != uid:
                bot.send_message(chat_id, "Устройство не найдено.")
                return
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(
                types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"devdelyes_{did}"),
                types.InlineKeyboardButton("« Отмена", callback_data="dev_list"),
            )
            bot.send_message(chat_id, f"Удалить устройство «{dev['name']}»? Конфиг перестанет работать.",
                             reply_markup=kb)

    # ──────────────────────────────────────────────────────────────
    # Email-авторизация и привязка
    # ──────────────────────────────────────────────────────────────

    # ══════════════════ §7 · EMAIL-ФЛОУ (регистрация/привязка) ══════════════════
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
        if call.from_user:
            _send_main_menu_for_tid(call.message.chat.id, call.from_user.id)

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
            from .database import db_upsert_user, db_delete_email_only_user
            # Удаляем email-only дубль (если был создан через recovery-сайт без Telegram).
            # Иначе UNIQUE constraint на email заблокирует обновление telegram-записи.
            db_delete_email_only_user(email)

            existing = find_user(uid)
            try:
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
            except Exception as exc:
                logger.error("Ошибка сохранения email для %s: %s", uid, exc)
                bot.reply_to(message, "❌ Не удалось сохранить email. Обратись к администратору.")
                return

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

    # ════════════════════════ §8 · ADMIN-ПАНЕЛЬ (inline) ════════════════════════
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
            types.InlineKeyboardButton("💳 Зачислить дней", callback_data="admin_credit_user"),
            types.InlineKeyboardButton("🔄 Ротация прокси", callback_data="admin_proxy_rotate"),
            types.InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user"),
            types.InlineKeyboardButton("🔓 Whitelist ID", callback_data="admin_whitelist"),
            types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
            types.InlineKeyboardButton("🔧 AmneziaWG конфиг", callback_data="admin_awg_conf"),
            types.InlineKeyboardButton("📊 Sync Google Sheets", callback_data="admin_sync_sheets"),
            types.InlineKeyboardButton("🎁 Дать всем дней", callback_data="admin_grant_all"),
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
        # Сброс предыдущего незавершённого выбора.
        _pending_broadcast.discard(call.from_user.id)
        _broadcast_segment.pop(call.from_user.id, None)
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("👥 Все", callback_data="bcast_seg:all"),
            types.InlineKeyboardButton("✅ Активные (есть доступ)", callback_data="bcast_seg:active"),
            types.InlineKeyboardButton("💤 Неактивные (все)", callback_data="bcast_seg:inactive"),
            types.InlineKeyboardButton("📝 Неактивные · не прошли онбординг", callback_data="bcast_seg:inactive_no_onboarding"),
            types.InlineKeyboardButton("🔚 Неактивные · пользовавшиеся", callback_data="bcast_seg:inactive_used"),
            types.InlineKeyboardButton("🧪 Тест (только мой 2-й акк)", callback_data="bcast_seg:test"),
            types.InlineKeyboardButton("« Назад", callback_data="admin_panel"),
        )
        bot.edit_message_text(
            "📢 <b>Рассылка</b>\n\nВыбери сегмент получателей:",
            call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda call: bool(call.data) and call.data.startswith("bcast_seg:"))
    def callback_broadcast_segment(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        seg = call.data.split(":", 1)[1]
        if seg not in _SEGMENT_LABELS:
            return
        _broadcast_segment[call.from_user.id] = seg
        _pending_broadcast.discard(call.from_user.id)
        try:
            count = len(db_users_by_segment(seg))
        except Exception:  # noqa: BLE001
            count = "?"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("📝 Обычный текст", callback_data="bcast_send:text"))
        if seg in ("inactive_used", "test"):
            kb.add(types.InlineKeyboardButton("❓ Опрос причин отвала", callback_data="bcast_send:churn"))
        if seg in ("inactive_no_onboarding", "test"):
            kb.add(types.InlineKeyboardButton("❓ Опрос про онбординг", callback_data="bcast_send:onb"))
        kb.add(types.InlineKeyboardButton("« Назад", callback_data="admin_broadcast"))
        bot.edit_message_text(
            f"📢 <b>Рассылка → {_SEGMENT_LABELS[seg]}</b>\n\n"
            f"Получателей: <b>{count}</b>.\n\nЧто отправить?",
            call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda call: bool(call.data) and call.data.startswith("bcast_send:"))
    def callback_broadcast_send(call: types.CallbackQuery) -> None:  # type: ignore[override]
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        uid = call.from_user.id
        mode = call.data.split(":", 1)[1]  # text | churn | onb
        seg = _broadcast_segment.get(uid)
        if not seg:
            bot.send_message(call.message.chat.id, "Сегмент не выбран — начни заново через 📢 Рассылка.")
            return
        if mode == "text":
            _pending_broadcast.add(uid)
            bot.edit_message_text(
                f"📢 <b>Рассылка → {_SEGMENT_LABELS[seg]}</b>\n\nНапиши текст — отправлю сегменту.\n"
                "<i>HTML: &lt;b&gt;жирный&lt;/b&gt;, &lt;i&gt;курсив&lt;/i&gt;, &lt;code&gt;код&lt;/code&gt;</i>",
                call.message.chat.id, call.message.message_id, parse_mode="HTML",
            )
            return
        if mode not in ("churn", "onb"):
            return
        # Рассылка опроса по сегменту: дедуп по churn_asked_at, помечаем при отправке.
        _broadcast_segment.pop(uid, None)
        try:
            recipients = db_users_by_segment(seg)
        except Exception as e:  # noqa: BLE001
            bot.send_message(call.message.chat.id, f"❌ Ошибка выборки сегмента: {e!r}")
            return
        bot.edit_message_text(
            f"⏳ Рассылаю опрос ({mode}) → «{_SEGMENT_LABELS[seg]}»: {len(recipients)}…",
            call.message.chat.id, call.message.message_id, parse_mode="HTML",
        )
        sent = skipped = failed = 0
        for u in recipients:
            tid = u.get("telegram_id")
            if not tid:
                continue
            if u.get("churn_asked_at"):  # уже спрашивали — не дублируем
                skipped += 1
                continue
            try:
                _send_churn_survey(int(tid), mode)
                db_mark_churn_asked(int(tid))
                sent += 1
                time.sleep(0.05)
            except Exception as e:  # noqa: BLE001
                logger.warning("Survey broadcast: не отправлено %s: %s", tid, e)
                failed += 1
        bot.edit_message_text(
            f"✅ Опрос ({mode}) → «{_SEGMENT_LABELS[seg]}»: отправлено <b>{sent}</b>, "
            f"пропущено (уже спрошены) <b>{skipped}</b>, ошибок <b>{failed}</b>.",
            call.message.chat.id, call.message.message_id, parse_mode="HTML",
        )

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _pending_broadcast
    )
    def handle_pending_broadcast(message: types.Message) -> None:  # type: ignore[override]
        """Получает текст рассылки от владельца и рассылает всем активным пользователям."""
        if not message.from_user:
            return
        uid = message.from_user.id
        _pending_broadcast.discard(uid)
        seg = _broadcast_segment.pop(uid, "all")
        broadcast_text = (message.text or "").strip()
        if not broadcast_text:
            bot.reply_to(message, "❌ Пустое сообщение. Рассылка отменена.")
            return

        # Шлём сразу по выбранному сегменту. Если передумал — просто не отправляй текст.
        try:
            recipients = db_users_by_segment(seg)
        except Exception as e:  # noqa: BLE001
            bot.reply_to(message, f"❌ Ошибка выборки сегмента: {e!r}")
            return

        seg_label = _SEGMENT_LABELS.get(seg, seg)
        status_msg = bot.reply_to(message, f"⏳ Рассылаю {len(recipients)} ({seg_label})…")
        sent = 0
        failed = 0
        for u in recipients:
            tid = u.get("telegram_id")
            if not tid:
                continue
            try:
                bot.send_message(int(tid), broadcast_text, parse_mode="HTML",
                                 disable_web_page_preview=True)
                sent += 1
                time.sleep(0.05)
            except Exception as e:  # noqa: BLE001
                logger.warning("Broadcast: не отправлено %s: %s", tid, e)
                failed += 1
        bot.edit_message_text(
            f"✅ Рассылка ({seg_label}) завершена: отправлено <b>{sent}</b>, не доставлено <b>{failed}</b>.",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode="HTML",
        )

    # === Дать всем активным N дней (компенсация простоя) ===
    @bot.callback_query_handler(func=lambda call: call.data == "admin_grant_all")
    def callback_admin_grant_all(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Шаг 1: спросить, сколько дней дать всем активным."""
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        _pending_grant_all.add(call.from_user.id)
        try:
            active_n = db_count_active_users()
        except Exception:  # noqa: BLE001
            active_n = "?"
        bot.edit_message_text(
            f"🎁 <b>Дать всем активным дней</b>\n\n"
            f"Сейчас активных (есть доступ, конечный срок): <b>{active_n}</b>.\n\n"
            f"Напиши <b>число дней</b> — добавлю их к сроку каждому активному "
            f"(тариф/триал не меняются). Любой другой текст — отмена.",
            call.message.chat.id, call.message.message_id, parse_mode="HTML",
        )

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _pending_grant_all
    )
    def handle_pending_grant_all(message: types.Message) -> None:  # type: ignore[override]
        """Шаг 2: принять число дней → показать подтверждение."""
        if not message.from_user:
            return
        uid = message.from_user.id
        _pending_grant_all.discard(uid)
        raw = (message.text or "").strip()
        if not raw.isdigit() or not (1 <= int(raw) <= 365):
            bot.reply_to(message, "Отменено. Нужно целое число дней 1–365.")
            return
        days = int(raw)
        try:
            active_n = db_count_active_users()
        except Exception:  # noqa: BLE001
            active_n = "?"
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton(f"✅ Дать +{days} дн", callback_data=f"grant_all_go:{days}"),
            types.InlineKeyboardButton("Отмена", callback_data="admin_panel"),
        )
        bot.reply_to(
            message,
            f"Подтверди: добавить <b>+{days} дн</b> каждому из <b>{active_n}</b> активных?",
            parse_mode="HTML", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda call: bool(call.data) and call.data.startswith("grant_all_go:"))
    def callback_grant_all_go(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Шаг 3: применить массовое продление."""
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        try:
            days = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        if not (1 <= days <= 365):
            return
        try:
            affected = db_bulk_extend_active(days)
        except Exception as e:  # noqa: BLE001
            bot.edit_message_text(
                f"❌ Ошибка массового продления: {e!r}",
                call.message.chat.id, call.message.message_id,
            )
            return
        logger.info("Bulk extend: +%d дн → %d активным (by %s)", days, affected, call.from_user.id)
        bot.edit_message_text(
            f"✅ Готово: <b>+{days} дн</b> добавлено <b>{affected}</b> активным юзерам.",
            call.message.chat.id, call.message.message_id, parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("« В админ-панель", callback_data="admin_panel")
            ),
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_awg_conf")
    def callback_admin_awg_conf(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Запрашивает Telegram ID, затем генерирует и отправляет AmneziaWG .conf файл."""
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        _pending_awg_conf.add(call.from_user.id)
        bot.send_message(
            call.message.chat.id,
            "🔧 <b>AmneziaWG конфиг</b>\n\nВведи Telegram ID пользователя:",
            parse_mode="HTML",
        )

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _pending_awg_conf
    )
    def handle_pending_awg_conf(message: types.Message) -> None:  # type: ignore[override]
        """Получает Telegram ID от владельца и генерирует AmneziaWG конфиг."""
        if not message.from_user:
            return
        _pending_awg_conf.discard(message.from_user.id)
        text = (message.text or "").strip()
        try:
            target_tid = int(text)
        except ValueError:
            bot.reply_to(message, "❌ Некорректный ID. Должно быть число.")
            return
        bot.send_message(message.chat.id, f"⏳ Генерирую конфиг для <code>{target_tid}</code>…", parse_mode="HTML")
        try:
            peer = find_peer_by_telegram_id(target_tid, server_id="eu1")
            if peer and peer.active:
                _, cfg = regenerate_amneziawg_peer_and_config_for_user(target_tid, android_safe=False, server_id="eu1")
            else:
                _, cfg = create_amneziawg_peer_and_config_for_user(target_tid, android_safe=False, server_id="eu1")
        except WireGuardError as e:
            bot.send_message(message.chat.id, f"❌ Ошибка WireGuard: {e}", parse_mode="HTML")
            return
        except Exception as e:  # noqa: BLE001
            bot.send_message(message.chat.id, f"❌ Ошибка: {e!r}", parse_mode="HTML")
            return
        filename = f"awg_eu1_{target_tid}.conf"
        bot.send_document(
            message.chat.id,
            io.BytesIO(cfg.encode()),
            visible_file_name=filename,
            caption=f"✅ AmneziaWG конфиг для <code>{target_tid}</code>",
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_sync_sheets")
    def callback_admin_sync_sheets(call: types.CallbackQuery) -> None:  # type: ignore[override]
        """Запускает синхронизацию пользователей в Google Sheets."""
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            bot.answer_callback_query(call.id, "Только для владельца.")
            return
        bot.answer_callback_query(call.id)
        status_msg = bot.send_message(
            call.message.chat.id,
            "⏳ Синхронизирую пользователей в Google Sheets…",
        )
        try:
            from bot.google_sheets import sync_users_to_sheets
            result = sync_users_to_sheets()
        except Exception as exc:  # noqa: BLE001
            bot.edit_message_text(
                f"❌ Ошибка: {exc!r}",
                chat_id=call.message.chat.id,
                message_id=status_msg.message_id,
            )
            return
        if result.get("ok"):
            text = f"✅ {result.get('message', 'Готово')}"
        else:
            text = f"❌ Ошибка синхронизации:\n<code>{result.get('error', '?')}</code>"
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=status_msg.message_id,
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

    # ── Зачислить/списать дней юзеру: кнопки из админ-панели ──────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "admin_credit_user")
    def callback_admin_credit_user(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user or not is_owner(call.from_user.id, admin_id):
            return
        _pending_credit_user.add(call.from_user.id)
        bot.send_message(
            call.message.chat.id,
            "💳 <b>Зачислить / списать дней</b>\n\n"
            "Введи одним сообщением: <code>telegram_id дней [метка]</code>\n\n"
            "<b>Положительное число</b> — добавить дни (зачисление).\n"
            "<b>Отрицательное число</b> — списать дни (коррекция, например при возврате).\n\n"
            "Примеры:\n"
            "<code>151990415 30</code> — добавить 30 дней\n"
            "<code>151990415 -10 ошибочное зачисление</code> — списать 10 дней\n"
            "<code>151990415 30 СБП Иван 27.05</code> — с меткой\n\n"
            "Отправь «отмена» чтобы выйти.",
            parse_mode="HTML",
        )

    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _pending_credit_user
    )
    def handle_pending_credit_user(message: types.Message) -> None:  # type: ignore[override]
        """Парсит '<tid> <days> [note]' и зачисляет."""
        if not message.from_user:
            return
        _pending_credit_user.discard(message.from_user.id)
        raw = (message.text or "").strip()
        if raw.lower() in ("отмена", "cancel", "/cancel"):
            safe_reply(message, "Отменено.", reply_markup=_back_to_menu_markup())
            return
        parts = raw.split(maxsplit=2)
        if len(parts) < 2:
            safe_reply(message, "Формат: <code>tid дней [метка]</code>")
            return
        try:
            tid = int(parts[0])
            days = int(parts[1])
        except ValueError:
            safe_reply(message, "tid и дней должны быть числами. Попробуй ещё раз через кнопку.")
            return
        if days == 0 or abs(days) > 365:
            safe_reply(message, "Дней должно быть в диапазоне ±1…365 (0 не имеет смысла).")
            return
        note = parts[2] if len(parts) > 2 else ""
        is_debit = days < 0  # списание (отрицательное)

        user_row = db_find_user_by_telegram_id(tid)
        if not user_row:
            safe_reply(message, f"❌ Юзер с tid <code>{tid}</code> не найден в БД.")
            return

        import time as _time
        ext_id = f"manual-bot-{tid}-{int(_time.time())}"
        try:
            # Запись в payments — ТОЛЬКО для зачислений (положительные дни).
            # Списание = коррекция баланса, не платёж — payments-таблица
            # для бухгалтерии, дебеты туда не пишем.
            if not is_debit:
                db_record_payment(
                    provider="manual",
                    amount=200.0 * (days / 30.0),
                    currency="RUB",
                    telegram_id=tid,
                    external_id=ext_id,
                    plan="monthly",
                    days=days,
                    status="succeeded",
                )
            new_exp = db_extend_subscription(tid, days=days, plan="monthly", status="active")
            # Auto-restore revoked peers (enforcement gap hook).
            # Только при зачислении — при списании наоборот ничего не возвращаем.
            if not is_debit:
                _restore_and_notify(tid)
            # Реферал-бонус — только при зачислении. При списании не начисляем.
            inviter = None
            if not is_debit:
                inviter = db_apply_referral_bonus(tid, REFERRAL_REWARD_DAYS)
        except Exception as e:
            logger.exception("admin credit failed: %s", e)
            safe_reply(message, f"❌ Ошибка: {e}")
            return

        exp_str = (new_exp or "")[:10]
        uname = user_row.get("username") or "—"
        email = user_row.get("email") or "—"
        op_label = f"Списано: {days} дней" if is_debit else f"Зачислено: +{days} дней"
        summary = (
            f"✅ {op_label}.\n\n"
            f"👤 @{uname} (id <code>{tid}</code>)\n"
            f"📧 {email}\n"
            f"📅 Активна до <b>{exp_str}</b>"
        )
        if note:
            summary += f"\n📝 {note}"
        if inviter:
            summary += f"\n🎁 Реферал-бонус: +{REFERRAL_REWARD_DAYS} дн пригласителю (tid {inviter})"
        safe_reply(message, summary)

        # Уведомление юзеру (только при зачислении — при списании юзеру не
        # сообщаем автоматически, это административная коррекция).
        if not is_debit:
            try:
                bot.send_message(
                    tid,
                    f"✅ Подписка продлена на {days} дней — активна до <b>{exp_str}</b>.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("notify credited user failed: %s", e)

    # ═════════════════ §9 · КОМАНДЫ: статус/ЛК/инструкции/proxy ═════════════════
    @bot.message_handler(commands=["status"])
    def cmd_status(message: types.Message) -> None:  # type: ignore[override]
        """Показывает статус подписки пользователя."""
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return
        if not _is_authorized(message.from_user.id):
            safe_reply(message, "Нет доступа. Войди по email через /start.")
            return

        tid = message.from_user.id

        import math
        from datetime import datetime as _dt
        try:
            sub = db_get_subscription(tid) or {}
        except Exception as e:
            logger.warning("cmd_status: db_get_subscription failed: %s", e)
            sub = {}
        expires_at = sub.get("expires_at")
        sub_status = sub.get("subscription_status") or "none"
        # db_get_subscription не возвращает days_left — считаем сами (как в /api/account/info).
        days_left = 0
        if expires_at:
            try:
                delta = _dt.fromisoformat(expires_at) - _dt.utcnow()
                days_left = max(0, math.ceil(delta.total_seconds() / 86400.0))
            except (ValueError, TypeError):
                days_left = 0
        if not expires_at:
            # Бессрочный (grandfather) — отображаем как «Активна без срока»
            sub_line = "📅 <b>Подписка:</b> активна без срока (legacy-аккаунт)"
        else:
            exp_str = expires_at[:10]
            if days_left > 0:
                kind = "Пробный период" if sub_status == "trial" else "Подписка"
                icon = "⚠️" if days_left <= 3 else "✅"
                sub_line = f"{icon} <b>{kind}:</b> активна до {exp_str} ({days_left} дн осталось)"
            else:
                sub_line = (
                    f"🔴 <b>Подписка:</b> неактивна (истекла {exp_str}).\n"
                    f"Нажми «💳 Продлить подписку» в меню."
                )

        data_line = ""
        try:
            tds = db_get_trial_data_status(tid)
            if tds:
                data_line = (
                    f"\n📦 <b>Данные триала:</b> {tds['used_human']} / {tds['limit_gb']} ГБ "
                    f"(осталось {tds['remaining_gb']} ГБ)"
                )
        except Exception as e:
            logger.debug("trial data status failed: %s", e)
        status_text = f"{sub_line}{data_line}\n\n🌍 <b>Сервер:</b> Германия"
        safe_reply(message, status_text)

    @bot.message_handler(commands=["lk"])
    def cmd_lk(message: types.Message) -> None:  # type: ignore[override]
        """Открывает ЛК (Mini App). Доступно из команды-меню бота."""
        if not message.from_user:
            return
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🌐 Открыть личный кабинет",
                web_app=types.WebAppInfo(url=recovery_url),
            ),
        )
        markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        safe_reply(
            message,
            "🌐 Личный кабинет VPN Kronos — нажми кнопку ниже, чтобы открыть.",
            reply_markup=markup,
        )

    @bot.message_handler(commands=["instruction"])
    def cmd_instruction(message: types.Message) -> None:  # type: ignore[override]
        """Показывает выбор платформы для инструкции по подключению."""
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("📱 iOS", callback_data="instr_ios"),
            types.InlineKeyboardButton("🤖 Android", callback_data="instr_android"),
            types.InlineKeyboardButton("💻 ПК", callback_data="instr_pc"),
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
        # Принимаем как новые ("pc"), так и legacy ("windows") callbacks — оба → файл instruction_pc_short.txt.
        name_map = {"ios": "ios", "android": "android", "pc": "pc", "windows": "pc"}
        file_key = name_map.get(platform)
        if not file_key:
            bot.send_message(call.message.chat.id, "Неизвестная платформа.")
            return
        instr = _load_instruction_text(config.base_dir, file_key)
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("📱 iOS", callback_data="instr_ios"),
            types.InlineKeyboardButton("🤖 Android", callback_data="instr_android"),
            types.InlineKeyboardButton("💻 ПК", callback_data="instr_pc"),
        )
        markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        bot.send_message(call.message.chat.id, instr, parse_mode="HTML", reply_markup=markup)

    @bot.message_handler(commands=["proxy"])
    def cmd_proxy(message: types.Message) -> None:  # type: ignore[override]
        """Proxy для Telegram временно отключён: MTProxy задавлен фильтрацией
        (усилена 2026-06). Отдаём честный текст + увод на рабочий путь (VPN)."""
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔗 Подключить VPN", callback_data="vpn_quick"),
        )
        safe_reply(
            message,
            "📨 Proxy для Telegram временно недоступен.\n\n"
            "Из-за усиленной фильтрации лёгкий прокси сейчас не работает. "
            "Чтобы Telegram и остальное работало — подключись через VPN: "
            "он держится там, где прокси уже не проходит.\n\n"
            "Нажми «🔗 Подключить VPN» ниже или открой «📲 Получить VPN».",
            reply_markup=markup,
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

    # ══════════════════ §10 · МОБИЛЬНЫЙ VLESS (под оператора) ══════════════════
    @bot.message_handler(commands=["mobile_vpn"])
    def cmd_mobile_vpn(message: types.Message) -> None:  # type: ignore[override]
        """Показывает клавиатуру выбора оператора для мобильного VPN."""
        if not message.from_user:
            safe_reply(message, "Не удалось определить пользователя.")
            return

        if not _is_authorized(message.from_user.id):
            safe_reply(message, "Нет доступа. Войди по email через /start.")
            return

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Билайн", callback_data="mobile_op_beeline"),
            types.InlineKeyboardButton("МТС", callback_data="mobile_op_mts"),
            types.InlineKeyboardButton("Мегафон", callback_data="mobile_op_megafon"),
            types.InlineKeyboardButton("Yota", callback_data="mobile_op_yota"),
            types.InlineKeyboardButton("Т-Мобайл", callback_data="mobile_op_tmobile"),
            types.InlineKeyboardButton("Т2", callback_data="mobile_op_t2"),
            types.InlineKeyboardButton("Другой", callback_data="mobile_op_other"),
        )
        markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        safe_reply(
            message,
            "📱 <b>Мобильный VPN</b>\n\nВыбери своего оператора:",
            reply_markup=markup,
        )

    def _send_mobile_vless(chat_id: int, url: str, instruction_key: str) -> None:
        """Отправляет инструкцию и VLESS ссылку для мобильного VPN."""
        import html as _html
        instr = _load_instruction_text(config.base_dir, instruction_key)
        bot.send_message(chat_id, instr)
        try:
            safe_url = _html.escape(url)
            bot.send_message(chat_id, f"<code>{safe_url}</code>", parse_mode="HTML")
        except Exception as e:  # noqa: BLE001
            logger.exception("Не удалось отправить VLESS ссылку: %s", e)
            bot.send_message(chat_id, "Не удалось отправить ссылку. Напиши владельцу.")

    def _personalize_vless_for_bot(template_url: str, target_server: str, telegram_id: int) -> str:
        """
        Подставляет per-user UUID в vless://-template для бота.
        Mirror функции _personalize_vless_url в web/app.py. Если UUID только что
        создан — асинхронно триггерит sync_xray_users (~10 сек до готовности).
        """
        if not template_url or "@" not in template_url or not template_url.startswith("vless://"):
            return template_url
        try:
            existing = db_get_per_user_vless_uuid(telegram_id, target_server)
            per_user_uuid = db_get_or_create_vless_uuid(telegram_id, target_server)
            if not per_user_uuid:
                return template_url
            if not existing:
                # Только что создан → async sync Xray в фоне
                import subprocess as _sp
                import pathlib as _pl
                script_path = _pl.Path(__file__).resolve().parent.parent / "scripts" / "sync_xray_users.py"
                try:
                    _sp.Popen(
                        [sys.executable, str(script_path), "--server", target_server],
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                        start_new_session=True,
                    )
                    logger.info("Spawned async sync_xray_users for tid=%s server=%s", telegram_id, target_server)
                except Exception as e:
                    logger.warning("Failed to spawn sync: %s", e)
            head, rest = template_url.split("@", 1)
            return f"vless://{per_user_uuid}@{rest}"
        except Exception as e:
            logger.warning("personalize_vless_for_bot failed for tid=%s: %s", telegram_id, e)
            return template_url

    @bot.callback_query_handler(func=lambda call: call.data.startswith("mobile_op_"))
    def callback_mobile_operator(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        if not _is_authorized(call.from_user.id):
            bot.send_message(call.message.chat.id, "Нет доступа.")
            return

        op = call.data  # mobile_op_beeline / mobile_op_megafon / etc.

        # target_server — для подстановки per-user UUID:
        #   main — REALITY cloud.mail.ru (Мегафон/Yota)
        #   yc   — REALITY www.microsoft.com (остальные операторы)
        if op == "mobile_op_yota":
            # Yota подтверждённо работает через main REALITY (SNI=cloud.mail.ru) при БС.
            # См. SESSION_SUMMARY_2026-05-21.
            if config.vless_cdn_tls_share_url:
                template_url = config.vless_cdn_tls_share_url
                instruction_key = "vless_cdn"
                target_server = "main"
            elif config.vless_cdn_share_url:
                template_url = config.vless_cdn_share_url
                instruction_key = "vless_cdn"
                target_server = "main"
            else:
                template_url = config.vless_eu1_share_url
                instruction_key = "vless_reality"
                target_server = "eu1"
        elif op == "mobile_op_megafon":
            # Мегафон: 2026-05-22 выявлено что у Мегафон IP Timeweb (наш main) НЕ в whitelist
            # (TCP-таймаут). Пока выдаём то же что Yota, как best-effort.
            if config.vless_cdn_tls_share_url:
                template_url = config.vless_cdn_tls_share_url
                instruction_key = "vless_cdn"
                target_server = "main"
            elif config.vless_cdn_share_url:
                template_url = config.vless_cdn_share_url
                instruction_key = "vless_cdn"
                target_server = "main"
            else:
                template_url = config.vless_eu1_share_url
                instruction_key = "vless_reality"
                target_server = "eu1"
        elif op == "mobile_op_other":
            template_url = config.vless_eu1_share_url
            instruction_key = "vless_reality_other"
            target_server = "eu1"
        else:
            template_url = config.vless_eu1_share_url
            instruction_key = "vless_reality"
            target_server = "eu1"

        if not template_url:
            bot.send_message(
                call.message.chat.id,
                "Мобильный профиль пока не настроен. Напиши владельцу.",
            )
            return

        # Подстановка per-user UUID (с автосинхронизацией Xray в фоне)
        url = _personalize_vless_for_bot(template_url, target_server, call.from_user.id)

        # Proof-of-life для VLESS
        try:
            db_update_vless_requested_at(call.from_user.id)
        except Exception:
            pass

        _send_mobile_vless(call.message.chat.id, url, instruction_key)

    # ════════════════════ §11 · OWNER-КОМАНДЫ / ОБСЛУЖИВАНИЕ ════════════════════
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

    @bot.message_handler(commands=["migrate_reset"])
    def cmd_migrate_reset(message: types.Message) -> None:  # type: ignore[override]
        """
        Selective reset для миграции на @vpnkronos_bot: сбрасывает AmneziaWG peer,
        VLESS UUID и sub_token у юзеров, которые не прошли /start в новом боте
        (migrated_at IS NULL).

        Двушаговое подтверждение:
          /migrate_reset           → показывает превью кого тронем
          /migrate_reset RESET     → реально сбрасывает
        """
        if not message.from_user:
            return
        if not is_owner(message.from_user.id, admin_id):
            return  # silent — не выдаём наличие команды

        args = (message.text or "").split(maxsplit=1)
        confirmation = args[1].strip().upper() if len(args) > 1 else ""

        from .wireguard_peers import _remove_amneziawg_peer  # type: ignore[attr-defined]
        from .storage import delete_peer, get_all_peers
        from .vless_peers import remove_vless_client_for_user

        users = db_get_non_migrated_users()
        if not users:
            safe_reply(message, "✅ Все активные юзеры уже прошли /start в новом боте. Сбрасывать нечего.")
            return

        if confirmation != "RESET":
            # Превью без действий
            preview_lines = []
            for u in users[:15]:
                uname = u.get("username") or "no_username"
                preview_lines.append(f"  • @{uname} (id: <code>{u['telegram_id']}</code>)")
            preview = "\n".join(preview_lines)
            more = f"\n  ... и ещё {len(users) - 15}" if len(users) > 15 else ""
            text = (
                f"⚠️ Не-перешедших юзеров (migrated_at IS NULL): <b>{len(users)}</b>\n\n"
                f"{preview}{more}\n\n"
                f"Сброс выполнит:\n"
                f"  • удалит AmneziaWG peers у этих юзеров\n"
                f"  • удалит VLESS UUIDs (на серверах)\n"
                f"  • очистит sub_token (subscription-ссылка перестанет отдавать конфиг)\n\n"
                f"БД-запись юзера и email НЕ удаляются.\n\n"
                f"Подтвердить: <code>/migrate_reset RESET</code>"
            )
            safe_reply(message, text)
            return

        # Реально сбрасываем
        all_peers = get_all_peers()
        reset_summary = {"awg_removed": 0, "vless_removed": 0, "sub_tokens_cleared": 0, "errors": 0}
        for u in users:
            tid = int(u["telegram_id"])

            # 1. AmneziaWG peers (могут быть несколько — pc / ios / android)
            user_peers = [p for p in all_peers if p.telegram_id == tid and p.active]
            for peer in user_peers:
                try:
                    if peer.public_key:
                        _remove_amneziawg_peer(peer.public_key)
                    delete_peer(tid, peer.server_id, peer.platform or "pc")
                    reset_summary["awg_removed"] += 1
                except Exception as e:
                    logger.warning("migrate_reset: AWG remove tid=%s failed: %s", tid, e)
                    reset_summary["errors"] += 1

            # 2. VLESS клиент
            try:
                remove_vless_client_for_user(tid)
                reset_summary["vless_removed"] += 1
            except Exception as e:
                # Если у юзера не было VLESS — это норма, не считаем ошибкой
                logger.debug("migrate_reset: VLESS remove tid=%s: %s", tid, e)

            # 3. sub_token
            try:
                db_clear_sub_token(tid)
                reset_summary["sub_tokens_cleared"] += 1
            except Exception as e:
                logger.warning("migrate_reset: clear sub_token tid=%s failed: %s", tid, e)
                reset_summary["errors"] += 1

        # Сохраняем AmneziaWG-конфиг в контейнере (persistance после reboot)
        try:
            execute_server_command("eu1", "/opt/amnezia-save-conf.sh 2>/dev/null || true", timeout=10)
        except Exception as e:
            logger.warning("migrate_reset: amnezia-save-conf.sh failed: %s", e)

        safe_reply(
            message,
            f"✅ Selective reset выполнен.\n\n"
            f"  • AWG peers сброшено: {reset_summary['awg_removed']}\n"
            f"  • VLESS клиенты сброшено: {reset_summary['vless_removed']}\n"
            f"  • sub_token очищено: {reset_summary['sub_tokens_cleared']}\n"
            f"  • ошибок: {reset_summary['errors']}",
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

    # ── Telegram Stars payments ────────────────────────────────────────────
    # Цена/период должны совпадать с web/app.py (SUBSCRIPTION_DAYS_PER_PAYMENT=30,
    # STARS_MONTHLY_PRICE=150, REFERRAL_REWARD_DAYS=14).
    REFERRAL_REWARD_DAYS = 14

    # ══════════════════ §12 · ПЛАТЕЖИ (Stars + donation-claim) ══════════════════
    @bot.pre_checkout_query_handler(func=lambda q: True)
    def pre_checkout_handler(query: types.PreCheckoutQuery) -> None:
        """Аппрувим pre_checkout (TG требует ответ в 10 сек)."""
        try:
            bot.answer_pre_checkout_query(query.id, ok=True)
        except Exception as e:
            logger.exception("pre_checkout failed: %s", e)
            try:
                bot.answer_pre_checkout_query(query.id, ok=False, error_message="Внутренняя ошибка, попробуй позже.")
            except Exception:
                pass

    @bot.message_handler(content_types=["successful_payment"])
    def successful_payment_handler(message: types.Message) -> None:
        """
        Обработка успешной оплаты (Telegram Stars currency=XTR).
        Payload: 'stars_sub:<telegram_id>:<days>:<ts>'.
        """
        try:
            sp = message.successful_payment
            if not sp or not message.from_user:
                return
            payload = sp.invoice_payload or ""
            currency = sp.currency or ""
            total_amount = sp.total_amount or 0
            charge_id = sp.telegram_payment_charge_id or ""
            tid = message.from_user.id

            # Парсим payload
            parts = payload.split(":")
            if len(parts) < 4 or parts[0] != "stars_sub":
                logger.warning("Unexpected payment payload: %r", payload)
                safe_reply(message, "Платёж получен, но payload не распознан. Свяжись с владельцем.")
                return
            try:
                days = int(parts[2])
            except ValueError:
                days = 30
            # device_limit (тариф 3/5) — в новом payload это parts[3]
            # (stars_sub:tid:days:device_limit:ts). Старый формат (4 части,
            # stars_sub:tid:days:ts) → дефолт 5.
            device_limit = 5
            if len(parts) >= 5:
                try:
                    _dl = int(parts[3])
                    device_limit = _dl if _dl in (3, 5) else 5
                except ValueError:
                    device_limit = 5

            # Идемпотентность: если уже обрабатывали этот charge_id — выходим
            if charge_id and db_find_payment_by_external_id(charge_id):
                logger.info("Duplicate successful_payment for charge_id=%s, skipping", charge_id)
                return

            # Записываем платёж и продлеваем подписку
            db_record_payment(
                provider="stars",
                amount=float(total_amount),
                currency=currency,
                telegram_id=tid,
                external_id=charge_id,
                plan=f"stars_{device_limit}dev",
                days=days,
                status="succeeded",
            )
            new_exp = db_extend_subscription(
                tid, days=days, plan=f"stars_{device_limit}dev",
                status="active", device_limit=device_limit,
            )
            if tariffs.months_from_days(days) == 0:  # Stars-оплата тест-тарифа 49₽/7д — разовый
                try:
                    db_mark_test_used(tid)
                except Exception as e:
                    logger.warning("db_mark_test_used (stars) failed for %s: %s", tid, e)
            logger.info("Stars payment: tid=%s days=%s new_exp=%s charge=%s", tid, days, new_exp, charge_id)
            # Auto-restore revoked peers (enforcement gap hook).
            _restore_and_notify(tid)
            _send_subscription(message.chat.id, tid)  # выдать подписку — платящий сразу получает подключение

            # Реферал-бонус (если есть и ещё не выплачен)
            inviter_tid = db_apply_referral_bonus(tid, REFERRAL_REWARD_DAYS)

            # Уведомление пользователю — после ВСЕХ начислений, итоговая дата.
            # Если реф-бонус сработал — берём свежий expires_at из БД (он
            # включает +14 после db_apply_referral_bonus).
            if inviter_tid:
                final_sub = db_get_subscription(tid) or {}
                final_exp = final_sub.get("expires_at") or new_exp
                exp_str = (final_exp or "")[:10]
                safe_reply(
                    message,
                    f"✅ Оплата получена: {total_amount} ⭐\n"
                    f"Подписка продлена на {days} дней (оплата) + {REFERRAL_REWARD_DAYS} дней (реф-бонус).\n"
                    f"Активна до {exp_str}.",
                )
            else:
                exp_str = (new_exp or "")[:10]
                safe_reply(
                    message,
                    f"✅ Оплата получена: {total_amount} ⭐\n"
                    f"Подписка продлена на {days} дней (активна до {exp_str}).",
                )
            if inviter_tid:
                # Юзеру отдельно про реферал-бонус
                safe_reply(
                    message,
                    f"🎁 Бонус за приглашение: +{REFERRAL_REWARD_DAYS} дней тебе и пригласившему.",
                )
                # Уведомить пригласившего
                try:
                    bot.send_message(
                        inviter_tid,
                        f"🎁 Друг по твоей ссылке оплатил подписку — тебе +{REFERRAL_REWARD_DAYS} дней!",
                    )
                except Exception as e:
                    logger.warning("Failed to notify inviter %s: %s", inviter_tid, e)
        except Exception as e:
            logger.exception("successful_payment handler failed: %s", e)
            try:
                safe_reply(message, "Платёж получен, но при обработке возникла ошибка. Свяжись с владельцем.")
            except Exception:
                pass

    # ── Donation-flow: approve/decline inline-кнопки владельца ────────────────
    @bot.callback_query_handler(func=lambda call: call.data and (
        call.data.startswith("claim_approve:") or call.data.startswith("claim_decline:")
    ))
    def callback_claim_decision(call: types.CallbackQuery) -> None:  # type: ignore[override]
        # Только владелец может решать заявки.
        if not call.from_user or call.from_user.id != admin_id:
            bot.answer_callback_query(call.id, "Нет доступа", show_alert=False)
            return
        try:
            action, claim_id_str = call.data.split(":", 1)
            claim_id = int(claim_id_str)
        except (ValueError, AttributeError):
            bot.answer_callback_query(call.id, "Битые данные")
            return

        claim = db_get_claim_by_id(claim_id)
        if not claim:
            bot.answer_callback_query(call.id, "Заявка не найдена")
            return
        if claim.get("status") != "pending":
            bot.answer_callback_query(call.id, f"Уже {claim.get('status')}")
            # На всякий случай чистим кнопки если они ещё висят
            try:
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None,
                )
            except Exception:
                pass
            return

        tid = int(claim["telegram_id"])
        days = int(claim.get("days") or 30)
        dev_limit = int(claim.get("device_limit") or 5)
        _months = tariffs.months_from_days(days)  # 7→0 (тест), 30→1, 90→3
        _tariff = tariffs.get_tariff(dev_limit, _months)
        _price = float(_tariff["price_rub"]) if _tariff else 200.0
        _plan = f"{dev_limit}dev_{_months}m"
        user_row = db_find_user_by_telegram_id(tid) or {}
        uname = user_row.get("username") or "—"
        email = user_row.get("email") or "—"

        if action == "claim_approve":
            decided = db_decide_claim(claim_id, "approved")
            if not decided:
                bot.answer_callback_query(call.id, "Не удалось обновить заявку")
                return
            # Идемпотентность платежа — external_id из claim_id (никакого charge_id нет).
            try:
                db_record_payment(
                    provider="manual",
                    amount=_price,
                    currency="RUB",
                    telegram_id=tid,
                    external_id=f"claim:{claim_id}",
                    plan=_plan,
                    days=days,
                    status="succeeded",
                )
            except Exception as e:
                logger.warning("db_record_payment failed for claim %s: %s", claim_id, e)
            new_exp = db_extend_subscription(
                tid, days=days, plan=_plan, status="active", device_limit=dev_limit,
            )
            if _months == 0:  # тест-тариф 49₽/7д — разовый, помечаем использованным
                try:
                    db_mark_test_used(tid)
                except Exception as e:
                    logger.warning("db_mark_test_used (claim) failed for %s: %s", tid, e)
            # Auto-restore revoked peers (enforcement gap hook).
            _restore_and_notify(tid)
            _send_subscription(tid, tid)  # выдать подписку юзеру (claim-оплата → сразу подключение)
            inviter_tid = None
            try:
                inviter_tid = db_apply_referral_bonus(tid, REFERRAL_REWARD_DAYS)
            except Exception as e:
                logger.warning("referral bonus failed for claim %s: %s", claim_id, e)

            # Итоговая дата — после ВСЕХ начислений (включая реф-бонус если был).
            # Без этого юзер видел дату от db_extend_subscription, до +14 бонуса.
            if inviter_tid:
                final_sub = db_get_subscription(tid) or {}
                final_exp = final_sub.get("expires_at") or new_exp
            else:
                final_exp = new_exp
            exp_str = (final_exp or "")[:10]

            # Уведомляем юзера — одним сообщением с правильной итоговой датой.
            try:
                if inviter_tid:
                    bot.send_message(
                        tid,
                        f"✅ Оплата подтверждена.\n"
                        f"Подписка продлена на {days} дней (оплата) + {REFERRAL_REWARD_DAYS} дней (реф-бонус).\n"
                        f"Активна до {exp_str}.",
                    )
                else:
                    bot.send_message(
                        tid,
                        f"✅ Оплата подтверждена. Подписка продлена на {days} дней "
                        f"(активна до {exp_str}).",
                    )
            except Exception as e:
                logger.warning("notify user (approved claim) failed: %s", e)
            if inviter_tid:
                try:
                    bot.send_message(
                        tid,
                        f"🎁 Бонус за приглашение: +{REFERRAL_REWARD_DAYS} дней тебе и пригласившему.",
                    )
                    bot.send_message(
                        inviter_tid,
                        f"🎁 Друг по твоей ссылке оплатил подписку — тебе +{REFERRAL_REWARD_DAYS} дней!",
                    )
                except Exception as e:
                    logger.warning("notify inviter failed: %s", e)

            # Обновляем сообщение владельца — убираем кнопки + ставим статус.
            # Дата с учётом реф-бонуса, чтобы admin видел корректную итоговую.
            admin_extra = (
                f" + {REFERRAL_REWARD_DAYS} реф-бонус" if inviter_tid else ""
            )
            try:
                bot.edit_message_text(
                    f"✅ <b>ОДОБРЕНО</b> — @{uname} (id: <code>{tid}</code>)\n"
                    f"📧 {email}\n"
                    f"+{days} дн{admin_extra}, активна до {exp_str}",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("edit owner message (approved) failed: %s", e)
            bot.answer_callback_query(call.id, "Подтверждено")
            logger.info("Claim %s approved: tid=%s +%s дн → %s", claim_id, tid, days, exp_str)
            return

        if action == "claim_decline":
            decided = db_decide_claim(claim_id, "declined")
            if not decided:
                bot.answer_callback_query(call.id, "Не удалось обновить заявку")
                return
            try:
                bot.send_message(
                    tid,
                    "❌ Оплата не подтверждена. Проверь перевод и попробуй ещё раз "
                    "через кнопку «Я перевёл деньги», либо напиши @nikkronos.",
                )
            except Exception as e:
                logger.warning("notify user (declined claim) failed: %s", e)
            try:
                bot.edit_message_text(
                    f"❌ <b>ОТКЛОНЕНО</b> — @{uname} (id: <code>{tid}</code>)\n📧 {email}",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("edit owner message (declined) failed: %s", e)
            bot.answer_callback_query(call.id, "Отклонено")
            logger.info("Claim %s declined: tid=%s", claim_id, tid)
            return

    # ── Donation-flow: «Я оплатил» как inline-кнопка в ботовском payment-меню ─
    @bot.callback_query_handler(func=lambda call: bool(call.data) and call.data.startswith("pay_claim"))
    def callback_pay_claim(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        tid = call.from_user.id
        # Тариф из callback: pay_claim:{devices}:{months}. Без суффикса — 5 устр./1 мес.
        _d, _m = 5, 1
        _parts = (call.data or "").split(":")
        if len(_parts) == 3:
            try:
                _d, _m = int(_parts[1]), int(_parts[2])
            except ValueError:
                _d, _m = 5, 1
        _t = tariffs.get_tariff(_d, _m) or tariffs.get_tariff(5, 1)
        _days, _dev_limit, _price = _t["days"], _t["device_limit"], _t["price_rub"]
        if _m == 0 and db_is_test_used(tid):
            bot.send_message(call.message.chat.id, "🧪 Тест уже использован. Выбери обычный тариф через «Продлить подписку».")
            return
        # Проверим, что юзер вообще зарегистрирован
        user_row = db_find_user_by_telegram_id(tid)
        if not user_row:
            bot.send_message(call.message.chat.id, "Сначала зарегистрируйся через /start.")
            return
        existing = db_get_pending_claim(tid)
        claim_id = db_create_payment_claim(tid, days=_days, source="bot", device_limit=_dev_limit)
        if not claim_id:
            bot.send_message(call.message.chat.id, "Не удалось создать заявку. Напиши @nikkronos.")
            return

        # Шлём уведомление владельцу (как и в web flow)
        sub = db_get_subscription(tid) or {}
        status_line = format_subscription_status(sub)
        uname = user_row.get("username") or "—"
        email = user_row.get("email") or "—"
        text = (
            f"💳 <b>Новая оплата — {_dev_limit} устр., {tariffs.period_label(_m)} ({_price} ₽)</b>\n\n"
            f"👤 @{uname} (id: <code>{tid}</code>)\n"
            f"📧 {email}\n"
            f"📅 Сейчас: {status_line}\n"
            f"🪵 Источник: bot · +{_days} дн"
            + ("\n♻️ Переотправка существующей заявки" if existing else "")
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                f"✅ Подтвердить +{_days} дн · {_dev_limit} устр.",
                callback_data=f"claim_approve:{claim_id}",
            ),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"claim_decline:{claim_id}"),
        )
        try:
            bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            logger.warning("notify owner (bot claim) failed: %s", e)
        try:
            bot.send_message(
                call.message.chat.id,
                "✅ Заявка отправлена владельцу. Жди подтверждения — пришлю сюда сообщение, "
                "как только проверю поступление.",
            )
        except Exception:
            pass

    # ── Быстрый VPN: subscription URL + QR-картинка ────────────────────────
    def _send_subscription(chat_id: int, telegram_id: int) -> bool:
        """Отдаёт ссылку-подписку (QR + Happ-инструкция + кнопки). Доступ гейтит вызывающий
        (после активации триала/оплаты доступ уже active). Дублирует тело callback_vpn_quick —
        дедуп в рефакторе (#3 очереди)."""
        try:
            sub_token = db_ensure_sub_token(telegram_id)
        except Exception as e:
            logger.exception("db_ensure_sub_token failed for %s: %s", telegram_id, e)
            sub_token = None
        if not sub_token:
            bot.send_message(chat_id, "Не удалось получить ссылку. Напиши @nikkronos.")
            return False
        try:
            db_update_vless_requested_at(telegram_id)
        except Exception:
            pass
        rec_url = getattr(config, "vpn_recovery_url", None) or "https://supportkronos.online:8443/recovery"
        sub_base = rec_url.rsplit("/recovery", 1)[0]
        sub_url = f"{sub_base}/sub/{sub_token}"
        caption = (
            "🔗 <b>Подключить VPN — одна ссылка</b>\n\n"
            "Импортируй в <b>Happ</b> (happ.su): «+» → по ссылке или из буфера. "
            "Приложение само выберет рабочий сервер и подтянет обновления."
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔄 Не работает", callback_data="menu_regen"),
            types.InlineKeyboardButton("🔌 Другие способы подключения", callback_data="menu_other_connect"),
            types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"),
        )
        try:
            import qrcode
            from io import BytesIO
            img = qrcode.make(sub_url)
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            bot.send_photo(chat_id, photo=buf, caption=caption, parse_mode="HTML")
        except Exception as e:
            logger.exception("send_subscription QR failed: %s", e)
            bot.send_message(chat_id, caption, parse_mode="HTML", disable_web_page_preview=True)
        bot.send_message(chat_id, sub_url, reply_markup=markup, disable_web_page_preview=True)
        return True

    @bot.callback_query_handler(func=lambda call: call.data == "vpn_quick")
    def callback_vpn_quick(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        if not _is_authorized(call.from_user.id):
            bot.send_message(call.message.chat.id, "Нет доступа.")
            return
        if not _check_access_or_block(call.message.chat.id, call.from_user.id):
            return
        tid = call.from_user.id
        try:
            sub_token = db_ensure_sub_token(tid)
        except Exception as e:
            logger.exception("db_ensure_sub_token failed for %s: %s", tid, e)
            sub_token = None
        if not sub_token:
            bot.send_message(call.message.chat.id, "Не удалось получить ссылку. Напиши @nikkronos.")
            return

        # Proof-of-life для VLESS — subscription URL = VLESS-канал. Авто-refresh
        # самого URL клиентом дублирует отметку в web/app.py (/sub/<token>),
        # эта же ставится в момент manual-выдачи через бот.
        try:
            db_update_vless_requested_at(tid)
        except Exception:
            pass

        # Базовый URL берём из recovery_url (env), вырезаем суффикс /recovery
        rec_url = getattr(config, "vpn_recovery_url", None) or "https://supportkronos.online:8443/recovery"
        sub_base = rec_url.rsplit("/recovery", 1)[0]
        sub_url = f"{sub_base}/sub/{sub_token}"

        caption = (
            "🔗 <b>Подключить VPN — одна ссылка</b>\n\n"
            "Импортируй в <b>Happ</b> (happ.su): «+» → по ссылке или из буфера. "
            "Приложение само выберет рабочий сервер и подтянет обновления."
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔄 Не работает", callback_data="menu_regen"),
            types.InlineKeyboardButton("🔌 Другие способы подключения", callback_data="menu_other_connect"),
            types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"),
        )

        # 1. QR картинка с инструкцией
        try:
            import qrcode
            from io import BytesIO
            img = qrcode.make(sub_url)
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            bot.send_photo(
                call.message.chat.id,
                photo=buf,
                caption=caption,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("vpn_quick QR failed: %s", e)
            bot.send_message(
                call.message.chat.id,
                caption,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        # 2. Сама ссылка — отдельным сообщением для удобного тап-копирования.
        # Plain text (без HTML-эскейпа в code-блок) — тап-удержание выделяет всю строку.
        bot.send_message(
            call.message.chat.id,
            sub_url,
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    # ── Donation-flow: выбор тарифа (устройства → срок) → реквизиты ───────────
    def _pay_devices_kb(uid: int) -> types.InlineKeyboardMarkup:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📱 3 устройства", callback_data="paytar_dev:3"),
            types.InlineKeyboardButton("📱 5 устройств", callback_data="paytar_dev:5"),
        )
        kb.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        return kb

    @bot.callback_query_handler(func=lambda call: call.data == "pay_show")
    def callback_pay_show(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user:
            return
        bot.send_message(
            call.message.chat.id,
            "💳 <b>Оформить подписку</b>\n\n"
            "Шаг 1 — сколько устройств подключаешь?\n"
            "3 — дешевле; 5 — для нескольких гаджетов или семьи.",
            parse_mode="HTML", reply_markup=_pay_devices_kb(call.from_user.id),
        )

    @bot.callback_query_handler(func=lambda call: bool(call.data) and call.data.startswith("paytar_dev:"))
    def callback_pay_devices(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        try:
            d = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        t1, t3 = tariffs.get_tariff(d, 1), tariffs.get_tariff(d, 3)
        if not t1 or not t3:
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton(f"1 месяц — {t1['price_rub']} ₽", callback_data=f"paytar:{d}:1"),
            types.InlineKeyboardButton(
                f"3 месяца — {t3['price_rub']} ₽ ({t3['price_rub'] // 3} ₽/мес)",
                callback_data=f"paytar:{d}:3"),
        )
        kb.add(types.InlineKeyboardButton("« Назад", callback_data="pay_show"))
        bot.send_message(
            call.message.chat.id,
            f"💳 <b>{d} устройств</b>\n\nШаг 2 — на какой срок? (3 месяца выгоднее)",
            parse_mode="HTML", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda call: bool(call.data) and call.data.startswith("paytar:"))
    def callback_pay_tariff(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        try:
            _, ds, ms = call.data.split(":")
            d, m = int(ds), int(ms)
        except (ValueError, IndexError):
            return
        t = tariffs.get_tariff(d, m)
        if not t:
            return
        if m == 0 and call.from_user and db_is_test_used(call.from_user.id):
            bot.send_message(call.message.chat.id, "🧪 Бесплатный тест уже был использован — выбери обычный тариф.")
            return
        price = t["price_rub"]
        per = f" ({price // m} ₽/мес)" if m == 3 else ""   # помесячная только для 3 мес (m=0 → деление на 0!)
        text = (
            f"💳 <b>{d} устр. · {tariffs.period_label(m)}</b>\n"
            f"Цена: <b>{price} ₽</b>{per} · доступ на {t['days']} дней\n\n"
            "Переведи на Т-Банк любым способом:\n"
            "📱 СБП по телефону: <code>+79213032918</code>\n"
            "💳 Карта: <code>2200 7007 6046 4759</code>\n\n"
            f"⚠️ Переведи <b>ровно {price} ₽</b>, затем нажми кнопку — владелец проверит и зачислит."
        )
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(f"✅ Я перевёл {price} ₽", callback_data=f"pay_claim:{d}:{m}"))
        kb.add(types.InlineKeyboardButton("« Назад", callback_data=("pay_show" if m == 0 else f"paytar_dev:{d}")))
        kb.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        try:
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            logger.exception("pay_tariff failed: %s", e)

    # ── Support: Variant B — двусторонняя переписка через бот ──────────────────

    # ═════════════════════════ §13 · SUPPORT / HELPDESK ═════════════════════════
    def _open_support_flow(chat_id: int, telegram_id: int) -> None:
        """
        Стартует support-флоу: если есть открытый тикет — просит просто написать сообщение,
        иначе создаёт новый тикет и просит первое сообщение.
        """
        existing = db_get_open_ticket(telegram_id)
        if existing:
            # У юзера уже открыт тикет — переводим его в режим продолжения переписки.
            ticket_id = int(existing["id"])
            _support_user_state[telegram_id] = {"step": "awaiting_message", "ticket_id": ticket_id}
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✕ Отмена", callback_data="support_cancel"))
            bot.send_message(
                chat_id,
                f"🆘 У тебя уже открыт тикет #{ticket_id}.\n\n"
                "Просто напиши новое сообщение в этот чат — оно дойдёт до владельца.\n"
                "Прикрепить можно одно фото с подписью.",
                reply_markup=markup,
            )
            return
        # Новый тикет (создаём по факту первого сообщения, чтобы не плодить пустых).
        _support_user_state[telegram_id] = {"step": "awaiting_message", "ticket_id": None}
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✕ Отмена", callback_data="support_cancel"))
        bot.send_message(
            chat_id,
            "🆘 <b>Поддержка</b>\n\n"
            "Опиши проблему одним сообщением. Прикрепить можно одно фото с подписью.\n"
            "Ответ придёт в этот чат.",
            parse_mode="HTML",
            reply_markup=markup,
        )

    @bot.callback_query_handler(func=lambda call: call.data == "support_cancel")
    def callback_support_cancel(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if call.from_user:
            _support_user_state.pop(call.from_user.id, None)
        bot.send_message(call.message.chat.id, "Отменено.")
        if call.from_user:
            _send_main_menu_for_tid(call.message.chat.id, call.from_user.id)

    def _notify_owner_about_support_message(
        ticket_id: int,
        user_tid: int,
        msg_text: Optional[str],
        photo_file_id: Optional[str],
    ) -> None:
        """Шлёт owner-у уведомление о новом сообщении в тикете + inline-кнопки."""
        user_row = db_find_user_by_telegram_id(user_tid) or {}
        uname = user_row.get("username") or "—"
        email = user_row.get("email") or "—"
        sub = db_get_subscription(user_tid) or {}
        expires_at = (sub.get("expires_at") or "")[:10] or "—"
        if sub.get("grandfathered") or not sub.get("expires_at"):
            sub_line = "Бессрочный (grandfather)"
        else:
            sub_line = f"до {expires_at}"

        text = (
            f"🆘 <b>Тикет #{ticket_id}</b> — новое сообщение\n\n"
            f"👤 @{uname} (id: <code>{user_tid}</code>)\n"
            f"📧 {email}\n"
            f"📅 Подписка: {sub_line}\n\n"
        )
        if msg_text:
            # Обрезаем длинные сообщения для inline-уведомления
            preview = msg_text[:1500] + ("…" if len(msg_text) > 1500 else "")
            import html as _html
            text += f"<b>Текст:</b>\n{_html.escape(preview)}"
        else:
            text += "<i>(только фото)</i>"

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✉️ Ответить", callback_data=f"support_reply:{ticket_id}"),
            types.InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"support_close:{ticket_id}"),
            types.InlineKeyboardButton("📜 История", callback_data=f"support_history:{ticket_id}"),
        )

        try:
            if photo_file_id:
                # Фото с caption-уведомлением
                bot.send_photo(
                    admin_id,
                    photo=photo_file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            logger.warning("notify owner support: %s", e)

    # Текстовые/фото сообщения от юзера в режиме support.
    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _support_user_state,
        content_types=["text", "photo"],
    )
    def handle_support_user_message(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        tid = message.from_user.id
        state = _support_user_state.pop(tid, None) or {}
        ticket_id = state.get("ticket_id")

        # Парсим текст и фото
        text_part: Optional[str] = None
        photo_part: Optional[str] = None
        if message.content_type == "photo":
            # Берём фото наибольшего размера
            if message.photo:
                photo_part = message.photo[-1].file_id
            text_part = (message.caption or "").strip() or None
        else:
            text_part = (message.text or "").strip() or None

        if not text_part and not photo_part:
            # Пустое сообщение — возвращаем юзера в режим ожидания
            _support_user_state[tid] = state
            safe_reply(message, "Пустое сообщение. Напиши текст или прикрепи фото с подписью.")
            return

        # Создаём тикет, если ещё нет (lazy create)
        if not ticket_id:
            ticket_id = db_create_ticket(tid)

        db_add_support_message(ticket_id, "user", text=text_part, photo_file_id=photo_part)

        # ack юзеру + одна reply-кнопка чтобы продолжить
        ack_markup = types.InlineKeyboardMarkup()
        ack_markup.add(types.InlineKeyboardButton("« Главное меню", callback_data="go_main_menu"))
        safe_reply(
            message,
            f"✅ Сообщение отправлено в поддержку (тикет #{ticket_id}).\n"
            f"Ответ придёт в этот чат. Можешь сразу написать ещё — будет добавлено в тот же тикет.",
            reply_markup=ack_markup,
        )

        # Оставляем юзера в state ожидания продолжения (чтобы next message сразу шёл в этот же ticket)
        _support_user_state[tid] = {"step": "awaiting_message", "ticket_id": ticket_id}

        # Форвардим owner-у
        _notify_owner_about_support_message(ticket_id, tid, text_part, photo_part)

    # Owner: «✉️ Ответить» → переводим в состояние awaiting reply text/photo.
    @bot.callback_query_handler(func=lambda call: call.data.startswith("support_reply:"))
    def callback_support_reply(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user or call.from_user.id != admin_id:
            return
        try:
            ticket_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        ticket = db_get_ticket_by_id(ticket_id)
        if not ticket:
            bot.send_message(admin_id, "Тикет не найден.")
            return
        _support_reply_state[admin_id] = {"ticket_id": ticket_id, "user_tid": int(ticket["telegram_id"])}
        bot.send_message(
            admin_id,
            f"✉️ Ответ на тикет #{ticket_id} (юзер id: <code>{ticket['telegram_id']}</code>).\n\n"
            "Напиши текст или прикрепи фото с подписью. /cancel — отмена.",
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("support_close:"))
    def callback_support_close(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user or call.from_user.id != admin_id:
            return
        try:
            ticket_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        ticket = db_get_ticket_by_id(ticket_id)
        if not ticket:
            bot.send_message(admin_id, "Тикет не найден.")
            return
        if ticket["status"] != "open":
            bot.send_message(admin_id, f"Тикет #{ticket_id} уже закрыт.")
            return
        db_close_ticket(ticket_id)
        user_tid = int(ticket["telegram_id"])
        # Уведомление юзеру
        try:
            bot.send_message(
                user_tid,
                f"✅ Тикет #{ticket_id} закрыт. Если что-то ещё — напиши «🆘 Поддержка» в меню, "
                f"открою новый.",
            )
        except Exception as e:
            logger.warning("notify user about close: %s", e)
        bot.send_message(admin_id, f"✅ Тикет #{ticket_id} закрыт.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("support_history:"))
    def callback_support_history(call: types.CallbackQuery) -> None:  # type: ignore[override]
        bot.answer_callback_query(call.id)
        if not call.from_user or call.from_user.id != admin_id:
            return
        try:
            ticket_id = int(call.data.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        msgs = db_get_ticket_messages(ticket_id, limit=30)
        if not msgs:
            bot.send_message(admin_id, "История пуста.")
            return
        import html as _html
        lines = [f"📜 <b>История тикета #{ticket_id}</b>\n"]
        for m in msgs:
            who = "👤" if m["sender"] == "user" else "💬"
            ts = (m.get("created_at") or "")[:16]
            body = (m.get("text") or "").strip()
            if m.get("photo_file_id"):
                body = (body + " [+фото]").strip()
            lines.append(f"{who} <i>{ts}</i>\n{_html.escape(body)[:500]}\n")
        bot.send_message(admin_id, "\n".join(lines), parse_mode="HTML")

    # Owner: ответ на тикет (текст/фото)
    @bot.message_handler(
        func=lambda msg: msg.from_user is not None and msg.from_user.id in _support_reply_state,
        content_types=["text", "photo"],
    )
    def handle_support_owner_reply(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user:
            return
        if message.from_user.id != admin_id:
            return
        # /cancel — отмена
        if message.content_type == "text" and (message.text or "").strip().lower() in ("/cancel", "отмена"):
            _support_reply_state.pop(admin_id, None)
            safe_reply(message, "Отменено.", reply_markup=_back_to_menu_markup())
            return
        state = _support_reply_state.pop(admin_id, None) or {}
        ticket_id = state.get("ticket_id")
        user_tid = state.get("user_tid")
        if not ticket_id or not user_tid:
            return

        text_part: Optional[str] = None
        photo_part: Optional[str] = None
        if message.content_type == "photo":
            if message.photo:
                photo_part = message.photo[-1].file_id
            text_part = (message.caption or "").strip() or None
        else:
            text_part = (message.text or "").strip() or None

        if not text_part and not photo_part:
            _support_reply_state[admin_id] = state
            safe_reply(message, "Пусто. Напиши текст или прикрепи фото с подписью. /cancel — отмена.")
            return

        # Сохраняем сообщение в тикет
        db_add_support_message(ticket_id, "owner", text=text_part, photo_file_id=photo_part)

        # Доставляем юзеру
        prefix = f"💬 <b>Ответ от поддержки</b> (тикет #{ticket_id}):"
        try:
            if photo_part:
                caption = f"{prefix}\n\n" + (text_part or "")
                bot.send_photo(user_tid, photo=photo_part, caption=caption, parse_mode="HTML")
            else:
                bot.send_message(
                    user_tid,
                    f"{prefix}\n\n{text_part}",
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.warning("deliver reply to user %s: %s", user_tid, e)
            safe_reply(message, f"⚠️ Не удалось доставить юзеру: {e}")
            return

        safe_reply(message, f"✅ Ответ доставлен юзеру (тикет #{ticket_id}).")
        # Возвращаем юзера в режим ожидания продолжения треда (если он не закрыл/менял состояние)
        if user_tid not in _support_user_state:
            _support_user_state[user_tid] = {"step": "awaiting_message", "ticket_id": ticket_id}

    # ── Owner commands ────────────────────────────────────────────────────────

    @bot.message_handler(commands=["support_list"])
    def cmd_support_list(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user or not is_owner(message.from_user.id, admin_id):
            return
        tickets = db_get_open_tickets()
        if not tickets:
            safe_reply(message, "Открытых тикетов нет.")
            return
        lines = [f"📋 <b>Открытые тикеты ({len(tickets)}):</b>\n"]
        for t in tickets[:20]:
            uname = t.get("username") or "—"
            last = (t.get("last_message_at") or t.get("created_at") or "")[:16]
            lines.append(f"#{t['id']} — @{uname} (id <code>{t['telegram_id']}</code>) — {last}")
        if len(tickets) > 20:
            lines.append(f"\n…и ещё {len(tickets) - 20}")
        safe_reply(message, "\n".join(lines))

    @bot.message_handler(commands=["support_view"])
    def cmd_support_view(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user or not is_owner(message.from_user.id, admin_id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            safe_reply(message, "Формат: <code>/support_view N</code> (где N — номер тикета)")
            return
        ticket_id = int(parts[1].strip())
        ticket = db_get_ticket_by_id(ticket_id)
        if not ticket:
            safe_reply(message, "Тикет не найден.")
            return
        msgs = db_get_ticket_messages(ticket_id, limit=50)
        import html as _html
        head = (
            f"📜 <b>Тикет #{ticket_id}</b> ({ticket['status']})\n"
            f"Юзер id: <code>{ticket['telegram_id']}</code>\n"
            f"Создан: {ticket['created_at']}\n"
        )
        if ticket.get("closed_at"):
            head += f"Закрыт: {ticket['closed_at']}\n"
        head += f"Сообщений: {len(msgs)}\n"

        body_lines = []
        for m in msgs:
            who = "👤 юзер" if m["sender"] == "user" else "💬 owner"
            ts = (m.get("created_at") or "")[:16]
            t = (m.get("text") or "").strip()
            if m.get("photo_file_id"):
                t = (t + " [+фото]").strip()
            body_lines.append(f"<b>{who}</b> <i>{ts}</i>\n{_html.escape(t)[:500]}\n")

        safe_reply(message, head + "\n" + "\n".join(body_lines))

    @bot.message_handler(commands=["support_close"])
    def cmd_support_close(message: types.Message) -> None:  # type: ignore[override]
        if not message.from_user or not is_owner(message.from_user.id, admin_id):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            safe_reply(message, "Формат: <code>/support_close N</code>")
            return
        ticket_id = int(parts[1].strip())
        ticket = db_get_ticket_by_id(ticket_id)
        if not ticket:
            safe_reply(message, "Тикет не найден.")
            return
        if ticket["status"] != "open":
            safe_reply(message, f"Тикет #{ticket_id} уже закрыт.")
            return
        db_close_ticket(ticket_id)
        user_tid = int(ticket["telegram_id"])
        try:
            bot.send_message(
                user_tid,
                f"✅ Тикет #{ticket_id} закрыт. Если что-то ещё — «🆘 Поддержка» в меню.",
            )
        except Exception:
            pass
        safe_reply(message, f"✅ Тикет #{ticket_id} закрыт.")

    # ════════════════════════ §14 · POLLING / BOOTSTRAP ════════════════════════
    logger.info("Starting VPN Telegram bot (pyTelegramBotAPI)...")
    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()

