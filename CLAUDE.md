# CLAUDE.md — VPN Service

Репозиторий: `nikkronos/vpnservice` | Путь: `Projects/VPN/`

**Бренд (с 2026-05-25):** Kronos / VPN Kronos. Бот `@vpnkronos_bot` (display `vpnkronos`). Домен `supportkronos.online` (нейтральный, маскировка под support-портал). Канал `@vforfriends` legacy. **Цена**: 200 ₽/мес. Текущие 34 юзера — на старом боте, миграция broadcast'ом владельца после Phase 3b.

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

## Инфраструктура (май 2026)

| Сервер | IP | Что на нём |
|--------|-----|-----------|
| **Fornex eu1** (основной) | `185.21.8.91` | Бот, веб-панель, AmneziaWG Docker, MTProxy Fake TLS, Xray VLESS+WS+XHTTP+REALITY (443) |
| **Timeweb main** (RU + Мегафон/Yota) | `81.200.146.32` | **Xray VLESS+REALITY на 443** (SNI=cloud.mail.ru, для Мегафон/Yota при БС, см. SESSION_SUMMARY_2026-05-21). Также WireGuard wg0 на UDP/51820 для 1 legacy user. SSH: `ssh -i ~/.ssh/id_ed25519_main root@81.200.146.32` (или через Fornex jump) |
| **Yandex Cloud vrprnt** (T2/МТС/Билайн) | `158.160.236.147` | Xray VLESS+REALITY xHTTP (порт 443, SNI: www.microsoft.com) |

**SSH:**
- Fornex: `ssh fornex` (алиас) или `ssh -i ~/.ssh/id_ed25519_fornex root@185.21.8.91`
- Timeweb (main): через Fornex jump — `ssh fornex "ssh -i /root/.ssh/id_ed25519_main root@81.200.146.32 ..."`
- Yandex Cloud (yc): через Fornex jump — `ssh fornex "ssh yc ..."` (alias настроен в `/root/.ssh/config` на Fornex, ключ `/root/.ssh/id_ed25519_yc`, user `ubuntu` с passwordless sudo)

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
  vpn.db           — SQLite (основная БД)
  peers.json       — legacy JSON (ещё используется)
  mtproto_proxy_link.txt — текущая MTProxy ссылка (не в git)
scripts/
  traffic_accounting.py — cron-сэмплер lifetime-трафика (*/5)
  expiry_reminder.py    — напоминания T-7/3/0 (cron 0 9 * * *, 12:00 МСК)
  sheets_sync_cron.py   — auto-sync БД → Google Sheets (cron 0 */6 * * *)
  health_check.py       — 22 проверки инфры (Fornex local + main/yc через SSH) → TG-алерты владельцу (cron */15)
  vless_summary_accounting.py — per-server VLESS lifetime через Xray stats API (cron */5)
  patch_xray_stats.py   — идемпотентный патч Xray config: добавляет stats/api блоки + теги inbound'ов
  traffic_diagnosis.py  — кто качал в окне (read-only диагностика по traffic_snapshots): `python scripts/traffic_diagnosis.py --last 1h` или `python scripts/traffic_diagnosis.py 2026-05-30 17:00 2026-05-30 18:00` (UTC)
  peers_sync_check.py   — диагностика рассинхрона peers.json ↔ awg show ↔ БД (read-only, on-demand)
```

### Ключевые концепции

- **server_id:** `eu1` (AmneziaWG, Docker), логически был `eu2` — нормализован в `eu1` через `storage.py`
- **peer key формат:** `{telegram_id}:{server_id}:{platform}` (в peers.json)
- **Платформы:** `pc`, `ios`, `android` — Android получает `vpn://` deep link, iOS/PC — `.conf` файл
- **Admin auth:** `ADMIN_SECRET` (64-char hex) — для `/api/users`, `/api/traffic`
- **Recovery auth:** `RECOVERY_SECRET` — для legacy recovery endpoints
- **traffic_accounting (SQLite):** накопительный lifetime-трафик по pubkey, reset-aware (счётчики awg обнуляются при рестарте/перегенерации). Пишется из `/api/traffic` при просмотре + cron `*/5` `scripts/traffic_accounting.py`. Столбец «Всего» в панели.
- **Модель аккаунта (биллинг, Фаза 0, 2026-05-25):** в `users` поля `subscription_status`/`expires_at`/`trial_used`/`plan`/`referral_code`/`referred_by`/`password_hash`/`sub_token` + таблица `payments`. Хелперы в `database.py` (`db_is_access_active`, `db_start_trial`, `db_extend_subscription`, `db_ensure_referral_code`, `db_set_password`, `db_ensure_sub_token`, …). **expires_at NULL = grandfathered** (доступ без ограничения). **Enforcement пока ВЫКЛЮЧЕН** — доступ у всех; включаем в Фазе 4 (тогда же grandfather существующих + новые стартуют с триала). Константы в `web/app.py`: TRIAL_DAYS=14, REFERRAL_REWARD_DAYS=14.
- **Subscription-URL (validated 2026-05-25):** `GET /sub/<sub_token>` → base64-список VLESS-REALITY ссылок (YC `www.microsoft.com` + main `cloud.mail.ru`). HAPP/Streisand/V2Box/Hiddify импортируют как «subscription» — один URL, авто-выбор сервера, авто-обновление. Гейт `db_is_access_active` — истёк срок → пустая подписка → все устройства отваливаются (чистый enforcement для Фазы 4). Спайк: общие share-ссылки; per-user UUID — TODO. `ProxyFix(x_proto, x_host)` в app.py чтобы за nginx Flask отдавал https-ссылки.
- **Cloudflare в РФ заблокирован/throttled** (durable, 2026-05-25): DPI режет TLS к CF — у владельца Safari не открывает CF-fronted домен. **CF используем только как DNS (grey-cloud)**, не как прокси. HTTPS — прямой с нашего хоста (Fornex direct + LE cert).
- **Зависимость:** `qrcode[pil]` (QR в ЛК). В `requirements.txt`; на сервере уже в venv.

