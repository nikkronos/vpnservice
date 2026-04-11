# Резюме сессии 2026-04-10 — MTProxy на Fornex, `/proxy_rotate`, код бота

## Контекст работы

После миграции Telegram-бота VPN на **Fornex** (см. `Main_docs/TELEGRAM_MIGRATION_TIMWEB_FORNEX_2026-04-10.md`) команда **`/proxy_rotate`** перестала работать: скрипт ротации поднимал Docker с пробросом **`0.0.0.0:443`**, но порт **443** на хосте **eu1 (185.21.8.91)** уже занят **`xray.service`** (VLESS+REALITY). Ошибка Docker: `failed to bind host port ... 443/tcp: address already in use`. Код выхода скрипта **125**, бот сообщал «новую ссылку разобрать не удалось».

Принцип: **не трогать** работающий основной стек (**Xray на 443/4443**, **AmneziaWG**). MTProxy Fake TLS (**`nineseconds/mtg:2`**, контейнер **`mtproxy-faketls`**) вынесен на **внешний порт хоста 8444** (порт **8443** был занят старым контейнером **`mtproto-proxy`**; **8444** был свободен по `ss`).

## Выполненные задачи в этой сессии

### Код репозитория `nikkronos/vpnservice` (коммит на `main`)

1. **`bot/main.py`**
   - Сообщение об ошибке ротации: если в выводе скрипта признаки конфликта порта **443**, бот явно пишет, что это **занятость порта**, а не сбой парсинга ссылки, и подсказывает команды диагностики (`docker ps`, `ss`).
2. **`bot/config.py`**
   - Функция **`environment_for_mtproxy_rotate()`**: при запуске скрипта ротации в **`subprocess`** передаётся окружение **`os.environ` + все переменные `MTPROXY_*` из `env_vars.txt`**. Раньше переменные вроде **`MTPROXY_PORT`** в файле **не попадали** в bash-скрипт.
3. **`env_vars.example.txt`**
   - Закомментированные примеры **`MTPROXY_PORT`**, **`MTPROXY_PUBLIC_IP`** для случая «Xray уже на 443».

### Прод на Fornex (оператор, не в Git)

- В **`/opt/vpnservice/env_vars.txt`**: **`MTPROXY_PORT=8444`**, **`MTPROXY_PUBLIC_IP=185.21.8.91`** (убран дублирующий старый **`MTPROXY_PUBLIC_IP=81.200.146.32`**); обновлён **`MTPROTO_PROXY_LINK`** на актуальную ссылку после успешной ротации (**`port=8444`**, новый секрет).
- **`git pull origin main`** в `/opt/vpnservice`, **`systemctl restart vpn-bot.service`**.
- Успешная проверка в Telegram: **`/proxy_rotate`** → вторая строка с **`tg://proxy?server=185.21.8.91&port=8444&secret=...`**.
- **`docker ps`**: **`mtproxy-faketls`** — **`0.0.0.0:8444->443/tcp`**.
- Удалён неиспользуемый контейнер **`mtproto-proxy`** (освобождён хост-порт **8443**).

## Важные изменения в коде (файлы)

- `bot/main.py` — диагностика порта + `env=` для ротации.
- `bot/config.py` — `environment_for_mtproxy_rotate`.
- `env_vars.example.txt` — пример переменных Fornex+Xray.

## Критические правила для следующего агента

1. На **одном хосте** нельзя одновременно слушать **TCP 443** и **`docker -p 443:443`** для MTProxy, если **443** уже занят (**Xray**, **nginx** и т.д.). Либо другой **внешний** порт (**`MTPROXY_PORT`**), либо MTProxy на другом сервере.
2. Переменные **`MTPROXY_*`** для скрипта ротации должны быть в **`env_vars.txt`** на машине бота (после обновления кода они **пробрасываются** в subprocess); только **`systemd` Environment=** не обязателен.
3. **`MTPROTO_PROXY_LINK`** в `env_vars.txt` нужно периодически **синхронизировать** с фактической ссылкой (или полагаться на **`data/mtproto_proxy_link.txt`** после `/proxy_rotate`), иначе расходится fallback с панелью/recovery на **другом** хосте.
4. **Веб-панель и `/recovery`** по-прежнему на **Timeweb** (`http://81.200.146.32:5001/recovery`). Перенос на Fornex — отдельный план: **`docs/vpn-web-migration-fornex-plan.md`**.

## Не сделано в этой сессии (следующие шаги)

- Перенос **`vpn-web.service`** и URL **`VPN_RECOVERY_URL`** на Fornex — см. чеклист в **`docs/vpn-web-migration-fornex-plan.md`**.

## Дополнение (та же сессия) — подготовка переноса панели `/` + `/recovery`

- **`web/app.py`:** трафик WireGuard для **main (rus1/rus2)** — если в `env_vars.txt` задан **`WG_SSH_HOST`**, панель читает `wg show … dump` **по SSH на main** (иначе на Fornex локального `wg0` нет). Блок сервисов EU1: проверка **MTProxy** по **TCP-порту из актуальной ссылки** (`get_effective_mtproto_proxy_link`), а не жёстко 443.
- **`env_vars.example.txt`:** пример **`WG_SSH_*`** для панели/бота не на Timeweb.
- **`docs/vpn-web-migration-fornex-plan.md`**, **`web/README.md`**, **`README_FOR_NEXT_AGENT.md`:** явно главная **`http://…:5001/`** и **`/recovery`**, шаги SSH для трафика main.
