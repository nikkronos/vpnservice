# SESSION SUMMARY — 2026-05-25

## TL;DR

- 🎯 Вернулись к роадмапу. Курс на коммерциализацию через **личный кабинет (ЛК)**: фазовый план ЛК → меню бота под ЛК → оплата → триал → реферал.
- ✅ **Фаза 0 — модель аккаунта** в SQLite (подписка/срок/триал/реферал + таблица `payments` + пароль). Аддитивно, enforcement пока выключен.
- ✅ **Фаза 2 — UX ЛК**: QR-коды, заметное one-click копирование, выравнивание/воздух, hero+объяснение на входе, экран «Мой аккаунт» (статус/срок, триал 14д, реферал), **вход по паролю** + установка/смена.
- ✅ Бот: приветствие → «ForFriends» + ссылка на ЛК + канал `@vforfriends`.
- 📋 Скорость закрыта в прошлой сессии; Мегафон-БС разведка ждёт окна БС (сейчас БС нет).

---

## Стратегия и решения

**План коммерциализации (фазы):**
0. Модель аккаунта в БД ✅
1. Домен + БС-достижимый хост ЛК + HTTPS → **тест при БС** (ждёт доступа к YC + окна БС)
2. UX ЛК (one-click, дашборд) ✅ (итеративно)
3. Меню бота под ЛК
4. **Enforcement** (резать доступ по `expires_at`) + триал + оплата
5. Реферальная система (начисление бонусов)

**Решения этой сессии:**
- **Домен:** нейтральное имя на базе бренда (ForFriends; варианты forfriends.* / vff / vforf — финал не выбран). Предпочтительно **не .ru** (устойчивее к изъятию РКН). Имя должно быть запоминаемым (вбивают руками, когда VPN не работает).
- **Хост ЛК = YC** (Yandex Cloud), широко-whitelisted RU-облако → достижим при БС. **Важно (честно):** одного whitelisted-IP мало — при строгом БС (Yota) инспектируется SNI; наш собственный домен может срезаться. Для БС-выживания, вероятно, нужен **whitelisted-SNI хостинг** (статика на платформенном домене RU-облака, напр. `*.website.yandexcloud.net`), а брендовый домен — для обычных дней. Финально подтвердить **тестом при БС**.
- **Почему ЛК критичен:** при БС **Telegram тоже режется** → опереться на бота как fallback нельзя. Web-ЛК на whitelisted-хосте — главный lifeline (через него же достаётся MTProxy, чтобы поднять Telegram).
- **Оплата:** ЮKassa (есть самозанятость; карты + СБП одной интеграцией) → Telegram Stars → крипта. Модель payments — provider-agnostic.
- **Триал:** 14 дней. **Реферал:** «дни обоим» — когда приглашённый оплатит, обоим +14 дней (начисление в Фазе 4).

---

## Что сделано (код)

### Фаза 0 — модель аккаунта (`bot/database.py`)
- `users` +колонки: `subscription_status`, `expires_at`, `trial_used`, `plan`, `referral_code`, `referred_by`, `password_hash` (идемпотентные, race-safe миграции).
- Таблица `payments(provider, amount, currency, status, external_id, plan, days, …)`.
- Хелперы: `db_get_subscription`, `db_is_access_active` (NULL expires_at = grandfathered), `db_extend_subscription`, `db_start_trial`, `db_ensure_referral_code`, `db_get_user_by_referral_code`, `db_count_referrals`, `db_set_referred_by`, `db_record_payment`, `db_update_payment_status`, `db_set_password`, `db_has_password`.

### Фаза 2 — UX ЛК (`web/`)
- **QR-коды** (PNG через `qrcode[pil]`, graceful None если либы нет): мобильный VLESS, MTProxy, AmneziaWG-конфиг для iOS/Android (скан в приложении).
- **Заметная primary-кнопка копирования** + ссылка в аккуратном блоке.
- **Выравнивание:** единая колонка 640px (меню/форма/результат одной ширины), равномерный вертикальный ритм, больше воздуха.
- **Hero-заголовок** + объяснение «что это» + 3 пункта возможностей на входе (до логина).
- **Экран «Мой аккаунт»** (после входа, вместо меню→подменю): статус-карточка (срок), кнопка триала (14д), реферальный блок (код/ссылка/счётчик), быстрые кнопки каналов.
- **Вход по паролю** (email+пароль, альтернатива OTP) + установка/смена пароля в ЛК (werkzeug hash, ≥8 симв.).
- Новые эндпоинты: `/api/account/info`, `/api/account/start-trial`, `/api/account/set-password`, `/api/auth/login-password`; `verify-otp` принимает `?ref` для реф-атрибуции.
- Константы (легко менять): `TRIAL_DAYS=14`, `REFERRAL_REWARD_DAYS=14`.