---

## Бот — текущий UX

**Меню /start:** 7 inline-кнопок

- `📲 Получить VPN` → выбор платформы [💻 ПК | 🍎 iOS | 🤖 Android] → конфиг
- `🔄 Обновить конфиг` → то же с платформой
- `📡 Мобильный резерв` → VLESS+REALITY ссылка (Yandex Cloud)
- `📋 Инструкция`, `ℹ️ Статус`, `📎 Прокси Telegram`
- `⚙️ Администратор` (только владелец)

**Команды владельца:** `/proxy_rotate`, `/broadcast`

---

## Веб-панель

- **Мониторинг:** `http://185.21.8.91:5001/` — тёмная тема, статус AWG/VLESS, таблица трафика по пользователям с устройством и handshake
- **Recovery / ЛК:** **`https://supportkronos.online:8443/recovery`** (HTTPS direct с Fornex, LE cert, nginx :8443 → Flask :5001; домен grey-cloud в CF). Старый `http://185.21.8.91:5001/recovery` тоже жив как fallback (не закрыт). Вход email-OTP или пароль. Экран «Мой аккаунт»: статус/срок, **«Подписка» как главный CTA** (одна ссылка для всех устройств, импорт в HAPP/Streisand/V2Box/Hiddify), триал, реферал, управление паролем. Альтернативно — конкретные конфиги (Основной VPN / VPN при блокировках / Разблокировка Telegram). QR (qrcode[pil]).

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
    - `*/5 * * * *` `scripts/vless_summary_accounting.py` — lifetime VLESS-трафика per-server (eu1 локально + main/yc через SSH к Xray stats API на 127.0.0.1:10085). Пишет в таблицу `vless_server_traffic`, reset-aware.
    - `0 9 * * *` `scripts/expiry_reminder.py` — напоминания T-7/3/0 (12:00 МСК).
    - `0 */6 * * *` `scripts/sheets_sync_cron.py` — auto-sync Google Sheets (каждые 6 ч). Ручной триггер в боте «📊 Sync Google Sheets» остаётся как fallback.
    - `*/15 * * * *` `scripts/health_check.py` — 22 проверки инфры. **Fornex (12, локально):** systemd сервисы (vpn-bot/vpn-web/nginx/xray), docker (amnezia-awg2/mtproxy-faketls), AWG peer-count, peers.json/awg consistency, диск, swap, LE-cert, HTTPS endpoint. **main (6, через SSH):** reachable + xray + wg-quick@wg0 + :443/tcp + :51820/udp + диск. **yc (4, через SSH):** reachable + xray + :443/tcp + диск. **Все remote-проверки одного хоста идут одним SSH-batch'ем** (с маркерами `<<<BEGIN:N>>>`/`<<<END:N:rc>>>`) — раньше отдельные ssh-коннекты иногда отбивались провайдером main с `Connection closed by ... port 22` на 5-6-м соединении (false-FAIL'ы 2026-05-31). При смене статуса OK↔FAIL шлёт TG-алерт владельцу (прямой HTTP API, не через инстанс бота). State: `/var/lib/vpn-health/state.json`. Remote-ключи префиксованы `<host>:` (`yc:xray.service`). FAIL `<host>:reachable` — gate: остальные проверки этого хоста скипаются, чтобы один сетевой провал не давал каскад.
    После reboot проверять `crontab -l` — все пять на месте.
11. **Swap на eu1:** `/swapfile` 2 ГБ, `swappiness=10` (RAM всего 2 ГБ) — не удалять, страховка от OOM.

---

## Документация

| Нужно | Читай |
|-------|-------|
| Открытые задачи | `ROADMAP_VPN.md` |
| История изменений | `DONE_LIST_VPN.md` |
| Последняя сессия | `docs/sessions/SESSION_SUMMARY_2026-05-27.md` |
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
