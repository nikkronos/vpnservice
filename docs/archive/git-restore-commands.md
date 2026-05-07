# Команды: откат репо на старый коммит (гит)

Откат репо **не восстанавливает VPN** — серверы (eu1, Timeweb) и их настройки от гита не зависят. Эти команды только меняют код и документы в репозитории.

---

## Где выполнять

- **На своём ПК (где открыт проект):** в папке репо, например  
  `c:\Users\krono\OneDrive\Рабочий стол\Cursor_Projects\Projects\VPN`  
  Открыть терминал (PowerShell или cmd) и перейти в эту папку:  
  `cd "c:\Users\krono\OneDrive\Рабочий стол\Cursor_Projects\Projects\VPN"`

- **На сервере бота (Timeweb):** в папке, откуда запускается бот, например  
  `/opt/vpnservice`  
  Подключиться по SSH к Timeweb и выполнить:  
  `cd /opt/vpnservice`

---

## Команды

### 1. Посмотреть последние коммиты

```bash
git log --oneline -20
```

Найди хеш коммита, на который хочешь откатиться (когда «всё работало»).

### 2. Откатиться на этот коммит

```bash
git checkout <хеш_коммита>
```

Пример: `git checkout ba87060`

Репо перейдёт в состояние «detached HEAD» — ты на конкретном коммите, не на ветке.

### 3. Вернуться на текущую ветку (main)

```bash
git checkout main
```

### 4. Если откатился на ПК и хочешь так же на Timeweb

На Timeweb после `cd /opt/vpnservice`:

```bash
git fetch origin
git checkout <хеш_коммита>
sudo systemctl restart vpn-bot.service
```

---

**Важно:** даже на «старом» коммите VPN не заработает, пока на eu1 не будет awg (AmneziaWG) и на Timeweb в env не будет `AMNEZIAWG_EU1_INTERFACE=awg0`. Восстановление VPN — через серверы, см. `docs/eu1-install-awg-commands.md`.
