# План: перенос веб-панели и `/recovery` с Timeweb на Fornex

**Текущее состояние (2026-04-10):**

- **Бот** `vpn-bot.service`: прод на **Fornex** (`/opt/vpnservice`).
- **MTProxy Fake TLS** (`mtproxy-faketls`): на **Fornex**, внешний порт **8444** (внутри контейнера 443).
- **Веб-панель** `vpn-web.service` и страница **[recovery](http://81.200.146.32:5001/recovery)**: по документации и URL — **Timeweb** (`81.200.146.32:5001`).

Цель переноса: чтобы пользователи при недоступности Telegram открывали recovery на том же регионе/хосте, что и бот (Fornex), и чтобы панель видела те же `env_vars.txt` / `data/`, что и бот (упрощается синхронизация **`MTPROTO_PROXY_LINK`** и **`data/mtproto_proxy_link.txt`**).

---

## Фаза 0 — Решения до работ

- [ ] Подтвердить **целевой URL**: только IP+порт (`http://185.21.8.91:5001/recovery`) или позже домен + HTTPS (отдельная задача).
- [ ] Решить судьбу панели на **Timeweb**: оставить редирект/заглушку, выключить сервис, или удалить после переноса.
- [ ] Убедиться, что на **Fornex** есть **тот же код** `vpnservice`, venv и зависимости панели (`web/requirements.txt`), что и для бота.

---

## Фаза 1 — Развёртывание `vpn-web` на Fornex

- [ ] Скопировать/синхронизировать каталог проекта (или `git clone` / `git pull`) в `/opt/vpnservice` — уже есть для бота; панель запускается из того же дерева.
- [ ] Установить зависимости панели в **тот же venv**, что у бота (PEP 668):
  ```bash
  /opt/vpnservice/venv/bin/pip install -r /opt/vpnservice/web/requirements.txt
  ```
- [ ] Создать или скопировать **unit** `vpn-web.service` на Fornex. В репозитории: **`web/vpn-web.service.example`** (`WorkingDirectory=/opt/vpnservice`, `PORT=5001`, `ExecStart=.../venv/bin/python web/app.py`). Сверить с Timeweb:
  ```bash
  # на Timeweb
  systemctl cat vpn-web.service
  ```
- [ ] **SSH с Fornex на main (Timeweb)** для блока «трафик» по **rus1/rus2**: в `env_vars.txt` на Fornex задать **`WG_SSH_HOST`**, **`WG_SSH_USER`**, **`WG_SSH_KEY_PATH`** (приватный ключ только на Fornex; в `authorized_keys` на main — публичная часть). Без этого панель на Fornex не сможет выполнить `wg show wg0 dump` на Timeweb — см. `web/app.py` (`_get_wg_transfer_for_server`).
- [ ] Открыть порт **5001/tcp** в firewall Fornex (ufw/панель провайдера), если доступ нужен с интернета (**и главная** `http://…:5001/`, и `/recovery`).
- [ ] Запуск: `systemctl enable --now vpn-web.service`, проверка `curl -sS http://127.0.0.1:5001/recovery | head` и `curl -sS http://127.0.0.1:5001/ | head`.
- [ ] Проверка с внешнего IP: `http://185.21.8.91:5001/` и `http://185.21.8.91:5001/recovery` (замени IP, если изменится).

---

## Фаза 2 — Конфигурация и согласованность с ботом

- [ ] На Fornex в **`/opt/vpnservice/env_vars.txt`** выставить **`VPN_RECOVERY_URL`** на новый адрес, например:
  ```bash
  VPN_RECOVERY_URL=http://185.21.8.91:5001/recovery
  ```
- [ ] Убедиться, что **`MTPROTO_PROXY_LINK`** и при необходимости файл **`data/mtproto_proxy_link.txt`** на Fornex актуальны (после `/proxy_rotate` бот уже пишет override локально).
- [ ] Перезапуск после правок: `systemctl restart vpn-bot.service` и `systemctl restart vpn-web.service` (если панель кэширует пути — по факту код читает env с диска; перезапуск безопасен).
- [ ] Обновить **тексты бота** (`/start`, `/help`), если там захардкожен старый URL — сейчас часто используется `VPN_RECOVERY_URL` из конфига; проверить в `bot/main.py`.

---

## Фаза 3 — SSH, recovery API и ноды

Панель для мониторинга и recovery может ходить по **SSH** на **main** и **eu1** (ключи, `WG_EU1_SSH_*` и т.д. в `env_vars.txt`).

- [ ] На **Fornex** разместить **те же SSH-ключи** и пути, что ожидает `web/app.py` (например ключ к eu1 — локальный на Fornex уже используется ботом; ключ к **main** Timeweb — если панель рестартует прокси на `main`, ключ должен быть на машине панели).
- [ ] Прогнать сценарии:
  - [ ] `GET /api/recovery/proxy-link?telegram_id=...` — ссылка совпадает с `/proxy` в боте.
  - [ ] `POST /api/recovery/telegram-proxy` — осознанно: сейчас MTProxy на **Fornex**, не на main; если код всё ещё таргетит `main` для рестарта контейнера — **обновить логику** или отключить кнопку «Восстановить Telegram» на рестарт, оставив только «показать ссылку» (иначе рестарт на Timeweb не тронет Fornex-контейнер).
- [ ] `POST /api/recovery/vpn` для EU1/EU2 — проверить выдачу конфига с Fornex-панели.

**Важно:** после переноса MTProxy на **eu1** кнопка recovery «перезапустить контейнер прокси», если она жёстко привязана к **server_id=main**, станет вводящей в заблуждение. Имеет смысл в отдельной задаче привести `web/app.py` в соответствие с фактическим хостом **`mtproxy-faketls`** (Fornex).

---

## Фаза 4 — DNS, HTTPS (опционально)

- [ ] При желании: домен на IP Fornex, reverse-proxy (caddy/nginx) и TLS для `https://vpn.example/recovery`.
- [ ] Обновить **`VPN_RECOVERY_URL`** и ссылки в документации.

---

## Фаза 5 — Отключение старого инстанса на Timeweb

- [ ] После стабильной работы на Fornex: на Timeweb `systemctl disable --now vpn-web.service`.
- [ ] Опционально: редирект с `http://81.200.146.32:5001/recovery` на новый URL (если оставляешь лёгкий nginx/curl на старом IP).

---

## Фаза 6 — Документация в репозитории

- [ ] Обновить `README_FOR_NEXT_AGENT.md`, `docs/deployment.md`, `docs/telegram-mtproxy-operators-guide.md` — новый URL recovery и расположение `vpn-web`.
- [ ] При необходимости — строка в `Main_docs/TELEGRAM_MIGRATION_TIMWEB_FORNEX_2026-04-10.md` или `Main_docs/PROJECTS.md`.

---

## Критерий готовности

- Пользователь с рабочим Telegram ID открывает **`http://<Fornex>:5001/recovery`**, получает ту же **`tg://proxy`**, что и **`/proxy`** в боте.
- Выдача VPN recovery (EU1/EU2) работает с панели на Fornex.
- Старый URL на Timeweb либо отключён, либо ведёт на новый адрес.
