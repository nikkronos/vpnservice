# Команды: установка AmneziaWG на eu1 и переключение на awg0

Только команды. Выполнять по порядку.

---

## На eu1 (Fornex, root@284854)

Подключись по SSH к eu1.

### Вариант A: установщик (скрипт)

```bash
curl -O https://raw.githubusercontent.com/romikb/amneziawg-install/main/amneziawg-install.sh
chmod +x amneziawg-install.sh
./amneziawg-install.sh
```

Скрипт спросит параметры (подсеть, порт и т.д.). Подсеть eu1 — **10.1.0.0/24**, порт можно оставить по умолчанию или **51820** (как у wg0). После установки проверь:

```bash
which awg
awg show awg0
```

### Вариант B: Ubuntu/Debian (ppa + apt)

```bash
sudo add-apt-repository ppa:amnezia/ppa
sudo apt update
sudo apt install -y amneziawg
```

Проверка:

```bash
which awg
```

Дальше настроить интерфейс awg0 и NAT/forward для 10.1.0.0/24 — по документации Amnezia или скрипту из варианта A.

---

## На Timeweb (сервер бота)

После того как на eu1 есть `awg` и интерфейс **awg0**:

```bash
grep AMNEZIAWG_EU1_INTERFACE /opt/vpnservice/env_vars.txt
```

В файле должна быть **одна** строка:

```bash
AMNEZIAWG_EU1_INTERFACE=awg0
```

Если стоит `wg0` — отредактировать `env_vars.txt` и поставить `awg0`. Затем:

```bash
sudo systemctl restart vpn-bot.service
sudo systemctl status vpn-bot.service
```

---

## В боте

В Telegram: /server → Европа, затем /get_config или /regen. Импортировать новый конфиг в Amnezia на устройстве и подключаться к awg0.
