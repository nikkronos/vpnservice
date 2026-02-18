# Обходные пути для eu1 (Fornex) — не теряя оплаченный месяц

Документ описывает варианты обхода проблемы с WireGuard UDP на Fornex (185.21.8.91) для клиентов из России.

**Проблема:** WireGuard UDP (порт 51820) не работает — туннель поднимается, но трафик не проходит. Сервер настроен корректно, проблема в маршруте Россия ↔ Fornex (блокировка/потеря UDP‑трафика).

**Цель:** попробовать обходные пути на существующем Fornex VPS, не теряя оплаченный месяц (~500 руб).

---

## Вариант 1: ShadowSocks (самый простой, ~30 минут)

ShadowSocks — SOCKS5‑прокси с шифрованием, хорошо обходит блокировки. Не VPN (нет маршрутизации), но для доступа к заблокированным сайтам подходит.

### Установка на Fornex

**Вариант А: shadowsocks-libev (рекомендуется, через apt)**

```bash
# Подключиться по SSH
ssh root@185.21.8.91

# Установить ShadowSocks
apt update
apt install -y shadowsocks-libev

# Создать конфиг
nano /etc/shadowsocks-libev/config.json
```

**Конфиг `/etc/shadowsocks-libev/config.json`:**

```json
{
    "server": "0.0.0.0",
    "server_port": 8388,
    "password": "твой_надёжный_пароль_здесь",
    "method": "aes-256-gcm",
    "timeout": 300
}
```

**Запуск:**

```bash
# Запустить ShadowSocks
systemctl start shadowsocks-libev
systemctl enable shadowsocks-libev

# Проверить статус
systemctl status shadowsocks-libev

# Открыть порт в firewall (если есть)
iptables -I INPUT 1 -p tcp --dport 8388 -j ACCEPT
netfilter-persistent save
```

**Вариант Б: shadowsocks (Python, если нужен именно ssserver)**

Если нужен именно Python-вариант с командой `ssserver`, используй виртуальное окружение:

```bash
# Установить через venv
python3 -m venv /opt/shadowsocks
source /opt/shadowsocks/bin/activate
pip install shadowsocks

# Конфиг уже создан в /etc/shadowsocks.json
# Запуск:
/opt/shadowsocks/bin/ssserver -c /etc/shadowsocks.json -d start
```

### Клиент (Windows)

