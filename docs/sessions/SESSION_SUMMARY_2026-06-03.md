# SESSION SUMMARY — 2026-06-03

> Per-user VLESS UUIDs — финальная сессия (Этапы 7+8+9). Архитектурная
> задача на 4 месяца вперёд закрыта чисто. 4 коммита.

---

## TL;DR

- ✅ **Этап 7 (удаление shared UUIDs):** `sync_xray_users.py --all --no-shared` + `policy.levels.0.statsUser{Up,Down}link` для per-user телеметрии. Apply на main + yc.
- ✅ **Этап 8 (enforcement для VLESS):** soft-revoke через SQL-фильтр (как `enforce_expired.py`) + auto-restore hook при оплате + cron `0 */6 *` safety net + health-check `vless_config_consistency` (23-я проверка).
- ✅ **Этап 9 (per-user телеметрия):** новая таблица `vless_user_traffic` + парсинг `tid_<X>@kronos` в `vless_summary_accounting.py` + `vless_last_seen` влияет на status='active' в админке + `vless_total_bytes` в users[].
- ✅ **Реальные метрики:** 7 юзеров на yc видны как `active` через per-user телеметрию (раньше показывались `idle`).
- 📋 **Открытая подзадача:** eu1 vless-ws (CDN канал) — не блокер.

---

## Контекст входа в сессию

01.06 закрыли Сессию 1 (Этапы 1-5 + broadcast 23:20 МСК). Договорились на паузу 24ч до 02.06 ~23:20.

02.06 параллельная сессия другого агента: **peers.json → SQLite (Phase 0-2)** в production. Брифинг получил перед началом — потенциальный конфликт по `bot/database.py` (модификация `_SCHEMA`, `init_db()`, `_conn()`), моя зона (`users` колонки + `sync_xray_users.py`) чиста. Работа другого агента уже в `main` + RKN-задачи закрыты (уведомление подано №100306737, решение остаться на Fornex, сравнение Продамус vs ЮKassa).

03.06 утром — продолжение Этапов 7-9. К моменту старта прошло ~36 часов с broadcast'а, поэтому пауза превышена.

---

## Observable check перед Этапом 7

Сначала `xray api statsquery -pattern='user>>>'` вернул `{}` на обоих серверах. Гипотеза: per-user stats не включены. Проверил `policy` — нет `levels.0.statsUser*`.

**Альтернативный observable:** journal Xray с `loglevel: info` → `grep email:` показал **реальные подключения**:
- **yc**: 8 уникальных per-user UUIDs за 2 дня (87 670 записей)
- **main**: 4 уникальных per-user UUIDs (4 920 записей)

Это подтвердило: pipeline работает, 8/43 юзеров уже на per-user (через subscription URL auto-refresh). Достаточно для принятия решения о Этапе 7.

---

## Этап 7 — детально

**`sync_xray_users.py` расширен:** теперь idempotent гарантирует `policy.levels.0.statsUser{Up,Down}link = true`. Без этого `xray api statsquery user>>>` возвращает пусто.

**Apply на оба сервера:**
- main: 45 clients → 44 (44 per-user, 0 shared)
- yc: 45 clients → 44 (44 per-user, 0 shared)

Validate через `xray run -test`, rolling restart прошёл. После restart **через 5 секунд** на yc уже видны 5+ юзеров в `statsquery user>>>` (cokoff, timurrrkakot, jdsklsj, и др. — реальный трафик).

Commit `92de823`.

---

## Этап 8 — детально

### Soft-revoke без новых флагов в БД

`sync_xray_users.py: fetch_db_users_for_server` теперь использует **тот же SQL-фильтр** что `enforce_expired.py`:

```sql
WHERE telegram_id IS NOT NULL AND active = 1 AND <vless_uuid_X> IS NOT NULL
  AND (expires_at IS NULL OR datetime(expires_at) > datetime('now', '-12 hours'))
```

**Эффект:**
- expires_at > now → активный → в Xray
- expires_at < now - 12h → revoked → НЕ в Xray (UUID убран при следующем sync)
- БД UUID не удаляется — только Xray state меняется

Dry-run показал 44 → 42 (отфильтровались Danila13if + 135509949 с истёкшим > 12h triala). Apply прошёл.

