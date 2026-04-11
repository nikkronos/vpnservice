# DONE_LIST_VPN — выполненные задачи VPN/Proxy проекта

## 2026-04-11 — Документация и код: пост-миграция бота на Fornex (Россия `/get_config`, EU `/regen`, SSH)

- **Контекст:** бот на Fornex; Россия (rus1) — WireGuard остаётся на **main** (Timeweb). В проде выявлено: на Fornex не было **`wireguard-tools`** → в логах `FileNotFoundError: 'wg'`, пользователь не получал ответ на `/get_config` для России. Второй кейс: в `env_vars.txt` был путь **`WG_EU1_SSH_KEY_PATH=/root/.ssh/id_ed25519_eu1`**, файла ключа на новом VPS не было → `/regen` AmneziaWG (в т.ч. слот eu2) — ошибка SSH до eu1.
- **Операции на проде (зафиксировано для повторения):** `apt install -y wireguard-tools`; `ssh-keygen` для `id_ed25519_eu1` + добавление `.pub` в `authorized_keys` на EU; `systemctl restart vpn-bot`; проверка `ssh -i ... root@185.21.8.91 "echo OK"`.
- **Репозиторий:** **`docs/deployment.md`** — раздел «Бот (Telegram)» переименован с устаревшего «Timeweb»; добавлен **чеклист хоста бота после переноса на Fornex** (wg, WG_SSH_*, WG_EU1_SSH_KEY_PATH, eu2 vs SSH); правка примера `WG_EU1_SSH_KEY_PATH` в блоке env; MTProxy — правка «сервер бота» вместо только Timeweb. **`env_vars.example.txt`** — комментарий про ключ на хосте бота. **`README_FOR_NEXT_AGENT.md`** — путь к `env_vars.txt` и ссылка на чеклист. **`bot/wireguard_peers.py`** — при отсутствии `wg` поднимается понятный `WireGuardError` с текстом про `apt install wireguard-tools`; сообщение об ошибке SSH к eu1 без упоминания Timeweb, с шагами после переноса VPS.
- **Сессия:** **`SESSION_SUMMARY_2026-04-11.md`**.

## 2026-04-11 — `vpn-web` и `/recovery` на Fornex; отключение панели на Timeweb

- **Цель:** одна площадка с ботом — мониторинг **`http://185.21.8.91:5001/`** и **`/recovery`** на Fornex; **`VPN_RECOVERY_URL`** в `env_vars.txt`; трафик **main** на панели через **`WG_SSH_*`** (ключ `id_ed25519_main`, `authorized_keys` на Timeweb).
- **Systemd Fornex:** создан и включён **`vpn-web.service`** (`PORT=5001`), проверка `curl` → 200.
- **Timeweb:** **`systemctl disable --now vpn-web.service`**, порт 5001 не слушается.
- **Код/доки (репозиторий):** дефолт **`vpn_recovery_url`** и fallback в **`bot/main.py`**, **`bot/config.py`**; **`docs/deployment.md`**, **`docs/telegram-mtproxy-operators-guide.md`**, **`docs/vpn-web-migration-fornex-plan.md`** (статус «выполнено»), **`SESSION_SUMMARY_2026-04-10.md`**, **`README_FOR_NEXT_AGENT.md`**.

## 2026-04-10 — MTProxy Fake TLS на Fornex (порт 8444), починка `/proxy_rotate`, проброс `MTPROXY_*` в subprocess

- **Контекст:** после переноса бота на Fornex ротация MTProxy падала: Docker не мог занять **хост 443** — порт занят **`xray.service`** (REALITY). Принцип: не менять Xray/AmneziaWG; внешний порт MTProxy — **8444** (свободен; **8443** был у старого `mtproto-proxy`).
- **Код (репозиторий, `main`):** `bot/main.py` — понятное сообщение при конфликте порта 443; `subprocess.run(..., env=environment_for_mtproxy_rotate(...))`. `bot/config.py` — `environment_for_mtproxy_rotate()`: `os.environ` + все **`MTPROXY_*`** из `env_vars.txt`. `env_vars.example.txt` — пример `MTPROXY_PORT` / `MTPROXY_PUBLIC_IP`.
- **Прод Fornex:** `env_vars.txt` — `MTPROXY_PORT=8444`, `MTPROXY_PUBLIC_IP=185.21.8.91`, обновлён `MTPROTO_PROXY_LINK` после ротации; `git pull`, `systemctl restart vpn-bot`; контейнер **`mtproxy-faketls`** — `8444->443`; удалён **`mtproto-proxy`**.
- **Документы:** `SESSION_SUMMARY_2026-04-10.md`; план переноса панели/recovery на Fornex — `docs/vpn-web-migration-fornex-plan.md`.
- **Код (перенос панели):** `web/app.py` — трафик **main** через SSH при наличии `WG_SSH_HOST`; проверка MTProxy по порту из ссылки `/proxy`. `env_vars.example.txt` — `WG_SSH_*`; обновлены `docs/vpn-web-migration-fornex-plan.md`, `web/README.md`, `README_FOR_NEXT_AGENT.md` (главная `/` и `/recovery`).

## 2026-04-02 — Логические слоты rus1 / rus2 / eu1 / eu2 + recovery EU1+EU2 + ссылка прокси без рестарта

- **Цель:** четыре именованных слота профилей VPN; отдельные peers в `peers.json`; Европа — два AmneziaWG-слота на одном EU-хосте; на странице `/recovery` — два блока выдачи конфига (EU1 и EU2). Имена файлов конфигов включают `server_id` (например `..._eu1_amneziawg.conf`).
- **`bot/storage.py`:** ключи пиров `"{telegram_id}:{server_id}"`; миграция со старого формата: единственный peer без суффикса → слот **`rus1`** (legacy `main` в логах/каноне — см. `canonical_env_server_id`).
- **`bot/wireguard_peers.py`:** `canonical_env_server_id` — rus1/rus2 → физическая нода **main**, eu1/eu2 → **eu1** (env/SSH); общий пул IP для rus1+rus2 и отдельно для eu1+eu2 (Amnezia); `get_available_servers()` возвращает четыре слота; Amnezia create/regen с параметром `server_id` в `eu1`|`eu2`.
- **`bot/main.py`:** `/get_config`, `/regen`, `/server`, `/status` работают с нормализованными `rus1`/`rus2`/`eu1`/`eu2`; WireGuard-классика для RU-слотов, Amnezia — для EU-слотов.
- **`web/app.py`:** `POST /api/recovery/vpn` — только Amnezia (`server_id`: eu1|eu2), без перезаписи «чужого» слота через preferred_server. `api_servers` / `api_services` / `_get_wg_transfer_for_server` используют канонический id ноды для ping и SSH. **`GET /api/recovery/proxy-link?telegram_id=...`** — та же проверка пользователя, что у `telegram-proxy`, отдаёт актуальный `tg://` как `/proxy`, **без** перезапуска Docker.
- **Веб recovery:** `recovery.html` / `recovery.js` — два блока VPN (EU1, EU2); блок «Текущая ссылка MTProxy» + кнопка «Показать актуальную ссылку» и «Копировать»; при наличии сохранённого Telegram ID в `localStorage` ссылка подгружается при открытии страницы.
- **Деплой:** юнит бота на сервере — **`vpn-bot.service`** (не `vpnservice-bot.service`); после `git pull`: `sudo systemctl restart vpn-bot.service` и при необходимости `vpn-web.service`.

