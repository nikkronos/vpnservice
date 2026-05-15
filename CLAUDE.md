# CLAUDE.md — VPN Service

Репозиторий: `nikkronos/vpnservice` | Путь: `Projects/VPN/`

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

## Инфраструктура (май 2026)

| Сервер | IP | Что на нём |
|--------|-----|-----------|
| **Fornex eu1** (основной) | `185.21.8.91` | Бот, веб-панель, AmneziaWG Docker, MTProxy Fake TLS, Xray VLESS+WS |
| **Timeweb main** (RU) | `81.200.146.32` | WireGuard сервер (wg0, порт 51820/UDP) |
| **Yandex Cloud** (LTE резерв) | `158.160.236.147` | Xray VLESS+REALITY xHTTP (порт 443, SNI: www.yandex.ru) |

**SSH:** `ssh fornex` (алиас) или `ssh -i ~/.ssh/id_ed25519_fornex root@185.21.8.91`

### Сервисы на Fornex

| Сервис | Команда | Порт/адрес |
|--------|---------|-----------|
| Telegram-бот | `vpn-bot.service` | — |
| Веб-панель | `vpn-web.service` | `:5001` |
| AmneziaWG (Docker) | контейнер `amnezia-awg2` | `39580/UDP` |
| MTProxy Fake TLS | контейнер `mtproxy-faketls` | `8444/TCP` |
| Xray VLESS+WS | `xray.service` | `80/TCP` (CDN через `sub.vpnnkrns.ru`) |

---

## Что работает / что нет

| Технология | Статус | Где |
|------------|--------|-----|
| WireGuard | ✅ Работает | main (Timeweb) — Россия |
| AmneziaWG | ✅ Работает | eu1 Docker `amnezia-awg2` — Европа |
| VLESS+WS+Cloudflare CDN | ✅ Обычные блокировки | `sub.vpnnkrns.ru:443` |
| VLESS+REALITY xHTTP | ✅ LTE whitelist-режим | Yandex Cloud `158.160.236.147:443` |
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
```

### Ключевые концепции

- **server_id:** `eu1` (AmneziaWG, Docker), логически был `eu2` — нормализован в `eu1` через `storage.py`
- **peer key формат:** `{telegram_id}:{server_id}:{platform}` (в peers.json)
- **Платформы:** `pc`, `ios`, `android` — Android получает `vpn://` deep link, iOS/PC — `.conf` файл
- **Admin auth:** `ADMIN_SECRET` (64-char hex) — для `/api/users`, `/api/traffic`
- **Recovery auth:** `RECOVERY_SECRET` — для legacy recovery endpoints

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
- **Recovery:** `http://185.21.8.91:5001/recovery` — восстановление VPN-конфига EU1, ссылка MTProxy, восстановление Telegram

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
```

---

## Важные правила

1. **Timeweb (main) не трогать** — там всё работает, прямой доступ аккуратно
2. **eu1 = Docker** — AmneziaWG в `amnezia-awg2`, команды через `docker exec`
3. **Подсеть eu1 = 10.8.1.0/24**, порт = 39580 (не 51820, не 10.1.0.0/24)
4. **MTProxy на eu1 — только Fake TLS** (порт 8444). Голый MTProto не использовать
5. **Не пушить сломанный код** — проверь diff перед commit
6. **env_vars.txt не коммитить никогда**
7. **После изменений:** `git add` → `git commit` → `git push` (push обязателен)

---

## Документация

| Нужно | Читай |
|-------|-------|
| Открытые задачи | `ROADMAP_VPN.md` |
| История изменений | `DONE_LIST_VPN.md` |
| Последняя сессия | `docs/sessions/SESSION_SUMMARY_2026-05-15.md` |
| Деплой чеклист | `docs/deployment.md` |
| MTProxy операции | `docs/telegram-mtproxy-operators-guide.md` |
| Yandex Cloud REALITY | `docs/yandex-cloud-reality-setup.md` |
| Бэкап/восстановление | `docs/backup-restore.md` |
| Стратегия обхода блокировок | `docs/blocking-bypass-strategy.md` |
| Конкуренты | `docs/competitors-analysis.md` |

Старые сессии (Feb–Mar 2026): `docs/sessions/old/` — история, не читать для работы.
Устаревшие доки: `docs/archive/` — не актуальны.