### Auto-restore при оплате

`_restore_and_notify(tid)` в `bot/main.py` (Stars/claim/admin_credit) и в `web/app.py` (/admin/credit) теперь триггерит **async subprocess** `sync_xray_users.py --all --no-shared`, если у юзера есть `vless_uuid_main` или `vless_uuid_yc`. Non-blocking — юзер сразу получает уведомление об оплате, sync восстанавливает UUID за 5-10 сек.

### Cron safety net

```cron
0 */6 * * * cd /opt/vpnservice && venv/bin/python scripts/sync_xray_users.py --all --no-shared 2>&1 | logger -t sync-xray-users
```

4 раза в сутки × ~5 сек downtime = 20 сек/день суммарно. Идемпотентно. Защита от drift БД↔config (например ручные правки).

### Health-check проверка `vless_config_consistency` (23-я проверка)

- SQL: count(active users с vless_uuid_X + expires_at OK) → `db_main`, `db_yc`
- SSH к main/yc: `jq '[.inbounds[]|select(.tag==X)|.settings.clients[]]|length'` → `cfg_main`, `cfg_yc`
- FAIL если diff > 2 (буфер для гонок sync ↔ health-check)
- Прогон: `db_main=42 cfg_main=42 (diff 0), db_yc=42 cfg_yc=42 (diff 0)` ✓

Commit `2ffe90f`.

---

## Этап 9 — детально

### БД миграция

Новая таблица `vless_user_traffic`:
- PRIMARY KEY (telegram_id, server_id) — юзер может быть active на main И yc
- lifetime_rx/tx + last_rx/tx (reset-aware accumulation)
- last_seen (datetime, обновляется при rx > 0 OR tx > 0)
- index по telegram_id

Хелперы:
- `db_accumulate_vless_user_traffic(server_id, samples)` — reset-aware
- `db_get_vless_user_last_seen()` → `{tid: max_last_seen across servers}`
- `db_get_vless_user_lifetime()` → `{tid: {rx, tx, total}}`

### Расширение `vless_summary_accounting.py`

Два запроса `xray api statsquery`:
1. `inbound>>>vless` (как было) → `vless_server_traffic`
2. `user>>>` (NEW) → `vless_user_traffic`. Regex `tid_(\d+)@kronos` → telegram_id. Только main/yc (eu1 без per-user UUID).

Прогон:
```
vless_summary[eu1]: vless-tcp=1626.6MB, vless-ws=30611.4MB
vless_summary[main]: vless-tcp=0.0MB, per-user=0 active
vless_summary[yc]: vless-xhttp=17.3MB, per-user=7 active
total rx+tx=32255.3 MB, per-user samples with traffic=7
```

### Интеграция в `/api/traffic`

- Новые поля в users[]: `vless_last_seen`, `vless_total_bytes`
- Status логика: `recent_vless = max(vless_requested_at, vless_user_traffic.last_seen) < 7d`. Если есть AWG-peer + recent_hs ИЛИ recent_vless → active. Если нет AWG-peer + recent_vless → active (VLESS-only).
- Закрывает кейс `@n_alitair_b` от 01.06: VLESS-юзеры больше не "тихие".
- `total_bytes` = AWG lifetime + VLESS lifetime (раньше только AWG).

**Топ-7 в `/api/traffic`:**
- @cokoff: 14 MB VLESS, status=active
- 378693761: 909 KB, active
- @t_arslann: 799 KB, active
- 237993736: 448 KB, active
- @timurrrkakot: 59 KB, active
- @jdsklsj: 40 KB, active
- @SalahievFR1: 7 KB, active

Commit `4e3fe18`.

---

## Сводка коммитов сессии

| Commit | Что | Файлы |
|---|---|---|
| `92de823` | Этап 7: удаление shared + policy stats | `sync_xray_users.py` |
| `2ffe90f` | Этап 8: enforcement + auto-restore + cron + health-check | `sync_xray_users.py`, `bot/main.py`, `web/app.py`, `scripts/health_check.py` |
| `4e3fe18` | Этап 9: per-user телеметрия | `bot/database.py`, `scripts/vless_summary_accounting.py`, `web/app.py` |
| `73ddb1f` | ROADMAP final | `ROADMAP_VPN.md` |

---

