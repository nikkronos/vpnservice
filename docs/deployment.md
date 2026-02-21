# Инструкция по развёртыванию VPN Service

## Обзор

Этот документ описывает процесс развёртывания VPN-сервиса на серверах и настройку бота.

## Серверы

### 1. main (Россия, Timeweb)

**IP:** `81.200.146.32`  
**Расположение:** `/opt/vpnservice`

#### Установка WireGuard

```bash
apt update
apt install -y wireguard wireguard-tools
```

#### Генерация ключей сервера

```bash
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
chmod 600 /etc/wireguard/server_private.key
```

#### Конфигурация WireGuard

`/etc/wireguard/wg0.conf`:
```ini
[Interface]
PrivateKey = <server_private_key>
Address = 10.0.0.1/24
ListenPort = 51820
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -D FORWARD -o wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
# Peer'ы добавляются ботом через wg set
```

#### Включение IP forwarding

```bash
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p
```

#### Настройка firewall (UFW)

```bash
ufw allow 51820/udp
ufw reload
```

#### Запуск WireGuard

```bash
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0
```

### 2. eu1 (Европа, Fornex)

**IP:** `185.21.8.91`  
**Подсеть:** `10.1.0.0/24`

#### Установка WireGuard и Shadowsocks

```bash
apt update
apt install -y wireguard wireguard-tools shadowsocks-libev
```

#### Конфигурация Shadowsocks

`/etc/shadowsocks-libev/ss-wg.json`:
```json
{
  "server": "185.21.8.91",
  "server_port": 8388,
  "local_address": "127.0.0.1",
  "local_port": 1081,
  "password": "<password>",
  "method": "aes-256-gcm"
}
```

#### Два режима Shadowsocks на eu1

- **Сервер** (`shadowsocks-libev.service`): конфиг `/etc/shadowsocks-libev/config.json` — слушает `0.0.0.0:8388`. Уже запущен.
- **Клиент ss-redir** (редирект 80/443 на 1081): конфиг `/etc/shadowsocks-libev/ss-wg.json` — подключается к серверу и слушает `127.0.0.1:1081`. Нужен для VPN+GPT и Unified.

Имя сервиса клиента — по имени конфига **без .json**: `ss-wg` → `shadowsocks-libev-redir@ss-wg.service`.

#### Запуск ss-redir

```bash
systemctl enable shadowsocks-libev-redir@ss-wg.service
systemctl start shadowsocks-libev-redir@ss-wg.service
```

Проверка: `ss -tlnp | grep 1081` — должен слушать `127.0.0.1:1081`.  
Не использовать `@config` — он использует config.json (серверный конфиг).

#### Конфигурация WireGuard

Аналогично main, но подсеть `10.1.0.1/24`.

**Важно для eu1:** если на сервере запущен Docker, его правила FORWARD (DOCKER-USER, DOCKER-FORWARD) идут первыми и могут не пропускать трафик из WireGuard. Нужно вставить правила для wg0 **в начало** цепочки FORWARD (до Docker):

```bash
# Вставить в начало FORWARD, чтобы трафик wg0 обрабатывался до цепочек Docker
iptables -I FORWARD 1 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -I FORWARD 1 -i wg0 -o eth0 -j ACCEPT
```

Чтобы правила сохранялись после перезагрузки, добавьте их в PostUp в `/etc/wireguard/wg0.conf` (используйте `-I FORWARD 1` вместо `-A FORWARD`) или настройте `iptables-persistent` / скрипт при загрузке.

**Ответы NAT (если пинг/сайты не работают):** после MASQUERADE ответы приходят на IP сервера и обрабатываются цепочкой **INPUT**. Нужно разрешить ESTABLISHED,RELATED в начале INPUT:
```bash
iptables -I INPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT
```
Если такого правила нет или оно не первое, ответные пакеты могут отбрасываться и трафик через VPN не будет работать.

#### Скрипт add-ss-redirect.sh для VPN+GPT

**Путь:** `/opt/vpnservice/scripts/add-ss-redirect.sh`

```bash
#!/bin/bash
# Добавляет редирект TCP 80/443 для указанного IP клиента на ss-redir (порт 1081)
# Использование: ./add-ss-redirect.sh <client_ip>

CLIENT_IP=$1
if [ -z "$CLIENT_IP" ]; then
  echo "Usage: $0 <client_ip>"
  exit 1
fi

iptables -t nat -A PREROUTING -i wg0 -s "$CLIENT_IP" -p tcp -m multiport --dports 80,443 -j REDIRECT --to-ports 1081
```