### Бот (`bot/main.py`)
- Приветствие над кнопками → «Привет! Это VPN-бот ForFriends. 🔐 / 🌐 Личный кабинет: {recovery_url} / ⌛ Канал: https://t.me/vforfriends» (оба варианта — авторизован/нет).

---

## Что пока косметика (доделать в Фазе 4)

1. **Enforcement выключен** → у всех статус «Бессрочный»; активация триала пишет дату, но доступ не режет.
2. **Реф-бонус** (+14 дней) начисляется только при оплате (Фаза 4); сейчас реферал лишь считает приглашённых.
3. **Grandfather-нюанс:** сейчас и новые юзеры по умолчанию `expires_at=NULL` (бессрочные). Перед enforcement: явно «вечный» существующим + у новых старт с триала/expired.

## Безопасность

- **Пароль идёт по HTTP** (`http://185.21.8.91:5001`) — сниффабелен. Полноценно безопасен только по **HTTPS** (Фаза 1, домен/YC). До этого — пароль как удобство, не как защита.

---

## Коммиты

- `1cfb5ec` — Фаза 0 модель аккаунта
- `c0e2384` — QR + one-click copy
- `9d561ba` — выравнивание + hero
- `0b3f6a7` — экран «Мой аккаунт» (статус/триал/реферал)
- `3647133` — вход по паролю + реферал 14д + приветствие бота

## Серверно (вне git)

- В venv установлен `qrcode[pil]` (pillow). Добавлено в `requirements.txt`.

---

## Что дальше

1. **Фаза 1** — YC-хост ЛК + домен + HTTPS, затем **тест при БС** (нужен доступ к YC + окно БС). SNI-нюанс держать в уме.
2. **Фаза 3** — меню бота под ЛК.
3. **Фаза 4** — enforcement (`db_is_access_active` уже готов) + grandfather существующих + ЮKassa (карты+СБП).
4. **Фаза 5** — начисление реф-бонусов при оплате.
5. **Мегафон при БС** — разведка whitelist через друга при активных БС (ждёт окна).
6. Тексты/инструкции — сократить (запаркован фидбэк владельца).

---

## Дополнение (вечер 2026-05-25) — домен `supportkronos.online` + прямой HTTPS на Fornex + subscription-спайк validated

### Контекст
Пост в TG (FSystem88/1717) натолкнул на модель «subscription-URL + HAPP» (одна ссылка → клиент сам подтягивает много серверов, авто-выбирает, refresh сам). Решили **спайкнуть** это на нашей инфре — аддитивно, ничего из работающего не ломая.

### Решения
- **Домен:** `supportkronos.online` (reg.ru, 199₽/год + WHOIS-privacy 243₽; нейтральное «support»-имя — маскировка, не палит VPN). Бренд бота/канала остаётся ForFriends; домен — нейтральный support-портал.
- **Оплата:** ЮKassa(карты+СБП) → Stars → крипта (provider-agnostic модель в БД — Фаза 0).

### Спайк (Фаза 0/2 продолжение): subscription-endpoint
- БД: `sub_token` column + helpers (`db_ensure_sub_token`, `db_find_user_by_sub_token`).
- `GET /sub/<token>` → base64-список наших REALITY-ссылок (YC `www.microsoft.com` + main `cloud.mail.ru`). Гейт: `db_is_access_active` (хук enforcement Фазы 4 — пустая подписка для истёкших).
- ЛК: блок «Подписка — одна ссылка на все устройства» (ссылка + QR через `_qr_datauri`).
- `app.py + ProxyFix(x_proto, x_host)` — за прокси Flask собирает `https://<домен>` (иначе sub-ссылка была бы http и HAPP её отверг).
- Аддитивно: AmneziaWG / индивидуальные VLESS / MTProxy не тронуты, recovery/traffic 200 не сломалось.

