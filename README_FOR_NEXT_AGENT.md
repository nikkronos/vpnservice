# README для следующего агента — VPN Service

## Обзор проекта

VPN-сервис на базе WireGuard с поддержкой нескольких серверов и типов профилей. Управление через Telegram-бота.

**Репозиторий:** `nikkronos/vpnservice`  
**Локальный путь:** `Projects/VPN/`

## Архитектура

### Серверы

1. **main (Россия, Timeweb)**
   - IP: `81.200.146.32`
   - WireGuard: `wg0`, подсеть `10.0.0.0/24`, порт `51820/UDP`
   - Бот работает здесь (Timeweb)

2. **eu1 (Европа, Fornex)**
   - IP: `185.21.8.91`
   - WireGuard: `wg0`, подсеть `10.1.0.0/24`, порт `51820/UDP` (из РФ не работает — блокировка).
   - Shadowsocks: `ss-redir` на `127.0.0.1:1081`
   - **AmneziaWG:** развёрнут на eu1, из России работает (обфускация). Для Европы бот выдаёт инструкцию AmneziaWG и при настройке скрипта на eu1 (`AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT`) — готовый AmneziaWG .conf. Инструкция развёртывания: docs/amneziawg-deploy-instruction.md; для пользователей: docs/client-instructions-amneziawg.md (iOS — импорт через «Поделиться»). Проверка на eu1: docs/amneziawg-eu1-discovery.md; спек бота: docs/specs/spec-05-bot-amneziawg-eu1.md.

### Типы профилей на eu1

1. **Обычный VPN** (`profile_type=None` или `"vpn"`)
   - Трафик через WireGuard напрямую
   - Подходит для: YouTube, Instagram, обычные сайты

2. **VPN+GPT** (`profile_type="vpn_gpt"`)
   - Пул IP: `10.1.0.8–19` и `51–254` (исключая `20–50`)
   - Весь TCP 80/443 редиректится на `ss-redir` (порт 1081)
   - Скрипт: `/opt/vpnservice/scripts/add-ss-redirect.sh <IP>`
   - Подходит для: ChatGPT, заблокированные сайты, все сервисы
   - ⚠️ Может быть медленнее из-за двойного туннелирования

3. **Универсальный (Unified)** (`profile_type="unified"`) — **НОВЫЙ**
   - Пул IP: `10.1.0.20–50` (отдельно от VPN+GPT)
   - Редирект только для IP из ipset `unified_ss_dst` (ChatGPT и др.)
   - Остальной трафик (YouTube, Telegram, обычные сайты) идёт напрямую
   - На сервере: ipset + одно правило iptables (см. `docs/scripts/setup-unified-iptables.sh.example`)
   - Скрипт обновления IP: `docs/scripts/update-unified-ss-ips.sh.example` (cron)
   - Подходит для: **все сервисы в одном профиле** (как у крупных VPN-провайдеров)

### Пул IP на eu1 (Fornex)

| Тип профиля | Пул октетов | Примечание |
|-------------|-------------|------------|
| VPN+GPT     | 8–19, 51–254 | Редирект всего 80/443 через ss-redir |
| Unified     | 20–50       | Редирект только IP из ipset (ChatGPT) |

## Структура проекта

```
VPN/
├── bot/                    # Telegram-бот
│   ├── main.py            # Основная логика бота
│   ├── wireguard_peers.py # Работа с WireGuard (создание peer, конфиги)
│   ├── storage.py         # Хранение users.json и peers.json
│   └── config.py          # Конфигурация из env_vars.txt
├── docs/
│   ├── specs/             # Спецификации
│   │   ├── spec-04-unified-profile-all-services.md
│   │   └── spec-04-implementation-unified-profile.md
│   ├── scripts/           # Примеры скриптов для сервера
│   │   ├── setup-unified-iptables.sh.example
│   │   ├── update-unified-ss-ips.sh.example
│   │   └── add-ss-redirect.sh.example
│   └── deployment.md      # Инструкции по деплою
├── env_vars.example.txt   # Пример переменных окружения
├── requirements.txt       # Python-зависимости
└── README_FOR_NEXT_AGENT.md  # Этот файл
```

## Ключевые файлы

### Бот

