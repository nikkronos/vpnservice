# Установка Telegram MTProto Proxy на Fornex сервер

## Предварительные требования

- Сервер Fornex (Ubuntu 24.04)
- Доступ по SSH с правами root или sudo
- Свободный порт (рекомендуется `443` или `8443`)

## Шаг 1: Проверка Docker

Проверь, установлен ли Docker:

```bash
docker --version
```

Если Docker не установлен, установи его:

```bash
# Обновление пакетов
sudo apt update

# Установка зависимостей
sudo apt install -y apt-transport-https ca-certificates curl gnupg lsb-release

# Добавление официального GPG ключа Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Добавление репозитория Docker
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установка Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io

# Проверка установки
sudo systemctl status docker
```

## Шаг 2: Проверка свободных портов

Проверь, свободен ли порт 443:

```bash
sudo netstat -tuln | grep 443
```

Если порт занят, используй `8443`:

```bash
sudo netstat -tuln | grep 8443
```

**Запомни выбранный порт** (далее в инструкции будет `PORT`).

## Шаг 3: Запуск MTProto Proxy контейнера

Запусти контейнер с MTProto‑прокси:

```bash
# Для порта 443:
sudo docker run -d --name mtproto-proxy --restart=always -p 443:443 -e SECRET=$(openssl rand -hex 16) telegrammessenger/proxy:latest

# ИЛИ для порта 8443:
sudo docker run -d --name mtproto-proxy --restart=always -p 8443:443 -e SECRET=$(openssl rand -hex 16) telegrammessenger/proxy:latest
```

**Важно**: Замени `PORT` на реальный порт (443 или 8443).

## Шаг 4: Получение секрета и генерация ссылки

После запуска контейнера получи секрет:

```bash
sudo docker logs mtproto-proxy 2>&1 | grep -oP "secret='\K[^']+"
```

Или посмотри все логи:

```bash
sudo docker logs mtproto-proxy
```

В логах найди строку вида:
```
Started! Secret: ee... (hex string)
```

**Запиши секрет** (это длинная hex‑строка).

## Шаг 5: Формирование ссылки подключения

Собери ссылку в формате:

```
tg://proxy?server=<PUBLIC_IP>&port=<PORT>&secret=<SECRET>
```

Где:
- `<PUBLIC_IP>` — внешний IP твоего Fornex сервера (например, `81.200.146.32`)
- `<PORT>` — порт, который ты выбрал (443 или 8443)
- `<SECRET>` — секрет из логов контейнера

**Пример**:
```
tg://proxy?server=81.200.146.32&port=443&secret=ee1234567890abcdef...
```

## Шаг 6: Проверка работы прокси

Проверь статус контейнера:

```bash
sudo docker ps | grep mtproto-proxy
```

Проверь, что порт слушается:

```bash
sudo netstat -tuln | grep <PORT>
```

Проверь логи:

```bash
sudo docker logs mtproto-proxy
```

## Шаг 7: Настройка systemd (опционально, но рекомендуется)

Создай systemd‑юнит для более удобного управления:

```bash
sudo nano /etc/systemd/system/mtproto-proxy.service
```

Вставь:

```ini
[Unit]
Description=Telegram MTProto Proxy
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/docker start mtproto-proxy
ExecStop=/usr/bin/docker stop mtproto-proxy
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Включи автозапуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mtproto-proxy.service
sudo systemctl status mtproto-proxy.service
```

## Шаг 8: Тестирование на клиенте

1. **На iPhone/Android**:
   - Открой Telegram
   - Настройки → Данные и хранилище → Прокси‑серверы → Добавить прокси
   - Выбери "MTProto"
   - Вставь ссылку `tg://proxy?server=...&port=...&secret=...`
   - Или введи параметры вручную:
     - Сервер: `<PUBLIC_IP>`
     - Порт: `<PORT>`
     - Секрет: `<SECRET>`
   - Включи прокси
   - Проверь, что Telegram работает

2. **На Desktop (Windows/macOS/Linux)**:
   - Открой Telegram Desktop
   - Настройки → Продвинутые → Сеть и прокси
   - Добавь MTProto прокси с теми же параметрами

## Резервное копирование

Сохрани ссылку подключения в безопасное место:

```bash
# Создай файл с ссылкой (НЕ коммить в Git!)
echo "tg://proxy?server=<PUBLIC_IP>&port=<PORT>&secret=<SECRET>" | sudo tee /root/vpn-backups/2026-02-18/mtproto-link.txt
```

## Управление прокси

**Остановить**:
```bash
sudo docker stop mtproto-proxy
# или
sudo systemctl stop mtproto-proxy.service
```

**Запустить**:
```bash
sudo docker start mtproto-proxy
# или
sudo systemctl start mtproto-proxy.service
```

**Перезапустить**:
```bash
sudo docker restart mtproto-proxy
# или
sudo systemctl restart mtproto-proxy.service
```

**Посмотреть логи**:
```bash
sudo docker logs mtproto-proxy
# или
sudo journalctl -u mtproto-proxy.service -f
```

## Обновление прокси

Для обновления до последней версии:

```bash
sudo docker stop mtproto-proxy
sudo docker rm mtproto-proxy
sudo docker pull telegrammessenger/proxy:latest
# Затем запусти заново по Шагу 3 (сохрани тот же SECRET, если хочешь использовать старую ссылку)
```

## Устранение проблем

**Проблема**: Контейнер не запускается
- Проверь логи: `sudo docker logs mtproto-proxy`
- Проверь, свободен ли порт: `sudo netstat -tuln | grep <PORT>`

**Проблема**: Telegram не подключается через прокси
- Проверь, что IP и порт правильные
- Проверь секрет (должен быть длинная hex‑строка без пробелов)
- Убедись, что контейнер работает: `sudo docker ps | grep mtproto-proxy`

**Проблема**: Прокси работает, но медленно
- Это нормально для MTProto (он оптимизирован для надёжности, а не скорости)
- Для быстрого доступа используй VPN (WireGuard) вместо прокси
