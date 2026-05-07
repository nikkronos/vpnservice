# Резюме сессии 2026-05-06

## Контекст

**Санкт-Петербург, 6 мая 2026.** Продолжение работы после сессии 2026-05-05, где Cloudflare CDN оказался заблокирован в whitelist-режиме. Цель: найти IP, гарантированно входящий в whitelist мобильных операторов, и построить на нём VPN-резерв.

LTE whitelist был активен вчера (5 мая), сегодня (6 мая) ограничения сняты — но задача создать резерв на следующий раз осталась актуальной.

---

## Диагностика

**Проверка Timeweb (81.200.146.32) на LTE:**
- Браузер телефона → `http://81.200.146.32` → тайм-аут
- **Вывод:** Timeweb тоже заблокирован в whitelist-режиме. Блокируются не только зарубежные, но и российские хостинги, не входящие в конкретный whitelist операторов.

---

## Решение: Yandex Cloud VM

**Логика:** Yandex Cloud IP (AS200350) гарантированно входит в whitelist любого российского оператора — блокировка Yandex Cloud = блокировка тысяч российских сервисов.

**VLESS+REALITY с SNI `www.yandex.ru`:** трафик визуально неотличим от обращения к Яндексу.

---

## Что настроено

### Yandex Cloud VM

| Параметр | Значение |
|---------|---------|
| Аккаунт | cloud-kronos-lolly |
| VM имя | vrprnt |
| Публичный IP | **158.160.236.147** |
| Зона | ru-central1-d |
| Конфигурация | Shared-core, 2 vCPU 20%, 1 ГБ RAM, 10 ГБ SSD |
| ОС | Ubuntu 24.04 LTS |
| Стоимость | ~1340₽/мес (покрывается грантом 4000₽) |

Платёжный аккаунт создан с привязкой карты МИР — активирован грант 4000₽ для новых пользователей.

Security Group: добавлено входящее правило TCP 443 → 0.0.0.0/0.

SSH ключ: `C:\Users\krono\.ssh\id_ed25519` (ED25519, создан в этой сессии).

### Xray на YC VM

**Конфиг** `/usr/local/etc/xray/config.json`:

```json
{
  "log": {"loglevel": "info"},
  "inbounds": [{
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{"id": "11dd653c-944b-4320-b29e-f1a9f2d75db8", "flow": "xtls-rprx-vision"}],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "dest": "www.yandex.ru:443",
        "serverNames": ["www.yandex.ru"],
        "privateKey": "uAEjBbdwuIwnUAxV91gSeFfUSmZyXOVAH4t-l9HegW4",
        "shortIds": ["ad88588f88ea4246"]
      }
    },
    "sniffing": {"enabled": true, "destOverride": ["http","tls","quic"]}
  }],
  "outbounds": [{"protocol": "freedom"}]
}
```

Клиентские параметры:
- UUID: `11dd653c-944b-4320-b29e-f1a9f2d75db8`
- PublicKey: `XKK9qJfFVdG3fegYC5vP8uF-OIzYK6YzKPz-sLVh_lE`
- ShortId: `ad88588f88ea4246`

**VLESS-ссылка:**
```
vless://11dd653c-944b-4320-b29e-f1a9f2d75db8@158.160.236.147:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.yandex.ru&fp=chrome&pbk=XKK9qJfFVdG3fegYC5vP8uF-OIzYK6YzKPz-sLVh_lE&sid=ad88588f88ea4246&type=tcp&headerType=none#YC-Reality
```

### Бот

`VLESS_REALITY_SHARE_URL` в `/opt/vpnservice/env_vars.txt` на Fornex обновлена на YC-Reality ссылку (через Python, т.к. sed/heredoc давали markdown-артефакты).

`vpn-bot.service` перезапущен. Команда `/mobile_vpn` теперь отдаёт YC-Reality ссылку.

---

## Проблемы при настройке

| Проблема | Причина | Решение |
|---------|---------|---------|
| `error: You must run this script as root` | Xray install script требует root | `sudo -i` перед запуском |
| `empty "privateKey"` в конфиге Xray | Переменные bash не раскрываются корректно в heredoc | Запись конфига через Python (`json.dump`) |
| Markdown-ссылки в env_vars.txt и config.json | Копирование из rendered markdown (chat interface добавлял `[url](url)`) | Запись через Python напрямую |
| Xray падает с `status=23` | Невалидный конфиг (markdown в `dest`) | Перегенерация ключей + запись через Python |

---

## Статус после сессии

| Компонент | Статус |
|-----------|--------|
| Yandex Cloud VM (158.160.236.147) | ✅ Running |
| Xray VLESS+REALITY на YC VM | ✅ Active, port 443 |
| Бот `/mobile_vpn` → YC-Reality | ✅ Настроен |
| AmneziaWG (eu1) | ✅ Не тронут |
| Cloudflare CDN стек (sub.vpnnkrns.ru) | ⚙️ Сохранён, Xray WS port 80 на eu1 |
| Тест YC-Reality на LTE whitelist | ⏳ Ожидает следующего ограничения |

---

## Что делать дальше

1. **При следующем whitelist-режиме на LTE:** подключиться к `YC-Reality` в Streisand, проверить работу, задокументировать результат.
2. **Если YC-Reality не работает в whitelist:** вероятно, изменился whitelist или Yandex Cloud IP не входит — исследовать какие конкретно IP разрешены.
3. **Оптимизация стоимости YC VM:** попробовать включить прерываемую VM (не нашли опцию в интерфейсе при создании) — снизит стоимость с ~1340 до ~400₽/мес.

---

## Для следующего агента

- **YC VM:** `ssh ubuntu@158.160.236.147` (ключ `~/.ssh/id_ed25519`); Xray конфиг — см. выше или `docs/yandex-cloud-reality-setup.md`
- **Бот:** если нужно обновить VLESS ссылку — редактировать `VLESS_REALITY_SHARE_URL` в `/opt/vpnservice/env_vars.txt` на Fornex (через Python, не sed/heredoc), перезапустить `vpn-bot.service`
- **Markdown-ловушка:** при копировании URL из chat-интерфейса всегда проверять что `www.yandex.ru` не превратился в `[www.yandex.ru](https://...)` в файле
