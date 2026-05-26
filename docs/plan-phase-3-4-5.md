# Plan — Phases 3, 4, 5 (новый бот + monetization + referral)

> Создан 2026-05-25 как master-документ для следующих фаз. Если контекст диалога закончится — это основная точка отсчёта для продолжения.

---

## Контекст и пройденное

**Фазы 0–2 (DONE 2026-05-25):**
- Модель аккаунта в БД (`subscription_status`, `expires_at`, `trial_used`, `plan`, `referral_code`, `referred_by`, `password_hash`, `sub_token` + таблица `payments`).
- UX ЛК (`recovery.html`): QR-коды, выравнивание, hero, экран «Мой аккаунт», вход по паролю, **subscription как главный CTA**.
- Subscription-endpoint `/sub/<sub_token>` (validated в HAPP iOS, Wi-Fi+LTE; БС-полевой тест отдельно).
- HTTPS на `https://supportkronos.online:8443` (direct с Fornex; LE-cert via DNS-01; **CF в РФ заблокирован как прокси** — используем только как DNS, grey-cloud).

**Текущая инфра (срез):**
- Бот: `vpn-bot.service` на Fornex. **Старый @username** (будет заменён).
- ЛК: `vpn-web.service` (Flask :5001) + nginx :8443 ssl → :5001.
- БД: SQLite `/opt/vpnservice/bot/data/vpn.db`.
- Серверы: Fornex eu1 (AmneziaWG + Xray REALITY на 443 + nginx :8443 + nginx :80), main Timeweb (Xray REALITY cloud.mail.ru на 443, БС), YC vrprnt (Xray REALITY www.microsoft.com xhttp на 443).
- CF-токен (DNS:Edit, zone supportkronos.online) — `/root/.secrets/cloudflare.ini` на Fornex (для авто-продления LE).
- Cron на Fornex (root): `*/5 amnezia-save-conf`, `*/5 traffic_accounting`, `0 5 * * 0 certbot renew` (через certbot.timer).

---

## Бренд (зафиксировано 2026-05-25)

| Сущность | Имя | Назначение |
|---|---|---|
| **Бренд (новый)** | **Kronos / VPN Kronos** | Личный handle владельца, преемственность с `nikkronos`, `kronos-lolly@yandex.ru`. |
| **Бот (новый)** | `@vpnkronos_bot` (display: `vpnkronos`) | Замена старого, токен в env (на Fornex). |
| **Канал** | `@vforfriends` (legacy) | Существующий канал; rename — отдельная задача владельца. |
| **Домен** | `supportkronos.online` | **Нейтральное «support»-имя — маскировка**, не палит VPN. Резервный/recovery-портал. |
| **ЛК** | `https://supportkronos.online:8443/recovery` | HTTPS direct с Fornex (CF только как DNS, см. ниже). |

**Несоответствие имён осознанное:** домен «support» — намеренная камуфляжная подстраховка от автоблокировок (РКН реже бьёт по «support»-доменам, чем по «vpn»-доменам). Бренд внутри — Kronos.

---

## Цена и позиционирование

- **Цена**: **200 ₽/мес** (выбрана 2026-05-25 владельцем).
- **Конкуренты**: 185–330 ₽/мес (hide-my-name.cloud, avoVPN, VPN Пельмень и др.).
- **УТП**: «работает когда другие отваливаются» — реальный обход БС (Yota подтверждено через REALITY+cloud.mail.ru, Мегафон ждёт окна разведки).
- **Период**: месяц как базовый. Квартал/год — позже, со скидкой (TODO для маркетинга).

---

## Стратегические решения 2026-05-25 (зафиксированы)

1. **Email-OTP/пароль остаётся** основным способом авторизации (сбор БД важен для будущей рассылки/маркетинга).
2. **Web-ЛК остаётся** основным интерфейсом (юзеры привыкли к сайтам).
3. **Mini App = дополнительный способ авторизации** через Telegram (initData → auto-login по `telegram_id`), не замена ЛК. Тот же recovery.html, просто детектит TG-контекст.
4. **ЮKassa = основная оплата** (карты + СБП, привычно).
5. **Telegram Stars = вторая кнопка оплаты** в ЛК, делается позже (необязательно для запуска).
6. **Замена старого бота** (не двух параллельных). Миграция через broadcast в старом боте всем 34 юзерам.
7. **AmneziaWG остаётся** как опция «макс. скорость» в ЛК; subscription (VLESS) — главный CTA для большинства.
8. **CF не используем как прокси в РФ** (durable, подтверждено живым тестом — DPI режет TLS к CF). Только как DNS (grey-cloud).

---

## Phase 3 — Новый бот + Mini App

