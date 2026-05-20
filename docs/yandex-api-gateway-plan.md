# План: Yandex API Gateway как relay для Мегафон/Yota при БС

**Создано:** 2026-05-20
**Статус:** план, не реализован
**Назначение:** альтернатива Yandex CDN relay для случаев, когда CDN-endpoint недоступен на Yota/Мегафон при активных белых списках.

---

## Контекст

Текущая попытка обхода БС — `cdn.vpnnkrns.ru` (Yandex CDN, XHTTP). Технически работает (логи nginx подтверждают XHTTP-запросы 19.05.2026 от двух клиентов), но **реального подтверждения работы на Yota/Мегафон при активных БС нет**. Возможные причины недоступности:

- Cloudflare DNS (grey cloud) перед Yandex CDN — DNS-цепочка может ломаться при БС
- Сам домен `cdn.vpnnkrns.ru` не в whitelist (whitelist на уровне SNI/Host, а не IP)
- Прозрачный прокси Мегафон/Yota для российских доменов перехватывает соединение (см. `yandex-cloud-reality-setup.md` — фикс с `.ru` → `www.microsoft.com` для REALITY)

API Gateway даёт **нативный домен `*.apigw.yandexcloud.net`** — без посредников DNS, на инфраструктуре Yandex Cloud (которая в whitelist).

---

## Что нужно проверить ДО реализации

1. **DNS-резолв `cdn.vpnnkrns.ru` на Yota при БС.**
   Если домен не резолвится — это и есть причина текущей неработоспособности; API Gateway с нативным `*.apigw.yandexcloud.net` решит проблему.
   Команда для проверки (с устройства на Yota без VPN при БС):
   ```
   nslookup cdn.vpnnkrns.ru 8.8.8.8
   nslookup cdn.vpnnkrns.ru 77.88.8.8       # Yandex DNS
   ```

2. **HTTPS-доступ к `*.apigw.yandexcloud.net` на Yota при БС.**
   Создать минимальный API Gateway (любой Hello-World) → попробовать открыть с Yota без VPN.
   Если открывается — endpoint в whitelist, идём дальше.
   Если не открывается — гипотеза не сработала, ищем другие варианты.

---

## Архитектура (если проверки пройдут)

```
Клиент (Yota/Мегафон)
   ↓ HTTPS, *.apigw.yandexcloud.net
[Yandex API Gateway]
   ↓ HTTP proxy / WebSocket
[Fornex 185.21.8.91:80] ← nginx (server_name = host от API Gateway)
   ↓
[Xray VLESS+WS на 127.0.0.1:8080] или [Xray VLESS+XHTTP на 127.0.0.1:8081]
```

API Gateway работает на HTTPS (443), даёт собственный TLS-сертификат. Это значит трафик от клиента до API Gateway шифруется, а от API Gateway до Fornex может идти по HTTP (порт 80) — внутри инфраструктуры YC → интернет.

---

## Пошаговая реализация

### Шаг 1. Создать API Gateway в YC Console

Аккаунт: `cloud-kronos-lolly` (тот же, что использовался для VLESS+REALITY VM).

YC Console → Serverless → API Gateway → Создать.

- Имя: `vpn-relay-gw` (или любое)
- Описание: `WebSocket/HTTP proxy to Fornex for whitelist bypass`
- Зона: ru-central1 (любая в default folder)
- Спецификация (OpenAPI 3.0 + Yandex extensions):

```yaml
openapi: 3.0.0
info:
  title: vpn-relay-gw
  version: 1.0.0
paths:
  /vpn:
    get:
      x-yc-apigateway-integration:
        type: http
        url: http://185.21.8.91:80/vpn
        method: GET
        timeouts:
          read: 30s
          connect: 5s
  /vpn/{tail+}:
    get:
      parameters:
        - name: tail
          in: path
          required: true
          schema:
            type: string
      x-yc-apigateway-integration:
        type: http
        url: http://185.21.8.91:80/vpn/{tail}
        method: GET
    post:
      parameters:
        - name: tail
          in: path
          required: true
          schema:
            type: string
      x-yc-apigateway-integration:
        type: http
        url: http://185.21.8.91:80/vpn/{tail}
        method: POST
```

