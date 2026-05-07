# План «чистого сброса» eu1 (Fornex) — только AmneziaWG

Документ описывает пошаговый план: очистить на eu1 только то, что относится к VPN (AmneziaWG и при необходимости старый WireGuard), оставить прокси для Telegram и при необходимости Shadowsocks, затем заново развернуть AmneziaWG и проверить на ПК и телефоне.

**Контекст:** На ПК VPN (AmneziaWG на eu1) работает; на телефоне и у друзей — подключение есть, интернета нет. Россия (main) проблем не даёт. Цель — выйти из круга «чиним — ломается» и получить стабильный eu1 только с AmneziaWG.

**Сервер:** eu1 (Fornex), IP `185.21.8.91`.

**Команды для копирования в терминал:** см. **`docs/eu1-clean-slate-commands.md`** — подключение к eu1, Фаза 1 (бэкапы), Фаза 2 (остановка и очистка), Фаза 4 (если нет интернета после установки).

---

## Протоколы на eu1 — что оставляем, что трогаем

| Компонент | Назначение | Действие |
|-----------|------------|----------|
| **MTProto (Docker, порт 443)** | Прокси для Telegram (ссылка `tg://proxy?...`) | **Не трогать** — оставить как есть |
| **Shadowsocks** | ss-redir на 127.0.0.1:1081 — редирект трафика для VPN+GPT/Unified (ChatGPT и т.п.), **не** для Telegram | **Не трогать** — оставить; не мешает AmneziaWG |
| **AmneziaWG (awg0)** | VPN с обфускацией для Европы, из РФ работает | **Сбросить и установить заново** по инструкции AmneziaVPN |
| **WireGuard (wg0) на eu1** | Старый WG на eu1 (из РФ по UDP не работал) | **По желанию** отключить/удалить конфиг, чтобы не путать с AmneziaWG; можно оставить выключенным |

Итого: **сбрасываем только AmneziaWG** (и при желании отключаем wg0). MTProto и Shadowsocks не удаляем.

---

## Фаза 1. Подготовка (бэкапы на eu1)

Выполнять по SSH на eu1 (185.21.8.91).

1. **Создать папку для бэкапа и сохранить текущее состояние:**

```bash
BACKUP_DIR="/root/eu1-backup-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"
```

2. **Сохранить конфиги AmneziaWG и WireGuard:**

```bash
# AmneziaWG — типичные пути
cp -r /etc/amnezia  "$BACKUP_DIR/" 2>/dev/null || true
cp -r /etc/wireguard "$BACKUP_DIR/"
ls -la /etc/wireguard/
# Если awg установлен — показать конфиг (без приватного ключа в лог)
awg show 2>/dev/null || true
```

3. **Сохранить iptables и список сервисов:**

```bash
iptables-save > "$BACKUP_DIR/iptables-save.txt"
ip6tables-save > "$BACKUP_DIR/ip6tables-save.txt" 2>/dev/null || true
systemctl list-units --type=service --state=running | grep -E 'wg|awg|wireguard' > "$BACKUP_DIR/wg-services.txt" 2>/dev/null || true
ss -tulnp > "$BACKUP_DIR/ss-tulnp.txt"
```

4. **Проверить, что MTProto (Docker) и ss-redir не затронуты:**  
   Не удалять и не останавливать Docker и контейнер MTProto, не трогать `shadowsocks-libev-redir@ss-wg.service`.

---

## Фаза 2. Остановка и очистка только AmneziaWG (и по желанию wg0)

Выполнять на eu1.

1. **Узнать имя интерфейса AmneziaWG и остановить:**

```bash
# Обычно awg0
ip link show | grep -E 'awg|wg'
# Остановить сервис AmneziaWG (имя может быть awg0 или wg-quick@awg0 — проверить на сервере)
systemctl stop wg-quick@awg0 2>/dev/null || true
# Или если сервис называется иначе:
systemctl list-units | grep -i awg
# Затем: systemctl stop <имя_сервиса>
```

2. **Удалить или переименовать конфиги AmneziaWG (чтобы не подхватились при загрузке):**

```bash
# Путь может быть /etc/wireguard/awg0.conf или /etc/amnezia/amneziawg/...
mv /etc/wireguard/awg0.conf /root/eu1-backup-*/awg0.conf.bak 2>/dev/null || true
# Если конфиг в /etc/amnezia/ — переместить туда же в бэкап
mv /etc/amnezia/amneziawg/awg0.conf "$BACKUP_DIR/" 2>/dev/null || true
```

3. **По желанию — отключить старый WireGuard (wg0) на eu1:**