- **`bot/main.py`**: Команды `/start`, `/get_config`, `/regen`, `/server`, `/status`, `/help`. Для Европы (eu1) выдаётся AmneziaWG (инструкция или .conf через скрипт на eu1).
- **`bot/wireguard_peers.py`**: 
  - `create_peer_and_config_for_user()` — создание peer и конфига
  - `_allocate_ip_unified_pool()` — выделение IP для Unified (20–50)
  - `_allocate_ip_in_pool()` — выделение IP для VPN+GPT (8–19, 51–254)
  - Для Unified **не вызывается** `_run_add_ss_redirect()`
- **`bot/storage.py`**: `User.preferred_profile_type` (`"vpn"`, `"vpn_gpt"`, `"unified"`), `Peer.profile_type`

### Конфигурация

- **`env_vars.txt`** (на сервере, не в Git): переменные `BOT_TOKEN`, `ADMIN_ID`, `WG_*`, `WG_EU1_*`
- **`env_vars.example.txt`**: пример всех переменных

## Настройка сервера eu1 для Unified профиля

### Однократная настройка

1. Установить ipset:
   ```bash
   apt install -y ipset
   ```

2. Запустить скрипт настройки (см. `docs/scripts/setup-unified-iptables.sh.example`):
   ```bash
   sudo ./setup-unified-iptables.sh
   ```
   Это создаст ipset `unified_ss_dst` и одно правило iptables для 10.1.0.20–50.

3. Сохранить ipset и iptables правила:
   ```bash
   ipset save > /etc/ipset.unified.conf
   iptables-save > /etc/iptables.rules
   ```
   Настроить автовосстановление после перезагрузки (systemd unit или `/etc/network/if-up.d/`).

### Обновление списка IP (cron)

Скрипт `update-unified-ss-ips.sh` разрешает домены (ChatGPT и др.) и обновляет ipset `unified_ss_dst`.

Рекомендуется запускать по cron раз в час:
```bash
0 * * * * /opt/vpnservice/scripts/update-unified-ss-ips.sh
```

## Как этим пользоваться

### Для пользователей

1. Владелец добавляет пользователя: `/add_user @username` или `/add_user <telegram_id>`
2. Пользователь выбирает сервер: `/server` → выбирает сервер (для eu1 — тип профиля)
3. Пользователь получает конфиг: `/get_config`
4. Импортирует `.conf` в WireGuard на устройстве

### Для разработчика

1. **Обновление бота на Timeweb:**
   ```bash
   cd /opt/vpnservice
   git pull
   systemctl restart vpn-bot.service
   systemctl status vpn-bot.service
   ```

2. **Проверка логов:**
   ```bash
   journalctl -u vpn-bot.service -f
   ```

3. **Добавление новой переменной окружения:**
   - Обновить `env_vars.example.txt` в репозитории
   - **Вручную** добавить в `/opt/vpnservice/env_vars.txt` на сервере (файл не в Git)

## Важные правила

1. **Не ломать существующее:** Обычный VPN и VPN+GPT должны продолжать работать как раньше
2. **Unified — только добавление:** Новый пул IP (20–50), новые правила iptables, но не трогаем существующие
3. **Пул VPN+GPT:** Теперь исключает 20–50 (фактически 8–19 и 51–254)
4. **Без add-ss-redirect для Unified:** Редирект только через ipset, скрипт `add-ss-redirect.sh` не вызывается

## Ближайшие задачи (по желанию владельца)

- **Бот:** инструкции в боте охватывают ПК, iPhone/iPad и Android; AmneziaWG (Европа) — ПК, iOS (импорт через «Поделиться»), Android (импорт из файла/буфера).
- **Веб-панель:** развернуть на сервере (Timeweb или eu1), получить ссылку (сейчас ссылки нет), доработать под полный мониторинг (ноды, сервисы, подключения). URL зафиксировать в документации после деплоя.
- **Второй VPS:** отложено — без монетизации по бюджету не планируется.

**Бэкап:** конфиги/экспорты можно хранить в Git при **приватном** репозитории (docs/backup-restore.md).

## Документация

