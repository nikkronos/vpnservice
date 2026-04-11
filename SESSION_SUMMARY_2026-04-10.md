# Резюме сессии 2026-04-10 — 2026-04-11 — MTProxy на Fornex, панель на Fornex, Timeweb выключен

## Контекст работы

После миграции Telegram-бота VPN на **Fornex** (см. `Main_docs/TELEGRAM_MIGRATION_TIMWEB_FORNEX_2026-04-10.md`) команда **`/proxy_rotate`** перестала работать: Docker не мог занять **хост 443** — порт занят **`xray.service`** (VLESS+REALITY). MTProxy Fake TLS (**`nineseconds/mtg:2`**, **`mtproxy-faketls`**) переведён на внешний порт **8444**; удалён старый контейнер **`mtproto-proxy`**.

Далее: перенос **веб-панели** (`/` мониторинг и **`/recovery`**) с **Timeweb** на **Fornex** (тот же `/opt/vpnservice`, что и бот), SSH **Fornex → main** для трафика WireGuard **rus1/rus2**, **`VPN_RECOVERY_URL`**, отключение **`vpn-web.service`** на Timeweb.

## Выполненные задачи

### Код `nikkronos/vpnservice` (ветка `main`)

1. **`bot/main.py`** — диагностика конфликта порта 443 при ротации; `env=environment_for_mtproxy_rotate(...)` для скрипта ротации.
2. **`bot/config.py`** — `environment_for_mtproxy_rotate()` (проброс **`MTPROXY_*`** из `env_vars.txt` в subprocess).
3. **`env_vars.example.txt`** — примеры **`MTPROXY_PORT`**, **`MTPROXY_PUBLIC_IP`**, **`WG_SSH_*`** (панель/бот не на main).
4. **`web/app.py`** — трафик **main**: при **`WG_SSH_HOST`** в `env_vars.txt` — `wg show … dump` по SSH; блок сервисов EU1: проверка **MTProxy** по порту из **`get_effective_mtproto_proxy_link`**.
5. **`docs/vpn-web-migration-fornex-plan.md`**, **`web/README.md`**, **`README_FOR_NEXT_AGENT.md`**, **`docs/deployment.md`**, **`docs/telegram-mtproxy-operators-guide.md`**, **`bot/config.py`** (дефолт **`vpn_recovery_url`**) — актуальные URL и прод Fornex (по мере коммитов).

### Прод Fornex (`185.21.8.91`, VPS `284854`)

- **`env_vars.txt`:** `MTPROXY_PORT=8444`, `MTPROXY_PUBLIC_IP=185.21.8.91`, актуальный **`MTPROTO_PROXY_LINK`**; **`WG_SSH_*`** к **main** (Timeweb) для панели; **`VPN_RECOVERY_URL=http://185.21.8.91:5001/recovery`**.
- Ключ **`/root/.ssh/id_ed25519_main`**, публичная часть в **`authorized_keys`** на Timeweb **root** (лишняя строка-плейсхолдер из `authorized_keys` удалена вручную).
- **`vpn-web.service`**: unit создан в `/etc/systemd/system/`, `enable --now`, порт **5001**, проверка `curl` → **200** на `/` и `/recovery`.
- **`vpn-bot.service`**: рестарты после правок `env_vars.txt`.

### Прод Timeweb (`81.200.146.32`)

- **`sudo systemctl disable --now vpn-web.service`** — панель на Timeweb **выключена**; порт **5001** не слушается.
- **main (WireGuard)** и каталог **`/opt/vpnservice`** на Timeweb по-прежнему используются как **нода RU** и для SSH с Fornex; бот на Timeweb для VPN **не** запускается (см. миграцию Telegram).

## Критические правила для следующего агента

1. **Панель и recovery:** прод — **`http://185.21.8.91:5001/`** и **`http://185.21.8.91:5001/recovery`** на Fornex; **`VPN_RECOVERY_URL`** в `env_vars.txt` должен совпадать. Старый **`http://81.200.146.32:5001/...`** не использовать (сервис на Timeweb отключён).
2. **Трафик rus1/rus2 на панели:** без **`WG_SSH_HOST` / `WG_SSH_USER` / `WG_SSH_KEY_PATH`** к main блок трафика на Fornex будет пустым (локального `wg0` нет).
3. **MTProxy:** внешний порт **8444**; **443** на eu1 занят Xray — не ставить `MTPROXY_PORT=443` без освобождения порта.
4. **`MTPROXY_*`** в `env_vars.txt` обязательны для скрипта ротации (после фикса в коде передаются в subprocess).
5. **Опционально доработать код:** `POST /api/recovery/telegram-proxy` перебирает **main/eu1** — при MTProxy только на Fornex кнопка «Восстановить Telegram» может сначала дёрнуть не тот хост; см. `docs/vpn-web-migration-fornex-plan.md` фаза 3.

## Ссылки

- План переноса (чеклист, история): **`docs/vpn-web-migration-fornex-plan.md`**
- Миграция Telegram: **`Main_docs/TELEGRAM_MIGRATION_TIMWEB_FORNEX_2026-04-10.md`**