## 2026-04-02 (дополнение) — Spec-08: без нового VPS

- Решение владельца: **второй VPS не оплачивается.** Спека **spec-08** переписана: основной сценарий **B** — только **main + eu1** (несколько способов: WG, AmneziaWG, `/mobile_vpn`, `/proxy`; опц. REALITY на **main**, домен для MTProxy). Сценарий **A** (RU2/EU2 на отдельном VPS) оставлен как опция при появлении бюджета. Обновлены `ROADMAP_VPN.md`, `blocking-bypass-strategy.md`, `README_FOR_NEXT_AGENT.md`, `third-party-vpn-boosters-vs-multi-entry.md`.

## 2026-04-02 — Спека вторая нода (RU2/EU2), документ про GearUp/мульти-вход

- **`docs/specs/spec-08-multi-node-redundancy-ru2-eu2.md`** — первоначально план EU2/RU2; затем уточнение «без второго VPS» — см. дополнение выше.
- **`docs/third-party-vpn-boosters-vs-multi-entry.md`** — что такое GearUp-подобные приложения, чем наш мульти-вход аналогичен и чем клонировать их продукт нецелесообразно.
- **`docs/blocking-bypass-strategy.md`** — ссылка на spec-08 в блоке MVP; связанные документы дополнены.
- **`ROADMAP_VPN.md`** — раздел «Второй/резервный сервер» переписан под spec-08 и актуальный приоритет.
- **`README_FOR_NEXT_AGENT.md`** — ссылки на spec-08 и third-party doc.

## 2026-03-30 — Сводная документация MTProxy + обновление README

- **`docs/telegram-mtproxy-operators-guide.md`** — единое руководство: `/proxy`, `/proxy_rotate`, recovery, `get_effective_mtproto_proxy_link`, env, деплой через venv-pip, ссылка на альтернативы.
- **`README_FOR_NEXT_AGENT.md`:** команды `/proxy` и `/proxy_rotate`, URL recovery, правило №5 приведено к текущему коду; раздел «Документация» дополнен ссылками.
- **`SESSION_SUMMARY_2026-03-30.md`:** дополнение с итогами по MTProxy/recovery/документации pip.

## 2026-03-30 — Деплой: явный путь к pip в venv (PEP 668 на Ubuntu 24+)

- **`docs/deployment.md`:** установка зависимостей бота и панели через `/opt/vpnservice/venv/bin/pip` (не системный `pip`); блок «Обновление бота» — опциональный `pip install -r requirements.txt` при смене зависимостей; «Обновление панели» — тот же путь к pip; примечание про перезапуск `vpn-bot` при общих изменениях в `bot/`.
- **`docs/specs/spec-06-web-panel-deploy-and-traffic.md`**, **`web/README.md`:** согласованы команды с venv-pip.

## 2026-03-30 — Ротация MTProxy: /proxy_rotate, override-файл, документация

- **Цель:** «обновляемая» ссылка на MTProxy Fake TLS без ручного копирования в `env` при каждой смене секрета; пользователи по-прежнему получают актуальный `tg://` через `/proxy`.
- **Код бота:** `get_effective_mtproto_proxy_link()` в `bot/config.py` — приоритет `data/mtproto_proxy_link.txt` над `MTPROTO_PROXY_LINK`; fallback читает `env_vars.txt` с диска при каждом вызове; команда `/proxy_rotate` (только владелец) запускает `MTPROXY_ROTATE_SCRIPT`, парсит `MTPROTO_LINK=...`, пишет override; `/proxy` вызывает `load_config()` + эффективная ссылка.
- **Web:** `web/app.py` — recovery `telegram-proxy` использует эффективную ссылку для определения IP хоста; в JSON-ответ добавлены `mtproto_proxy_link` и `hint` (та же ссылка, что `/proxy`; при ошибке перезапуска контейнера ссылка всё равно отдаётся). `recovery.js` / `recovery.html` — понятный вывод ссылки пользователю.
- **Репозиторий:** `.gitignore` — `data/mtproto_proxy_link.txt`; `data/.gitkeep`; `env_vars.example.txt` — `MTPROXY_ROTATE_SCRIPT`.
- **Документация:** `docs/mtproxy-proxy-rotation.md`; `docs/scripts/mtproxy-faketls-rotate.sh.example`; ссылка из `docs/mtproxy-faketls-deploy.md`.

## 2026-03-30 — README: MTProxy Fake TLS vs «голый» MTProto; резюме сессии

- **`README_FOR_NEXT_AGENT.md`:** уточнены таблицы «что не работает на eu1» / «что работает»: обычный MTProto на eu1 — не использовать (блок по сигнатуре); **MTProxy с Fake TLS** на main (Timeweb, `docs/mtproxy-faketls-deploy.md`) — рабочий путь для Telegram; правило №5 приведено в соответствие с `docs/telegram-unblock-algorithm.md` (команда `/proxy` снята, ссылка через `MTPROTO_PROXY_LINK`/вручную).
- **`SESSION_SUMMARY_2026-03-30.md`:** зафиксированы итоги сессии (ревью плана, согласование документации по прокси).

## 2026-03-26 — LTE blackhole, MVP/юнит-экономика (документация)

- **`docs/blocking-bypass-strategy.md`:** дополнение 2026-03-26 — выводы по полевым тестам LTE (недоступность HTTP/HTTPS до main/eu1 IP при рабочем Wi‑Fi; мульти-вход для mobile).
- **`docs/mvp-unit-economics-and-plan.md`:** новый документ — юнит-экономика (формулы, пример брейк-ивена), риски, фазы MVP, рамка «строить vs покупать сервис».
- **`SESSION_SUMMARY_2026-03-26.md`:** резюме диагностики и рекомендаций следующим шагам.

## 2026-03-25 — Веб recovery: Telegram/VPN + ссылка в боте

- **Веб-панель:** добавлен отдельный маршрут `/recovery`, а recovery-блоки вынесены с главной страницы `/`, чтобы пользователи не путались с мониторингом.
- **UI recovery:**
  - добавлены кнопки “Восстановить Telegram” и “Восстановить VPN (конфиг)”;
  - вход по `Telegram ID`;
  - опция `Android-safe` для корректного DNS в VPN-конфиге.