### 3a. Создание нового бота — DONE (внешне)
- В BotFather: `@vpnkronos_bot` (display `vpnkronos`). Токен получен.
- Токен пойдёт в `/opt/vpnservice/env_vars.txt` как `BOT_TOKEN`. Старый токен заменяется. Старый бот через `revoke token` в BotFather или просто перестаёт работать (старый сервис остановится).

### 3b. Меню бота под ЛК
**Минимум кнопок** (бот = launcher Mini App):
- **Menu Button** (всегда видимая нижняя кнопка): `web_app` тип, URL = `https://supportkronos.online:8443/recovery`. Текст: «🌐 Личный кабинет».
- На `/start` — inline keyboard с двумя кнопками:
  - `web_app`: «🌐 Открыть Личный кабинет» → запускает Mini App.
  - `callback_data="menu_proxy"`: «📨 Разблокировка Telegram» (выдаёт MTProxy-ссылку — это нужно вне Mini App, т.к. при заблокированном TG юзер должен получить proxy чтобы сам Telegram запустить — но это chicken-and-egg, обсудим).
- Приветствие — короткое:
  ```
  Привет! Это VPN Kronos. 🔐
  
  Открой Личный кабинет — там подписка, статус и все настройки.
  Если Telegram не открывается — нажми «Разблокировка Telegram».
  
  Канал с обновлениями: https://t.me/vforfriends
  ```
- Команды (`setMyCommands`):
  - `/start` — главное меню.
  - `/proxy` — MTProxy-ссылка (legacy команда, оставить).
- **Убираем** старые кнопки «Получить VPN», «Обновить конфиг», «Инструкции», «Мой статус», «Мобильный VPN». Всё перенесено в Mini App (ЛК).
- Старый код (`menu_get_config`, `menu_regen`, `menu_mobile_vpn`, `menu_status`, `menu_instruction`) — оставить в коде как dead callbacks для совместимости, но в новом меню не показывать.

### 3c. Mini App auto-login (initData валидация)
- **Backend:** новый endpoint `POST /api/auth/tg-webapp`:
  - Body: `{init_data: <строка из Telegram.WebApp.initData>}`.
  - Валидация: парсим query-string, отделяем `hash`, сортируем остальные пары, считаем HMAC-SHA256(сорт_строка, HMAC-SHA256("WebAppData", bot_token).digest()). Сравниваем с `hash`. Проверяем `auth_date` не старше 24 часа (anti-replay).
  - При успехе: парсим поле `user` (JSON), берём `id` = `telegram_id`. Upsert user (db_upsert_user with telegram_id, username) → выпускаем session-token (`db_create_session` под синтетический email вида `tg{telegram_id}@vpnkronos`? Или меняем `db_create_session` принимать `telegram_id` напрямую). Проще: добавить `db_create_session_for_telegram_id(telegram_id)` параллельно текущему (email-based). Сейчас `web_sessions(token, email, ...)` — email-keyed. Можно либо: (а) сгенерировать synthetic email `tg{id}@local`, (б) добавить нормальный telegram_id-keyed session. Лучше (б) — добавить поле в `web_sessions` или создать `db_create_session_by_user`. **TODO в реализации:** определиться с моделью.
- **Frontend (recovery.html / recovery.js):**
  - Подключить `<script src="https://telegram.org/js/telegram-web-app.js"></script>`.
  - На загрузке: `if (Telegram.WebApp.initData) → POST /api/auth/tg-webapp с initData → сохранить session token → showStep(stepMenu) + loadAccount()`. Пропустить stepEmail.
  - При прямом заходе (не из TG) — текущий email/OTP/password flow.
- **Bot Telegram.WebApp.ready() + expand()** — стандартный init.

### 3d. Enforcement + grandfather + триал
- **Grandfather всех текущих юзеров**: миграция в `database.py`, выставить `expires_at = '2099-01-01T00:00:00'` (или флаг `is_legacy=1`) для всех существующих `users` с `active=1` и `expires_at IS NULL`. Делаем это **до** включения enforcement, чтобы они не потеряли доступ.
- **Новые юзеры**: при первой регистрации (email-OTP, Mini App auto-login, или /start в боте) — если нет `expires_at`, **автоматически активируется триал** (`db_start_trial(14)`). Не показываем «активировать триал»-кнопку — даём сразу.
- **Enforcement включён по факту** — `/sub` уже гейтит через `db_is_access_active`. Доп. enforcement: при истечении triала/подписки — мы НЕ удаляем AWG-peer/UUID (это сложно и нужно делать с грейс-периодом), а просто `/sub` возвращает пустоту → клиенты (HAPP) теряют серверы. AmneziaWG-конфиги остаются работать (peer есть на сервере), это менее строго. **Решение по строгости enforcement: разобраться** — нужно ли вообще удалять AWG-peer (вырубить полностью) или хватит «не давать новый конфиг + не обновлять подписку».
  - **Лояльный enforcement (рекомендую старт):** просрочка → не выдаём новый конфиг, не обновляем подписку. Существующие сессии живут до отвала.
  - **Жёсткий enforcement (позже, если будет abuse):** удалять AWG-peer + ротировать UUID при просрочке.

