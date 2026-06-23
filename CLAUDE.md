# CLAUDE.md — VPN Service

Репозиторий: `nikkronos/vpnservice` | Путь: `Projects/In progress/VPN/` (переехал из `Projects/VPN/` 2026-06-09)

**Бренд (с 2026-05-25):** Kronos / VPN Kronos. Бот `@vpnkronos_bot` (display `vpnkronos`). Домен `supportkronos.online` (нейтральный, маскировка под support-портал). Канал `@vforfriends` legacy. **Тарифы (с 2026-06-11):** 3 устр. — 199 ₽/мес или 449 ₽/3мес; 5 устр. — 249 ₽/мес или 599 ₽/3мес (Stars 150/200/350/450 ⭐). Единый источник — `bot/tariffs.py`; cap устройств по тарифу через `users.device_limit` (3/5; грандфазер существующих + триал = 5). 2-шаговый выбор (устройства→срок) в боте и ЛК. **Триал 7 дней / 20 ГБ** (с 06-20: блок при исчерпании дней ИЛИ 20 ГБ — `enforce_expired.py --data-cap` cron `*/10`; baseline-грандфазер старых триалов через `users.trial_data_baseline`; предупреждение на ~80%). **Бывший 49 ₽-тест убран из выдачи** (06-20): объединён с триалом; `TARIFFS(3,0)` + payment-хендлеры оставлены для decode 2 существующих (`test_used`). Кнопки бота цветные (Bot API 9.4 `style`, telebot ≥4.34).

---

## Старт сессии

```bash
git status
git log --oneline -3
```

Читай в таком порядке:
1. Этот файл — полная текущая картина
2. `ROADMAP_VPN.md` — открытые задачи
3. Последний `docs/sessions/SESSION_SUMMARY_*.md` — что делали в прошлый раз

---

## Обслуживание серверов / диск (важно для агента)

**Что НЕ трогать на серверах** (личные проекты владельца, не имеют отношения к VPN-сервису):

| Сервер | Путь | Что это |
|--------|------|---------|
| **main** (Timeweb) | `/root/transcribator/` (с `.venv`) | Личный проект владельца — транскрибация |
| **main** | `/root/.cache/huggingface/` | HuggingFace модели для transcribator |
| **Fornex** | `/home/hamster26/` | Личные проекты владельца (`bot/`, `userbot/`) |

**Что можно чистить безопасно** (если диск > 80%):
- `journalctl --vacuum-size=300M` — лимит уже стоит 500M (`/etc/systemd/journald.conf` `SystemMaxUse=500M`), но vacuum можно делать вручную.
- **Xray access-лог (с 06-17)** пишется в `/var/log/xray/access.log` (НЕ journald; `log.access` + `loglevel: warning` на eu1/main/yc/yc2) + `logrotate /etc/logrotate.d/xray` (copytruncate, rotate 3). Поэтому journald больше не пухнет от Xray (~1М строк/день убрали). `ip_usage_watcher` читает этот файл.
- `apt clean` — кеш .deb пакетов.
- `docker system prune -af --volumes` — **ТОЛЬКО** после `docker ps` для проверки, что активные контейнеры (`amnezia-awg2`, `mtproxy-faketls`) не попадут под удаление.
- `/opt/vpnservice/web/{templates,static}/*.bak.*` — мои deploy-бэкапы (есть в git).
- `/root/awg-orphans-*.log` — бэкапы перед удалением peers (мелкие, обычно оставляю).

**Что ВСЕГДА НЕ трогать** на любом сервере:
- `/opt/amnezia/` — конфиги AWG, **PSK в `/opt/amnezia/awg/wireguard_psk.key`** (один общий для всех peers интерфейса; терять = терять все клиентские конфиги).
- `/opt/vpnservice/data/` — SQLite БД, peers.json.
- `/opt/vpnservice/env_vars.txt`, `/root/.secrets/` — секреты.
- AWG peer-ы в runtime — см. memory `feedback_no_delete_runtime_blind`. Признаки жизни (endpoint/traffic/handshake) важнее консистентности с БД.

**Health-check (cron `*/15`)** алертит при `диск > 85%`. Когда придёт алерт — действовать по плану выше.

---

## Инфраструктура (июнь 2026)

| Сервер | IP | Что на нём |
|--------|-----|-----------|
| **Fornex eu1** (основной) | `185.21.8.91` | Бот, веб-панель, AmneziaWG Docker, MTProxy Fake TLS, Xray VLESS+WS+XHTTP+REALITY (443) |
| **Timeweb main** (RU + Мегафон/Yota) | `81.200.146.32` | **Xray VLESS+REALITY на 443** (SNI=cloud.mail.ru, для Мегафон/Yota при БС, см. SESSION_SUMMARY_2026-05-21). Также WireGuard wg0 на UDP/51820 для 1 legacy user. SSH: `ssh -i ~/.ssh/id_ed25519_main root@81.200.146.32` (или через Fornex jump) |
| **Yandex Cloud vrprnt** (yc, T2/МТС/Билайн) | `158.160.236.147` | Xray VLESS+REALITY xHTTP (порт 443, SNI: www.microsoft.com) |
| **Yandex Cloud yc2** (РФ-резерв, с 2026-06-09) | `84.252.136.139` (static) | Клон yc: Xray VLESS+REALITY xHTTP (443, SNI: www.microsoft.com), те же per-user UUID (`vless_uuid_yc`). Резерв + разгрузка yc. В подписке, в `sync_xray_users --all` и health-check (с 2026-06-10) |

