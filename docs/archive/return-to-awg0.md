# Вернуть awg0 (AmneziaWG) — обход блокировки РКН

WireGuard (wg0) блокируется Роскомнадзором. AmneziaWG (awg0) использует обфускацию и обходит блокировку. Если переключились на wg0 и интернет перестал работать (или из РФ не подключается) — верни использование **awg0**.

---

## Что нужно

- На **eu1** должен быть установлен AmneziaWG: утилита `awg`, интерфейс **awg0** поднят и настроен (NAT/forward для 10.1.0.0/24).  
  **Если на eu1 команда `which awg` выдаёт «not found»** — AmneziaWG на этом сервере не установлен, интерфейса awg0 нет. Сначала нужно установить серверную часть AmneziaWG на eu1 (официальная документация Amnezia / репозиторий AmneziaWG для Linux).
- На **Timeweb** (сервер бота) в env одна строка `AMNEZIAWG_EU1_INTERFACE=awg0`.

---

## Шаги

### 1. Проверка на eu1

Подключись по SSH к **eu1** и убедись, что AmneziaWG работает:

```bash
which awg
ip link show awg0
awg show awg0
```

Если `awg` или интерфейс `awg0` нет — на eu1 установлен только обычный WireGuard (`wg`, wg0). Чтобы использовать awg0, нужно сначала установить AmneziaWG на eu1 (серверная часть; см. официальную документацию Amnezia / AmneziaWG для Linux).

### 2. На Timeweb: одна строка awg0

На **сервере бота (Timeweb)** открой файл с переменными окружения (например `/opt/vpnservice/env_vars.txt`):

```bash
grep AMNEZIAWG_EU1_INTERFACE /opt/vpnservice/env_vars.txt
```

Должна быть **только одна** строка, и значение — **awg0**:

```bash
AMNEZIAWG_EU1_INTERFACE=awg0
```

Если там стоит `wg0` или две строки (wg0 и awg0) — отредактируй файл: оставь одну строку `AMNEZIAWG_EU1_INTERFACE=awg0`. Остальные строки с `AMNEZIAWG_EU1_INTERFACE` удали или закомментируй.

### 3. Перезапуск бота

На **Timeweb**:

```bash
sudo systemctl restart vpn-bot.service
sudo systemctl status vpn-bot.service
```

Если веб-панель читает тот же env и показывает трафик по eu1 — при необходимости перезапусти и её (чтобы панель запрашивала `awg show awg0`).

### 4. Конфиги для клиентов

Новые конфиги (get_config / regen) будут добавлять пиров в **awg0** на eu1. Старые конфиги, выданные при wg0, подключались к wg0 — их лучше заменить:

- В боте: /server → Европа, затем /get_config или /regen.
- Импортировать новый конфиг в AmneziaVPN/AmneziaWG на телефоне или ПК и подключаться уже к awg0.

---

## Итог

После смены на `AMNEZIAWG_EU1_INTERFACE=awg0` и перезапуска бота:

- бот и скрипт на eu1 используют интерфейс **awg0**;
- трафик на панели для eu1 запрашивается через `awg show awg0`;
- клиенты подключаются к AmneziaWG (awg0) и обходят блокировку РКН.

Если после возврата awg0 интернет по-прежнему не работает — проверь на eu1 NAT/forward для awg0 (аналогично [eu1-vpn-internet-recovery.md](eu1-vpn-internet-recovery.md), но для интерфейса awg0 вместо wg0).