```bash
chmod +x /opt/vpnservice/scripts/add-ss-redirect.sh
```

#### Настройка Unified профиля (ipset)

**Однократная настройка:**

1. Установить ipset:
   ```bash
   apt install -y ipset
   ```

2. Создать ipset и правило iptables (см. `docs/scripts/setup-unified-iptables.sh.example`):
   ```bash
   ipset create unified_ss_dst hash:ip family inet
   iptables -t nat -A PREROUTING -i wg0 -m iprange --src-range 10.1.0.20-10.1.0.50 -p tcp -m set --match-set unified_ss_dst dst -m multiport --dports 80,443 -j REDIRECT --to-ports 1081
   ```

3. Сохранить ipset:
   ```bash
   ipset save > /etc/ipset.unified.conf
   ```

4. Настроить автовосстановление после перезагрузки:
   - Создать systemd unit или скрипт в `/etc/network/if-up.d/`
   - Пример unit: `/etc/systemd/system/restore-unified-ipset.service`

**Обновление списка IP (cron):**

Скрипт `update-unified-ss-ips.sh` (см. `docs/scripts/update-unified-ss-ips.sh.example`) разрешает домены ChatGPT и обновляет ipset.

Добавить в cron:
```bash
0 * * * * /opt/vpnservice/scripts/update-unified-ss-ips.sh
```

## Бот (Timeweb)

### Установка зависимостей

```bash
cd /opt/vpnservice
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Конфигурация

Создать `env_vars.txt` (не в Git):
```bash
BOT_TOKEN=<bot_token>
ADMIN_ID=<admin_telegram_id>

# main (Timeweb)
WG_SERVER_PUBLIC_KEY=<public_key>
WG_INTERFACE=wg0
WG_NETWORK_CIDR=10.0.0.0/24
WG_ENDPOINT_HOST=81.200.146.32
WG_ENDPOINT_PORT=51820
WG_DNS=1.1.1.1,8.8.8.8

# eu1 (Fornex)
WG_EU1_SERVER_PUBLIC_KEY=<eu1_public_key>
WG_EU1_INTERFACE=wg0
WG_EU1_NETWORK_CIDR=10.1.0.0/24
WG_EU1_ENDPOINT_HOST=185.21.8.91
WG_EU1_ENDPOINT_PORT=51820
WG_EU1_DNS=1.1.1.1,8.8.8.8
WG_EU1_SSH_HOST=185.21.8.91
WG_EU1_SSH_USER=root
WG_EU1_SSH_KEY_PATH=/root/.ssh/id_rsa_eu1
WG_EU1_ADD_SS_REDIRECT_SCRIPT=/opt/vpnservice/scripts/add-ss-redirect.sh
```

### Systemd сервис

`/etc/systemd/system/vpn-bot.service`:
```ini
[Unit]
Description=VPN Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnservice
Environment="PATH=/opt/vpnservice/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/vpnservice/venv/bin/python -m bot.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable vpn-bot.service
systemctl start vpn-bot.service
```

### Обновление бота

```bash
cd /opt/vpnservice
git pull
systemctl restart vpn-bot.service
systemctl status vpn-bot.service
```

**Важно:** Если добавлены новые переменные в `env_vars.example.txt`, их нужно **вручную** добавить в `env_vars.txt` на сервере (файл не в Git).

### Логи

```bash
journalctl -u vpn-bot.service -f
```

## Веб-панель мониторинга (Timeweb)

Панель отображает статус серверов, пользователей и статистику. Разворачивается на том же сервере Timeweb, где работает бот (`/opt/vpnservice`).

### Зависимости

В том же venv, что и бот:

```bash
cd /opt/vpnservice
source venv/bin/activate
pip install -r web/requirements.txt
```

### Запуск вручную (проверка)

```bash
cd /opt/vpnservice
FLASK_ENV=production PORT=5001 /opt/vpnservice/venv/bin/python web/app.py
```

Панель слушает порт **5001** (чтобы не конфликтовать с другими сервисами на 5000). Открыть в браузере: `http://81.200.146.32:5001` (при необходимости: `ufw allow 5001/tcp` и `ufw reload`).

### Systemd (постоянный запуск)

1. Скопировать unit-файл:
   ```bash
   sudo cp /opt/vpnservice/web/vpn-web.service.example /etc/systemd/system/vpn-web.service
   ```
   Если путь к проекту не `/opt/vpnservice`, отредактировать `WorkingDirectory` и пути в `ExecStart` и `Environment`.

