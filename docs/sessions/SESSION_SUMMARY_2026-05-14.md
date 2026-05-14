# SESSION SUMMARY — 2026-05-14

**Дата:** 2026-05-14
**Статус:** завершена

---

## Что сделано

### 1. IPv6 leak — AllowedIPs
- Добавлен `::/0` в `AllowedIPs` для ПК и iOS конфигов
- `/opt/amnezia-add-client.sh` на Fornex обновлён
- `bot/wireguard_peers.py` и оба примера в `docs/scripts/` обновлены
- Android не затронут — `_make_amneziawg_config_android_safe()` уже срезает `::/0`

### 2. Аудит безопасности веб-панели
- `/api/users`: заменена авторизация с `telegram_id` → `ADMIN_SECRET` (env var)
- Legacy recovery endpoints (`/api/recovery/vpn`, `/api/recovery/telegram-proxy`, `/api/recovery/proxy-link`, `/api/recovery/mobile-vpn`): добавлена проверка `RECOVERY_SECRET`
- `/api/traffic`: убран `telegram_id` из публичного ответа
- `bot/config.py`: добавлены поля `admin_secret`, `recovery_secret` в `BotConfig`
- Секреты добавлены в `env_vars.txt` на сервере и локально
- Email/OTP флоу (`/api/recovery/vpn-by-email`) был уже защищён — не трогали

### 3. Инструкция /mobile_vpn
- Убраны Happ и Streisand (удалены из App Store)
- Протокол-агностичный подход: «любой VLESS-совместимый клиент»
- Актуальные приложения: Hiddify, FoXray, V2Box (iOS); Hiddify, v2rayNG (Android)
- Добавлено пояснение что `vless://` — универсальный формат

### 4. ROADMAP обновлён
- Добавлены задачи: собственное приложение, переписать инструкции, выгрузка пользователей в Google Sheets
- Закрыты: IPv6, аудит безопасности, кнопки платформы в /instruction (уже были)
- Rate limit на /regen — отложен до роста аудитории
- Домен — отложен (нейминг = решение о бренде)

---

## Открытые задачи (приоритет)

- Домен + nginx + SSL — ждёт решения по названию проекта
- Обновить тексты остальных инструкций в боте (/instruction по платформам)
- Unit-экономика, юридика — скоро нужно
- Yota/MegaFon whitelist — при следующем тесте

---

## Технические заметки

- `ADMIN_SECRET` и `RECOVERY_SECRET` — в `/opt/vpnservice/env_vars.txt` на Fornex
- Деплой: `scp -i "C:\Users\krono\.ssh\id_ed25519_fornex" <file> root@185.21.8.91:<path>`
- Файлы инструкций читаются динамически — перезапуск бота не нужен после их правки
