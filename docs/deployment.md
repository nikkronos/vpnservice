# Деплой и сервер VPN

## Распределение серверов

| Сервер | Назначение | Что крутится |
|--------|------------|--------------|
| **Timeweb** | Хостинг бота и (ранее) нода РФ | Telegram‑бот VPN: код в `/opt/vpnservice`, сервис `vpn-bot.service`. Бот выдаёт конфиги, создаёт пиры на Timeweb (нода РФ) и на Fornex (нода eu1) по SSH. Переменные окружения бота: `env_vars.txt` на Timeweb (BOT_TOKEN, WG_*, WG_EU1_*, при необходимости MTPROTO_PROXY_LINK). |
| **Fornex (eu1)** | VPN‑нода «Европа» | WireGuard (wg0), Shadowsocks‑клиент (ss-redir), MTProto‑прокси (Docker). IP 185.21.8.91. Конфиги: `/etc/wireguard/`, `/etc/shadowsocks-libev/`, бэкапы в `/root/vpn-backups/`. |

Код бота хранится в репозитории `nikkronos/vpnservice`; на Timeweb в `/opt/vpnservice` делается `git pull` и перезапуск `vpn-bot.service`. Файлы между серверами: бот на Timeweb, VPN‑сервисы (WireGuard, SS, MTProto) на Fornex.

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