### 3e. ЮKassa — основная оплата
- **Регистрация (внешне, делает владелец)**: см. `docs/yookassa-setup-instruction.md`.
- **Что получим**: `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY` → в `env_vars.txt`.
- **Backend (новые endpoints):**
  - `POST /api/billing/create-payment {token, plan}` → создать платёж в ЮKassa через их API (Idempotence-Key), вернуть `confirmation_url` для redirect.
  - `POST /api/billing/yookassa-webhook` (на ЮKassa-стороне настроить вебхук на этот URL) — обрабатывает события `payment.succeeded`:
    - Найти запись `payments` по `external_id` (idempotency).
    - Если не обработано → `db_extend_subscription(telegram_id, days=30)`, `db_update_payment_status(succeeded)`.
    - **Реферал-начисление** (см. 3f) — если это первая оплата юзера и есть `referred_by` → `db_extend_subscription` обоим (+14 дней).
- **UI в ЛК** (recovery.html / Mini App):
  - В статус-карточке: кнопка «💳 Продлить на месяц — 200 ₽».
  - Открывается ЮKassa-страница оплаты (или внутри TG WebApp — TG Mini Apps умеют `openInvoice` для не-Stars платежей? Нет, для внешних — `openLink`).
  - После оплаты — обновить страницу, увидеть новый `expires_at`.
- **Запись в БД**: `db_record_payment(provider='yookassa', ...)`.

### 3f. Реферал-начисление
- **Триггер**: первая успешная оплата (любой провайдер) пользователя с `referred_by IS NOT NULL`.
- **Действие**: 
  - Найти пригласившего по `referral_code = me.referred_by`.
  - Если найден и активен: `db_extend_subscription(inviter, +14)`.
  - Текущему: `db_extend_subscription(self, +14)` (сверх купленного).
  - Записать в БД флаг «реферал-бонус выплачен» (чтобы не выплатить дважды). Можно поле `referral_bonus_paid INTEGER DEFAULT 0` в `users`. **TODO миграция** в реализации.
- **Уведомление**: в TG приходит сообщение «Тебе начислено +14 дней за приглашённого друга».

### 3g. Telegram Stars (вторая кнопка оплаты, **позже**)
- В ЛК рядом с «Оплатить картой» — «⭐ Оплатить звёздами Telegram (внутри Telegram)».
- Backend: `createInvoiceLink(currency='XTR', prices=[{label: 'Подписка', amount: N_stars}], subscription_period=2592000)`.
  - Цена в Stars: ~115–150 Stars для эквивалента 200₽ (1 Star ≈ 1.5₽ по текущему курсу, проверить актуальное).
- Handler `successful_payment`:
  - Если `is_first_recurring=True` или `is_recurring=False` → первая оплата → `db_extend_subscription(+30)`.
  - Если `is_recurring=True` → продление → `db_extend_subscription(+30)`.
  - Реферал-начисление аналогично 3f.
- Stars-кнопка работает **только из бота / TG WebApp**, не из обычного браузера. В web ЛК — серая.
- **Telegram забирает ~30% (через Apple/Google) или меньше при прямой покупке Stars**. Меньше маржи, но zero setup.
- **Вывод Stars в РФ**: Stars → TON (через bot.fragment или TG-кошелёк) → фиат (Fragment, P2P). Friction есть. Это **деньги для будущего**, не для немедленного запуска.

### 3h. Миграция (внешне, делает владелец)
- В старом боте (пока он ещё работает) — broadcast всем юзерам:
  ```
  Привет! Мы переехали в новый бот: @vpnkronos_bot
  Подключение, статус и подписка теперь там. Старый бот скоро перестанет работать — переходи сейчас.
  ```
- После рассылки (через 3–7 дней) — заменить токен на сервере (`BOT_TOKEN` в env), перезапустить `vpn-bot.service`. Старый токен можно отозвать в BotFather.
- В новом боте: при `/start` ловить existing users по `telegram_id` (распознаются автоматически по БД), приветствие как для returning.

---

## Phase 4 — реалии и риски

**Юр-сторона:**
- Самозанятый + ЮKassa: каждый платёж формирует чек через ФНС автоматически (требование ЮKassa). Лимит самозанятого: 2.4 млн ₽/год доходов.
- VPN-мерчанта могут флагнуть. На случай блокировки ЮKassa — иметь план Б (другой провайдер: YooMoney, Lava, Stripe-аналоги).
- Stars: вывод в РФ непрост, но возможен через Fragment.