**SSH:**
- Fornex: `ssh fornex` (алиас) или `ssh -i ~/.ssh/id_ed25519_fornex root@185.21.8.91`
- Timeweb (main): через Fornex jump — `ssh fornex "ssh -i /root/.ssh/id_ed25519_main root@81.200.146.32 ..."`
- Yandex Cloud (yc): через Fornex jump — `ssh fornex "ssh yc ..."` (alias настроен в `/root/.ssh/config` на Fornex, ключ `/root/.ssh/id_ed25519_yc`, user `ubuntu` с passwordless sudo)
- Yandex Cloud (yc2, РФ-резерв): через Fornex jump — `ssh fornex "ssh yc2 ..."` (alias на Fornex, user `ubuntu` с passwordless sudo)

**Тариф eu1:** Cloud NVMe 2 — 2 ядра / 2 ГБ RAM / 20 ГБ NVMe, 936 ₽/мес. Канал **~100 Мбит/с** (порт VPS; диагностика 2026-05-24, ждём уточнение в тикете). + swap 2 ГБ (swappiness=10). Узкое место скорости — порт, не CPU/RAM.

### Сервисы на Fornex

| Сервис | Команда | Порт/адрес |
|--------|---------|-----------|
| Telegram-бот | `vpn-bot.service` | — |
| Веб-панель | `vpn-web.service` | `:5001` |
| AmneziaWG (Docker) | контейнер `amnezia-awg2` | `39580/UDP` |
| MTProxy Fake TLS | контейнер `mtproxy-faketls` | `8444/TCP` |
| Xray VLESS+WS | `xray.service` | `80/TCP` (CDN через `sub.vpnnkrns.ru`) |
| nginx (ЛК HTTPS) | `nginx.service` | `8443/TCP` ssl → :5001 для `supportkronos.online`; конфиг `/etc/nginx/conf.d/supportkronos.conf`. LE-cert via DNS-01 (CF token в `/root/.secrets/cloudflare.ini`, auto-renew). |

---

## Что работает / что нет

| Технология | Статус | Где |
|------------|--------|-----|
| WireGuard | ✅ Работает | main (Timeweb) — Россия |
| AmneziaWG | ✅ Работает | eu1 Docker `amnezia-awg2` — Европа |
| VLESS+WS+Cloudflare CDN | ✅ Обычные блокировки | `sub.vpnnkrns.ru:443` |
| VLESS+XHTTP+Yandex CDN | ⏳ Настроен, тест при БС — ждём | `cdn.vpnnkrns.ru:80` → Fornex |
| VLESS+REALITY xHTTP (yc) | ✅ T2/МТС/Билайн/Т-Мобайл (SNI=www.microsoft.com) | Yandex Cloud `158.160.236.147:443` |
| **VLESS+REALITY (main)** | ✅ **Мегафон/Yota при БС** (SNI=cloud.mail.ru, dest=cloud.mail.ru:443) | Timeweb `81.200.146.32:443` |
| MTProxy Fake TLS | ✅ Telegram | eu1 порт `8444` |
| WireGuard UDP к Fornex | ❌ Заблокирован РФ | — |
| Голый MTProto на eu1 | ❌ Блок по сигнатуре | — |
| Cloudflare на LTE whitelist | ❌ Даже CF IPs не в whitelist | — |

