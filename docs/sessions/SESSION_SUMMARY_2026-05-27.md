# SESSION SUMMARY — 2026-05-27

## TL;DR

- ✅ **Phase 3g — Telegram Stars (одноразовая оплата)** — DONE утром (commit `d0155e8`).
- ✅ **Phase 3g+ — ручная СБП/карта Т-Банк + `/admin/credit`** — DONE утром (commit `8ee3541`).
- 🆕 **ROADMAP**: зафиксированы 4 варианта автозачисления (A=Cryptomus / B=Stars-subscription / C=копейки-парсер / D=самозанятость+Lava) — владелец думает (commit `eaf6d03`).
- ✅ **Mini App: реструктуризация ЛК под вложенные разделы** (вечер) — длинный скролл превращён в главное меню + 4 подстраницы. Substeps: «Продлить подписку», «Резервные конфиги» (3 канала), «Пригласить друзей», «Пароль и настройки».
- ✅ **Inline-кнопка «Продлить»** в статус-карточке: показывается, когда `days_left ≤ 3` (включая истёкшие). Не показывается grandfather'ам.
- ✅ Деплой на Fornex, smoke-тест прошёл (`vpn-web.service` active, 200 на `/recovery`, новая разметка отдаётся).

---

## Что сделано (Mini App restructure)

### Контекст
Owner: «не нравится, что в Mini App всё на одной странице, логично рассортировать под кнопки». Текущая структура — длинный скролл на одном `stepMenu`: status → subscription (CTA) → pay → trial → password → referral → 3 кнопки альт.способов. На мобиле «Альт.способы» уезжали за второй экран и почти не находились.

### Решение
Главное меню = «лицо» ЛК (status + Подписка + 4 nav-кнопки). Всё остальное переехало в свои substeps.

**Новая иерархия:**
```
stepMenu (главная)
├── status-card (с inline «Продлить» при days_left ≤ 3)
├── subBlock (Подписка — главный CTA, QR + ссылка)
├── trialBlock (только если триал доступен)
└── 4 nav-кнопки:
    ├── 💳 Продлить подписку → stepBilling
    ├── 🔌 Резервные конфиги → stepConnect
    │   ├── 📲 Основной VPN → stepPlatform
    │   ├── 📡 VPN при блокировках → stepOperator
    │   └── 📨 Разблокировка Telegram → stepProxy
    ├── 👥 Пригласить друзей → stepReferral
    └── ⚙️ Пароль и настройки → stepSettings
```

### Навигация
- Введена `stepParent` Map с маршрутами «назад» по иерархии. Кнопки «« Назад» и TG `BackButton` оба используют `stepParent.get(currentStep)`.
- `showStep()` теперь трекает `currentStep`, скроллит наверх и управляет видимостью `BackButton`.
- `data-substep` на nav-кнопках → один обработчик мапит ключ → нужный substep.
- `data-channel` (3 канала) остался прежним, но живёт уже в `stepConnect`.

### Файлы
- `web/templates/recovery.html` — реструктуризация секций, 4 новые substep-секции, существующие `stepPlatform/Operator/Proxy` без изменений (только `data-back` стал маркером, не строкой).
- `web/static/recovery.js` — добавлены `stepBilling/stepConnect/stepReferral/stepSettings` рефы, `stepParent` map, `currentStep`, обработчики `data-substep`, inline-CTA в `renderAccount`.
- CSS не трогал — переиспользованы `.btn-menu`, `.account-card`, `.btn-back`, `.recovery-menu`.

### API не трогали
Никаких изменений в `web/app.py`, БД, эндпоинтах. Бэкенд возвращает те же данные, фронт перестраивает раскладку.

### Деплой
- SCP `recovery.html` + `recovery.js` → `/opt/vpnservice/web/{templates,static}/`
- Бэкап старых файлов на сервере: `recovery.html.bak.<ts>`, `recovery.js.bak.<ts>` (rollback в одну команду).
- `systemctl restart vpn-web.service` → active, в логах только запуск Flask, никаких 500/traceback.
- `curl https://supportkronos.online:8443/recovery` → 200.

---

## Что закрывает в ROADMAP

- ✅ **«Альтернативные способы» не видны на телефоне** (фидбэк 2026-05-26): больше не теряются в длинном скролле — у них теперь свой раздел «Резервные конфиги» с явной точкой входа.

## Что НЕ закрыто (осталось висеть)

