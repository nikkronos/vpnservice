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

- Бэкапы `/opt/vpnservice/web/templates/recovery.html.bak.<ts>` и `/opt/vpnservice/web/static/recovery.js.bak.<ts>`.