- **Backend recovery (`web/app.py`):**
  - `POST /api/recovery/telegram-proxy` — перезапуск docker-контейнера Telegram proxy-кандидата (через SSH, по server_id `main`/`eu1`), проверка пользователя через `bot/data/users.json`.
  - `POST /api/recovery/vpn` — генерация/регенерация peer и выдача клиентского VPN-конфига.
- **Фронтенд:** вынесена логика recovery в отдельный JS-файл `web/static/recovery.js`.
- **Telegram-бот:** обновлены тексты `/start` и `/help` — добавлена строка со ссылкой `http://81.200.146.32:5001/recovery`, чтобы пользователи могли восстановить доступ при неработающем Telegram.
- **UX:** с recovery страницы удалена навигационная ссылка “Назад к мониторингу”, чтобы пользователи не переходили туда.

## 2026-03-23 (продолжение) — Документация попытки LTE + eu1

- **Файл:** `docs/mobile-lte-eu1-xray-reality-attempt-2026-03.md` — зафиксированы: внедрение Xray REALITY на eu1, Streisand, порты 443/4443, Fragment, tcpdump, Fornex firewall off, вывод о недоступности IP `185.21.8.91` с LTE; план дальше: REALITY на Timeweb (`81.200.146.32`) или другой ASN.
- **README_FOR_NEXT_AGENT.md** — добавлена ссылка на этот документ в разделе «Документация».

## 2026-03-23 — Мобильный резерв: VLESS+REALITY и команда /mobile_vpn

- **Контекст:** AmneziaWG и прокси работают по Wi‑Fi, по LTE/5G на разных операторах и устройствах — тайм-ауты; нужен TCP-транспорт с маскировкой под TLS, без отключения AmneziaWG.
- **Спека:** `docs/specs/spec-07-mobile-fallback-vless-reality.md`.
- **Развёртывание на eu1 (оператор):** `docs/xray-vless-reality-eu1-deploy.md` — бэкап AmneziaWG → установка Xray → `VLESS_REALITY_SHARE_URL` в `env_vars.txt` на Timeweb.
- **Код бота:** `bot/config.py` — чтение `VLESS_REALITY_SHARE_URL`; `bot/main.py` — команда `/mobile_vpn` (инструкция + вторая сообщение со ссылкой без HTML); обновлены `/start`, `/help`, `/instruction`.
- **Тексты:** `docs/bot-instruction-texts/instruction_vless_reality_short.txt`; `env_vars.example.txt`; `docs/backup-restore.md` (бэкап Xray); `docs/deployment.md`; `docs/blocking-bypass-strategy.md`; `README_FOR_NEXT_AGENT.md`.

## 2026-03-15 — Фиксация сторонних альтернатив для Telegram

- **Документация:** создан файл `docs/telegram-proxy-alternatives.md` — отдельный список альтернативных решений для Telegram (локальный SOCKS5 `tg-ws-proxy`, платные SOCKS5-прокси вроде `ru.shopproxy.net/buy-proxy/telegram/`), с пометкой, что это НЕ официальный стек проекта и без гарантий работоспособности.
- **Цель:** сохранить найденные в интернете и чатах варианты, чтобы не держать их в голове, но при этом явно указать, что основной и рекомендованный путь для Telegram — работа через VPN/AmneziaWG по текущей стратегии обхода блокировок РКН.

## 2026-03-07 — Telegram-прокси с Fake TLS, алгоритм разблокировки, оценка провайдера

- **Уточнения:** в README зафиксировано отсутствие relay-сервера в проекте; сторонний прокси 79.132.138.66:9443 (не работает) зафиксирован в алгоритме.
- **Документация:** созданы docs/provider-choice-evaluation.md (Fornex vs FirstVDS), docs/telegram-unblock-algorithm.md (алгоритм разблокировки Telegram), docs/mtproxy-faketls-deploy.md (пошаговое развёртывание MTProxy с Fake TLS; добавлен шаг установки Docker).
- **Развёртывание:** пользователь развернул на Timeweb (81.200.146.32:443) контейнер mtproxy-faketls (nineseconds/mtg:2, маскировка под 1c.ru). Прокси проверен — работает у владельца и у знакомого в Москве, скорость нормальная. Ссылка и секрет не в репо.

## 2026-03-14 — Диагностика тайм-аута AmneziaWG, команда /broadcast, документация

- **Проблема:** на телефоне (AmneziaWG) ошибка «Не удалось установить соединение» (тайм-аут 12 с), на ПК VPN работал. В мониторинге 0 Б по части пользователей.
- **Диагностика на eu1:** проверка через `docker exec amnezia-awg2 awg show awg0` — один peer без handshake (конфиг на телефоне не совпадал с сервером). Решение: /regen в боте или экспорт рабочего .conf с ПК и импорт на телефон.
- **Команда /broadcast:** добавлена в бота (только владелец). Рассылает всем пользователям уведомление о проблеме VPN и рекомендацию выполнить /regen, заменить старый конфиг новым. Отчёт владельцу: количество доставленных и не доставленных сообщений.
- **Документация:** обновлён `docs/client-instructions-amneziawg.md` (раздел «Если перестало работать»); создан `docs/troubleshooting-amneziawg-connection-timeout.md` (симптомы, решение, почему /regen помогает, почему ПК не пострадал).
- **Деплой:** коммит и push в nikkronos/vpnservice; на Timeweb git stash → git pull → restart vpn-bot.service. Рассылка выполнена (11 доставлено, 1 не доставлено).

## 2026-02-26 — Автоматизация выдачи конфигов AmneziaWG + удаление /proxy

- **Задача 1:** настроить автоматическую выдачу рабочих конфигов VPN через Telegram-бота для сервера eu1 (Европа).
- **Задача 2:** удалить неработающие функции (команда `/proxy`, отображение Shadowsocks и MTProto на веб-панели).

- **Диагностика eu1:**
  - AmneziaWG работает в Docker-контейнере `amnezia-awg2`
  - Порт: 39580/UDP (не 51820)
  - Подсеть: 10.8.1.0/24 (не 10.1.0.0/24)
  - Публичный ключ сервера: `pevLcgguoIMDWnbtPgQ3ZsSak73fylprex54Tv65ZyI=`

- **Создан бэкап:** `/root/amnezia-backup-20260226/` на eu1 (конфиг сервера, ключи, clientsTable)

- **Написаны скрипты:**
  - `/opt/amnezia-add-client.sh` — добавление клиента в Docker-контейнер
  - `/opt/amnezia-remove-client.sh` — удаление клиента

- **Настроен SSH:** ключ `/root/.ssh/id_ed25519_eu1` на Timeweb добавлен в authorized_keys на eu1