## Что разблокировано для бизнеса

1. **Enforcement для VLESS:** подписка истекла > 12h → юзер вылетает из Xray → ссылка не работает. Оплатил → восстановилось за 5-10 сек (auto-restore hook).
2. **Защита от расшаривания:** per-user UUID отзывается индивидуально. Юзеры, шерившие общий UUID, обломались после удаления shared.
3. **Точная активность в админке:** 7 юзеров перестали быть «тихими» (admin-панель `@n_alitair_b` problem closed).
4. **Per-user lifetime трафик** в БД для биллинга / тарифов / fair-use.
5. **Готовность к `iplimit`** — для тарифов с разным лимитом устройств (отложено в Этапе 1, теперь возможно).

---

## Архитектурные решения (durable)

- **Email-маркер:** `tid_<telegram_id>@kronos` — синтетический, без ПД в логах Xray
- **Sync через config.json + restart**, не runtime API (`xray api adu/rmu` silent fail на наших inbound'ах)
- **SQL-фильтр в `fetch_db_users_for_server` = `enforce_expired`** (единый source of truth для grace 12h)
- **Cron `0 */6 *` safety net** — на случай drift БД↔config
- **eu1 vless-ws (CDN канал) НЕ трогаем** — пул 9 share-UUIDs, отдельная подзадача

---

## Открытые задачи (для следующих сессий)

### Из ROADMAP P1 (большие)

- **Email-кампании** (6 open questions от меня владельцу)
- **Тарифы/прайс-лист + per-device конфиги** (связаны)
- **УТП в одно предложение** (отложено по psychological load)
- **Phase 4 ЮKassa backend** (можно начать параллельно с твоей модерацией)
- **Сайт ЛК независимый от Telegram** (~неделя)

### Из ROADMAP P2

- **Split tunneling** (выбор архитектуры A/B/C)
- **`/api/services` через health-check state** (~1 ч)
- **Аудит markdown-доков** в `docs/`

### Действия владельца

- **Подача ЮKassa-модерации** (после внесения РКН в реестр, ~неделя)
- **External uptime monitor** UptimeRobot
- **Чек НПД** — корректная формулировка услуги в «Мой налог»

### Подзадачи в Per-user UUIDs (закрыта, но есть остатки)

- **eu1 vless-ws** — пул 9 share-UUIDs + 1 общий WS. Сначала разведка кто использует, потом миграция. Не блокер.
- **iplimit** — для тарифной системы. Когда дойдут руки до тарифов.

---

## Метрики Сессии (03.06)

- 4 коммита (`92de823` → `73ddb1f`)
- ~3 часа активной работы
- 1 архитектурное расследование (observable: stats пустой → нашли в journal)
- 0 нежданных багов (Pre-deploy checklist в действии)
- 7 юзеров получили per-user телеметрию за 5 секунд после policy fix

---

## Дополнение (03.06) — peers.json → SQLite Phase 3 (параллельный агент Opus)

Завершение консолидации хранения peers (Phase 0-2 были 02.06). После суток dual-write на проде:

- **Reconcile:** `main` = `e6d460f` (Этапы 7-9 этой сессии). `storage.py` (моя зона) агентом per-user-UUID не тронут, сервер == main. Конфликта нет — peers-слой (`storage.py` + таблица `peers`) и per-user-UUID (`database.py` колонки + `sync_xray_users`) ортогональны.
- **Наблюдение успешно:** dual-write держался сутки — **27 peers.json == 27 таблица, 0 расхождений**, за период **3 реальных peer-write** (сигнап + enforce) → write-path отвалидирован на живом трафике.
- **`storage.py` (commit `84c7042`):** `DUAL_WRITE_JSON=False` — запись в `peers.json` отключена (файл = статический fallback-снимок). Удалено мёртвое зеркало `users.json` (`_sync_user_to_json`).
- **Деплой:** только `storage.py` (бэкап `storage.py.pre_phase3.*`), `database.py` агента не трогал. Тест 20/20 на сервере, рестарт vpn-bot/web, журнал чист, веб 200, consistency 27==27.

**Итог:** консолидация полная — `peers.json` и `users.json` больше не пишутся, источник правды только `vpn.db`. Будущая Postgres-миграция = «одна БД → другая».
