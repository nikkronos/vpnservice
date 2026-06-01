# SESSION SUMMARY — 2026-06-01

> Один из самых плотных дней. 20+ коммитов, 3 крупных задачи закрыты,
> 2 архитектурные проблемы расследованы и решены, ~5 раундов
> юр.экспертизы лендинга и оферты.

---

## TL;DR

- ✅ **Phase 3i закрыт** — лендинг + оферта + контакты + Политика ПД (после 3 раундов юр.экспертизы LLM). Готово к ЮKassa-модерации, остался только Уведомление РКН на стороне владельца.
- ✅ **Enforcement gap для AWG закрыт** — soft-revoke peer при истечении подписки + auto-restore при оплате с теми же pubkey/ip (старый .conf продолжает работать). E2E тест на синтетическом юзере прошёл.
- ✅ **Реферал-программа DONE** — UI возвращён, TG share-кнопка, уведомление пригласителю при регистрации друга, deeplinks `?startapp=ref_X` (после настройки Direct Link Mini App в BotFather). E2E на 2 TG-аккаунтах владельца прошёл.
- ✅ **Health-check fix** — batch SSH вместо 6 отдельных (было ложное FAIL от rate-limit провайдера main).
- ✅ **yc memory pressure resolved** — добавлен 1 GB swap, Xray ел 619 MB → 330 MB после рестарта (закрыло 14-мин freeze'ы).
- ✅ **CRITICAL fix /start handler** — был баг при редактировании рядом с декоратором, бот не отвечал на /start. После этого зафиксирован Pre-deploy checklist в CLAUDE.md.
- ✅ **traffic_snapshots + diagnosis** — теперь можно ответить «кто качал в N мск».
- ⏸ **УТП в одно предложение** — обсудили, варианты на руках, владелец отложил по psychological load.
- ⏸ **Split tunneling** — spec-04 устарела (была написана под классический WG, у нас Docker AmneziaWG), отдельная архитектурная задача 1-6 ч в зависимости от подхода.

---

## Хронология коммитов (16 шт за день)

| # | Commit | Что |
|---|---|---|
| 1 | `f54b3bc` | health-check fix: batch SSH вместо 6 отдельных |
| 2 | `7d2a447` | traffic_snapshots + diagnosis tool |
| 3 | `7672eed` | Phase 3i: лендинг + оферта + контакты + перенос админки на /admin |
| 4 | `0e6e15f` | email убран с лендинга |
| 5 | `ac0daf2` | УТП отложено, принципы зафиксированы |
| 6 | `bd6f3a7` | split-tunneling spec-04 устарела (отложено) |
| 7 | `d0b56ac` | реферал-UI возвращён + TG share + уведомления |
| 8 | `9f21cc2` | реф-ссылка `?start=` (fix BOT_INVALID) |
| 9 | `97df7f6` | реф-ссылка `?startapp=` после BotFather |
| 10 | `f2f3116` | payment-notify итоговая дата с реф-бонусом |
| 11 | `e6d7e15` | CRITICAL fix /start handler (баг привязки декоратора) |
| 12 | `e7361c4` | «Списать дней» через ту же кнопку admin_credit |
| 13 | `d7c3d14` | Pre-deploy checklist в CLAUDE.md |
| 14 | `a2d8c88` | Enforcement gap (AWG) — soft-revoke + auto-restore |
| 15 | `9ba0f69` | Юр.правка оферты round 1 (149-ФЗ ст.15.8) |
| 16 | `663120b` | Юр.правка round 2 + Политика ПД (/privacy) |
| 17 | `6296c1b` | `VPN Kronos` в /recovery (после раунда 4 LLM) |
| 18 | `ed98240` | ops(yc): swap 1G + restart Xray, закрыли 14-мин freeze'ы |
| 19 | `0dee1f5` | UX: Support button fix + онбординг-текст в тон юр.фильтру |

---

## Архитектурные изменения

### Cron entries на Fornex (теперь 6)

```
*/5 * * * * /opt/amnezia-save-conf.sh        # AWG persist safety net
*/5 * * * * scripts/traffic_accounting.py    # AWG lifetime + snapshots (NEW)
*/5 * * * * scripts/vless_summary_accounting.py  # VLESS per-server (стартовал 2026-05-29)
0 9 * * *   scripts/expiry_reminder.py       # T-7/T-3/T-0
0 */6 * * * scripts/sheets_sync_cron.py      # Google Sheets sync
*/15 * * * * scripts/health_check.py         # 22 проверки (Fornex+main+yc) batch
0 * * * *   scripts/enforce_expired.py --apply  # NEW: отзыв при истечении подписки
```

### Новые таблицы в БД

- `traffic_snapshots` — 14-дневная история per-pubkey rx/tx (для `traffic_diagnosis.py`)
- `vless_server_traffic` — per-server VLESS lifetime (создана 2026-05-29, расширения не требует)

### Новые public routes

- `/` → лендинг (раньше был редирект на /login)
- `/admin` → админ-панель (раньше была на `/`)
- `/oferta` → договор-оферта (3 раунда юр.правки)
- `/contacts` → реквизиты
- `/privacy` → Политика обработки ПД (152-ФЗ)
- `/recovery` → ЛК (как было) + acceptance notice под кнопкой

### Новые функции в коде

- `bot/wireguard_peers.py`:
  - `revoke_amneziawg_peer_soft(pubkey)` — отзыв из runtime, credentials в peers.json остаются
  - `restore_amneziawg_peer_runtime(pubkey, ip)` — возврат с теми же ключами
  - `restore_user_revoked_peers(tid)` — массовое восстановление всех revoked peer'ов юзера
- `bot/main.py`:
  - `_restore_and_notify(tid)` — hook в 3 payment handlers (Stars, claim_approve, admin_credit)
  - `_notify_inviter_about_signup_from_bot(ref_code)` — уведомление пригласителю
  - В `cmd_start`: fallback для `?start=ref_X` (если открыли в обычном чате, не Mini App)
- `web/app.py`:
  - `_notify_inviter_about_signup(ref_code)` — через прямой TG API (для web-flow)
  - `/admin/credit`: hook auto-restore peer

---

## Что осталось открытым (для следующих сессий)

### 🔥 Критичное / На действии владельца

1. **Уведомление РКН** (pd.rkn.gov.ru) — мы стали оператором ПД + Resend для email = трансграничная передача. 2 уведомления, бесплатно, ~30 мин. **БЛОКЕР для ЮKassa-модерации.**
2. **Регистрация мерчанта ЮKassa** — после уведомления РКН, подача на модерацию с готовым сайтом.
3. **Чек НПД в «Мой налог»** — текст услуги «Услуга по настройке и сопровождению защищённого сетевого соединения за 30 дней», НЕ «VPN-подписка».
4. **External uptime monitor** (UptimeRobot) — ждёт твоего решения с 2026-05-29 (если падает сам Fornex, alert не уйдёт).

### 🔥 САМОЕ ВАЖНОЕ в P1 (код)

5. **Per-user VLESS UUIDs** на всех 3 серверах. Закрывает enforcement gap для VLESS (сейчас закрыт только AWG). 4-6 ч поэтапно с 24-часовой паузой между migration и удалением общих UUIDs. **Не блокировано** ничем внешним.

### 🟡 Открыто в P1

6. **УТП в одно предложение** — отложено по psychological load. Кандидаты на руках в ROADMAP.
7. **Email-кампании** — 6 open questions владельцу (тон, скидка после expired, welcome письмо).
8. **Тарифы / прайс-лист** (грейды) — связано с per-device. ~3-4 ч.
9. **Автозачисление СБП/карты** — 4 варианта на столе (Cryptomus / Stars Sub ✅ / IMAP-копейки / самозанятость+Lava), владелец отложил.
10. **Сайт ЛК независим от Telegram** — отдельная сессия ~неделя.
11. **Phase 4 ЮKassa backend** — код можно готовить параллельно с подачей на модерацию (~2-3 ч).

### 🟡 Открыто в P2

12. **Split tunneling** — spec-04 устарела, нужен выбор архитектуры (A server-side / B client AllowedIPs / C VLESS routing). 1-6 ч в зависимости.
13. **Per-device конфиги (именованные слоты)** — связано с тарифами, без этого «семейный» технически не работает.
14. **Аудит markdown-доков** в `docs/` — потеплое (когда время будет).
15. **`/api/services` через health-check state** — мелкий tech debt (~1 ч).

### ⏸ Мониторить

16. **yc memory pressure** — после swap 1G + restart Xray должно быть стабильно. Если через несколько дней снова 14-мин freeze'ы — копать Xray (stats counters / connection state).
17. **«Скорость иногда падает»** — теперь есть `traffic_diagnosis.py` для pinpoint'а. Дождёмся следующей жалобы → прогон.

---

## Что зафиксировано в правилах (CLAUDE.md)

### Pre-deploy checklist (новый раздел, 2026-06-01)

После критического бага с /start handler:
- После Edit рядом с декораторами/импортами — прочитать блок ±5 строк контекста
- syntax check (`ast.parse`) на сервере перед restart
- import check (`import bot.main` или `from X import Y`) — ловит import-time errors
- После restart: `systemctl is-active` + журнал 30 сек grep'нуть error/except
- Для bot handlers — попросить владельца проверить /start (30 сек)

### Правило #12 (новое)

Swap на yc — 1 GB swapfile, swappiness=10 (RAM 960 MB, критически мало). Контекст: Xray на yc ел до 619 MB из-за накопления stats counters + state от SYN-сканеров.

---

## Что протестировано end-to-end

| Что | Кто проверил | Результат |
|---|---|---|
| Enforcement gap (revoke + auto-restore) | Я на синтетическом tid=999999999 | ✅ peer revoked → restored с теми же pubkey/ip, cleanup |
| Реферал-программа | Владелец на 2 TG-аккаунтах | ✅ регистрация B → уведомление A → оплата B → +14 обоим |
| Лендинг + оферта + контакты + Политика | Владелец визуально + LLM юр.экспертиза | ✅ после 3 раундов LLM «достаточно чисто для ЮKassa» |
| health-check batch SSH | Стресс-тест 3 прогона подряд | ✅ 22/22 OK каждый, ~2 сек |
| Кнопка «Поддержка» в браузере | Владелец | ✅ работает после фикса button → a |

---

## Незакрытые риски и наблюдения

1. **VLESS прямой share-link не отзывается** при истечении подписки — общие UUIDs, нельзя отозвать конкретного юзера. Решит только Per-user UUIDs (🔥 САМОЕ ВАЖНОЕ).
2. **yc memory pressure** может вернуться через несколько дней если Xray снова накопит state. Swap смягчает, но не лечит корень. Если повторится — отключение stats блока на yc / daily restart Xray cron.
3. **«VLESS-тихий» в админ-панели** для юзеров с прямой share-ссылкой — не видим их активность. Тоже решает Per-user UUIDs.
4. **Падение самого Fornex** — health-check не запустится, алерт не уйдёт. Лечится только external uptime monitor.

---

## Метрики за день

- 19 коммитов с push в `nikkronos/vpnservice`
- 3 крупных закрытия в ROADMAP (Phase 3i, Enforcement gap AWG, Реферал)
- 2 архитектурные проблемы расследованы и решены (health-check rate-limit, yc memory)
- 1 критический баг (бот не отвечал) — нашёл, исправил, зафиксировал процессное правило (Pre-deploy checklist)
- ~5 раундов юр.экспертизы оферты/лендинга

**Что я считаю главным достижением:** не количество, а **что мы вышли на состояние готовности к ЮKassa подаче**. Это разблокирует автоматизацию платежей, что снимает с владельца ручную обработку каждого payment claim.

Следующий шаг — Уведомление РКН + регистрация ЮKassa (это на тебе).

---

## Дополнение (поздний вечер 2026-06-01) — Per-user VLESS UUIDs Сессия 1

Решили закрыть **Per-user VLESS UUIDs** (🔥 САМОЕ ВАЖНОЕ в ROADMAP). 5 коммитов, ~3 часа работы. Архитектурное изменение по ходу — отказались от runtime API (`xray api adu` не работал), перешли на прямую правку config.json.

### Что сделано (Этапы 1, 2, 4, 5, 5.5 — все DONE)

| Commit | Этап | Что |
|---|---|---|
| `4c5caa3` | 1 | БД миграция: `users.vless_uuid_{eu1,main,yc}` + хелперы `db_get_or_create_vless_uuid`, `db_get_per_user_vless_uuid`, `db_get_all_per_user_vless_uuids`, `db_clear_per_user_vless_uuid` |
| `2648538` | 2 | `scripts/sync_xray_users.py` — синхронизация config.json на main/yc с БД через SSH + `xray run -test` validate + atomic mv + restart. Архитектурный pivot: НЕ runtime API. |
| `ea479d7` | 4 | Переписана выдача VLESS-ссылок (web `/sub`, `/api/recovery/mobile-link-by-email`, bot `callback_mobile_operator`). Подстановка per-user UUID + async sync Xray при создании нового UUID |
| `da996b4` | 5 | Backfill 42 юзеров (main + yc UUIDs созданы). sync_xray_users.py --all — 44 clients (43+1 shared) на каждом сервере |
| — | 5.5 | Broadcast отправлен владельцем 2026-06-01 23:20 МСК. Пауза 24ч до 02.06 ~23:20. |

### Архитектурный pivot: Этап 3 (Restore-скрипт) стал не нужен

**Изначальный план** предполагал runtime API (`xray api adu/rmu`) — UUIDs в памяти Xray, теряются при рестарте → нужен Restore-скрипт через systemd ExecStartPost.

**В процессе обнаружено:** `xray api adu` молча fail'ится на наших inbound'ах (даже после добавления `HandlerService` в `api.services`). Не разбирались глубже — выбрали более простой и надёжный путь.

**Принятая архитектура:** прямая правка config.json + restart. При этом UUIDs **живут в config.json**, переживают рестарт Xray по определению. **Restore-скрипт не нужен.**

`sync_xray_users.py` сам играет роль restore — БД = source of truth, скрипт регенерирует config.json из БД одной командой. Это **архитектурно лучше** runtime+restore: меньше движущихся частей, БД явный source-of-truth, sync_xray_users = инструмент общего назначения (backfill + regular sync + recovery).

В Этапе 8 добавлю cron `sync_xray_users.py --all` раз в 6 часов как safety net (аналог Etапа 3 safety-механизма в новом контексте).

### Другое архитектурное решение

**Email-маркер: `tid_<telegram_id>@kronos`** — синтетический, не утекают ПД в логи Xray.

**`iplimit` не используется** — Xray не принимал в JSON (нужен другой формат?). Отложено, вернёмся в Этапе 9.

**eu1 НЕ трогаем** — vless-ws на CDN-канале использует пул 9 share-UUIDs + 1 общий WS. Кто реально пользуется неясно. Сначала разведка, потом миграция. Отдельная подзадача внутри Per-user UUIDs.

### Что ждёт (после паузы 24ч)

- **Этап 7** (02.06 ~23:20): `sync_xray_users.py --all --no-shared` — удалить shared-UUIDs (старые ссылки legacy юзеров перестанут работать → broadcast предупредил)
- **Этап 8**: enforce_expired для per-user UUID, cron safety net sync, health-check consistency
- **Этап 9**: per-user телеметрия через `xray api statsquery user>>>` (теперь работает — email-маркеры есть)

### E2E подтверждено

```
GET /sub/<owner_token>:
  vless://2a748133-...@158.160.236.147:443?... (per-user yc)
  vless://5c444a98-...@81.200.146.32:443?...   (per-user main)
```
Раньше там были общие `11dd653c-...` и `359e23cc-...`.

### Что зафиксировано в правилах

CLAUDE.md: упоминание `sync_xray_users.py` в списке скриптов (добавлю в следующем коммите).

### Метрики Сессии 1

- 5 коммитов (`4c5caa3` → `da996b4`)
- 42 новых UUIDs созданы (для 42 юзеров, owner был у них из Этапа 1)
- 86 UUIDs в config.json (43 main + 43 yc — включая owner)
- 2 рестарта Xray (~5 сек downtime VLESS на каждом)
- 1 архитектурный pivot
- 0 нежданных багов (Pre-deploy checklist в действии)
