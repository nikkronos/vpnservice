# Чеклист: что сделать на eu1 для универсального профиля (Unified)

Если пользователь уже получил конфиг через бота (`vpn_*_eu1_unified.conf`) и импортировал его в WireGuard или AmneziaVPN — пир на сервере уже создан. Чтобы трафик к ChatGPT и заблокированным сайтам шёл через Shadowsocks, на **eu1** нужно выполнить однократную настройку ниже.

**Важно:** диапазон клиентов Unified — **10.1.0.20–10.1.0.50** (не 19.1.0.20). Если правило добавляли с опечаткой — удалить его и добавить с правильным диапазоном.

---

## Команды по порядку (копируй и выполняй по одной)

Подключись к eu1 по SSH (`ssh root@185.21.8.91`), затем по очереди:

```bash
# 1. Установить ipset
apt update && apt install -y ipset
```

```bash
# 2. Создать ipset (если уже есть — не страшно)
ipset create unified_ss_dst hash:ip family inet 2>/dev/null || true
```

```bash
# 3. Удалить правило с неправильным диапазоном (19.1.0.x), если добавляли — одна строка
iptables -t nat -D PREROUTING -i wg0 -m iprange --src-range 19.1.0.20-10.1.0.50 -p tcp -m set --match-set unified_ss_dst dst -m multiport --dports 80,443 -j REDIRECT --to-ports 1081 2>/dev/null || true
```

```bash
# 4. Добавить правильное правило (диапазон 10.1.0.20–10.1.0.50)
iptables -t nat -A PREROUTING -i wg0 -m iprange --src-range 10.1.0.20-10.1.0.50 -p tcp -m set --match-set unified_ss_dst dst -m multiport --dports 80,443 -j REDIRECT --to-ports 1081
```

```bash
# 5. Заполнить ipset IP ChatGPT и др. (скрипт должен быть в /opt/vpnservice/scripts/)
sudo /opt/vpnservice/scripts/update-unified-ss-ips.sh
```

```bash
# 6. Проверить ss-redir на 1081
ss -tlnp | grep 1081
```

```bash
# 7. Сохранить настройки (чтобы не потерялись после перезагрузки)
ipset save > /etc/ipset.unified.conf
iptables-save > /etc/iptables.rules
```

После шага 7 настройка на сервере готова. Дальше — восстановление ipset/iptables после перезагрузки (см. раздел 6 ниже).

---

## 1. Подключиться к eu1 по SSH

```bash
ssh root@185.21.8.91
```

(или ваш пользователь и ключ)

---

## 2. Установить ipset (если ещё нет)

```bash
apt update && apt install -y ipset
```

---

## 3. Создать ipset и правило iptables для диапазона 10.1.0.20–50

Скопировать скрипт из репозитория или выполнить вручную.

**Вариант А — из репо (если есть файл на сервере):**

```bash
sudo /opt/vpnservice/scripts/setup-unified-iptables.sh
```

**Вариант Б — вручную (скопировать и выполнить по очереди):**

```bash
# Создать ipset
ipset create unified_ss_dst hash:ip family inet 2>/dev/null || true

# Добавить правило: трафик от 10.1.0.20–50 к IP из ipset, порты 80/443 → перенаправить на 1081 (ss-redir)
iptables -t nat -A PREROUTING -i wg0 -m iprange --src-range 10.1.0.20-10.1.0.50 -p tcp -m set --match-set unified_ss_dst dst -m multiport --dports 80,443 -j REDIRECT --to-ports 1081
```

---

## 4. Заполнить ipset IP-адресами ChatGPT и др.

Нужно, чтобы в `unified_ss_dst` попали IP доменов, которые должны идти через Shadowsocks (ChatGPT и т.п.). Запустить скрипт обновления или один раз добавить IP вручную.

**Вариант А — скрипт (если есть на сервере):**

```bash
sudo /opt/vpnservice/scripts/update-unified-ss-ips.sh
```

**Вариант Б — вручную добавить несколько IP для проверки:**

```bash
# Пример: добавить IP openai.com / chat.openai.com (узнать можно: getent ahosts chat.openai.com или dig +short chat.openai.com)
ipset add unified_ss_dst 104.18.2.0   # пример, подставь актуальные IP
ipset add unified_ss_dst 172.67.0.0   # пример
```

Лучше использовать скрипт `update-unified-ss-ips.sh` — он разрешает домены (openai.com, chat.openai.com, chatgpt.com и др.) и добавляет их в ipset.

---

## 5. Проверить, что ss-redir слушает на 1081

```bash
ss -tlnp | grep 1081
```

Должен быть процесс (часто `ss-redir`) на `127.0.0.1:1081`. Если нет — запустить сервис Shadowsocks (ss-redir), как настроено для VPN+GPT на eu1.

---

## 6. Сохранить ipset и iptables после перезагрузки

```bash
ipset save > /etc/ipset.unified.conf
iptables-save > /etc/iptables.rules
```

Настроить восстановление при загрузке (например, через `ipset restore < /etc/ipset.unified.conf` в скрипте в `/etc/network/if-up.d/` или через netfilter-persistent/iptables-persistent).

---

## Итог

- **Пир** для твоего конфига бот уже добавил (при `/get_config`).
- На сервере нужно: **ipset** → **правило iptables** для 10.1.0.20–50 → **заполнить ipset** IP ChatGPT/заблокированных → убедиться, что **ss-redir** на 1081 работает.

После этого с ПК (WireGuard или AmneziaVPN с этим конфигом) обычные сайты идут напрямую, а трафик к IP из ipset (ChatGPT и др.) — через Shadowsocks.

**Важно:** если ты из России и до eu1 по обычному WireGuard трафик не ходит (известная проблема маршрута), то подключение может установиться, но интернет не появится. Тогда нужен обфусцированный протокол на сервере — AmneziaWG по инструкции `amneziawg-deploy-instruction.md`.