- **Обновлены переменные бота** (`env_vars.txt` на Timeweb):
  - `WG_EU1_ENDPOINT_PORT=39580`
  - `WG_EU1_NETWORK_CIDR=10.8.1.0/24`
  - `AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT=/opt/amnezia-add-client.sh`
  - `AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT=/opt/amnezia-remove-client.sh`
  - `AMNEZIAWG_EU1_NETWORK_CIDR=10.8.1.0/24`

- **Очищены старые peers:** удалены все eu1 peers из `peers.json` (имели IP из старой подсети 10.1.0.0/24)

- **Результат (автоматизация):** бот автоматически выдаёт рабочие конфиги AmneziaWG для Европы, проверено на телефоне

**Очистка от неработающих функций (сессия 2):**

- **Удалена команда /proxy из бота:**
  - Удалён хендлер `cmd_proxy` из `/opt/vpnservice/bot/main.py`
  - Убрана строка про `/proxy` из команды `/start`
  - Убрана строка про `/proxy` из команды `/help`

- **Удалены Shadowsocks и MTProto с веб-панели:**
  - Из `/opt/vpnservice/web/app.py` удалены блоки проверки Shadowsocks (порт 8388) и MTProto (порт 443)
  - Обновлена подсказка в блоке "Сервисы" в `/opt/vpnservice/web/templates/index.html`
  - Теперь в блоке "Сервисы" отображаются только: WireGuard (main), WireGuard (eu1), AmneziaWG (eu1)

- **Результат (очистка):** веб-панель показывает только работающие сервисы, бот не предлагает нерабочий MTProto-прокси

- **Обновлена документация:** SESSION_SUMMARY_2026-02-26.md, README_FOR_NEXT_AGENT.md, DONE_LIST_VPN.md

## 2026-02-23 — Восстановление eu1, эксперименты Remnawave/Xray/MTProto (неудачны)

- **Переустановка ОС на eu1:** Сервер eu1 (Fornex) полностью переустановлен (Ubuntu 24.04). Все сервисы были удалены.

- **Попытка Remnawave (неудачна):**
  - Развёрнут Remnawave (panel + node) на eu1 с доменами `panel.vpnnkrns.ru`, `sub.vpnnkrns.ru`, `node.vpnnkrns.ru`.
  - ACME выписал сертификаты успешно.
  - Контейнер `remnanode` падал с ошибкой `Invalid SECRET_KEY payload`.
  - Ручное добавление `SECRET_KEY` в `.env` проблему не решило.
  - **Решение:** Remnawave удалён, попытка признана неудачной.

- **Возврат AmneziaWG на eu1:**
  - Через приложение AmneziaVPN установлен AmneziaWG на eu1.
  - Конфиги созданы и раздаются **вручную** через «Поделиться VPN».
  - На ПК и iOS (телефон владельца и друзей) — **работает**.

- **Попытка MTProto-прокси (неудачна):**
  - Переустановлен MTProto-прокси на порт 443, затем 8443.
  - На обоих портах Telegram показывает «connecting», но не подключается.
  - **Вывод:** Мобильный оператор блокирует MTProto по сигнатуре протокола.
  - **Решение:** Telegram работает **через VPN (AmneziaWG)**.

- **Эксперимент Xray VLESS/TCP (неудачен):**
  - Установлен Xray (`xray-core`), настроен минимальный inbound VLESS/TCP без TLS (порт 21017).
  - Xray-служба работает, `curl` с сервера возвращает 200.
  - На ПК (v2rayN) профиль подключается, в логах видны подключения.
  - Однако: `ifconfig.me` показывает исходный IP, сайты не открываются.
  - **Вывод:** VLESS/TCP без TLS не работает (DPI распознаёт или проблемы маршрутизации на клиенте).
  - **Решение:** Эксперимент остановлен, не продолжать без TLS/Reality.

- **Обновление документации:**
  - Обновлён `SESSION_SUMMARY_2026-02-23.md` с полным описанием всех экспериментов.
  - Обновлён `README_FOR_NEXT_AGENT.md` — актуальное состояние, что работает/не работает.
  - Обновлён `DONE_LIST_VPN.md` (этот файл).
  - Обновлён `ROADMAP_VPN.md` — скорректированы задачи.

## 2026-02-22 — Чистый сброс eu1 (Fornex): AmneziaWG, проверка на ПК и iOS

- **Проблема:** на телефоне и у друзей — подключение к eu1 было, интернета не было; на ПК VPN работал через AmneziaWG.
- **План:** сброс только на eu1 (оставить MTProto и Shadowsocks), остановить и убрать конфиги AmneziaWG и wg0, проверить работу с нуля.
- **Документы:** созданы `docs/eu1-clean-slate-plan.md`, `docs/eu1-clean-slate-commands.md`; в README_FOR_NEXT_AGENT.md добавлен блок про план чистого сброса.
- **На eu1:** бэкап в `/root/eu1-backup-20260222`; остановлены и отключены awg-quick@awg0 и wg-quick@wg0; awg0.conf и копия /etc/amnezia перенесены в бэкап. Контейнеры Docker (amnezia-awg2, mtproto-proxy) не трогали.
- **Проверка:** сервер уже был в AmneziaVPN; экспорт для iOS через «Поделиться VPN»; на телефоне и на ПК подключение и интернет работают. Чистый сброс завершён успешно.

- **Бот — выдача конфигов AmneziaWG (Docker):** на eu1 развёрнуты скрипты amneziawg-add-client-docker.sh и amneziawg-remove-client-docker.sh; конфиг сервера в контейнере — /opt/amnezia/awg/awg0.conf; в скрипт добавлено извлечение обфускации (Jc, Jmin, Jmax, S1–S4, H1–H4) и подстановка в клиентский .conf. На Timeweb в env указаны пути к *-docker.sh; бот по /get_config и /regen выдаёт конфиги. На телефоне с конфигом от бота: handshake есть, трафик не грузится (открытый вопрос — см. SESSION_SUMMARY и docs/eu1-phone-config-open-question.md).

## 2026-02-21 — Веб-панель: деплой, этапы 2–3, подсказки

- **Деплой:** панель развёрнута на Timeweb на порту 5001 (чтобы не конфликтовать с Damir на 5000). Добавлены `web/vpn-web.service.example`, раздел в `docs/deployment.md`, переменная PORT=5001.
- **Этап 2:** блок «Сервисы» (API `/api/services` — WireGuard, AmneziaWG по пингу; Shadowsocks и MTProto по проверке TCP-портов); блок «Пользователи (сводка)» (без блока «По типам профилей»).
- **Этап 3:** учёт трафика — `wg show dump` локально для main, по SSH для eu1; API `/api/traffic`, блок «Трафик по пользователям» (по пользователям и по устройствам), обновление раз в 30 сек.
- **Подсказки:** под каждым блоком панели добавлены короткие пояснения (пользователь vs подключение, онлайн/офлайн по пингу, main/eu1, частота обновления трафика, подключение = конфиг, не устройство).

## 2026-02-21 — Бот: Европа = AmneziaWG (инструкция + опция выдачи конфига через скрипт)

