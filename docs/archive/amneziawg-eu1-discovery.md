# Проверка AmneziaWG на eu1 для выдачи конфигов ботом

Перед тем как бот сможет выдавать AmneziaWG конфиги для сервера «Европа» (eu1), на сервере eu1 нужно проверить, где установлен AmneziaWG и как к нему обращаться.

**Сервер eu1:** 185.21.8.91 (Fornex). Выполнять команды по SSH от пользователя с доступом к eu1.

---

## 1. Команды для проверки (выполнить на eu1)

```bash
# Есть ли утилита awg (AmneziaWG)?
which awg
awg --version 2>/dev/null || true

# Какие интерфейсы WireGuard/AmneziaWG есть?
ip link show | grep -E 'awg|wg'

# Стандартный путь конфигов WireGuard
ls -la /etc/wireguard/

# Путь, куда Amnezia app часто ставит конфиги
ls -la /etc/amnezia/ 2>/dev/null || true
ls -la /etc/amnezia/amneziawg/ 2>/dev/null || true

# Если интерфейс awg0 есть — показать ключ и порт
awg show awg0 2>/dev/null || true

# Найти конфиг с AmneziaWG (поиск по содержимому)
grep -r "ListenPort\|PrivateKey" /etc/wireguard/ 2>/dev/null | head -20
grep -r "ListenPort\|PrivateKey" /etc/amnezia/ 2>/dev/null | head -20
```

---

## 2. Что зафиксировать

После выполнения записать:

| Параметр | Значение (пример) |
|----------|-------------------|
| Путь к утилите `awg` | например `/usr/bin/awg` |
| Имя интерфейса AmneziaWG | например `awg0` или `wg0` (зависит от установки на eu1) |
| Путь к серверному конфигу | например `/etc/wireguard/awg0.conf` или `/etc/amnezia/amneziawg/awg0.conf` |
| Порт (ListenPort из конфига) | например `51820` или другой |
| Публичный ключ сервера | вывод `awg show awg0 public-key` или из конфига |

Если в конфиге есть параметры обфускации (JunkPacketCount, Jmin, Jmax, H1–H4, S1–S2 и т.п.) — скопировать их блок из секции `[Interface]` (без PrivateKey). Они понадобятся для сборки клиентского `.conf`.

---

## 3. Переменные окружения для бота (после проверки)

После проверки на eu1 в `env_vars.txt` на сервере бота (Timeweb) задать переменные (см. также `docs/amneziawg-bot-automation-setup.md`):

- **SSH к eu1:** WG_EU1_SSH_HOST, WG_EU1_SSH_USER, WG_EU1_SSH_KEY_PATH (рекомендуемое имя ключа на Timeweb: **id_ed25519_eu1**).
- **AmneziaWG:** AMNEZIAWG_EU1_INTERFACE — имя интерфейса с eu1 (`awg0` или `wg0`); AMNEZIAWG_EU1_ADD_CLIENT_SCRIPT, AMNEZIAWG_EU1_NETWORK_CIDR, AMNEZIAWG_EU1_REMOVE_CLIENT_SCRIPT.

Полный пример env и пошаговая настройка автоматической выдачи конфигов — в `docs/amneziawg-bot-automation-setup.md`.

---

## 4. Связанные документы

- `docs/specs/spec-05-bot-amneziawg-eu1.md` — спецификация выдачи AmneziaWG конфигов ботом.
- `docs/amneziawg-deploy-instruction.md` — как развёрнут AmneziaWG на eu1.
- `docs/client-instructions-amneziawg.md` — инструкция для пользователей.
