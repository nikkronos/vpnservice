# POSTMORTEM: VLESS+XHTTP через Yandex CDN / API Gateway для Мегафон/Yota при БС

**Дата:** 2026-05-20
**Длительность сессии:** ~5 часов
**Результат:** ❌ Не решено. Все четыре проверенные гипотезы опровергнуты.

> **⚠️ ДЛЯ БУДУЩИХ АГЕНТОВ:** не повторяйте опровергнутые гипотезы из этого документа. Идите сразу к разделу "Что НЕ пробовать" и "Реалистичные следующие шаги".

---

## Краткое содержание

Задача: обеспечить работу VPN на Мегафон/Yota при активных белых списках РКН.

Текущий канал — VLESS+XHTTP через `cdn.vpnnkrns.ru` (Yandex CDN с CNAME-маршрутом на CDN-edge `*.yccdn.cloud.yandex.net`, origin = Fornex `185.21.8.91:80`).

Симптом: на Wi-Fi / других операторах (T2/МТС/Билайн через REALITY) — работает. На Мегафон/Yota (Streisand на iPhone) — клиент показывает "Connected", но трафик не идёт.

---

## Проверенные гипотезы (все отрицательные)

### Гипотеза 1: «Прозрачный прокси Мегафон/Yota ломает HTTP. Нужен TLS.»

