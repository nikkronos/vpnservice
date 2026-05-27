# SESSION SUMMARY — 2026-05-27

## TL;DR

- ✅ **Phase 3g — Telegram Stars (одноразовая оплата)** — DONE утром (commit `d0155e8`).
- ✅ **Phase 3g+ — ручная СБП/карта Т-Банк + `/admin/credit`** — DONE утром (commit `8ee3541`).
- 🆕 **ROADMAP**: зафиксированы 4 варианта автозачисления (A=Cryptomus / B=Stars-subscription / C=копейки-парсер / D=самозанятость+Lava) — владелец думает (commit `eaf6d03`).
- ✅ **Mini App: реструктуризация ЛК под вложенные разделы** (вечер) — длинный скролл превращён в главное меню + 4 подстраницы. Substeps: «Продлить подписку», «Резервные конфиги» (3 канала), «Пригласить друзей», «Пароль и настройки».
- ✅ **Inline-кнопка «Продлить»** в статус-карточке: показывается, когда `days_left ≤ 3` (включая истёкшие). Не показывается grandfather'ам.
- ✅ Деплой на Fornex, smoke-тест прошёл (`vpn-web.service` active, 200 на `/recovery`, новая разметка отдаётся).

---

## Что сделано (Mini App restructure)

### Контекст
Owner: «не нравится, что в Mini App всё на одной странице, логично рассортировать под кнопки». Текущая структура — длинный скролл на одном `stepMenu`: status → subscription (CTA) → pay → trial → password → referral → 3 кнопки альт.способов. На мобиле «Альт.способы» уезжали за второй экран и почти не находились.

### Решение
Главное меню = «лицо» ЛК (status + Подписка + 4 nav-кнопки). Всё остальное переехало в свои substeps.

**Новая иерархия:**
```
stepMenu (главная)
├── status-card (с inline «Продлить» при days_left ≤ 3)
├── subBlock (Подписка — главный CTA, QR + ссылка)
├── trialBlock (только если триал доступен)
└── 4 nav-кнопки:
    ├── 💳 Продлить подписку → stepBilling
    ├── 🔌 Резервные конфиги → stepConnect
    │   ├── 📲 Основной VPN → stepPlatform
    │   ├── 📡 VPN при блокировках → stepOperator
    │   └── 📨 Разблокировка Telegram → stepProxy
    ├── 👥 Пригласить друзей → stepReferral
    └── ⚙️ Пароль и настройки → stepSettings
```

### Навигация
- Введена `stepParent` Map с маршрутами «назад» по иерархии. Кнопки «« Назад» и TG `BackButton` оба используют `stepParent.get(currentStep)`.
- `showStep()` теперь трекает `currentStep`, скроллит наверх и управляет видимостью `BackButton`.
- `data-substep` на nav-кнопках → один обработчик мапит ключ → нужный substep.
- `data-channel` (3 канала) остался прежним, но живёт уже в `stepConnect`.

### Файлы
- `web/templates/recovery.html` — реструктуризация секций, 4 новые substep-секции, существующие `stepPlatform/Operator/Proxy` без изменений (только `data-back` стал маркером, не строкой).
- `web/static/recovery.js` — добавлены `stepBilling/stepConnect/stepReferral/stepSettings` рефы, `stepParent` map, `currentStep`, обработчики `data-substep`, inline-CTA в `renderAccount`.
- CSS не трогал — переиспользованы `.btn-menu`, `.account-card`, `.btn-back`, `.recovery-menu`.

### API не трогали
Никаких изменений в `web/app.py`, БД, эндпоинтах. Бэкенд возвращает те же данные, фронт перестраивает раскладку.

### Деплой
- SCP `recovery.html` + `recovery.js` → `/opt/vpnservice/web/{templates,static}/`
- Бэкап старых файлов на сервере: `recovery.html.bak.<ts>`, `recovery.js.bak.<ts>` (rollback в одну команду).
- `systemctl restart vpn-web.service` → active, в логах только запуск Flask, никаких 500/traceback.
- `curl https://supportkronos.online:8443/recovery` → 200.

---

## Что закрывает в ROADMAP

- ✅ **«Альтернативные способы» не видны на телефоне** (фидбэк 2026-05-26): больше не теряются в длинном скролле — у них теперь свой раздел «Резервные конфиги» с явной точкой входа.

## Что НЕ закрыто (осталось висеть)

