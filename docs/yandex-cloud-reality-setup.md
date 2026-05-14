# Yandex Cloud — VLESS+REALITY relay (резерв для LTE whitelist-режима)

**Создано:** 2026-05-06  
**Назначение:** Резервный VPN-узел на Yandex Cloud для работы в условиях whitelist-режима на LTE (когда российские операторы пропускают только одобренные IP). Yandex Cloud IP находится в whitelist у всех операторов.

---

## Инфраструктура

| Параметр | Значение |
|---------|---------|
| **Провайдер** | Yandex Cloud (console.yandex.cloud) |
| **Аккаунт** | cloud-kronos-lolly |
| **Тариф** | Платёжный аккаунт (грант 4000₽ для новых) |
| **VM имя** | vrprnt |
| **Публичный IP** | 158.160.236.147 |
| **Внутренний IP** | 10.130.0.8 |
| **Зона** | ru-central1-d |
| **Платформа** | standard-v4a, Shared-core 20% |
| **vCPU / RAM** | 2 vCPU / 1 ГБ |
| **Диск** | 10 ГБ SSD |
| **ОС** | Ubuntu 24.04 LTS |
| **Стоимость** | ~1340₽/мес (покрывается грантом) |

---

## Xray конфигурация на VM

**Протокол:** VLESS + REALITY (xHTTP packet-up, порт 443)  
**SNI:** `www.microsoft.com` (трафик выглядит как обращение к Microsoft)  
**Конфиг:** `/usr/local/etc/xray/config.json`

> **Изменено 2026-05-09:** транспорт TCP → xHTTP packet-up для обхода ТСПУ-заморозки сессий после 15–20 КБ.  
> **Изменено 2026-05-14:** SNI `www.yandex.ru` → `www.microsoft.com`. Причина: MegaFon/Yota имеет прозрачный прокси для .ru-доменов, который перехватывал REALITY-рукопожатие. Диагностика подтвердила: TCP до YC IP с Yota проходит (HTTP 406 в браузере), но VLESS-соединение рвалось. Смена SNI на нейтральный зарубежный домен устраняет перехват.

```json
{
  "log": {"loglevel": "info"},
  "inbounds": [{
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{"id": "11dd653c-944b-4320-b29e-f1a9f2d75db8"}],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "xhttp",
      "security": "reality",
      "realitySettings": {
        "dest": "www.microsoft.com:443",
        "serverNames": ["www.microsoft.com"],
        "privateKey": "uAEjBbdwuIwnUAxV91gSeFfUSmZyXOVAH4t-l9HegW4",
        "shortIds": ["ad88588f88ea4246"]
      },
      "xhttpSettings": {"mode": "packet-up", "path": "/download"}
    }
  }],
  "outbounds": [
    {
      "tag": "eu1",
      "protocol": "vless",
      "settings": {
        "vnext": [{
          "address": "185.21.8.91",
          "port": 80,
          "users": [{"id": "359e23cc-f90c-4e43-97af-bd1b662ff043", "encryption": "none"}]
        }]
      },
      "streamSettings": {
        "network": "ws",
        "security": "none",
        "wsSettings": {"path": "/vpn"}
      }
    },
    {"tag": "direct", "protocol": "freedom"}
  ],
  "routing": {
    "rules": [{"type": "field", "outboundTag": "eu1", "network": "tcp,udp"}]
  }
}
```

---

## Клиентские параметры

| Параметр | Значение |
|---------|---------|
| **UUID** | `11dd653c-944b-4320-b29e-f1a9f2d75db8` |
| **PublicKey** | `XKK9qJfFVdG3fegYC5vP8uF-OIzYK6YzKPz-sLVh_lE` |
| **ShortId** | `ad88588f88ea4246` |
| **SNI** | `www.microsoft.com` |
| **Fingerprint** | `chrome` |
| **Transport** | `xhttp` |
| **Mode** | `packet-up` |
| **Path** | `/download` |
| **Port** | `443` |

**VLESS-ссылка:**
```
vless://11dd653c-944b-4320-b29e-f1a9f2d75db8@158.160.236.147:443?encryption=none&security=reality&sni=www.microsoft.com&fp=chrome&pbk=XKK9qJfFVdG3fegYC5vP8uF-OIzYK6YzKPz-sLVh_lE&sid=ad88588f88ea4246&type=xhttp&mode=packet-up&path=%2Fdownload#YC-Reality
```

**В боте:** команда `/mobile_vpn` — отправляет эту ссылку.  
**Клиент:** Streisand (iOS), v2rayTun mode.

---

## Сетевые правила (Yandex Cloud Security Group)

Группа: `default-sg-enp7c63osmhkkqeo3q3v`  
Добавлено правило входящего трафика:
- Протокол: TCP
- Порт: 443
- Источник: 0.0.0.0/0

UFW на VM: разрешены OpenSSH и 443/tcp.

---

## SSH доступ

```bash
ssh ubuntu@158.160.236.147
# или
ssh root@158.160.236.147  # после sudo -i
```

Ключ: `C:\Users\krono\.ssh\id_ed25519`

---

## Управление сервисом

```bash
systemctl status xray
systemctl restart xray
journalctl -u xray -f
```

---

## Почему именно Yandex Cloud

- IP из AS Yandex (AS200350) — гарантированно в whitelist у всех российских операторов
- Блокировка Yandex Cloud = блокировка тысяч российских сервисов (невозможно на практике)
- REALITY с SNI `www.microsoft.com` — трафик неотличим от HTTPS к Microsoft
- ⚠️ SNI `www.yandex.ru` не использовать: MegaFon/Yota перехватывает TLS для .ru-доменов (прозрачный прокси), REALITY-рукопожатие ломается. Смена на нейтральный зарубежный SNI решает проблему.

---

## Известные проблемы при настройке

| Проблема | Решение |
|---------|---------|
| `error: You must run this script as root` | `sudo -i` перед запуском скрипта установки |
| `empty "privateKey"` в конфиге | Переменные bash не раскрываются в heredoc корректно; использовать Python для записи config.json |
| Markdown-ссылки в конфиге (`sni=[www.yandex.ru](...)`) | Копировать команды только из plain text, не из rendered markdown; использовать Python для записи |
| Xray не слушает порт 443 | Проверить `systemctl status xray`; перезапустить после исправления конфига |

---

## Проверка после следующего whitelist-ограничения

Следующий раз когда операторы включат whitelist (предположительно праздники):
1. Выключить основной VPN (AmneziaWG)
2. Подключиться к `YC-Reality` в Streisand
3. Проверить доступность интернета на LTE
4. Задокументировать результат в DONE_LIST_VPN.md