**Что сделали:**
- Выпустили Let's Encrypt сертификат `cdn-vpnnkrns-cert` для `cdn.vpnnkrns.ru` через YC Certificate Manager (DNS-01 challenge через CNAME в Cloudflare).
- Привязали к Cloud CDN ресурсу.
- Edge заработал по HTTPS (curl подтвердил валидный TLS handshake, сертификат от Let's Encrypt R12).
- Обновили VLESS-ссылку: `vless://...@cdn.vpnnkrns.ru:443?security=tls&type=xhttp&...`
- Задеплоили в env_vars.txt + бот.

**Результат:** Streisand на Yota показывает "Connected", но трафик не идёт. На Wi-Fi с той же ссылкой — то же самое.

**Вывод:** Проблема **не в HTTP-перехвате**. И вообще не в Yota-сети — на Wi-Fi с той же ссылкой воспроизводится.

---

### Гипотеза 2: «XHTTP в режиме `auto`/`stream-up` плохо переносится через CDN. Нужен `packet-up`.»

**Что сделали:**
- На сервере Xray inbound на `127.0.0.1:8081` (XHTTP) добавили `"mode": "packet-up"` в `xhttpSettings`.
- В VLESS-ссылке добавили `&mode=packet-up`.
- Restart Xray, restart бота.

**Результат:** Streisand на Yota и Wi-Fi — то же самое. Connected, без трафика.

**Откат:** `mode` удалён из конфига Xray, возвращён `auto` (как было до сессии). Mode в VLESS-ссылке оставлен в env_vars.txt — клиенту понять параметр не помешает, серверу всё равно.

**Вывод:** Режим XHTTP не повлиял на симптом.

---

### Гипотеза 3: «Yandex CDN сам по себе ломает XHTTP. Yandex API Gateway даст другой endpoint, без CDN-цепочки.»

**Что сделали:**
- Создали YC API Gateway `vpn-relay-gw` (id: `d5dtgpmg79u2noup9iit`).
- Endpoint: `https://d5dtgpmg79u2noup9iit.wnq2w1o5.apigw.yandexcloud.net` (whitelisted Yandex-домен).
- OpenAPI спецификация с HTTP-integration на `http://185.21.8.91/vpn` и `http://185.21.8.91/vpn/{path}`.
- Проксирование заработало: запросы от IP API Gateway (`84.201.x.x`, `185.206.x.x`, `178.154.x.x`) появились в nginx access.log на Fornex.

**Результат:** Xray на сервере возвращает 400 на каждый запрос, потому что **API Gateway режет query string** (включая критический для XHTTP параметр `x_padding`).

Логи Xray подтвердили: `transport/internet/splithttp: invalid x_padding length:0` — сервер видит запросы без padding и отвергает.

**Попытка фикса 1:** Декларация query-параметра `x_padding` в OpenAPI спеке.
**Результат:** Не помогло. API Gateway всё равно режет query string.

**Попытка фикса 2:** URL template с явной подстановкой: `url: 'http://185.21.8.91/vpn/{path}?x_padding={x_padding}'`.
**Результат:** Запрос в API Gateway повис и **вообще не дошёл до Fornex** — в nginx access.log нет новых записей от IP API Gateway. То есть API Gateway не смог обработать template и проглотил запрос.

**Вывод:** **YC API Gateway фундаментально несовместим с XHTTP-протоколом.** Он:
1. По умолчанию не пробрасывает query string (даже задекларированные параметры).
2. С URL template для query — не справляется или режет длинные параметры.
3. Для XHTTP это критично, потому что `x_padding` может быть любой длины и **сервер обязан получить именно тот padding, что прислал клиент**.

---

### Гипотеза 4: «Может, дело в nginx-роутинге на Fornex (default_server).»

**Что сделали:**
- Изменили nginx-конфиг: XHTTP-блок (server_name `185.21.8.91`) стал `default_server`, чтобы запросы с любым Host попадали в правильный upstream (`127.0.0.1:8081` для XHTTP).

**Результат:** Не повлияло. Серверная сторона работала корректно и до этого (прямые curl-запросы к `http://localhost/vpn/<uuid>?x_padding=<long>` сервер принимал и держал XHTTP-сессию).

**Вывод:** nginx-роутинг не был проблемой. Default_server остался — это полезное улучшение для гибкости при будущих relay-экспериментах.

---

## Что мы знаем ТОЧНО на 2026-05-20

1. **Yandex CDN endpoint `cdn.vpnnkrns.ru` доступен на Мегафон/Yota при БС** (друг открыл `http://cdn.vpnnkrns.ru/vpn` в браузере без VPN — страница загружается).
2. **TLS на CDN работает технически** (curl показал валидный TLS handshake, сертификат от Let's Encrypt).
3. **На сервере Fornex Xray на XHTTP-inbound (8081) работает корректно** для прямых запросов с правильным padding.
4. **VLESS+XHTTP через Yandex CDN не работает у Streisand iOS** (ни на Wi-Fi, ни на Yota — симптом одинаковый).
5. **YC API Gateway не подходит для XHTTP** (режет query string).

---

## Что НЕ пробовать в следующих сессиях

| Гипотеза | Почему не работает |
|----------|---------------------|
| Перевыпустить сертификат с другого CA | TLS уже работает |
| Поменять mode в XHTTP (`auto` / `packet-up` / `stream-up` / `stream-one`) | Mode не влияет на симптом |
| Crank up `mode=packet-up` снова | Уже проверено |
| Сделать YC API Gateway с HTTP-integration | Режет query string, фундаментально несовместим с XHTTP |
| Поменять Cloudflare DNS-режим на orange cloud | Это сломает текущую CDN-цепочку, причина обрыва не в Cloudflare DNS |
| Изменить nginx-роутинг на Fornex | Серверная сторона работает, проблема не там |
| Поменять SNI на `www.microsoft.com` (как для REALITY) | SNI=`cdn.vpnnkrns.ru` валиден для нашего сертификата; смена SNI ломает TLS |

---

## Реалистичные следующие шаги (по убыванию приоритета)

### 1. VLESS+WS+TLS через API Gateway WebSocket-extension

API Gateway даёт отдельный WebSocket-endpoint (`wss://d5dtgpmg79u2noup9iit.wnq2w1o5.apigw.yandexcloud.net`). WebSocket в YC API Gateway — это не "прозрачный proxy", а событийная модель с тремя extensions:
- `x-yc-apigateway-websocket-connect` — обработка handshake
- `x-yc-apigateway-websocket-message` — обработка сообщений
- `x-yc-apigateway-websocket-disconnect` — обработка отключения

**Гипотеза:** если эти extensions можно использовать как passthrough к backend WebSocket (Xray inbound на `127.0.0.1:8080` через nginx), и API Gateway не режет WS-frames — VLESS+WS должен работать.

**Подводный камень:** документация YC показывает примеры с интеграциями типа `cloud_functions`, не `http`. Нужно проверить, поддерживается ли HTTP-backend для WebSocket.

**Затраты:** ~1–2 часа на тест.

**Документация:** https://yandex.cloud/ru/docs/api-gateway/concepts/extensions/websocket

### 2. Trojan-go / Hysteria2 / TUIC через YC

Альтернативные VPN-протоколы, которые не используют HTTP-туннелирование и могут лучше переноситься через Yandex-инфраструктуру.

**Главный недостаток:** требует другого Xray-клиента (Streisand может не поддерживать). Перенастройка всего стека.

**Затраты:** ~3–5 часов.

### 3. Поднять полноценный nginx-relay на YC Compute VM в собственной подсети

Создать новую YC Compute VM, поставить nginx с TLS-сертификатом для нашего домена, проксировать на Fornex. Полный контроль над transport.

**Главный недостаток:** YC Compute VM получит публичный IP, который **не в whitelist у мобильных операторов** (мы это уже знаем по тесту 2026-05-20 с `vrprnt`, IP `158.160.236.147`). То есть на Мегафон/Yota при БС этот VPS будет недоступен — пользователю надо будет проксировать через что-то whitelisted.

**Затраты:** ~2 часа, но фундаментально не решает whitelist-проблему.

### 4. VPS у whitelisted-провайдера (Selectel / VK Cloud / SberCloud)

Купить VPS у провайдера, чьи IP-блоки включены в whitelist РКН. Это самый прямой и дорогой путь.

**Затраты:** аренда VPS ~500-1000 ₽/мес + время на исследование, какие провайдеры реально в whitelist.

### 5. Yandex Cloud Functions с TCP/HTTP relay (последний резерв)

Cloud Function на `*.functions.yandexcloud.net` (whitelisted Yandex-домен). Функция написана на Python/Node — делает passthrough HTTP-запросов к Fornex.

**Главный недостаток:** функции имеют timeout (по умолчанию ~10 минут максимум), не подходят для long-lived VPN-сессий.

**Затраты:** ~3 часа.

---

## Что было задеплоено и осталось активным

| Компонент | Состояние |
|-----------|-----------|
| Сертификат `cdn-vpnnkrns-cert` в YC Certificate Manager | **Оставлен** (привязан к CDN HTTPS, бесплатный, может пригодиться) |
| Yandex CDN ресурс `cdn.vpnnkrns.ru` с HTTPS | **Оставлен** (HTTPS на edge работает, может пригодиться для WS+TLS) |
| YC API Gateway `vpn-relay-gw` | **Удалён владельцем** |
| Xray inbound на `127.0.0.1:8081` (XHTTP) | Без изменений (mode=auto, как до сессии) |
| nginx default_server на блок `185.21.8.91` | **Оставлен** (полезное улучшение, не вредит) |
| env_vars.txt: `VLESS_CDN_TLS_SHARE_URL` | **Оставлен** (бот отдаёт TLS-ссылку Мегафон/Yota, разницы с HTTP-вариантом по факту нет — обе не работают) |
| env_vars.txt: `VLESS_CDN_SHARE_URL` (старая HTTP) | Оставлен как fallback |
| bot/config.py, bot/main.py | **Деплой остался** (commit `ca1d187`). Логика: для оператора Мегафон/Yota приоритет TLS → HTTP → REALITY. |

---

## Ссылки на коммиты сессии

- `b012a0b` — docs: expand roadmap + APIGW plan + initial session log
- `216b92a` — docs: correct CDN status — confirmed broken on Megafon/Yota
- `57ee38b` — docs: add CDN HTTPS upgrade plan as primary path
- `ca1d187` — feat(bot): add VLESS_CDN_TLS_SHARE_URL with priority over plain HTTP CDN

## Связанные документы

- `docs/cdn-tls-upgrade-plan.md` — план апгрейда на TLS, выполнен, не сработал
- `docs/yandex-api-gateway-plan.md` — план API Gateway, выполнен, не сработал
- `docs/sessions/SESSION_SUMMARY_2026-05-20.md` — хронология сессии
- `docs/blocking-bypass-strategy.md` — общая стратегия обхода блокировок
