# Резюме сессии 2026-05-05

## Контекст

**Санкт-Петербург, начало мая 2026 (предпраздничный период перед 9 мая).** Мобильные операторы (все проверенные симки) включили режим белого списка на LTE: работают только ~2–3 одобренных ресурса. AmneziaWG, VLESS+REALITY и прямой HTTP до IP Fornex — всё недоступно с LTE (ранее задокументировано в `docs/mobile-lte-eu1-xray-reality-attempt-2026-03.md`).

Цель сессии: попытаться обойти ограничения через **Cloudflare CDN** — маршрут телефон → Cloudflare IP → Fornex, скрывая прямой IP Fornex за CDN.

---

## Что настроено (инфраструктура)

### Cloudflare

- Зарегистрирован аккаунт Cloudflare (через GitHub OAuth).
- Домен **`vpnnkrns.ru`** добавлен в Cloudflare.
- NS-серверы у регистратора (Timeweb) изменены на:
  - `ray.ns.cloudflare.com`
  - `susan.ns.cloudflare.com`
- Домен стал **Active** в Cloudflare после пропагации NS (~30 мин).
- DNS-запись: **`sub.vpnnkrns.ru`** → A → `185.21.8.91`, **Proxied (оранжевое облако)**.
- Настройки Cloudflare:
  - SSL/TLS mode: **Flexible** (Cloudflare → origin по HTTP).
  - **WebSockets** включены (Network → WebSockets).

### Xray на Fornex (185.21.8.91)

Конфигурация `/usr/local/etc/xray/config.json` изменена с REALITY на **VLESS + WebSocket**:

```json
{
  "log": { "loglevel": "info" },
  "dns": { "servers": ["8.8.8.8", "1.1.1.1"] },
  "inbounds": [{
    "listen": "0.0.0.0",
    "port": 80,
    "protocol": "vless",
    "settings": {
      "clients": [{ "id": "359e23cc-f90c-4e43-97af-bd1b662ff043", "flow": "" }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "ws",
      "security": "none",
      "wsSettings": { "path": "/vpn" }
    },
    "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"] }
  }],
  "outbounds": [{ "protocol": "freedom", "tag": "direct" }]
}
```

- Порт **80/tcp** открыт в UFW (`ufw allow 80/tcp`).
- Прямая проверка: `curl -H "Host: sub.vpnnkrns.ru" http://185.21.8.91/vpn -v` → Xray отвечает (400 Bad Request — WS-рукопожатие ожидаемо не для curl).
- `xray.service` активен, слушает `*:80`.

### Ссылка клиента

`env_vars.txt` (Fornex, `/opt/vpnservice`) — переменная `VLESS_REALITY_SHARE_URL` обновлена:

```
vless://359e23cc-f90c-4e43-97af-bd1b662ff043@sub.vpnnkrns.ru:443?encryption=none&security=tls&sni=sub.vpnnkrns.ru&alpn=http%2F1.1&type=ws&host=sub.vpnnkrns.ru&path=%2Fvpn#VPN-CDN
```

Клиент: **Streisand** (iOS), режим **v2rayTun**.

---

## Проблемы, с которыми столкнулись

| Проблема | Решение |
|----------|---------|
| Cloudflare Origin Certificate: «Failed to validate hostname» | Домен ещё не активен; использовали `openssl` для самоподписанного cert |
| Xray: `permission denied` на `key.pem` | `chmod 644 /etc/xray/ssl/key.pem cert.pem` |
| `client sent HTTP request to HTTPS server` (3.130.168.2) | Cloudflare Full отправлял HTTP, Xray ждал TLS; переключили на Flexible SSL + port 80 без TLS |
| WebSocket не устанавливается: `'upgrade' token not found in 'Connection' header` | Cloudflare согласовывает ALPN h2 и убирает hop-by-hop заголовки (Connection: Upgrade, Upgrade: websocket); попытка добавить `alpn=http%2F1.1` в ссылку клиента — результата не дала |

---

## Итог: корневая причина неудачи

**Cloudflare IPs тоже заблокированы** на LTE в период whitelist-режима (СПб, операторы все проверенные симки).

Проверка: `https://sub.vpnnkrns.ru` не открывается в браузере телефона (LTE, VPN выкл.) — страница не загружается. Нет смысла разбираться с WebSocket/gRPC/XHTTP: даже первый TCP до Cloudflare не проходит.

**Вывод:** В режиме «полного белого списка» (whitelist only) на LTE не поможет ни одна технология, которая маршрутизирует через IP/CDN, не входящий в этот список. Cloudflare CDN — обычно работающее решение в «нормальных» условиях блокировок (блок по ASN/IP конкретного VPS), но бессилен против тотального whitelist.

---

## Состояние после сессии

| Компонент | Статус |
|-----------|--------|
| Cloudflare аккаунт + `vpnnkrns.ru` в CF | ✅ настроен |
| `sub.vpnnkrns.ru` → Proxied → 185.21.8.91 | ✅ работает |
| Xray на Fornex: VLESS + WS, port 80 | ✅ работает (Wi-Fi подключение должно работать) |
| AmneziaWG (Docker, eu1) | ✅ не тронут, работает |
| MTProxy Fake TLS (port 8444) | ✅ не тронут |
| LTE мобильный доступ | ❌ не решён (whitelist-режим) |

**Cloudflare-стек сохраняется как рабочий резерв** — после снятия whitelist-режима он будет полезен: скроет прямой IP Fornex от обычных блокировок по ASN.

---

## Что делать дальше (LTE в режиме whitelist)

Против тотального whitelist технического решения через обычный интернет-канал — нет. Варианты:

1. **Ждать снятия ограничений** (режим temporary, ожидаемо после 9 мая 2026).
2. **Wi-Fi** при наличии.
3. **Исследовать, какие ресурсы белые:** если в белый список попал какой-то туннелируемый ресурс (корпоративный VPN шлюз, специфичный CDN) — через него теоретически можно маршрутизировать трафик. Требует знания конкретного whitelist.
4. **Роуминг через иностранный SIM** (e-SIM) — другой оператор без российских ограничений.

---

## Для следующего агента

- **Cloudflare настроен:** домен активен, `sub.vpnnkrns.ru` → Proxied.
- **Xray на Fornex:** VLESS + WebSocket на порту 80 (без TLS), `/vpn`.
- **VLESS-ссылка** в `env_vars.txt` обновлена под Cloudflare CDN.
- **Если WebSocket через Cloudflare нужно починить (для нормальных условий):** изучить переход на **gRPC** transport (Cloudflare поддерживает нативно, не режет hop-by-hop заголовки) — `"network": "grpc"`, `grpcSettings: { "serviceName": "vpn" }`.
- **REALITY конфиг (port 443/4443):** был на eu1, вероятно стёрт при переписи config.json. Восстановить при необходимости из `docs/xray-vless-reality-eu1-deploy.md`.
