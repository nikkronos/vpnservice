# Развёртывание WireGuard VPN-ноды

## Стратегия развёртывания

- **Первая нода (текущая):** развёртывание на существующем Timeweb-сервере (где уже работают TradeTherapyBot и PastuhiBot).
- **В дальнейшем:** перенос на отдельный VPS, выделенный под VPN (когда будет готово и протестировано).

## Предварительные требования

- Доступ к существующему Timeweb-серверу по SSH (IP, пользователь, пароль/ключ из `env_vars.txt`).
- Права root или sudo на сервере.
- Понимание, что на сервере уже работают другие сервисы (боты), поэтому нужно быть аккуратным с портами и конфигурацией.

## Шаг 1: Подключение к серверу

```bash
# Из PowerShell или терминала
ssh root@<IP_ADDRESS>
# или
ssh <USER>@<IP_ADDRESS>
```

**Важно:** IP адрес, пользователь и пароль хранятся в `env_vars.txt` (локально) и не коммитятся в Git.

## Шаг 2: Проверка системы и установка WireGuard

### 2.1. Обновление системы (если нужно)

```bash
# Для Ubuntu/Debian
apt update && apt upgrade -y

# Для CentOS/RHEL
yum update -y
```

### 2.2. Установка WireGuard

```bash
# Для Ubuntu/Debian
apt install wireguard wireguard-tools -y

# Для CentOS/RHEL
yum install epel-release -y
yum install wireguard-tools -y
```

### 2.3. Проверка установки

```bash
wg --version
```

Должна вывестись версия WireGuard (например, `wireguard-tools v1.0.20210914`).

## Шаг 3: Генерация ключей

### 3.1. Создание директории для конфигурации

```bash
mkdir -p /etc/wireguard
cd /etc/wireguard
```

### 3.2. Генерация приватного ключа сервера

```bash
wg genkey | tee server_private.key | wg pubkey > server_public.key
```

**Важно:** Сохрани `server_private.key` и `server_public.key` в безопасном месте (локально в `env_vars.txt` или в зашифрованном хранилище). Эти ключи **НЕ коммитятся** в Git!

### 3.3. Генерация ключей для первого клиента (владелец)

```bash
wg genkey | tee client1_private.key | wg pubkey > client1_public.key
```

Аналогично сохрани эти ключи локально.

## Шаг 4: Настройка WireGuard на сервере

### 4.1. Определение сетевого интерфейса

```bash
ip route | grep default
```

Обычно это `eth0` или `ens3` (запиши название интерфейса).

### 4.2. Создание конфигурационного файла сервера

```bash
nano /etc/wireguard/wg0.conf
```

Вставь следующую конфигурацию (замени `<SERVER_PRIVATE_KEY>`, `<CLIENT1_PUBLIC_KEY>`, `<NETWORK_INTERFACE>`):

```ini
[Interface]
# Приватный ключ сервера
PrivateKey = <SERVER_PRIVATE_KEY>

# Адрес VPN-интерфейса на сервере (выбери подсеть, которая не конфликтует с существующими)
Address = 10.0.0.1/24

# Порт для WireGuard (стандартный 51820, убедись, что он свободен)
ListenPort = 51820

# Команда для включения NAT (маршрутизация трафика)
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o <NETWORK_INTERFACE> -j MASQUERADE

# Команда для отключения NAT
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -D FORWARD -o wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o <NETWORK_INTERFACE> -j MASQUERADE

[Peer]
# Публичный ключ первого клиента
PublicKey = <CLIENT1_PUBLIC_KEY>

# Разрешить клиенту подключаться с любого IP (или укажи конкретный AllowedIPs)
AllowedIPs = 10.0.0.2/32
```

**Важные замечания:**
- `<SERVER_PRIVATE_KEY>` — содержимое файла `server_private.key`.
- `<CLIENT1_PUBLIC_KEY>` — содержимое файла `client1_public.key`.
- `<NETWORK_INTERFACE>` — название интерфейса из шага 4.1 (например, `eth0`).
- Подсеть `10.0.0.0/24` — пример; можно выбрать другую (например, `10.8.0.0/24`), главное, чтобы не конфликтовала с существующими сетями на сервере.