- **Европа (eu1) в боте:** для сервера «Европа» бот больше не выдаёт WireGuard конфиги. Выдаётся инструкция по AmneziaWG (ПК + iOS через «Поделиться»). При настройке скрипта на eu1 (`AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT`) бот вызывает скрипт по SSH и выдаёт готовый AmneziaWG .conf.
- **Спецификация и скрипты:** созданы `docs/specs/spec-05-bot-amneziawg-eu1.md`, `docs/scripts/amneziawg-add-client.sh.example`, `docs/amneziawg-eu1-discovery.md` (проверка на eu1). В `env_vars.example.txt` добавлены переменные для AmneziaWG.
- **Тексты бота:** обновлены /start, /help, /instruction — Европа = AmneziaWG, импорт в AmneziaVPN/AmneziaWG. Добавлен короткий текст `docs/bot-instruction-texts/instruction_amneziawg_short.txt`. Регенерация (/regen) для Европы пока вручную — сообщение «напиши владельцу».
- **Код:** в `bot/wireguard_peers.py` добавлены `is_amneziawg_eu1_configured()`, `create_amneziawg_peer_and_config_for_user()`, `_remove_amneziawg_peer()`, `regenerate_amneziawg_peer_and_config_for_user()`; в `bot/main.py` — ветка для eu1 (AmneziaWG скрипт или инструкция), автоматическая регенерация (/regen) для Европы при настроенных скриптах.
- **Автоматизация выдачи и регенерации:** доработаны скрипты add-client и remove-client (`docs/scripts/`); бот поддерживает reuse_ip при создании peer и автоматический /regen для Европы (удаление старого peer на eu1, создание нового с тем же IP). Добавлен пошаговый гайд `docs/amneziawg-bot-automation-setup.md`. Переменные env: AMNEZIAWG_EU1_INTERFACE, AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT.

## 2026-02-21 — AmneziaWG на eu1 работает, iOS через «Поделиться», следующие задачи

- **VPN работает:** AmneziaWG на eu1 развёрнут, подключение из России (ПК + iPhone/iPad) работает. На iOS конфиг импортируется через «Поделиться» → AmneziaWG (выбор файла в пикере не срабатывал).
- **Инструкция для пользователей:** обновлена docs/client-instructions-amneziawg.md — импорт через «Поделиться» на iOS, какой файл использовать (.conf для AmneziaWG).
- **Решения владельца:** бэкап можно хранить в Git (репозиторий сделать приватным). Второй VPS отложен — без монетизации по бюджету не планируется. Бот — обновить инструкции (выдавать инструкцию по AmneziaWG, при возможности конфиг). Веб-панель — развернуть, получить ссылку, доработать под полный мониторинг (сейчас ссылки нет).
- **ROADMAP и README:** обновлены: задачи по боту (выдача инструкции/конфига AmneziaWG), веб-панель (деплой + ссылка + доработка мониторинга), второй VPS отложен. В docs/backup-restore.md добавлено про бэкап в Git при приватном репо.

## 2026-02-21 — Стратегия обхода блокировок РКН, выбор AmneziaWG, план развёртывания

- **Документ по стратегии обхода блокировок:**
  - Создан `docs/blocking-bypass-strategy.md` — контекст (что работает/блокируется в РФ 2026), варианты A/B/C/D (в т.ч. Shadowsocks + V2BOX), совет по провайдерам и доменам.
  - **Выбран вариант A (AmneziaWG):** один клиент AmneziaVPN на ПК и iOS/iPadOS; понятно пользователю; при блокировке РКН — добавить Xray в том же приложении.

- **РКН: начеку и легко перестраиваться:**
  - В ROADMAP_VPN.md добавлен раздел «РКН: быть начеку и легко перестраиваться» — документировать шаги, один клиент для пользователя, резерв Xray в Amnezia, при необходимости смена домена/провайдера.

- **Пошаговый план и инструкция развёртывания:**
  - Обновлён `docs/step-by-step-plan-bypass.md` — зафиксирован выбор A, упрощены шаги под AmneziaWG.
  - Создан `docs/amneziawg-deploy-instruction.md` — пошаговая инструкция: установка AmneziaVPN на ПК → добавление сервера eu1 по SSH → установка AmneziaWG через приложение → создание подключения → iOS/iPad по тому же приложению; раздел «Если РКН начнёт блокировать».

- **Обновление ROADMAP_VPN.md:**
  - Блок «Обход блокировок РКН»: выбор A отмечен как выполненный, следующие шаги — развернуть по инструкции, тест из России, при необходимости бот.
  - Раздел «Проблема eu1» сокращён до ссылок на AmneziaWG и резерв Xray.

- **SESSION_SUMMARY:**
  - Создан `SESSION_SUMMARY_2026-02-21.md` с контекстом сессии и замечаниями для следующего агента.

## 2026-02-20 — Улучшение UX и решение проблем тестирования

- **Улучшение UX в боте:**
  - Улучшены объяснения режимов "обычный VPN" и "VPN+GPT" в боте с понятными описаниями и эмодзи
  - Добавлена команда `/help` с подробной справкой о режимах VPN и типах профилей
  - Улучшены сообщения при выборе сервера и типа профиля
  - Добавлены визуальные индикаторы для лучшего понимания

- **Документация по диагностике проблем:**
  - Создан документ `docs/troubleshooting-multiple-devices.md` — диагностика проблемы с несколькими устройствами (плохо работает интернет при подключении с двух устройств)
  - Создан документ `docs/troubleshooting-ios-devices.md` — решение проблем VPN на iPhone без SIM и iPad
  - Создан документ `docs/troubleshooting-telegram-vpn-conflict.md` — решение конфликта VPN и Telegram proxy на iPhone
  - Создан скрипт `docs/scripts/monitor-server.sh.example` — мониторинг состояния VPN-сервера

- **Спецификация единого профиля:**
  - Создана спецификация `docs/specs/spec-04-unified-profile-all-services.md` с вариантами решения единого профиля для всех сервисов (YouTube + GPT + Telegram + сайты)
  - Исследованы 4 варианта решения, рекомендован гибридный вариант (WireGuard + Smart DNS + Shadowsocks)
  - Описана детальная реализация с чеклистом и рисками

- **Веб-панель мониторинга:**
  - Создана базовая структура веб-панели в `web/`
  - Реализовано Flask-приложение с API endpoints для мониторинга серверов, пользователей и статистики
  - Созданы HTML шаблоны, CSS стили и JavaScript для автообновления
  - Добавлена документация по установке и деплою

- **Изучение альтернатив:**
  - Создан документ `docs/vless-alternative.md` — изучение VLESS как альтернативы WireGuard
  - Сравнение VLESS с WireGuard по различным параметрам
  - Рекомендации по использованию VLESS в проекте