- **Обход блокировок РКН:** `docs/blocking-bypass-strategy.md` — стратегия, выбран AmneziaWG.
- **Пошаговый план:** `docs/step-by-step-plan-bypass.md` — выбран A (AmneziaWG).
- **Развёртывание AmneziaWG:** `docs/amneziawg-deploy-instruction.md` — пошагово для eu1 (ПК, iOS, Android).
- **Инструкция для пользователей (AmneziaWG):** `docs/client-instructions-amneziawg.md` — ПК, iOS (импорт через «Поделиться»), Android.
- **Инструкция для Android:** `docs/client-instructions-android.md` — WireGuard (Россия) и AmneziaVPN/AmneziaWG (Европа).
- **Спецификация Unified:** `docs/specs/spec-04-implementation-unified-profile.md`
- **Roadmap:** `ROADMAP_VPN.md`
- **Выполненные задачи:** `DONE_LIST_VPN.md`
- **Деплой:** `docs/deployment.md`
- **eu1: известные ограничения и что уже делалось:** `docs/eu1-status-known-issues.md` — не повторять одни и те же шаги диагностики.

## Откат Unified профиля

Если нужно откатить Unified:

1. Удалить правило iptables для 10.1.0.20–50
2. Удалить ipset `unified_ss_dst`
3. В боте перестать выдавать Unified (оставить только Обычный и VPN+GPT)

Существующие клиенты 10.1.0.8–19 и 51–254 (VPN+GPT) не затронуты.

## Известное ограничение: eu1 (Fornex) — трафик через VPN не выходит в интернет

**Факт (подтверждён в нескольких сессиях):** При включённом VPN на eu1 (профиль Unified или VPN+GPT) пинг до 8.8.8.8 даёт **100% потерь**, сайты не открываются. Туннель WireGuard поднимается (handshake есть, счётчики трафика растут), трафик форвардится на сервере (FORWARD), но доступа в интернет через VPN нет.

**Что уже делалось (не повторять по кругу):**
- На eu1 добавлены правила FORWARD в начало цепочки (до Docker): `wg0 → eth0` и `eth0 → wg0 ESTABLISHED,RELATED`.
- Добавлено правило INPUT: `ESTABLISHED,RELATED -j ACCEPT` в начало цепочки.
- POSTROUTING: есть MASQUERADE для eth0 (трафик из 10.1.0.0/24 теоретически матчится правилом 0.0.0.0/0).
- ss-redir слушает на 1081; ipset `unified_ss_dst` настроен.

**Вывод:** Проблема, по всей видимости, на стороне маршрута/провайдера (Fornex) или блокировок, а не только в локальных правилах iptables. Не предлагать повторную диагностику одних и тех же шагов (пинг, FORWARD, INPUT, MASQUERADE). Варианты для пользователя: использовать сервер **main** (Timeweb) или рассмотреть миграцию eu1 на другого хостинг-провайдера.

## Что сделано в боте (для справки)

- **`/server_exec`:** выполнение команд на сервере по SSH. Команда передаётся через stdin; кавычки из Telegram снимаются; PATH задаётся на сервере. Использовать для диагностики на eu1 без прямого SSH.
- **Смена типа профиля:** при выборе «Универсальный» в `/server` и вызове `/get_config` или `/regen` бот пересоздаёт peer с типом `unified` и IP из пула 10.1.0.20–50 (файл `_unified.conf`). Раньше выдавался старый профиль VPN+GPT (10.1.0.9, `_gpt.conf`) — исправлено через `replace_peer_with_profile_type()`.
- **Документация eu1:** в `docs/deployment.md` описаны FORWARD для wg0 (до Docker), правило INPUT ESTABLISHED,RELATED, запуск ss-redir через `shadowsocks-libev-redir@ss-wg.service` (не `@config`).

## Проблемы и решения

### eu1 (Fornex): UDP WireGuard не работает из России

**Проблема:** Клиенты из России не могут подключиться к eu1 по UDP 51820.

**Решение:** Использовать **AmneziaWG** на eu1 (развёрнут, из России работает). Или профиль VPN+GPT/Unified для тех, кто не из РФ. При блокировке AmneziaWG — добавить Xray в Amnezia (docs/blocking-bypass-strategy.md).

### eu1: туннель поднят, но пинг и сайты не работают

См. раздел **«Известное ограничение: eu1 (Fornex)»** выше. Не повторять одни и те же шаги диагностики.

### Несколько устройств: плохо работает интернет

**Проблема:** При подключении с двух устройств интернет работает плохо.

**Решение:** Использовать единый профиль Unified вместо разных профилей/серверов. См. `docs/troubleshooting-multiple-devices.md`.

## Контакты и ресурсы

- GitHub: `nikkronos/vpnservice`
- Сервер бота: Timeweb (81.200.146.32)
- Сервер eu1: Fornex (185.21.8.91)
