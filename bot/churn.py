"""Опрос причин отвала / недо-онбординга — единый источник текстов, причин и
клавиатур. Используется и ботом (telebot markup), и `expiry_reminder.py`
(reply_markup как dict для TG HTTP API). Без зависимостей (как tariffs.py).

Два вида (kind):
  "churn" — пользовавшиеся, не продлили: «почему не оплатил?»
  "onb"   — не прошли онбординг: «что помешало закончить настройку?»

callback_data кнопок: `drop:<kind>:<code>` (обрабатывает бот).
Хранится человекочитаемый label (для Google Sheets).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

CHURN_TEXT = (
    "Жаль, что доступ закончился 😔\n\n"
    "Что стало причиной? Один тап — поможет нам стать лучше."
)
CHURN_REASONS: List[Tuple[str, str]] = [
    ("not_needed", "Уже не нужен"),
    ("expensive", "Дорого"),
    ("not_working", "Не работало / глючило"),
    ("found_other", "Нашёл другой сервис"),
    ("forgot", "Забыл продлить"),
    ("other", "Другое"),
]

ONB_TEXT = (
    "Похоже, настройка осталась незаконченной 🤔\n\n"
    "Что помешало? Один тап — поможет нам стать лучше."
)
ONB_REASONS: List[Tuple[str, str]] = [
    ("too_hard", "Сложно / долго"),
    ("changed_mind", "Передумал"),
    ("no_email", "Код на email не пришёл"),
    ("just_looking", "Просто смотрел"),
    ("other", "Другое"),
]


def reasons_for(kind: str) -> List[Tuple[str, str]]:
    return CHURN_REASONS if kind == "churn" else ONB_REASONS


def text_for(kind: str) -> str:
    return CHURN_TEXT if kind == "churn" else ONB_TEXT


def label_for(kind: str, code: str) -> Optional[str]:
    """Человекочитаемый текст причины по коду (для хранения/Sheets)."""
    for c, label in reasons_for(kind):
        if c == code:
            return label
    return None


def needs_free_text(kind: str, code: str) -> bool:
    """Нужен ли уточняющий свободный текст после выбора причины."""
    if kind == "churn":
        return code in ("not_working", "other")
    return code in ("no_email", "other")


def inline_keyboard_dict(kind: str) -> Dict:
    """reply_markup как dict — для TG HTTP API (expiry_reminder.py)."""
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": f"drop:{kind}:{code}"}]
            for code, label in reasons_for(kind)
        ]
    }
