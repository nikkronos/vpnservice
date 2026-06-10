# DONE_LIST_VPN — выполненные задачи VPN/Proxy проекта

## 2026-06-10 — yc2 досинхронизирован (sync_xray_users + health_check)

**Проблема:** yc2 (РФ-резерв, заведён 06-09 как статичный клон yc) не входил в cron-sync и мониторинг. cron `sync_xray_users.py --all --no-shared` держал main/yc актуальными, а yc2 застывал → с первыми оплатами/истечениями (~10.06) клиенты на yc2 дрейфнули бы: оплаченный без UUID на yc2 не пускается, истёкший с оставшимся UUID ходит бесплатно (мини-фрод-зона на резерве).

**Фикс:**
- `scripts/sync_xray_users.py`: запись `yc2` в `SERVERS` (ssh `yc2` / inbound `vless-xhttp` / flow="" / `db_column=vless_uuid_yc` — клон yc, общая колонка / sudo). `--server` choices += `yc2`; `--all` → `[main, yc, yc2]` (crontab не трогали — `--all` подхватил).
- `scripts/health_check.py`: yc2 в `REMOTE_HOSTS` + `REMOTE_CHECK_PLAN` (reachable/xray/:443/disk); `check_vless_config_consistency` расширен — yc2 сверяется с `db_yc` (детектор дрейфа клона). Счётчик проверок 23 → 27.

**Верификация (на проде, read-only сначала):** yc2 reachable через Fornex-jump, user `ubuntu`+passwordless sudo, inbound `vless-xhttp`, паритет 50/50/50 (db_yc / yc / yc2). Локальный+серверный AST OK. Dry-run sync yc2 (50 per-user, 0 shared). Реальный sync yc2: backup → validate OK → restart → xray active, :443 listening. `health_check --dry-run` = 27/27 green, `vless_config_consistency: cfg_yc2=50 (diff 0)`.

**Эффект:** оплаты/истечения теперь синхронизируются на yc2 автоматически; дрейф клона ловится health-check'ом. Первый шаг мастер-плана `docs/plan-blocking-antifraud-traffic-tariffs.md` закрыт.

---

## 2026-06-04 — UX-фикс: единый путь подключения (фидбэк @veryvoro)

**Диагностика:** @veryvoro «на мобильном ничего не работает». Сервер был исправен (23 OK/0 FAIL весь день). Корень клиентский: (1) AmneziaWG не работает на мобильном (UDP, by design); (2) её VLESS был на старой shared-ссылке, убитой Этапом 7 (03.06), новую персональную подписку не переимпортировала. Путь фрагментирован — юзер не знает, какой механизм нужен.

**Фикс** (тексты/разводка, логику не трогали; синхронно бот/ЛК/MiniApp):
- Ссылка-подключение (`/sub`) везде = **«Подключить VPN»** (раньше бот «Быстрый VPN», ЛК «Доступ к VPN»). Билинговую «подписку» (оплата) не трогали.
- Бот подменю «Получить VPN»: 🔗 Подключить VPN (главный) / 💻 AmneziaWG — макс. скорость ПК/Wi-Fi (⚠️ не для мобильного) / 📡 Мобильный.
- `🔄 Обновить конфиг` → **`🔄 Не работает`** → разводка ПК (сброс AmneziaWG) vs Телефон/«Подключить» (переотдаёт ссылку + «удали старый профиль в HAPP, добавь новую») — закрывает ловушку Ани.
- В тексте AmneziaWG — предупреждение «не для мобильного». Убрано враньё про «vpn:// отвалится».
- ЛК/MiniApp: заголовок «🔗 Подключить VPN», AmneziaWG-канал «не для мобильного интернета».

Задеплоено, смоук владельца прошёл. CLAUDE.md «Бот — текущий UX» актуализирован. Детали: `docs/sessions/SESSION_SUMMARY_2026-06-04.md`.

---

## 2026-06-03 — Админ-панель: активность+VLESS, /api/services из health-check; диагностика T-7

**Активность учитывает VLESS** (`d9464b4`): `/api/stats` счётчики `active_24h/7d/30d` теперь по `max(AWG handshake, VLESS last_seen, vless_requested_at)` per-юзер (тот же сигнал, что бейджи). Было «3 за 24ч» (AWG-only) → стало 16.

**`/api/services` из health-check state** (`d9464b4`): читает `/var/lib/vpn-health/state.json`, маппит на 5 user-facing сервисов (🛡️ AmneziaWG / 📲 VLESS Россия-main / 📲 VLESS Европа-yc / 🌐 VLESS-WS / 📎 MTProxy) + staleness (mtime>20мин→unknown, палит зависший health-check) + fallback. Убран захардкоженный неверный IP `158.160.0.1`. Фронт (index.html+main.js) — динамический рендер.

**Диагностика массового T-7 reminder** (`b6d66ab`): НЕ баг. `db_users_due_for_expiry_notif` корректна. Корень — при миграции 27.05 существующим выдали 14-дн триал вместо grandfather → ~30 истекают 10.06, разом достигли T-7. Решение владельца: оставить триал (монетизация). Доки/память исправлены (enforcement ВКЛ, grandfather не делали).

---

## 2026-06-03 — peers.json → SQLite Phase 3 (консолидация завершена)

Завершение консолидации хранения peers. После суток наблюдения за dual-write на проде:
- **Reconcile перед выключением:** `main` = `e6d460f` (UUID-агент закрыл Этапы 7-9, rebase на мой peers-слой сработал чисто). Мой `storage.py` не тронут агентом. Сервер == main.
- **Наблюдение успешно:** dual-write держался сутки — **27 json == 27 таблица, 0 расхождений**, за период **3 реальных peer-write** (новый сигнап + enforce) → write-path отвалидирован на живом трафике.
- **`storage.py`:** `DUAL_WRITE_JSON=False` — запись в `peers.json` отключена (файл остаётся статическим fallback-снимком, читается только если таблица пуста). Удалено мёртвое зеркало `users.json` (`_sync_user_to_json` + вызов) — SQLite единственный источник правды и для users.
- **Тест** (Python 3.13): 20/20, включая проверку что при `False` json не пишется.
- Задеплоено на Fornex (только `storage.py`, `database.py` агента не трогал), рестарт vpn-bot/web, верификация.

**Итог:** консолидация полная — JSON-файлы (`peers.json`, `users.json`) больше не пишутся, источник правды только `vpn.db`. Будущая Postgres-миграция теперь «одна БД → другая».

---

## 2026-06-02 — Мониторинг eu1 + чистка доков + .gitattributes

**Лёгкий мониторинг eu1** (`6eb38cc`): `scripts/eu1_monitor.sh` (cron `*/5`, теперь 8 кронов) пишет CSV (load/RAM/swap/conntrack/awg-peers/rx-tx eth0) в `/var/log/eu1-monitor.log`. Без speedtest (не грузим 100-Мбит порт). Под расследование жалоб «скорость иногда падает» — корреляция метрик с временем жалобы. Задеплоен, протестирован.

**Глубокая чистка доков** (`b1c548a`, `4f98e04`): 18 устаревших доков (classic-WG / Shadowsocks / Remnawave / historical эпохи) → `docs/archive/` (git rename, история сохранена). Баннеры «устарело/реализовано» на `spec-05`, `spec-07`, `deployment.md`, `eu1-setup-and-troubleshooting.md`, `backup-restore.md` (последний — добавлен блок «что бэкапить сейчас»: `vpn.db` + AWG PSK). 13 активных доков — фикс inbound-ссылок на `archive/`, битых ссылок в актуальных доках нет. `docs/` root ~40→31, `docs/specs/` ~10→4. DONE_LIST/sessions/archive не трогались (история).

**`.gitattributes`** (`0283986`): LF форсится для `*.sh`/`*.py` — защита от CRLF при ре-чекауте на Windows (скрипты деплоятся на Linux). Renormalize 0 изменений (блобы уже LF).

---

## 2026-06-02 — Уведомление РКН об обработке ПД подано (вариант B)

Стали оператором ПД (email + telegram_id юзеров) → подали уведомление на pd.rkn.gov.ru. **Номер 100306737, ключ 15161399.** Принято в ИС уполномоченного органа, в реестр ~неделя.

**Ключевые решения по ходу:**
- Уведомление **одно** (не два) — трансграничная передача = раздел внутри формы.
- **Вариант B (остаёмся на Fornex, подаём честно)** — взвесили против переноса управлялки (бот+`vpn.db`) на RU. Перенос отложен: риски (Telegram-API из РФ untested, корреляция отказов с TimeWeb-REALITY, кросс-граница SSH, тайминг с UUID-агентом) перевесили localization-выгоду. Бот управляет нодами через SSH — технически отвязан, но не сейчас.
- В форме: место БД = **Германия**; трансгранично = **США (Resend)** + **Германия (хостинг)**; организация, ответственная за хранение = **Fornex = ИП Лавков О.А., ИНН 772774400302, ОГРНИП 314774625401362, Москва** (российский ИП, хоть сервер в Германии); цель = «исполнение гражданско-правового договора»; основание = согласие + договор; категории ПД = email + «иные» (telegram_id, оплаты, тех.данные); субъекты = клиенты + «давшие согласие на трансгранично».
- РКН показал авто-плашку про 242-ФЗ (БД не в РФ) — ожидаемо для B, не отказ.

**Гайд по полям формы:** `docs/rkn-notification-guide.md` (с реальной структурой: выпадающие списки, ФИАС-справочник адреса, и т.д.).
**Разблокировало:** регистрацию мерчанта ЮKassa (следующий шаг владельца).

---

## 2026-06-02 — Консолидация peers.json → SQLite (таблица `peers`), Phase 0-2

«Переделать БД» (refactor-вариант — НЕ путать с Postgres-миграцией в P3). До этого peers жили **только** в `bot/data/peers.json` (таблицы `peers` в SQLite не было, вопреки старому описанию в CLAUDE.md — это был реальный второй источник правды, кусал 2026-05-29). Источник правды переведён в SQLite; публичный API storage не менялся → ~30 call sites не тронуты.

**Phase 0 — схема + миграция (`bot/database.py`, commit `689e8f2`):**
- Таблица `peers` (composite-PK `telegram_id:server_id:platform` — точная копия ключа peers.json) + индекс `public_key`. Без FK (сохранена вольность JSON: legacy/синтетические отрицательные tid).
- `_migrate_peers_json_to_sqlite()` в цепочке `init_db()` — идемпотентно, по образцу `_migrate_from_json` (users.json). Пропуск записей без wg_ip/public_key.
- `db_get_all_peers / db_upsert_peer / db_delete_peer`.
- `PRAGMA busy_timeout=5000` в `_conn()` — страховка от «database is locked» (bot+web+cron пишут конкурентно).

**Phase 1 — storage поверх БД (`bot/storage.py`):**
- `_load_peers_data()` читает из таблицы, fallback на JSON если таблица пуста.
- `upsert_peer/delete_peer` → запись в БД + dual-write зеркало `peers.json` (флаг `DUAL_WRITE_JSON=True`). Сигнатуры и dataclass `Peer` не тронуты.

**Скрипты:** `scripts/migrate_peers_check.py` (бэкап + сверка JSON↔таблица), `scripts/test_peers_sqlite.py` (self-contained тест, 18 проверок).

**Валидация перед прод-деплоем:** локально (Python 3.13, поставлен в эту сессию) — syntax/import + тест 18/18; **dry-run на КОПИИ реальных прод-данных** в /tmp (нулевой риск) — 26 JSON → 26 в таблице, 0 расхождений.

**Cutover (Phase 2, dual-write ON):**
- Бэкап прод (`peers.json` + `vpn.db` + старые `.py`) → `*.precutover.20260602-072957`.
- Деплой по SCP, миграция на проде **ДО рестарта**: 26→26, 0 расхождений. Рестарт vpn-bot + vpn-web — active, журнал чист.
- `peers_sync_check.py` поверх таблицы: **20/20 eu1-пиров == awg show**, 2 legacy LIVE-пира («НЕ ТРОГАТЬ») целы, lost=0. Веб 200.
- Смоук владельца: статус / Получить VPN / подписка / резерв per-device — бот отдаёт.

**Коммиты:** `689e8f2` (Phase 0-1), `ab215c6` (UTF-8 fix скриптов), `994973d` (CLAUDE.md sync). Велось в ветке `feat/peers-to-sqlite`, смержено в `main` (FF).

**Координация:** параллельно с per-user-UUID агентом (Этапы 7-9 на паузе). Сверено перед деплоем (md5 серверного кода == база) — затирания нет. Бриф агенту — по запросу владельца.

**Остаётся — Phase 3 (после ~03.06 10:45):** выключить `DUAL_WRITE_JSON` + убрать мёртвое зеркало `users.json` (`_sync_user_to_json`). После суток наблюдения за real write-path. Детали: `docs/sessions/SESSION_SUMMARY_2026-06-02.md`.

---

## 2026-05-27 — Telegram Stars + ручная СБП/карта + админ-форма зачисления (Phase 3g + 3g+)

Промежуточный платёжный стек до автоматизации. Stars-флоу + рабочий ручной флоу + админ-форма; авто-зачисление платежей вынесено отдельной развилкой в ROADMAP («Автоматизация платежей»).