**БС-доступность для оплаты:**
- ЮKassa-страница оплаты на yookassa.ru — гарантированно открывается в РФ при обычных условиях. При БС — yookassa.ru скорее всего whitelisted (банковский домен).
- Mini App при БС: TG-клиент работает через MTProxy → Mini App грузится из нашего HTTPS — но наш Fornex german IP при БС недоступен. Phase 1b (RU clean-443 host) нужен **до** того, как будут платящие при БС.

**Per-user UUID на main/yc REALITY** — нужно для биллинга/аналитики (иначе невозможно отличить кто прошёл по подписке). Сейчас shared UUID. **TODO в Phase 4** перед запуском оплаты.

---

## Phase 1b (откладывается, durable open loop)

**БС-robust RU-хост с чистым :443**:
- Текущий Fornex `:8443` работает в обычных условиях РФ, но при БС немецкий IP отвалится → ЛК недоступен → recovery-lifeline сломан в самый нужный момент.
- Решение: новый RU-VPS на whitelisted-облаке (VK Cloud / Yandex Cloud / Selectel / Cloud.ru) с **free 443** и LE-cert. Домен `supportkronos.online` → grey-cloud → этот IP.
- Нюанс: при строгом БС (Yota) DPI инспектирует SNI → наш domain SNI может срезаться даже на whitelisted-IP. Решение: hosting на платформенном домене RU-облака (`*.website.yandexcloud.net` и т.п.) с whitelisted-SNI. Брендовый домен — для обычных дней.
- **Требует**: денег (~150–250 ₽/мес VPS) + работы по настройке.

---

## Что осталось pending (full list)

| Задача | Приоритет | Зависит от |
|---|---|---|
| 3a — новый бот в BotFather | DONE | — |
| 3b — меню бота под ЛК + Menu Button web_app | P0 (сейчас) | токен (есть) |
| 3c — Mini App auth (initData) | P0 (сейчас) | — |
| 3d — enforcement + grandfather + триал | P0 (сейчас) | — |
| 3e — ЮKassa интеграция | P0 (после регистрации на ЮKassa) | YOOKASSA_SHOP_ID/SECRET |
| 3f — реферал-начисление | P1 | 3e |
| 3g — Stars (вторая кнопка) | P2 (после 3e) | — |
| 3h — миграция (broadcast) | P0 (после 3b+3e) | владелец |
| Phase 1b — RU clean-443 host | P1 (для БС-recovery) | деньги + БС-окно для теста |
| Per-user UUID на main/yc | P1 (для биллинга) | — |
| Мегафон БС-разведка | P2 | БС-окно + друг на Мегафоне |
| Переименование канала `@vforfriends` → ? | P3 | владелец |

---

## Технические артефакты (где что лежит)

- **Бэкенд**: Python Flask `web/app.py`, бот `bot/main.py`, БД `bot/database.py`, helpers `bot/storage.py` `bot/wireguard_peers.py` `bot/vless_peers.py`.
- **Фронт ЛК**: `web/templates/recovery.html`, `web/static/recovery.js`, `web/static/style.css`.
- **Subscription endpoint**: `web/app.py` функция `api_subscription` + `_build_subscription_links`.
- **Account/info**: `api_account_info` — расширяется для Mini App auth.
- **БД схема**: `database.py` `_SCHEMA` + миграции `_migrate_add_*`.
- **Inflra скрипты**: `scripts/traffic_accounting.py` (cron), `docs/scripts/nginx-supportkronos-8443.conf` (nginx).
- **Env**: `env_vars.example.txt` — пример, реальные secrets в `/opt/vpnservice/env_vars.txt` (gitignored).
- **CF API token**: `/root/.secrets/cloudflare.ini` (для certbot auto-renew).

---

## Принципы продолжения (для следующего агента)

- **Аддитивно > переписывание**. Старый email-OTP/пароль остаётся; Mini App auth = дополнительный путь.
- **Сначала grandfather, потом enforcement.** Иначе 34 текущих юзера потеряют доступ.
- **ЮKassa first, Stars later.** ЮKassa = деньги, Stars = удобство (с большой комиссией).
- **БС-валидация — только реальным тестом** (`memory:no-hypothesis-without-test`). Гипотезы про клиента — отбрасывать без полевого теста.
- **CF не использовать как прокси в РФ** (durable, см. memory).
- **Чтобы всё работающее продолжало работать.** Каждое изменение — non-breaking.
- **Git push после каждого изменения** (per CLAUDE.md правило).