Для WebSocket — отдельный путь с `x-yc-apigateway-integration: type: websocket` (если YC API Gateway это поддерживает; проверить документацию: https://cloud.yandex.ru/docs/api-gateway/concepts/extensions/websocket).

### Шаг 2. Получить endpoint

После создания gateway даёт URL вида `https://d5dxxxxxxxxxxxxx.apigw.yandexcloud.net`. Этот URL — наш новый relay-endpoint.

### Шаг 3. Тест без VPN на Yota при БС

С устройства на Yota без VPN открыть в браузере:
- `https://<id>.apigw.yandexcloud.net/vpn` — должен отдать что-то (например 404 от Xray, что значит соединение проходит)

**Контрольная точка:** если открывается — Gateway в whitelist, идём дальше. Если нет — план не работает, возвращаемся к поиску альтернатив.

### Шаг 4. Адаптировать Fornex nginx

Добавить в `/etc/nginx/sites-enabled/xray-router` блок для запросов от API Gateway. Запросы будут приходить с Host = `<id>.apigw.yandexcloud.net` (или с переписанным Host, в зависимости от настроек integration).

Вариант: универсальный default-блок, не привязанный к Host:

```nginx
server {
    listen 80 default_server;

    location /vpn {
        proxy_pass http://127.0.0.1:$xray_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $http_connection;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
```

### Шаг 5. Сформировать VLESS-ссылку

Если работает WebSocket:
```
vless://359e23cc-f90c-4e43-97af-bd1b662ff043@<id>.apigw.yandexcloud.net:443?encryption=none&security=tls&type=ws&path=%2Fvpn&host=<id>.apigw.yandexcloud.net&sni=<id>.apigw.yandexcloud.net#APIGW-Whitelist-Relay
```

Если работает только HTTP/XHTTP:
```
vless://359e23cc-f90c-4e43-97af-bd1b662ff043@<id>.apigw.yandexcloud.net:443?encryption=none&security=tls&type=xhttp&path=%2Fvpn&host=<id>.apigw.yandexcloud.net&sni=<id>.apigw.yandexcloud.net#APIGW-Whitelist-Relay
```

Добавить в `/opt/vpnservice/env_vars.txt`:
```
VLESS_APIGW_SHARE_URL=vless://...
```

### Шаг 6. Бот: обновить кнопку Мегафон/Yota

`bot/config.py` — добавить `vless_apigw_share_url`.
`bot/main.py` `_send_mobile_vless` — для оператора Мегафон/Yota использовать APIGW ссылку вместо CDN.

Старую `VLESS_CDN_SHARE_URL` оставить как фоллбек (на случай если APIGW перестанет работать).

---

## Риски и ограничения

1. **Лимиты API Gateway.** Бесплатный план: 100k запросов / 1 ГБ исходящего в месяц. WebSocket-сессия = долгое соединение, может расходовать лимиты иначе. Проверить тарификацию для WS.
2. **WebSocket поддержка.** Документация YC API Gateway упоминает WebSocket, но требует подтверждения, что он работает в режиме transparent proxy (без преобразования протокола).
3. **Latency.** API Gateway добавляет hop в цепочку — клиент → YC API Gateway → Fornex. Может быть заметно при плохой связи.
4. **ToS Yandex Cloud.** API Gateway не предназначен для проксирования произвольного трафика. Юридически серая зона.

---

## Альтернативы, если API Gateway не подойдёт

1. **Cloud Functions с WebSocket.** Serverless функция как WS-relay. Тоже на `*.cloudfunctions.yandexcloud.net` или `*.apigw.yandexcloud.net`.
2. **YC Object Storage с CORS.** Маловероятно — Object Storage не проксирует.
3. **YC Container Registry / Container Optimized Compute.** Своя VM с публичным IP внутри YC — но это уже есть (`158.160.236.147`), и IP не в whitelist.
4. **YC Application Load Balancer + Yandex CDN с WebSocket через тех. поддержку.** Самый сложный путь, но в теории даёт нативный WS через CDN.

---

## Связанные документы

- `blocking-bypass-strategy.md` — общая стратегия обхода блокировок
- `yandex-cloud-reality-setup.md` — текущая REALITY-инфраструктура в YC
- `docs/sessions/SESSION_SUMMARY_2026-05-19.md` — детали по текущему CDN relay