1. **Автозачисление платежей** — 4 варианта на столе, ждёт решения владельца. Stars-subscription (B) — 30-минутная аддитивная задача, можно сделать без решения остальных.
2. **Phase 3i (лендинг/оферта/контакты)** — блокер ЮKassa, нужны данные владельца.
3. **Phase 3b proper** — swap токена на `@vpnkronos_bot` в env_vars.txt + restart.
4. **End-to-end реферал-тест** на двух TG-аккаунтах.
5. **Missing `instruction_vless_*_short.txt`** файлы.
6. **Регрессия `MenuButtonWebApp`** — проверить версию pyTelegramBotAPI на сервере.
7. **Per-user UUID для main REALITY**.
8. **Мегафон при БС** — разведка ждёт окна.

## Дальнейшее (рекомендация)

После визуальной валидации владельцем — взять **Stars Subscription (вариант B)** как самое дешёвое движение по теме автозачисления. Параллельно — UX-проверка нового флоу на нескольких устройствах (особенно прокликать в TG Mini App: BackButton, переходы между substeps, inline-«Продлить» при истечении срока).

---

## Коммиты сегодня

- `d0155e8` — phase 3g: Telegram Stars payments (native, no merchant setup)
- `8ee3541` — phase 3g+: manual SBP/card payments UI + /admin/credit form
- `eaf6d03` — roadmap: автоматизация платежей (4 варианта) + фиксация Phase 3g/3g+
- *(этот session, Mini App restructure)* — будет в следующем коммите

## Серверно (вне git)

- Бэкапы `/opt/vpnservice/web/templates/recovery.html.bak.<ts>` и `/opt/vpnservice/web/static/recovery.js.bak.<ts>` (от Mini App restructure).
- Бэкап `/opt/vpnservice/web/app.py.bak.<ts>` (от auto-login дебага).

---

## Дополнение (вечер 2026-05-27) — фикс auto-login в Mini App

### Симптом
После реструктуризации ЛК владелец открыл Mini App с iPhone (`@thisvpnforfriends_bot` → Menu Button «🌐 Личный кабинет») и попадал на экран email-логина вместо дашборда. Auto-login через `initData` не срабатывал.

### Диагностика (через временный debug-bar в UI + серверное логирование `_validate_init_data`)
1. **Первый снимок**: dbgBar показал `DBG: loading…` — JS вообще не выполнялся.
2. **Гипотеза**: блокирующий `<script src="https://telegram.org/js/telegram-web-app.js">` подвисал на загрузке → следующий за ним `recovery.js` ждал и не запускался.
3. **Фикс №1**: `async` на SDK-теге + JS-поллинг `window.Telegram.WebApp` до 3 секунд.
4. **Второй снимок**: dbgBar показал `tg=no ver=? initLen=0 inTG=false no tg after 3s (browser mode)` — SDK вообще не подгрузился даже за 3 секунды. То есть `telegram.org/js/telegram-web-app.js` **не доходит до iPhone** в этом WebView.
5. **Корень**: `telegram.org` из РФ-сети владельца (mobile) режется DPI/тротлится — даже когда сам TG-клиент работает (он использует свои app-сервера, не telegram.org/js). Эпизодически кэш TG спасал — отсюда «утром работало, вечером нет».
6. **Фикс №2 (durable)**: скачали SDK один раз на сервер (`/opt/vpnservice/web/static/telegram-web-app.js`, 116 KB) и переключили `<script src>` на локальный путь. Теперь SDK гарантированно доходит — он раздаётся с того же хоста и порта, что и сам ЛК (`supportkronos.online:8443`).
7. **Третий снимок**: `tg=yes ver=9.6 pl=ios initLen=580 inTG=true auth=200 token=ok` — дашборд открылся сразу.

### Что закрепилось
- В памяти (`project_vpn_decisions.md`): «**Telegram-web-app.js хостим у себя**» — любые внешние JS/asset, нужные внутри Mini App, дублируем на нашем хосте. Не полагаться на telegram.org / cdn.jsdelivr / unpkg из РФ.
- Polling `window.Telegram.WebApp` оставлен как defensive-фолбэк (если в будущем SDK по какой-то причине загрузится с задержкой).
- Debug-bar и серверное расширенное логирование вырезаны после фикса.

### Файлы, которые поехали этим фиксом
- `web/static/telegram-web-app.js` — **новый** (116 KB, скачан с telegram.org один раз).
- `web/templates/recovery.html` — script src переключён на локальный путь.
- `web/static/recovery.js` — рефакторинг auto-login: `setupTelegramFeatures()` + `runAutoLogin()` + поллинг.
- `web/app.py` — без изменений в финальном виде (debug-логирование вырезано).

---

