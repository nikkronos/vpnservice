# SESSION SUMMARY — 2026-05-21

## TL;DR

- ✅ **Yota/Мегафон при БС — решено окончательно.** VLESS+REALITY на main Timeweb (`81.200.146.32:443`) с `dest=cloud.mail.ru`. Подтверждено реальным тестом с другом при активных БС.
- ✅ **Исправлен скрытый critical bug:** AmneziaWG peers терялись при рестарте Docker-контейнера. После reboot Fornex 28 из 30 peers пропали (только 4 остались в `awg0.conf`). Восстановлены, persistent-fix внедрён через `awg showconf` + cron.
- ✅ Все 3 сервера обновлены до свежих kernel'ов (Fornex, YC vrprnt, main).

## Хронология

### 1. Подъём контекста и выбор пути для Yota/Мегафон

Прошлая сессия (`SESSION_SUMMARY_2026-05-20`) закончилась postmortem'ом: XHTTP через любые YC HTTP/2-endpoints (CDN, API Gateway) не работает у клиентов. Реалистичные пути в `yandex-cdn-xhttp-postmortem.md`: WS-extension API Gateway / Trojan / VPS у whitelisted-провайдера / Cloud Functions.

Выбран Path 1: WS-extension в API Gateway.

### 2. Path 1 — WS-extension API Gateway

Изучили документацию: WebSocket в YC API Gateway работает **только с Cloud Functions**, прозрачный proxy к HTTP-backend невозможен. Path 1 закрыт.

**Но** при чтении docs нашли упущенный синтаксис: HTTP-integration с `'*': '*'` пробрасывает все query/headers. Это не пробовали в прошлой сессии. Пересоздали API Gateway с правильной спекой → query string наконец доходит до Xray, запросы получают HTTP 200 на серверной стороне.

Тест с другом (Streisand iOS): и на Wi-Fi, и на Yota — connected, трафика нет. То же что и через CDN. Подтвердили: **XHTTP через любой Yandex HTTP/2-edge не работает у клиентов**, постмортем был верен в выводе, мы лишь дочистили технический контекст.

API Gateway удалён.

### 3. Разведка whitelist через друга при активных БС

Ключевое окно — у друга активны БС. Сделали несколько диагностических раундов:

**Тест 1 — какие cloud-провайдеры в whitelist:**
- ✅ `cloud.vk.com`, `cloud.mail.ru`, `timeweb.cloud`, `cloud.ru`, `selectel.ru` — все открываются
- ❌ `digitalocean.com` (контроль) — не открывается
→ Whitelist реально активен и пропускает российские облака.

**Тест 2 — whitelist по SNI или по IP:**
- ✅ Прямые IP whitelisted доменов (`178.248.239.157` timeweb, `95.163.48.30` mail.ru, `95.163.254.192` vk.com) — все открываются (TLS warning, но handshake прошёл)
- ❌ DigitalOcean IP — нет
→ Whitelist пропускает по **IP-подсетям**, не по строгому SNI.

**Тест 3 — наш main `81.200.146.32` (Timeweb) в whitelist?**
Запустили на main временный openssl s_server на :443. Друг открыл `https://81.200.146.32` на Yota → TLS warning (handshake прошёл). **Наш IP в whitelist.**

### 4. Деплой VLESS+WS+TLS на main с собственным доменом

Архитектура:
- `ru.vpnnkrns.ru` → A-запись на `81.200.146.32` (grey cloud)
- nginx на main: 80 → 301 → 443 (TLS termination), 443 → WS proxy на Xray
- Xray VLESS+WS на 127.0.0.1:10000
- Let's Encrypt cert для `ru.vpnnkrns.ru`, авто-renew

Тест с другом:
- На Wi-Fi работает: в nginx access log виден реальный трафик через WS (десятки сессий, до 4.2 МБ в одной)
- **На Yota не работает**: симптом «сетевое подключение прервано» — это TCP-handshake прошёл, потом RST. Сигнатура **DPI с SNI inspection**.

То есть IP в whitelist, но SNI `ru.vpnnkrns.ru` — нет. Yota DPI режет TLS Client Hello с не-whitelisted SNI.

### 5. Переход на VLESS+REALITY с whitelisted SNI

REALITY именно для этого: клиент шлёт TLS Client Hello с **whitelisted SNI** (`cloud.vk.com`), DPI пропускает, наш сервер расшифровывает VLESS-туннель внутри.

Архитектура:
- nginx на main:443 убран → освободили порт
- Xray на main:443 напрямую, REALITY-протокол
- SNI=`cloud.vk.com` → не сработал (cloud.vk.com отдаёт нестандартный TLS, ломает REALITY-fronting: `target sent incorrect server hello`)
- SNI=`cloud.mail.ru` → ✅ работает (стандартный TLS 1.3)

Серверная проверка:
- TLS-fronting на `81.200.146.32:443` с SNI=cloud.mail.ru отдаёт настоящий cert от VK LLC `*.cloud.mail.ru` — снаружи наш сервер выглядит как mirror Mail.ru Cloud

Тест с другом: «Всё работает! И так и так» (Wi-Fi + Yota).