1. Скачать клиент: [Shadowsocks-Windows](https://github.com/shadowsocks/shadowsocks-windows/releases)
2. Добавить сервер:
   - Адрес: `185.21.8.91`
   - Порт: `8388`
   - Пароль: из конфига
   - Метод: `aes-256-gcm`
3. Включить системный прокси или настроить прокси в браузере.

### Клиент (iOS)

1. Установить из App Store: **Shadowrocket** или **Surge** (платные, ~$3–5).
2. Добавить сервер по тем же параметрам.

**Плюсы:** быстро настроить, хорошо обходит блокировки, работает стабильно.  
**Минусы:** не VPN (нужно настраивать прокси в приложениях), не маршрутизует весь трафик.

---

### Проверенная настройка ShadowSocks (февраль 2026)

Ниже — пошаговая настройка, проверенная на Fornex (Ubuntu 24.04). Используется **shadowsocks-libev** из apt (не Python-версия).

**Важно:**
- На Ubuntu 24.04 `pip3 install shadowsocks` даёт ошибку «externally-managed-environment» — ставим через apt: `apt install -y shadowsocks-libev`.
- Команда сервера — `ss-server`, конфиг: `/etc/shadowsocks-libev/config.json`.
- В конфиге обязательно `"server": "0.0.0.0"` — иначе сервер слушает только localhost и снаружи не подключаться.

#### Быстрая установка на сервере (копируй-вставляй)

Подключение:

```bash
ssh root@185.21.8.91
```

Установка и конфиг (подставь свой пароль вместо `ТВОЙ_ПАРОЛЬ`):

```bash
apt update
apt install -y shadowsocks-libev
```

```bash
cat > /etc/shadowsocks-libev/config.json << 'EOF'
{
    "server": "0.0.0.0",
    "server_port": 8388,
    "password": "ТВОЙ_ПАРОЛЬ",
    "method": "aes-256-gcm",
    "timeout": 300
}
EOF
```

Открыть порт и запустить:

```bash
iptables -I INPUT 1 -p tcp --dport 8388 -j ACCEPT
netfilter-persistent save
systemctl restart shadowsocks-libev
systemctl enable shadowsocks-libev
```

Проверка:

```bash
cat /etc/shadowsocks-libev/config.json
systemctl status shadowsocks-libev
ss -tlnp | grep 8388
```

В выводе `ss` должно быть `0.0.0.0:8388` (не `127.0.0.1:8388`). В логах сервиса — `tcp server listening at 0.0.0.0:8388`.

#### Клиент Windows (кратко)

1. Скачать: [Shadowsocks-Windows](https://github.com/shadowsocks/shadowsocks-windows/releases), распаковать, запустить.
2. Servers → Edit Servers → Add: Address `185.21.8.91`, Port `8388`, Password из конфига, Encryption `aes-256-gcm`.
3. Включить: Enable System Proxy или режим PAC.

#### Результат

Настройка проверена: сервер Fornex (185.21.8.91) успешно раздаёт ShadowSocks, клиенты из России подключаются и обходят блокировки. WireGuard по UDP на том же VPS по-прежнему не работает из РФ; ShadowSocks (TCP) — рабочий обходной путь.

---

## Вариант 2: WireGuard через Cloudflared Tunnel (TCP через Cloudflare)

Обёртка WireGuard в TCP через Cloudflare Tunnel — бесплатно, обходит блокировки UDP.

### Установка на Fornex

```bash
# Установить cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# Создать туннель (нужен аккаунт Cloudflare, бесплатно)
cloudflared tunnel login
cloudflared tunnel create eu1-vpn
cloudflared tunnel route dns eu1-vpn vpn-eu1.example.com  # подставить свой домен или использовать IP

# Настроить туннель для проксирования WireGuard
nano ~/.cloudflared/config.yml
```

**Конфиг `~/.cloudflared/config.yml`:**

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: vpn-eu1.example.com
    service: tcp://127.0.0.1:51820
  - service: http_status:404
```

**Запуск:**

```bash
cloudflared tunnel --config ~/.cloudflared/config.yml run
```

**Проблема:** WireGuard по умолчанию UDP, а cloudflared туннель работает по TCP. Нужен WireGuard через TCP или другой подход.

**Альтернатива:** использовать cloudflared как SOCKS5‑прокси (аналогично ShadowSocks), а не как туннель для WireGuard.

---

## Вариант 3: WireGuard через Nginx TCP proxy

Nginx как TCP‑прокси для WireGuard (WireGuard должен поддерживать TCP, но по умолчанию только UDP).

**Проблема:** стандартный WireGuard не работает через TCP. Нужен WireGuard‑go с поддержкой TCP или другой подход.

**Альтернатива:** использовать **boringtun** (WireGuard на Rust) с TCP‑режимом, но это сложнее.

---

## Вариант 4: Обфускация UDP (udp2raw)

Обёртка UDP WireGuard в TCP с обфускацией.

### Установка на Fornex

```bash
# Скачать udp2raw
wget https://github.com/wangyu-/udp2raw/releases/download/20230206.0/udp2raw_binaries.tar.gz
tar -xzf udp2raw_binaries.tar.gz
cp udp2raw_amd64 /usr/local/bin/udp2raw
chmod +x /usr/local/bin/udp2raw

# Запустить на сервере (оборачивает локальный WireGuard в TCP)
udp2raw -s -l 0.0.0.0:4096 -r 127.0.0.1:51820 -k "твой_секретный_ключ" --raw-mode faketcp
```

### Клиент

Нужно установить `udp2raw` на клиенте (Windows/iOS) и настроить цепочку: WireGuard → udp2raw клиент → интернет → udp2raw сервер → WireGuard сервер.

**Плюсы:** сохраняет производительность UDP, обходит простые блокировки.  
**Минусы:** сложнее настройка, нужна установка на клиенте.

---

## Вариант 5: V2Ray/Xray (продвинутый прокси)

V2Ray/Xray — продвинутый прокси с множеством протоколов и обфускацией.

### Установка на Fornex

```bash
# Установить Xray (форк V2Ray)
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install

# Создать конфиг
nano /usr/local/etc/xray/config.json
```

**Конфиг (пример, VLESS + TLS):**

```json
{
  "inbounds": [{
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{"id": "твой_uuid_здесь"}],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "tls",
      "tlsSettings": {"certificates": [{"certificateFile": "/path/to/cert.pem", "keyFile": "/path/to/key.pem"}]}
    }
  }],
  "outbounds": [{"protocol": "freedom"}]
}
```

**Плюсы:** очень хорошо обходит блокировки, много вариантов обфускации.  
**Минусы:** сложнее в настройке, нужны специальные клиенты (V2RayN для Windows, Shadowrocket/Surge для iOS).

---

## Рекомендация: с чего начать

1. **ShadowSocks** (Вариант 1) — самый простой, ~30 минут настройки. Если работает — значит, проблема точно в UDP WireGuard, можно дальше пробовать обфускацию.
2. Если ShadowSocks не работает — проблема может быть глубже (блокировка всего трафика с Fornex или конкретного IP).
3. Если ShadowSocks работает — можно пробовать **udp2raw** (Вариант 4) для WireGuard или **V2Ray** (Вариант 5) как альтернативу.

---

## Проверка с не-российского IP

Перед настройкой обходных путей стоит **исключить проблему на стороне Fornex**:

- Попросить кого‑то из‑за границы (не из России) подключиться к eu1 по WireGuard и проверить, работает ли VPN.
- Если работает — проблема точно в маршруте Россия ↔ Fornex.
- Если не работает — проблема может быть на стороне Fornex или в конфигурации.

---

---

*Документ создан в рамках отладки eu1 (февраль 2026).*  
*Проверенная настройка ShadowSocks (shadowsocks-libev) задокументирована 17.02.2026 — успешно работает для клиентов из России на Fornex 185.21.8.91.*