**Phase 3g — Telegram Stars (одноразовая оплата, commit `d0155e8`):**
- `web/app.py`: `/api/billing/create-stars-invoice` — `createInvoiceLink` с currency=XTR, payload `stars_sub:{tid}:{days}:{ts}`. Константы `STARS_MONTHLY_PRICE=150`, `SUBSCRIPTION_DAYS_PER_PAYMENT=30`.
- `bot/main.py`: `pre_checkout_query` (approve all) + `successful_payment` хендлер. Парсит payload → idempotency через `db_find_payment_by_external_id(telegram_payment_charge_id)` → `db_record_payment` (status=succeeded) → `db_extend_subscription(+30 дн)` → `db_apply_referral_bonus(+14 дн обоим)` → уведомления юзеру и пригласившему.
- `web/static/recovery.js`: кнопка «⭐ Оплатить Telegram Stars (150 ⭐)» в payBlock, `tg.openInvoice` с callback.

**Phase 3g+ — Ручная СБП/карта + админ-форма (commit `8ee3541`):**
- `web/app.py`: константа `MANUAL_PAY` (СБП `+79213032918` Т-Банк, карта `2200 7007 6046 4759` Т-Банк, owner_tg `nikkronos`, rub `200`). Отдаётся в `/api/account/info`.
- `web/static/recovery.js`: pay-block теперь показывается всем (убрано `days_left > 730` скрытие — владелец-grandfather мог тестировать). Разворачивающийся блок «💳 Оплатить СБП / картой» с реквизитами (кнопка «Скопировать номер» / «Скопировать номер карты») + шаблон комментария «VPN <email>» + кнопка «✉️ Написать @nikkronos после оплаты» (`openTelegramLink` в TG, новая вкладка в браузере).
- `web/app.py`: **`/admin/credit`** — HTML-форма ручного зачисления оплаты (за `@_require_admin_auth`, render_template_string). Поля: email **или** telegram_id, дни, сумма, валюта (RUB/USD/XTR), провайдер (manual_sbp/card/crypto/other), external_id (idempotency), заметка. POST → `db_record_payment` (status=succeeded) → `db_extend_subscription` → `db_apply_referral_bonus`. Повторный submit с тем же `external_id` → ошибка, двойного зачисления нет.

**Фикс UX:**
- `trial_available = (not trial_used) AND (expires_at IS NULL)` — grandfather (`expires_at='2099-01-01'`) больше не видит кнопку триала. Ранее владелец случайно её активировал — статус стал «ПРОБНЫЙ ПЕРИОД», но 26500+ дней (безвредно).

**CSS:** `.manual-pay-box` (пунктирная граница сверху), `.manual-pay-title`, `.muted` — стилизация развёрнутого блока реквизитов.

**Что осталось:** автоматизация платежей — 4 варианта в ROADMAP (Crypto / Stars-subscription / уникальные копейки + парсер / самозанятость + Lava). Владелец думает.

---

## 2026-05-25 (вечер) — Домен `supportkronos.online`, прямой HTTPS на Fornex, subscription-спайк validated

Пост FSystem88/1717 → решили проверить модель «subscription-URL + HAPP» на нашей инфре (аддитивно).

**Спайк (БД/бэкенд):**
- `users.sub_token` + helpers (`db_ensure_sub_token`, `db_find_user_by_sub_token`).
- `GET /sub/<token>` → base64 наших REALITY-ссылок (YC `www.microsoft.com` + main `cloud.mail.ru`). Гейт `db_is_access_active` (хук enforcement Фазы 4).
- ЛК: блок «Подписка» (ссылка + QR). ProxyFix → за прокси Flask отдаёт https-ссылки.

**Дорога к HTTPS:**
- Купили `supportkronos.online` (reg.ru, WHOIS-privacy). Нейтральное «support»-имя — маскировка.
- CF Tunnel отвалился (Zero Trust требует не-Mir карту).
- CF proxy + Origin Rule + Browser Integrity Check off — серверно работало, но **HAPP падал в таймаут**. **Safari владельца тоже не открывает `https://supportkronos.online` через CF** (DPI RST = «сетевое подключение прервано»). → **Cloudflare не надёжен в РФ для нашего use-case** (durable finding).
- **Дроп CF.** A-запись → grey-cloud (DNS-only) → Fornex `185.21.8.91`. LE-сертификат через **DNS-01 via CF API token** (certbot-dns-cloudflare, авто-продление). **nginx на :8443 ssl http2** → :5001 (443 занят Xray REALITY). Файл `docs/scripts/nginx-supportkronos-8443.conf`.

**Validated в HAPP:** подтянулись 2 сервера (YC-Reality + RU-REALITY), Wi-Fi + LTE — работают. **БС-полевой тест отдельно** (БС сейчас нет).

**Закрепление:**
- `VPN_RECOVERY_URL=https://supportkronos.online:8443/recovery` в env (бот + ссылки).
- Инструкции ios/android/windows: URL заменён.
- ЛК: «Подписка» поднята выше — главный CTA, остальные каналы — «Альтернативные способы (конкретные конфиги)».
- `env_vars.example.txt` обновлён.

**Серверно (вне git):** A-запись grey, LE cert, nginx :8443, CF API token в `/root/.secrets/cloudflare.ini`.

**Также этим вечером:**
- Переименованы метки серверов в подписке: `YC-Reality / RU-REALITY` → **🇪🇺 Европа / 🇷🇺 Россия** (commit `0d74701`, URL-encoded UTF-8 в `_SUB_LABEL_MAP`).
- Создан **новый бот** в BotFather: `@vpnkronos_bot` (display `vpnkronos`). Токен у владельца + у нас (в env при деплое Phase 3b). Бренд: Kronos / VPN Kronos.
- Зафиксирована **цена 200 ₽/мес** (середина рынка, УТП «работает при БС»).
- Открыты для использования две большие TG-фичи: **Mini Apps** (auto-login через initData) и **Star Subscriptions** (Bot API 8.0). Mini App — доп. способ авторизации (email/пароль остаются). Stars — вторая кнопка оплаты после ЮKassa.
- **Master-план Phase 3+4+5: `docs/plan-phase-3-4-5.md`** (читать первым при потере контекста).
- **ЮKassa setup инструкция владельцу: `docs/yookassa-setup-instruction.md`** (200₽/мес, самозанятый, чеки через ФНС, webhook на `/api/billing/yookassa-webhook`).

**Что осталось:** Phase 1b (БС-robust RU clean-443 host), per-user UUID на main/yc, БС-полевой тест subscription, broadcast-миграция старого бота, **ЮKassa-регистрация владельцем**. Детали — `docs/plan-phase-3-4-5.md`.

---

## 2026-05-25 — Личный кабинет: модель аккаунта + UX + триал/реферал + пароль (Фазы 0–2)

Старт коммерциализации через ЛК. План по фазам: 0 модель → 1 домен/YC-хост/HTTPS+БС-тест → 2 UX ЛК → 3 бот под ЛК → 4 enforcement+оплата → 5 реферал-начисление.

**Фаза 0 — модель аккаунта (`bot/database.py`):**
- `users` +колонки: subscription_status, expires_at, trial_used, plan, referral_code, referred_by, password_hash. Таблица `payments`.
- Хелперы: subscription/trial/referral/payment/password (`db_is_access_active`, `db_extend_subscription`, `db_start_trial`, `db_ensure_referral_code`, `db_count_referrals`, `db_set_referred_by`, `db_set_password`, `db_has_password`, …). expires_at NULL = grandfathered.

**Фаза 2 — UX ЛК (`web/`):**
- QR-коды (qrcode[pil]) для VLESS / MTProxy / AmneziaWG-конфига (iOS/Android — скан в приложении).
- Заметная primary-кнопка копирования; единая колонка 640px + ритм (выравнивание/воздух); hero-заголовок + объяснение на входе.
- Экран **«Мой аккаунт»**: статус/срок, кнопка триала (14д), реферальный блок (код/ссылка/счётчик), быстрые кнопки каналов.
- **Вход по паролю** (email+пароль) + установка/смена пароля (werkzeug hash, ≥8); `verify-otp` ловит `?ref` для атрибуции.
- Эндпоинты: `/api/account/info`, `/account/start-trial`, `/account/set-password`, `/api/auth/login-password`. Константы TRIAL_DAYS=14, REFERRAL_REWARD_DAYS=14.

**Бот:** приветствие → «ForFriends» + ссылка на ЛК + канал `@vforfriends`.

**Инструкции бота переписаны (вечер, фидбэк тестера Ани):** ios/android/windows были устаревшими (iOS описывал VLESS+V2Box как основной, хотя основной = AmneziaWG) → нетехнический юзер не понимал, куда вставлять `vless://`. Теперь единая модель «два варианта, у каждого своё приложение» + явный блок «куда что вставлять» (vless → Streisand/Happ/V2Box/Hiddify; AmneziaWG-конфиг → Amnezia) + опора на ЛК с QR. Исправлена ошибка в Error-103 («Hiddify — тот же конфиг», неверно: в Hiddify только vless). Задача «конфиг на устройство» (iPad/iPhone оба `ios` → коллизия) — в ROADMAP, отложено до платящих.

**Решения:** домен — нейтральный на базе ForFriends (предпоч. не .ru); хост ЛК — YC (whitelisted, при БС нужен whitelisted-SNI хостинг); оплата — ЮKassa(карты+СБП)→Stars→крипта; триал 14д; реферал «дни обоим» +14.

**Косметика до Фазы 4:** enforcement выключен (у всех «Бессрочный»); реф-бонус начисляется при оплате; пароль по HTTP — безопасен только с HTTPS (Фаза 1).

Коммиты: `1cfb5ec`, `c0e2384`, `9d561ba`, `0b3f6a7`, `3647133`. Детали — `docs/sessions/SESSION_SUMMARY_2026-05-25.md`.

---

## 2026-05-24 — Учёт трафика lifetime + колонки Email/Всего + swap + диагностика скорости

**Панель мониторинга:**
- Колонка **Email** — галочка email-верификации (джойн `email_verified` по `telegram_id`). Caveat: только для юзеров с активным AWG-peer; полная картина — CSV.
- Колонка **Всего** — накопительный lifetime-трафик пользователя.

