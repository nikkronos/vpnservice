# План: перенос веб-панели и `/recovery` с Timeweb на Fornex

## Статус после миграции (2026-04-11) — выполнено

**Прод сейчас:**

| Компонент | Хост | Примечание |
|-----------|------|------------|
| **`vpn-bot.service`** | Fornex (`185.21.8.91`), `/opt/vpnservice` | С 2026-04-10 |
| **`vpn-web.service`** | Fornex, порт **5001** | Главная **`/`** и **`/recovery`** |
| **URL панели** | `http://185.21.8.91:5001/` | Мониторинг |
| **URL recovery** | `http://185.21.8.91:5001/recovery` | В `env_vars.txt`: **`VPN_RECOVERY_URL`** |
| **Трафик rus1/rus2 на панели** | SSH Fornex → main | **`WG_SSH_HOST`**, **`WG_SSH_USER`**, **`WG_SSH_KEY_PATH`** в `env_vars.txt` |
| **`vpn-web` на Timeweb** | — | **`systemctl disable --now`**, порт 5001 не слушается |

Детали сессии: **`SESSION_SUMMARY_2026-04-10.md`** (объединённое резюме 10–11.04), **`DONE_LIST_VPN.md`**.

---

## Фаза 0 — Решения до работ

- [x] Целевой URL: **`http://185.21.8.91:5001/`** и **`/recovery`** (IP eu1 Fornex).
- [x] Панель на Timeweb: **отключена** после стабилизации на Fornex.
- [x] Код и venv на Fornex: `git pull`, `venv/bin/pip install -r web/requirements.txt`.

---

## Фаза 1 — Развёртывание `vpn-web` на Fornex

- [x] Проект в `/opt/vpnservice` (общий с ботом).
- [x] Зависимости панели в venv.
- [x] Unit **`/etc/systemd/system/vpn-web.service`** (по образцу **`web/vpn-web.service.example`**): `PORT=5001`, `ExecStart=.../venv/bin/python web/app.py`.
- [x] SSH **Fornex → main** для `wg show` (переменные **`WG_SSH_*`**).
- [x] Firewall **5001/tcp** (по необходимости у провайдера/ufw).
- [x] `systemctl enable --now vpn-web.service`, проверка `curl` localhost **200** на `/` и `/recovery`.

---

## Фаза 2 — Конфигурация и согласованность с ботом

- [x] **`VPN_RECOVERY_URL=http://185.21.8.91:5001/recovery`** в `env_vars.txt`.
- [x] **`MTPROTO_PROXY_LINK`** / override синхронизированы с `/proxy`.
- [x] Рестарт **`vpn-bot`** и **`vpn-web`** после правок env.
- [x] Fallback URL в коде обновлён: **`bot/config.py`**, **`bot/main.py`** (дефолт recovery).

---

## Фаза 3 — SSH, recovery API и ноды

- [x] Ключи на Fornex: **`WG_EU1_SSH_*`**, **`WG_SSH_*`** к main; recovery **VPN** (EU1/EU2) с Fornex-панели работает.
- [x] **`GET /api/recovery/proxy-link`** — та же ссылка, что `/proxy`.
- [ ] **Улучшение (отложено):** `POST /api/recovery/telegram-proxy` перебирает **main/eu1**; при MTProxy только на Fornex порядок попыток может быть запутанным — при необходимости сузить до **eu1** или определять из IP в ссылке (см. `_determine_target_server_id_from_env` в `web/app.py`).

---

## Фаза 4 — DNS, HTTPS (опционально)

- [ ] Домен, reverse-proxy, TLS для панели на Fornex.

---

## Фаза 5 — Отключение старого инстанса на Timeweb

- [x] **`sudo systemctl disable --now vpn-web.service`** на Timeweb (`81.200.146.32`).
- [ ] Опционально: редирект со старого URL (если когда-нибудь поднимут лёгкий nginx на Timeweb).

---

## Фаза 6 — Документация в репозитории

- [x] Обновлены **`README_FOR_NEXT_AGENT.md`**, **`docs/deployment.md`**, **`docs/telegram-mtproxy-operators-guide.md`**, **`SESSION_SUMMARY`**, **`DONE_LIST`**, **`ROADMAP`**, **`Main_docs`**, **`docs/server-timeweb.md`** (по мере коммита в `Cursor_Projects` / `vpnservice`).

---

## Критерий готовности — достигнут

- Пользователь открывает **`http://185.21.8.91:5001/recovery`**, получает актуальную **`tg://proxy`** (как **`/proxy`** в боте).
- Панель **`/`** на Fornex отвечает **200**.
- Старый инстанс **`vpn-web`** на Timeweb отключён.