- **Обновление Roadmap:**
  - Обновлён `ROADMAP_VPN.md` с учётом всех выполненных задач
  - Отмечены выполненные задачи с датами
  - Добавлены новые разделы и обновлены существующие

## 2026-02-18 — Настройка WireGuard + Shadowsocks и клиентов

- **Сервер Fornex (Ubuntu 24.04)**
  - Установлен `shadowsocks-libev` и настроен клиентский конфиг `/etc/shadowsocks-libev/ss-wg.json` для подключения к Shadowsocks‑серверу `185.21.8.91:8388` (метод `aes-256-gcm`).
  - Запущен `ss-redir` как systemd‑сервис `ss-wg.service` (автозапуск, прослушивает `127.0.0.1:1081`).
  - В WireGuard‑конфиг `/etc/wireguard/wg0.conf` добавлены новые `Peer`:
    - Владелец iPhone: `10.1.0.4/32`.
    - Друг PC: `10.1.0.5/32`.
    - Друг iPhone: `10.1.0.6/32`.
    - Друг iPad: `10.1.0.7/32`.
  - Настроены iptables‑правила:
    - редирект всего TCP‑трафика на порты 80/443 от выбранных IP (`10.1.0.4/32`, `10.1.0.5/32`, `10.1.0.6/32`, `10.1.0.7/32`) на `127.0.0.1:1081` (Shadowsocks‑клиент);
    - разрешён форвардинг трафика интерфейса `wg0`.
  - Создана резервная копия основных конфигов:
    - `/etc/wireguard/wg0.conf`;
    - `/etc/wireguard/iphone.conf`;
    - `/etc/shadowsocks-libev/ss-wg.json`;
    - бэкапы сохранены в `/root/vpn-backups/2026-02-18/`.

- **Клиенты владельца**
  - **ПК (Windows)**:
    - Папка клиента Shadowsocks упорядочена (перенесена в отдельную директорию, например, `VPN.Shadowsocks`), проверено, что `Shadowsocks.exe` и `gui-config.json` работают корректно.
    - Текущий рабочий профиль WireGuard `client1` (от бота второго аккаунта) продолжает использоваться для обычного VPN.
  - **iPhone**:
    - Создан и импортирован новый профиль WireGuard `iphone`:
      - `Address = 10.1.0.4/32`, `DNS = 8.8.8.8`;
      - `Endpoint = <публичный IP Fornex>:51820`;
      - `AllowedIPs = 0.0.0.0/0`, `PersistentKeepalive = 25`.
    - Проверено, что при подключении профиля `iphone`:
      - ChatGPT работает;
      - обычные сайты идут через тот же сервер (с учётом ограничений/блокировок по IP Shadowsocks).

- **Клиенты друга** (по проектному допущению — успешно подключены)
  - **ПК (Friend PC)**:
    - Сгенерированы ключи и создан профиль WireGuard `friend-pc.conf`:
      - `Address = 10.1.0.5/32`, `DNS = 8.8.8.8`;
      - `Endpoint = <публичный IP Fornex>:51820`;
      - `AllowedIPs = 0.0.0.0/0`, `PersistentKeepalive = 25`.
  - **iPhone (Friend iPhone)**:
    - Профиль `friend-iphone.conf`:
      - `Address = 10.1.0.6/32`, остальные параметры аналогичны.
  - **iPad (Friend iPad)**:
    - Профиль `friend-ipad.conf`:
      - `Address = 10.1.0.7/32`, остальные параметры аналогичны.

- **Документация**
  - Создан файл `README_FOR_NEXT_AGENT.md` с описанием:
    - текущей архитектуры (WireGuard + Shadowsocks);
    - профилей владельца и друга;
    - расположения бэкапов конфигов;
    - ключевых правил безопасности и ограничений.
  - Создан `ROADMAP_VPN.md`:
    - зафиксировано текущее состояние (MVP 0.1);
    - намечены ближайшие и среднесрочные шаги (спеки, Telegram‑proxy, второй сервер, автоматизация через бота).

## 2026-02-18 — Установка Telegram MTProto Proxy

- **Сервер Fornex (Ubuntu 24.04)**
  - Установлен Docker (версия 29.2.1) для запуска контейнеров.
  - Развёрнут MTProto‑прокси через Docker‑контейнер `telegrammessenger/proxy:latest`:
    - контейнер: `mtproto-proxy` (автозапуск через `--restart=always`);
    - порт: `443/TCP` (маппинг `0.0.0.0:443->443/tcp`);
    - секрет: `29d11c61ea1b644d75299dd0706c2da3` (сгенерирован автоматически при запуске);
    - внешний IP: `185.21.8.91` (тот же, что у WireGuard‑сервера).
  - Сформирована ссылка подключения:
    - `tg://proxy?server=185.21.8.91&port=443&secret=29d11c61ea1b644d75299dd0706c2da3`;
    - альтернативная ссылка: `https://t.me/proxy?server=185.21.8.91&port=443&secret=29d11c61ea1b644d75299dd0706c2da3`;
    - ссылка сохранена в `/root/vpn-backups/2026-02-18/mtproto-link.txt`.
  - Проверена работа прокси:
    - контейнер запущен и работает стабильно;
    - пинг через прокси: ~45 мс (приемлемо для Telegram);
    - прокси работает независимо от WireGuard и Shadowsocks.

- **Клиенты**
  - **Владелец**: протестирован MTProto‑прокси на iPhone, подключение успешно, Telegram работает через прокси.
  - **Друг**: предоставлена ссылка подключения, прокси успешно настроен и работает на его устройствах.

- **Документация**
  - Создана спецификация `docs/specs/spec-02-telegram-mtproto-proxy.md`:
    - архитектура MTProto‑прокси;
    - требования и этапы реализации;
    - риски и митигация;
    - чеклист проверки.
  - Создана инструкция по установке `docs/mtproto-setup.md`:
    - пошаговая установка Docker (если не установлен);
    - запуск контейнера MTProto‑прокси;
    - получение секрета и формирование ссылки подключения;
    - настройка systemd (опционально);
    - тестирование на клиентах;
    - управление и устранение проблем.
  - Обновлены основные документы проекта:
    - `README_FOR_NEXT_AGENT.md`: добавлена информация о MTProto‑прокси в разделы "Серверы" и "Как этим пользоваться";
    - `ROADMAP_VPN.md`: отмечена выполненная задача по установке MTProto‑прокси.

## 2026-02-18 — Интеграция бота: инструкции, MTProto-ссылка, VPN+GPT

- **Команды бота**
  - Добавлена команда `/instruction` — пошаговая инструкция по подключению (ПК и iPhone/iPad); тексты загружаются из `docs/bot-instruction-texts/instruction_pc_short.txt` и `instruction_ios_short.txt`.
  - Добавлена команда `/proxy` — отправка ссылки MTProto‑прокси и краткой инструкции из `instruction_mtproto_short.txt`; ссылка читается из переменной окружения `MTPROTO_PROXY_LINK` (на Timeweb добавлена в `env_vars.txt`).
  - После успешной выдачи конфига по `/get_config` бот автоматически отправляет объединённую инструкцию (ПК + iOS).
  - В приветствии `/start` добавлены строки про `/instruction` и `/proxy`.

