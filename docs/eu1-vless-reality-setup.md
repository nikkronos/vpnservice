# eu1 — VLESS+REALITY (per-user, обычный режим)

**Создано:** 2026-05-14  
**Назначение:** Альтернатива AmneziaWG для удобного импорта через `vless://` ссылку. Работает в обычном режиме. В whitelist-режиме на LTE — использовать `/mobile_vpn` (YC).

---

## Инфраструктура

| Параметр | Значение |
|---------|---------|
| **Сервер** | eu1, Fornex (185.21.8.91) |
| **Порт** | 443/TCP |
| **Протокол** | VLESS + REALITY + xtls-rprx-vision |
| **Transport** | TCP |
| **SNI / dest** | `www.microsoft.com:443` |
| **Конфиг** | `/usr/local/etc/xray/config.json` (второй inbound) |

> **Примечание:** первый inbound (порт 80, VLESS+WS) — приёмный конец YC-релея, не трогать.

---

## Xray inbound (добавлен к существующему config.json)

```json
{
  "listen": "0.0.0.0",
  "port": 443,
  "protocol": "vless",
  "settings": {
    "clients": [
      {"id": "<UUID пользователя>", "flow": "xtls-rprx-vision"}
    ],
    "decryption": "none"
  },
  "streamSettings": {
    "network": "tcp",
    "security": "reality",
    "realitySettings": {
      "dest": "www.microsoft.com:443",
      "serverNames": ["www.microsoft.com"],
      "privateKey": "AHTtsR3ntxxAuSMhA2Iztlo_nE8uEBL56fpO3ZZrQ3g",
      "shortIds": ["<shortId пользователя>"]
    }
  }
}
```

---

## Ключи REALITY (eu1-specific, не менять без необходимости)

| Параметр | Значение |
|---------|---------|
| **Private key** | `AHTtsR3ntxxAuSMhA2Iztlo_nE8uEBL56fpO3ZZrQ3g` |
| **Public key** | `JjUIhhSWTWGLjYBn9DSou0q_RiBqIaGl4Af7MCjQ0iQ` |

> ⚠️ Private key хранится только на сервере в `/usr/local/etc/xray/config.json`. В репозиторий не коммитится.

---

## Текущие клиенты

| Пользователь | UUID | shortId | Добавлен |
|-------------|------|---------|----------|
| owner (тест) | `44af9414-81d5-4baa-ac54-689f2c896c0d` | `04d9b6c0` | 2026-05-14 |

---

## Формат vless:// ссылки

```
vless://<UUID>@185.21.8.91:443?encryption=none&security=reality&sni=www.microsoft.com&fp=chrome&pbk=JjUIhhSWTWGLjYBn9DSou0q_RiBqIaGl4Af7MCjQ0iQ&sid=<shortId>&type=tcp&flow=xtls-rprx-vision#EU1-VLESS
```

**Тестовая ссылка владельца:**
```
vless://44af9414-81d5-4baa-ac54-689f2c896c0d@185.21.8.91:443?encryption=none&security=reality&sni=www.microsoft.com&fp=chrome&pbk=JjUIhhSWTWGLjYBn9DSou0q_RiBqIaGl4Af7MCjQ0iQ&sid=04d9b6c0&type=tcp&flow=xtls-rprx-vision#EU1-VLESS
```

---

## Клиентские приложения

| Платформа | Приложения |
|-----------|-----------|
| **iOS** | Hiddify, FoXray, V2Box |
| **Android** | Hiddify, v2rayNG |

> Happ и Streisand удалены из App Store — не рекомендовать новым пользователям.

---

## Управление клиентами (ручной способ, до автоматизации)

```bash
ssh -i "C:\Users\krono\.ssh\id_ed25519_fornex" root@185.21.8.91

# Добавить клиента
python3 -c "
import json, secrets
with open('/usr/local/etc/xray/config.json') as f:
    cfg = json.load(f)
inbound = next(i for i in cfg['inbounds'] if i['port'] == 443)
inbound['settings']['clients'].append({'id': '<UUID>', 'flow': 'xtls-rprx-vision'})
inbound['streamSettings']['realitySettings']['shortIds'].append(secrets.token_hex(4))
with open('/usr/local/etc/xray/config.json', 'w') as f:
    json.dump(cfg, f, indent=2)
print('Done')
"
systemctl reload xray  # или restart если reload не поддерживается
```

---

## Этап 2 — автоматизация (следующая задача)

- [ ] Скрипт `/opt/xray-add-client.sh` на eu1 (принимает UUID, добавляет shortId, делает reload)
- [ ] Скрипт `/opt/xray-remove-client.sh` (удаляет по UUID)
- [ ] Интеграция в бота: при `/get_config` генерировать UUID → вызывать скрипт → отдавать `vless://`
- [ ] UUID хранить в БД (`vpn.db`) рядом с WG-пиром
- [ ] Обновить инструкции в боте
