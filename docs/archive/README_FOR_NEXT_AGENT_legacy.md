# README для следующего агента — VPN Service

## Обзор проекта

VPN-сервис на базе WireGuard/AmneziaWG с поддержкой нескольких серверов. Управление через Telegram-бота.

**Репозиторий GitHub:** https://github.com/nikkronos/vpnservice (кратко: `nikkronos/vpnservice`)

**Локальный путь от корня workspace:** `Projects/VPN/`

**Полный путь (Windows):** `C:\Users\krono\OneDrive\Рабочий стол\Cursor_Projects\Projects\VPN`

## Уточнения (вопросы из сторонних обсуждений)

- **Relay-сервера в проекте нет.** Ноды: **main** (Timeweb, WireGuard), **eu1** (Fornex, AmneziaWG). **Прод-бот** и **`vpn-web`** с **2026-04-11** на **Fornex** (`185.21.8.91`); панель на Timeweb **отключена**. Итог миграции: **`docs/vpn-web-migration-fornex-plan.md`**, **`SESSION_SUMMARY_2026-04-10.md`**.
- **После переноса бота на Fornex** обязательно: **`wireguard-tools`** на хосте бота (иначе `/get_config` для России падает на `wg genkey`); файл по **`WG_EU1_SSH_KEY_PATH`** должен существовать (иначе `/regen` AmneziaWG — SSH «ключ не найден»). Подробно: **`docs/deployment.md`** → раздел «Чеклист хоста бота после переноса на Fornex», **`SESSION_SUMMARY_2026-04-11.md`**, **`DONE_LIST_VPN.md`** (2026-04-11).

## Текущее состояние (2026-03-14)

### Серверы

| Сервер | IP | Протокол | Порт | Подсеть | Статус |
|--------|-----|----------|------|---------|--------|
| main (Россия, Timeweb) | 81.200.146.32 | WireGuard | 51820/UDP | 10.0.0.0/24 | ✅ Работает |
| eu1 (Европа, Fornex) | 185.21.8.91 | AmneziaWG (Docker) | 39580/UDP | 10.8.1.0/24 | ✅ Работает |

### Бот

- **Расположение (прод, 2026-04-10):** Fornex — `/opt/vpnservice`, `vpn-bot.service` (ранее в доках указывался Timeweb; миграция Telegram-сервисов — `Main_docs/TELEGRAM_MIGRATION_TIMWEB_FORNEX_2026-04-10.md`).
- **Россия (main):** автоматическая выдача WireGuard конфигов
- **Европа (eu1):** автоматическая выдача AmneziaWG конфигов
- **Мобильный резерв (eu1):** если в `env_vars.txt` задан `VLESS_REALITY_SHARE_URL` (полная ссылка `vless://…`), пользователи с активным доступом в **чате с Telegram-ботом** отправляют команду **`/mobile_vpn`** (это не путь к папке и не shell-команда — обычная slash-команда бота, как `/start`). В ответ — инструкция + ссылка для v2rayNG / Streisand / Hiddify и т.п. (TCP REALITY, не затрагивает AmneziaWG).
- **Команды:** `/start`, `/server`, `/get_config`, `/regen`, `/status`, `/help`, `/instruction`, `/proxy` (актуальная ссылка MTProxy Fake TLS — как на странице recovery), `/proxy_rotate` (только владелец — ротация секрета на сервере), `/mobile_vpn`, `/broadcast` (только владелец — рассылка уведомления всем пользователям)

### Веб-панель мониторинга

