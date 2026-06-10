# Фаза 2 B — per-device слоты: детальный имплемент-док

> Создан 2026-06-10. **Спецификация перед кодом** (правок прода нет). Реализует
> Часть B арх-дока `docs/plan-phase2-keystone-architecture.md`. Цель: заменить
> per-OS слоты на именованные устройства — фикс коллизии iPad/iPhone (фидбэк
> Ани) + база под «семейный» тариф. Осторожно: трогает РАБОЧУЮ выдачу AWG-конфигов.

## 0. Scope (что трогаем / что НЕ трогаем)

- **Только AmneziaWG.** `platform` сейчас = ключ AWG-слота. VLESS НЕ трогаем (`vless_peers.py` не знает про platform — 0 упоминаний; VLESS = per-user UUID + iplimit отдельно).
- Поверхность по факту кода: `bot/storage.py` (Peer/ключ/find/upsert/delete), `bot/database.py` (таблица peers + хелперы), `bot/wireguard_peers.py` (~10 функций с `platform`), `bot/main.py` (**43** упоминания: get_config/regen/callbacks/delete/метки/инструкции), `web/app.py` (**18**: выдача в ЛК), `web/static/recovery.js` (UX устройств).

## 1. Целевая модель данных

`platform` (ОС) перестаёт быть КЛЮЧОМ слота, становится свойством устройства (нужно для формата доставки: Android = `vpn://` deeplink, iOS/PC = `.conf`, + тексты инструкций). Ключ слота → **именованное устройство**.

### 1.1 Новая таблица `devices` (вариант B2b — чище под список/лимит)
```sql
CREATE TABLE IF NOT EXISTS devices (
    device_id    TEXT PRIMARY KEY,              -- стабильный короткий id (hex8)
    telegram_id  INTEGER NOT NULL,
    name         TEXT NOT NULL,                 -- человекочитаемое («iPhone Ани»)
    os           TEXT NOT NULL DEFAULT 'pc',    -- 'pc'|'ios'|'android' — формат доставки
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_devices_tid ON devices (telegram_id);
```

### 1.2 `peers`: ключ (tid, server, platform) → (tid, server, device_id)
SQLite не умеет ALTER PRIMARY KEY → **пересборка таблицы** (идемпотентная миграция):
```sql
-- peers_new с новым PK; platform → os (инфо, не ключ)
CREATE TABLE peers_new (
    telegram_id INTEGER NOT NULL,
    server_id   TEXT NOT NULL DEFAULT 'rus1',
    device_id   TEXT NOT NULL,
    os          TEXT NOT NULL DEFAULT 'pc',
    wg_ip       TEXT NOT NULL,
    public_key  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    profile_type TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT,
    PRIMARY KEY (telegram_id, server_id, device_id)
);
```
Миграция копирует каждый существующий peer, создавая по устройству.

## 2. Миграция существующих peer'ов (ОДИН раз, идемпотентно, с бэкапом)

Для каждого `peers(tid, server, platform)`:
1. Создать `devices` строку: `device_id = hex8`, `os = platform`, `name = {pc:'ПК', ios:'Устройство iOS', android:'Android-устройство'}[platform]` (юзер потом переименует).
2. Вставить в `peers_new` с `device_id`, `os = platform`, остальные поля как есть.
3. После полной копии: `DROP peers; ALTER peers_new RENAME TO peers;` + индексы.

Свойства:
- **Идемпотентно:** если `devices` уже засеяны / `peers` уже в новом формате — пропуск (детект по наличию колонки `device_id`).
- **Бэкап:** перед пересборкой — `vpn.db` копия (как `migrate_peers_check.py`); сверка count(old) == count(new).
- **Каждый существующий слот → ровно одно устройство** (старый PK гарантировал уникальность (tid,server,platform), коллизий при копировании нет).
- 1:1 → данные клиента (wg_ip/public_key) сохраняются → **старые .conf продолжают работать** (ключи не меняются).

## 3. Изменения по файлам

### 3.1 `bot/database.py`
- `_SCHEMA`: + `devices`; `peers` — целевой вид с `device_id` (для свежих БД).
- Новая миграция `_migrate_peers_platform_to_device()` (см. §2), добавить в `init_db()`.
- Хелперы peers: `db_upsert_peer`/`db_delete_peer`/`db_get_all_peers` — ключ `platform` → `device_id` (+ `os`).
- Новые: `db_list_devices(tid)`, `db_get_device(device_id)`, `db_add_device(tid,name,os)→device_id`, `db_rename_device`, `db_delete_device`, `db_count_devices(tid)`.