**Reset-aware учёт трафика (SQLite):**
- Таблица `traffic_accounting(public_key PK, telegram_id, lifetime_rx/tx, last_rx/tx, updated_at)`.
- `db_accumulate_traffic` — детект сброса счётчика (current < last → приращение = current); `db_get_lifetime_by_user` — SUM по юзеру (включая удалённые peer'ы).
- `/api/traffic` накапливает при просмотре + отдаёт `total_bytes`; `scripts/traffic_accounting.py` — cron `*/5` на случай простоя панели.
- Baseline засеян текущими счётчиками 24.05 (ретроактива нет, дальше растёт надёжно).

**Инфра (Fornex eu1, вне git):**
- **swap 2 ГБ** + `swappiness=10` — страховка от OOM (RAM 2 ГБ).
- cron `*/5 traffic_accounting.py`.

**Диагностика «упала скорость»:**
- Сервер здоров: load 0.31/2 ядра, CPU 86% idle, 0 пакетных ошибок, BBR+fq уже включены.
- Bandwidth: 4–8 потоков = 93–95 Мбит/с → **жёсткий потолок ~100 Мбит/с (порт VPS)**. Делится на всех онлайн-юзеров.
- Тариф: Cloud NVMe 2 (2/2/20), 936 ₽/мес. **Fornex подтвердил (тикет): порт до 100 Мбит/с, лимита трафика нет.**
- **Клиентский замер 2026-05-25** (ПК, СПб): без VPN 278↓, AWG **84↓**, VLESS 59↓. VPN не упирается в порт — узкое место путь RU→DE (RTT 2→60мс). **Решение: деньги не тратим** (апгрейд/переезд для одиночной скорости бесполезны). AWG ≈ +40% к VLESS → AWG основной.
- Коммиты: `9246d7a`, `8e71b02`. Детали — `docs/sessions/SESSION_SUMMARY_2026-05-24.md`.

---

## 2026-05-21 (вечер) — Recovery-сайт полный передел + Error-103 fallback

**Recovery (`/recovery`):**
- Удалены 3 legacy секции по Telegram ID + 5 legacy endpoint'ов: `/api/recovery/vpn`, `/mobile-vpn`, `/telegram-proxy`, `/proxy-link`, `/vpn-by-email`
- Новый UX: email/OTP → главное меню с 3 каналами → подстраница выбора → результат
  - **Основной VPN**: выбор ПК / iOS / Android → AmneziaWG-конфиг (для Android — `vpn://` deep link)
  - **Мобильный резерв**: выбор оператора → VLESS (megafon/yota → main REALITY cloud.mail.ru, остальные → eu1 REALITY)
  - **MTProxy**: кнопка «Открыть в Telegram» + ссылка
- Новые backend endpoint'ы: `/api/recovery/awg-config-by-email`, `/mobile-link-by-email`, `/proxy-link-by-email` — все по email-token (helper `_verify_email_session`)
- Стили: добавлен `.btn-menu` (большие многострочные) + `.btn-back`
- В UI после выдачи AWG-конфига есть встроенный Error-103 fallback с инструкцией

**Бот:**
- `instruction_windows_short.txt`: добавлен блок про AmneziaVPN Error 103 (закрыть Amnezia*, запуск от админа, перезагрузка, либо Hiddify как альтернатива)

**Что не сделано:** персональные UUIDs для main REALITY (запарковано в ROADMAP отдельной задачей).

---

## 2026-05-21 — Yota/Мегафон при БС РЕШЕНО + critical fix AmneziaWG persistent peers

**Главное:** ✅ **VLESS+REALITY на main Timeweb с SNI=cloud.mail.ru — работает на Мегафон/Yota при активных белых списках.** Подтверждено реальным тестом (друг на Yota, `digitalocean.com` режется → БС активны → VPN при этом работает).

### Архитектура решения
- **Whitelist у Yota** работает по IP-подсетям (whitelisted: Timeweb, VK Cloud, Mail.ru Cloud, Cloud.ru, Selectel) + SNI inspection (whitelisted: cloud.mail.ru, cloud.vk.com, и т.д.). Наш `81.200.146.32` (Timeweb) подтверждённо в whitelist.
- **REALITY** делает TLS Client Hello с SNI=`cloud.mail.ru` (whitelisted) → DPI пропускает → наш Xray расшифровывает VLESS-туннель внутри.
- **Dest = cloud.mail.ru** — Xray делает реальный TLS-handshake к cloud.mail.ru для fronting. Снаружи наш сервер выглядит как mirror Mail.ru Cloud (отдаёт настоящий cert от VK LLC).
- `cloud.vk.com` как dest не подошёл — нестандартный TLS, ломает REALITY-fronting (`target sent incorrect server hello`). Перебрали 6 кандидатов через openssl: cloud.mail.ru / yandex.ru / timeweb.cloud отдают чистый TLS 1.3.

### Серверная инфраструктура
- **main Timeweb** (`81.200.146.32`) — новая VPN-нода:
  - Установлен Xray VLESS+REALITY на :443 (private key + public key generated через `xray x25519`, shortid=04d9b6c0)
  - nginx на :80 для ACME (server_name=ru.vpnnkrns.ru, location /.well-known/acme-challenge/)
  - Let's Encrypt cert для `ru.vpnnkrns.ru` через certbot (auto-renew enabled)
  - WireGuard на UDP/51820 для 1 legacy user — оставлено без изменений
- **DNS:** Cloudflare → `ru.vpnnkrns.ru` (A) → `81.200.146.32`, **DNS only (grey cloud)**
- **Бот:** `VLESS_CDN_TLS_SHARE_URL` обновлён на новую REALITY-ссылку с main. Для оператора Мегафон/Yota приоритет: TLS-ссылка → HTTP-CDN → REALITY.

### VLESS-ссылка (текущая в боте для Мегафон/Yota)
```
vless://359e23cc-f90c-4e43-97af-bd1b662ff043@81.200.146.32:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=cloud.mail.ru&fp=chrome&pbk=QlzHHy5Z1QXBpSK8wtyrjPfFkGHnAoNorhflEyFkcFg&sid=04d9b6c0&type=tcp&headerType=none#RU-REALITY
```

### Critical fix: AmneziaWG потерял peers после reboot Fornex
- **Симптом:** после reboot Fornex 28 из 30 peers пропали из `awg show`. Пользователи получили `.conf` от бота, но не могли подключиться (handshake fail).
- **Причина:** скрипт `/opt/amnezia-add-client.sh` использовал `awg-quick save awg0 2>/dev/null || true` — команда fail-silent в нашем AmneziaWG-контейнере. Peers сохранялись только в running-state ядра, не в `/opt/amnezia/awg/awg0.conf`. После рестарта контейнера (от apt upgrade docker-ce + reboot) — потерялись.
- **Восстановление:** Python-скрипт проходом по `peers.json`, для каждого active eu1-peer'a → `docker exec amnezia-awg2 awg set awg0 peer <pubkey> preshared-key /tmp/psk.key allowed-ips <wg_ip>/32`. Восстановлено 21 peer (3 изначальных + 21 новых = 24 в awg).
- **Persistent fix:**
  - Создан `/opt/amnezia-save-conf.sh` — общий helper: `awg showconf awg0` + ручная вставка `Address = 10.8.1.0/24` → запись в `/opt/amnezia/awg/awg0.conf`.
  - `/opt/amnezia-add-client.sh` и `/opt/amnezia-remove-client.sh` пропатчены: вместо нерабочей `awg-quick save` вызывают `/opt/amnezia-save-conf.sh`.
  - Cron `*/5 * * * * /opt/amnezia-save-conf.sh` — safety net.

### Что НЕ сделали в этой сессии (пробовали и закрыли)
- WS-extension в YC API Gateway — поддерживает только Cloud Functions backend, не HTTP-passthrough (Path 1 из postmortem).
- VLESS+XHTTP через API Gateway с `'*': '*'` query passthrough — серверная сторона теперь работала (HTTP 200), но клиент Streisand iOS всё равно не устанавливал тоннель. Подтвердили окончательный вердикт postmortem'а: **XHTTP через любые Yandex HTTP/2-edge не работает у клиентов**. API Gateway удалён.
- VLESS+WS+TLS на main `ru.vpnnkrns.ru` — работает на Wi-Fi и других операторах. На Yota не работает: DPI режет TLS Client Hello с не-whitelisted SNI (симптом «сетевое подключение прервано» = RST после TCP-handshake). Этот промежуточный setup стёрт переводом на REALITY.

### apt upgrades (попутно)
- **YC vrprnt:** apt upgrade + reboot, kernel `6.8.0-117-generic`. Xray REALITY поднялся автоматически.
- **main Timeweb:** apt upgrade (без kernel update в этой партии). Reboot не понадобился.
- **Fornex eu1:** apt upgrade (docker-ce + libgnutls + rsync) + reboot, kernel `6.8.0-117-generic`. Простой ~3 мин. Все сервисы поднялись автоматом — именно этот reboot выявил скрытый баг AmneziaWG persistent peers.

### Коммиты
(будут после этой записи)

### Что нового в репозитории
- `docs/sessions/SESSION_SUMMARY_2026-05-21.md` — полная хронология
- `docs/scripts/nginx-ru-vpnnkrns.conf.example` — текущий nginx-конфиг на main (только :80 для ACME)
- `docs/scripts/xray-main-reality.json.example` — текущий Xray REALITY-конфиг на main
- `docs/scripts/amnezia-save-conf.sh.example` — helper-скрипт для persistent awg0.conf

---

## 2026-05-20 — Финальный тест CDN relay при активных БС

- **YC VM IP `158.160.236.147`** — протестирован на Yota при активном БС → "не смог подключиться к серверу". IP не в whitelist. Подтверждено окончательно.
- **Yandex CDN WebSocket** — запрос в поддержку YC → ответ: "техническая возможность отсутствует, сценарий не поддерживается". Закрыто окончательно.
- **Yandex CDN POST** — метод отсутствует в списке разрешённых методов CDN. XHTTP через CDN невозможен.
- **Следующий кандидат:** Yandex API Gateway (`*.apigw.yandexcloud.net`) — поддерживает WebSocket proxy. Проверить доступность при следующем БС событии.
- **Инфраструктура nginx на Fornex:** установлен nginx, роутит трафик на порту 80 по заголовку `Host` и `Upgrade`: WS → Xray:8080, XHTTP → Xray:8081. Xray переехал с порта 80 на localhost.
- **Исправлен баг:** YC VM использует Fornex:80 как WS outbound. После смены Xray на XHTTP relay сломался. Nginx исправил роутинг по `$http_upgrade`.

## 2026-05-19 — Yandex CDN relay (XHTTP) + выбор оператора в боте

- **Xray на Fornex:** транспорт порта 80 переключён WS → XHTTP (SplitHTTP). Путь `/vpn`, UUID без изменений.
- **Yandex CDN relay:** `cdn.vpnnkrns.ru` → Fornex:80 через XHTTP. CDN пробрасывает запросы к origin (подтверждено логами). Кеширование было уже выключено.
- **Выяснено:** Yandex CDN не поддерживает WebSocket через консоль — только через заявку в поддержку. XHTTP — обходное решение, CDN-совместимое.
- **Новая ссылка CDN:** `vless://359e23cc...@cdn.vpnnkrns.ru:80?type=xhttp&path=%2Fvpn` — добавлена в `env_vars.txt` как `VLESS_CDN_SHARE_URL`.
- **Бот — выбор оператора:** кнопка «📱 Мобильный VPN» теперь показывает клавиатуру (Билайн / Мегафон/Yota / МТС / Т-Мобайл / Т2). Мегафон/Yota получает CDN ссылку, остальные — REALITY.
- **Исправлен баг:** `parse_mode="HTML"` в `safe_reply()` вызывал `TypeError` → кнопка не реагировала.
- Тест CDN на Мегафон/Yota при активных белых списках — **ждём следующего события**.

## 2026-05-16 — Тест VLESS+REALITY при белых списках

- **VLESS+REALITY xHTTP (Yandex Cloud)** протестирован на Yota/Мегафон при активных белых списках РКН — **не работает**
- **AmneziaWG** при БС не работает нигде (UDP блокируется) — известно давно
- **T2 (Tele2)** — работает, у них нет жёстких белых списков
- Вывод: при активных БС у сервиса нет рабочего решения для Yota/Мегафон. Ограничение зафиксировано, решение требует протокол поверх HTTPS (Trojan TLS или аналог)

## 2026-05-15 — Авторизация веб-панели + трекинг прокси

- **Закрыта веб-панель `/`** от публичного доступа: HTML login-форма с Flask session (`session["logged_in"]`). Логин: `admin`, пароль: `ADMIN_SECRET`. `/recovery` остался публичным.
- **`web/templates/login.html`** создан и добавлен в git (тёмная тема, в стиле панели).
- **Убран Basic Auth** (не работал в Chrome без HTTPS, не передавался в fetch-запросах JS).
- **Колонка «Прокси»** в таблице пользователей: показывает когда пользователь последний раз запрашивал MTProxy-ссылку.
  - `bot/database.py`: миграция поля `proxy_requested_at`, функция `db_update_proxy_requested_at()`
  - `bot/main.py`: запись при нажатии кнопки «📎 Прокси Telegram» и команде `/proxy`
  - `web/app.py` + `web/static/main.js`: отображение в панели

## 2026-05-14 — Аудит безопасности веб-панели

- **`/api/users`**: убрана авторизация по telegram_id (легко угадать). Теперь требует `ADMIN_SECRET` — случайная 64-char hex строка из `env_vars.txt`.
- **Legacy recovery endpoints** (`/api/recovery/vpn`, `/api/recovery/telegram-proxy`, `/api/recovery/proxy-link`, `/api/recovery/mobile-vpn`): добавлена проверка `RECOVERY_SECRET` через заголовок `X-Recovery-Secret` или тело запроса. Без секрета — 403/503. Frontend (`/recovery`) использует email/OTP, эти эндпоинты не затронуты.
- **`/api/traffic`**: убран `telegram_id` из публичного ответа — остались только `username`, `wg_ip`, трафик.
- **`bot/config.py`**: добавлены поля `admin_secret` и `recovery_secret` в `BotConfig`.
- **`env_vars.example.txt`**: добавлены примеры новых переменных.
- Приватные ключи WG/Xray: не хранятся в БД, генерируются на сервере и отдаются единожды — OK.
- Email/OTP флоу: защищён session token'ом — OK.

## 2026-05-14 — IPv6 в AllowedIPs (защита от IPv6 leak)

- **Задача:** трафик к IPv6-адресам шёл мимо VPN — реальный IP виден на сайтах с IPv6.
- **Решение:** добавлен `::/0` в `AllowedIPs` для ПК и iOS конфигов.
- **Изменено:** `/opt/amnezia-add-client.sh` на Fornex (боевой скрипт eu1) + `bot/wireguard_peers.py` + оба примера в `docs/scripts/`.
- **Android:** не затронут — функция `_make_amneziawg_config_android_safe()` уже срезала `::/0` (Error 1000), всё работает корректно.
- **Примечание:** существующие конфиги не меняются, только новые и после `/regen`.

## 2026-05-11 — Защита сервера Fornex от брутфорса и UDP-флуда

- **Причина:** скачок CPU до 98.69% из-за SSH-брутфорса (нет fail2ban) + возможный UDP-флуд на порт 39580.
- **fail2ban** установлен и активен — банит IP после неудачных попыток входа.
- **SSH по паролю отключён** — только ключ. Важно: настройка была в `/etc/ssh/sshd_config.d/50-cloud-init.conf` (перекрывает основной конфиг).
- **SSH-ключ Fornex:** `C:\Users\krono\.ssh\id_ed25519_fornex`, алиас `ssh fornex` в `~/.ssh/config`.
- **Rate-limit UDP 39580** через iptables (1000 пакетов/сек), сохранён через `iptables-persistent`.
- **sysstat** установлен — история CPU/сети: `sar -u 1 10`.
- Подробно: `docs/sessions/SESSION_SUMMARY_2026-05-11.md`

## 2026-05-13 — Platform-based доставка конфига (vpn:// Android, файл iOS/PC)

- **Задача:** упростить подключение — убрать навигацию по файловой системе где возможно.
- **Новый флоу:** кнопка «📲 Получить VPN» в /start → выбор платформы [💻 ПК | 🍎 iOS | 🤖 Android] → доставка под платформу. То же для «Обновить конфиг».
- **Android:** `vpn://` deep link — тап в Telegram → AmneziaVPN импортирует автоматически. Реализован через `generate_vpn_url()` в `wireguard_peers.py`: qCompress (zlib + 4-байтный big-endian заголовок) + base64url.
- **iOS:** `.conf` файл + инструкция «Поделиться → AmneziaWG». Буфер обмена не поддерживается (нет кнопки в AmneziaWG iOS); QR из галереи тоже нет — только камера.
- **ПК:** `.conf` файл как раньше.
- **android_safe=True** автоматически для Android (один DNS, обход ErrorCode 1000).
- **Файлы:** `bot/main.py` (новые callbacks, `_deliver_config`, `_show_platform_keyboard`), `bot/wireguard_peers.py` (`generate_vpn_url`).

## 2026-05-13 — Задокументирован Trojan-сетап (проверенная схема, не нами)

- **Источник:** личный опыт знакомого, работает в РФ (май 2026).
- **Протокол:** Trojan поверх TLS — трафик неотличим от HTTPS.
- **Клиент:** ShadowRocket (iOS, платный ~$3). Поддерживает Trojan/VLESS/SS.
- **Ключевые настройки:**
  - UDP отключён — снижает поверхность детектирования.
  - **IPv6 отключён** — критично: несколько пользователей получили блокировку именно из-за IPv6-leak (туннель шёл через IPv4, а браузер/ОС коннектился по IPv6 напрямую).
- **Сервер:** VPS в Нидерландах (не российский хостинг).
- **Бонус-практика:** VPS с Ubuntu + GUI + Remote Desktop как «чистый браузер» для регистрации аккаунтов (Apple ID и др.) без запроса номера телефона.
- **Вывод для нашего проекта:** IPv6 leak — реальный вектор блокировки, не только теоретический. Учитывать при развитии.

## 2026-05-11 — Багфикс: eu2 → eu1 при /regen и /get_config

- **Проблема:** пользователи с `preferred_server_id = "eu2"` получали ошибку «Не удалось добавить peer в WireGuard» при `/regen`. Причина: `normalize_preferred_server_id` не конвертировала `eu2` → `eu1`, бот пытался использовать классический WireGuard (`wg0`) который уже не работает — сервер перешёл на AmneziaWG (`awg0`).
- **Фикс:** `bot/storage.py` — добавлен `"eu2"` в список legacy-слотов, нормализуемых в `eu1`.
- **Деплой:** патч применён точечно через `sed` на Fornex, `vpn-bot` перезапущен.

## 2026-05-09 — xHTTP packet-up на YC VM (обход ТСПУ-заморозки)

- **Проблема:** ТСПУ замораживает TCP+REALITY сессии после 15–20 КБ; `/mobile_vpn` не работает у Yota/MegaFon в whitelist-режиме.
- **Изменение:** транспорт на YC VM (`158.160.236.147`) переключён с `TCP + xtls-rprx-vision` на `xHTTP packet-up` (каждый пакет — отдельный HTTP-запрос, нет долгоживущей сессии для заморозки).
- **Файл на сервере:** `/usr/local/etc/xray/config.json` — `network: xhttp`, `xhttpSettings: {mode: packet-up, path: /download}`, убран `flow`.
- **Бот:** `VLESS_REALITY_SHARE_URL` в `/opt/vpnservice/env_vars.txt` на Fornex обновлена (`type=xhttp&mode=packet-up&path=%2Fdownload`); `vpn-bot.service` перезапущен.
- **Статус:** развёрнуто ✅, тест на MegaFon-SIM — ожидает фидбэка от пользователей.
- **Документация:** `docs/yandex-cloud-reality-setup.md` обновлён.

## 2026-05-08 — Анализ конкурентов, удаление eu2, редизайн панели мониторинга

### Анализ конкурентов

- **VlexNet:** balance-модель (бесплатно за рефералов), Mini App, Telegram-прокси бесплатно, 3 дня пробного, без карты.
- **Barin VPN:** 13 399 пользователей/мес, слот-машина как геймификация, Telegram OAuth для веб-кабинета, 199₽/3 устройства.
- **SPACE Connect:** уточнены данные — Mini App ✅ (через Happ), split tunneling, 8610 пользователей/мес, 1% партнёрская программа.
- Обновлена таблица сравнения в `docs/competitors-analysis.md` (7 конкурентов, новые строки: Telegram proxy, split tunneling, новостной канал, геймификация, подарочный VPN).
- **Вывод по анализу:** все конкуренты используют key-based систему (не .conf), белые списки у конкурентов не работают — наш VLESS+REALITY через YC — преимущество на LTE.

### Удаление eu2 из бота

- **`bot/wireguard_peers.py`:** `not in ("eu1", "eu2")` → `!= "eu1"` (3 вхождения); `get_available_servers()` — eu2 удалён.
- **`bot/storage.py`:** приоритет поиска peer `["rus1", "rus2", "eu1", "eu2"]` → `["eu1"]`.
- **`bot/main.py`:** все `in ("eu1", "eu2")` → `== "eu1"`; кнопка «🖥 Выбрать сервер» удалена из меню (3 места); удалены хендлеры `cmd_server` и `callback_server_select`; упоминание `/server` в тексте бота убрано.

### Редизайн панели мониторинга (http://185.21.8.91:5001/)

**Проблема трафика (root cause):** панель работает на eu1, старый код SSHился к eu1 с eu1 (self-SSH). AmneziaWG живёт в Docker-контейнере `amnezia-awg2` — `awg` недоступен на хосте напрямую.

**Исправление:** `_get_awg_dump_eu1()` теперь использует `docker exec amnezia-awg2 awg show awg0 dump` вместо локального subprocess.

**Изменения файлов:**
- **`web/app.py`:** добавлены `_parse_wg_dump_full()` (парсит rx, tx, last_handshake по pubkey), `_get_awg_dump_eu1()` (docker exec); `/api/traffic` возвращает список пользователей с rx_bytes, tx_bytes, last_handshake, отсортированный по трафику; `/api/services` упрощён до AmneziaWG + VLESS.
- **`web/templates/index.html`:** полный переписан — тёмная тема, статус-бар (AWG/VLESS точки, счётчики), таблица пользователей (IP, ↓ Принято, ↑ Отправлено, Последний сеанс), статическая сводка конфигов, footer с Recovery.
- **`web/static/main.js`:** переписан — `fmt(bytes)` (КБ/МБ/ГБ), `relTime(ts)` («● сейчас» / «N мин назад» / «N ч назад» / «никогда»), автообновление каждые 60 сек.
- **`web/static/style.css`:** полная замена старой светлой темы на тёмную неоновую (CSS variables, neon glow для dot-on, cyan accent, purple tx, зелёный «сейчас»).
- **`web/templates/recovery.html`:** удалён блок «Слот EU2», описание упрощено, кнопка переименована в «Восстановить VPN».

**Результат:** трафик отображается корректно (8.3 ГБ, 7.6 ГБ и т.д.), last_handshake показывает «● сейчас» / время, строки без трафика уходят вниз и затемняются.

## 2026-05-07 — Рефакторинг UX бота + git setup

- **VLESS code-блок:** `/mobile_vpn` теперь отправляет ссылку в `<code>` блоке — Telegram не авто-линкует `www.yandex.ru` внутри строки, копирование чистое.
- **Удалены команды:** `/get_config_android`, `/regen_android`, `/my_config`, `/help` — убраны из кода полностью.
- **Inline-меню /start:** вместо списка 13 команд — 7 inline-кнопок + кнопка ⚙️ Администратор (только владельцу).
- **Inline админ-панель:** 5 кнопок — статистика, пользователи, ротация прокси, добавить пользователя (state machine), рассылка с подтверждением.
- **Исправление:** `call.message.from_user` → `call.from_user` в menu-callbacks (бот ≠ пользователь).
- **GitHub:** первый коммит в `nikkronos/vpnservice`, 54 файла (реструктуризация + YC-Reality + bot refactor).
- **Yota:** расследование — ссылка корректная, проблема в whitelist MegaFon. Проверить при следующем событии.
- **Сессия:** `SESSION_SUMMARY_2026-05-07.md`.

## 2026-05-06 — Yandex Cloud VLESS+REALITY relay (резерв для LTE whitelist-режима)

- **Диагностика:** Timeweb (81.200.146.32) тоже недоступен на LTE — whitelist не включает даже российский хостинг.
- **Yandex Cloud VM:** создан аккаунт (грант 4000₽), VM `vrprnt` — Ubuntu 24.04, Shared-core 2vCPU/1GB, публичный IP `158.160.236.147`, зона `ru-central1-d`.
- **Xray:** установлен, конфиг VLESS+REALITY (port 443, SNI `www.yandex.ru`); UFW открыт 443/tcp; Security Group YC добавлено входящее правило TCP 443.
- **Ключи:** UUID `11dd653c-944b-4320-b29e-f1a9f2d75db8`, PublicKey `XKK9qJfFVdG3fegYC5vP8uF-OIzYK6YzKPz-sLVh_lE`, ShortId `ad88588f88ea4246`.
- **Бот:** `VLESS_REALITY_SHARE_URL` в `env_vars.txt` на Fornex обновлена на YC-Reality ссылку; `vpn-bot.service` перезапущен. Команда `/mobile_vpn` отдаёт YC-Reality ссылку.
- **Тест:** VPN подключается по Wi-Fi ✅. Тест на LTE в whitelist-режиме — ожидает следующего ограничения.
- **Документация:** `docs/yandex-cloud-reality-setup.md` создан с полными параметрами VM и конфига.
- **Сессия:** `SESSION_SUMMARY_2026-05-06.md`.

## 2026-05-05 — Cloudflare CDN стек для мобильного LTE (настроен, whitelist-блок)

- **Cloudflare:** зарегистрирован аккаунт, домен `vpnnkrns.ru` добавлен, NS изменены на CF (`ray`/`susan`), домен Active.
- **DNS:** `sub.vpnnkrns.ru` → A → `185.21.8.91`, Proxied; SSL Flexible; WebSockets включены.
- **Xray на Fornex:** конфиг переписан с REALITY на **VLESS + WebSocket** (port 80, no TLS); `ufw allow 80/tcp`; сервис активен.
- **env_vars.txt (Fornex):** `VLESS_REALITY_SHARE_URL` обновлена на CDN-ссылку (`sub.vpnnkrns.ru:443`, `type=ws`, `alpn=http/1.1`).
- **Итог:** LTE whitelist-режим блокирует даже Cloudflare IPs — решение отложено до снятия ограничений (после 9 мая 2026). CDN-стек сохранён как рабочий резерв для обычных условий.
- **Сессия:** `SESSION_SUMMARY_2026-05-05.md`.

## 2026-04-13 — Документирован предпрод-план коммерциализации + синхронизация с AI-идеями

- Добавлен документ **`docs/commercialization-prelaunch-plan-2026-04.md`**:
  - as-is архитектура (Fornex/Timeweb, слоты `rus1/rus2/eu1/eu2`, recovery и MTProxy flow);
  - prelaunch-риски (техника, продукт, коммерция/юридика);
  - обязательный минимум до платного запуска (PostgreSQL, production web stack, мониторинг, бэкапы/restore, webhook-безопасность, подписки);
  - этапный план A/B/C/D и Definition of Ready.
- Включена синхронизация с внешними AI-идеями из профильных чатов:
  - что брать в проект сейчас (PostgreSQL, agent-автоматизация рутины, точечные MCP-интеграции),
  - что отложить (рекламные Meta-агенты как не-core для VPN-инфраструктуры).
- `ROADMAP_VPN.md` обновлён: добавлен отдельный блок «Предпрод-пакет для коммерциализации» со ссылкой на новый документ.

## 2026-04-12 — Исправление доступа к мониторингу и recovery (UFW + обновление устаревших ссылок)

- **Причина:** после переноса `vpn-web.service` на Fornex порт 5001 не был открыт в UFW — сервис работал, но снаружи был недоступен. Дополнительно: ряд файлов содержал старые ссылки `81.200.146.32:5001` (Timeweb).
- **Сервер Fornex:** `ufw allow 5001/tcp && ufw reload` — панели `http://185.21.8.91:5001/` и `http://185.21.8.91:5001/recovery` снова доступны.
- **Репозиторий (2 коммита):**
  - `env_vars.example.txt` — пример `VPN_RECOVERY_URL` обновлён на Fornex IP.
  - `docs/mtproxy-proxy-rotation.md` — ссылка Web recovery и заголовок раздела обновлены (Timeweb → Fornex).
  - `docs/blocking-bypass-strategy.md` — URL панели мониторинга в разделе LTE-тестов обновлён на Fornex.
  - `docs/deployment.md` — шаг `ufw allow 5001/tcp` вынесен как **обязательный** пункт в разделе деплоя `vpn-web`; добавлен шаг проверки curl.
- **Сессия:** `SESSION_SUMMARY_2026-04-12.md`.

## 2026-04-11 — Документация и код: пост-миграция бота на Fornex (Россия `/get_config`, EU `/regen`, SSH)

- **Контекст:** бот на Fornex; Россия (rus1) — WireGuard остаётся на **main** (Timeweb). В проде выявлено: на Fornex не было **`wireguard-tools`** → в логах `FileNotFoundError: 'wg'`, пользователь не получал ответ на `/get_config` для России. Второй кейс: в `env_vars.txt` был путь **`WG_EU1_SSH_KEY_PATH=/root/.ssh/id_ed25519_eu1`**, файла ключа на новом VPS не было → `/regen` AmneziaWG (в т.ч. слот eu2) — ошибка SSH до eu1.
- **Операции на проде (зафиксировано для повторения):** `apt install -y wireguard-tools`; `ssh-keygen` для `id_ed25519_eu1` + добавление `.pub` в `authorized_keys` на EU; `systemctl restart vpn-bot`; проверка `ssh -i ... root@185.21.8.91 "echo OK"`.
- **Репозиторий:** **`docs/deployment.md`** — раздел «Бот (Telegram)» переименован с устаревшего «Timeweb»; добавлен **чеклист хоста бота после переноса на Fornex** (wg, WG_SSH_*, WG_EU1_SSH_KEY_PATH, eu2 vs SSH); правка примера `WG_EU1_SSH_KEY_PATH` в блоке env; MTProxy — правка «сервер бота» вместо только Timeweb. **`env_vars.example.txt`** — комментарий про ключ на хосте бота. **`README_FOR_NEXT_AGENT.md`** — путь к `env_vars.txt` и ссылка на чеклист. **`bot/wireguard_peers.py`** — при отсутствии `wg` поднимается понятный `WireGuardError` с текстом про `apt install wireguard-tools`; сообщение об ошибке SSH к eu1 без упоминания Timeweb, с шагами после переноса VPS.
- **Сессия:** **`SESSION_SUMMARY_2026-04-11.md`**.

## 2026-04-11 — `vpn-web` и `/recovery` на Fornex; отключение панели на Timeweb

- **Цель:** одна площадка с ботом — мониторинг **`http://185.21.8.91:5001/`** и **`/recovery`** на Fornex; **`VPN_RECOVERY_URL`** в `env_vars.txt`; трафик **main** на панели через **`WG_SSH_*`** (ключ `id_ed25519_main`, `authorized_keys` на Timeweb).
- **Systemd Fornex:** создан и включён **`vpn-web.service`** (`PORT=5001`), проверка `curl` → 200.
- **Timeweb:** **`systemctl disable --now vpn-web.service`**, порт 5001 не слушается.
- **Код/доки (репозиторий):** дефолт **`vpn_recovery_url`** и fallback в **`bot/main.py`**, **`bot/config.py`**; **`docs/deployment.md`**, **`docs/telegram-mtproxy-operators-guide.md`**, **`docs/vpn-web-migration-fornex-plan.md`** (статус «выполнено»), **`SESSION_SUMMARY_2026-04-10.md`**, **`README_FOR_NEXT_AGENT.md`**.

## 2026-04-10 — MTProxy Fake TLS на Fornex (порт 8444), починка `/proxy_rotate`, проброс `MTPROXY_*` в subprocess

- **Контекст:** после переноса бота на Fornex ротация MTProxy падала: Docker не мог занять **хост 443** — порт занят **`xray.service`** (REALITY). Принцип: не менять Xray/AmneziaWG; внешний порт MTProxy — **8444** (свободен; **8443** был у старого `mtproto-proxy`).
- **Код (репозиторий, `main`):** `bot/main.py` — понятное сообщение при конфликте порта 443; `subprocess.run(..., env=environment_for_mtproxy_rotate(...))`. `bot/config.py` — `environment_for_mtproxy_rotate()`: `os.environ` + все **`MTPROXY_*`** из `env_vars.txt`. `env_vars.example.txt` — пример `MTPROXY_PORT` / `MTPROXY_PUBLIC_IP`.
- **Прод Fornex:** `env_vars.txt` — `MTPROXY_PORT=8444`, `MTPROXY_PUBLIC_IP=185.21.8.91`, обновлён `MTPROTO_PROXY_LINK` после ротации; `git pull`, `systemctl restart vpn-bot`; контейнер **`mtproxy-faketls`** — `8444->443`; удалён **`mtproto-proxy`**.
- **Документы:** `SESSION_SUMMARY_2026-04-10.md`; план переноса панели/recovery на Fornex — `docs/vpn-web-migration-fornex-plan.md`.
- **Код (перенос панели):** `web/app.py` — трафик **main** через SSH при наличии `WG_SSH_HOST`; проверка MTProxy по порту из ссылки `/proxy`. `env_vars.example.txt` — `WG_SSH_*`; обновлены `docs/vpn-web-migration-fornex-plan.md`, `web/README.md`, `README_FOR_NEXT_AGENT.md` (главная `/` и `/recovery`).

## 2026-04-02 — Логические слоты rus1 / rus2 / eu1 / eu2 + recovery EU1+EU2 + ссылка прокси без рестарта

- **Цель:** четыре именованных слота профилей VPN; отдельные peers в `peers.json`; Европа — два AmneziaWG-слота на одном EU-хосте; на странице `/recovery` — два блока выдачи конфига (EU1 и EU2). Имена файлов конфигов включают `server_id` (например `..._eu1_amneziawg.conf`).
- **`bot/storage.py`:** ключи пиров `"{telegram_id}:{server_id}"`; миграция со старого формата: единственный peer без суффикса → слот **`rus1`** (legacy `main` в логах/каноне — см. `canonical_env_server_id`).
- **`bot/wireguard_peers.py`:** `canonical_env_server_id` — rus1/rus2 → физическая нода **main**, eu1/eu2 → **eu1** (env/SSH); общий пул IP для rus1+rus2 и отдельно для eu1+eu2 (Amnezia); `get_available_servers()` возвращает четыре слота; Amnezia create/regen с параметром `server_id` в `eu1`|`eu2`.
- **`bot/main.py`:** `/get_config`, `/regen`, `/server`, `/status` работают с нормализованными `rus1`/`rus2`/`eu1`/`eu2`; WireGuard-классика для RU-слотов, Amnezia — для EU-слотов.
- **`web/app.py`:** `POST /api/recovery/vpn` — только Amnezia (`server_id`: eu1|eu2), без перезаписи «чужого» слота через preferred_server. `api_servers` / `api_services` / `_get_wg_transfer_for_server` используют канонический id ноды для ping и SSH. **`GET /api/recovery/proxy-link?telegram_id=...`** — та же проверка пользователя, что у `telegram-proxy`, отдаёт актуальный `tg://` как `/proxy`, **без** перезапуска Docker.
- **Веб recovery:** `recovery.html` / `recovery.js` — два блока VPN (EU1, EU2); блок «Текущая ссылка MTProxy» + кнопка «Показать актуальную ссылку» и «Копировать»; при наличии сохранённого Telegram ID в `localStorage` ссылка подгружается при открытии страницы.
- **Деплой:** юнит бота на сервере — **`vpn-bot.service`** (не `vpnservice-bot.service`); после `git pull`: `sudo systemctl restart vpn-bot.service` и при необходимости `vpn-web.service`.

## 2026-04-02 (дополнение) — Spec-08: без нового VPS

- Решение владельца: **второй VPS не оплачивается.** Спека **spec-08** переписана: основной сценарий **B** — только **main + eu1** (несколько способов: WG, AmneziaWG, `/mobile_vpn`, `/proxy`; опц. REALITY на **main**, домен для MTProxy). Сценарий **A** (RU2/EU2 на отдельном VPS) оставлен как опция при появлении бюджета. Обновлены `ROADMAP_VPN.md`, `blocking-bypass-strategy.md`, `README_FOR_NEXT_AGENT.md`, `third-party-vpn-boosters-vs-multi-entry.md`.

## 2026-04-02 — Спека вторая нода (RU2/EU2), документ про GearUp/мульти-вход

- **`docs/specs/spec-08-multi-node-redundancy-ru2-eu2.md`** — первоначально план EU2/RU2; затем уточнение «без второго VPS» — см. дополнение выше.
- **`docs/third-party-vpn-boosters-vs-multi-entry.md`** — что такое GearUp-подобные приложения, чем наш мульти-вход аналогичен и чем клонировать их продукт нецелесообразно.
- **`docs/blocking-bypass-strategy.md`** — ссылка на spec-08 в блоке MVP; связанные документы дополнены.
- **`ROADMAP_VPN.md`** — раздел «Второй/резервный сервер» переписан под spec-08 и актуальный приоритет.
- **`README_FOR_NEXT_AGENT.md`** — ссылки на spec-08 и third-party doc.

## 2026-03-30 — Сводная документация MTProxy + обновление README

- **`docs/telegram-mtproxy-operators-guide.md`** — единое руководство: `/proxy`, `/proxy_rotate`, recovery, `get_effective_mtproto_proxy_link`, env, деплой через venv-pip, ссылка на альтернативы.
- **`README_FOR_NEXT_AGENT.md`:** команды `/proxy` и `/proxy_rotate`, URL recovery, правило №5 приведено к текущему коду; раздел «Документация» дополнен ссылками.
- **`SESSION_SUMMARY_2026-03-30.md`:** дополнение с итогами по MTProxy/recovery/документации pip.

## 2026-03-30 — Деплой: явный путь к pip в venv (PEP 668 на Ubuntu 24+)

- **`docs/deployment.md`:** установка зависимостей бота и панели через `/opt/vpnservice/venv/bin/pip` (не системный `pip`); блок «Обновление бота» — опциональный `pip install -r requirements.txt` при смене зависимостей; «Обновление панели» — тот же путь к pip; примечание про перезапуск `vpn-bot` при общих изменениях в `bot/`.
- **`docs/specs/spec-06-web-panel-deploy-and-traffic.md`**, **`web/README.md`:** согласованы команды с venv-pip.

## 2026-03-30 — Ротация MTProxy: /proxy_rotate, override-файл, документация

- **Цель:** «обновляемая» ссылка на MTProxy Fake TLS без ручного копирования в `env` при каждой смене секрета; пользователи по-прежнему получают актуальный `tg://` через `/proxy`.
- **Код бота:** `get_effective_mtproto_proxy_link()` в `bot/config.py` — приоритет `data/mtproto_proxy_link.txt` над `MTPROTO_PROXY_LINK`; fallback читает `env_vars.txt` с диска при каждом вызове; команда `/proxy_rotate` (только владелец) запускает `MTPROXY_ROTATE_SCRIPT`, парсит `MTPROTO_LINK=...`, пишет override; `/proxy` вызывает `load_config()` + эффективная ссылка.
- **Web:** `web/app.py` — recovery `telegram-proxy` использует эффективную ссылку для определения IP хоста; в JSON-ответ добавлены `mtproto_proxy_link` и `hint` (та же ссылка, что `/proxy`; при ошибке перезапуска контейнера ссылка всё равно отдаётся). `recovery.js` / `recovery.html` — понятный вывод ссылки пользователю.
- **Репозиторий:** `.gitignore` — `data/mtproto_proxy_link.txt`; `data/.gitkeep`; `env_vars.example.txt` — `MTPROXY_ROTATE_SCRIPT`.
- **Документация:** `docs/mtproxy-proxy-rotation.md`; `docs/scripts/mtproxy-faketls-rotate.sh.example`; ссылка из `docs/mtproxy-faketls-deploy.md`.

## 2026-03-30 — README: MTProxy Fake TLS vs «голый» MTProto; резюме сессии

- **`README_FOR_NEXT_AGENT.md`:** уточнены таблицы «что не работает на eu1» / «что работает»: обычный MTProto на eu1 — не использовать (блок по сигнатуре); **MTProxy с Fake TLS** на main (Timeweb, `docs/mtproxy-faketls-deploy.md`) — рабочий путь для Telegram; правило №5 приведено в соответствие с `docs/telegram-unblock-algorithm.md` (команда `/proxy` снята, ссылка через `MTPROTO_PROXY_LINK`/вручную).
- **`SESSION_SUMMARY_2026-03-30.md`:** зафиксированы итоги сессии (ревью плана, согласование документации по прокси).

## 2026-03-26 — LTE blackhole, MVP/юнит-экономика (документация)

- **`docs/blocking-bypass-strategy.md`:** дополнение 2026-03-26 — выводы по полевым тестам LTE (недоступность HTTP/HTTPS до main/eu1 IP при рабочем Wi‑Fi; мульти-вход для mobile).
- **`docs/mvp-unit-economics-and-plan.md`:** новый документ — юнит-экономика (формулы, пример брейк-ивена), риски, фазы MVP, рамка «строить vs покупать сервис».
- **`SESSION_SUMMARY_2026-03-26.md`:** резюме диагностики и рекомендаций следующим шагам.

## 2026-03-25 — Веб recovery: Telegram/VPN + ссылка в боте

- **Веб-панель:** добавлен отдельный маршрут `/recovery`, а recovery-блоки вынесены с главной страницы `/`, чтобы пользователи не путались с мониторингом.
- **UI recovery:**
  - добавлены кнопки “Восстановить Telegram” и “Восстановить VPN (конфиг)”;
  - вход по `Telegram ID`;
  - опция `Android-safe` для корректного DNS в VPN-конфиге.
- **Backend recovery (`web/app.py`):**
  - `POST /api/recovery/telegram-proxy` — перезапуск docker-контейнера Telegram proxy-кандидата (через SSH, по server_id `main`/`eu1`), проверка пользователя через `bot/data/users.json`.
  - `POST /api/recovery/vpn` — генерация/регенерация peer и выдача клиентского VPN-конфига.
- **Фронтенд:** вынесена логика recovery в отдельный JS-файл `web/static/recovery.js`.
- **Telegram-бот:** обновлены тексты `/start` и `/help` — добавлена строка со ссылкой `http://81.200.146.32:5001/recovery`, чтобы пользователи могли восстановить доступ при неработающем Telegram.
- **UX:** с recovery страницы удалена навигационная ссылка “Назад к мониторингу”, чтобы пользователи не переходили туда.

## 2026-03-23 (продолжение) — Документация попытки LTE + eu1

- **Файл:** `docs/mobile-lte-eu1-xray-reality-attempt-2026-03.md` — зафиксированы: внедрение Xray REALITY на eu1, Streisand, порты 443/4443, Fragment, tcpdump, Fornex firewall off, вывод о недоступности IP `185.21.8.91` с LTE; план дальше: REALITY на Timeweb (`81.200.146.32`) или другой ASN.
- **README_FOR_NEXT_AGENT.md** — добавлена ссылка на этот документ в разделе «Документация».

## 2026-03-23 — Мобильный резерв: VLESS+REALITY и команда /mobile_vpn

- **Контекст:** AmneziaWG и прокси работают по Wi‑Fi, по LTE/5G на разных операторах и устройствах — тайм-ауты; нужен TCP-транспорт с маскировкой под TLS, без отключения AmneziaWG.
- **Спека:** `docs/specs/spec-07-mobile-fallback-vless-reality.md`.
- **Развёртывание на eu1 (оператор):** `docs/xray-vless-reality-eu1-deploy.md` — бэкап AmneziaWG → установка Xray → `VLESS_REALITY_SHARE_URL` в `env_vars.txt` на Timeweb.
- **Код бота:** `bot/config.py` — чтение `VLESS_REALITY_SHARE_URL`; `bot/main.py` — команда `/mobile_vpn` (инструкция + вторая сообщение со ссылкой без HTML); обновлены `/start`, `/help`, `/instruction`.
- **Тексты:** `docs/bot-instruction-texts/instruction_vless_reality_short.txt`; `env_vars.example.txt`; `docs/backup-restore.md` (бэкап Xray); `docs/deployment.md`; `docs/blocking-bypass-strategy.md`; `README_FOR_NEXT_AGENT.md`.

## 2026-03-15 — Фиксация сторонних альтернатив для Telegram

- **Документация:** создан файл `docs/telegram-proxy-alternatives.md` — отдельный список альтернативных решений для Telegram (локальный SOCKS5 `tg-ws-proxy`, платные SOCKS5-прокси вроде `ru.shopproxy.net/buy-proxy/telegram/`), с пометкой, что это НЕ официальный стек проекта и без гарантий работоспособности.
- **Цель:** сохранить найденные в интернете и чатах варианты, чтобы не держать их в голове, но при этом явно указать, что основной и рекомендованный путь для Telegram — работа через VPN/AmneziaWG по текущей стратегии обхода блокировок РКН.

## 2026-03-07 — Telegram-прокси с Fake TLS, алгоритм разблокировки, оценка провайдера

- **Уточнения:** в README зафиксировано отсутствие relay-сервера в проекте; сторонний прокси 79.132.138.66:9443 (не работает) зафиксирован в алгоритме.
- **Документация:** созданы docs/provider-choice-evaluation.md (Fornex vs FirstVDS), docs/telegram-unblock-algorithm.md (алгоритм разблокировки Telegram), docs/mtproxy-faketls-deploy.md (пошаговое развёртывание MTProxy с Fake TLS; добавлен шаг установки Docker).
- **Развёртывание:** пользователь развернул на Timeweb (81.200.146.32:443) контейнер mtproxy-faketls (nineseconds/mtg:2, маскировка под 1c.ru). Прокси проверен — работает у владельца и у знакомого в Москве, скорость нормальная. Ссылка и секрет не в репо.

## 2026-03-14 — Диагностика тайм-аута AmneziaWG, команда /broadcast, документация

- **Проблема:** на телефоне (AmneziaWG) ошибка «Не удалось установить соединение» (тайм-аут 12 с), на ПК VPN работал. В мониторинге 0 Б по части пользователей.
- **Диагностика на eu1:** проверка через `docker exec amnezia-awg2 awg show awg0` — один peer без handshake (конфиг на телефоне не совпадал с сервером). Решение: /regen в боте или экспорт рабочего .conf с ПК и импорт на телефон.
- **Команда /broadcast:** добавлена в бота (только владелец). Рассылает всем пользователям уведомление о проблеме VPN и рекомендацию выполнить /regen, заменить старый конфиг новым. Отчёт владельцу: количество доставленных и не доставленных сообщений.
- **Документация:** обновлён `docs/client-instructions-amneziawg.md` (раздел «Если перестало работать»); создан `docs/troubleshooting-amneziawg-connection-timeout.md` (симптомы, решение, почему /regen помогает, почему ПК не пострадал).
- **Деплой:** коммит и push в nikkronos/vpnservice; на Timeweb git stash → git pull → restart vpn-bot.service. Рассылка выполнена (11 доставлено, 1 не доставлено).

## 2026-02-26 — Автоматизация выдачи конфигов AmneziaWG + удаление /proxy

- **Задача 1:** настроить автоматическую выдачу рабочих конфигов VPN через Telegram-бота для сервера eu1 (Европа).
- **Задача 2:** удалить неработающие функции (команда `/proxy`, отображение Shadowsocks и MTProto на веб-панели).

- **Диагностика eu1:**
  - AmneziaWG работает в Docker-контейнере `amnezia-awg2`
  - Порт: 39580/UDP (не 51820)
  - Подсеть: 10.8.1.0/24 (не 10.1.0.0/24)
  - Публичный ключ сервера: `pevLcgguoIMDWnbtPgQ3ZsSak73fylprex54Tv65ZyI=`

- **Создан бэкап:** `/root/amnezia-backup-20260226/` на eu1 (конфиг сервера, ключи, clientsTable)

- **Написаны скрипты:**
  - `/opt/amnezia-add-client.sh` — добавление клиента в Docker-контейнер
  - `/opt/amnezia-remove-client.sh` — удаление клиента

- **Настроен SSH:** ключ `/root/.ssh/id_ed25519_eu1` на Timeweb добавлен в authorized_keys на eu1

- **Обновлены переменные бота** (`env_vars.txt` на Timeweb):
  - `WG_EU1_ENDPOINT_PORT=39580`
  - `WG_EU1_NETWORK_CIDR=10.8.1.0/24`
  - `AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT=/opt/amnezia-add-client.sh`
  - `AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT=/opt/amnezia-remove-client.sh`
  - `AMNEZIAWG_EU1_NETWORK_CIDR=10.8.1.0/24`

- **Очищены старые peers:** удалены все eu1 peers из `peers.json` (имели IP из старой подсети 10.1.0.0/24)

- **Результат (автоматизация):** бот автоматически выдаёт рабочие конфиги AmneziaWG для Европы, проверено на телефоне

**Очистка от неработающих функций (сессия 2):**

- **Удалена команда /proxy из бота:**
  - Удалён хендлер `cmd_proxy` из `/opt/vpnservice/bot/main.py`
  - Убрана строка про `/proxy` из команды `/start`
  - Убрана строка про `/proxy` из команды `/help`

- **Удалены Shadowsocks и MTProto с веб-панели:**
  - Из `/opt/vpnservice/web/app.py` удалены блоки проверки Shadowsocks (порт 8388) и MTProto (порт 443)
  - Обновлена подсказка в блоке "Сервисы" в `/opt/vpnservice/web/templates/index.html`
  - Теперь в блоке "Сервисы" отображаются только: WireGuard (main), WireGuard (eu1), AmneziaWG (eu1)

- **Результат (очистка):** веб-панель показывает только работающие сервисы, бот не предлагает нерабочий MTProto-прокси

- **Обновлена документация:** SESSION_SUMMARY_2026-02-26.md, README_FOR_NEXT_AGENT.md, DONE_LIST_VPN.md

## 2026-02-23 — Восстановление eu1, эксперименты Remnawave/Xray/MTProto (неудачны)

- **Переустановка ОС на eu1:** Сервер eu1 (Fornex) полностью переустановлен (Ubuntu 24.04). Все сервисы были удалены.

- **Попытка Remnawave (неудачна):**
  - Развёрнут Remnawave (panel + node) на eu1 с доменами `panel.vpnnkrns.ru`, `sub.vpnnkrns.ru`, `node.vpnnkrns.ru`.
  - ACME выписал сертификаты успешно.
  - Контейнер `remnanode` падал с ошибкой `Invalid SECRET_KEY payload`.
  - Ручное добавление `SECRET_KEY` в `.env` проблему не решило.
  - **Решение:** Remnawave удалён, попытка признана неудачной.

- **Возврат AmneziaWG на eu1:**
  - Через приложение AmneziaVPN установлен AmneziaWG на eu1.
  - Конфиги созданы и раздаются **вручную** через «Поделиться VPN».
  - На ПК и iOS (телефон владельца и друзей) — **работает**.

- **Попытка MTProto-прокси (неудачна):**
  - Переустановлен MTProto-прокси на порт 443, затем 8443.
  - На обоих портах Telegram показывает «connecting», но не подключается.
  - **Вывод:** Мобильный оператор блокирует MTProto по сигнатуре протокола.
  - **Решение:** Telegram работает **через VPN (AmneziaWG)**.

- **Эксперимент Xray VLESS/TCP (неудачен):**
  - Установлен Xray (`xray-core`), настроен минимальный inbound VLESS/TCP без TLS (порт 21017).
  - Xray-служба работает, `curl` с сервера возвращает 200.
  - На ПК (v2rayN) профиль подключается, в логах видны подключения.
  - Однако: `ifconfig.me` показывает исходный IP, сайты не открываются.
  - **Вывод:** VLESS/TCP без TLS не работает (DPI распознаёт или проблемы маршрутизации на клиенте).
  - **Решение:** Эксперимент остановлен, не продолжать без TLS/Reality.

- **Обновление документации:**
  - Обновлён `SESSION_SUMMARY_2026-02-23.md` с полным описанием всех экспериментов.
  - Обновлён `README_FOR_NEXT_AGENT.md` — актуальное состояние, что работает/не работает.
  - Обновлён `DONE_LIST_VPN.md` (этот файл).
  - Обновлён `ROADMAP_VPN.md` — скорректированы задачи.

## 2026-02-22 — Чистый сброс eu1 (Fornex): AmneziaWG, проверка на ПК и iOS

- **Проблема:** на телефоне и у друзей — подключение к eu1 было, интернета не было; на ПК VPN работал через AmneziaWG.
- **План:** сброс только на eu1 (оставить MTProto и Shadowsocks), остановить и убрать конфиги AmneziaWG и wg0, проверить работу с нуля.
- **Документы:** созданы `docs/eu1-clean-slate-plan.md`, `docs/eu1-clean-slate-commands.md`; в README_FOR_NEXT_AGENT.md добавлен блок про план чистого сброса.
- **На eu1:** бэкап в `/root/eu1-backup-20260222`; остановлены и отключены awg-quick@awg0 и wg-quick@wg0; awg0.conf и копия /etc/amnezia перенесены в бэкап. Контейнеры Docker (amnezia-awg2, mtproto-proxy) не трогали.
- **Проверка:** сервер уже был в AmneziaVPN; экспорт для iOS через «Поделиться VPN»; на телефоне и на ПК подключение и интернет работают. Чистый сброс завершён успешно.

- **Бот — выдача конфигов AmneziaWG (Docker):** на eu1 развёрнуты скрипты amneziawg-add-client-docker.sh и amneziawg-remove-client-docker.sh; конфиг сервера в контейнере — /opt/amnezia/awg/awg0.conf; в скрипт добавлено извлечение обфускации (Jc, Jmin, Jmax, S1–S4, H1–H4) и подстановка в клиентский .conf. На Timeweb в env указаны пути к *-docker.sh; бот по /get_config и /regen выдаёт конфиги. На телефоне с конфигом от бота: handshake есть, трафик не грузится (открытый вопрос — см. SESSION_SUMMARY и docs/eu1-phone-config-open-question.md).

## 2026-02-21 — Веб-панель: деплой, этапы 2–3, подсказки

- **Деплой:** панель развёрнута на Timeweb на порту 5001 (чтобы не конфликтовать с Damir на 5000). Добавлены `web/vpn-web.service.example`, раздел в `docs/deployment.md`, переменная PORT=5001.
- **Этап 2:** блок «Сервисы» (API `/api/services` — WireGuard, AmneziaWG по пингу; Shadowsocks и MTProto по проверке TCP-портов); блок «Пользователи (сводка)» (без блока «По типам профилей»).
- **Этап 3:** учёт трафика — `wg show dump` локально для main, по SSH для eu1; API `/api/traffic`, блок «Трафик по пользователям» (по пользователям и по устройствам), обновление раз в 30 сек.
- **Подсказки:** под каждым блоком панели добавлены короткие пояснения (пользователь vs подключение, онлайн/офлайн по пингу, main/eu1, частота обновления трафика, подключение = конфиг, не устройство).

## 2026-02-21 — Бот: Европа = AmneziaWG (инструкция + опция выдачи конфига через скрипт)

- **Европа (eu1) в боте:** для сервера «Европа» бот больше не выдаёт WireGuard конфиги. Выдаётся инструкция по AmneziaWG (ПК + iOS через «Поделиться»). При настройке скрипта на eu1 (`AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT`) бот вызывает скрипт по SSH и выдаёт готовый AmneziaWG .conf.
- **Спецификация и скрипты:** созданы `docs/specs/spec-05-bot-amneziawg-eu1.md`, `docs/scripts/amneziawg-add-client.sh.example`, `docs/amneziawg-eu1-discovery.md` (проверка на eu1). В `env_vars.example.txt` добавлены переменные для AmneziaWG.
- **Тексты бота:** обновлены /start, /help, /instruction — Европа = AmneziaWG, импорт в AmneziaVPN/AmneziaWG. Добавлен короткий текст `docs/bot-instruction-texts/instruction_amneziawg_short.txt`. Регенерация (/regen) для Европы пока вручную — сообщение «напиши владельцу».
- **Код:** в `bot/wireguard_peers.py` добавлены `is_amneziawg_eu1_configured()`, `create_amneziawg_peer_and_config_for_user()`, `_remove_amneziawg_peer()`, `regenerate_amneziawg_peer_and_config_for_user()`; в `bot/main.py` — ветка для eu1 (AmneziaWG скрипт или инструкция), автоматическая регенерация (/regen) для Европы при настроенных скриптах.
- **Автоматизация выдачи и регенерации:** доработаны скрипты add-client и remove-client (`docs/scripts/`); бот поддерживает reuse_ip при создании peer и автоматический /regen для Европы (удаление старого peer на eu1, создание нового с тем же IP). Добавлен пошаговый гайд `docs/amneziawg-bot-automation-setup.md`. Переменные env: AMNEZIAWG_EU1_INTERFACE, AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT.

## 2026-02-21 — AmneziaWG на eu1 работает, iOS через «Поделиться», следующие задачи

- **VPN работает:** AmneziaWG на eu1 развёрнут, подключение из России (ПК + iPhone/iPad) работает. На iOS конфиг импортируется через «Поделиться» → AmneziaWG (выбор файла в пикере не срабатывал).
- **Инструкция для пользователей:** обновлена docs/client-instructions-amneziawg.md — импорт через «Поделиться» на iOS, какой файл использовать (.conf для AmneziaWG).
- **Решения владельца:** бэкап можно хранить в Git (репозиторий сделать приватным). Второй VPS отложен — без монетизации по бюджету не планируется. Бот — обновить инструкции (выдавать инструкцию по AmneziaWG, при возможности конфиг). Веб-панель — развернуть, получить ссылку, доработать под полный мониторинг (сейчас ссылки нет).
- **ROADMAP и README:** обновлены: задачи по боту (выдача инструкции/конфига AmneziaWG), веб-панель (деплой + ссылка + доработка мониторинга), второй VPS отложен. В docs/backup-restore.md добавлено про бэкап в Git при приватном репо.

## 2026-02-21 — Стратегия обхода блокировок РКН, выбор AmneziaWG, план развёртывания

- **Документ по стратегии обхода блокировок:**
  - Создан `docs/blocking-bypass-strategy.md` — контекст (что работает/блокируется в РФ 2026), варианты A/B/C/D (в т.ч. Shadowsocks + V2BOX), совет по провайдерам и доменам.
  - **Выбран вариант A (AmneziaWG):** один клиент AmneziaVPN на ПК и iOS/iPadOS; понятно пользователю; при блокировке РКН — добавить Xray в том же приложении.

- **РКН: начеку и легко перестраиваться:**
  - В ROADMAP_VPN.md добавлен раздел «РКН: быть начеку и легко перестраиваться» — документировать шаги, один клиент для пользователя, резерв Xray в Amnezia, при необходимости смена домена/провайдера.

- **Пошаговый план и инструкция развёртывания:**
  - Обновлён `docs/step-by-step-plan-bypass.md` — зафиксирован выбор A, упрощены шаги под AmneziaWG.
  - Создан `docs/amneziawg-deploy-instruction.md` — пошаговая инструкция: установка AmneziaVPN на ПК → добавление сервера eu1 по SSH → установка AmneziaWG через приложение → создание подключения → iOS/iPad по тому же приложению; раздел «Если РКН начнёт блокировать».

- **Обновление ROADMAP_VPN.md:**
  - Блок «Обход блокировок РКН»: выбор A отмечен как выполненный, следующие шаги — развернуть по инструкции, тест из России, при необходимости бот.
  - Раздел «Проблема eu1» сокращён до ссылок на AmneziaWG и резерв Xray.

- **SESSION_SUMMARY:**
  - Создан `SESSION_SUMMARY_2026-02-21.md` с контекстом сессии и замечаниями для следующего агента.

## 2026-02-20 — Улучшение UX и решение проблем тестирования

- **Улучшение UX в боте:**
  - Улучшены объяснения режимов "обычный VPN" и "VPN+GPT" в боте с понятными описаниями и эмодзи
  - Добавлена команда `/help` с подробной справкой о режимах VPN и типах профилей
  - Улучшены сообщения при выборе сервера и типа профиля
  - Добавлены визуальные индикаторы для лучшего понимания

- **Документация по диагностике проблем:**
  - Создан документ `docs/troubleshooting-multiple-devices.md` — диагностика проблемы с несколькими устройствами (плохо работает интернет при подключении с двух устройств)
  - Создан документ `docs/troubleshooting-ios-devices.md` — решение проблем VPN на iPhone без SIM и iPad
  - Создан документ `docs/troubleshooting-telegram-vpn-conflict.md` — решение конфликта VPN и Telegram proxy на iPhone
  - Создан скрипт `docs/scripts/monitor-server.sh.example` — мониторинг состояния VPN-сервера

- **Спецификация единого профиля:**
  - Создана спецификация `docs/specs/spec-04-unified-profile-all-services.md` с вариантами решения единого профиля для всех сервисов (YouTube + GPT + Telegram + сайты)
  - Исследованы 4 варианта решения, рекомендован гибридный вариант (WireGuard + Smart DNS + Shadowsocks)
  - Описана детальная реализация с чеклистом и рисками

- **Веб-панель мониторинга:**
  - Создана базовая структура веб-панели в `web/`
  - Реализовано Flask-приложение с API endpoints для мониторинга серверов, пользователей и статистики
  - Созданы HTML шаблоны, CSS стили и JavaScript для автообновления
  - Добавлена документация по установке и деплою

- **Изучение альтернатив:**
  - Создан документ `docs/vless-alternative.md` — изучение VLESS как альтернативы WireGuard
  - Сравнение VLESS с WireGuard по различным параметрам
  - Рекомендации по использованию VLESS в проекте

- **Обновление Roadmap:**
  - Обновлён `ROADMAP_VPN.md` с учётом всех выполненных задач
  - Отмечены выполненные задачи с датами
  - Добавлены новые разделы и обновлены существующие

## 2026-02-18 — Настройка WireGuard + Shadowsocks и клиентов

- **Сервер Fornex (Ubuntu 24.04)**
  - Установлен `shadowsocks-libev` и настроен клиентский конфиг `/etc/shadowsocks-libev/ss-wg.json` для подключения к Shadowsocks‑серверу `185.21.8.91:8388` (метод `aes-256-gcm`).
  - Запущен `ss-redir` как systemd‑сервис `ss-wg.service` (автозапуск, прослушивает `127.0.0.1:1081`).
  - В WireGuard‑конфиг `/etc/wireguard/wg0.conf` добавлены новые `Peer`:
    - Владелец iPhone: `10.1.0.4/32`.
    - Друг PC: `10.1.0.5/32`.
    - Друг iPhone: `10.1.0.6/32`.
    - Друг iPad: `10.1.0.7/32`.
  - Настроены iptables‑правила:
    - редирект всего TCP‑трафика на порты 80/443 от выбранных IP (`10.1.0.4/32`, `10.1.0.5/32`, `10.1.0.6/32`, `10.1.0.7/32`) на `127.0.0.1:1081` (Shadowsocks‑клиент);
    - разрешён форвардинг трафика интерфейса `wg0`.
  - Создана резервная копия основных конфигов:
    - `/etc/wireguard/wg0.conf`;
    - `/etc/wireguard/iphone.conf`;
    - `/etc/shadowsocks-libev/ss-wg.json`;
    - бэкапы сохранены в `/root/vpn-backups/2026-02-18/`.

- **Клиенты владельца**
  - **ПК (Windows)**:
    - Папка клиента Shadowsocks упорядочена (перенесена в отдельную директорию, например, `VPN.Shadowsocks`), проверено, что `Shadowsocks.exe` и `gui-config.json` работают корректно.
    - Текущий рабочий профиль WireGuard `client1` (от бота второго аккаунта) продолжает использоваться для обычного VPN.
  - **iPhone**:
    - Создан и импортирован новый профиль WireGuard `iphone`:
      - `Address = 10.1.0.4/32`, `DNS = 8.8.8.8`;
      - `Endpoint = <публичный IP Fornex>:51820`;
      - `AllowedIPs = 0.0.0.0/0`, `PersistentKeepalive = 25`.
    - Проверено, что при подключении профиля `iphone`:
      - ChatGPT работает;
      - обычные сайты идут через тот же сервер (с учётом ограничений/блокировок по IP Shadowsocks).

- **Клиенты друга** (по проектному допущению — успешно подключены)
  - **ПК (Friend PC)**:
    - Сгенерированы ключи и создан профиль WireGuard `friend-pc.conf`:
      - `Address = 10.1.0.5/32`, `DNS = 8.8.8.8`;
      - `Endpoint = <публичный IP Fornex>:51820`;
      - `AllowedIPs = 0.0.0.0/0`, `PersistentKeepalive = 25`.
  - **iPhone (Friend iPhone)**:
    - Профиль `friend-iphone.conf`:
      - `Address = 10.1.0.6/32`, остальные параметры аналогичны.
  - **iPad (Friend iPad)**:
    - Профиль `friend-ipad.conf`:
      - `Address = 10.1.0.7/32`, остальные параметры аналогичны.

- **Документация**
  - Создан файл `README_FOR_NEXT_AGENT.md` с описанием:
    - текущей архитектуры (WireGuard + Shadowsocks);
    - профилей владельца и друга;
    - расположения бэкапов конфигов;
    - ключевых правил безопасности и ограничений.
  - Создан `ROADMAP_VPN.md`:
    - зафиксировано текущее состояние (MVP 0.1);
    - намечены ближайшие и среднесрочные шаги (спеки, Telegram‑proxy, второй сервер, автоматизация через бота).

## 2026-02-18 — Установка Telegram MTProto Proxy

- **Сервер Fornex (Ubuntu 24.04)**
  - Установлен Docker (версия 29.2.1) для запуска контейнеров.
  - Развёрнут MTProto‑прокси через Docker‑контейнер `telegrammessenger/proxy:latest`:
    - контейнер: `mtproto-proxy` (автозапуск через `--restart=always`);
    - порт: `443/TCP` (маппинг `0.0.0.0:443->443/tcp`);
    - секрет: `29d11c61ea1b644d75299dd0706c2da3` (сгенерирован автоматически при запуске);
    - внешний IP: `185.21.8.91` (тот же, что у WireGuard‑сервера).
  - Сформирована ссылка подключения:
    - `tg://proxy?server=185.21.8.91&port=443&secret=29d11c61ea1b644d75299dd0706c2da3`;
    - альтернативная ссылка: `https://t.me/proxy?server=185.21.8.91&port=443&secret=29d11c61ea1b644d75299dd0706c2da3`;
    - ссылка сохранена в `/root/vpn-backups/2026-02-18/mtproto-link.txt`.
  - Проверена работа прокси:
    - контейнер запущен и работает стабильно;
    - пинг через прокси: ~45 мс (приемлемо для Telegram);
    - прокси работает независимо от WireGuard и Shadowsocks.

- **Клиенты**
  - **Владелец**: протестирован MTProto‑прокси на iPhone, подключение успешно, Telegram работает через прокси.
  - **Друг**: предоставлена ссылка подключения, прокси успешно настроен и работает на его устройствах.

- **Документация**
  - Создана спецификация `docs/specs/spec-02-telegram-mtproto-proxy.md`:
    - архитектура MTProto‑прокси;
    - требования и этапы реализации;
    - риски и митигация;
    - чеклист проверки.
  - Создана инструкция по установке `docs/mtproto-setup.md`:
    - пошаговая установка Docker (если не установлен);
    - запуск контейнера MTProto‑прокси;
    - получение секрета и формирование ссылки подключения;
    - настройка systemd (опционально);
    - тестирование на клиентах;
    - управление и устранение проблем.
  - Обновлены основные документы проекта:
    - `README_FOR_NEXT_AGENT.md`: добавлена информация о MTProto‑прокси в разделы "Серверы" и "Как этим пользоваться";
    - `ROADMAP_VPN.md`: отмечена выполненная задача по установке MTProto‑прокси.

## 2026-02-18 — Интеграция бота: инструкции, MTProto-ссылка, VPN+GPT

- **Команды бота**
  - Добавлена команда `/instruction` — пошаговая инструкция по подключению (ПК и iPhone/iPad); тексты загружаются из `docs/bot-instruction-texts/instruction_pc_short.txt` и `instruction_ios_short.txt`.
  - Добавлена команда `/proxy` — отправка ссылки MTProto‑прокси и краткой инструкции из `instruction_mtproto_short.txt`; ссылка читается из переменной окружения `MTPROTO_PROXY_LINK` (на Timeweb добавлена в `env_vars.txt`).
  - После успешной выдачи конфига по `/get_config` бот автоматически отправляет объединённую инструкцию (ПК + iOS).
  - В приветствии `/start` добавлены строки про `/instruction` и `/proxy`.

- **Конфигурация бота**
  - В `bot/config.py`: добавлены поля `base_dir`, `mtproto_proxy_link`; загрузка `MTPROTO_PROXY_LINK` из env (опционально).
  - В `docs/deployment.md`: раздел «Обновление бота на Timeweb» — напоминание, что `env_vars.txt` на сервере не в Git и новые переменные нужно добавлять вручную; команды для `git pull`, перезапуска сервиса и просмотра логов.

- **Опция VPN+GPT для Европы (eu1)**
  - При выборе сервера «Европа» в `/server` добавлен второй шаг: выбор типа профиля — «Обычный VPN» или «VPN+GPT (обход блокировок ChatGPT)».
  - Для VPN+GPT: выделение IP из пула **10.1.0.8–10.1.0.254**; после добавления peer в WireGuard бот по SSH на eu1 вызывает скрипт `add-ss-redirect.sh <IP>`, добавляющий iptables‑редирект TCP 80/443 на порт 1081 (ss-redir).
  - Имя конфига для VPN+GPT: `vpn_<id>_eu1_gpt.conf`; в сообщении бота явно указан тип «VPN+GPT».
  - В `bot/storage.py`: у `User` — поле `preferred_profile_type` (vpn / vpn_gpt); у `Peer` — поле `profile_type`; при регенерации конфига тип профиля сохраняется.
  - В `bot/wireguard_peers.py`: функции `_allocate_ip_in_pool()`, `_run_add_ss_redirect()`; в `create_peer_and_config_for_user()` добавлен параметр `profile_type`; опциональная переменная env `WG_EU1_ADD_SS_REDIRECT_SCRIPT` (по умолчанию `/opt/vpnservice/scripts/add-ss-redirect.sh`).

- **Скрипт add-ss-redirect.sh на eu1**
  - Пример скрипта: `docs/scripts/add-ss-redirect.sh.example`; развёртывание и путь описаны в `docs/deployment.md`.
  - На сервере eu1 (Fornex) скрипт развёрнут в `/opt/vpnservice/scripts/add-ss-redirect.sh`, выполнен `chmod +x`, проверен вызов с аргументом `10.1.0.8` и наличие правил в iptables.
  - На Timeweb в `env_vars.txt` добавлена переменная `WG_EU1_ADD_SS_REDIRECT_SCRIPT=/opt/vpnservice/scripts/add-ss-redirect.sh` (опционально, путь по умолчанию совпадает).

- **Документация и планы**
  - Спека `docs/specs/spec-03-bot-integration-instructions.md`: отмечены выполненные пункты (инструкции, MTProto, VPN+GPT, скрипт).
  - `ROADMAP_VPN.md`: отмечены выполненные задачи (выдача инструкции, команда /proxy, опция VPN+GPT в боте); оставлена задача «На сервере eu1 развернуть add-ss-redirect.sh» как выполненная по факту (скрипт развёрнут).

# DONE_LIST_VPN

История выполненных задач по проекту VPN.

## 2026-02-09

- Создана базовая структура документации для проекта VPN:
  - добавлен `ROADMAP_VPN.md` с этапами развития (MVP, бот, масштабирование, коммерциализация);
  - подготовлен шаблон для `SESSION_SUMMARY_2026-02-09.md` (см. файл сессии);
  - проект VPN интегрирован в центральные документы (`RULES.md`, `PROJECTS.md`, `ROAD_MAP_AI.md`, `QUICK_START_AGENT.md`, `docs/AGENT_PROMPTS.md`).
- Инициализирован отдельный Git-репозиторий для проекта VPN:
  - создан локальный репозиторий в папке `VPN/` (`git init`);
  - привязан к GitHub-репозиторию `nikkronos/vpnservice` (`git remote add origin`);
  - выполнен первый коммит с базовой структурой документации (`chore: initialize vpnservice repo structure`);
  - ветка переименована в `main` и отправлена на GitHub (`git push -u origin main`).
- Определена стратегия развёртывания:
  - первая нода будет развёрнута на существующем Timeweb-сервере (для тестирования и экономии средств);
  - в дальнейшем — миграция на отдельный VPS под VPN.
- Создана детальная инструкция по развёртыванию:
  - `VPN/docs/deployment.md` — пошаговое руководство по установке и настройке WireGuard на сервере;
  - включает генерацию ключей, конфигурацию сервера и клиентов, тестирование подключения.
- Развёрнута первая WireGuard-нода на существующем Timeweb-сервере (81.200.146.32):
  - установлен WireGuard, сгенерированы ключи сервера и клиента;
  - настроен интерфейс wg0, IP forwarding, UFW (порт 51820/UDP), systemd автозапуск;
  - создан конфиг клиента client1.conf, скопирован на Windows через scp.
- Успешное тестирование на Windows:
  - туннель «client1» подключён, внешний IP — 81.200.146.32;
  - ping 8.8.8.8: 0% потерь, ~10–15 мс;
  - Speedtest: ~91 Мбит/с вниз, ~88 Мбит/с вверх, пинг 10 мс.
- Успешное тестирование на iOS:
  - установлен qrencode на сервере, сгенерирован QR-код из client1.conf;
  - конфиг добавлен в WireGuard на iPhone через сканирование QR-кода;
  - подключение работает.

## 2026-02-11

- Реализован self-service через Telegram-бота:
  - спроектирована модель данных для пользователей (`users.json`) и VPN-подключений (`peers.json`);
  - добавлен модуль `bot/storage.py` с dataclass `Peer` и функциями для работы с peers;
  - добавлен модуль `bot/wireguard_peers.py` для интеграции с WireGuard (генерация ключей, подбор IP, добавление peer через `wg set`, формирование `.conf`);
  - переработан `bot/main.py` под сценарий self-service (команды `/start`, `/get_config`, `/my_config`, `/add_user`, `/users` с учётом новой модели данных).
- Настроены переменные окружения для VPN-проекта:
  - в `env_vars.txt` добавлены параметры `WG_SERVER_PUBLIC_KEY`, `WG_INTERFACE`, `WG_NETWORK_CIDR`, `WG_ENDPOINT_HOST`, `WG_ENDPOINT_PORT`, `WG_DNS`;
  - `WG_SERVER_PUBLIC_KEY` получен с помощью `wg show wg0 public-key` на сервере.
- Настроено обновление кода на сервере `/opt/vpnservice`:
  - сконфигурирован доступ к GitHub через Personal Access Token для `nikkronos/vpnservice`;
  - аккуратно разрешён конфликт между старым локальным `bot/storage.py` и новой версией из репозитория (старый файл сохранён как бэкап);
  - выполнен `git pull`, подтянуты новые файлы (`bot/main.py`, `bot/storage.py`, `bot/wireguard_peers.py`, `bot/__init__.py`, specs), перезапущен `vpn-bot.service`.
- Протестирован self-service для друзей:
  - владелец добавляет друга командой `/add_user` (ответом на сообщение или по Telegram ID);
  - друг пишет боту `/start` и `/get_config`, бот создаёт peer в WireGuard, сохраняет его в `peers.json` и отправляет конфигурационный файл `vpn_<telegram_id>.conf`;
  - как минимум один друг успешно подключился к VPN: YouTube и Instagram работают через туннель.
- Обновлены планы по развитию infrastructure и multi-node в `ROADMAP_VPN.md` (добавлены задачи по оценке нагрузки и внедрению нескольких нод/регионов).

## 2026-02-13

- Уточнены лимиты трафика у провайдера Timeweb:
  - подтверждено, что базовых ограничений по объёму трафика нет;
  - основное требование — не нарушать правила платформы (отсутствие незаконного контента, DDoS, спама и т.п.);
  - сделан вывод, что текущий VPS подходит для использования VPN друзьями и коллегами без жёстких лимитов по трафику.
- Доведена до рабочего состояния команда `/regen` (регенерация ключей и конфига WireGuard):
  - реализованы функции `_remove_peer_from_wireguard()` и `regenerate_peer_and_config_for_user()` в `bot/wireguard_peers.py`;
  - обновлён хендлер `/regen` в `bot/main.py`, который удаляет старый peer, создаёт новый с тем же IP и отправляет пользователю обновлённый `.conf`;
  - исправлена ошибка с отсутствующим импортом `find_peer_by_telegram_id`, из-за которой бот молчал при вызове `/regen`;
  - протестировано на боевом пользователе: новый конфиг успешно отработал, туннель продолжил работать.
- GitHub‑репозиторий `nikkronos/vpnservice` временно сделан публичным для упрощения деплоя (без постоянного ввода PAT); зафиксирована необходимость после завершения работ вернуть репозиторий в приватный режим и убедиться в отсутствии секретов в истории коммитов.

## 2026-02-14

- Добавлена вторая VPN-нода **eu1 (Европа)** на Fornex (Германия):
  - заказан VPS Cloud NVMe 1 (1 ядро, 1 ГБ RAM, 10 ГБ NVMe, безлимитный трафик) в локации Германия;
  - на сервере 185.21.8.91 установлен WireGuard (Ubuntu 24.04 LTS), настроен интерфейс wg0 в подсети 10.1.0.0/24, порт 51820/UDP, IP forwarding, UFW;
  - сгенерированы ключи сервера eu1, публичный ключ добавлен в конфигурацию бота.
- Настроен доступ бота (Timeweb) к ноде eu1 по SSH:
  - на Timeweb создан отдельный SSH-ключ для доступа к eu1;
  - публичный ключ добавлен в `authorized_keys` на Fornex (eu1);
  - в `env_vars.txt` на Timeweb добавлены переменные WG_EU1_* (SERVER_PUBLIC_KEY, INTERFACE, NETWORK_CIDR, ENDPOINT_HOST/PORT, DNS, SSH_HOST/USER/KEY_PATH).
- Логика бота обновлена ранее: `get_available_servers()` возвращает eu1 только при наличии WG_EU1_SERVER_PUBLIC_KEY и WG_EU1_ENDPOINT_HOST; переменные для нод используют формат `WG_<SERVERID>_*` (см. env_vars.example.txt).
- Успешная проверка в боте:
  - в `/server` отображаются две опции: «Россия (Timeweb)» и «Европа»;
  - пользователь выбрал «Европа», вызвал `/get_config` — бот создал peer на eu1 по SSH и отправил конфиг;
  - импорт конфига в WireGuard и подключение к ноде Европа работают; доступ к ChatGPT и другим EU-сервисам через eu1 обеспечен.
- Исправлена путаница с конфигами при переключении серверов:
  - имена файлов конфигов изменены с `vpn_<telegram_id>.conf` на `vpn_<telegram_id>_<server_id>.conf` (например, `vpn_123_main.conf` и `vpn_123_eu1.conf`);
  - в `bot/main.py` обновлены вызовы для `/get_config` и `/regen`, чтобы пользователи не перезаписывали и не путали конфиги для РФ и Европы.

## 2026-02-15

- Продолжена отладка ноды eu1 (Fornex): проблема «Получено 0, отправлено ок» не решена с прошлым агентом.
- Расширена документация по отладке eu1:
  - добавлены разделы 9–13 в `VPN/docs/eu1-setup-and-troubleshooting.md` (рекомендуемые проверки, обратный путь, финальные тесты, варианты обхода).
  - создан `VPN/docs/eu1-commands-step-by-step.md` — пошаговые команды для диагностики.
  - создан `VPN/docs/eu1-workarounds-fornex.md` — инструкции по обходным путям (ShadowSocks, Cloudflared, udp2raw, V2Ray).
- Добавлена опциональная поддержка MTU в клиентском конфиге:
  - в `bot/wireguard_peers.py` добавлен параметр `mtu` в конфиг ноды и в `_build_client_config()`.
  - если задан `WG_EU1_MTU` (например, 1280), в выдаваемый конфиг добавляется строка `MTU = 1280` в `[Interface]`.
  - обновлён `env_vars.example.txt` с примером `WG_EU1_MTU=1280`.
- Диагностика на Fornex:
  - исправлен пир с `AllowedIPs 10.1.0.0/24` → `10.1.0.2/32`.
  - добавлены правила iptables FORWARD в начало цепочки (wg0↔eth0, eth0→wg0 RELATED,ESTABLISHED).
  - rp_filter установлен в 0 для all и wg0.
  - выполнен tcpdump на eth0 (UDP 51820, 45 секунд) — пакетов от клиента к серверу не видно, но `wg show` показывает активный обмен (14.25 KiB received, 33.17 KiB sent).
- Вывод по eu1:
  - WireGuard UDP (порт 51820) на Fornex технически не работает для клиентов из России (блокировка/потеря трафика на маршруте Россия ↔ Fornex).
  - Сервер настроен корректно (все проверки пройдены), проблема вне зоны контроля.
  - Подготовлены варианты обходных путей для Fornex (ShadowSocks, Cloudflared, udp2raw, V2Ray) — см. `eu1-workarounds-fornex.md`.
- Обновлён `ROADMAP_VPN.md`: добавлена задача про проблему eu1 и варианты решения (обходные пути или миграция на другой провайдер).
- Fornex подтвердил: «С нашей стороны, ограничений нет.» — исходящий UDP с VPS до абонентских IP со стороны Fornex не блокируется.