### Дорога к HTTPS — нетривиальный путь
1. **Cloudflare Tunnel отвалился** — Zero Trust требует не-Mir-карту (у владельца только МИР).
2. **CF proxy (orange) + Origin Rule (порт 5001) + Flexible SSL** — серверно работало (`/recovery` 200), но HAPP падал в таймаут.
3. **Диагностика**: `curl` с пустым UA → CF 403 (Browser Integrity Check). Browser Integrity Check выключили — empty-UA → 200, но HAPP всё равно таймаут.
4. **Ключевое открытие**: Safari у владельца тоже не открывает `https://supportkronos.online` («сетевое подключение прервано» = DPI RST). **Cloudflare у него в РФ блокируется/тротлится** (не только при БС, а вообще сейчас). → CF не годится как хост для РФ-юзеров. **Дроп CF.**
5. **Решение**: A-запись **grey-cloud (DNS-only)** → резолв напрямую на Fornex `185.21.8.91`. Сертификат **Let's Encrypt через DNS-01** (CF API token DNS:Edit, certbot-dns-cloudflare, авто-продление). **nginx на :8443 ssl http2** → proxy `:5001` (443 занят Xray REALITY, поэтому :8443). Файл `docs/scripts/nginx-supportkronos-8443.conf`, на сервере `/etc/nginx/conf.d/supportkronos.conf`.

### Спайк validated в HAPP
- Подписка `https://supportkronos.online:8443/sub/<token>` подтянулась в HAPP (iOS): 2 сервера (YC-Reality + RU-REALITY), авто-обновление 12ч. Работает **на Wi-Fi и LTE**.
- ⚠️ **БС-валидация не проведена** (БС сейчас нет). Архитектурно RU-REALITY/cloud.mail.ru должен держать при БС, но реальный тест — позже при окне (принцип «гипотеза о клиенте только через тест»).
- Пустой UA отдаёт 200 (CF-BIC ушёл вместе с CF) — HAPP-фетчер любым UA примет.

### Закрепление (Phase 1 — done в форме прямого HTTPS на Fornex)
- `VPN_RECOVERY_URL=https://supportkronos.online:8443/recovery` в env_vars.txt → приветствие бота, инструкции, ссылки указывают на новый URL.
- Инструкции ios/android/windows — URL заменён.
- ЛК: блок «Подписка» поднят выше как **главный CTA** (после статуса), подзаголовок «Альтернативные способы (конкретные конфиги)» для старых каналов.
- `env_vars.example.txt`: пример нового URL.

### Серверные изменения (вне git)
- A-запись `supportkronos.online` → 185.21.8.91 (proxied: **false**, grey-cloud) — через CF API.
- Browser Integrity Check отключён в CF (не нужен, т.к. ушли с прокси) — historical note.
- Let's Encrypt сертификат `/etc/letsencrypt/live/supportkronos.online/` (DNS-01, авто-продление, истекает 2026-08-23).
- `nginx -t` ок, конфиг в `/etc/nginx/conf.d/supportkronos.conf`, reload.
- CF API token (DNS:Edit, zone supportkronos.online) в `/root/.secrets/cloudflare.ini` (600) для авто-продления.
- `env_vars.txt`: `VPN_RECOVERY_URL` обновлён.

### Что НЕ сделали и что осталось
- **Phase 1b — БС-robust хост на RU-облаке с чистым :443** — pending. Текущий setup (немецкий Fornex :8443) работает в обычных условиях РФ, но при БС немецкий IP недоступен. И `:8443` в URL — не идеал для «вбить руками».
- **Per-user UUID** на main/yc для REALITY (сейчас shared UUID) — Phase 4 prerequisite для биллинга.
- **БС-полевой тест** subscription-модели (RU-REALITY должен держать).
- **Переименование меток** «YC-Reality / RU-REALITY» в понятные пользователю — следующая итерация.
- **Новый бот + монетизация** — на общем бэкенде, после закрепления текущего.

### Ключевое durable-наблюдение
**Cloudflare не надёжен в РФ** для нашего use-case (не только БС, а вообще). DPI RST на TLS к CF подтверждён живым тестом. Использовать CF только как DNS (grey-cloud), не как прокси. Для HTTPS — прямой хостинг.

---