### 4.3. Установка прав доступа

```bash
chmod 600 /etc/wireguard/wg0.conf
chmod 600 /etc/wireguard/*.key
```

## Шаг 5: Настройка IP forwarding и firewall

### 5.1. Включение IP forwarding

```bash
# Временно включить
sysctl -w net.ipv4.ip_forward=1

# Постоянно включить (добавить в /etc/sysctl.conf)
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p
```

### 5.2. Открытие порта в firewall (если используется ufw/firewalld)

```bash
# Для ufw (Ubuntu)
ufw allow 51820/udp

# Для firewalld (CentOS/RHEL)
firewall-cmd --permanent --add-port=51820/udp
firewall-cmd --reload
```

**Важно:** Убедись, что порт 51820/UDP открыт в панели Timeweb (если есть веб-интерфейс управления firewall).

## Шаг 6: Запуск WireGuard

### 6.1. Запуск интерфейса

```bash
wg-quick up wg0
```

### 6.2. Проверка статуса

```bash
wg show
```

Должен показать интерфейс `wg0` и подключенного peer (если клиент уже подключился).

### 6.3. Настройка автозапуска через systemd

```bash
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0
```

Проверка статуса:
```bash
systemctl status wg-quick@wg0
```

## Шаг 7: Создание конфигурации для клиента (Windows/iOS)

### 7.1. Создание конфига для клиента

На сервере создай файл конфигурации клиента:

```bash
nano /tmp/client1.conf
```

Вставь следующее (замени `<CLIENT1_PRIVATE_KEY>`, `<SERVER_PUBLIC_KEY>`, `<SERVER_IP>`):

```ini
[Interface]
# Приватный ключ клиента
PrivateKey = <CLIENT1_PRIVATE_KEY>

# Адрес клиента в VPN-сети
Address = 10.0.0.2/24

# DNS (опционально, можно использовать 8.8.8.8 или 1.1.1.1)
DNS = 8.8.8.8

[Peer]
# Публичный ключ сервера
PublicKey = <SERVER_PUBLIC_KEY>

# IP адрес сервера (внешний IP Timeweb-сервера)
Endpoint = <SERVER_IP>:51820

# Разрешить весь трафик через VPN (0.0.0.0/0) или только определённые подсети
AllowedIPs = 0.0.0.0/0

# Keepalive (опционально, помогает поддерживать соединение)
PersistentKeepalive = 25
```

**Важно:**
- `<CLIENT1_PRIVATE_KEY>` — содержимое файла `client1_private.key`.
- `<SERVER_PUBLIC_KEY>` — содержимое файла `server_public.key`.
- `<SERVER_IP>` — внешний IP адрес Timeweb-сервера.

### 7.2. Копирование конфига на локальную машину

Из PowerShell на твоём компьютере:

```powershell
# Используй SCP или другой способ
scp root@<SERVER_IP>:/tmp/client1.conf C:\Users\krono\Downloads\client1.conf
```

Или скопируй содержимое файла вручную через SSH и сохрани локально.

## Шаг 8: Подключение клиента

### 8.1. Windows

1. Установи официальный клиент WireGuard: https://www.wireguard.com/install/
2. Открой WireGuard.
3. Нажми "Add Tunnel" → "Import tunnel(s) from file".
4. Выбери файл `client1.conf`.
5. Нажми "Activate" (или переключи тоггл в положение "On").

### 8.2. iOS

1. Установи WireGuard из App Store.
2. Открой приложение.
3. Нажми "+" → "Create from file or archive" (или используй QR-код, см. шаг 9).
4. Выбери файл `client1.conf` (через AirDrop, iCloud Drive или другой способ).
5. Нажми "Add Tunnel" и активируй подключение.

## Шаг 9: Генерация QR-кода (опционально, для удобства)

На сервере установи `qrencode`:

```bash
# Ubuntu/Debian
apt install qrencode -y

# CentOS/RHEL
yum install qrencode -y
```