- **Конфигурация бота**
  - В `bot/config.py`: добавлены поля `base_dir`, `mtproto_proxy_link`; загрузка `MTPROTO_PROXY_LINK` из env (опционально).
  - В `docs/deployment.md`: раздел «Обновление бота на Timeweb» — напоминание, что `env_vars.txt` на сервере не в Git и новые переменные нужно добавлять вручную; команды для `git pull`, перезапуска сервиса и просмотра логов.

- **Опция VPN+GPT для Европы (eu1)**
  - При выборе сервера «Европа» в `/server` добавлен второй шаг: выбор типа профиля — «Обычный VPN» или «VPN+GPT (обход блокировок ChatGPT)».
  - Для VPN+GPT: выделение IP из пула **10.1.0.8–10.1.0.254**; после добавления peer в WireGuard бот по SSH на eu1 вызывает скрипт `add-ss-redirect.sh <IP>`, добавляющий iptables‑редирект TCP 80/443 на порт 1081 (ss-redir).
  - Имя конфига для VPN+GPT: `vpn_<id>_eu1_gpt.conf`; в сообщении бота явно указан тип «VPN+GPT».
  - В `bot/storage.py`: у `User` — поле `preferred_profile_type` (vpn / vpn_gpt); у `Peer` — поле `profile_type`; при регенерации конфига тип профиля сохраняется.
  - В `bot/wireguard_peers.py`: функции `_allocate_ip_in_pool()`, `_run_add_ss_redirect()`; в `create_peer_and_config_for_user()` добавлен параметр `profile_type`; опциональная переменная env `WG_EU1_ADD_SS_REDIRECT_SCRIPT` (по умолчанию `/opt/vpnservice/scripts/add-ss-redirect.sh`).

- **Скрипт add-ss-redirect.sh на eu1**
  - Пример скрипта: `docs/scripts/add-ss-redirect.sh.example`; развёртывание и путь описаны в `docs/deployment.md`.
  - На сервере eu1 (Fornex) скрипт развёрнут в `/opt/vpnservice/scripts/add-ss-redirect.sh`, выполнен `chmod +x`, проверен вызов с аргументом `10.1.0.8` и наличие правил в iptables.
  - На Timeweb в `env_vars.txt` добавлена переменная `WG_EU1_ADD_SS_REDIRECT_SCRIPT=/opt/vpnservice/scripts/add-ss-redirect.sh` (опционально, путь по умолчанию совпадает).

- **Документация и планы**
  - Спека `docs/specs/spec-03-bot-integration-instructions.md`: отмечены выполненные пункты (инструкции, MTProto, VPN+GPT, скрипт).
  - `ROADMAP_VPN.md`: отмечены выполненные задачи (выдача инструкции, команда /proxy, опция VPN+GPT в боте); оставлена задача «На сервере eu1 развернуть add-ss-redirect.sh» как выполненная по факту (скрипт развёрнут).

# DONE_LIST_VPN

История выполненных задач по проекту VPN.

## 2026-02-09

- Создана базовая структура документации для проекта VPN:
  - добавлен `ROADMAP_VPN.md` с этапами развития (MVP, бот, масштабирование, коммерциализация);
  - подготовлен шаблон для `SESSION_SUMMARY_2026-02-09.md` (см. файл сессии);
  - проект VPN интегрирован в центральные документы (`RULES_CURSOR.md`, `PROJECTS.md`, `ROAD_MAP_AI.md`, `QUICK_START_AGENT.md`, `docs/AGENT_PROMPTS.md`).
- Инициализирован отдельный Git-репозиторий для проекта VPN:
  - создан локальный репозиторий в папке `VPN/` (`git init`);
  - привязан к GitHub-репозиторию `nikkronos/vpnservice` (`git remote add origin`);
  - выполнен первый коммит с базовой структурой документации (`chore: initialize vpnservice repo structure`);
  - ветка переименована в `main` и отправлена на GitHub (`git push -u origin main`).
- Определена стратегия развёртывания:
  - первая нода будет развёрнута на существующем Timeweb-сервере (для тестирования и экономии средств);
  - в дальнейшем — миграция на отдельный VPS под VPN.
- Создана детальная инструкция по развёртыванию:
  - `VPN/docs/deployment.md` — пошаговое руководство по установке и настройке WireGuard на сервере;
  - включает генерацию ключей, конфигурацию сервера и клиентов, тестирование подключения.
- Развёрнута первая WireGuard-нода на существующем Timeweb-сервере (81.200.146.32):
  - установлен WireGuard, сгенерированы ключи сервера и клиента;
  - настроен интерфейс wg0, IP forwarding, UFW (порт 51820/UDP), systemd автозапуск;
  - создан конфиг клиента client1.conf, скопирован на Windows через scp.
- Успешное тестирование на Windows:
  - туннель «client1» подключён, внешний IP — 81.200.146.32;
  - ping 8.8.8.8: 0% потерь, ~10–15 мс;
  - Speedtest: ~91 Мбит/с вниз, ~88 Мбит/с вверх, пинг 10 мс.
- Успешное тестирование на iOS:
  - установлен qrencode на сервере, сгенерирован QR-код из client1.conf;
  - конфиг добавлен в WireGuard на iPhone через сканирование QR-кода;
  - подключение работает.

## 2026-02-11

- Реализован self-service через Telegram-бота:
  - спроектирована модель данных для пользователей (`users.json`) и VPN-подключений (`peers.json`);
  - добавлен модуль `bot/storage.py` с dataclass `Peer` и функциями для работы с peers;
  - добавлен модуль `bot/wireguard_peers.py` для интеграции с WireGuard (генерация ключей, подбор IP, добавление peer через `wg set`, формирование `.conf`);
  - переработан `bot/main.py` под сценарий self-service (команды `/start`, `/get_config`, `/my_config`, `/add_user`, `/users` с учётом новой модели данных).
- Настроены переменные окружения для VPN-проекта:
  - в `env_vars.txt` добавлены параметры `WG_SERVER_PUBLIC_KEY`, `WG_INTERFACE`, `WG_NETWORK_CIDR`, `WG_ENDPOINT_HOST`, `WG_ENDPOINT_PORT`, `WG_DNS`;
  - `WG_SERVER_PUBLIC_KEY` получен с помощью `wg show wg0 public-key` на сервере.
