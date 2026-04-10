# README для следующего агента — VPN Service

## Обзор проекта

VPN-сервис на базе WireGuard/AmneziaWG с поддержкой нескольких серверов. Управление через Telegram-бота.

**Репозиторий GitHub:** https://github.com/nikkronos/vpnservice (кратко: `nikkronos/vpnservice`)

**Локальный путь от корня workspace:** `Projects/VPN/`

**Полный путь (Windows):** `C:\Users\krono\OneDrive\Рабочий стол\Cursor_Projects\Projects\VPN`

## Уточнения (вопросы из сторонних обсуждений)

- **Relay-сервера в проекте нет.** Есть только ноды VPN (main на Timeweb, eu1 на Fornex). **Прод-бот** с 2026-04-10 на **Fornex**; **веб-панель** `vpn-web` и URL recovery пока по документам на **Timeweb** — перенос на Fornex: **`docs/vpn-web-migration-fornex-plan.md`**.

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

- **URL (сейчас):** http://81.200.146.32:5001/
- **Recovery (без Telegram):** http://81.200.146.32:5001/recovery — ввод Telegram ID → **актуальная ссылка `tg://proxy`** (`GET /api/recovery/proxy-link`, как `/proxy`, без рестарта) или **«Восстановить Telegram»** (POST — рестарт контейнера + ссылка); два блока **VPN EU1 / EU2** (AmneziaWG). См. `docs/telegram-mtproxy-operators-guide.md`, `DONE_LIST_VPN.md` (слоты rus1–eu2).
- **Сервис:** `vpn-web.service` на Timeweb; **перенос на Fornex** — чеклист `docs/vpn-web-migration-fornex-plan.md`.
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

Файл `/opt/vpnservice/env_vars.txt` на Timeweb:

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

## Что РАБОТАЕТ

| Технология | Сервер | Статус |
|------------|--------|--------|
| WireGuard | main (Timeweb) | ✅ Автоматическая выдача через бота |
| AmneziaWG (Docker) | eu1 (Fornex) | ✅ Автоматическая выдача через бота |
| VLESS + REALITY (TCP) | eu1 (опционально) | ⚙️ Резерв для LTE/5G; см. `docs/xray-vless-reality-eu1-deploy.md`, бот `/mobile_vpn` |
| Telegram | Через VPN (AmneziaWG eu1 / WG main) | ✅ |
| MTProxy с Fake TLS (`mtproxy-faketls`, `nineseconds/mtg:2`) | **Fornex eu1**, внешний порт **8444** (443 на хосте занят Xray); ранее в доках — main Timeweb :443 | ✅ Развёртывание: `docs/mtproxy-faketls-deploy.md`; ротация: `docs/mtproxy-proxy-rotation.md`; сессия 2026-04-10 — `SESSION_SUMMARY_2026-04-10.md` |

## Полезные команды

### На Timeweb (бот)

```bash
# Логи бота
journalctl -u vpn-bot.service -f

# Перезапуск бота
systemctl restart vpn-bot.service

# Проверка peers
cat /opt/vpnservice/bot/data/peers.json | python3 -m json.tool

# Тест SSH к eu1
ssh -i /root/.ssh/id_ed25519_eu1 root@185.21.8.91 "echo OK"
```

### На eu1 (Fornex)

```bash
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

- **`docs/mobile-lte-eu1-xray-reality-attempt-2026-03.md`** — попытка обхода LTE через Xray REALITY на eu1: что сделано, диагностика (tcpdump, Safari), вывод «блок до IP Fornex», **что делать дальше** (REALITY на Timeweb, другой VPS)
- **SESSION_SUMMARY_2026-03-07.md** — последняя сессия (Telegram-прокси Fake TLS, алгоритм разблокировки, оценка провайдера)
- **SESSION_SUMMARY_2026-02-26.md** — автоматизация выдачи конфигов + удаление /proxy
- **SESSION_SUMMARY_2026-02-23.md** — попытки Remnawave, Xray, MTProto (неудачны)
- **ROADMAP_VPN.md** — план развития
- **DONE_LIST_VPN.md** — выполненные задачи
- **docs/provider-choice-evaluation.md** — оценка выбора провайдера (Fornex vs FirstVDS и др.)
- **docs/telegram-unblock-algorithm.md** — алгоритм сохранения доступа к Telegram при блокировках/троттлинге (без правок в боте)
- **docs/mtproxy-faketls-deploy.md** — пошаговое развёртывание MTProxy с Fake TLS (готовые команды под копипаст)
- **docs/telegram-mtproxy-operators-guide.md** — **сводка для владельца/агентов:** `/proxy`, `/proxy_rotate`, recovery, env, деплой pip через venv
- **docs/mtproxy-proxy-rotation.md** — ротация секрета, скрипт, переменные
- **docs/telegram-proxy-alternatives.md** — сторонние варианты (справочно, не официальный стек)
- **`docs/specs/spec-08-multi-node-redundancy-ru2-eu2.md`** — резервы и мульти-вход: **без нового VPS** (сценарий B: main+eu1, опц. REALITY на main); отдельный VPS (RU2/EU2) — только если появится бюджет
- **`docs/third-party-vpn-boosters-vs-multi-entry.md`** — «ускорители» вроде GearUp vs наш мульти-вход (что реалистично в MVP)

## Важные правила

1. **Не трогать main (Timeweb)** — там всё работает
2. **eu1 = Docker** — AmneziaWG работает в контейнере `amnezia-awg2`
3. **Подсеть eu1 = 10.8.1.0/24** — не путать со старой 10.1.0.0/24
4. **Порт eu1 = 39580** — не 51820
5. **Прокси Telegram:** на eu1 «голый» MTProto не использовать (блок по сигнатуре). Для Telegram без полного VPN — **MTProxy с Fake TLS на main** (`docs/mtproxy-faketls-deploy.md`). В боте снова есть **`/proxy`** и **`/proxy_rotate`** (владелец); актуальная ссылка: приоритет `data/mtproto_proxy_link.txt`, иначе `MTPROTO_PROXY_LINK` в `env_vars.txt` (читается с диска). Сводка: **`docs/telegram-mtproxy-operators-guide.md`**
6. **Конфиги в Docker не персистентны** — делать бэкапы!

## Контакты и ресурсы

- **GitHub:** `nikkronos/vpnservice`
- **Бот:** Timeweb (81.200.146.32)
- **eu1:** Fornex (185.21.8.91)