```bash
systemctl stop wg-quick@wg0 2>/dev/null || true
systemctl disable wg-quick@wg0 2>/dev/null || true
# Конфиг не удалять, только отключить — при необходимости можно вернуть
```

4. **Правила iptables:**  
   Не удалять вручную все правила — при новой установке AmneziaWG через приложение AmneziaVPN обычно создаются свои. Если после установки интернет через VPN не заработает — см. фазу 4.

---

## Фаза 3. Установка AmneziaWG с нуля (как в первый раз)

Делать **с ПК (Windows)** по инструкции проекта:

- **`docs/amneziawg-deploy-instruction.md`** — пошагово: установка AmneziaVPN на ПК → добавление сервера eu1 по SSH → установка протокола AmneziaWG через приложение → создание подключения.

Кратко:

1. Установить/обновить AmneziaVPN на ПК (не ниже 4.8.12.7 для AmneziaWG 2.0).
2. В приложении: «Добавить свой сервер» → адрес `185.21.8.91`, логин и пароль/ключ SSH.
3. Для сервера eu1: установить протокол **AmneziaWG** (кнопка «Установить» в приложении).
4. Создать подключение для себя, подключиться с ПК и проверить, что есть и подключение, и интернет.
5. Создать второе подключение (или экспорт конфига) для второго аккаунта iOS — для проверки на телефоне.

Не поднимать на eu1 вручную старый WireGuard (wg0), скрипты бота и т.п. — только то, что создаёт приложение AmneziaVPN.

---

## Фаза 4. Если после установки «подключение есть, интернета нет»

Такое уже наблюдалось на eu1 (см. `docs/eu1-status-known-issues.md`). После чистой установки AmneziaWG приложение может настроить форвардинг сам; если нет — на eu1 проверить:

1. **IP forwarding:**

```bash
sysctl net.ipv4.ip_forward
# Должно быть 1. Если 0:
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf && sysctl -p
```

2. **FORWARD для интерфейса AmneziaWG (например awg0):**  
   Трафик из awg0 в eth0 и обратно должен разрешаться. Если на сервере есть Docker, его правила не должны блокировать awg0:

```bash
iptables -I FORWARD 1 -o awg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -I FORWARD 1 -i awg0 -o eth0 -j ACCEPT
```

3. **INPUT (ответы после NAT):**

```bash
iptables -I INPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT
```

4. **NAT (MASQUERADE):**  
   Должно быть правило для выхода в интернет из подсети AmneziaWG (например 10.x.x.0/24). Если приложение Amnezia не добавило — добавить вручную, например:

```bash
iptables -t nat -A POSTROUTING -s 10.1.0.0/24 -o eth0 -j MASQUERADE
```

(Подсеть уточнить по конфигу AmneziaWG на сервере.)

Сохранить правила (например `iptables-save > /etc/iptables.rules` и восстановление при загрузке — см. `docs/deployment.md` и `docs/eu1-status-known-issues.md`).

---

## Фаза 5. Проверка на ПК и телефоне

1. **ПК:** подключиться к eu1 через AmneziaVPN (AmneziaWG), открыть сайт — убедиться, что интернет есть.
2. **Телефон (второй аккаунт iOS):** импортировать конфиг (или гостевой доступ) в AmneziaVPN на iPhone → подключиться → проверить интернет.
3. Если оба работают — зафиксировать в проекте: «eu1 после чистого сброса, только AmneziaWG, проверено на ПК и iOS».

После стабильной работы можно снова настроить бота для выдачи AmneziaWG конфигов (скрипты на eu1, переменные на Timeweb) по `docs/amneziawg-bot-automation-setup.md`.

---

## Краткая памятка по протоколам (для себя)

- **Telegram proxy** = MTProto (Docker, порт 443). Оставляем.
- **Shadowsocks (ss-redir)** = редирект части трафика для VPN+GPT/ChatGPT, не для Telegram. Оставляем, не мешает AmneziaWG.
- **AmneziaWG** = VPN для Европы с обфускацией. Сбрасываем и ставим заново по инструкции.

---

## Связанные документы

- `docs/amneziawg-deploy-instruction.md` — развёртывание AmneziaWG на eu1.
- `docs/amneziawg-eu1-discovery.md` — проверка наличия AmneziaWG на eu1.
- `docs/eu1-status-known-issues.md` — известные ограничения eu1 (туннель есть, интернета нет).
- `docs/deployment.md` — общие правила FORWARD, INPUT, NAT для eu1.
- `docs/mtproto-setup.md` — установка MTProto (для справки, не трогаем при сбросе).
