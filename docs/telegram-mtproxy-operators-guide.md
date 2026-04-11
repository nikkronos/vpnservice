# Telegram MTProxy (Fake TLS): руководство для владельца и агентов

Единая точка входа по смыслу: **одна актуальная ссылка `tg://proxy?...`**, которую получают пользователи через бота и через страницу восстановления. После смены секрета на сервере ссылка обновляется без ручного копирования в десять мест — при соблюдении приоритетов ниже.

---

## 1. Что развёрнуто

| Компонент | Где | Документ |
|-----------|-----|----------|
| MTProxy Fake TLS (`nineseconds/mtg:2`, контейнер `mtproxy-faketls`) | **Fornex eu1**, внешний порт **8444** (443 занят Xray) | [mtproxy-proxy-rotation.md](mtproxy-proxy-rotation.md), [SESSION_SUMMARY_2026-04-10.md](../SESSION_SUMMARY_2026-04-10.md) |
| Telegram-бот | Fornex: `/opt/vpnservice`, `vpn-bot.service` | [deployment.md](deployment.md) |
| Веб-панель + recovery | Fornex: порт **5001**, `vpn-web.service` | [deployment.md](deployment.md), [vpn-web-migration-fornex-plan.md](vpn-web-migration-fornex-plan.md) |

**Не путать:** «голый» MTProto на eu1 и **MTProxy Fake TLS** — разные вещи; статусы см. [README_FOR_NEXT_AGENT.md](../README_FOR_NEXT_AGENT.md) и [telegram-unblock-algorithm.md](telegram-unblock-algorithm.md).

---

## 2. Откуда берётся «актуальная» ссылка (один источник правды)

Функция `get_effective_mtproto_proxy_link()` в `bot/config.py`:

1. Если существует файл **`/opt/vpnservice/data/mtproto_proxy_link.txt`** и в нём строка, начинающаяся с `tg://proxy` — **используется она** (приоритет).
2. Иначе читается **`MTPROTO_PROXY_LINK`** из **`env_vars.txt` с диска** при каждом запросе (не закэшированное значение процесса), чтобы веб-панель не отдавала устаревшую ссылку после правки env.

Файл `data/mtproto_proxy_link.txt` **не в Git** (`.gitignore`), в репозиторий не коммитить.

---

## 3. Команды бота

| Команда | Кто | Действие |
|---------|-----|----------|
| **`/proxy`** | Любой зарегистрированный сценарий (как в коде бота) | Отправляет **текущую** `tg://proxy?...` + краткая инструкция из `docs/bot-instruction-texts/instruction_mtproto_short.txt`. |
| **`/proxy_rotate`** | **Только владелец** (`ADMIN_ID`) | Запускает скрипт `MTPROXY_ROTATE_SCRIPT` на том же хосте, что и бот; парсит из stdout `MTPROTO_LINK=tg://...` или строку `tg://proxy...`; пишет результат в `data/mtproto_proxy_link.txt`. Меняет секрет на сервере — **старые записи прокси в клиентах с прежним секретом перестают работать**; пользователи добавляют новую ссылку (можно второй строкой в списке прокси). |

Когда вызывать **`/proxy_rotate`**: при необходимости **сменить секрет** (компрометация, подозрение на блокировку, плановая ротация). Не как ежедневная рутина.

Подробности: [mtproxy-proxy-rotation.md](mtproxy-proxy-rotation.md).

---

## 4. Страница восстановления (без работающего Telegram)

- **URL:** `http://185.21.8.91:5001/recovery` (или значение `VPN_RECOVERY_URL` в `env_vars.txt` на сервере бота/панели).
- **Только ссылка, без рестарта Docker:** пользователь вводит **Telegram ID**, нажимает **«Показать актуальную ссылку»** (или при сохранённом ID в браузере ссылка подгрузится при открытии страницы). API **`GET /api/recovery/proxy-link?telegram_id=...`** — та же проверка пользователя в `users.json`, что и у POST; ответ: **`mtproto_proxy_link`** + **`hint`** (источник ссылки — как у `/proxy`: override-файл или env).
- **Рестарт контейнера + ссылка (как раньше):** кнопка «Восстановить Telegram» → **`POST /api/recovery/telegram-proxy`**: перезапуск Docker-контейнера прокси на подходящей ноде (main/eu1); в ответе **`mtproto_proxy_link`** и **`hint`** (в т.ч. при ошибке рестарта, HTTP 502).
- Отдельно на той же странице: восстановление VPN AmneziaWG для слотов **EU1** и **EU2** (`POST /api/recovery/vpn` с `server_id`).

Реализация: `web/app.py`, `web/static/recovery.js`, `web/templates/recovery.html`.

---

## 5. Переменные окружения (сервер бота)

В **`/opt/vpnservice/env_vars.txt`** (не в Git):

| Переменная | Назначение |
|------------|------------|
| `MTPROTO_PROXY_LINK` | Fallback-ссылка `tg://proxy?...`, если нет `data/mtproto_proxy_link.txt`. После ротации имеет смысл периодически **синхронизировать** с актуальной ссылкой (или полагаться только на override-файл). |
| `MTPROXY_ROTATE_SCRIPT` | Путь к исполняемому скрипту ротации, например `/opt/vpnservice/scripts/mtproxy-faketls-rotate.sh`. |
| `MTPROXY_PUBLIC_IP` и др. | Опционально для скрипта (см. пример в `docs/scripts/mtproxy-faketls-rotate.sh.example`). |

---

## 6. Деплой кода и зависимостей (Fornex, прод)

- Репозиторий: **`nikkronos/vpnservice`**, каталог на сервере: **`/opt/vpnservice`** (бот и панель на одном хосте).
- После `git pull` зависимости Python ставить **только из venv** (Ubuntu 24+, PEP 668):

```bash
/opt/vpnservice/venv/bin/pip install -r requirements.txt
/opt/vpnservice/venv/bin/pip install -r web/requirements.txt
```

- Перезапуск: `sudo systemctl restart vpn-bot.service` и/или `sudo systemctl restart vpn-web.service`.

Полный чеклист: [deployment.md](deployment.md) (разделы «Обновление бота», «Обновление панели»).

---

## 7. Веб-панель на другом хосте, чем бот (редкий случай)

**Прод (2026-04-11):** бот и панель на **одном** Fornex — общий `env_vars.txt` и `data/`. Если когда-нибудь снова вынесешь панель на отдельный VPS: на машине панели не будет `data/mtproto_proxy_link.txt` — обновляй **`MTPROTO_PROXY_LINK`** в её `env_vars.txt` или синхронизируй override-файл с сервера бота. См. [mtproxy-proxy-rotation.md](mtproxy-proxy-rotation.md).

---

## 8. Сторонние альтернативы (не официальный стек)

Справочно: [telegram-proxy-alternatives.md](telegram-proxy-alternatives.md).

---

## 9. Связанные коммиты и записи

- История задач: `DONE_LIST_VPN.md` (записи от 2026-03-30 про ротацию, recovery, pip).
- Резюме сессии: `SESSION_SUMMARY_2026-03-30.md`.
