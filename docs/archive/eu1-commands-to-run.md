# Команды: что выполнить для работы VPN на eu1

Сейчас на eu1 (Fornex) только **wg0** (awg нет). Ниже — команды по шагам: сначала **Timeweb**, потом **eu1**.

---

## Часть 1. На Timeweb (сервер бота)

Подключись по SSH к **Timeweb** (не к eu1).

### 1.1. Проверить env: одна строка AMNEZIAWG_EU1_INTERFACE

```bash
grep AMNEZIAWG_EU1_INTERFACE /opt/vpnservice/env_vars.txt
```

Должна быть **одна** строка. Так как на eu1 нет awg, значение должно быть **wg0**:

```bash
AMNEZIAWG_EU1_INTERFACE=wg0
```

Если строк несколько или стоит awg0 — отредактируй файл (nano/vim) и оставь только:

```bash
AMNEZIAWG_EU1_INTERFACE=wg0
```

### 1.2. Перезапустить бота

```bash
sudo systemctl restart vpn-bot.service
sudo systemctl status vpn-bot.service
```

---

## Часть 2. На eu1 (Fornex, 185.21.8.91)

Подключись по SSH к **eu1** (root@284854 или по IP 185.21.8.91).

### 2.1. Проверить пира (allowed-ips) — обязательно

Без **allowed-ips** у твоего пира на сервере интернет через VPN не заработает, даже если INPUT/FORWARD/POSTROUTING настроены.

```bash
wg show wg0
```

Найди пира, с которого ты подключаешься (публичный ключ клиента — в конфиге на телефоне, секция `[Peer]`, строка `PublicKey = ...`). Если у этого пира **allowed ips: (none)** — задай IP (тот же, что в конфиге в `[Interface]`, строка `Address = 10.1.0.21/32`):

```bash
sudo wg set wg0 peer ПУБЛИЧНЫЙ_КЛЮЧ_КЛИЕНТА allowed-ips 10.1.0.21/32
```

Пример (если ключ клиента именно этот и IP 10.1.0.21):

```bash
sudo wg set wg0 peer BQXpQfn+TWwbsqn2wVIRDz3NGEsJ190i9jHdTxFeriQ= allowed-ips 10.1.0.21/32
```

Проверка: снова `wg show wg0` — у твоего пира должно быть **allowed ips: 10.1.0.21/32**, не (none).

### 2.2. INPUT: правило ESTABLISHED,RELATED в начало

Проверить:

```bash
sudo iptables -L INPUT -n -v --line-numbers | head -5
```

Если в первых строках **нет** правила с `state ESTABLISHED,RELATED` и ACCEPT — добавить:

```bash
sudo iptables -I INPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT
```

### 2.3. POSTROUTING: MASQUERADE для 10.1.0.0/24

Проверить:

```bash
sudo iptables -t nat -L POSTROUTING -n -v --line-numbers
```

Если **нет** правила с source 10.1.0.0/24, out eth0, MASQUERADE — добавить:

```bash
sudo iptables -t nat -A POSTROUTING -s 10.1.0.0/24 -o eth0 -j MASQUERADE
```

### 2.4. FORWARD: правила wg0 в начало цепочки

Вставить правила в **начало** FORWARD (до Docker):

```bash
sudo iptables -I FORWARD 1 -i eth0 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo iptables -I FORWARD 1 -i wg0 -o eth0 -j ACCEPT
```

### 2.5. (По желанию) rp_filter — если интернет всё ещё не работает

```bash
sudo sysctl -w net.ipv4.conf.all.rp_filter=0
sudo sysctl -w net.ipv4.conf.wg0.rp_filter=0
sudo sysctl -w net.ipv4.conf.eth0.rp_filter=0
```

Проверить интернет с телефона/ПК через VPN. Если заработало — зафиксировать в `/etc/sysctl.d/99-wireguard.conf`:

```bash
echo "net.ipv4.conf.all.rp_filter=0" | sudo tee -a /etc/sysctl.d/99-wireguard.conf
echo "net.ipv4.conf.wg0.rp_filter=0" | sudo tee -a /etc/sysctl.d/99-wireguard.conf
echo "net.ipv4.conf.eth0.rp_filter=0" | sudo tee -a /etc/sysctl.d/99-wireguard.conf
sudo sysctl -p /etc/sysctl.d/99-wireguard.conf
```

---

## Кратко: только команды без пояснений (eu1)

Если уже проверял и хочешь просто вставить всё подряд на **eu1**:

```bash
# allowed-ips — только если у пира (none); подставь ключ и IP
# sudo wg set wg0 peer ПУБЛИЧНЫЙ_КЛЮЧ allowed-ips 10.1.0.21/32

sudo iptables -I INPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT
sudo iptables -t nat -A POSTROUTING -s 10.1.0.0/24 -o eth0 -j MASQUERADE
sudo iptables -I FORWARD 1 -i eth0 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo iptables -I FORWARD 1 -i wg0 -o eth0 -j ACCEPT
```

После выполнения проверь интернет с устройства через VPN. Из РФ обычный WireGuard (wg0) может блокироваться РКН; обход — только через AmneziaWG (awg0), для этого нужно сначала установить AmneziaWG на eu1.
