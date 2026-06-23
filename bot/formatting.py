"""Общие форматтеры отображения (бот + веб-панель).

Чистые функции без сайд-эффектов. Дедуп из bot/main.py и web/app.py
(рефактор #3, Tier 1). См. docs/plan-refactor-scope.md.
"""


def format_subscription_status(sub: dict | None) -> str:
    """Человекочитаемый статус подписки для уведомлений владельцу.

    sub — результат db_get_subscription (ключи days_left / expires_at / grandfathered).
    Поведение идентично прежним инлайн-блокам в claim-флоу бота и ЛК
    (byte-for-byte: те же строки на тех же входах).
    """
    sub = sub or {}
    days_left = sub.get("days_left", 0) or 0
    expires_at = (sub.get("expires_at") or "")[:10] or "—"
    if sub.get("grandfathered"):
        return "Бессрочный (grandfather)"
    if days_left > 0:
        return f"до {expires_at} (осталось {days_left} дн)"
    return "Подписка неактивна"
