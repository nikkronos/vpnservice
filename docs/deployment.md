# Деплой и сервер VPN

## Распределение серверов

| Сервер | Назначение | Что крутится |
|--------|------------|--------------|
| **Timeweb** | Хостинг бота и (ранее) нода РФ | Telegram‑бот VPN: код в `/opt/vpnservice`, сервис `vpn-bot.service`. Бот выдаёт конфиги, создаёт пиры на Timeweb (нода РФ) и на Fornex (нода eu1) по SSH. Переменные окружения бота: `env_vars.txt` на Timeweb (BOT_TOKEN, WG_*, WG_EU1_*, при необходимости MTPROTO_PROXY_LINK). |
| **Fornex (eu1)** | VPN‑нода «Европа» | WireGuard (wg0), Shadowsocks‑клиент (ss-redir), MTProto‑прокси (Docker). IP 185.21.8.91. Конфиги: `/etc/wireguard/`, `/etc/shadowsocks-libev/`, бэкапы в `/root/vpn-backups/`. |

Код бота хранится в репозитории `nikkronos/vpnservice`; на Timeweb в `/opt/vpnservice` делается `git pull` и перезапуск `vpn-bot.service`. Файлы между серверами: бот на Timeweb, VPN‑сервисы (WireGuard, SS, MTProto) на Fornex.

### Обновление бота на Timeweb

1. Подключись по SSH к серверу Timeweb.
2. Обновить код и перезапустить сервис:
   ```bash
   cd /opt/vpnservice && git pull origin main
   sudo systemctl restart vpn-bot.service
   ```
3. **Переменные окружения:** файл `env_vars.txt` на сервере **не в Git** (в репозитории только `env_vars.example.txt`). Если в проекте добавили новую переменную (например `MTPROTO_PROXY_LINK`), её нужно **вручную добавить в `/opt/vpnservice/env_vars.txt` на сервере**, затем перезапустить бота:
   ```bash
   sudo nano /opt/vpnservice/env_vars.txt
   # добавить строку, например: MTPROTO_PROXY_LINK=tg://proxy?server=...
   sudo systemctl restart vpn-bot.service
   ```
   Правки в `env_vars.txt` на своём ПК (в папке проекта) на работу бота на Timeweb **не влияют** — бот читает только файл на сервере.

4. Проверить логи при сбоях:
   ```bash
   sudo journalctl -u vpn-bot.service -n 100 --no-pager
   ```

---

## Сервер Fornex (eu1)

- **Провайдер**: Fornex
- **ОС**: Ubuntu 24.04 LTS
- **Назначение**: VPN‑сервер (WireGuard), интеграция с Shadowsocks, MTProto‑прокси для Telegram
- **Внешний IP**: хранится на сервере и в конфигах клиентов (не коммитить в Git)

## Расположение конфигов и сервисов

| Компонент | Путь / сервис | Примечание |
|-----------|----------------|------------|
| WireGuard (сервер) | `/etc/wireguard/wg0.conf` | Конфиг интерфейса `wg0` |
| WireGuard (клиентские конфиги) | `/etc/wireguard/*.conf` | `iphone.conf`, `friend-pc.conf` и т.д. |
| Shadowsocks (клиент ss-redir) | `/etc/shadowsocks-libev/ss-wg.json` | Конфиг для редиректа |
| Резервные копии | `/root/vpn-backups/YYYY-MM-DD/` | Бэкапы конфигов по датам |
| MTProto‑прокси | Docker‑контейнер `mtproto-proxy` | Порт 443/TCP |

## Systemd‑сервисы

| Сервис | Назначение | Команды проверки |
|--------|------------|-------------------|
| `wg-quick@wg0` | WireGuard интерфейс `wg0` | `sudo systemctl status wg-quick@wg0`, `sudo wg show` |
| `ss-wg.service` | Shadowsocks‑редирект (ss-redir) на порту 1081 | `sudo systemctl status ss-wg.service` |
| `docker` | Docker daemon (для MTProto) | `sudo systemctl status docker`, `sudo docker ps \| grep mtproto-proxy` |

## Команды проверки состояния

```bash
# WireGuard
sudo wg show
sudo systemctl status wg-quick@wg0

# Shadowsocks
sudo systemctl status ss-wg.service
ss -tlnp | grep 1081

# iptables (редирект на 1081)
sudo iptables -t nat -L PREROUTING -n | grep 1081

# MTProto
sudo docker ps | grep mtproto-proxy
sudo docker logs mtproto-proxy --tail 10
```

## Порты

| Порт | Протокол | Сервис |
|------|----------|--------|
| 51820 | UDP | WireGuard (wg0) |
| 1081 | TCP (localhost) | ss-redir (Shadowsocks) |
| 443 | TCP | MTProto‑прокси (Docker) |

## Скрипт add-ss-redirect.sh (VPN+GPT)

Для опции «VPN+GPT» в боте (Европа) бот по SSH вызывает на eu1 скрипт, который добавляет iptables‑редирект TCP 80/443 для IP клиента на порт 1081 (ss-redir). Так трафик HTTP/HTTPS пользователя идёт через Shadowsocks (обход блокировок ChatGPT и др.).

- **Развёртывание на eu1:** скопировать содержимое из `docs/scripts/add-ss-redirect.sh.example` в скрипт на сервере, например `/opt/vpnservice/scripts/add-ss-redirect.sh`, и выполнить `chmod +x add-ss-redirect.sh`. Скрипт должен запускаться с `sudo`.
- **Путь по умолчанию**, с которым бот обращается к скрипту: `/opt/vpnservice/scripts/add-ss-redirect.sh`. Переопределение: в `env_vars.txt` на Timeweb задать `WG_EU1_ADD_SS_REDIRECT_SCRIPT=/путь/на/eu1/add-ss-redirect.sh`.
- Пул IP для VPN+GPT на eu1: **10.1.0.8–10.1.0.254** (обычные peer'ы eu1 используют 10.1.0.2–10.1.0.7).

## Резервное копирование и восстановление

См. `docs/backup-restore.md`.

## SSH и доступ

- Подключение: по SSH (пользователь и ключ/пароль хранятся вне репозитория).
- После изменений конфигов: перезапуск соответствующих сервисов (см. выше и `docs/checklist-add-client.md`).

## Связанные документы

- `docs/specs/spec-01-architecture-wg-ss.md` — архитектура
- `docs/checklist-add-client.md` — добавление клиента
- `docs/backup-restore.md` — бэкапы и восстановление
- `README_FOR_NEXT_AGENT.md` — текущее состояние проекта
