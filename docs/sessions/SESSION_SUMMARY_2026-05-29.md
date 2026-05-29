# SESSION SUMMARY — 2026-05-28 / 29

> Покрывает период между `SESSION_SUMMARY_2026-05-27.md` и текущим моментом
> (≈ 25 коммитов с вечера 2026-05-27 до ночи 2026-05-29).
> Цель: закрыть рассинхрон ROADMAP с реальным состоянием.

---

## TL;DR

- ✅ **Фаза 3b proper — DONE 2026-05-28.** Swap токена на `@vpnkronos_bot`, FSM-онбординг (дисклеймер → email/OTP → выбор триала), enforcement gate под флагом `ENFORCEMENT_ENABLED=1`, команда `/migrate_reset`, колонка `users.migrated_at`. Коммиты: `5e73512`, `0ed6ffc`, `f872b70`.
- ✅ **Фаза 3h — broadcast выполнен владельцем.** 34 legacy юзера получили уведомление через старый бот, новый бот `@vpnkronos_bot` активен.
- ✅ **Support Variant B — DONE 2026-05-28** (`52eaea0`). Двусторонняя переписка (не только форвард). Тикеты `support_tickets` + `support_messages` в SQLite. Owner inline-кнопки [✉️ Ответить / ✅ Закрыть / 📜 История]. Deeplink `?start=support` из ЛК.
- ✅ **Триал enforcement + grandfather** — включено вместе с Phase 3b (`ENFORCEMENT_ENABLED=1`). Grandfather (`expires_at IS NULL`) проходят через `db_is_access_active`, новые юзеры получают triаl выбором в онбординге.
- ✅ **Регрессия MenuButtonWebApp** — закрыта косвенно: левая кнопка переключена на `MenuButtonCommands` (`f0ce23d`), Mini App доступен через `/lk` и инлайн-кнопку в `/start`.
- ✅ **Аудит инструкций бота — переписаны** под 3-уровневую модель (Быстрый VPN / Резервный VPN / Мобильный VPN). Коммиты `4534aa7`, `b743e58`, `8508662`, `8821733`.
- ✅ **Серверная безопасность** — nginx HSTS + security headers + TLSv1.2/1.3 (`0a45c4e`), Flask биндим на 127.0.0.1 (`10fe107`).
- ⏸ **Реферал-флоу** — в UI переведён в режим «В разработке» (`e1b90ea`). Бэкенд (`db_apply_referral_bonus`) остаётся, но фронт спрятан.

---

## Что сделано — детально

### 1. Миграция на @vpnkronos_bot (Phase 3b proper)

**Коммит `5e73512` — migration pre-flight**:
- БД: колонка `users.migrated_at`, хелперы `db_mark_migrated`, `db_is_migrated`, `db_get_non_migrated_users`, `db_clear_sub_token`, `db_clear_vless_uuid`.
- Config: ENV-флаги `ONBOARDING_ENABLED`, `ENFORCEMENT_ENABLED` в `bot/config.py`.
- Enforcement gate: `_check_access_or_block(chat_id, tid)` на хендлерах `vpn_quick`, `menu_get_config`, `menu_regen_confirm`, `menu_mobile_vpn`. MTProxy не гейтится (открыт для всех).
- Web: `/api/recovery/awg-config-by-email` и `/api/recovery/mobile-link-by-email` → 402 `subscription_inactive:true` при истёкшем доступе.
- FSM-онбординг: дисклеймер (5 пунктов) → email (с опцией «использовать существующий, если есть») → OTP → авто-trial 14 дн → меню. Состояния через `_onboarding_state` dict.
- `/migrate_reset` (admin only, двушаговая `превью → RESET`): удаляет AWG peer + VLESS UUID + sub_token у не-перешедших. БД-запись и email сохраняются.

**Коммит `0ed6ffc` — hotfixes**:
- Исправлена сигнатура `send_otp_email`.
- Synthetic-email detection (старый код мог генерить искусственные emails — теперь определяет и не считает их «привязанными»).
- Тайминг `migrated_at` (ставить после успешного онбординга, не на старте FSM).

**Коммит `f872b70` — trial choice**:
- После OTP — выбор «🎁 Активировать 14 дней» / «⏭ Пропустить».
- При «Пропустить» — `expires_at=NOW` (истёкшая), но `trial_used=0` (триал остаётся доступным позже).
- В главном меню кнопка «🎁 Активировать 14 дней бесплатно» — видна если `trial_used=0 AND (expires_at IS NULL OR days_left=0)`.
- `trial_available` в `/api/account/info` теперь учитывает и skip-сценарий.

