# Резюме сессии 2026-05-11

## Контекст

Сервер Fornex (`185.21.8.91`) показал скачок CPU до 98.69% в 12:11 МСК (09:11 UTC).
Одновременно — входящий трафик 22 МБит/с. VPN и PastuhiBot отвалились.
Пользователь перезагрузил сервер — всё поднялось, но причина была неясна.

---

## Диагностика

**Причина скачка:** комбо из двух факторов:
1. **SSH брутфорс без защиты** — с момента старта сервера шёл непрерывный перебор паролей с десятков IP. Без fail2ban каждая попытка порождала процесс sshd → CPU под нагрузкой.
2. **Возможный UDP-флуд на порт 39580** (AmneziaWG) — входящий трафик 22 МБит/с после ребута.

**Логи:** `auth.log` зафиксировал брутфорс с IP `92.118.39.236`, `2.57.122.197`, `45.148.10.152` и др. сразу после старта.

---

## Что сделано

### Блок А — SSH (критично)

1. **fail2ban установлен и активен:**
   ```bash
   apt install -y fail2ban
   systemctl enable fail2ban && systemctl start fail2ban
   ```
   Автоматически банит IP после нескольких неудачных попыток входа.

2. **Вход по паролю отключён** — только по SSH-ключу:
   - Исправлен `/etc/ssh/sshd_config` (PasswordAuthentication no)
   - Исправлен `/etc/ssh/sshd_config.d/50-cloud-init.conf` (этот файл перекрывал основной — важно!)
   - `systemctl restart ssh`

3. **SSH-ключ для Fornex на Windows:**
   - Ключ: `C:\Users\krono\.ssh\id_ed25519_fornex`
   - Добавлен в `~/.ssh/authorized_keys` на сервере
   - SSH-алиас в `C:\Users\krono\.ssh\config`:
     ```
     Host fornex
         HostName 185.21.8.91
         User root
         IdentityFile ~/.ssh/id_ed25519_fornex
     ```
   - Теперь вход: `ssh fornex` (без пароля, без указания ключа)

### Блок Б — Rate-limit на VPN-порт

Добавлены iptables-правила для защиты от UDP-флуда на порт 39580 (AmneziaWG):
```bash
iptables -A INPUT -p udp --dport 39580 -m limit --limit 1000/sec --limit-burst 2000 -j ACCEPT
iptables -A INPUT -p udp --dport 39580 -j DROP
apt install -y iptables-persistent && netfilter-persistent save
```
Правила сохранены (переживут ребут). Лимит 1000 пакетов/сек — реальные пользователи VPN не достигают этого порога.

### Блок В — Мониторинг истории

Установлен `sysstat`:
```bash
apt install -y sysstat
sed -i 's/ENABLED=.false./ENABLED="true"/' /etc/default/sysstat
systemctl restart sysstat
```
Теперь история CPU/сети доступна командой `sar -u 1 10` прямо на сервере.

---

## Важные нюансы для следующего агента

- **`/etc/ssh/sshd_config.d/50-cloud-init.conf`** перекрывает основной sshd_config — если нужно менять SSH-настройки, менять нужно именно этот файл, а не только основной.
- **Вход на Fornex теперь только по ключу.** Команды вида `ssh root@185.21.8.91` без ключа не работают — только `ssh fornex` или `ssh -i ~/.ssh/id_ed25519_fornex root@185.21.8.91`.
- **iptables-правила сохранены** через `iptables-persistent` — переживут ребут автоматически.

---

## Статус после сессии

| Компонент | Статус |
|-----------|--------|
| fail2ban | ✅ Активен |
| SSH вход по паролю | ❌ Отключён (только ключ) |
| SSH-ключ fornex | ✅ Настроен |
| Rate-limit UDP 39580 | ✅ Активен, сохранён |
| sysstat | ✅ Активен |
| VPN (AmneziaWG) | ✅ Работает |
| vpn-bot.service | ✅ Работает |
| mtproxy-faketls | ✅ Работает |
| PastuhiBot (hamster*) | ✅ Работает |
