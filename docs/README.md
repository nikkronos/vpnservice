# docs/ — навигация и правила документации VPN

> Индекс и правила. Цель — чтобы агенты не путались, где что лежит, и не плодили
> дубли. Создан 2026-06-13 в рамках «порядок в документах».

## Где что живёт (source of truth — соблюдать!)

| Файл / папка | Только это | Чего там быть НЕ должно |
|---|---|---|
| `CLAUDE.md` (корень проекта) | как система устроена и как работать **сейчас** | история, списки задач |
| `ROADMAP_VPN.md` | только **открытое/будущее** по приоритетам | «сделано», нарративы |
| `DONE_LIST_VPN.md` | **хронология** выполненного (newest-first) | открытые задачи |
| `docs/` | глубокий **референс** (setup/troubleshooting/планы/бизнес) | дубли оперативки из CLAUDE |
| `docs/sessions/` | журнал сессий (append-only) | — |
| `docs/archive/` | **устаревшее** (для истории), «не читать для работы» | актуальное |

**Правило против дублей:** факт живёт в ОДНОМ месте по таблице выше; в других —
только ссылка. Перед созданием нового дока проверь, нет ли уже файла по теме
(этот индекс) — дополни существующий, а не плоди новый.

**Правило свежести (карантин перед архивом):** не архивировать документ, если он
правился в последние **7 дней** (по `git log -1 --format=%cs`, НЕ по mtime —
OneDrive сдвигает mtime). В архив — только после ≥7 дней без правок.

## Индекс docs/ (актуальное)

### Деплой и эксплуатация
- `deployment.md` — деплой кода на серверы, чеклист.
- `eu1-setup-and-troubleshooting.md` — **канон** по eu1 (AmneziaWG в Docker): setup + troubleshooting.
- `backup-restore.md` — бэкап и восстановление.
- `mtproxy-faketls-deploy.md` — деплой MTProxy Fake TLS.
- `mtproxy-proxy-rotation.md` — ротация MTProxy.
- `eu1-vless-reality-setup.md` — eu1 VLESS+REALITY (узел «Германия»). ⚠ требует фикса точности (рекомендация Happ).
- `yandex-cloud-reality-setup.md` — yc VLESS+REALITY (узел «Европа»).

### Клиентские инструкции
- `client-instructions-amneziawg.md` — инструкция AmneziaWG для пользователя.
- _живые тексты, которые шлёт бот, — в `bot-instruction-texts/` (не дублировать)._

### Troubleshooting
- `troubleshooting-ios-devices.md`, `troubleshooting-multiple-devices.md`,
  `troubleshooting-telegram-vpn-conflict.md`, `troubleshooting-amneziawg-connection-timeout.md`.

### Стратегия обхода / Telegram
- `blocking-bypass-strategy.md` — стратегия обхода блокировок.
- `telegram-mtproxy-operators-guide.md` — **канон** по MTProxy и операторам.
- `telegram-proxy-alternatives.md` — сторонние альтернативы (park-lot, **не наш стек**).

### Планы (активные)
- `plan-phase-3-4-5.md` — **master-план** коммерциализации (читать первым при потере контекста).
- `plan-phase2-keystone-architecture.md` — арх-док антифрод/iplimit (Часть A активна).
- `plan-blocking-antifraud-traffic-tariffs.md` — блокировки/антифрод/тарифы.
- `plan-phase2B-per-device-impl.md` — ⏳ импл-спека Фазы 2B (**выполнено**; карантин свежести → в архив после 2026-06-17).

### Бизнес и правовое
- `monetization-and-payments.md` — **монетизация и платежи** (donation-flow, фазы коммерциализации, выбор провайдера авто-оплаты). Вынесено из ROADMAP 06-13.
- `competitors-analysis.md` — анализ конкурентов.
- `mvp-unit-economics-and-plan.md` — юнит-экономика.
- `provider-choice-evaluation.md` — выбор VPS-провайдера. ⚠ устар. тариф (NVMe1 → NVMe2).
- `rkn-notification-guide.md` — гайд по уведомлению РКН.
- `yookassa-setup-instruction.md` — настройка ЮKassa.

### Безопасность и риски
- `security.md` — принципы безопасности проекта.
- `risks-and-mitigations.md` — реестр рисков. ⚠ часть статусов устарела.

## Подпапки
- `specs/` — design-спеки (provenance): spec-05 (бот+AmneziaWG eu1), spec-07 (mobile VLESS+REALITY), spec-08 (multi-node; ru2/eu2 частично устарели).
- `sessions/` — резюме сессий; `sessions/old/` — Feb–Mar, история.
- `archive/` — устаревшее/выполненное, для истории. Не использовать для текущей работы.
- `scripts/` — примеры серверных скриптов и конфигов (`.example`, nginx, xray).
- `bot-instruction-texts/` — **живые** тексты инструкций, которые отдаёт бот.