Финальное подтверждение через тест `digitalocean.com` на Yota (друг — не открывается → **БС активны прямо сейчас**) → **REALITY с SNI=cloud.mail.ru работает на Мегафон/Yota при активных БС**.

### 6. apt upgrade на всех 3 серверах + reboot

В процессе подняли версии ядра / docker / прочих пакетов:
- **YC vrprnt** — apt upgrade, `sudo reboot`, kernel `6.8.0-117-generic`. Xray REALITY поднялся автоматом.
- **main Timeweb** — apt upgrade. Kernel update не было в этой партии, reboot не понадобился.
- **Fornex eu1** — apt upgrade включал docker-ce + libgnutls + rsync. Pending kernel update от прошлых апгрейдов. Сделали reboot — kernel `6.8.0-117-generic`. Все сервисы (Docker, контейнеры, Xray, nginx, vpn-bot, vpn-web) поднялись автоматически.

### 7. Обнаружение CRITICAL бага: AmneziaWG peers потерялись после reboot Fornex

Двое пользователей написали что их клиенты AmneziaVPN падают с Error 103 («Фоновая служба не запущена»). Web-панель показывала все handshakes как «никогда».

Диагностика:
- API `/api/traffic` возвращал `last_handshake: 0` для всех 18 users
- Серверный `docker exec amnezia-awg2 awg show awg0` показывал только 4 peer'а
- В `peers.json` — 30 пользователей
- В `/opt/amnezia/awg/awg0.conf` внутри контейнера — только 3 peer'а (initial install от AmneziaWG)

**Причина:** скрипт `/opt/amnezia-add-client.sh` после `awg set awg0 peer ...` вызывал `awg-quick save awg0 2>/dev/null || true`. Эта команда в нашем AmneziaWG-контейнере **fail-silent** (тихо проваливалась). Peers сохранялись только в running-state ядра WireGuard. При рестарте контейнера (от `docker restart` после apt upgrade docker-ce + от reboot Fornex) — все in-memory peers пропали, остались только те 3, что в `awg0.conf`.

**Исправление:**

1. Восстановили 21 active peer из `peers.json` обратно в running awg (`docker exec ... awg set ... peer ... allowed-ips ...`)
2. Сохранили running config в `awg0.conf` через `awg showconf awg0` + ручная вставка `Address = 10.8.1.0/24` (showconf не выводит Address)
3. Создан `/opt/amnezia-save-conf.sh` — общий helper, который правильно сохраняет
4. Patched `/opt/amnezia-add-client.sh` и `/opt/amnezia-remove-client.sh`: вместо `awg-quick save awg0 || true` → вызывают `/opt/amnezia-save-conf.sh`
5. Cron `*/5 * * * * /opt/amnezia-save-conf.sh` — safety net, чтобы даже ручные `awg set` сохранялись

Двое пользователей переустановили AmneziaVPN / перезагрузили ПК → подключились (Егорян «работает 👍»). Это была комбинация: их client-side Error 103 (на Windows) + наша серверная потеря peers.

### 8. Восстановление web-панели мониторинга

API `/api/traffic` теперь корректно показывает handshakes. На скриншоте: ID 5147045004 (10.8.1.9) — «сейчас» с трафиком `2.5 МБ / 98.6 МБ`. Это **бонусное доказательство** что fix реальный: пользователь подключился сразу после нашего восстановления peer'ов.

---

## Что изменилось в инфраструктуре

| Сервер | Что было | Что стало |
|--------|----------|-----------|
| **main Timeweb** (`81.200.146.32`) | Только WireGuard для RU users (1 активный пользователь) | + Xray VLESS+REALITY на :443, SNI=cloud.mail.ru, dest=cloud.mail.ru:443. Сертификат LE для `ru.vpnnkrns.ru` (для acme renewal). WireGuard на UDP/51820 остаётся |
| **Fornex eu1** (`185.21.8.91`) | AmneziaWG Docker, peers сохранялись в memory | AmneziaWG с правильным persistent-сохранением peers, cron каждые 5 мин |
| **YC vrprnt** (`158.160.236.147`) | Xray VLESS+REALITY, SNI=www.microsoft.com (T2/МТС/Билайн/Т-Мобайл) | Без изменений (работает) |
| **Cloudflare DNS** | — | + `ru` (A) → `81.200.146.32` (grey cloud) |
| **Бот для Мегафон/Yota** | Выдавал VLESS+XHTTP CDN (не работало) | Выдаёт VLESS+REALITY на main с cloud.mail.ru (работает) |

## Что осталось активным (для пользы, на «всякий случай»)

- **TLS-cert `cdn-vpnnkrns-cert`** в YC Certificate Manager для `cdn.vpnnkrns.ru` — бесплатный LE, может пригодиться
- **Cloud CDN ресурс** `cdn.vpnnkrns.ru` с HTTPS — может пригодиться для будущих экспериментов
- **`VLESS_CDN_SHARE_URL`** в env_vars (старая HTTP-CDN ссылка) — fallback если новая REALITY когда-то отвалится

## Что удалено по результату