### 2. Support — Variant B (двусторонняя)

**Коммит `52eaea0`**:
- БД: `support_tickets` (open/closed) + `support_messages` (sender, text, photo_file_id). Один open-тикет на юзера за раз.
- Юзер: «🆘 Поддержка» в меню → FSM ожидания сообщения → пишет текст/фото с подписью → бот форвардит admin + ack юзеру. Ответ owner-а возвращает юзера в state продолжения треда.
- Deeplink `/start support` (из ЛК → `openTelegramLink`) — сразу запускает support-флоу.
- Owner: уведомление с контекстом (username/id/email/статус) + inline-кнопки [✉️ Ответить / ✅ Закрыть / 📜 История]. «Ответить» → FSM текст/фото → доставка с пометкой «💬 Ответ от поддержки (тикет #N)».
- Команды владельца: `/support_list`, `/support_view N`, `/support_close N`.
- ЛК: кнопка «🆘 Поддержка» → `openTelegramLink` на `@vpnkronos_bot?start=support`.

### 3. ЛК (Mini App)

- **Ребрендинг** (`4d2bc96`): «ForFriends VPN — личный кабинет» → «VPN Kronos — личный кабинет». Слоган «Работает 24/7 почти на всех операторах». Убран футер с last-update. Actionable error для orphan-юзеров: «Открой @vpnkronos_bot и пройди /start».
- **Substep для оператора/платформы** (`d917c40`): клик по оператору → `stepMobileResult` с динамическим заголовком («📡 VPN при блокировках — Yota»). То же для платформы → `stepAwgResult`. Унифицированные тексты (нет особого блока про cloud.mail.ru). Убран Error-103 fallback из ЛК (остался в инструкциях бота).
- Реферал переведён в режим «В разработке» (`e1b90ea`) — бэкенд жив, UI спрятан.

### 4. Бот UX

- Ребрендинг `ForFriends → Kronos` в текстах (`3a4eb0c`). Канал `@vpnkronos` вместо `@vforfriends`.
- Подменю «📲 Получить VPN» — 3 опции (Быстрый/Резервный/Мобильный) вместо прямого AWG-флоу (`6376778`).
- «🔄 Обновить конфиг» с подтверждением (`6376778`).
- «📨 Разблокировка Telegram» → «📨 Proxy для Telegram» (`c9f21c6`).
- `MenuButtonCommands` вместо `MenuButtonWebApp` слева (`f0ce23d`). Mini App через `/lk` или инлайн-кнопка в `/start`.
- `set_my_commands`: `/start`, `/lk`, `/status` (`8bb1ac8`).
- `cmd_status`: фикс расчёта `days_left` (`c6d0a41`), убран блок про peer/сервер по фидбэку (`f0ce23d`), строка «🌍 Сервер: Германия» (`8bb1ac8`).
- «Мой статус» → «Статус подписки» в главном меню (`b808068`).
- **iOS bug fix** (`8821733`, `8508662`): `_do_get_config` и `_do_regen` для eu1 выдавали VLESS+REALITY для всех платформ (legacy путь не обновлён при переезде на AmneziaWG-as-Резервный). Теперь корректно: AWG → `.conf` для PC/iOS, `vpn://` deep link для Android. VLESS — только в Быстром VPN и Мобильном VPN.
- Тексты инструкций (`4534aa7`, `b743e58`, `8508662`): rewrite под 3-уровневую логику, «Windows» → «ПК», AmneziaWG step-by-step под платформу.

### 5. Серверная инфраструктура

- **nginx security** (`0a45c4e`): HSTS + security headers, TLSv1.2/1.3 only.
- **Flask на 127.0.0.1** (`10fe107`): снаружи закрыт, доступ только через nginx :8443. `FLASK_HOST=0.0.0.0` — для локальной отладки.
- **Google Sheets sync** (`d62939b`): добавлены колонки `sub_token`, `days_left`, `migrated_at` в выгрузке (для аналитики оwнером).
- **`/admin/credit`** (`d62939b`): кнопка «Зачислить дней» + HTML-теги в hint исправлены.

### 6. ROADMAP — добавлено за период

(Сами добавки в ROADMAP — не «сделанная работа», а зафиксированный беклог. Для полноты картины.)
- 4 новые задачи (`98534b6`): тарифы/прайс-лист, текст онбординга при росте, оператор «Волна», скорость прокси.
- Расширение «скорость падает» — 2 фидбэка + план мониторинга (`300f1e4`).
- Конкуренты (`9776c19`): Сота / Whale / Gear Up / blacktemple / toshib + кейс «арендую Fornex сам».

---

## Что осталось открытым (для следующей сессии)

### Монетизация
- Автозачисление СБП/карты (4 варианта на столе, владелец отложил).
- Phase 3i — лендинг/оферта/контакты (блокер ЮKassa). Нужны: ФИО, ИНН, контактный email, утверждение описания.
- Phase 4 — ЮKassa.
- Email-кампании / транзакционные письма (5 шаблонов, 6 open questions владельцу).
- Тарифы / прайс-лист (грейды).

### Продукт
- УТП и позиционирование (одно предложение + адаптация текстов).
- Split tunneling (unified-профиль) в UI бота.
- Сайт ЛК независим от Telegram.
- Per-device конфиги (после платящих).
- Per-user UUIDs для main REALITY.
- Аудит остальной markdown-документации в `docs/`.
- Текст онбординга при росте аудитории.

### Каналы
- Мегафон при БС (нужна разведка через Мегафон-друга).
- Оператор «Волна» (Крым) — юзер Unatham готов тестить.
- «Прокси иногда теряет скорость» — диагностика eu1/throttling.

### Реферал
- Включён `db_apply_referral_bonus` в Stars/manual, но UI временно «В разработке». Когда вернёмся — нужен end-to-end тест на двух аккаунтах.

### Технический долг
- Домен для admin/recovery с whitelist при БС.

---

## Текущее состояние сервиса (зафиксировать для следующей сессии)

- **Бот**: `@vpnkronos_bot` (новый токен в env). Старый `@thisvpnforfriends_bot` молчит.
- **`ONBOARDING_ENABLED=1`, `ENFORCEMENT_ENABLED=1`** — флаги выставлены при swap токена.
- **Donation-flow** + **Stars (oneshot + Subscription)** работают параллельно.
- **Cron T-7/T-3/T-0** напоминания — `0 9 * * *` UTC = 12:00 МСК.
- **Support Variant B** — активен.
- **34 grandfather** проходят `db_is_access_active` (NULL → активно). Triаl у них не доступен. Новые юзеры стартуют через FSM-онбординг.
- **Реферал** — бэкенд работает, UI спрятан.

---

## Коммиты периода (хронология)

```
2026-05-27 23:12  58be672  donation-flow + T-7/3/0
2026-05-27 23:30  22367f9  ЛК: оплата СБП substep + «Доступ к VPN»
2026-05-27 23:49  e1b90ea  реферал «в разработке» + детализация Phase C
2026-05-28 00:00  3a4eb0c  бот: ребрендинг Kronos + Mini App в /start
2026-05-28 00:09  6376778  бот: подменю «Получить VPN» + подтверждение regen
2026-05-28 00:25  c9f21c6  «Proxy для Telegram» + ссылка отдельным сообщением
2026-05-28 00:37  c6d0a41  бот status: days_left fix
2026-05-28 00:44  f0ce23d  бот: «Меню» слева + убрать VPN-блок /status
2026-05-28 00:49  8bb1ac8  бот: /lk + «Сервер: Германия»
2026-05-28 00:51  2c8290d  docs: дополнение SESSION_SUMMARY_2026-05-27
2026-05-28 00:55  59021d5  docs: runbook миграции
2026-05-28 01:14  a60a29f  docs: финализация migration plan
2026-05-28 01:26  5e73512  migration pre-flight (Phase 3b proper)
2026-05-28 01:42  0ed6ffc  migration hotfixes
2026-05-28 11:07  f872b70  trial choice в онбординге
2026-05-28 11:15  8821733  бот: «Резервный VPN» = AmneziaWG (не VLESS)
2026-05-28 11:30  8508662  бот: iOS bug + новые AmneziaWG-инструкции
2026-05-28 11:39  4534aa7  instructions: rewrite + «Windows» → «ПК»
2026-05-28 11:45  b743e58  instructions/pc: убраны Mobile VPN и Error 103
2026-05-28 12:01  4d2bc96  ЛК: ребрендинг + слоган
2026-05-28 17:21  d917c40  ЛК: substep для оператора/платформы
2026-05-28 17:35  d62939b  HTML hint + «Зачислить дней» + Sheets cols
2026-05-28 17:51  10fe107  Flask на 127.0.0.1 + Google Sheets fix
2026-05-28 17:59  0a45c4e  nginx: HSTS + TLSv1.2/1.3
2026-05-28 18:13  98534b6  roadmap: 4 новые задачи
2026-05-28 21:54  52eaea0  Support Variant B (двусторонний)
2026-05-29 00:44  b808068  «Мой статус» → «Статус подписки»
2026-05-29 00:48  300f1e4  roadmap: расширил «скорость падает»
2026-05-29 00:53  9776c19  competitors: + 5 новых + кейс «Fornex сам»
```

---

## Дополнение (день 2026-05-29) — видимость инфраструктуры

По запросу владельца: «нужно видеть кто использует VPN, кто прокси, где нагрузка, чтобы поддерживать инфру». Сделано тремя этапами.

### Этап 1 — Диагностика рассинхрона peer-данных (read-only)

Создан `scripts/peers_sync_check.py` — сравнивает три источника:
1. БД (`db_get_all_users`)
2. `peers.json` (`get_all_peers()`, фильтр `eu1`)
3. Runtime AWG (`docker exec amnezia-awg2 awg show awg0 dump`)

**Запуск:** `cd /opt/vpnservice && venv/bin/python scripts/peers_sync_check.py`.

**Результат прогона 2026-05-29:**
- `peers.json`: 15 eu1 active peers.
- `awg show`: 18 peers.
- БД: 37 users (36 с telegram_id).
- ✅ `lost after reboot: 0` — persistent state работает, все JSON peer-ы существуют в AWG.
- ⚠️ 3 orphan-peer-а в AWG runtime без записи в peers.json (legacy/тестовые, безвредны). Зафиксировано как задача в ROADMAP «Зачистка orphan-peer-ов».
- 26 users в БД без AWG peer-а: 8 с `migrated_at` (онбординг-стейдж, прошли FSM, не нажали «Получить VPN»), остальные — старые без `migrated_at`. Конверсия `онбординг → конфиг` после миграции ≈ 30%.

### Этап 2 — Админ-панель показывает всех юзеров

Раньше `/api/traffic` фильтровал только тех, у кого есть AWG peer → 11+ юзеров с онбординга невидимы. Теперь видны все.

**Файлы:**
- `web/app.py` — `/api/traffic` переписан: итерация по `db_get_all_users()`, peers индексируются по telegram_id. Для каждого юзера считается:
  - `status` ∈ {`active`, `idle`, `onboarding`, `no_config`, `expired`}
  - `days_left` (NULL = grandfather, маркер `∞`)
  - peer-данные (или None для без-peer-а)
  - Сортировка по статус-приоритету + последней активности.
- `web/templates/index.html` — добавлена колонка **«Статус»** между Email и IP, `colspan` 8 → 9.
- `web/static/main.js` — `renderStatus(u)` с бейджем + суффиксом по дням (`активен · 12д`, `истёк · −3д`, `активен · ∞`). Юзеры без peer-а получают CSS-класс `row-no-peer` (приглушены, на hover видны полностью).
- `web/static/style.css` — `.status-badge` + 5 вариантов (`.st-active/idle/onb/noconf/expired`) + `.row-no-peer`.

**Smoke-test после деплоя:**
```
total_users=36
  no_config: 18
  idle: 9
  onboarding: 8
  active: 1
```

`vpn-web.service` active, без 500.

### Этап 3 — Auto-sync Google Sheets каждые 6 часов

Раньше Sheets обновлялся только по ручному триггеру через бота. Теперь — крон.

**Файлы:**
- `scripts/sheets_sync_cron.py` — обёртка над `bot.google_sheets.sync_users_to_sheets`. Логирование через `logger -t sheets-sync` (как остальные кроны).
- Cron entry на Fornex: `0 */6 * * * cd /opt/vpnservice && /opt/vpnservice/venv/bin/python scripts/sheets_sync_cron.py 2>&1 | logger -t sheets-sync`.

**Тестовый запуск:** `Sheets sync OK: updated=37`. Sheets свежий.

Ручной триггер в боте «📊 Sync Google Sheets» **оставлен** как fallback / refresh-по-запросу.

### Что закрепилось в документации

- `CLAUDE.md` — в правиле №10 теперь все 4 cron'а (раньше упоминались только 2 из них).
- `CLAUDE.md` — расширен список `scripts/`.
- `ROADMAP_VPN.md` — добавлена задача «Зачистка orphan-peer-ов» (Приоритет 2).

### Файлы / коммит

- `scripts/peers_sync_check.py` (новый)
- `scripts/sheets_sync_cron.py` (новый)
- `web/app.py` — `/api/traffic` (рефакторинг)
- `web/templates/index.html` — колонка «Статус», colspan 9
- `web/static/main.js` — `renderStatus()` + поддержка без-peer строк
- `web/static/style.css` — `.status-badge` + 5 цветов + `.row-no-peer`
- `CLAUDE.md` — список cron'ов и скриптов
- `ROADMAP_VPN.md` — задача про orphan-peer-ов

Серверно (вне git): бэкапы `app.py`/`index.html`/`main.js`/`style.css` на Fornex с timestamp 1780049355.

---

## Инцидент orphan-удаления (день 2026-05-29) — урок

### Что произошло
После Этапа 1 диагностики (нашёл 3 peer-а в `awg show`, которых нет в `peers.json`) я предложил «зачистить их за 5 минут как косметику» и получил `да` от владельца. Удалил все три через `awg set awg0 peer <pk> remove` + `amnezia-save-conf.sh`. **VPN владельца оборвался прямо во время работы со мной** — он сидел через тот же сервис и был вынужден переключиться на сторонний VPN.

### Почему оборвалось
Один из удалённых peer-ов — `Sh4gHaXonhu4N11D…` — был **рабочим owner-peer-ом** владельца с 27 GB rx / 57 GB tx трафика и свежим last_handshake. Просто legacy: peer создавался до того, как `peers.json` стал источником истины для peer-метаданных. Отсутствие в JSON ≠ orphan.

В исходной диагностике этот peer показывался как:
```
Sh4gHaXonhu4N11D…  allowed_ips=10.8.1.1/32  endpoint=94.19.223.132:60636
```
— и endpoint, и нестандартный `allowed-ips`, и реальный объём трафика **сразу должны были остановить delete**. Я этого не сделал.

### Восстановление (~10 мин)
1. Из `/root/awg-orphans-removed-20260529-102349.log` достал public keys + полный AWG dump до удаления (была `endpoint:port`, `allowed-ips`).
2. Re-add peer-ов: `docker exec amnezia-awg2 awg set awg0 peer <pk> allowed-ips <ips>`.
3. Запустил `/opt/amnezia-save-conf.sh` для persist.
4. **Handshake не пошёл** — у восстановленных peer-ов отсутствовал PSK (в дампе он показывался как `(hidden)` и я его не сохранил). Сравнил с работающими peer-ами — у тех PSK был.
5. Нашёл общий PSK в `/opt/amnezia/awg/wireguard_psk.key` — для AmneziaWG один PSK используется для всех peer-ов интерфейса. Установил через `awg set awg0 peer <pk> preshared-key /tmp/psk.txt` для всех 3 восстановленных.
6. Владелец переподключился — handshake прошёл, туннель поднялся.

### Защитные правки
- **`scripts/peers_sync_check.py` обновлён** — категория `orphans on server` разбита на две:
  - `[⚠] LIVE peer-ы вне peers.json` — есть endpoint ИЛИ rx/tx > 0 ИЛИ last_handshake > 0 → «НЕ ТРОГАТЬ без анализа».
  - `[?] unused peer-ы вне peers.json` — всё на нулях → можно безопасно зачищать (с обязательным backup PSK).
  - Итоговая сводка показывает счётчики раздельно. В конце предупреждение про PSK в `/opt/amnezia/awg/wireguard_psk.key`.
- **Memory `feedback_no_delete_runtime_blind.md`** — зафиксирован durable урок: «не удалять runtime-объекты только на основании отсутствия в одном источнике; признаки жизни (endpoint/traffic/handshake) важнее консистентности с БД». Применимо ко всему — peer-ам, systemd units, nginx vhosts, cron entries.
- **ROADMAP_VPN.md** — задача «Зачистка orphan-peer-ов» снята; вместо неё `[~]` пометка «Legacy peer-ы вне peers.json — НЕ ТРОГАТЬ».

### Извлечённое правило для будущих сессий
**Один человек = два подтверждения для delete-операций.** Read-only диагностика и destructive cleanup не должны идти «одной серией» — между ними обязан быть явный stop-light. Когда показал что собираюсь удалить — ждать пока пользователь не скажет «да», даже если он уже сказал «да делай» на более раннюю задачу.
