# Пошаговая настройка автоматической выдачи AmneziaWG конфигов ботом

Цель: бот по команде /get_config и /regen для сервера «Европа» автоматически выдаёт AmneziaWG .conf (без ручной выдачи конфигов).

**Требования:** AmneziaWG уже развёрнут на eu1 (185.21.8.91) по `docs/amneziawg-deploy-instruction.md`. Бот работает на Timeweb и имеет SSH-доступ к eu1 (WG_EU1_SSH_HOST, WG_EU1_SSH_USER, WG_EU1_SSH_KEY_PATH в env_vars.txt).

---

## Шаг 1. Проверка на eu1

Подключись по SSH к eu1 и выполни команды из **`docs/amneziawg-eu1-discovery.md`** (раздел «Команды для проверки»).

Зафиксируй:
- имя интерфейса AmneziaWG (например `awg0`);
- путь к серверному конфигу (например `/etc/wireguard/awg0.conf` или `/etc/amnezia/amneziawg/awg0.conf`);
- порт ListenPort из конфига (если отличается от 51820);
- что утилита `awg` есть в PATH (`which awg`).

---

## Шаг 2. Развернуть скрипты на eu1

### 2.1. Каталог для скриптов

На eu1 создай каталог (если нет):

```bash
sudo mkdir -p /opt/vpnservice/scripts
```

### 2.2. Скрипт добавления клиента

Скопируй содержимое **`docs/scripts/amneziawg-add-client.sh.example`** в `/opt/vpnservice/scripts/amneziawg-add-client.sh` на eu1.

В начале скрипта задай переменные под твой сервер (или экспортируй их в env перед вызовом):

```bash
# Пример: если после проверки выяснилось, что интерфейс awg0, конфиг в /etc/amnezia/amneziawg/awg0.conf
AWG_INTERFACE="${AWG_INTERFACE:-awg0}"
AWG_SERVER_CONF="${AWG_SERVER_CONF:-/etc/amnezia/amneziawg/awg0.conf}"
ENDPOINT_HOST="${ENDPOINT_HOST:-185.21.8.91}"
ENDPOINT_PORT="${ENDPOINT_PORT:-51820}"
```

Сделай скрипт исполняемым:

```bash
sudo chmod +x /opt/vpnservice/scripts/amneziawg-add-client.sh
```

Проверка (от root или с sudo):

```bash
/opt/vpnservice/scripts/amneziawg-add-client.sh 10.1.0.99
```

Ожидаемо: первая строка `PUBKEY=...`, далее блок `[Interface]` и `[Peer]`. После проверки peer можно удалить вручную: `awg set awg0 peer <PUBKEY_ЗНАЧЕНИЕ> remove`.

### 2.3. Скрипт удаления клиента (для /regen)

Скопируй **`docs/scripts/amneziawg-remove-client.sh.example`** в `/opt/vpnservice/scripts/amneziawg-remove-client.sh` на eu1.

Задай `AWG_INTERFACE` в начале скрипта (то же значение, что в add-client). Сделай исполняемым:

```bash
sudo chmod +x /opt/vpnservice/scripts/amneziawg-remove-client.sh
```

---

## Шаг 3. Переменные окружения на Timeweb (сервер бота)

На сервере, где запущен бот (Timeweb), открой `env_vars.txt` (в каталоге проекта VPN, например `/opt/vpnservice/env_vars.txt`) и добавь или проверь:

```bash
# SSH к eu1 (должны быть уже заданы для WireGuard/других задач)
WG_EU1_SSH_HOST=185.21.8.91
WG_EU1_SSH_USER=root
WG_EU1_SSH_KEY_PATH=/root/.ssh/id_rsa_eu1

# AmneziaWG: автоматическая выдача и регенерация конфигов
AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT=/opt/vpnservice/scripts/amneziawg-add-client.sh
AMNEZIAWG_EU1_NETWORK_CIDR=10.1.0.0/24
AMNEZIAWG_EU1_INTERFACE=awg0
AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT=/opt/vpnservice/scripts/amneziawg-remove-client.sh
```

- **AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT** — путь к скрипту на **eu1** (бот выполняет его по SSH на eu1).
- **AMNEZIAWG_EU1_INTERFACE** — имя интерфейса AmneziaWG на eu1 (нужно для удаления peer, если не используется REMOVE_CLIENT_SCRIPT).
- **AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT** — путь к скрипту удаления на **eu1** (опционально; если не задан, бот выполнит `awg set <interface> peer <key> remove`).

Сохрани файл и перезапусти бота:

```bash
sudo systemctl restart vpn-bot.service
sudo systemctl status vpn-bot.service
```

---

## Шаг 4. Проверка

1. В Telegram: выбери сервер «Европа» (/server → Европа).
2. Вызови /get_config. Должен прийти файл `.conf` (имя вида `vpn_<id>_eu1_amneziawg.conf`) и сообщение об успешном создании доступа.
3. Импортируй конфиг в AmneziaVPN/AmneziaWG и проверь подключение.
4. Вызови /regen. Должен прийти новый `.conf`; старый конфиг перестаёт работать. Импортируй новый и проверь снова.

Если бот пишет «Скрипт AmneziaWG вернул ошибку» — смотри логи бота (`journalctl -u vpn-bot.service -f`) и на eu1 проверь вручную запуск скрипта с тестовым IP и права (root/awg).

---

## Шаг 5. Друзья и знакомые

Напиши пользователям: для Европы теперь AmneziaWG. Пусть выберут в боте «Европа» (/server), нажмут /get_config и импортируют полученный .conf в AmneziaVPN/AmneziaWG по инструкции (/instruction). Регенерация — через /regen.

---

## Связанные документы

- `docs/amneziawg-eu1-discovery.md` — проверка AmneziaWG на eu1.
- `docs/amneziawg-deploy-instruction.md` — развёртывание AmneziaWG на eu1.
- `docs/client-instructions-amneziawg.md` — инструкция для пользователей (ПК + iOS).
- `docs/specs/spec-05-bot-amneziawg-eu1.md` — спецификация выдачи AmneziaWG ботом.
