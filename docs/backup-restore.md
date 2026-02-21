# Резервное копирование и восстановление конфигов VPN‑сервера

## Цель

Перед любыми изменениями на сервере Fornex создавать резервные копии конфигов WireGuard, Shadowsocks, AmneziaWG и (при необходимости) MTProto. При сбое — восстанавливать из бэкапа.

**Бэкап в Git:** конфиги и экспорты (в т.ч. AmneziaWG) можно хранить в репозитории, если репозиторий **приватный**. После добавления бэкапа — убедиться, что репозиторий приватный; не коммитить секреты в публичный репозиторий.

## Расположение бэкапов

- **Базовая директория**: `/root/vpn-backups/`
- **Структура**: по датам `YYYY-MM-DD`, например `/root/vpn-backups/2026-02-18/`
- **Содержимое** (рекомендуемое):
  - `wg0.conf` — конфиг WireGuard‑сервера
  - `iphone.conf`, `friend-pc.conf`, … — клиентские конфиги
  - `ss-wg.json` — конфиг Shadowsocks‑клиента (ss-redir)
  - `mtproto-link.txt` — ссылка MTProto‑прокси (если используется)

## Процедура резервного копирования

### Перед изменениями (обязательно)

```bash
BACKUP_DIR=/root/vpn-backups/$(date +%Y-%m-%d)
sudo mkdir -p "$BACKUP_DIR"

# WireGuard
sudo cp /etc/wireguard/wg0.conf "$BACKUP_DIR/"
sudo cp /etc/wireguard/*.conf "$BACKUP_DIR/" 2>/dev/null || true

# Shadowsocks
sudo cp /etc/shadowsocks-libev/ss-wg.json "$BACKUP_DIR/" 2>/dev/null || true

# MTProto (если есть файл со ссылкой)
[ -f /root/vpn-backups/2026-02-18/mtproto-link.txt ] && sudo cp /root/vpn-backups/2026-02-18/mtproto-link.txt "$BACKUP_DIR/" 2>/dev/null || true

echo "Backup done: $BACKUP_DIR"
ls -la "$BACKUP_DIR"
```

### После добавления нового клиента

Скопировать новый клиентский конфиг в текущую дата‑директорию:

```bash
BACKUP_DIR=/root/vpn-backups/$(date +%Y-%m-%d)
sudo cp /etc/wireguard/NEW_CLIENT.conf "$BACKUP_DIR/"
```

## Процедура восстановления

### Восстановление только WireGuard (`wg0.conf`)

```bash
# Выбери нужную дату
BACKUP_DIR=/root/vpn-backups/2026-02-18

sudo cp "$BACKUP_DIR/wg0.conf" /etc/wireguard/wg0.conf
sudo systemctl restart wg-quick@wg0
sudo wg show
```

### Восстановление клиентского конфига

```bash
BACKUP_DIR=/root/vpn-backups/2026-02-18
sudo cp "$BACKUP_DIR/iphone.conf" /etc/wireguard/iphone.conf
# Дальше раздать конфиг клиенту при необходимости
```

### Восстановление Shadowsocks (ss-wg.json)

```bash
BACKUP_DIR=/root/vpn-backups/2026-02-18
sudo cp "$BACKUP_DIR/ss-wg.json" /etc/shadowsocks-libev/ss-wg.json
sudo systemctl restart ss-wg.service
sudo systemctl status ss-wg.service
```

### Восстановление iptables (редирект)

Правила редиректа не хранятся в файлах по умолчанию; они задаются вручную или через PostUp в `wg0.conf`. Текущие правила можно сохранить:

```bash
sudo iptables-save | grep -E "PREROUTING|1081|wg0" > /root/vpn-backups/$(date +%Y-%m-%d)/iptables-redirect.txt
```

Восстановление — по записи в этом файле (добавить правила вручную или скриптом).

## Рекомендации

1. **Перед правкой** `wg0.conf`, `ss-wg.json` или добавлением iptables — всегда делать бэкап в новую дата‑директорию.
2. **Не хранить секреты** (ключи, пароли) в Git; бэкапы на сервере доступны только root.
3. **Периодически** проверять наличие и читаемость бэкапов (`ls -la /root/vpn-backups/`).
4. При **миграции на другой сервер** — скопировать всю нужную дата‑директорию и восстановить конфиги по шагам выше; ключи и пароли переносить отдельно, безопасно.

## Связанные документы

- `docs/specs/spec-01-architecture-wg-ss.md` — архитектура
- `docs/checklist-add-client.md` — добавление клиента