2. Включить и запустить:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable vpn-web.service
   sudo systemctl start vpn-web.service
   sudo systemctl status vpn-web.service
   ```

3. Логи:
   ```bash
   journalctl -u vpn-web.service -f
   ```

### URL панели

После деплоя зафиксировать ссылку в этом разделе, например:

- **URL панели:** `http://81.200.146.32:5001` (порт 5001, чтобы не пересекаться с другими приложениями на 5000; при необходимости — nginx/HTTPS)

### Обновление панели

```bash
cd /opt/vpnservice
git pull
pip install -r web/requirements.txt --quiet
sudo systemctl restart vpn-web.service
```

### Безопасность

- Панель читает `env_vars.txt` и данные бота (`bot/data/`). Доступ к `/api/users` — по параметру `admin_key=<ADMIN_ID>` (в продакшене лучше вынести за nginx или добавить нормальную авторизацию).
- Рекомендуется поставить nginx reverse proxy и HTTPS (Let's Encrypt), открывать порт 5001 только с localhost при необходимости.

## Проверка работы

### Проверка WireGuard

```bash
wg show
```

### Проверка ss-redir (eu1)

```bash
systemctl status shadowsocks-libev-local@ss-wg.service
netstat -tlnp | grep 1081
```

### Проверка FORWARD для wg0 (eu1, если сайты не открываются)

Правила **должны быть выполнены на сервере eu1** (185.21.8.91), а не на другом хосте. Проверка:

```bash
# На eu1: первые две строки FORWARD должны быть правила для wg0
iptables -L FORWARD -n -v | head -8
```

Ожидаемо: в начале цепочки есть `ACCEPT ... wg0 eth0` и `ACCEPT ... * wg0 ... ESTABLISHED`. После попытки открыть сайт счётчики пакетов (pkts) у этих правил должны расти.

Если правил нет или они не в начале — выполнить на **eu1** ещё раз:
```bash
iptables -I FORWARD 1 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -I FORWARD 1 -i wg0 -o eth0 -j ACCEPT
```

Проверка MASQUERADE (трафик из VPN должен выходить в интернет):
```bash
iptables -t nat -L POSTROUTING -n -v
```
Должно быть правило с `MASQUERADE` и выходом в `eth0` (источник может быть `0.0.0.0/0` или `10.1.0.0/24`). После открытия сайта счётчик пакетов у этого правила должен расти.

### Проверка ipset (eu1, Unified)

```bash
ipset list unified_ss_dst
iptables -t nat -L PREROUTING -n -v | grep unified
```

### Тестирование бота

1. Добавить пользователя: `/add_user @username`
2. Выбрать сервер: `/server` → выбрать сервер
3. Получить конфиг: `/get_config`
4. Импортировать конфиг в WireGuard на клиенте
5. Проверить подключение

## Резервное копирование

### Конфиги WireGuard

```bash
cp /etc/wireguard/wg0.conf /root/vpn-backups/$(date +%Y-%m-%d)/wg0.conf
```

### ipset (eu1)

```bash
ipset save > /root/vpn-backups/$(date +%Y-%m-%d)/ipset.unified.conf
```

### iptables правила

```bash
iptables-save > /root/vpn-backups/$(date +%Y-%m-%d)/iptables.rules
```

## Восстановление после перезагрузки

### WireGuard

Автоматически через `systemctl enable wg-quick@wg0`.

### ipset (eu1, Unified)

Создать systemd unit или скрипт:
```bash
ipset restore < /etc/ipset.unified.conf
```

### iptables правила

Использовать `iptables-persistent` или восстановить из бэкапа:
```bash
iptables-restore < /root/vpn-backups/YYYY-MM-DD/iptables.rules
```

## Откат Unified профиля

Если нужно откатить Unified:

1. Удалить правило iptables:
   ```bash
   iptables -t nat -D PREROUTING -i wg0 -m iprange --src-range 10.1.0.20-10.1.0.50 -p tcp -m set --match-set unified_ss_dst dst -m multiport --dports 80,443 -j REDIRECT --to-ports 1081
   ```

2. Удалить ipset:
   ```bash
   ipset destroy unified_ss_dst
   ```

3. Удалить из cron скрипт обновления ipset

4. В боте перестать выдавать Unified (оставить только Обычный и VPN+GPT)

Существующие клиенты VPN+GPT (10.1.0.8–19 и 51–254) не затронуты.
