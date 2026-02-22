# Команды «чистого сброса» eu1 — копировать по шагам

Все команды ниже выполняются **на сервере eu1 (Fornex)** по SSH. Сначала подключись к eu1, затем копируй блоки по порядку.

**Подключение к eu1 (с твоего ПК в PowerShell):**

```powershell
ssh root@185.21.8.91
```

Если используешь ключ (например `id_ed25519_eu1`):

```powershell
ssh -i "C:\Users\krono\.ssh\id_ed25519_eu1" root@185.21.8.91
```

(Путь к ключу замени на свой.)

---

## Фаза 1. Бэкапы (выполнить одним блоком на eu1)

Скопируй весь блок и вставь в терминал SSH на eu1.

```bash
BACKUP_DIR="/root/eu1-backup-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

# Конфиги AmneziaWG и WireGuard
cp -r /etc/amnezia  "$BACKUP_DIR/" 2>/dev/null || true
cp -r /etc/wireguard "$BACKUP_DIR/" 2>/dev/null || true

# iptables и состояние
iptables-save > "$BACKUP_DIR/iptables-save.txt"
ip6tables-save > "$BACKUP_DIR/ip6tables-save.txt" 2>/dev/null || true
ss -tulnp > "$BACKUP_DIR/ss-tulnp.txt"
systemctl list-units --type=service --state=running | grep -E 'wg|awg|wireguard' > "$BACKUP_DIR/wg-services.txt" 2>/dev/null || true

# Показать, что сохранили
echo "=== Backup in $BACKUP_DIR ==="
ls -la "$BACKUP_DIR"
echo "=== WireGuard configs ==="
ls -la /etc/wireguard/
```

Проверь вывод: в `$BACKUP_DIR` должны быть папки `wireguard`, возможно `amnezia`, и файлы `iptables-save.txt`, `ss-tulnp.txt`. Запомни путь к бэкапу (например `/root/eu1-backup-20260222`).

---

## Фаза 2. Остановка и очистка AmneziaWG (и wg0)

**Шаг 2.1 — посмотреть, какие интерфейсы и сервисы есть:**

```bash
echo "=== Interfaces ==="
ip link show | grep -E 'awg|wg'
echo "=== Services (wg/awg) ==="
systemctl list-units --all | grep -E 'wg|awg'
```

По выводу запомни имя интерфейса AmneziaWG (обычно `awg0`) и имя сервиса (например `wg-quick@awg0` или `awg0.service`).

**Шаг 2.2 — остановить AmneziaWG:**

```bash
# Подставь свой интерфейс, если не awg0
systemctl stop wg-quick@awg0 2>/dev/null || true
systemctl disable wg-quick@awg0 2>/dev/null || true
# Альтернативные имена сервиса (если приложение Amnezia ставило иначе)
systemctl stop awg0 2>/dev/null || true
systemctl stop amneziawg@awg0 2>/dev/null || true
ip link set awg0 down 2>/dev/null || true
```

**Шаг 2.3 — перенести конфиги AmneziaWG в бэкап (не удалять):**

```bash
BACKUP_DIR=$(ls -d /root/eu1-backup-* 2>/dev/null | tail -1)
if [ -z "$BACKUP_DIR" ]; then echo "Сначала выполни Фазу 1 (бэкап)"; exit 1; fi

# Конфиг в /etc/wireguard/
[ -f /etc/wireguard/awg0.conf ] && mv /etc/wireguard/awg0.conf "$BACKUP_DIR/awg0.conf.bak" && echo "Moved awg0.conf from /etc/wireguard/"
# Конфиг в /etc/amnezia/
[ -f /etc/amnezia/amneziawg/awg0.conf ] && mv /etc/amnezia/amneziawg/awg0.conf "$BACKUP_DIR/awg0-amnezia.conf.bak" && echo "Moved awg0.conf from /etc/amnezia/"
[ -d /etc/amnezia ] && mv /etc/amnezia "$BACKUP_DIR/amnezia_dir.bak" 2>/dev/null || true

echo "Done. Backup: $BACKUP_DIR"
ls -la /etc/wireguard/
```

**Шаг 2.4 — остановить старый WireGuard (wg0) на eu1:**