## Дополнение (вечер 2026-05-27) — Stars Subscription + смена курса монетизации на donation-flow

### Stars Subscription (commit `23cf3c5`)
Расширил `/api/billing/create-stars-invoice` параметром `recurring:bool`. При `recurring=true` добавляется `subscription_period=2592000` (Bot API 8.0). В ЛК — две кнопки: «⭐ Подписка Stars (150⭐/мес, авто)» и «⭐ Оплатить Stars один раз». Идемпотентность auto-renew уже была в существующем `successful_payment_handler` (через `telegram_payment_charge_id`).

### VLESS-инструкции (commit `23cf3c5`)
Создал два недостающих файла:
- `instruction_vless_cdn_short.txt` — для Yota/Мегафон (через main REALITY, SNI=cloud.mail.ru). УТП: «работает при белых списках».
- `instruction_vless_reality_other_short.txt` — для «не уверен какой оператор» (REALITY через eu1/yc, SNI=microsoft.com).
Бот подгружает их на лету при выборе «Мобильный резерв».

### Убран блок «Комментарий к переводу» (commit `bc57699`)
По фидбэку владельца — не нужен (Т-Банк требует только сумму и реквизиты).

### Смена курса монетизации — donation-flow (вечерний коммит, после)

**Контекст:** владелец «устал от бесконечной борьбы с провайдерами». Меняем план на простую donation-схему. Stars остаются как авто-канал.

**Новый поток:**
1. Юзер видит реквизиты + кнопку «✅ Я перевёл деньги, подтверди».
2. Жмёт → `payment_claim` pending в БД → владельцу TG-сообщение с inline ✅/❌.
3. Владелец проверяет в банке, жмёт ✅ → +30 дней (стакается с остатком).
4. Если ❌ → юзеру «не подтверждено, попробуй ещё раз».

**Cron-напоминания T-7 / T-3 / T-0.** `scripts/expiry_reminder.py` через cron `0 9 * * *` (12:00 МСК). Идемпотентно через флаги `notif_7d_sent` / `notif_3d_sent` / `notif_0d_sent` в `users` (сбрасываются при каждом продлении). Grandfather пропускаются. 403 (юзер заблокировал бота) — флаг ставится всё равно, чтобы не ретраить.

**Файлы:**
- БД: миграция `_migrate_add_expiry_notif_columns` + таблица `payment_claims` через `_SCHEMA`. Хелперы: `db_create_payment_claim`, `db_get_pending_claim`, `db_get_claim_by_id`, `db_decide_claim`, `db_set_claim_notify_msg`, `db_users_due_for_expiry_notif`, `db_mark_expiry_notif_sent`.
- Web: новый endpoint `POST /api/billing/claim-payment` — auth по email-токену → создаёт claim → дёргает TG sendMessage напрямую (через urllib, без инстанса бота) → возвращает `{ok, claim_id, pending, reused}`. Возвращает `pending_claim` в `/api/account/info`.
- Bot: callback-хендлеры `claim_approve:` / `claim_decline:` (только владелец). Кнопка «💳 Продлить подписку» в главном меню → экран реквизитов + «✅ Я перевёл деньги» → создаёт claim из бота, шлёт уведомление владельцу. После решения владельца → бот шлёт юзеру результат + редактирует своё сообщение владельцу (убирает кнопки, добавляет статус «✅ ОДОБРЕНО» / «❌ ОТКЛОНЕНО»).
- ЛК: `renderPayBlock` переключается в pending-режим если `d.pending_claim` (показывает «Заявка отправлена, жди подтверждения»). Иначе — Stars-кнопки (как раньше) + раскрывающийся «💳 Оплатить СБП/картой» с реквизитами + большой кнопкой «✅ Я перевёл деньги, подтверди» (вместо старой «Написать @nikkronos»).
- Cron: `scripts/expiry_reminder.py` — отправка через TG API, шаблоны T-7/T-3/T-0, разовая отправка на цикл подписки.
- Cron entry на Fornex: `0 9 * * * cd /opt/vpnservice && /opt/vpnservice/venv/bin/python scripts/expiry_reminder.py 2>&1 | logger -t expiry-reminder`.

**Чего НЕ делали (durable):**
- Cryptomus, IMAP-парсер Т-Банка (вариант C из «Автоматизации платежей»), Lava.top + самозанятость — всё отложено, владелец 2026-05-27 явно решил не идти в эту сложность пока.

