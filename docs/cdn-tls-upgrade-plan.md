# План: апгрейд Yandex CDN на HTTPS (TLS) для cdn.vpnnkrns.ru

**Создано:** 2026-05-20
**Цель:** проверить гипотезу, что VLESS+XHTTP на Мегафон/Yota при БС не работает из-за HTTP (без TLS) — прозрачный прокси оператора ломает протокол.
**Стоимость:** ~30–60 минут, без рисков для prod (старая HTTP-ссылка может остаться как fallback).

---

## Гипотеза

| Канал | TLS на edge | Работает на Мегафон/Yota при БС? |
|-------|-------------|----------------------------------|
| Cloudflare CDN (sub.vpnnkrns.ru) + WS | ✅ HTTPS:443 | Работает (T2/МТС/Билайн подтверждено; Yota не тестировали отдельно) |
| Yandex CDN (cdn.vpnnkrns.ru) + XHTTP | ❌ HTTP:80 | **Не работает** (тест с другом 19.05.2026) |

Единственное архитектурное различие — TLS на edge. Прозрачный прокси Yota/Мегафон вмешивается в HTTP-трафик, но не может в HTTPS.

**Подтверждение от 20.05.2026:** друг на Yota открыл `http://cdn.vpnnkrns.ru/vpn` в браузере — страница загружается (пустая, что нормально для XHTTP endpoint без UUID). То есть **CDN endpoint доступен**, обрыв — на уровне HTTP-протокола в VPN-туннеле.

---

## Архитектура после апгрейда

```
Клиент Streisand (iOS)
  ↓ HTTPS:443 + TLS (sni=cdn.vpnnkrns.ru)
[Yandex CDN edge]  ← TLS terminate, валидный сертификат от Let's Encrypt
  ↓ HTTP:80 (по yccdn внутренней сети)
[Fornex 185.21.8.91:80]
  ↓ nginx → 127.0.0.1:8081 (XHTTP)
[Xray VLESS]
  ↓ direct outbound
[Интернет]
```

Серверная сторона (Fornex, nginx, Xray) **не меняется**.

---

## Что нужно сделать в YC Console (твоя часть)

### Шаг 1. Выпустить TLS-сертификат через YC Certificate Manager

YC Console → Certificate Manager → Создать сертификат → Let's Encrypt.

- **Имя:** `cdn-vpnnkrns-cert` (или любое)
- **Тип:** Let's Encrypt
- **Домены:** `cdn.vpnnkrns.ru`
- **Тип проверки:** **DNS** (через CNAME)
- Нажать "Создать"

После создания YC покажет:
- `_acme-challenge.cdn.vpnnkrns.ru` — **имя записи** для CNAME
- `<длинная строка>.acme.cm.yandexcloud.net` — **значение** CNAME

### Шаг 2. Добавить CNAME в Cloudflare DNS

Cloudflare → Dashboard → выбрать домен `vpnnkrns.ru` → DNS.

- Тип: `CNAME`
- Name: `_acme-challenge.cdn`
- Target: `<значение из YC>.acme.cm.yandexcloud.net`
- Proxy status: **DNS only** (grey cloud, без оранжевого облака)
- TTL: Auto

Сохранить.

### Шаг 3. Дождаться валидации сертификата

В YC Certificate Manager → сертификат `cdn-vpnnkrns-cert` → статус сменится с `Pending validation` → `Issued`. Обычно 5–15 минут.

Если зависло — проверить через `dig _acme-challenge.cdn.vpnnkrns.ru CNAME` или https://dnschecker.org, что CNAME уже прописался.

### Шаг 4. Привязать сертификат к Yandex CDN

YC Console → Cloud CDN → ресурс с `cdn.vpnnkrns.ru` → Изменить.

- В блоке HTTPS / TLS:
  - **Источник сертификата:** Certificate Manager
  - **Сертификат:** `cdn-vpnnkrns-cert` (тот, что выпустили на шаге 1)
- Сохранить.

### Шаг 5. Проверить, что HTTPS работает на edge

С любого устройства:
```
curl -v https://cdn.vpnnkrns.ru/vpn
```
Ожидаемо: TLS-handshake успешен, сертификат `cdn.vpnnkrns.ru` от Let's Encrypt, HTTP ответ от Xray (404 или пустой).

После шага 5 — пингани меня в чате, я сделаю серверную часть и подготовлю новую VLESS-ссылку.

---

## Что сделаю я (после твоего шага 5)

### Серверная часть

Ничего на Fornex менять не нужно — origin продолжает быть HTTP:80. Проверю что `nginx` корректно отдаёт ответы (curl с подменой Host).

### VLESS-ссылка

Старая (HTTP, не работает на Yota):
```
vless://359e23cc-...@cdn.vpnnkrns.ru:80?encryption=none&type=xhttp&path=%2Fvpn&host=cdn.vpnnkrns.ru#CDN-Whitelist-Relay
```

Новая (HTTPS+TLS):
```
vless://359e23cc-...@cdn.vpnnkrns.ru:443?encryption=none&security=tls&type=xhttp&path=%2Fvpn&host=cdn.vpnnkrns.ru&sni=cdn.vpnnkrns.ru#CDN-Whitelist-Relay-TLS
```

### env_vars.txt на Fornex

Добавить:
```
VLESS_CDN_TLS_SHARE_URL=vless://...
```

Старую `VLESS_CDN_SHARE_URL` оставить как fallback (на случай если TLS-вариант не сработает и нужно откатить).

### Бот

`bot/config.py`: добавить `vless_cdn_tls_share_url`.
`bot/main.py` `_send_mobile_vless`: для оператора Мегафон/Yota использовать TLS-ссылку (если задана), иначе fallback на старую.

### Тест с другом

Прислать новую ссылку → друг импортирует в Streisand на Yota при БС → подключается → проверяет работу VPN.

---

## Если TLS не помог

Сужение гипотезы будет такое: дело не в HTTP-перехвате прозрачным прокси. Тогда:

1. **Логи Streisand** — попросить друга прислать (Streisand → Settings → Logs).
2. **VLESS+WS вместо XHTTP через тот же CDN** — переключить транспорт, проверить.
3. **API Gateway** — `docs/yandex-api-gateway-plan.md`.
4. **Cloud Functions WS relay** — альтернативная архитектура.

---

## Риски / на что обратить внимание

- **Yandex CDN тарификация HTTPS.** Уточнить, не дороже ли HTTPS-трафик чем HTTP. По документации — одинаковая цена.
- **Перевыпуск сертификата.** Let's Encrypt = 90 дней. YC Certificate Manager перевыпускает автоматически. Проверить, что auto-renewal включён.
- **Cloudflare DNS зона.** Если CNAME `cdn` в Cloudflare настроен с orange cloud (proxy) — DNS-01 challenge не сработает (Cloudflare перехватывает). Должно быть grey cloud (DNS only). По SESSION_SUMMARY_2026-05-19 у нас уже grey cloud.

---

## Связанные документы

- `docs/sessions/SESSION_SUMMARY_2026-05-19.md` — начальная настройка Yandex CDN
- `docs/sessions/SESSION_SUMMARY_2026-05-20.md` — тест с другом, обнаружение проблемы
- `docs/yandex-api-gateway-plan.md` — альтернативный путь, если TLS не сработает
- `docs/blocking-bypass-strategy.md` — общая стратегия обхода блокировок