```bash
systemctl stop wg-quick@wg0 2>/dev/null || true
systemctl disable wg-quick@wg0 2>/dev/null || true
echo "wg0 stopped and disabled"
```

**Шаг 2.5 — убедиться, что MTProto и ss-redir не тронуты:**

```bash
docker ps
systemctl is-active shadowsocks-libev-redir@ss-wg.service 2>/dev/null || true
```

Должны быть: контейнер MTProto (если был) и сервис ss-redir в active. После этого можно отключиться от eu1 и переходить к Фазе 3 с ПК.

---

## Фаза 3. Установка AmneziaWG с нуля (с ПК, не команды)

Делается **вручную с твоего ПК (Windows)** в приложении AmneziaVPN:

1. Установи/обнови AmneziaVPN (не ниже 4.8.12.7): https://amnezia.org/en/downloads  
2. В приложении: **Добавить свой сервер** → адрес `185.21.8.91`, логин (root) и пароль или ключ SSH.  
3. После добавления сервера: открыть сервер → вкладка **Протоколы** → у **AmneziaWG** нажать **Установить**.  
4. Дождаться установки, затем создать подключение для себя и подключиться.  
5. Проверить на ПК: есть подключение и есть интернет (открыть сайт).  
6. Создать второе подключение (или экспорт/гостевой конфиг) для второго аккаунта iOS и проверить на телефоне.

Подробно: `docs/amneziawg-deploy-instruction.md`.

---

## Фаза 4. Только если после установки «подключение есть, интернета нет»

Выполнять **на eu1 по SSH**. Сначала узнай имя интерфейса AmneziaWG (часто `awg0`) и подсеть (в конфиге AmneziaWG на сервере, например 10.1.0.0/24).

**4.1 — IP forwarding:**

```bash
sysctl net.ipv4.ip_forward
```

Если выведет `0`, включить:

```bash
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p
```

**4.2 — FORWARD для AmneziaWG (подставь интерфейс, если не awg0):**

```bash
iptables -I FORWARD 1 -o awg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -I FORWARD 1 -i awg0 -o eth0 -j ACCEPT
```

**4.3 — INPUT (ответы после NAT):**

```bash
iptables -I INPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT
```

**4.4 — NAT MASQUERADE (подставь подсеть из конфига AmneziaWG, например 10.1.0.0/24; основной интерфейс может быть eth0 или ens3):**

```bash
# Узнать имя основного интерфейса:
ip route show default | awk '{print $5}'
# Затем (подставь INTERFACE и SUBNET):
iptables -t nat -A POSTROUTING -s 10.1.0.0/24 -o eth0 -j MASQUERADE
```

**4.5 — сохранить правила iptables (чтобы не слетели после перезагрузки):**

```bash
apt-get install -y iptables-persistent 2>/dev/null || true
iptables-save > /etc/iptables/rules.v4
ip6tables-save > /etc/iptables/rules.v6 2>/dev/null || true
```

Или вручную при каждой загрузке: добавить в systemd unit AmneziaWG или в `/etc/rc.local` вызов `iptables-restore < /etc/iptables/rules.v4`. Подробнее: `docs/deployment.md`, `docs/eu1-status-known-issues.md`.

---

## Фаза 5. Проверка (вручную)

1. **ПК:** подключиться к eu1 через AmneziaVPN (AmneziaWG) → открыть сайт → убедиться, что интернет есть.  
2. **Телефон (второй iOS):** импортировать конфиг в AmneziaVPN → подключиться → проверить интернет.  
3. Если оба работают — можно снова настроить бота для выдачи конфигов по `docs/amneziawg-bot-automation-setup.md`.

---

## Краткий порядок действий

| Где        | Что делать |
|-----------|------------|
| ПК        | Открыть PowerShell, выполнить `ssh root@185.21.8.91` (или с ключом). |
| eu1 (SSH) | Фаза 1 — весь блок бэкапов. |
| eu1 (SSH) | Фаза 2 — шаги 2.1–2.5. |
| ПК        | Фаза 3 — в приложении AmneziaVPN: добавить сервер, установить AmneziaWG, создать подключение, проверить. |
| eu1 (SSH) | Фаза 4 — только если после Фазы 3 нет интернета. |
| ПК + телефон | Фаза 5 — проверить подключение и интернет. |

Связанный документ: `docs/eu1-clean-slate-plan.md`.