## Дополнение (поздний вечер 2026-05-25) — фиксация бренда, цены, нового бота, и Mini App-пивота

После подтверждения спайка subscription-модели обсудили план Phase 3+4+5. Зафиксированы решения:

### Бренд
- **Kronos / VPN Kronos** (переход с ForFriends, под личный handle владельца).
- **Бот**: `@vpnkronos_bot` (display `vpnkronos`). **Создан в BotFather, токен получен** — будет в env_vars.txt на сервере при деплое Phase 3b.
- **Домен**: `supportkronos.online` (нейтральная маскировка).
- **Канал**: `@vforfriends` legacy (не блокирует, rename — задача владельца).
- **Цена**: **200 ₽/мес** (середина рынка, УТП «работает при БС»).

### Открыли две большие TG-фичи 2024–2025, которые меняют план
- **Telegram Mini Apps (Web Apps)** — UI прямо внутри Telegram, авторизация через подписанный `initData` (HMAC с bot-token) → auto-login по `telegram_id`. Серверный HTTPS — наш (уже есть).
- **Star Subscriptions** (Bot API 8.0, ноябрь 2024) — `createInvoiceLink(subscription_period=2592000)` → Telegram сам списывает Stars ежемесячно, шлёт webhook на `successful_payment` (`is_recurring`, `is_first_recurring`). Нативный recurring.

### Скорректированный план (после уточнений владельца)
Владелец уточнил приоритеты:
- **Email-OTP/пароль ОСТАЁТСЯ** (сбор БД важен).
- **Web-ЛК ОСТАЁТСЯ** (юзеры привыкли к сайтам).
- **Mini App = ДОПОЛНИТЕЛЬНЫЙ способ авторизации**, не замена email-флоу.
- **ЮKassa = ОСНОВНАЯ оплата** (карты+СБП, привычно). Stars = вторая кнопка позже.
- **Замена** старого бота (не два параллельных). Broadcast-миграция через старый.

### Документы созданы / обновлены
- `docs/plan-phase-3-4-5.md` — **master-план Phase 3+4+5** (читать первым при потере контекста).
- `docs/yookassa-setup-instruction.md` — пошаговая инструкция владельцу по подключению ЮKassa для самозанятого (Shop ID + Secret + webhook).
- `ROADMAP_VPN.md` — обновлён, фазы и решения зафиксированы.
- `CLAUDE.md` — добавлен блок «Бренд» + ссылки на master-план и ЮKassa.
- `env_vars.example.txt` — заготовки `YOOKASSA_SHOP_ID/SECRET_KEY/WEBHOOK_URL`.
- Память (`project_vpn_decisions.md`) — Phase 3+4+5 решения как durable.

### Что осталось pending до старта Phase 3 (реальный код)
1. **3a — новый бот**: внешне DONE (создан, токен у нас).
2. **3b — меню бота под ЛК** (Menu Button = web_app, минимум кнопок): код, после деплоя токена.
3. **3c — Mini App initData auth**: новый endpoint `/api/auth/tg-webapp` + frontend detect Telegram.WebApp.
4. **3d — enforcement + grandfather + триал**: миграция БД (legacy `expires_at` = far future), новые → авто-триал, `/sub` уже гейтит.
5. **3e — ЮKassa**: ждёт регистрации владельца (~1-2 дня) → Shop ID + Secret → код endpoint'ов + webhook.
6. **3f — реферал-начисление при первой оплате** (флаг `referral_bonus_paid`).
7. **3g — Stars** (необязательный 2-й способ, после ЮKassa).
8. **3h — broadcast в старом боте** (владелец).

### Принципы для следующего агента (если контекст этого диалога потеряется)
1. Читай `docs/plan-phase-3-4-5.md` ПЕРВЫМ — это master.
2. Аддитивно > переписывание. Email-OTP/пароль/Web-ЛК — остаются. Mini App / Stars — добавляются.
3. Grandfather ДО enforcement (иначе 34 юзера потеряют доступ).
4. CF не как прокси в РФ (durable, в памяти).
5. БС-валидация — только реальным тестом.
6. ЮKassa — основная оплата; Stars — вторая, не блокер.
7. Цена 200 ₽/мес.
8. Бот `@vpnkronos_bot`, домен `supportkronos.online`, бренд Kronos.
