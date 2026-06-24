# План рефактора (#3) — scope-оценка

> 2026-06-23, read-only анализ. Цель: убрать **дубли и боль** (правишь логику в одном месте, не в двух → меньше багов), НЕ «красивая архитектура». На ~15 платящих полный распил монолитов = оверинжиниринг.

> **ОБНОВЛЕНИЕ 06-24 — #3 ЗАКРЫТ.** Реврейм владельцем: настоящая метрика — **токены на чтение кода + путаница агентов**, не число дублей. Под неё главный выигрыш дала **навигация** (карта-докстринг + grep-баннеры `# ═══ §N`): `bot/main.py` 15 секций (`94cf223`), `web/app.py` 9 (`bad7eb9`). Дедупы device-autoname (`eef5287`)/status-line взяты. Рычаг 2 (физвынос «листьев») ~2% — монолит держится на замыканиях; рычаг 3 (`register()`-распил) отложен как рискованный. Память `feedback_refactor_goal_agent_navigability`. Трекер ниже — фактическое состояние.

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

## Прогресс (трекер) — #3 ЗАКРЫТ 06-24
- ✅ **status-line** (06-23, `214603e`): `format_subscription_status()` в `bot/formatting.py`; дедуп claim-флоу бота+ЛК. Byte-идентично.
- ✅ **device-autoname** (06-24, `eef5287`): byte-identical `_device_autoname`/`_device_autoname_web` → `bot/database.db_device_autoname`; оба call-site. Смоук ок.
- ✅ **status-line — добито проверкой:** `cmd_status` (свой `days_left`/иконки) и support-notify (`до DATE`, без days_left) — **осознанно разные рендеры, не дубли**; фолд сломал бы → оставлены.
- ✅ **Навигация** (06-24): карта-докстринг + grep-баннеры `# ═══ §N` — `bot/main.py` 15 секций (`94cf223`), `web/app.py` 9 (`bad7eb9`). Главный выигрыш по метрике владельца.
- ⏸️ **notify-inviter** — НЕ byte-identical: дедупится только текст (доставка `bot.send_message` vs raw HTTP; бот хардкодит «+14», web берёт `REFERRAL_REWARD_DAYS`). Маргинал — по запросу.
- ⏸️ **vless-персонализация** — реальный дубль, НО bot `_personalize_vless_for_bot` всегда `sync_xray_users.py`, web ветвит eu1→`sync_eu1_vless.py` = латентный баг бота для eu1 (не срабатывает: мобильный целит yc/main). Сведение = поведенческое изменение + трогает Xray-sync → нужно решение владельца.
- ⏸️ **Tier-2 (опц.):** donation-notify билдер; `_send_subscription` дедуп.
- ⛔ **Tier-3 (распил `main()` через `register()`):** отложен — реальный распил, но риск (декораторы/замыкания/стейт, billing/enforcement/peers). Только если зона начнёт болеть, по одной группе, тщательный смоук.
