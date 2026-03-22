# Восстановление интернета через VPN на eu1

Если туннель поднимается (handshake есть), но интернет не работает — пройди по шагам **на сервере eu1** по порядку.

---

## 1. У какого пира сейчас handshake

```bash
wg show wg0
```

Найди пира с **самым свежим** handshake (секунды/минуты назад). Запомни его **public key** и **allowed ips**.

- Если у этого пира **allowed ips: (none)** — задай IP вручную (подставь свой ключ и нужный IP, например 10.1.0.21):
  ```bash
  sudo wg set wg0 peer ПУБЛИЧНЫЙ_КЛЮЧ_ИЗ_ВЫВОДА allowed-ips 10.1.0.21/32
  ```

---

## 2. INPUT: ответный трафик не должен дропаться

После MASQUERADE ответы приходят на IP сервера и обрабатываются цепочкой **INPUT**. Правило для ESTABLISHED,RELATED должно быть **первым**.

```bash
# Проверить, есть ли в начале INPUT правило ESTABLISHED,RELATED
sudo iptables -L INPUT -n -v --line-numbers | head -5
```

Если в первых строках нет `state ESTABLISHED,RELATED` с ACCEPT — добавь в самое начало:

```bash
sudo iptables -I INPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT
```

---

## 3. POSTROUTING: NAT для 10.1.0.0/24

Трафик из VPN (10.1.0.x) должен маскарадиться при выходе в eth0.

```bash
sudo iptables -t nat -L POSTROUTING -n -v --line-numbers
```

Должно быть правило вида: **source 10.1.0.0/24**, **out eth0**, **target MASQUERADE**. Если его нет — добавь:

```bash
sudo iptables -t nat -A POSTROUTING -s 10.1.0.0/24 -o eth0 -j MASQUERADE
```

Если перед ним есть правило «0.0.0.0/0 → eth0 MASQUERADE», то NAT уже делается им; тогда шаг можно пропустить, но правило для 10.1.0.0/24 не помешает.

---

## 4. FORWARD: wg0 ↔ eth0 до Docker

Правила для wg0 должны быть **в начале** FORWARD (до DOCKER-USER / DOCKER-FORWARD):

```bash
sudo iptables -I FORWARD 1 -i eth0 -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
sudo iptables -I FORWARD 1 -i wg0 -o eth0 -j ACCEPT
```

(Если уже делал — порядок уже верный, повторять не обязательно.)

---

## 5. Reverse path filter (по желанию)

Иногда из‑за rp_filter дропается ответный трафик. Можно временно отключить:

```bash
sudo sysctl -w net.ipv4.conf.all.rp_filter=0
sudo sysctl -w net.ipv4.conf.wg0.rp_filter=0
sudo sysctl -w net.ipv4.conf.eth0.rp_filter=0
```

Проверь интернет. Если заработало — зафиксируй в `/etc/sysctl.d/99-wireguard.conf` или в PostUp в wg0.conf.

---

## 6. На клиенте (телефон/ПК)

- В конфиге в секции `[Interface]` должно быть **Address = 10.1.0.21/32** (или тот IP, который ты задал пиру на сервере).
- В секции `[Peer]` — **AllowedIPs = 0.0.0.0/0** (весь трафик через VPN).
- Конфиг — **тот же**, что соответствует пиру с свежим handshake (тот же публичный ключ клиента на сервере).

Если после правок на eu1 интернет так и не пошёл — пришли вывод команд из шагов 1–3 (wg show, INPUT, POSTROUTING).
