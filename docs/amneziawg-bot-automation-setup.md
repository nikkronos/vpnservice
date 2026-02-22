# Пошаговая настройка автоматической выдачи AmneziaWG конфигов ботом

Цель: бот по команде /get_config и /regen для сервера «Европа» автоматически выдаёт AmneziaWG .conf (без ручной выдачи конфигов).

**Требования:** AmneziaWG уже развёрнут на eu1 (185.21.8.91) по `docs/amneziawg-deploy-instruction.md`. Бот работает на Timeweb и имеет SSH-доступ к eu1: в `env_vars.txt` на Timeweb заданы WG_EU1_SSH_HOST, WG_EU1_SSH_USER, WG_EU1_SSH_KEY_PATH. Рекомендуемое имя ключа на Timeweb: **`id_ed25519_eu1`** (файл должен существовать, например `/root/.ssh/id_ed25519_eu1`).

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
# SSH к eu1 (ключ должен существовать на Timeweb по указанному пути)
WG_EU1_SSH_HOST=185.21.8.91
WG_EU1_SSH_USER=root
WG_EU1_SSH_KEY_PATH=/root/.ssh/id_ed25519_eu1

# AmneziaWG: автоматическая выдача и регенерация конфигов
AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT=/opt/vpnservice/scripts/amneziawg-add-client.sh
AMNEZIAWG_EU1_NETWORK_CIDR=10.1.0.0/24
AMNEZIAWG_EU1_INTERFACE=wg0
AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT=/opt/vpnservice/scripts/amneziawg-remove-client.sh
```

- **WG_EU1_SSH_KEY_PATH** — путь к приватному ключу **на сервере бота (Timeweb)**. Рекомендуемое имя файла: `id_ed25519_eu1`. Проверка: `ls -la /root/.ssh/`; если ключ называется иначе — укажи его путь.
- **AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT** — путь к скрипту на **eu1** (бот выполняет его по SSH на eu1).
- **AMNEZIAWG_EU1_INTERFACE** — имя интерфейса на eu1 (`wg0` или `awg0`). Бот передаёт его в скрипты как AWG_INTERFACE.
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

Если в ответе бота есть «Identity file ... not accessible» или «Permission denied» — на Timeweb проверь путь в WG_EU1_SSH_KEY_PATH и наличие файла ключа (`ls -la /root/.ssh/`).

---

## Ошибка «не удалось добавить peer в awg0» (get_config / regen для Европы)

Сообщение приходит, когда скрипт на eu1 не может выполнить `awg set <interface> peer ... allowed-ips ...`. Что проверить:

### 1. Имя интерфейса на eu1

На **eu1** выполни:
```bash
ip link show | grep -E 'awg|wg'
awg show 2>/dev/null || wg show 2>/dev/null
```
Узнай реальное имя интерфейса: `awg0`, `wg0` или другое.

### 2. Одна строка AMNEZIAWG_EU1_INTERFACE на Timeweb

На **сервере бота (Timeweb)** в `env_vars.txt` должна быть **только одна** строка `AMNEZIAWG_EU1_INTERFACE=...` с тем именем, что на eu1. Если добавляли вторую строку (например сначала было wg0, потом дописали awg0) — удали дубликат и оставь одно значение, совпадающее с интерфейсом на eu1:
```bash
# На Timeweb: посмотреть все вхождения
grep AMNEZIAWG_EU1_INTERFACE /opt/vpnservice/env_vars.txt
# Отредактировать файл и оставить одну строку, например:
# AMNEZIAWG_EU1_INTERFACE=awg0   # если на eu1 интерфейс awg0
# или
# AMNEZIAWG_EU1_INTERFACE=wg0    # если на eu1 интерфейс wg0
```
После правки: `sudo systemctl restart vpn-bot.service`.

### 3. Запуск скрипта на eu1 от root

Подключись по SSH к **eu1** и запусти скрипт вручную (подставь свой свободный IP из пула, например 10.1.0.99):
```bash
sudo AWG_INTERFACE=awg0 /opt/vpnservice/scripts/amneziawg-add-client.sh 10.1.0.99
```
Если здесь та же ошибка — проблема на eu1 (интерфейс не awg0, или нужен `sudo`, или путь к `awg` не в PATH при вызове по SSH). Проверь: `which awg`, `sudo awg show awg0`.

Бот по SSH выполняет команду от пользователя WG_EU1_SSH_USER (обычно root). Если на eu1 скрипт должен идти с sudo — либо залогинься на eu1 как root, либо настрой sudo без пароля для этого скрипта.

---

## Шаг 5. Друзья и знакомые

Напиши пользователям: для Европы теперь AmneziaWG. Пусть выберут в боте «Европа» (/server), нажмут /get_config и импортируют полученный .conf в AmneziaVPN/AmneziaWG по инструкции (/instruction). Регенерация — через /regen.

---

## Деплой обновлений бота

После изменений в коде бота (репозиторий `nikkronos/vpnservice`):

1. **Локально:** коммит и пуш в `main`:
   ```bash
   cd Projects/VPN   # или путь к клону репо vpnservice
   git add bot/ docs/ env_vars.example.txt
   git commit -m "fix: ..."
   git push origin main
   ```

2. **На сервере бота (Timeweb):** подтянуть код и перезапустить сервис:
   ```bash
   cd /opt/vpnservice
   git pull
   sudo systemctl restart vpn-bot.service
   sudo systemctl status vpn-bot.service
   ```

Переменные окружения (`env_vars.txt`) на Timeweb при этом не меняются — правь их только при смене ключей, хостов или путей к скриптам.

---

## Связанные документы

- `docs/amneziawg-eu1-discovery.md` — проверка AmneziaWG на eu1.
- `docs/amneziawg-deploy-instruction.md` — развёртывание AmneziaWG на eu1.
- `docs/client-instructions-amneziawg.md` — инструкция для пользователей (ПК + iOS).
- `docs/specs/spec-05-bot-amneziawg-eu1.md` — спецификация выдачи AmneziaWG ботом.