Сгенерируй QR-код:

```bash
qrencode -t ansiutf8 < /tmp/client1.conf
```

Или сохрани в файл:

```bash
qrencode -t png -o /tmp/client1.png < /tmp/client1.conf
```

Скопируй PNG на локальную машину и отсканируй через WireGuard на iOS.

## Шаг 10: Тестирование подключения

### 10.1. Проверка на сервере

```bash
# Проверить статус подключения
wg show

# Проверить логи (если есть проблемы)
journalctl -u wg-quick@wg0 -f
```

### 10.2. Проверка на клиенте (Windows/iOS)

- Проверь, что VPN-туннель активен (в клиенте WireGuard должен быть статус "Connected").
- Проверь свой IP: открой браузер и зайди на https://whatismyipaddress.com/ — должен показаться IP сервера.
- Проверь пинг: `ping 8.8.8.8` (или другой внешний адрес).
- Проверь скорость: используй speedtest.net или аналогичный сервис.

### 10.3. Зафиксировать результаты

Запиши в `VPN/SESSION_SUMMARY_YYYY-MM-DD.md`:
- Скорость подключения (download/upload).
- Пинг до сервера.
- Любые проблемы или особенности.

## Шаг 11: Безопасность и очистка

### 11.1. Удаление временных файлов с ключами

```bash
# Удалить временные файлы с ключами (после того, как сохранил их локально!)
rm /tmp/client1.conf
# НЕ удаляй файлы в /etc/wireguard/ — они нужны для работы!
```

### 11.2. Сохранение ключей локально

Сохрани все ключи в `env_vars.txt` (локально, не коммить в Git!):

```
# WireGuard Server Keys
WG_SERVER_PRIVATE_KEY=<значение>
WG_SERVER_PUBLIC_KEY=<значение>

# WireGuard Client Keys (Client 1 - Owner)
WG_CLIENT1_PRIVATE_KEY=<значение>
WG_CLIENT1_PUBLIC_KEY=<значение>

# WireGuard Server Config
WG_SERVER_IP=<IP_адрес_сервера>
WG_SERVER_PORT=51820
WG_SERVER_INTERFACE=wg0
```

## Управление WireGuard на сервере

### Полезные команды

```bash
# Запустить интерфейс
wg-quick up wg0

# Остановить интерфейс
wg-quick down wg0

# Перезапустить интерфейс
systemctl restart wg-quick@wg0

# Показать статус и подключенных peers
wg show

# Показать логи
journalctl -u wg-quick@wg0 -f
```

## Добавление новых клиентов

Когда понадобится добавить нового пользователя (друг/коллега):

1. Сгенерируй новые ключи:
   ```bash
   wg genkey | tee client2_private.key | wg pubkey > client2_public.key
   ```

2. Добавь peer в `/etc/wireguard/wg0.conf`:
   ```ini
   [Peer]
   PublicKey = <CLIENT2_PUBLIC_KEY>
   AllowedIPs = 10.0.0.3/32
   ```

3. Перезагрузи конфигурацию:
   ```bash
   wg syncconf wg0 <(wg-quick strip wg0)
   ```

4. Создай конфиг для клиента (аналогично шагу 7).

## Миграция на отдельный сервер (когда будет готово)

Когда захочешь перенести VPN на отдельный VPS:

1. Разверни новый сервер (Timeweb или другой провайдер).
2. Повтори шаги 2–6 на новом сервере.
3. Обнови конфиги клиентов (измени `Endpoint` на новый IP).
4. Останови WireGuard на старом сервере:
   ```bash
   systemctl stop wg-quick@wg0
   systemctl disable wg-quick@wg0
   ```
5. Обнови документацию (`VPN/docs/deployment.md` и `docs/server-timeweb.md`).

## Ссылки и дополнительная информация

- Официальная документация WireGuard: https://www.wireguard.com/
- Руководство по настройке WireGuard: https://www.wireguard.com/quickstart/
- Общие правила безопасности: `VPN/docs/security.md`
- Информация о сервере Timeweb: `docs/server-timeweb.md`
