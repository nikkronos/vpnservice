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
| Имя интерфейса AmneziaWG | например `awg0` |
| Путь к серверному конфигу | например `/etc/wireguard/awg0.conf` или `/etc/amnezia/amneziawg/awg0.conf` |
| Порт (ListenPort из конфига) | например `51820` или другой |
| Публичный ключ сервера | вывод `awg show awg0 public-key` или из конфига |

Если в конфиге есть параметры обфускации (JunkPacketCount, Jmin, Jmax, H1–H4, S1–S2 и т.п.) — скопировать их блок из секции `[Interface]` (без PrivateKey). Они понадобятся для сборки клиентского `.conf`.

---

## 3. Переменные окружения для бота (после проверки)

После проверки на eu1 в `env_vars.txt` на сервере бота (Timeweb) можно добавить (см. также `spec-05-bot-amneziawg-eu1.md`):

```bash
# AmneziaWG для eu1 (выдача конфигов ботом)
# Заполнить после проверки на eu1 (docs/amneziawg-eu1-discovery.md)
AMNEZIAWG_EU1_INTERFACE=awg0
AMNEZIAWG_EU1_CONFIG_PATH=/etc/wireguard/awg0.conf
# Или, если конфиг в другом месте:
# AMNEZIAWG_EU1_CONFIG_PATH=/etc/amnezia/amneziawg/awg0.conf
```

Если бот будет только отдавать инструкцию и конфиги вручную — эти переменные не обязательны.

---

## 4. Связанные документы

- `docs/specs/spec-05-bot-amneziawg-eu1.md` — спецификация выдачи AmneziaWG конфигов ботом.
- `docs/amneziawg-deploy-instruction.md` — как развёрнут AmneziaWG на eu1.
- `docs/client-instructions-amneziawg.md` — инструкция для пользователей.
