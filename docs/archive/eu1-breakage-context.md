# Где произошла поломка: «удалили awg» и «доступ для Android»

Кратко: что менялось на этапе «оставили wg, убрали awg» и при добавлении поддержки Android, и почему после этого мог перестать работать интернет через VPN на eu1.

**Что работало:** конфиг Amnezia **831 байт** (другое имя, другая структура) — подключался к **awg0** (AmneziaWG на eu1), обфускация, обход РКН. **Что не работает:** конфиги с «eu» в названии (**257 байт**), которые выдаёт бот сейчас — подключаются к **wg0** (обычный WireGuard на eu1), без обфускации, РКН блокирует. Переход на wg0 вместо awg0 изменил и имя файла, и структуру/назначение конфига: трафик снова идёт как обычный WireGuard и попадает под ограничения РКН. **Решение:** вернуть на eu1 AmneziaWG (awg, awg0), на Timeweb — `AMNEZIAWG_EU1_INTERFACE=awg0`, чтобы бот снова выдавал конфиги к awg0 (обфускация, обход РКН). См. [return-to-awg0.md](return-to-awg0.md); на eu1 сейчас awg не установлен — нужно сначала установить AmneziaWG на eu1.

---

## 1. Коммит в репозитории

**Коммит:** `0989741` — *fix(web): traffic from eu1 via awg show; feat(bot): Android instructions and /instruction steps*

**Изменённые файлы:**
- `web/app.py` — для eu1 добавлена логика «awg или wg» по переменной `AMNEZIAWG_EU1_INTERFACE`; fallback на `wg show`, если `awg show` не сработал.
- `bot/main.py` — добавлены шаги инструкции и учёт Android (инструкции, тексты после выдачи конфига).
- `docs/client-instructions-android.md` — новая инструкция для Android.
- `docs/bot-instruction-texts/instruction_android_short.txt` — короткий текст для бота по Android.
- Плюс правки в README_FOR_NEXT_AGENT, ROADMAP, web/README, competitors-analysis.

В репозитории **никто не удалял строку с awg** — там только добавили поддержку выбора интерфейса (awg0/wg0) через env и Android.

---

## 2. Где «удалили awg» (оставили wg)

Удаление было **на сервере бота (Timeweb)** — в файле с переменными окружения, например:

- `/opt/vpnservice/env_vars.txt`

Там было **две** строки:

- `AMNEZIAWG_EU1_INTERFACE=wg0`
- `AMNEZIAWG_EU1_INTERFACE=awg0`

По инструкции из `docs/amneziawg-bot-automation-setup.md` («Одна строка AMNEZIAWG_EU1_INTERFACE на Timeweb») оставили **одну** — ту, что совпадает с интерфейсом на eu1. Оставили **wg0**, строку с **awg0** удалили.

Итого: **удалённая строка** — в env на Timeweb: `AMNEZIAWG_EU1_INTERFACE=awg0`.

---

## 3. Как это связано с ботом и eu1

В коде бота (`bot/wireguard_peers.py`):

- При добавлении пира для eu1 вызывается скрипт на eu1 с переменной `AWG_INTERFACE`, значение берётся из `AMNEZIAWG_EU1_INTERFACE` (если пусто — по умолчанию `awg0`).
- Строка: `interface = env.get("AMNEZIAWG_EU1_INTERFACE", "").strip() or "awg0"` и затем `AWG_INTERFACE={interface}` в команде для eu1.

После удаления строки с awg0 в env осталась только `AMNEZIAWG_EU1_INTERFACE=wg0`. Поэтому бот стал передавать на eu1 **AWG_INTERFACE=wg0** и скрипт на eu1 стал добавлять пиров в **wg0** (через `wg set wg0 peer ...` или `awg set wg0 ...` в зависимости от наличия `awg` на eu1).

Раньше (при двух строках в env) обычно использовалось последнее значение — **awg0**. Тогда пиры добавлялись в **awg0**, клиенты подключались к AmneziaWG (awg0), интернет шёл через настройки awg0.

После перехода на одну строку **wg0**:
- новые пиры стали добавляться в **wg0**;
- клиенты (в т.ч. AmneziaWG на телефоне) получают конфиг для того же сервера и порта, но фактически подключаются к **wg0**;
- если на eu1 интернет был настроен и работал только для **awg0** (NAT/forward для awg0), а для **wg0** не был настроен или настроен иначе — интернет через VPN перестаёт работать (handshake есть, трафика в интернет нет).

То есть поломка, скорее всего, не из-за «удаления строки в коде», а из-за **переключения с awg0 на wg0** в env на Timeweb: бот и скрипт переключились на wg0, а на eu1 интернет мог быть поднят только для awg0.

---

## 4. Что можно сделать (без изменения сервера из этого репо)

- **Вариант A (рекомендуется при блокировке РКН).** Вернуть **awg0** (AmneziaWG): WireGuard блокируется Роскомнадзором, AmneziaWG обходит блокировку. Пошагово — [return-to-awg0.md](return-to-awg0.md): на Timeweb одна строка `AMNEZIAWG_EU1_INTERFACE=awg0`, перезапуск бота, при необходимости заново выдать конфиги и подключаться к awg0. На eu1 должен быть установлен AmneziaWG (интерфейс awg0).
- **Вариант B.** Оставить `AMNEZIAWG_EU1_INTERFACE=wg0` и починить интернет именно для **wg0** на eu1: NAT (POSTROUTING, MASQUERADE для 10.1.0.0/24), FORWARD, при необходимости INPUT и rp_filter — по шагам из [eu1-vpn-internet-recovery.md](eu1-vpn-internet-recovery.md). Учти: из РФ wg0 может быть заблокирован РКН.

Документ «Одна строка AMNEZIAWG_EU1_INTERFACE» и диагностика — в [amneziawg-bot-automation-setup.md](amneziawg-bot-automation-setup.md).
