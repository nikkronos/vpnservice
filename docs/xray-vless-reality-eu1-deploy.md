# Развёртывание Xray VLESS + REALITY на eu1 (мобильный резерв)

Цель: **TCP-туннель** с маскировкой под TLS, чтобы обойти типичные ограничения мобильных сетей на **UDP** и на «нестандартные» протоколы. **AmneziaWG не удалять** — работает параллельно на **UDP** (например, 39580).

## 0. Бэкап перед любыми правками

На **eu1** (Fornex):

```bash
BACKUP_ROOT=/root/vpn-backups/$(date +%Y-%m-%d)-pre-xray-reality
mkdir -p "$BACKUP_ROOT"

# AmneziaWG (Docker)
docker ps -a > "$BACKUP_ROOT/docker-ps.txt"
docker inspect amnezia-awg2 > "$BACKUP_ROOT/amnezia-awg2-inspect.json" 2>/dev/null || true
docker exec amnezia-awg2 cat /opt/amnezia/awg/awg0.conf > "$BACKUP_ROOT/awg0.conf.from-container" 2>/dev/null || true

# Если есть старый каталог бэкапа Amnezia — скопировать
cp -a /root/amnezia-backup-* "$BACKUP_ROOT/" 2>/dev/null || true

ls -la "$BACKUP_ROOT"
```

На **Timeweb** (бот):

```bash
sudo cp /opt/vpnservice/env_vars.txt "/opt/vpnservice/env_vars.txt.backup_$(date +%Y%m%d_%H%M)"
sudo cp /opt/vpnservice/bot/data/peers.json "/opt/vpnservice/bot/data/peers.json.backup_$(date +%Y%m%d_%H%M)"
```

Откат AmneziaWG при проблемах — см. `README_FOR_NEXT_AGENT.md` и `docs/backup-restore.md`.

## 1. Выбор порта

- **443/tcp** — лучше для обхода; занят, если на хосте уже nginx/caddy.
- **8443/tcp** — безопасный запасной вариант.

Проверка:

```bash
ss -tlnp | grep -E ':443|:8443' || true
```

## 2. Установка Xray (Linux x64)

Официальные релизы: [XTLS/Xray-core](https://github.com/XTLS/Xray-core/releases).

Пример (версию подставь актуальную):

```bash
XRAY_VER=25.3.6
cd /tmp
wget -q "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VER}/Xray-linux-64.zip" -O xray.zip
unzip -o xray.zip xray -d /usr/local/bin
chmod +x /usr/local/bin/xray
/usr/local/bin/xray version
```

## 3. Ключи REALITY

```bash
/usr/local/bin/xray x25519
```

Сохрани вывод:

- `Private key:` → в конфиг сервера `realitySettings.privateKey`
- `Password` (public) → в клиентскую ссылку как `pbk=...`

## 4. Выбор `dest` и SNI

Нужен **чужой** сайт с TLS 1.3, который **стабильно отвечает** с eu1:

```bash
curl -sI --connect-timeout 5 https://www.microsoft.com | head -3
```

В конфиге:

- `dest`: например `www.microsoft.com:443`
- `serverNames`: список имён, совместимых с этим сервером (как минимум тот же хост).

При смене `dest` пересобери клиентскую ссылку (`sni=`).

## 5. Пример `config.json`

Подставь **свой** `PRIVATE_KEY`, **свой** `UUID` (`uuidgen`), **порт** и **dest/serverNames**.

Файл: `/usr/local/etc/xray/config.json`

```json
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "listen": "0.0.0.0",
      "port": 8443,
      "protocol": "vless",
      "settings": {
        "clients": [
          { "id": "ВАШ-UUID-ЗДЕСЬ", "flow": "xtls-rprx-vision" }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.microsoft.com:443",
          "xver": 0,
          "serverNames": ["www.microsoft.com", "microsoft.com"],
          "privateKey": "ВАШ_PRIVATE_KEY_ИЗ_x25519",
          "shortIds": [""]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" }
  ]
}
```

Проверка JSON:

```bash
/usr/local/bin/xray run -test -config /usr/local/etc/xray/config.json
```

## 6. systemd

`/etc/systemd/system/xray.service`:

```ini
[Unit]
Description=Xray Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/xray run -config /usr/local/etc/xray/config.json
Restart=on-failure
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable xray
systemctl restart xray
systemctl status xray
ss -tlnp | grep xray
```

Файрвол: разреши **только TCP** выбранный порт (UDP для AmneziaWG не трогай).

## 7. Клиентская ссылка `vless://`

Шаблон (подставь IP eu1, порт, UUID, `pbk`, `sni`):

```text
vless://UUID@185.21.8.91:8443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.microsoft.com&fp=chrome&pbk=ПУБЛИЧНЫЙ_КЛЮЧ_ИЗ_x25519&sid=&type=tcp&headerType=none#eu1-mobile-reality
```

Проверка на ПК: **v2rayN** / **Nekoray** — импорт из буфера, затем тест с **системным прокси** или TUN.

## 8. Интеграция с ботом

На Timeweb в `/opt/vpnservice/env_vars.txt` добавь **одну строку** (без кавычек; в URL спецсимволы не экранировать):

```env
VLESS_REALITY_SHARE_URL=vless://....полная_ссылка....
```

Перезапуск:

```bash
sudo systemctl restart vpn-bot.service
```

Пользователи: команда **`/mobile_vpn`** (после регистрации в боте).

## 9. Клиенты на телефонах

- **Android:** v2rayNG, NekoBox, Hiddify.
- **iOS:** Streisand, FoXray, Hiddify (редакция App Store меняется — проверь актуальные названия).

Включи **VPN-режим** в приложении после импорта ссылки.

## 10. Если «не коннектится»

1. С eu1: `ss -tlnp`, `journalctl -u xray -n 50`.
2. С внешней сети: доступен ли TCP-порт (не блокирует ли хостинг).
3. Смени `dest`/`sni` на другой крупный TLS-сайт.
4. Попробуй порт **443** вместо 8443 (если свободен).

---

*Документ создан 2026-03-23. IP/порт в примерах — из README проекта; замени при смене инфраструктуры.*