### 3.2 `bot/storage.py`
- `Peer`: `platform` → `device_id` (ключ) + `os` (инфо). `_peer_storage_key` → `{tid}:{sid}:{device_id}`.
- `find_peer_by_telegram_id(tid, server_id, device_id)` — точная выборка по device_id; fallback-приоритет (pc→ios→android) убрать/переосмыслить (теперь устройства явные).
- `upsert_peer`/`delete_peer` — по `device_id`.
- `_normalize_platform` → оставить как `_normalize_os` (валидация os-значения).
- peers.json-зеркало (DUAL_WRITE_JSON=False) — мёртвый код, ключ обновить для консистентности или удалить ветку.

### 3.3 `bot/wireguard_peers.py`
- ~10 сигнатур: `platform=` → `device_id=` (+ `os=` где нужен формат). `create_amneziawg_peer`, `regenerate_*`, `find_peer_by_telegram_id`, `delete`.
- Формат доставки (Android deeplink vs .conf) теперь от `os` устройства, не от ключа.

### 3.4 `bot/main.py` (UX — самое заметное)
**Было:** «AmneziaWG» → выбор ОС (pc/ios/android) → один слот на ОС; «Обновить» по ОС.
**Стало:** «AmneziaWG» → **«Мои устройства»**:
- список устройств (имя + ОС-иконка) с действиями на каждом: `🔄 Обновить` (регенит ИМЕННО это устройство), `🗑 Удалить`;
- `➕ Добавить устройство` → выбрать ОС (для формата) → задать имя (или дефолт) → создать device + выдать конфиг;
- (Фаза 3) если достигнут `device_limit` — «➕» предлагает апгрейд тарифа.
- `callback_platform_select`/`_do_get_config`/`_do_regen` → работают по `device_id` (callback несёт device_id). `callback_instruction_platform` — инструкции по `os` устройства.
- Закрывает ловушку Ани: «обновить» одно устройство НЕ трогает соседнее (разные слоты).

### 3.5 `web/app.py` + `recovery.js` (ЛК)
- Раздел «Мои устройства»: список/добавить(имя)/обновить-конкретное/удалить + QR/файл на устройство. 18 platform-мест → device_id/os.

## 4. Раскатка без поломки (rollout)

1. Код деплоится; `init_db()` на старте сервиса делает миграцию (бэкап+сверка). Сервисы рестартятся управляемо (pre-deploy checklist).
2. Старые .conf у юзеров **продолжают работать** (ключи не тронуты — 1:1 миграция).
3. Старые callback'и (`getcfg_ios` и т.п.) — принять как «устройство по умолчанию для этой ОС» (legacy-совместимость), чтобы кнопки из старых сообщений не падали.
4. Откат: бэкап `vpn.db` + код предыдущей версии.

## 5. Поэтапный план + тесты (НЕ одним куском)

- **B0.** Расширить `scripts/test_peers_sqlite.py`: тест миграции platform→device на временной БД (создать old-peers, прогнать миграцию, проверить devices+peers_new, count, идемпотентность повторного прогона). **Зелёный тест — гейт на прод-миграцию.**
- **B1.** Схема + миграция + db-хелперы (`database.py`). Прогнать B0 локально и на копии прод-БД.
- **B2.** `storage.py` + `wireguard_peers.py` (ключ device_id). Юнит-проверка find/upsert/delete.
- **B3.** UX бота (`main.py`): список устройств / добавить / обновить / удалить. Смоук: владелец добавляет 2 iOS-устройства → независимы (фикс Ани).
- **B4.** ЛК (`app.py`+`recovery.js`).
- **B5.** (Фаза 3) привязка `device_limit` к числу устройств.

Каждый шаг — отдельный коммит, прод-миграция (B1) — только после зелёного B0 + бэкап.

## 6. Открытые решения для владельца
1. **Имя устройства при добавлении:** спрашивать ввод имени, ИЛИ авто-имя («iPhone 1») с возможностью переименовать потом? (склоняюсь к авто-имя + переименование — меньше трения.)
2. **Старые 3 кнопки ОС** оставить как быстрый «добавить (ПК/iOS/Android)», ИЛИ полностью перейти на список устройств? (склоняюсь: «➕ Добавить» → выбор ОС → авто-имя — сохраняет привычный шаг выбора ОС, но создаёт независимый слот.)
3. **Лимит устройств по умолчанию** (до тарифов) — без лимита, или мягкий cap (напр. 5), чтобы не плодить слоты до Фазы 3? (склоняюсь к мягкому cap.)

## 7. Риски / что НЕ делать
- **Трогаем рабочую выдачу конфигов** → строго поэтапно, миграция только после зелёного теста + бэкап, смоук владельца после каждого UX-шага (pre-deploy checklist).
- НЕ менять ключи существующих peer'ов (1:1) — иначе у людей отвалятся .conf.
- НЕ трогать VLESS/релей/iplimit здесь (Оккам).
- НЕ делать «семейный» лимит до Фазы 3 — сначала механика устройств.