- Настроено обновление кода на сервере `/opt/vpnservice`:
  - сконфигурирован доступ к GitHub через Personal Access Token для `nikkronos/vpnservice`;
  - аккуратно разрешён конфликт между старым локальным `bot/storage.py` и новой версией из репозитория (старый файл сохранён как бэкап);
  - выполнен `git pull`, подтянуты новые файлы (`bot/main.py`, `bot/storage.py`, `bot/wireguard_peers.py`, `bot/__init__.py`, specs), перезапущен `vpn-bot.service`.
- Протестирован self-service для друзей:
  - владелец добавляет друга командой `/add_user` (ответом на сообщение или по Telegram ID);
  - друг пишет боту `/start` и `/get_config`, бот создаёт peer в WireGuard, сохраняет его в `peers.json` и отправляет конфигурационный файл `vpn_<telegram_id>.conf`;
  - как минимум один друг успешно подключился к VPN: YouTube и Instagram работают через туннель.
- Обновлены планы по развитию infrastructure и multi-node в `ROADMAP_VPN.md` (добавлены задачи по оценке нагрузки и внедрению нескольких нод/регионов).

## 2026-02-13

- Уточнены лимиты трафика у провайдера Timeweb:
  - подтверждено, что базовых ограничений по объёму трафика нет;
  - основное требование — не нарушать правила платформы (отсутствие незаконного контента, DDoS, спама и т.п.);
  - сделан вывод, что текущий VPS подходит для использования VPN друзьями и коллегами без жёстких лимитов по трафику.
- Доведена до рабочего состояния команда `/regen` (регенерация ключей и конфига WireGuard):
  - реализованы функции `_remove_peer_from_wireguard()` и `regenerate_peer_and_config_for_user()` в `bot/wireguard_peers.py`;
  - обновлён хендлер `/regen` в `bot/main.py`, который удаляет старый peer, создаёт новый с тем же IP и отправляет пользователю обновлённый `.conf`;
  - исправлена ошибка с отсутствующим импортом `find_peer_by_telegram_id`, из-за которой бот молчал при вызове `/regen`;
  - протестировано на боевом пользователе: новый конфиг успешно отработал, туннель продолжил работать.
- GitHub‑репозиторий `nikkronos/vpnservice` временно сделан публичным для упрощения деплоя (без постоянного ввода PAT); зафиксирована необходимость после завершения работ вернуть репозиторий в приватный режим и убедиться в отсутствии секретов в истории коммитов.

## 2026-02-14

- Добавлена вторая VPN-нода **eu1 (Европа)** на Fornex (Германия):
  - заказан VPS Cloud NVMe 1 (1 ядро, 1 ГБ RAM, 10 ГБ NVMe, безлимитный трафик) в локации Германия;
  - на сервере 185.21.8.91 установлен WireGuard (Ubuntu 24.04 LTS), настроен интерфейс wg0 в подсети 10.1.0.0/24, порт 51820/UDP, IP forwarding, UFW;
  - сгенерированы ключи сервера eu1, публичный ключ добавлен в конфигурацию бота.
- Настроен доступ бота (Timeweb) к ноде eu1 по SSH:
  - на Timeweb создан отдельный SSH-ключ для доступа к eu1;
  - публичный ключ добавлен в `authorized_keys` на Fornex (eu1);
  - в `env_vars.txt` на Timeweb добавлены переменные WG_EU1_* (SERVER_PUBLIC_KEY, INTERFACE, NETWORK_CIDR, ENDPOINT_HOST/PORT, DNS, SSH_HOST/USER/KEY_PATH).
- Логика бота обновлена ранее: `get_available_servers()` возвращает eu1 только при наличии WG_EU1_SERVER_PUBLIC_KEY и WG_EU1_ENDPOINT_HOST; переменные для нод используют формат `WG_<SERVERID>_*` (см. env_vars.example.txt).
- Успешная проверка в боте:
  - в `/server` отображаются две опции: «Россия (Timeweb)» и «Европа»;
  - пользователь выбрал «Европа», вызвал `/get_config` — бот создал peer на eu1 по SSH и отправил конфиг;
  - импорт конфига в WireGuard и подключение к ноде Европа работают; доступ к ChatGPT и другим EU-сервисам через eu1 обеспечен.
- Исправлена путаница с конфигами при переключении серверов:
  - имена файлов конфигов изменены с `vpn_<telegram_id>.conf` на `vpn_<telegram_id>_<server_id>.conf` (например, `vpn_123_main.conf` и `vpn_123_eu1.conf`);
  - в `bot/main.py` обновлены вызовы для `/get_config` и `/regen`, чтобы пользователи не перезаписывали и не путали конфиги для РФ и Европы.

## 2026-02-15

- Продолжена отладка ноды eu1 (Fornex): проблема «Получено 0, отправлено ок» не решена с прошлым агентом.
- Расширена документация по отладке eu1:
  - добавлены разделы 9–13 в `VPN/docs/eu1-setup-and-troubleshooting.md` (рекомендуемые проверки, обратный путь, финальные тесты, варианты обхода).
  - создан `VPN/docs/eu1-commands-step-by-step.md` — пошаговые команды для диагностики.
  - создан `VPN/docs/eu1-workarounds-fornex.md` — инструкции по обходным путям (ShadowSocks, Cloudflared, udp2raw, V2Ray).
- Добавлена опциональная поддержка MTU в клиентском конфиге:
  - в `bot/wireguard_peers.py` добавлен параметр `mtu` в конфиг ноды и в `_build_client_config()`.
  - если задан `WG_EU1_MTU` (например, 1280), в выдаваемый конфиг добавляется строка `MTU = 1280` в `[Interface]`.
  - обновлён `env_vars.example.txt` с примером `WG_EU1_MTU=1280`.
- Диагностика на Fornex:
  - исправлен пир с `AllowedIPs 10.1.0.0/24` → `10.1.0.2/32`.
  - добавлены правила iptables FORWARD в начало цепочки (wg0↔eth0, eth0→wg0 RELATED,ESTABLISHED).
  - rp_filter установлен в 0 для all и wg0.
  - выполнен tcpdump на eth0 (UDP 51820, 45 секунд) — пакетов от клиента к серверу не видно, но `wg show` показывает активный обмен (14.25 KiB received, 33.17 KiB sent).
- Вывод по eu1:
  - WireGuard UDP (порт 51820) на Fornex технически не работает для клиентов из России (блокировка/потеря трафика на маршруте Россия ↔ Fornex).
  - Сервер настроен корректно (все проверки пройдены), проблема вне зоны контроля.
  - Подготовлены варианты обходных путей для Fornex (ShadowSocks, Cloudflared, udp2raw, V2Ray) — см. `eu1-workarounds-fornex.md`.
- Обновлён `ROADMAP_VPN.md`: добавлена задача про проблему eu1 и варианты решения (обходные пути или миграция на другой провайдер).
- Fornex подтвердил: «С нашей стороны, ограничений нет.» — исходящий UDP с VPS до абонентских IP со стороны Fornex не блокируется.

