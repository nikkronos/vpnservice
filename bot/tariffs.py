"""Тарифная сетка VPN Kronos — единый источник правды для бота и веб-ЛК.

Две оси: число устройств (3/5) × срок (1/3 мес). Цену ВСЕГДА считаем здесь, на
сервере — клиент присылает только (devices, months), но не цену (защита от
подмены). Stars-цены округлены для удобства.

Импортируется и `bot/main.py`, и `web/app.py`.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# (devices, months) -> параметры тарифа.
#   days         — на сколько продлевать подписку
#   price_rub    — цена в рублях (ручная оплата СБП/карта)
#   price_stars  — цена в Telegram Stars (XTR), округлено
#   device_limit — лимит именованных устройств (= devices)
TARIFFS: Dict[Tuple[int, int], Dict[str, int]] = {
    (3, 1): {"days": 30, "price_rub": 199, "price_stars": 150, "device_limit": 3},
    (5, 1): {"days": 30, "price_rub": 249, "price_stars": 200, "device_limit": 5},
    (3, 3): {"days": 90, "price_rub": 449, "price_stars": 350, "device_limit": 3},
    (5, 3): {"days": 90, "price_rub": 599, "price_stars": 450, "device_limit": 5},
}

VALID_DEVICES: Tuple[int, ...] = (3, 5)
VALID_MONTHS: Tuple[int, ...] = (1, 3)
# Лимит по умолчанию: грандфазер существующих юзеров + триал (щедро, тариф
# выбирается при первой оплате). НЕ менять без миграции users.device_limit.
DEFAULT_DEVICE_LIMIT = 5


def get_tariff(devices: int, months: int) -> Optional[Dict[str, int]]:
    """Параметры тарифа по (devices, months) или None, если пара невалидна."""
    try:
        return TARIFFS.get((int(devices), int(months)))
    except (TypeError, ValueError):
        return None


def tariff_short(devices: int, months: int) -> str:
    """Короткая подпись тарифа для кнопок/сообщений."""
    t = get_tariff(devices, months)
    if not t:
        return f"{devices} устр. · {months} мес"
    per = "" if months == 1 else f" · {t['price_rub'] // months}₽/мес"
    return f"{devices} устр. · {months} мес — {t['price_rub']}₽{per}"


def encode_payload(devices: int, months: int) -> str:
    """Кодирование тарифа в invoice_payload Stars-платежа."""
    return f"tariff:{int(devices)}:{int(months)}"


def decode_payload(payload: str) -> Optional[Tuple[int, int]]:
    """Разбор invoice_payload Stars-платежа → (devices, months) или None.

    Валидируется по таблице — неизвестный/битый payload вернёт None.
    """
    try:
        parts = (payload or "").split(":")
        if len(parts) == 3 and parts[0] == "tariff":
            d, m = int(parts[1]), int(parts[2])
            if (d, m) in TARIFFS:
                return d, m
    except (TypeError, ValueError):
        pass
    return None