1. **Автозачисление платежей** — 4 варианта на столе, ждёт решения владельца. Stars-subscription (B) — 30-минутная аддитивная задача, можно сделать без решения остальных.
2. **Phase 3i (лендинг/оферта/контакты)** — блокер ЮKassa, нужны данные владельца.
3. **Phase 3b proper** — swap токена на `@vpnkronos_bot` в env_vars.txt + restart.
4. **End-to-end реферал-тест** на двух TG-аккаунтах.
5. **Missing `instruction_vless_*_short.txt`** файлы.
6. **Регрессия `MenuButtonWebApp`** — проверить версию pyTelegramBotAPI на сервере.
7. **Per-user UUID для main REALITY**.
8. **Мегафон при БС** — разведка ждёт окна.

## Дальнейшее (рекомендация)

После визуальной валидации владельцем — взять **Stars Subscription (вариант B)** как самое дешёвое движение по теме автозачисления. Параллельно — UX-проверка нового флоу на нескольких устройствах (особенно прокликать в TG Mini App: BackButton, переходы между substeps, inline-«Продлить» при истечении срока).

---

## Коммиты сегодня

- `d0155e8` — phase 3g: Telegram Stars payments (native, no merchant setup)
- `8ee3541` — phase 3g+: manual SBP/card payments UI + /admin/credit form
- `eaf6d03` — roadmap: автоматизация платежей (4 варианта) + фиксация Phase 3g/3g+
- *(этот session, Mini App restructure)* — будет в следующем коммите

## Серверно (вне git)

- Бэкапы `/opt/vpnservice/web/templates/recovery.html.bak.<ts>` и `/opt/vpnservice/web/static/recovery.js.bak.<ts>` (от Mini App restructure).
- Бэкап `/opt/vpnservice/web/app.py.bak.<ts>` (от auto-login дебага).

---

## Дополнение (вечер 2026-05-27) — фикс auto-login в Mini App

### Симптом
После реструктуризации ЛК владелец открыл Mini App с iPhone (`@thisvpnforfriends_bot` → Menu Button «🌐 Личный кабинет») и попадал на экран email-логина вместо дашборда. Auto-login через `initData` не срабатывал.

### Диагностика (через временный debug-bar в UI + серверное логирование `_validate_init_data`)
1. **Первый снимок**: dbgBar показал `DBG: loading…` — JS вообще не выполнялся.
2. **Гипотеза**: блокирующий `<script src="https://telegram.org/js/telegram-web-app.js">` подвисал на загрузке → следующий за ним `recovery.js` ждал и не запускался.
3. **Фикс №1**: `async` на SDK-теге + JS-поллинг `window.Telegram.WebApp` до 3 секунд.
4. **Второй снимок**: dbgBar показал `tg=no ver=? initLen=0 inTG=false no tg after 3s (browser mode)` — SDK вообще не подгрузился даже за 3 секунды. То есть `telegram.org/js/telegram-web-app.js` **не доходит до iPhone** в этом WebView.
5. **Корень**: `telegram.org` из РФ-сети владельца (mobile) режется DPI/тротлится — даже когда сам TG-клиент работает (он использует свои app-сервера, не telegram.org/js). Эпизодически кэш TG спасал — отсюда «утром работало, вечером нет».
6. **Фикс №2 (durable)**: скачали SDK один раз на сервер (`/opt/vpnservice/web/static/telegram-web-app.js`, 116 KB) и переключили `<script src>` на локальный путь. Теперь SDK гарантированно доходит — он раздаётся с того же хоста и порта, что и сам ЛК (`supportkronos.online:8443`).
7. **Третий снимок**: `tg=yes ver=9.6 pl=ios initLen=580 inTG=true auth=200 token=ok` — дашборд открылся сразу.

### Что закрепилось
- В памяти (`project_vpn_decisions.md`): «**Telegram-web-app.js хостим у себя**» — любые внешние JS/asset, нужные внутри Mini App, дублируем на нашем хосте. Не полагаться на telegram.org / cdn.jsdelivr / unpkg из РФ.
- Polling `window.Telegram.WebApp` оставлен как defensive-фолбэк (если в будущем SDK по какой-то причине загрузится с задержкой).
- Debug-bar и серверное расширенное логирование вырезаны после фикса.

### Файлы, которые поехали этим фиксом
- `web/static/telegram-web-app.js` — **новый** (116 KB, скачан с telegram.org один раз).
- `web/templates/recovery.html` — script src переключён на локальный путь.
- `web/static/recovery.js` — рефакторинг auto-login: `setupTelegramFeatures()` + `runAutoLogin()` + поллинг.
- `web/app.py` — без изменений в финальном виде (debug-логирование вырезано).
