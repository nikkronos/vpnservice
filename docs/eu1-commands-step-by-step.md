# eu1: команды по шагам (друг — второй ПК, ты — VPN)

Сценарий: **друг** подключается к Fornex с **второго ПК** через PowerShell и выполняет команды на сервере. **Ты** на своём ПК включаешь VPN (Европа) и проверяешь, открываются ли сайты.

---

## Пункт 1. Диагностика на Fornex (rp_filter и проверки)

### 1.1. Друг: подключение к Fornex по SSH (PowerShell)

На **втором ПК** (у друга) открыть PowerShell. Подключиться к Fornex:

- **Если ключ лежит у друга** (например, скопировал тебе файл `id_ed25519_eul` в `C:\Users\ИмяДруга\.ssh\`):

```powershell
ssh -i C:\Users\ИмяДруга\.ssh\id_ed25519_eul root@185.21.8.91
```

- **Если друг заходит по паролю root:**

```powershell
ssh root@185.21.8.91
```

(ввести пароль когда попросит)

После входа ты будешь на сервере Fornex (приглашение типа `root@hostname:~#`). Дальше все команды — **уже на Fornex**, по одной.

---

### 1.2. Друг: команды на Fornex (копировать по очереди)

По одной команде вставить в терминал и нажимать Enter.

**Шаг 1 — текущие rp_filter:**

```bash
sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.default.rp_filter net.ipv4.conf.eth0.rp_filter
```

(для wg0 может не быть — это ок)

**Шаг 2 — временно отключить rp_filter для теста:**

```bash
sysctl -w net.ipv4.conf.wg0.rp_filter=0
```

```bash
sysctl -w net.ipv4.conf.all.rp_filter=0
```

**Шаг 3 — убедиться, что применилось:**

```bash
sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.wg0.rp_filter
```

(должно быть 0)

**Шаг 4 — (опционально) дамп firewall, можно прислать тебе скрин/текст:**

```bash
iptables-save
```

**Шаг 5 — пиры WireGuard (должны быть только 10.1.0.x/32):**

```bash
wg show wg0
```

```bash
grep -E 'PublicKey|AllowedIPs' /etc/wireguard/wg0.conf
```

После шага 2–3 **друг пусть не выходит из SSH** и ждёт.

---

### 1.3. Ты: проверка с VPN

1. На **своём ПК** включи VPN **Европа** (туннель eu1) в WireGuard.
2. Открой браузер, зайди на любой сайт (например https://google.com или https://chat.openai.com).
3. В клиенте WireGuard посмотри счётчики: **«Получено»** — если число растёт, трафик пошёл.
4. Напиши другу: заработало или нет.

---

### 1.4. Если заработало — друг на Fornex фиксирует rp_filter

Если сайты открылись и «Получено» растёт, чтобы настройка не слетела после перезагрузки, друг на Fornex выполняет:

```bash
echo 'net.ipv4.conf.wg0.rp_filter=0' >> /etc/sysctl.d/99-wireguard.conf
```

```bash
echo 'net.ipv4.conf.all.rp_filter=0' >> /etc/sysctl.d/99-wireguard.conf
```

```bash
sysctl -p /etc/sysctl.d/99-wireguard.conf
```

Проверка:

```bash
sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.wg0.rp_filter
```

(должно остаться 0)

Если **не** заработало — можно вернуть rp_filter обратно (по желанию):

```bash
sysctl -w net.ipv4.conf.wg0.rp_filter=1
sysctl -w net.ipv4.conf.all.rp_filter=1
```

---

## Пункт 2. Опционально: MTU в конфиге (на Timeweb)

Делается **на сервере Timeweb**, где крутится бот. Если у тебя есть SSH к Timeweb — делаешь ты; если ключ/доступ у друга — может сделать друг.

### 2.1. Подключение к Timeweb (PowerShell)

```powershell
ssh root@81.200.146.32
```

(или с ключом: `ssh -i путь\к\ключу root@81.200.146.32`, подставить свой путь и пользователя, если не root)

### 2.2. На Timeweb: добавить MTU для eu1

Открыть файл с переменными:

```bash
nano /opt/vpnservice/env_vars.txt
```

Найти блок с `WG_EU1_*` и добавить строку (можно в конец блока):

```text
WG_EU1_MTU=1280
```

Сохранить: `Ctrl+O`, Enter, выйти: `Ctrl+X`.

### 2.3. На Timeweb: перезапуск бота

```bash
systemctl restart vpn-bot.service
```

```bash
systemctl status vpn-bot.service
```

(должно быть `active (running)`)

### 2.4. У себя: новый конфиг и тест

1. В Telegram написать боту **/regen** (если уже есть конфиг для Европы) или выбрать «Европа» в **/server** и затем **/get_config**.
2. Скачать новый `.conf` и открыть его в WireGuard (заменить туннель или добавить новый).
3. Включить VPN (Европа) и проверить сайты и счётчик «Получено».

Если в конфиге есть строка `MTU = 1280` в блоке `[Interface]` — MTU применился.

---

## Пункт 3. Если всё сделали, а сайты не открываются (Received ≈ 0)

По скриншотам часто видно: **на сервере один из пиров с AllowedIPs 10.1.0.0/24** (нужно только 10.1.0.x/32) и **UFW может резать FORWARD**. Делает друг на Fornex (SSH со второго ПК).

### 3.1. Удалить пира с 10.1.0.0/24

На Fornex по SSH выполнить:

```bash
wg show wg0
```

Найти в выводе пира, у которого **allowed ips: 10.1.0.0/24** (не 10.1.0.2/32). Скопировать его **public key** (длинная строка после `peer:`).

Удалить только этого пира (подставить свой ключ вместо `<PUBLIC_KEY>`):

```bash
wg set wg0 peer <PUBLIC_KEY> remove
```

Пример (ключ из твоего скрина для пира с 10.1.0.0/24):

```bash
wg set wg0 peer qC6xc5aEoai0IX83JbewjS/QQD+FWamRRYbZKJjeSXc= remove
```

Проверка:

```bash
wg show wg0
```

У оставшегося пира должно быть только **allowed ips: 10.1.0.2/32** (или другой один адрес 10.1.0.x/32).

### 3.2. Разрешить FORWARD в UFW

На том же Fornex в SSH:

```bash
ufw status verbose | head -25
```

Посмотреть строку **Default:** — если там **forward (deny)**, нужно явно разрешить:

```bash
ufw route allow in on wg0 out on eth0
ufw route allow in on eth0 out on wg0
ufw reload
```

Если основной интерфейс не eth0 (узнать: `ip route show default`), подставить его вместо eth0.

### 3.3. Проверка с твоей стороны

После 3.1 и 3.2: на своём ПК снова включить VPN (Европа), открыть сайт, посмотреть в WireGuard счётчик «Получено» — должен начать расти.

---

## Краткая шпаргалка по ролям

| Кто        | Где        | Действие |
|-----------|------------|----------|
| Друг      | Второй ПК  | PowerShell → `ssh root@185.21.8.91` (или с ключом), затем команды из п. 1.2 и при успехе 1.4 |
| Ты        | Свой ПК    | Включить VPN Европа, открыть сайт, смотреть «Получено» (п. 1.3) |
| Ты/друг   | Timeweb    | По желанию: добавить `WG_EU1_MTU=1280`, перезапуск бота (п. 2) |
| Ты        | Свой ПК    | После п. 2: /regen или /get_config для Европы, новый конфиг, тест |
| Друг      | Fornex     | Если не работает: п. 3 — удалить пира с 10.1.0.0/24, UFW forward (п. 3.1–3.2) |
