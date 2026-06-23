# План рефактора (#3) — scope-оценка

> 2026-06-23, read-only анализ. Цель: убрать **дубли и боль** (правишь логику в одном месте, не в двух → меньше багов), НЕ «красивая архитектура». На ~15 платящих полный распил монолитов = оверинжиниринг.

## Карта

**`bot/main.py` (4135 строк).** Почти всё — внутри одной `main()` (с 203) с ~80 вложенными функциями/хендлерами (замыкания над `bot`, `admin_id`, state-словарями). Module-level: только 4 хелпера (111–203). Группы внутри `main()`:
- auth/меню (233–447) · онбординг+use_case+churn (447–893) · restore/referral (893–971) · `cmd_start` (971) · доставка конфигов (1035–1413) · профили/девайсы (1413–1699) · email-флоу (1699–1834) · **admin-блок** (1834–2446) · команды (status/lk/proxy/mobile/users/broadcast/stats…) (2446–3204) · **платежи/donation-claim** (3204–3700+).

**`web/app.py` (2470).** Top-level (чище). Группы: хелперы (147–461) · публичные страницы+`/admin` (461–551) · API servers/services/users/traffic/stats (551–1059) · recovery API (1159–1472) · account/billing (1472–1855) · `/admin/credit` (1855–2023) · vless/`/sub`/auth/admin-API (2023–2470).

## Кандидаты (ранжир польза/риск)

### Tier 1 — дедуп чистых хелперов (низкий риск, делаем первыми)
- **status-line** (`days_left`/`expires_at`/grandfather → строка) — ✅ подтверждённый дубль: `bot/main.py` claim (~3526) + `web/app.py` claim (~1692) + ещё в `cmd_status`/`/api/account/info`. → `format_subscription_status(sub)`.
- **notify-inviter** — `_notify_inviter_about_signup_from_bot` (bot 943) ↔ `_notify_inviter_about_signup` (web 162). Имена-близнецы (сверить тела при резке).
- **device-autoname** — `_device_autoname` (bot 1602) ↔ `_device_autoname_web` (web 1255). То же (сверить).
- **VLESS-персонализация** — `_personalize_vless_for_bot` (bot 2706) ↔ `_personalize_vless_url`/`_replace_uuid_in_vless_url` (web 2054/2101). Пересекается (сверить).

### Tier 2 — общий билдер (средний риск)
- **donation-notify** — ✅ подтверждённый дубль: текст «💳 Новая оплата» + approve/decline в `bot/main.py` (~3491) и `web/app.py` (~1654). → общий `build_claim_notify_text()` + константы callback_data; markup каждая сторона строит свой (telebot `InlineKeyboardMarkup` vs dict — это и есть единственное реальное различие).
- **`_send_subscription`** (bot 3563) — по пометке в CLAUDE дублирует тело `callback_vpn_quick`. Дедуп внутри bot.

### Tier 3 — структурный распил (ВЫСОКИЙ риск — НЕ сейчас)
- **`bot/main.py`: распил `main()`** на модули по группам хендлеров (admin/payments/onboarding/devices) через `register(bot, deps)`. Риск: привязка декораторов + замыкания + общее состояние (тут был баг `/start`). ROI на текущем масштабе низкий.
- **`web/app.py`: Flask Blueprints** по группам. Средний риск (регистрация роутов).

## Рекомендация
**Сделать Tier 1 (+ опц. Tier 2). Tier 3 — отложить** (делать только если конкретная зона начнёт реально болеть/часто кусать). Куда выносить общее: новый модуль **`bot/formatting.py`** (или `shared.py`), импортируют и bot, и web (web уже импортит `bot.*`).

## Процедура резки (после «ок» владельца)
Строго по **Pre-deploy checklist**, атомарно, по одному резу:
1. `git commit` ДО (точка отката) → серверный `.bak` перед `scp`.
2. 1 рез = **поведение не меняем** (чистая реструктуризация).
3. `python -m py_compile` + import-check → деплой → smoke (`/start` через владельца / `curl`).
4. ОК → commit+push; не ОК → `git revert` + `scp` `.bak`.
Порциями, не за один заход.

## Прогресс (трекер)
- ✅ **Tier-1 #1 — status-line** (06-23, `214603e`): `format_subscription_status()` в новом `bot/formatting.py`; дедуп в `bot/main.py` (claim) + `web/app.py` (claim). Byte-идентично (проверено на сервере), прод ок, `/start` ОК.
- ⬜ **Tier-1 — notify-inviter** (`bot/main.py:943` ↔ `web/app.py:162`) — сверить тела, вынести.
- ⬜ **Tier-1 — device-autoname** (`bot/main.py:1602` ↔ `web/app.py:1255`) — сверить, вынести.
- ⬜ **Tier-1 — vless-персонализация** (`bot/main.py:2706` ↔ `web/app.py:2054/2101`) — сверить, вынести.
- ⬜ **status-line добить:** `bot/main.py:2476` (cmd_status — иное слово, проверить идентичность) и `:3822` (support-notify `sub_line` — вероятно тот же паттерн).
- ⬜ **Tier-2 (опц.):** donation-notify билдер (текст+callback_data); `_send_subscription` дедуп тела `callback_vpn_quick`.
- ⛔ **Tier-3 (распил `main()`):** отложен (оверинжиниринг на масштабе).