- YC API Gateway `vpn-relay-gw` — удалён владельцем (несовместим с XHTTP)
- nginx server-block на main:443 — заменён на Xray REALITY на :443

## Файлы изменены / добавлены

- `bot/config.py`, `bot/main.py`, `env_vars.example.txt` — без изменений в этой сессии (логика уже была готова с прошлой сессии)
- `docs/scripts/nginx-ru-vpnnkrns.conf.example` — новый, текущий конфиг nginx на main (только :80 для ACME)
- `docs/scripts/xray-main-reality.json.example` — новый, текущий Xray REALITY на main
- `docs/scripts/amnezia-save-conf.sh.example` — новый, helper-скрипт
- `ROADMAP_VPN.md` — закрыта P2 Yota/Мегафон, добавлены follow-ups
- `DONE_LIST_VPN.md` — запись об этой сессии
- `CLAUDE.md` — обновлена инфраструктура (main с REALITY)
- `docs/sessions/SESSION_SUMMARY_2026-05-21.md` — этот файл

## Дополнение к сессии — recovery-передел (вечер 2026-05-21)

После основной работы вернулись и закрыли запаркованный пункт «полный передел recovery».

**Изменения в `web/app.py`:**
- Удалены legacy endpoint'ы по Telegram ID: `/api/recovery/vpn`, `/api/recovery/mobile-vpn`, `/api/recovery/telegram-proxy`, `/api/recovery/proxy-link`, `/api/recovery/vpn-by-email`
- Добавлен helper `_verify_email_session(body)` — общий auth по email-token из активной OTP-сессии (DRY для всех recovery endpoints)
- Добавлены 3 новых endpoint'a:
  - `POST /api/recovery/awg-config-by-email` — `{token, platform}` → AmneziaWG-конфиг для eu1, для android дополнительно возвращается `vpn_url` (deep link)
  - `POST /api/recovery/mobile-link-by-email` — `{token, operator}` → VLESS-ссылка, маршрутизация по оператору (megafon/yota → main REALITY cloud.mail.ru, остальные → eu1 REALITY www.microsoft.com)
  - `POST /api/recovery/proxy-link-by-email` — `{token}` → текущая `tg://proxy` ссылка

**Изменения в `web/templates/recovery.html`:**
- Полная перепись. Email/OTP → главное меню с 3 кнопками (Основной VPN / Мобильный резерв / MTProxy) → подстраница выбора (платформа или оператор) → результат.
- Кнопки «Назад» в подстраницах.

**Изменения в `web/static/recovery.js`:**
- Полная перепись под новый flow.
- Helper'ы `showStep`, `renderLinkBlock`, `downloadFile`.
- Android получает кликабельную кнопку «👆 Открыть в AmneziaVPN» с `vpn://` deep link.
- Error-103 fallback показывается сразу после выдачи AWG-конфига (инструкция про админа/переустановку/Hiddify).

**Изменения в `web/static/style.css`:**
- Добавлен класс `.btn-menu` — большие многострочные кнопки с подзаголовком, для меню каналов и выбора платформы/оператора.
- Класс `.btn-back` — компактная кнопка «Назад».

**Бот:**
- `docs/bot-instruction-texts/instruction_windows_short.txt` — добавлен блок про Error 103 (закрыть Amnezia*, запуск от админа, перезагрузка, Hiddify).

**Проверки:**
- Все 5 legacy endpoint'ов возвращают HTTP 404 (удалены).
- Все 3 новых endpoint'a возвращают HTTP 401 без token (валидный auth-стек).
- `/recovery` страница: HTTP 200.
- `vpn-web.service` поднялся, в логах ошибок нет.

**Что осталось открытым:** Персональные UUIDs для main REALITY (Мегафон/Yota) — добавлена задача в ROADMAP. Сейчас у всех Мегафон/Yota юзеров один общий UUID (упрощение, для биллинга позже сделаем персональные).

---

## Что передать следующему агенту

1. **Yota/Мегафон через REALITY работает**, используется `cloud.mail.ru` как SNI / dest. Если когда-то перестанет работать — рассмотри другие whitelisted домены с TLS 1.3 (тестированные: `cloud.mail.ru`, `www.yandex.ru`, `timeweb.cloud`). Не работают: `cloud.vk.com`, `mcs.mail.ru`, `selectel.ru` (нестандартный TLS).
2. **AmneziaWG persistent fix** — теперь add/remove client скрипты + cron сохраняют конфиг. При следующем reboot Fornex — peers НЕ должны теряться. Если всё-таки потерялись — повтори восстановление по шаблону из этой сессии (Python скрипт прохода по peers.json + `awg set ...`).
3. **`/api/traffic` бывает «никогда» для всех** — это симптом потерянных peers, не баг панели. Проверь `docker exec amnezia-awg2 awg show awg0 dump | wc -l` — должно совпадать с количеством active peers в peers.json.
4. Recovery-сайт всё ещё выдаёт старую EU1-VLESS-ссылку с SNI=www.microsoft.com (не работает на Yota). Можно обновить — задача в ROADMAP.
5. Бот всё ещё показывает в инструкции «Hiddify или v2rayNG» — это нормально для REALITY-ссылки, эти клиенты её поддерживают.