**Подписка `/sub` = 4 узла** (метки в Happ): 🇪🇺 Европа (yc) · 🇪🇺 Европа-2 (yc2) · 🇩🇪 Германия (eu1 direct) · 🇷🇺 Россия (main). yc/yc2 — **фронт-релеи в eu1** (правило #0), не прямые выходы.

**Покрытие (факт, тест владельца 06-13 на T2):** РКН режет по **IP-репутации, не транспорту** (память `project_vpn_rkn_ip_block`). На мобильных/фильтрующих сетях надёжны только Яндекс-узлы (Европа/Европа-2) + AmneziaWG; eu1 (Германия) и main (Россия) прямым входом могут не подниматься даже без БС. **Мегафон при БС — известный гэп** (ждём тест человека); **Yota** решено 05-21 (БС-ретест ждёт). Покрытие операторов НЕ считать «закрытым».

---

## Архитектура (код)

```
bot/
  main.py          — хендлеры Telegram-бота
  database.py      — SQLite: users, peers, servers
  wireguard_peers.py — создание/удаление WG и AWG конфигов
  vless_peers.py   — VLESS конфиги
  storage.py       — peers.json + нормализация server_id
  config.py        — BotConfig, чтение env_vars.txt
web/
  app.py           — Flask: /, /recovery, API эндпоинты
  templates/       — index.html, recovery.html
  static/          — main.js, recovery.js, style.css
bot/data/
  vpn.db           — SQLite (основная БД; таблица `peers` — источник правды для WG/AWG слотов с 2026-06-02)
  peers.json       — статический fallback-снимок (запись ОТКЛЮЧЕНА в Phase 3, storage.DUAL_WRITE_JSON=False; источник правды = таблица peers)
  mtproto_proxy_link.txt — текущая MTProxy ссылка (не в git)
scripts/
  traffic_accounting.py — cron-сэмплер lifetime-трафика (*/5)
  expiry_reminder.py    — ЕЖЕДНЕВНЫЕ напоминания об окончании доступа (0..7 дн до конца; подписка/триал/тест), cron 0 9 * * *, 12:00 МСК
  sheets_sync_cron.py   — auto-sync БД → Google Sheets (cron 0 */6 * * *)
  health_check.py       — 22 проверки инфры (Fornex local + main/yc через SSH) → TG-алерты владельцу (cron */15)
  vless_summary_accounting.py — per-server VLESS lifetime через Xray stats API (cron */5)
  patch_xray_stats.py   — идемпотентный патч Xray config: добавляет stats/api блоки + теги inbound'ов
  traffic_diagnosis.py  — кто качал в окне (read-only диагностика по traffic_snapshots): `python scripts/traffic_diagnosis.py --last 1h` или `python scripts/traffic_diagnosis.py 2026-05-30 17:00 2026-05-30 18:00` (UTC)
  enforce_expired.py    — soft-revoke AWG peers у юзеров с истёкшей подпиской (> 12 ч grace). Default dry-run, `--apply` для реального отзыва. Auto-restore при оплате через `restore_user_revoked_peers` (peer возвращается с теми же pubkey/ip — старый .conf работает). **`--data-cap` (06-20):** режим блока триала по лимиту 20 ГБ (`find_data_cap_candidates` + закрытие гейта + предупреждение на 80%; см. cron `*/10`).
  sync_xray_users.py    — синхронизация per-user VLESS UUIDs из БД в Xray config.json на main/yc через SSH + restart. `--server main|yc | --all`, `--dry-run`, `--no-shared`. Также idempotent гарантирует `policy.levels.0.statsUser*` для per-user телеметрии. Использует тот же SQL-фильтр что enforce_expired (grace 12h) → revoked юзер автоматически вылетает из Xray.
  vless_uuid_backfill.py — one-shot скрипт генерации per-user UUIDs всем active юзерам в БД (идемпотентен).
  peers_sync_check.py   — диагностика рассинхрона таблицы peers ↔ awg show ↔ БД (read-only, on-demand)
  migrate_peers_check.py — бэкап + сверка peers.json ↔ таблица peers (для cutover; read-only кроме --backup)
  test_peers_sqlite.py  — self-contained тест миграции + storage поверх SQLite (на временной БД)
  eu1_monitor.sh        — лёгкий мониторинг eu1 (cron */5): CSV метрик (load/RAM/swap/conntrack/awg-peers/rx-tx) в /var/log/eu1-monitor.log для расследования жалоб «скорость падает». Без speedtest, self-trim.
```

### Ключевые концепции

- **server_id:** `eu1` (AmneziaWG, Docker), логически был `eu2` — нормализован в `eu1` через `storage.py`
- **peer key (Фаза 2 B):** `{telegram_id}:{server_id}:{device_id}` (composite-PK `peers`). Раньше `platform` (per-OS) → перешли на **именованные устройства** (таблица `devices`: device_id/telegram_id/name/os). `os` (`pc`/`ios`/`android`) — только формат доставки. **Shim в `storage.py`:** принимает `platform=` (legacy), мапит на device; `Peer.platform` = алиас `Peer.os` → бот/ЛК/wireguard_peers без правок. UX «Мои устройства» (список/добавить/обновить/удалить/переименовать) в боте и ЛК; эндпоинты `/api/recovery/devices|device-add|device-regen|device-delete|device-rename`. Cap по тарифу — `db_get_device_limit` (3/5; грандфазер/триал=5), не хардкод. _(детали внедрения: DONE_LIST 06-10/06-11)_
- **Платформы/os:** `pc`, `ios`, `android` — Android получает `vpn://` deep link, iOS/PC — `.conf` файл
- **device-хелперы** (`bot/database.py`): `db_list_devices`/`db_get_device`/`db_add_device`/`db_rename_device`/`db_delete_device`/`db_count_devices`.
- **Admin auth:** `ADMIN_SECRET` (64-char hex) — для `/api/users`, `/api/traffic`
- **Recovery auth:** `RECOVERY_SECRET` — для legacy recovery endpoints
- **traffic_accounting (SQLite):** накопительный lifetime-трафик по pubkey, reset-aware (счётчики awg обнуляются при рестарте/перегенерации). Пишется из `/api/traffic` при просмотре + cron `*/5` `scripts/traffic_accounting.py`. Столбец «Всего» в панели.
- **Модель аккаунта (биллинг, Фаза 0):** `users` поля `subscription_status`/`expires_at`/`trial_used`/`plan`/`referral_code`/`referred_by`/`password_hash`/`sub_token` + таблица `payments`. Хелперы (`db_is_access_active`, `db_start_trial`, `db_extend_subscription`, `db_ensure_referral_code`, `db_set_password`, `db_ensure_sub_token`, …). **expires_at NULL = grandfathered** (реальных нет). **Enforcement ВКЛ** (`ENFORCEMENT_ENABLED=1` + `enforce_expired.py` hourly + per-user VLESS revoke). **Триал 7 дней** (`tariffs.TRIAL_DAYS`); `REFERRAL_REWARD_DAYS=14` (не путать). Доп. поля `users`: `device_limit` (3/5; грандфазер=5), `use_case` (онбординг «для чего VPN» → Google Sheets), `test_used` (разовый тест 49₽/7д), `last_reminder_date` (anti-дубль напоминаний), `drop_reason`/`drop_reason_at`/`churn_asked_at` (churn-опрос → Sheets). **Рассылка сегментирована** (`db_users_by_segment`: all/active/inactive/inactive_no_onboarding/inactive_used/test → текст или опрос).
- **Subscription-URL (validated 2026-05-25):** `GET /sub/<sub_token>` → base64-список VLESS-REALITY ссылок (YC `www.microsoft.com` + main `cloud.mail.ru`). Happ импортирует как «subscription» — один URL, авто-выбор сервера, авто-обновление. **Happ — референс-клиент (стандартизировано 06-20);** V2Box и пр. не всегда тянут наш xhttp REALITY → в инструкциях только Happ (память `project_vpn_client_happ_reference`). Гейт `db_is_access_active` — истёк срок → пустая подписка → все устройства отваливаются (чистый enforcement для Фазы 4). Спайк: общие share-ссылки; per-user UUID — TODO. `ProxyFix(x_proto, x_host)` в app.py чтобы за nginx Flask отдавал https-ссылки.
- **Cloudflare в РФ заблокирован/throttled** (durable, 2026-05-25): DPI режет TLS к CF — у владельца Safari не открывает CF-fronted домен. **CF используем только как DNS (grey-cloud)**, не как прокси. HTTPS — прямой с нашего хоста (Fornex direct + LE cert).
- **Зависимость:** `qrcode[pil]` (QR в ЛК). В `requirements.txt`; на сервере уже в venv.

---

## Бот — текущий UX

**Меню /start** (авторизованный):
- `🌐 Открыть личный кабинет` (Mini App → recovery)
- `📲 Получить VPN` → **сразу отдаёт `🔗 Подключить VPN`** (subscription `/sub/<token>`, телефон+ПК — главный путь, как в ЛК «всё на первом экране») + кнопка `🔌 Другие способы` → подменю `💻 AmneziaWG` (макс. скорость ПК/Wi-Fi, ⚠️ не для мобильного) / `📡 Мобильный` (под оператора main/yc)
- `🔄 Не работает` → подменю:
  - `💻 Сбросить конфиг AmneziaWG` → подтверждение → платформа → реген
  - `📱 Телефон / «Подключить»` → переотдаёт ссылку-подписку + «удали старый профиль в HAPP, добавь заново»
- `💳 Продлить подписку`, `📊 Статус подписки`, `📖 Инструкции`, `📨 Proxy для Telegram`, `🆘 Поддержка`

**Терминология (синхронно бот/ЛК/MiniApp, с 2026-06-04):** ссылка-подключение = **«Подключить VPN»** (НЕ «Подписка» — это слово только про оплату). AmneziaWG = «макс. скорость ПК/Wi-Fi, не для мобильного». Изменено по фидбэку @veryvoro.

**Команды владельца:** `/proxy_rotate`, `/broadcast`

---

## Веб-панель

- **Мониторинг:** `https://supportkronos.online:8443/admin` (после `/login`: username `admin` / пароль `ADMIN_SECRET`) — тёмная тема, статус AWG/VLESS, таблица трафика по пользователям с устройством и handshake, счётчик «ждут подтверждения» (pending-оплаты, с 06-23). **Flask :5001 биндится на 127.0.0.1** — `http://185.21.8.91:5001/` работает только на самом сервере; снаружи всё через nginx :8443. Дашборд переехал с `/` на `/admin` (на `/` теперь публичный лендинг).
- **Recovery / ЛК:** **`https://supportkronos.online:8443/recovery`** (HTTPS direct с Fornex, LE cert, nginx :8443 → Flask :5001; домен grey-cloud в CF). Старый `http://185.21.8.91:5001/recovery` тоже жив как fallback (не закрыт). Вход email-OTP или пароль. Экран «Мой аккаунт»: статус/срок, **«Подписка» как главный CTA** (одна ссылка для всех устройств, импорт в Happ), триал, реферал, управление паролем. Альтернативно — конкретные конфиги (Основной VPN / VPN при блокировках / Разблокировка Telegram). QR (qrcode[pil]).

---

## Деплой

```bash
# Код → сервер (пример для bot/main.py)
scp -i ~/.ssh/id_ed25519_fornex bot/main.py root@185.21.8.91:/opt/vpnservice/bot/
ssh fornex "systemctl restart vpn-bot.service"

# Веб-панель
scp -i ~/.ssh/id_ed25519_fornex web/app.py root@185.21.8.91:/opt/vpnservice/web/
ssh fornex "systemctl restart vpn-web.service"

# Логи
ssh fornex "journalctl -u vpn-bot.service -f"
ssh fornex "journalctl -u vpn-web.service -f"

# AmneziaWG
ssh fornex "docker exec amnezia-awg2 awg show awg0"
ssh fornex "docker logs amnezia-awg2"
```

**Зависимости:**
```bash
ssh fornex "/opt/vpnservice/venv/bin/pip install -r /opt/vpnservice/requirements.txt"
```

---

## Переменные окружения

Файл `/opt/vpnservice/env_vars.txt` на Fornex (и локально `Projects/VPN/env_vars.txt`). Пример структуры: `env_vars.example.txt`.

Ключевые переменные:
```
BOT_TOKEN=...
ADMIN_TELEGRAM_ID=...
ADMIN_SECRET=...          # 64-char hex, для /api/users
RECOVERY_SECRET=...       # для recovery endpoints

# Russia (main, Timeweb)
WG_SERVER_PUBLIC_KEY=...
WG_ENDPOINT_HOST=81.200.146.32
WG_ENDPOINT_PORT=51820

# Europe (eu1, Fornex, AmneziaWG Docker)
WG_EU1_SERVER_PUBLIC_KEY=pevLcgguoIMDWnbtPgQ3ZsSak73fylprex54Tv65ZyI=
WG_EU1_ENDPOINT_HOST=185.21.8.91
WG_EU1_ENDPOINT_PORT=39580
WG_EU1_SSH_HOST=185.21.8.91
WG_EU1_SSH_KEY_PATH=/root/.ssh/id_ed25519_eu1

# VLESS+REALITY (Yandex Cloud, LTE fallback)
VLESS_REALITY_SHARE_URL=vless://...  # xHTTP+packet-up через YC

# MTProxy
MTPROTO_PROXY_LINK=tg://proxy?...
MTPROXY_PORT=8444
MTPROXY_ROTATE_SCRIPT=/opt/vpnservice/scripts/mtproxy-rotate.sh

# Google Sheets (sync юзеров: tid/email/expires_at/days_left/trial_used/migrated)
# Триггер: бот → ⚙️ Администратор → 📊 Sync Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON=/opt/vpnservice/google-sa.json
GOOGLE_SHEETS_ID=10HAqnr2-pIB6m4OXMqDOfHSbFVVutsOK9NkOPNpbbKQ

# Флаги переезда (выставлены =1 при swap токена 2026-05-27 ночью)
ONBOARDING_ENABLED=1     # FSM-онбординг при /start
ENFORCEMENT_ENABLED=1    # гейт «Получить VPN» по db_is_access_active
```

---

## Важные правила

0. **⛔ yc/yc2 («Европа») — ФРОНТ-РЕЛЕИ, не прямые выходы** (вскрыто 2026-06-10). Их Xray routing шлёт ВЕСЬ трафик в outbound `vless+ws → 185.21.8.91:80/vpn` = **eu1 vless-ws**. Вход через Яндекс-IP (переживает РКН), выход через eu1. Релей-credential `359e23cc-f90c-4e43-97af-bd1b662ff043` (общий yc/yc2) лежит в eu1 vless-ws. У него нет `tid_…@kronos` email → `access_audit` метит «SHARED», но это **несущая инфра, НЕ фрод**. **НЕ удалять shared на eu1** (`sync_eu1_vless.py --no-shared` гейтнут за `--force` + бережёт `RELAY_PRESERVE`) — снос перерубает выход Европы. Память: `project_vpn_yc_relay_topology`, `feedback_no_delete_runtime_blind`.
0.1. **🌐 supportkronos.online (ЛК + `/sub`) фронтится через Яндекс** (с 2026-06-10, БС-резильентность). DNS A → **yc + yc2** (158.160.236.147 + 84.252.136.139, TTL 60, grey-cloud), там `socat sub-forward.service` :8443 → passthrough на Fornex:8443 (TLS терминируется на Fornex, существующий LE-cert). Смысл: при БС немецкий IP eu1 недоступен → подписка не обновлялась; Яндекс-IP переживает → failover-ротация серверов теперь доходит до БС-юзеров. **eu1:8443 nginx остаётся бэкендом** (не выключать). yc потребовал `ufw allow 8443`. ⚠️ Полная БС-устойчивость (SNI-фильтрация) не доказана — валидировать при БС. health-check мониторит yc/yc2:8443.
1. **Timeweb (main)** — там теперь крутится Xray VLESS+REALITY для Мегафон/Yota (см. SESSION_SUMMARY_2026-05-21). Старый WG (wg0/UDP/51820) тоже остался для 1 legacy user. SSH-ключ к main: `id_ed25519_main` на Fornex.
2. **eu1 = Docker** — AmneziaWG в `amnezia-awg2`, команды через `docker exec`
3. **Подсеть eu1 = 10.8.1.0/24**, порт = 39580 (не 51820, не 10.1.0.0/24)
4. **MTProxy на eu1 — только Fake TLS** (порт 8444). Голый MTProto не использовать
5. **AmneziaWG persistent-сохранение peers:** `/opt/amnezia-add-client.sh` и `/opt/amnezia-remove-client.sh` после `awg set` вызывают `/opt/amnezia-save-conf.sh`. Cron `*/5 * * * * /opt/amnezia-save-conf.sh` — safety net. **НЕ возвращать `awg-quick save awg0`** — она fail-silent в этом контейнере.
6. **Не пушить сломанный код** — проверь diff перед commit
7. **env_vars.txt не коммитить никогда**
8. **После изменений:** `git add` → `git commit` → `git push` (push обязателен)
9. **Reboot любого сервера** — проверь после: `systemctl is-active <services>`, `docker ps`, наличие всех peers (особенно AmneziaWG на Fornex: `docker exec amnezia-awg2 awg show awg0 | grep -c '^peer'` должно совпадать с количеством active eu1-peer'ов в peers.json).
9.1. **Admin-вход на сайт `/admin/credit` и `/login`:** username = `admin` (literal), пароль = `ADMIN_SECRET` (64-char hex из env_vars.txt). НЕ email/пароль владельца.
9.2. **Flask :5001 биндится на 127.0.0.1** — снаружи закрыт. Доступ только через nginx :8443 с TLS. Для отладки локально можно переопределить `FLASK_HOST=0.0.0.0`.
10. **Cron на Fornex (root):**
    - `*/5 * * * *` `/opt/amnezia-save-conf.sh` — persist AWG peers (safety net).
    - `*/5 * * * *` `scripts/traffic_accounting.py` — lifetime AmneziaWG-трафика per peer/user. **Также пишет snapshots в `traffic_snapshots`** (timestamp + pubkey + rx/tx) — 14-дневная история для `scripts/traffic_diagnosis.py`.
    - `*/5 * * * *` `scripts/vless_summary_accounting.py` — VLESS-трафик: (1) per-inbound aggregate → `vless_server_traffic` (шапка админки), (2) per-user (только main/yc, парсинг `user>>>tid_X@kronos`) → `vless_user_traffic` (статус юзеров в админке). eu1 локально + main/yc через SSH. Reset-aware. После Этапа 7-9 (2026-06-03) даёт per-user точность.
    - `7 * * * *` `scripts/sync_xray_users.py --all --no-shared` — пересинхронизирует per-user VLESS UUIDs из БД в Xray config.json на main+yc+**yc2** (клон yc, та же колонка `vless_uuid_yc`). **Ежечасно с 2026-06-11** (было `7 */6`): чтобы VLESS-отзыв истёкших догонял ежечасный `enforce_expired` — раньше VLESS-доступ (главный путь!) жил до ~6 ч после grace = enforcement-лик + источник ложных `vless_config_consistency`-алертов на когортах истечений. **No-change guard (2026-06-11):** рестартит Xray ТОЛЬКО если clients/policy реально изменились, иначе skip → ежечасный прогон почти всегда no-op без downtime. Также защита от drift (ручные правки / неудачные sync). **Минута :07 (не :00) специально** — когда рестарт реально нужен, он не попадает на сетку health-check (`*/15` = :00/:15), иначе ловится 5-сек окно рестарта → ложный `main:443 down` (исправлено 2026-06-05).
    - `0 9 * * *` `scripts/expiry_reminder.py` — ЕЖЕДНЕВНЫЕ напоминания (с 2026-06-12): всем у кого доступ истекает в ближайшие 0..7 дней, по одному в день (`last_reminder_date` anti-дубль). Покрывает подписку/триал/тест. **+ авто-T+1 churn-опрос** (истёк вчера + неактивен + онбординг завершён + не спрошен → опрос причин, `bot/churn.py`; дедуп `churn_asked_at`). 12:00 МСК.
    - `0 */6 * * *` `scripts/sheets_sync_cron.py` — auto-sync Google Sheets (каждые 6 ч). Ручной триггер в боте «📊 Sync Google Sheets» остаётся как fallback.
    - `0 * * * *` `scripts/enforce_expired.py --apply` — отзыв AWG peer у юзеров с `expires_at < now - 12h`. Soft-revoke: peer удаляется из runtime, peer-credentials в peers.json сохраняются (`active=False`). При оплате — auto-restore через `restore_user_revoked_peers` hook в payment-handlers (Stars / claim_approve / admin_credit / web/admin/credit). Уведомление юзеру при отзыве, владельцу — сводка с тех революциях когда они есть.
    - `*/10 * * * *` `scripts/enforce_expired.py --apply --data-cap` — **блок триала по данным (с 2026-06-20):** триал-юзеры с `total − trial_data_baseline ≥ 20 ГБ` → тот же soft-revoke + закрытие гейта (`expires=now`, `status=data_capped`, иначе пере-запрос конфига обходит лимит) + уведомление. **Грандфазер:** старые триалы (`trial_data_baseline` NULL) не трогаются. + предупреждение на ~80% (`trial_data_warned`, anti-дубль). Мягкий кэп (≤10 мин). Учёт `db_get_user_total_bytes` (AWG `traffic_accounting` + VLESS `vless_user_traffic`). Платные (`plan≠trial`) под кэп НЕ попадают.
    - `*/15 * * * *` `scripts/health_check.py` — 32 проверки инфры (yc/yc2 +`:8443` socat sub-forward с 2026-06-10; +fail2ban на main/yc/yc2 с 2026-06-11). **Fornex (13, локально):** systemd сервисы (vpn-bot/vpn-web/nginx/xray), docker (amnezia-awg2/mtproxy-faketls), AWG peer-count, peers.json/awg consistency, диск, swap, LE-cert, HTTPS endpoint, vless_config_consistency. **main (7, через SSH):** reachable + xray + wg-quick@wg0 + fail2ban + :443/tcp + :51820/udp + диск. **yc (6, через SSH):** reachable + xray + fail2ban + :443/tcp + :8443/tcp + диск. **yc2 (6, через SSH, РФ-резерв):** reachable + xray + fail2ban + :443/tcp + :8443/tcp + диск. **Все remote-проверки одного хоста идут одним SSH-batch'ем** (с маркерами `<<<BEGIN:N>>>`/`<<<END:N:rc>>>`) — раньше отдельные ssh-коннекты иногда отбивались провайдером main с `Connection closed by ... port 22` на 5-6-м соединении (false-FAIL'ы 2026-05-31). При смене статуса OK↔FAIL шлёт TG-алерт владельцу (прямой HTTP API, не через инстанс бота). State: `/var/lib/vpn-health/state.json`. Remote-ключи префиксованы `<host>:` (`yc:xray.service`). FAIL `<host>:reachable` — gate: остальные проверки этого хоста скипаются, чтобы один сетевой провал не давал каскад. **Кросс-серверная проверка `vless_config_consistency`** (с 2026-06-03, yc2 с 2026-06-10): count(active vless_uuid_X в users) vs count(clients в Xray config на main/yc/yc2) — FAIL если diff > 2 (yc2 сверяется с db_yc — клон yc). На когортах истечений БД и config законно расходятся в окне grace→sync; перевод sync на ежечасный (2026-06-11) сузил это окно с ~6 ч до ~1 ч. Полное устранение кратких ложных FAIL — опц. debounce (алерт только если diff держится ≥2 циклов).
    - `*/5 * * * *` `scripts/eu1_monitor.sh` — лёгкий мониторинг eu1 (CSV в `/var/log/eu1-monitor.log`) для расследования жалоб «скорость падает». Без speedtest, self-trim до ~12000 строк.
    - `*/10 * * * *` `scripts/ip_usage_watcher.py` — **iplimit-НАБЛЮДЕНИЕ (Фаза 2 A-Stage1)**, ТОЛЬКО замер. Парсит access-log Xray **из файла** `/var/log/xray/access.log` (не journald, с 06-17) на всех входах (eu1 локально + main/yc/yc2 SSH), копит (real client IP ↔ tid) в `ip_usage` (релей `127.0.0.1` игнор). distinct **/24** per юзер за окно = сигнал шеринга. **Калибровка 06-17: шеринга нет → enforcement НЕ вводим**, observe-only. Отчёт: `ip_usage_watcher.py --report`. Retention 48ч. Архитектура: `docs/plan-phase2-keystone-architecture.md`.
    После reboot проверять `crontab -l` — все на месте (текущий набор; eu1-share-audit снят 2026-06-15).
11. **Swap на eu1:** `/swapfile` 2 ГБ, `swappiness=10` (RAM всего 2 ГБ) — не удалять, страховка от OOM.
12. **Swap на yc:** `/swapfile` 1 ГБ, `swappiness=10` (RAM всего 960 МБ — критически мало) — добавлен 2026-06-01 после серии 14-минутных freeze'ов из-за memory pressure. Xray на yc ел до 619 МБ RAM (64%) из-за накопления stats counters + state от SYN-сканеров. Без swap при OOM-pressure ядро замораживало процессы → SSH timeout → health-check FAIL → юзеры теряли VLESS на ~14 мин. Если повторится при росте нагрузки — рассмотреть upgrade VM (yc free-tier очень тесный) или перезапуск Xray по расписанию.
13. **fail2ban на main/yc/yc2** (с 2026-06-11, Ubuntu 24.04, конфиг `/etc/fail2ban/jail.local`): `[sshd]` jail, `backend=systemd`, `maxretry=5`/`findtime=10m`/`bantime=1h`. **`ignoreip` ОБЯЗАТЕЛЬНО содержит Fornex `185.21.8.91`** — health_check / ip_usage_watcher / sync_xray_users / vless_summary_accounting ходят по SSH с Fornex; убрать из whitelist = fail2ban забанит мониторинг = каскадный сбой. `journalmatch` пиннится на `ssh.service` (Ubuntu-юнит, **не** `sshd.service` — иначе фильтр ловит 0 событий). Бан идёт в nft-таблицу `inet f2b-table` (на yc сосуществует с активным ufw). **Fornex БЕЗ fail2ban** (jump-хост, заходишь с динамического IP → риск самобана). health_check мониторит `fail2ban.service` на трёх. Снять бан: `fail2ban-client set sshd unbanip <ip>`. См. DONE_LIST 2026-06-11.

---

## Pre-deploy checklist (для агента)

Введено 2026-06-01 после критического бага: я случайно поставил декоратор `@bot.message_handler(commands=["start"])` над неправильной функцией → бот не отвечал на `/start` для всех юзеров. Чтобы такое не повторялось — перед каждым деплоем критичных файлов проходить чеклист:

**Критичные файлы:** `bot/main.py`, `web/app.py`, `bot/wireguard_peers.py`, `bot/vless_peers.py`, `bot/database.py`, `scripts/health_check.py`.

### Перед коммитом / scp

1. **После любого Edit рядом с декораторами или импортами** — прочитать **весь изменённый блок + ±5 строк контекста**. Проверить:
   - Декораторы привязаны к ожидаемой функции (не сдвинулись после вставки)
   - Имена импортов совпадают с тем что используется
   - Имена переменных не перепутаны после copy-paste
2. **Syntax check** на сервере перед restart: `venv/bin/python -c 'import ast; ast.parse(open("path/to/file.py").read()); print("OK")'` — обязательный шаг
3. **Import check** для модулей с handler'ами: `venv/bin/python -c 'from bot.main import register_handlers'` (или аналог) — ловит import-time errors которые syntax не видит
4. **Backup для destructive операций** на сервере: tmp-копия конфига/файла перед replace (как делает `patch_xray_stats.py`)

### После restart сервиса

5. **`systemctl is-active`** — обязательная проверка
6. **Журнал 30 сек после рестарта**: `journalctl -u <service> --since '30 seconds ago' --no-pager | grep -iE 'error|except|fail'` — нет ли немедленных exception'ов
7. **Smoke-test критичного функционала** (выбрать в зависимости от изменений):
   - Изменения в `cmd_start` / message handlers бота → **попросить владельца отправить `/start`** и подтвердить ответ
   - Изменения в API endpoints → `curl -sI` на изменённый route
   - Изменения в крон-скриптах → одиночный ручной прогон с проверкой stdout/stderr
   - Изменения в БД-helpers → проверить `sqlite3 ... "SELECT ... LIMIT 1"` что схема не сломана

### Особые случаи

- **Не использовать `logger.warning(...)` для критичных error path** — это скрывает стектрейс. Использовать `logger.exception(...)` чтобы при отладке видеть откуда упало.
- **Не делать большие изменения за один Edit** — атомарные правки, между ними возможность проверить
- **Для bot handler'ов** — после деплоя ВСЕГДА просить владельца попробовать `/start` (или соответствующую команду). 30 секунд проверки, исключает 90% багов привязки декораторов.

### Что НЕ делать

- ❌ Не пушить коммит без smoke-test'а
- ❌ Не делать `systemctl restart` без `systemctl is-active` проверки после
- ❌ Не игнорировать deprecation warnings — они часто становятся реальными багами в следующей мажорной версии библиотеки
- ❌ Не оставлять `logger.warning` где нужен `logger.exception` для error-path

---

## Документация

| Нужно | Читай |
|-------|-------|
| **Навигация по докам** | **`docs/README.md`** (индекс + правила source-of-truth + правило свежести 7 дн) |
| Открытые задачи | `ROADMAP_VPN.md` (только открытое) |
| История изменений | `DONE_LIST_VPN.md` (хронология + оглавление) |
| Монетизация / платежи | `docs/monetization-and-payments.md` |
| Последняя сессия | `docs/sessions/SESSION_SUMMARY_2026-06-23.md` (Daniil-триаж + #4-минимум + whitelist-трек запаркован) |
| Yota/Мегафон решение | `docs/sessions/SESSION_SUMMARY_2026-05-21.md` + `DONE_LIST_VPN.md` (2026-05-21) |
| Деплой чеклист | `docs/deployment.md` |
| MTProxy операции | `docs/telegram-mtproxy-operators-guide.md` |
| **План фаз 3–4–5 (master)** | **`docs/plan-phase-3-4-5.md`** — читать первым при потере контекста |
| Support tickets (Variant B) | `support_tickets` + `support_messages` в SQLite. Команды: `/support_list /support_view N /support_close N`. Юзер: меню → «🆘 Поддержка» (или ЛК → openTelegramLink → `?start=support`). Owner: inline-кнопки [✉️ Ответить / ✅ Закрыть / 📜 История] на каждом входящем. |
| ЮKassa setup (владельцу) | `docs/yookassa-setup-instruction.md` |
| Yandex Cloud REALITY | `docs/yandex-cloud-reality-setup.md` |
| Бэкап/восстановление | `docs/backup-restore.md` |
| Стратегия обхода блокировок | `docs/blocking-bypass-strategy.md` |
| Конкуренты | `docs/competitors-analysis.md` |

Старые сессии (Feb–Mar 2026): `docs/sessions/old/` — история, не читать для работы.
Устаревшие доки: `docs/archive/` — не актуальны.