**Phase C (переезд на @vpnkronos_bot) — план онбординга зафиксирован в ROADMAP:**
- При `/start` для новых: email → OTP → дисклеймер → «🎁 14 дней бесплатно» → меню.
- Существующих (`email_verified=1` после миграции) — сразу в меню.
- Делается, когда владелец готов сделать broadcast в старом боте и подменить токен.

---

## Дополнение (поздний вечер 2026-05-27 / ночь 28-го) — ребрендинг бота + новое меню + полировка UX

Серия мелких UX-правок по фидбэку владельца, без архитектурных изменений.

### Бот
- **Ребрендинг ForFriends → Kronos** в тексте приветствия. Канал `@vpnkronos` вместо `@vforfriends`.
- **Подменю «📲 Получить VPN»** — раньше сразу вело в платформа-селектор для AmneziaWG. Теперь — экран выбора из 3 опций:
  - `🔗 Быстрый VPN` — subscription URL (`/sub/<token>`) + QR-картинка + ссылка отдельным plain-text сообщением (для удобного тап-копирования на мобильных).
  - `📲 Резервный VPN` — старый AmneziaWG-флоу (платформа → .conf).
  - `📡 Мобильный VPN` — VLESS при блокировках.
- **«🔄 Обновить конфиг»** теперь с подтверждением: «⚠️ Сбросится. Все устройства отвалятся.» + кнопки Да/Отмена.
- **«📨 Разблокировка Telegram» → «📨 Proxy для Telegram»** (rename).
- **Левая кнопка input bar — `MenuButtonCommands`** (обычное «Меню» с командами), не `MenuButtonWebApp`. Mini App теперь не висит постоянно слева, но есть инлайн-кнопка «🌐 Открыть личный кабинет» в /start-сообщении и команда `/lk`.
- **set_my_commands**: `/start /lk /status` — выпадающее меню «Меню» слева.
- **`cmd_status`**: фикс расчёта `days_left` (раньше всегда был 0 → ложная «истекла»). Убран блок про VPN-peer (сервер/IP) по фидбэку. Добавлена строка «🌍 Сервер: Германия».

### ЛК (Mini App)
- **«📨 Разблокировка Telegram»** в главном меню (поднята из «Резервных конфигов» — это независимый сервис, не VPN-канал). В «Резервных конфигах» осталось 2 кнопки (AmneziaWG + VLESS при блокировках).
- **«🔗 Подписка — рекомендуется» → «🔗 Доступ к VPN.»** + обновлённый текст + кнопка «Скопировать ссылку» без эмодзи.
- **«💳 Оплатить СБП/картой»** — теперь отдельный substep (`stepManualPay`), не раскрывающийся блок. С навигацией через TG BackButton.
- **Реферал-блок** — переключён в режим «В разработке. Скоро добавим…» (рефералка отложена). Сам функционал `db_apply_referral_bonus` в коде остался, включится когда вернёмся к задаче.
- **Убран блок «💬 Комментарий к переводу»** в ручной оплате — не нужен по фидбэку.

### Коммиты этой ночи

| commit | что |
|---|---|
| `3a4eb0c` | бот: ребрендинг Kronos + Mini App кнопка в /start |
| `6376778` | бот меню: подменю «Получить VPN» + подтверждение «Обновить конфиг» |
| `c9f21c6` | «Proxy для Telegram» + статус с подпиской + ссылка отдельным сообщением |
| `c6d0a41` | бот status: фикс расчёта days_left |
| `f0ce23d` | бот: вернуть «Меню» слева + убрать VPN-блок из /status |
| `8bb1ac8` | бот: /lk команда + строка «Сервер: Германия» в /status |
| `22367f9` | ui: оплата СБП/карта как отдельный substep + текст «Доступ к VPN» |
| `e1b90ea` | ui: реферал «В разработке» + детализация Phase C в ROADMAP |

### Текущее состояние (закрепляю для следующей сессии)
- **Бот**: `@thisvpnforfriends_bot`, токен пока старый. Внешне выглядит как «VPN-бот Kronos». Готов к переезду по команде владельца.
- **Donation-flow + Stars (oneshot + Subscription)** — работают параллельно. Stars зачисляется автоматически, donation требует кнопки владельца ✅/❌.
- **Cron T-7/T-3/T-0** напоминания работают (`0 9 * * *` UTC = 12:00 МСК).
- **Enforcement** ВЫКЛЮЧЕН. Все юзеры (включая grandfather) имеют VPN-доступ. Включение — по команде владельца (вариант A или B в моей терминологии).
- **Phase C (переезд на @vpnkronos_bot)** — план + спека в ROADMAP, ждёт триггера.
- **Email-кампании** — задача в ROADMAP, 6 open questions владельцу.