- **URL (прод, Fornex):** [мониторинг](http://185.21.8.91:5001/) и [recovery](http://185.21.8.91:5001/recovery) — главная **`/`** (статистика, сервисы, трафик) и **`/recovery`** (Telegram ID → ссылка MTProxy, VPN EU1/EU2). В `env_vars.txt`: **`VPN_RECOVERY_URL=http://185.21.8.91:5001/recovery`**.
- **Recovery:** ввод Telegram ID → **актуальная ссылка `tg://proxy`** (`GET /api/recovery/proxy-link`, как `/proxy`, без рестарта) или **«Восстановить Telegram»** (POST — рестарт контейнера + ссылка); два блока **VPN EU1 / EU2** (AmneziaWG). См. `docs/telegram-mtproxy-operators-guide.md`, `DONE_LIST_VPN.md` (слоты rus1–eu2).
- **Сервис:** `vpn-web.service` на **Fornex**; для трафика **rus1/rus2** на панели — **`WG_SSH_*`** к main в `env_vars.txt`. На **Timeweb** `vpn-web` **отключён** (2026-04-11).
- **Функции:** статус серверов, статистика пользователей, трафик по пользователям

## Архитектура eu1 (Docker)

AmneziaWG на eu1 работает **в Docker-контейнере**:

```
Контейнер: amnezia-awg2
Порт: 39580/UDP
Подсеть: 10.8.1.0/24
Публичный ключ сервера: pevLcgguoIMDWnbtPgQ3ZsSak73fylprex54Tv65ZyI=
PSK: 3/mTrFbOrpdmhVpvKOHyitiCeqGCefX9K9e4MdRmbQo=
```

### Скрипты на eu1

- **`/opt/amnezia-add-client.sh`** — добавление клиента
  - Принимает IP или имя клиента
  - Выводит `PUBKEY=...` первой строкой, затем конфиг
  - Автоматически генерирует ключи и добавляет peer в контейнер

- **`/opt/amnezia-remove-client.sh`** — удаление клиента по публичному ключу

### Параметры обфускации (фиксированные)

```
Jc = 5
Jmin = 10
Jmax = 50
S1 = 139
S2 = 72
S3 = 20
S4 = 4
H1 = 2087213719-2093002138
H2 = 2133611580-2143827555
H3 = 2144912845-2145190160
H4 = 2145842498-2146737471
```

## Ключевые переменные бота

Файл `/opt/vpnservice/env_vars.txt` на сервере бота (**прод: Fornex**, `/opt/vpnservice`):

```bash
# Россия (main)
WG_SERVER_PUBLIC_KEY=...
WG_INTERFACE=wg0
WG_NETWORK_CIDR=10.0.0.0/24
WG_ENDPOINT_HOST=81.200.146.32
WG_ENDPOINT_PORT=51820

# Европа (eu1) — AmneziaWG в Docker
WG_EU1_SERVER_PUBLIC_KEY=pevLcgguoIMDWnbtPgQ3ZsSak73fylprex54Tv65ZyI=
WG_EU1_ENDPOINT_HOST=185.21.8.91
WG_EU1_ENDPOINT_PORT=39580
WG_EU1_NETWORK_CIDR=10.8.1.0/24
WG_EU1_SSH_HOST=185.21.8.91
WG_EU1_SSH_USER=root
WG_EU1_SSH_KEY_PATH=/root/.ssh/id_ed25519_eu1

# Скрипты AmneziaWG
AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT=/opt/amnezia-add-client.sh
AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT=/opt/amnezia-remove-client.sh
AMNEZIAWG_EU1_NETWORK_CIDR=10.8.1.0/24
AMNEZIAWG_EU1_INTERFACE=awg0
```

## Как это работает

### Получение конфига пользователем

1. Пользователь: `/server` → выбирает "Европа"
2. Пользователь: `/get_config`
3. Бот вызывает по SSH: `/opt/amnezia-add-client.sh <IP>`
4. Скрипт добавляет peer в Docker-контейнер и возвращает конфиг
5. Бот отправляет `.conf` файл пользователю
6. Пользователь импортирует в **AmneziaVPN** (не обычный WireGuard!)

### Регенерация конфига

1. Пользователь: `/regen`
2. Бот вызывает `/opt/amnezia-remove-client.sh <old_pubkey>`
3. Бот вызывает `/opt/amnezia-add-client.sh <same_IP>`
4. Бот отправляет новый конфиг

## Бэкапы

### eu1 (Fornex)

```
/root/amnezia-backup-20260226/
├── awg0.conf                      # Конфиг сервера
├── clientsTable                   # Таблица клиентов (JSON)
├── wireguard_server_private_key.key
├── wireguard_server_public_key.key
├── wireguard_psk.key
└── container-inspect.json         # Параметры Docker-контейнера
```

### Timeweb

```
/opt/vpnservice/env_vars.txt.backup_*   # Бэкапы переменных
/opt/vpnservice/bot/data/peers.json.backup_*  # Бэкапы peers
```

## Восстановление при проблемах

### Если автоматизация сломалась

1. Восстановить через приложение **AmneziaVPN** на ПК:
   - Удалить сервер eu1 из приложения
   - Добавить сервер заново по SSH (root@185.21.8.91)
   - Установить AmneziaWG через приложение
   - Раздать конфиги вручную через "Поделиться VPN"

2. Или восстановить из бэкапа:
   - Скопировать файлы из `/root/amnezia-backup-20260226/` в контейнер
   - Перезапустить контейнер

### Если Docker-контейнер удалён

Конфиги хранятся **внутри контейнера** (нет volume). При удалении контейнера:
1. Восстановить из бэкапа `/root/amnezia-backup-20260226/`
2. Или установить AmneziaWG заново через приложение

## Что НЕ работает на eu1

| Технология | Статус | Причина |
|------------|--------|---------|
| WireGuard UDP (51820) | ❌ | Блокировка на маршруте РФ ↔ Fornex |
| Обычный MTProto (`telegrammessenger/proxy`) на eu1 | ❌ | Оператор блокировал по сигнатуре (не порт); см. `docs/telegram-unblock-algorithm.md` |
| Xray VLESS/TCP без TLS | ❌ | DPI распознаёт |
| Remnawave | ❌ | Ошибки конфигурации |
| Cloudflare CDN + VLESS/WS (при whitelist-режиме LTE) | ❌ | Даже Cloudflare IPs не входят в whitelist; см. `SESSION_SUMMARY_2026-05-05.md` |

## Что РАБОТАЕТ

| Технология | Сервер | Статус |
|------------|--------|--------|
| WireGuard | main (Timeweb) | ✅ Автоматическая выдача через бота |
| AmneziaWG (Docker) | eu1 (Fornex) | ✅ Автоматическая выдача через бота |
| VLESS + WebSocket + Cloudflare CDN | eu1 (Fornex), `sub.vpnnkrns.ru:443` | ⚙️ Настроен; работает при обычных блокировках, бесполезен при whitelist-режиме LTE; Xray port 80, `path=/vpn` |
| VLESS + REALITY (Yandex Cloud) | `158.160.236.147:443`, SNI `www.yandex.ru` | ✅ Резерв для LTE whitelist-режима; Yandex Cloud IP в whitelist у всех операторов; бот `/mobile_vpn`; см. `docs/yandex-cloud-reality-setup.md` |
| Telegram | Через VPN (AmneziaWG eu1 / WG main) | ✅ |
| MTProxy с Fake TLS (`mtproxy-faketls`, `nineseconds/mtg:2`) | **Fornex eu1**, внешний порт **8444** | ✅ Развёртывание: `docs/mtproxy-faketls-deploy.md`; ротация: `docs/mtproxy-proxy-rotation.md`; сессия 2026-04-10 — `SESSION_SUMMARY_2026-04-10.md` |

## Полезные команды

### На Fornex (бот, веб-панель, eu1 — один хост `185.21.8.91`)

```bash
# Логи бота
journalctl -u vpn-bot.service -f

# Перезапуск бота
sudo systemctl restart vpn-bot.service

# Логи веб-панели
journalctl -u vpn-web.service -f

# Перезапуск панели
sudo systemctl restart vpn-web.service

# Проверка peers
cat /opt/vpnservice/bot/data/peers.json | python3 -m json.tool

# Тест SSH к main (Timeweb), если настроен WG_SSH_KEY_PATH
ssh -i /root/.ssh/id_ed25519_main -o BatchMode=yes root@81.200.146.32 "echo OK"

# Статус Docker-контейнера
docker ps

# Список клиентов AmneziaWG
docker exec amnezia-awg2 awg show awg0

# Логи контейнера
docker logs amnezia-awg2

# Тест скрипта добавления клиента
/opt/amnezia-add-client.sh test_client

# Конфиг сервера
docker exec amnezia-awg2 cat /opt/amnezia/awg/awg0.conf
```

## Документация

### Активные операционные доки
- **`docs/yandex-cloud-reality-setup.md`** — полная документация YC VM: параметры, Xray конфиг, ключи, Security Group, SSH, known issues
- **`docs/risks-and-mitigations.md`** — реестр рисков инфраструктуры с приоритетными действиями
- **`docs/blocking-bypass-strategy.md`** — стратегия обхода блокировок, включая whitelist-режим LTE
- **`docs/deployment.md`** — чеклист деплоя и переноса бота
- **`docs/backup-restore.md`** — процедуры бэкапа и восстановления
- **`docs/mobile-lte-eu1-xray-reality-attempt-2026-03.md`** — попытка REALITY на eu1: диагностика, вывод «блок до IP Fornex»
- **`docs/yandex-cloud-reality-setup.md`** — YC VM setup (актуально)

### Telegram / MTProxy
- **`docs/telegram-mtproxy-operators-guide.md`** — сводка для владельца: `/proxy`, `/proxy_rotate`, recovery, env
- **`docs/mtproxy-faketls-deploy.md`** — развёртывание MTProxy Fake TLS
- **`docs/mtproxy-proxy-rotation.md`** — ротация секрета
- **`docs/telegram-unblock-algorithm.md`** — алгоритм сохранения доступа к Telegram

### Клиентские инструкции
- **`docs/client-instructions-pc.md`**, **`docs/client-instructions-ios.md`**, **`docs/client-instructions-android.md`**, **`docs/client-instructions-amneziawg.md`**

### Прочее
- **`docs/provider-choice-evaluation.md`** — оценка провайдеров
- **`docs/telegram-proxy-alternatives.md`** — альтернативы MTProxy
- **`docs/specs/`** — спецификации фич

### Сессии (docs/sessions/)
- **`docs/sessions/SESSION_SUMMARY_2026-05-06.md`** — YC VM, VLESS+REALITY, routing через eu1 ✅
- **`docs/sessions/SESSION_SUMMARY_2026-05-05.md`** — Cloudflare CDN (whitelist-блок)
- **`docs/sessions/SESSION_SUMMARY_2026-04-12.md`** — UFW fix, обновление ссылок
- **`docs/sessions/SESSION_SUMMARY_2026-04-11.md`** — миграция бота на Fornex (часть 2)
- **`docs/sessions/SESSION_SUMMARY_2026-04-10.md`** — MTProxy Fake TLS, миграция на Fornex
- *(остальные — ранние сессии разработки)*

### Архив (docs/archive/)
Устаревшие одноразовые файлы (команды установки, старые планы, нереализованные эксперименты).

- **ROADMAP_VPN.md** — план развития
- **DONE_LIST_VPN.md** — выполненные задачи

## Важные правила

1. **Не трогать main (Timeweb)** — там всё работает
2. **eu1 = Docker** — AmneziaWG работает в контейнере `amnezia-awg2`
3. **Подсеть eu1 = 10.8.1.0/24** — не путать со старой 10.1.0.0/24
4. **Порт eu1 = 39580** — не 51820
5. **Прокси Telegram:** на eu1 «голый» MTProto не использовать (блок по сигнатуре). **MTProxy Fake TLS** сейчас на **Fornex**, внешний порт **8444** (см. `docs/mtproxy-proxy-rotation.md`, `SESSION_SUMMARY_2026-04-10.md`). В боте **`/proxy`** и **`/proxy_rotate`** (владелец); приоритет ссылки: `data/mtproto_proxy_link.txt`, иначе `MTPROTO_PROXY_LINK`. Сводка: **`docs/telegram-mtproxy-operators-guide.md`**
6. **Конфиги в Docker не персистентны** — делать бэкапы!

## Контакты и ресурсы

- **GitHub:** `nikkronos/vpnservice`
- **Бот и веб-панель:** Fornex (`185.21.8.91`, `/opt/vpnservice`)
- **main (WireGuard RU):** Timeweb (`81.200.146.32`)
- **eu1 (AmneziaWG и др.):** тот же Fornex (`185.21.8.91`)
