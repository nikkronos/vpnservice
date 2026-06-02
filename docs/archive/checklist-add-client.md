# Чеклист: добавление нового клиента WireGuard

## Предварительные условия

- Доступ по SSH к серверу Fornex (Ubuntu 24.04)
- Права root или sudo
- WireGuard‑сервер `wg0` уже настроен и работает

## 1. На сервере: генерация ключей

```bash
cd /etc/wireguard

# Имя клиента (замени NEW_CLIENT на осмысленное имя, например friend2-pc)
CLIENT=NEW_CLIENT

wg genkey | tee ${CLIENT}-privatekey | wg pubkey > ${CLIENT}-publickey

echo "PRIVATE:"; cat ${CLIENT}-privatekey
echo "PUBLIC:"; cat ${CLIENT}-publickey
```

Запомни или сохрани приватный и публичный ключи.

## 2. На сервере: выбор свободного IP

- Подсеть WireGuard: `10.1.0.0/24`
- Сервер: `10.1.0.1`
- Уже занятые адреса (примеры): `10.1.0.2`, `10.1.0.4`, `10.1.0.5`, `10.1.0.6`, `10.1.0.7`
- Выбери свободный адрес, например `10.1.0.8/32` для следующего клиента

## 3. На сервере: добавление peer в wg0.conf

```bash
sudo nano /etc/wireguard/wg0.conf
```

В конец файла добавь (подставь PUBLIC_KEY и выбранный IP):

```ini
[Peer]
# NEW_CLIENT
PublicKey = ПУБЛИЧНЫЙ_КЛЮЧ_КЛИЕНТА
AllowedIPs = 10.1.0.8/32
```

Сохрани файл.

## 4. На сервере: редирект через Shadowsocks (опционально)

Если клиенту нужен обход блокировок (GPT и т.п.) через Shadowsocks:

```bash
# Замени 10.1.0.8/32 на выбранный IP клиента
sudo iptables -t nat -A PREROUTING -i wg0 -s 10.1.0.8/32 -p tcp -m multiport --dports 80,443 -j REDIRECT --to-ports 1081
```

Если редирект не нужен — шаг пропустить.

## 5. На сервере: перезапуск WireGuard

```bash
sudo systemctl restart wg-quick@wg0
sudo wg show
```

Убедись, что новый peer отображается с правильным `allowed ips`.

## 6. На сервере: создание клиентского конфига

Узнай публичный ключ сервера:

```bash
sudo wg show wg0 | grep "public key"
```

Создай конфиг (подставь PRIVATE_KEY клиента, SERVER_PUBLIC_KEY, IP клиента, внешний IP и порт сервера):

```bash
sudo nano /etc/wireguard/NEW_CLIENT.conf
```

Содержимое (шаблон):

```ini
[Interface]
PrivateKey = ПРИВАТНЫЙ_КЛЮЧ_КЛИЕНТА
Address = 10.1.0.8/32
DNS = 8.8.8.8

[Peer]
PublicKey = ПУБЛИЧНЫЙ_КЛЮЧ_СЕРВЕРА
Endpoint = ВНЕШНИЙ_IP_СЕРВЕРА:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

Сохрани. Покажи конфиг (без передачи по незащищённому каналу):

```bash
sudo cat /etc/wireguard/NEW_CLIENT.conf
```

## 7. Передача конфига клиенту

- **Windows**: передать файл `.conf`; клиент импортирует в приложение WireGuard (Import tunnel(s) from file).
- **iOS/iPadOS**: передать файл или текст конфига; в приложении WireGuard — «+» → «Create from file or archive» или вставка из буфера.
- **Android**: аналогично iOS (импорт файла или сканирование QR, если сгенерирован).

Не передавай конфиги по незащищённым каналам; предпочтительно личная передача или защищённый мессенджер.

## 8. Резервная копия

Перед изменениями или после добавления клиента обнови бэкап:

```bash
sudo mkdir -p /root/vpn-backups/$(date +%Y-%m-%d)
sudo cp /etc/wireguard/wg0.conf /root/vpn-backups/$(date +%Y-%m-%d)/
sudo cp /etc/wireguard/NEW_CLIENT.conf /root/vpn-backups/$(date +%Y-%m-%d)/
```

## Краткая сводка по платформам

| Платформа   | Клиент              | Импорт конфига                          |
|------------|---------------------|----------------------------------------|
| Windows    | WireGuard (офиц.)   | Импорт из файла .conf                  |
| iOS        | WireGuard (офиц.)   | Файл / буфер / QR (если есть)         |
| iPadOS     | WireGuard (офиц.)   | То же                                  |
| Android    | WireGuard (офиц.)   | Файл / буфер / QR                      |

## Связанные документы

- `docs/specs/spec-01-architecture-wg-ss.md` — архитектура
- `README_FOR_NEXT_AGENT.md` — текущие профили и адреса
