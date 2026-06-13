# DONE_LIST_VPN — выполненные задачи VPN/Proxy проекта

> Хронология выполненного (newest-first). Единый формат: `## дата — заголовок` +
> сжатые буллеты (что сделано / решение / коммит). Детали — в коммитах и
> `docs/sessions/SESSION_SUMMARY_*`. Открытые задачи — в `ROADMAP_VPN.md`.
> Сжато 2026-06-13 (порядок в документах). Записей: 79.

## Оглавление

**2026-06**
- 2026-06-12 — Churn-опрос + сегментированная рассылка (S1+S2+S3)
- 2026-06-12 — Продуктовые доводки воронки (триал/тест/напоминания/онбординг/UX)
- 2026-06-11 — Тарифы 199/249/449/599 НА ПРОДЕ
- 2026-06-11 — VLESS enforcement-лаг закрыт (sync ежечасно)
- 2026-06-11 — fail2ban на main/yc/yc2
- 2026-06-11 — Фаза 2 B4: устройства в ЛК → Фаза 2 B завершена
- 2026-06-11 — yc2 ночной false-FAIL устранён
- 2026-06-11 — Гигиена: ссылки RULES_CURSOR.md → RULES.md
- 2026-06-10 — Фаза 2 B3: «Мои устройства» в боте (фикс Ани)
- 2026-06-10 — Фаза 2 B1+B2: per-device слой (cutover)
- 2026-06-10 — access_audit расширен на main-wg0 + legacy
- 2026-06-10 — Подписка/ЛК через Яндекс-фронт (БС-резильентность)
- 2026-06-10 — Фаза 2 A-Stage1: iplimit-наблюдение
- 2026-06-10 — Поштучный разбор eu1 «shared» + liveness-аудит
- 2026-06-10 — Фрод-зона eu1: попытка Этапа 4 откачена (релей yc/yc2→eu1)
- 2026-06-10 — Подписка: Яндекс-серверы первыми
- 2026-06-10 — yc2 досинхронизирован
- 2026-06-04 — UX-фикс: единый путь подключения (@veryvoro)
- 2026-06-03 — Админ-панель: активность+VLESS, /api/services; диагностика T-7
- 2026-06-03 — peers.json → SQLite Phase 3 (консолидация завершена)
- 2026-06-02 — Мониторинг eu1 + чистка доков + .gitattributes
- 2026-06-02 — Уведомление РКН подано (вариант B)
- 2026-06-02 — Консолидация peers.json → SQLite, Phase 0-2

**2026-05**
- 2026-05-27 — Telegram Stars + ручная СБП/карта + админ-форма (Phase 3g+3g+)
- 2026-05-25 (вечер) — supportkronos.online, прямой HTTPS, subscription validated
- 2026-05-25 — ЛК: модель аккаунта + UX + триал/реферал + пароль (Фазы 0–2)
- 2026-05-24 — Учёт трафика lifetime + Email/Всего + swap + диагностика скорости
- 2026-05-21 (вечер) — Recovery-сайт передел + Error-103 fallback
- 2026-05-21 — Yota/Мегафон при БС РЕШЕНО + fix AmneziaWG persistent peers
- 2026-05-20 — Финальный тест CDN relay при БС
- 2026-05-19 — Yandex CDN relay (XHTTP) + выбор оператора
- 2026-05-16 — Тест VLESS+REALITY при белых списках
- 2026-05-15 — Авторизация веб-панели + трекинг прокси
- 2026-05-14 — Аудит безопасности веб-панели
- 2026-05-14 — IPv6 в AllowedIPs (защита от leak)
- 2026-05-13 — Platform-based доставка конфига
- 2026-05-13 — Trojan-сетап задокументирован
- 2026-05-11 — Защита Fornex от брутфорса/UDP-флуда
- 2026-05-11 — Багфикс eu2 → eu1 при /regen
- 2026-05-09 — xHTTP packet-up на YC VM
- 2026-05-08 — Анализ конкурентов, удаление eu2, редизайн панели
- 2026-05-07 — Рефакторинг UX бота + git setup
- 2026-05-06 — Yandex Cloud VLESS+REALITY relay
- 2026-05-05 — Cloudflare CDN стек для LTE

**2026-04**
- 2026-04-13 — Предпрод-план коммерциализации + синхронизация AI-идей
- 2026-04-12 — Доступ к мониторингу/recovery (UFW + ссылки)
- 2026-04-11 — Пост-миграция бота на Fornex (Россия/EU/SSH)
- 2026-04-11 — vpn-web и /recovery на Fornex; отключение Timeweb-панели
- 2026-04-10 — MTProxy Fake TLS на Fornex (8444), /proxy_rotate
- 2026-04-02 — Логические слоты rus1/rus2/eu1/eu2 + recovery EU1+EU2
- 2026-04-02 (доп.) — Spec-08: без нового VPS
- 2026-04-02 — Спека вторая нода (RU2/EU2), GearUp-документ

**2026-03**
- 2026-03-30 — Сводная документация MTProxy + README
- 2026-03-30 — Деплой: явный pip в venv (PEP 668)
- 2026-03-30 — Ротация MTProxy: /proxy_rotate, override-файл
- 2026-03-30 — README: MTProxy Fake TLS vs голый MTProto
- 2026-03-26 — LTE blackhole, MVP/юнит-экономика
- 2026-03-25 — Веб recovery: Telegram/VPN + ссылка в боте
- 2026-03-23 (продолжение) — Документация попытки LTE + eu1
- 2026-03-23 — Мобильный резерв: VLESS+REALITY + /mobile_vpn
- 2026-03-15 — Сторонние альтернативы для Telegram
- 2026-03-14 — Диагностика тайм-аута AmneziaWG, /broadcast
- 2026-03-07 — Telegram-прокси Fake TLS, алгоритм разблокировки, оценка провайдера

**2026-02**
- 2026-02-26 — Автоматизация выдачи конфигов AmneziaWG + удаление /proxy
- 2026-02-23 — Восстановление eu1, эксперименты Remnawave/Xray/MTProto (неудачны)
- 2026-02-22 — Чистый сброс eu1: AmneziaWG, проверка ПК/iOS
- 2026-02-21 — Веб-панель: деплой, этапы 2–3
- 2026-02-21 — Бот: Европа = AmneziaWG
- 2026-02-21 — AmneziaWG на eu1 работает, iOS через «Поделиться»
- 2026-02-21 — Стратегия обхода РКН, выбор AmneziaWG
- 2026-02-20 — Улучшение UX + troubleshooting-доки
- 2026-02-18 — WireGuard + Shadowsocks и клиенты
- 2026-02-18 — Установка Telegram MTProto Proxy
- 2026-02-18 — Интеграция бота: инструкции, MTProto, VPN+GPT
- 2026-02-15 — Отладка eu1: WG UDP из РФ к Fornex не работает
- 2026-02-14 — Вторая нода eu1 (Fornex, Германия)
- 2026-02-13 — Лимиты трафика + рабочая /regen
- 2026-02-11 — Self-service через Telegram-бота
- 2026-02-09 — Базовая структура + первая WireGuard-нода

---

## 2026-06-12 — Churn-опрос + сегментированная рассылка (S1+S2+S3) НА ПРОДЕ

Диагностика воронки: спрашиваем у отвалившихся причину. Ветка `feature/churn-survey` → main (`1173213`). Смоук владельца (тест-сегмент на 2-й акк) ок.
- **S1 — сегментированная рассылка** (owner «📢 Рассылка»): `db_users_by_segment` — all / active / inactive / inactive_no_onboarding / inactive_used / **test** (2-й акк владельца). Флоу: сегмент → счёт → «📝 текст | ❓ опрос» → отправка (пейсинг, 403-скип, отчёт). На проде: active 26 / inactive_used 16 / inactive_no_onboarding 13.
- **S2 — опрос причин + win-back.** `bot/churn.py` (единый источник текстов/причин, 2 вида: `churn` 3.2 / `onb` 3.1). Колонки `users.drop_reason`/`drop_reason_at`/`churn_asked_at`. Callback `drop:<kind>:<code>` → сохранить причину → дедуп → win-back; «не работало»/«другое» → уточнение текстом. `drop_reason` → Google Sheets. **Авто-T+1** (`expiry_reminder`): истёк вчера + неактивен + онбординг завершён + не спрошен → опрос. T-0: кнопка «🤔 Не планирую продлевать».
- **S3 — рассылка опроса по бэклогу** (churn для inactive_used, onb для inactive_no_onboarding) с дедупом по `churn_asked_at`.

## 2026-06-12 — Продуктовые доводки воронки (триал/тест/напоминания/онбординг/UX)

По разбору воронки. Ветка `feature/product-tweaks` → main (`3361848`).
- **Триал 14→7 дней.** `TRIAL_DAYS` централизован в `bot/tariffs.py` (был захардкожен ~8 мест). Реферал +14 не тронут. Только новые триалы.
- **Платный тест 49₽/7д/3 устр. — РАЗОВЫЙ** (как триал). Тариф `(3,0)` (months=0=тест). `users.test_used` + `db_is_test_used`/`db_mark_test_used`; скрыт/блок повторно в боте и ЛК (409). Кнопка «🧪 Сначала тест — 7 дней за 49 ₽».
- **Ежедневные напоминания с 7 дней** (вместо T-7/3/0): `db_users_due_for_daily_reminder` (окно 0..7) + `last_reminder_date`. Покрывает подписку/триал/тест.
- **Онбординг-вопрос «для чего VPN»** (свободный текст) → `users.use_case` + **Google Sheets**. FSM + кнопки «✍️ Ответить»/«⏭ Пропустить».
- **«🔄 Не работает» под каждой выдачей конфига** (бот + ЛК `lastConfigRetry`); из главного меню убрана.
- **Тексты** (приветствие, онбординг-интро) + **цветные кнопки бота** (Bot API 9.4 `style`, апгрейд `pyTelegramBotAPI 4.17→4.34`). Rollback: `pip install pyTelegramBotAPI==4.17.0`.

## 2026-06-11 — Тарифы 199/249/449/599 НА ПРОДЕ (3/5 устр. × 1/3 мес)

Бизнес-приоритет #1. 2-шаговый выбор (устройства → срок). Ветка `feature/tariffs` → main (`51292f3`). Смоук (бот+ЛК) ок.

| Устройств | 1 мес | 3 мес |
|---|---|---|
| 3 | 199 ₽ / 150 ⭐ | 449 ₽ / 350 ⭐ |
| 5 | 249 ₽ / 200 ⭐ | 599 ₽ / 450 ⭐ |

- Единый источник `bot/tariffs.py` (цена считается на сервере; клиент шлёт devices+months).
- **DB:** `users.device_limit` + `payment_claims.device_limit` (DEFAULT 5 = грандфазер + триал; все 58 юзеров = 5). `db_get_device_limit`.
- **Cap по тарифу:** бот+ЛК читают `db_get_device_limit` (хардкод 5 убран). При покупке 3-тарифа лишние устройства не удаляются, только блок добавления сверх лимита.
- **Деплой:** бэкап кода + БД → scp 6 файлов → AST+import → restart bot+web → миграция → health 0 FAIL.

## 2026-06-11 — VLESS enforcement-лаг закрыт (sync ежечасно + no-change guard)

**Проблема** (алерт `vless_config_consistency`): `enforce_expired` режет AWG ежечасно, а `sync_xray_users` убирал истёкшие VLESS-UUID раз в 6 ч → истёкший до ~6 ч сохранял VLESS (главный путь) = enforcement-лик + ложные FAIL на когортах истечений.
- **`sync_xray_users.py`:** **no-change guard** (сравнение clients[]/policy; идентично → config не трогаем, Xray не рестартим) + cron `7 */6` → `7 *` (ежечасно). Лик 6ч→~1ч.
- Guard провалидирован на проде (×3 «нет изменений, не рестартим»). Документировано в CLAUDE.md (#10).
- **Остаток (опц.):** debounce чека (алерт если diff держится ≥2 циклов).

## 2026-06-11 — fail2ban на main/yc/yc2 (подавление SSH brute-force)

Закрывает follow-up «yc2 ночной false-FAIL» (ниже). `645cb63` лечил симптом, brute-force (76 sshd-событий/5мин) оставался.
- `apt install fail2ban` на yc2/yc/main (Ubuntu 24.04). **Fornex НЕ трогали** (jump/мониторинг-хост).
- `/etc/fail2ban/jail.local`: `[sshd]`, `backend=systemd`, maxretry=5/findtime=10m/bantime=1h, **`ignoreip` содержит Fornex `185.21.8.91`** (иначе fail2ban забанит мониторинг = каскад).
- **Готча Ubuntu:** SSH-юнит = `ssh.service`, не `sshd.service` → пин `journalmatch`.
- **Верификация:** fail2ban-regex ловит реальные события; тест-бан в nft (на yc сосуществует с ufw); на main забанил 7 реальных атакующих IP; Fornex ни на одном не забанен.
- **health_check** +`fail2ban.service` для main/yc/yc2 (29→32 проверки).
- **Follow-up:** Fornex без fail2ban (риск самобана с динам. IP); main key-only хардненг (1 legacy WG-user).

## 2026-06-11 — Фаза 2 B4: устройства в ЛК (фронт) → Фаза 2 B ЗАВЕРШЕНА

Последний кусок per-device — «Мои устройства» в веб-ЛК (зеркало бот-флоу). Merge `feature/per-device-lk` → main (`caecf9d`+`44940b6`).
- **`web/app.py`:** `/api/recovery/device-rename` (+ 4 эндпоинта devices/add/regen/delete были на ветке).
- **`recovery.html`/`recovery.js`:** «🖥 Мои устройства» — список/add(ОС→конфиг)/regen/delete/rename; `renderAwgPayload` (config/QR/`vpn://`), cap 5.
- **Деплой:** бэкап → scp 3 файла → AST → restart vpn-web → 5 device-роутов 401. Смоук владельца (браузер+Mini App, кросс-консистентность с ботом) ок.
- **Фаза 2 B завершена** (B1+B2+B3+B4). Разблокированы тарифы по числу устройств.

## 2026-06-11 — yc2 ночной false-FAIL мониторинга устранён (ретрай SSH)

**Симптом:** ночью ~02:00 UTC алерт `vless_config_consistency yc2_rc=255`, «DOWN ~14 мин» → RESOLVED.
- **Диагноз (по логам):** НЕ простой сервиса (Xray NRestarts=0, журнал непрерывен, 0 OOM). Причина — ночной SSH brute-force упирает sshd в MaxStartups; в :00 совпадают Fornex-кроны → SSH-коннект чека отбивается rc=255 → false-FAIL. Юзеры не отваливались.
- **Фикс (`health_check.py`, `645cb63`):** `_run_remote_resilient` — ретрай на rc=255/timeout (3 попытки). Реальные ошибки команды не маскируются.
- **Заодно:** yc2 persist `swappiness=10` (выровнено с yc).
- **Follow-up:** fail2ban на yc/yc2/main (сделано, см. выше).

## 2026-06-11 — Гигиена: ссылки RULES_CURSOR.md → RULES.md

5 доков (`security.md` + архив/old-сессии) ссылались на переименованный `RULES_CURSOR.md` → поправлено на `RULES.md` (`913c1dc`).

## 2026-06-10 — Фаза 2 B3: «Мои устройства» в боте НА ПРОДЕ (фикс Ани ✅)

Поверх B1+B2 — UX именованных устройств. **Баг Ани закрыт:** 2 устройства одной ОС (iPhone+iPad) сосуществуют.
- **`wireguard_peers`:** `device_id` в create/regen + `delete_amneziawg_device`.
- **`bot/main.py`:** «🖥 Мои устройства» в «Другие способы» — список / добавить (ОС→авто-имя→конфиг) / обновить / удалить. cap 5. Per-OS путь не тронут (аддитивно).
- **Деплой:** ветка `feature/per-device-ux` → AST+import → restart → смоук владельца → merge.

## 2026-06-10 — Фаза 2 B1+B2: per-device слой данных НА ПРОДЕ (cutover)

Заменили per-OS слоты на именованные устройства (фикс коллизии iPad/iPhone + база под «семейный» тариф).
- **Что:** ключ `peers` `(tid,server,platform)` → `(tid,server,device_id)` + таблица `devices`. `platform`→`os`. **Backward-compat shim** в storage → бот/ЛК/wireguard_peers без правок. Миграция `_migrate_peers_platform_to_device` (1:1, старые .conf живут).
- **Cutover (staged, с откатом):** бэкап БД+код → stop → деплой → миграция → start → smoke. Инцидент по ходу: `_migrate_peers_json_to_sqlite` падал на device-схеме → пофикшен guard'ом.
- **Верификация:** 31→31 peer (1:1) + 31 device; сервисы active; тесты зелёные; смоук владельца ок. Имплемент-док `docs/plan-phase2B-per-device-impl.md`.

## 2026-06-10 — access_audit расширен на main-wg0 + legacy-строки (блайнд-спот закрыт)

Аудит видел VLESS+AWG-eu1, но не main-wg0 и не peer-строки на снятых серверах.
- **`scripts/access_audit.py`:** `audit_main_wg0()` (SSH `wg show wg0 dump`) + `audit_legacy_peer_rows()`.
- **Находки:** main wg0 — тяжёлый `Mjvdy` (~96 ГБ, Жуковский) опознан как НЕ нужный (не @aaguseinov, не в боте) → **удалён обратимо** (данные на main `/root/wg0-removed-Mjvdy.*`). Остался `/5BeCINho` (СПб, вероятно «1 legacy user», оставлен). 6 legacy peer-строк (cruft) → помечены `active=0` (история сохранена, не удалены).
- **Урок:** forensic-сверка pubkey с runtime ДО вывода «мёртв».

## 2026-06-10 — Подписка/ЛК через Яндекс-фронт (БС-резильентность)

**Проблема:** `supportkronos.online` резолвился в немецкий IP eu1 → при БС недоступен → HAPP не обновлял подписку (главный failover-рычаг не работал под БС).
- На yc+yc2 — `socat sub-forward.service` (:8443 passthrough → Fornex:8443; TLS на Fornex). DNS A → yc+yc2 (round-robin, TTL 60, grey-cloud). eu1:8443 остаётся бэкендом → даунтайма ноль. health-check +yc/yc2:8443.
- **⚠️ Caveat:** no-regret по IP (Яндекс ≥ немецкий под БС); устойчивость по SNI `supportkronos.online` не доказана — валидировать при БС.

## 2026-06-10 — Фаза 2 A-Stage1: iplimit-НАБЛЮДЕНИЕ запущено (без enforcement)

Старт keystone (`docs/plan-phase2-keystone-architecture.md`). Замер «IP на юзера» неделю → калибровка порогов анти-шеринга по данным.
- **Таблица `ip_usage`** (retention 48ч) + **`scripts/ip_usage_watcher.py`** (cron `*/10`): парсит access-log 4 входов, `from <IP> … tid_X@kronos`. Релей-строки `127.0.0.1` игнор. `--report`.
- **Проверено:** макс 2 IP на юзера (дом+мобайл), шеринга нет — чистый baseline. **Enforcement (Stage 2) — после калибровки.**

## 2026-06-10 — Поштучный разбор eu1 «shared» + liveness-аудит (в наблюдении)

После инцидента (ниже) — разбор не-per-user UUID на eu1 со 100% доказательством.
- **`scripts/vless_uuid_forensics.py`** (read-only): **1 релей** (`359e23cc`, yc/yc2→eu1) + **9 eu1-only client-share** на vless-tcp.
- **Liveness:** через access-log (eu1 per-user STATS не работают by design). За ~16ч — 0 использований всех 9.
- **Инструментовка** (`instrument_eu1_shares.py`) + наблюдение (`eu1_share_audit_sampler.sh`, cron `23 */6` → `/var/log/eu1-share-audit.log`).
- **▶ Завершить:** если 9 = «не использовались» → удалить `sync_eu1_vless.py --no-shared --force` (RELAY_PRESERVE бережёт релей) + снять обвязку. Если UUID всплыл → живой юзер, мигрировать.

## 2026-06-10 — Фрод-зона eu1: ПОПЫТКА Этапа 4 ОТКАЧЕНА (вскрыт релей yc/yc2→eu1)

**Хотели:** удалить 11 «shared» UUID на eu1. **Что пошло не так:** `sync_eu1_vless.py --no-shared` снёс shared → **выход «Европы» перерубило.**
- **Корень (критический факт):** **yc/yc2 («Европа») — НЕ прямые выходы, а фронт-релеи** → outbound `vless+ws → eu1:80/vpn`. UUID `359e23cc` = релей-credential (без tid-email → `access_audit` ошибочно метил «фрод»). Память `project_vpn_yc_relay_topology`, [[feedback_no_delete_runtime_blind]].
- **Восстановление:** откат eu1-конфига из бэкапа → рестарт → 0 ошибок. Снят опасный cron `17 */6 sync_eu1_vless`.
- **Защита:** `RELAY_PRESERVE={359e23cc}` бережётся всегда; `--no-shared` теперь требует `--force`. `access_audit` помечает релей отдельно.
- **Статус:** фрод-зона eu1 НЕ закрывается как `--no-shared` (eu1 vless-ws несёт релей). Прямые входы (vless-tcp/xhttp) уже per-user.

## 2026-06-10 — Подписка: Яндекс-серверы первыми (pre-broadcast фикс)

**Проблема:** по подписке Германия (eu1) и Россия (main) «не работают», работает только Европа — IP-репутация РКН (`project_vpn_rkn_ip_block`), а Германия стояла первой → юзер видел «сломано».
- **Фикс:** `_build_subscription_links` (`web/app.py`) — порядок **Европа (yc) → Европа-2 (yc2) → Германия (eu1) → Россия (main)**. Авто-разъезд по клиентам за ~12ч (без broadcast).

## 2026-06-10 — yc2 досинхронизирован (sync_xray_users + health_check)

yc2 (РФ-резерв, клон yc от 06-09) не входил в cron-sync/мониторинг → дрейфнул бы с первыми оплатами/истечениями.
- **`sync_xray_users.py`:** yc2 в `SERVERS` (db_column=`vless_uuid_yc` — клон). `--all` → [main, yc, yc2].
- **`health_check.py`:** yc2 в `REMOTE_HOSTS`/`CHECK_PLAN`; `vless_config_consistency` для yc2 сверяется с db_yc. 23→27 проверок.
- **Верификация:** паритет 50/50/50, sync yc2 OK, health 27/27. Первый шаг `docs/plan-blocking-antifraud-traffic-tariffs.md` закрыт.

## 2026-06-04 — UX-фикс: единый путь подключения (фидбэк @veryvoro)

**Диагностика:** @veryvoro «на мобильном ничего не работает». Сервер исправен. Корень клиентский: AmneziaWG не для мобильного (UDP), а VLESS был на старой shared-ссылке (убита Этапом 7) — новую подписку не переимпортировал.
- **Фикс (тексты/разводка):** ссылка `/sub` везде = «Подключить VPN»; `🔄 Обновить конфиг` → `🔄 Не работает` с разводкой ПК/Телефон; AmneziaWG помечен «не для мобильного». Синхронно бот/ЛК/MiniApp. `SESSION_SUMMARY_2026-06-04.md`.

## 2026-06-03 — Админ-панель: активность+VLESS, /api/services из health-check; диагностика T-7

- **Активность учитывает VLESS** (`d9464b4`): счётчики `active_*` по `max(AWG handshake, VLESS last_seen, vless_requested_at)`. Было «3 за 24ч» → 16.
- **`/api/services`** из `/var/lib/vpn-health/state.json` → 5 user-facing сервисов + staleness; убран хардкод IP `158.160.0.1`.
- **Массовый T-7 reminder** (`b6d66ab`) — НЕ баг: при миграции 27.05 выдали 14-дн триал → ~30 истекают 10.06 разом. Решение: оставить триал. Доки/память исправлены.

## 2026-06-03 — peers.json → SQLite Phase 3 (консолидация завершена)

После суток наблюдения dual-write:
- **`storage.py`:** `DUAL_WRITE_JSON=False` (peers.json больше не пишется, остаётся read-only fallback). Удалено мёртвое зеркало `users.json`.
- Наблюдение: 27 json == 27 таблица, 0 расхождений, 3 реальных write. Тест 20/20. Источник правды только `vpn.db` → будущая Postgres-миграция «одна БД → другая».

## 2026-06-02 — Мониторинг eu1 + чистка доков + .gitattributes

- **`scripts/eu1_monitor.sh`** (`6eb38cc`, cron `*/5`): CSV метрик (load/RAM/swap/conntrack/awg/rx-tx) в `/var/log/eu1-monitor.log`. Под жалобы «скорость падает».
- **Чистка доков** (`b1c548a`,`4f98e04`): 18 устаревших → `docs/archive/` (git rename); баннеры «устарело» на spec-05/07, deployment, eu1-setup, backup-restore. `docs/` root ~40→31, specs ~10→4.
- **`.gitattributes`** (`0283986`): LF для `*.sh`/`*.py` (защита от CRLF на Windows).

## 2026-06-02 — Уведомление РКН об обработке ПД подано (вариант B)

Оператор ПД (email+telegram_id) → подали на pd.rkn.gov.ru. **Номер 100306737, ключ 15161399.** В реестр ~неделя.
- Уведомление одно (трансгранично = раздел в форме). **Вариант B (остаёмся на Fornex, подаём честно)** — перенос управлялки на RU отложен (риски: Telegram-API из РФ untested, корреляция отказов, кросс-граница SSH).
- В форме: место БД = Германия; трансгранично = США (Resend) + Германия (хостинг); ответств. хранение = Fornex (ИП Лавков, рос. ИП). Авто-плашка 242-ФЗ — ожидаемо для B, не отказ.
- Гайд: `docs/rkn-notification-guide.md`. Разблокировало регистрацию ЮKassa.

## 2026-06-02 — Консолидация peers.json → SQLite (таблица `peers`), Phase 0-2

«Переделать БД» (refactor, не Postgres). До этого peers жили только в `peers.json` (второй источник правды, кусал 29.05).
- **Phase 0** (`689e8f2`): таблица `peers` (composite-PK = ключ peers.json) + `_migrate_peers_json_to_sqlite()` + `db_get_all_peers/upsert/delete` + `PRAGMA busy_timeout=5000`.
- **Phase 1:** storage читает из таблицы (fallback JSON если пусто) + dual-write зеркало (`DUAL_WRITE_JSON=True`). API/dataclass не тронуты (~30 call sites целы).
- **Cutover (Phase 2):** бэкап → dry-run на копии прод-данных (26→26) → деплой → миграция ДО рестарта → `peers_sync_check` 20/20 eu1==awg, 2 legacy LIVE целы. Велось в `feat/peers-to-sqlite` → main (FF). Координация с per-user-UUID агентом (сверено md5).
- **Остаётся Phase 3:** выключить dual-write (сделано 06-03, см. выше).

## 2026-05-27 — Telegram Stars + ручная СБП/карта + админ-форма зачисления (Phase 3g + 3g+)

Промежуточный платёжный стек до автоматизации.
- **Phase 3g — Stars** (`d0155e8`): `/api/billing/create-stars-invoice` (XTR, payload `stars_sub:tid:days:ts`) + `successful_payment` хендлер (idempotency по `telegram_payment_charge_id` → `db_record_payment` → `db_extend_subscription(+30)` → `db_apply_referral_bonus(+14)`). Кнопка в ЛК.
- **Phase 3g+ — ручная СБП/карта** (`8ee3541`): реквизиты Т-Банк (СБП `+79213032918`, карта `2200700760464759`) в ЛК + «✉️ Написать @nikkronos». **`/admin/credit`** — форма ручного зачисления (idempotent по `external_id`).
- **Фикс UX:** `trial_available = not trial_used AND expires_at IS NULL` (грандфазер не видит кнопку триала).
- Осталось: автоматизация платежей (4 варианта в ROADMAP).

## 2026-05-25 (вечер) — Домен supportkronos.online, прямой HTTPS на Fornex, subscription-спайк validated

Проверили модель «subscription-URL + HAPP» на нашей инфре.
- **Спайк:** `users.sub_token` + `GET /sub/<token>` → base64 REALITY-ссылок (YC `www.microsoft.com` + main `cloud.mail.ru`), гейт `db_is_access_active`. ЛК-блок «Подписка» + QR. ProxyFix.
- **HTTPS:** купили `supportkronos.online` (нейтральное «support»-имя). **CF не надёжен в РФ** (HAPP таймаут, Safari владельца не открывает через CF — DPI RST, durable). → дроп CF, A-запись grey-cloud → Fornex; LE через DNS-01 (CF API token); **nginx :8443 ssl** → :5001 (443 занят REALITY). `docs/scripts/nginx-supportkronos-8443.conf`.
- **Validated в HAPP** (2 сервера, Wi-Fi+LTE). Метки `🇪🇺 Европа / 🇷🇺 Россия` (`0d74701`). Создан бот `@vpnkronos_bot`. Цена 200₽/мес. Master-план `docs/plan-phase-3-4-5.md`, `docs/yookassa-setup-instruction.md`.

## 2026-05-25 — Личный кабинет: модель аккаунта + UX + триал/реферал + пароль (Фазы 0–2)

Старт коммерциализации через ЛК (`1cfb5ec`,`c0e2384`,`9d561ba`,`0b3f6a7`,`3647133`).
- **Фаза 0 (БД):** `users` +subscription/expires/trial/plan/referral/password; таблица `payments`; хелперы (`db_is_access_active`, `db_extend_subscription`, `db_start_trial`, …). `expires_at NULL = grandfathered`.
- **Фаза 2 (UX ЛК):** QR (qrcode[pil]), копирование, hero, экран «Мой аккаунт» (статус/срок/триал/реферал), вход по паролю (werkzeug). `TRIAL_DAYS=14`, `REFERRAL_REWARD_DAYS=14`.
- **Инструкции бота переписаны** (фидбэк Ани): единая модель «два варианта, у каждого своё приложение» + «куда что вставлять». Задача per-device (iPad/iPhone коллизия) — в ROADMAP. `SESSION_SUMMARY_2026-05-25.md`.

## 2026-05-24 — Учёт трафика lifetime + колонки Email/Всего + swap + диагностика скорости

- **Панель:** колонки Email (галочка верификации) + Всего (накопительный lifetime).
- **Reset-aware учёт:** таблица `traffic_accounting` + `db_accumulate_traffic` (детект сброса) + `scripts/traffic_accounting.py` (cron `*/5`).
- **Инфра:** swap 2 ГБ + `swappiness=10` на eu1.
- **Диагностика скорости:** сервер здоров; потолок ~100 Мбит/с (порт VPS). Клиентский замер (СПб): без VPN 278↓, AWG 84↓, VLESS 59↓ → узкое место путь RU→DE, **деньги не тратим**, AWG основной. `9246d7a`,`8e71b02`.

## 2026-05-21 (вечер) — Recovery-сайт полный передел + Error-103 fallback

- **`/recovery`:** удалены 3 legacy-секции по Telegram ID + 5 legacy endpoint'ов. Новый UX: email/OTP → 3 канала (Основной VPN ПК/iOS/Android / Мобильный резерв по оператору / MTProxy). Новые email-token эндпоинты (`awg-config-by-email`, `mobile-link-by-email`, `proxy-link-by-email`). Встроенный Error-103 fallback.
- **Бот:** `instruction_windows_short.txt` — блок про Error 103.
- Не сделано: персональные UUIDs для main REALITY (запарковано).

## 2026-05-21 — Yota/Мегафон при БС РЕШЕНО + critical fix AmneziaWG persistent peers

**✅ VLESS+REALITY на main Timeweb (SNI=cloud.mail.ru) работает на Мегафон/Yota при БС.** Подтверждено тестом друга на Yota (digitalocean.com режется → БС активны).
- **Архитектура:** whitelist Yota по IP-подсетям (Timeweb в whitelist) + SNI inspection; REALITY ClientHello SNI=cloud.mail.ru (whitelisted), dest=cloud.mail.ru:443 (fronting под Mail.ru Cloud). cloud.vk.com не подошёл (нестандартный TLS).
- **main Timeweb:** Xray VLESS+REALITY :443 (shortid=04d9b6c0), nginx :80 ACME, LE cert; WG UDP/51820 для 1 legacy. DNS grey-cloud. Бот: `VLESS_CDN_TLS_SHARE_URL`.
- **Critical fix:** после reboot Fornex 28/30 AWG-peers пропали — `awg-quick save` fail-silent в контейнере. Восстановлено по `peers.json`. **Persistent:** `/opt/amnezia-save-conf.sh` (`awg showconf` + ручной Address) вызывается из add/remove + cron `*/5`. **Не возвращать `awg-quick save`.**
- Закрыто (пробовали): WS-ext в YC API Gateway, XHTTP через API Gateway (клиент не коннектится), VLESS+WS+TLS на main (Yota режет не-whitelisted SNI). `SESSION_SUMMARY_2026-05-21.md`. Новые: `nginx-ru-vpnnkrns.conf.example`, `xray-main-reality.json.example`, `amnezia-save-conf.sh.example`.

## 2026-05-20 — Финальный тест CDN relay при активных БС

- YC VM IP `158.160.236.147` на Yota при БС — не подключается (IP не в whitelist). Yandex CDN WebSocket — поддержка YC: «сценарий не поддерживается». XHTTP через CDN POST невозможен.
- Следующий кандидат: Yandex API Gateway (`*.apigw.yandexcloud.net`).
- nginx на Fornex роутит порт 80 по `Host`/`Upgrade`: WS → Xray:8080, XHTTP → Xray:8081.

## 2026-05-19 — Yandex CDN relay (XHTTP) + выбор оператора в боте

- Xray на Fornex порт 80: WS → XHTTP (SplitHTTP, путь `/vpn`). `cdn.vpnnkrns.ru` → Fornex:80, CDN пробрасывает к origin. Новая `VLESS_CDN_SHARE_URL`.
- Бот: «📱 Мобильный VPN» → выбор оператора (Билайн/Мегафон-Yota/МТС/Т-Мобайл/Т2). Мегафон/Yota → CDN, остальные → REALITY. Тест при БС ждёт события.

## 2026-05-16 — Тест VLESS+REALITY при белых списках

- VLESS+REALITY xHTTP (YC) на Yota/Мегафон при БС — **не работает**; AmneziaWG при БС нигде (UDP). **T2 (Tele2) — работает** (нет жёстких whitelist).
- Вывод: при БС для Yota/Мегафон нужен протокол поверх HTTPS (привело к решению 21.05).

## 2026-05-15 — Авторизация веб-панели + трекинг прокси

- Закрыта панель `/` HTML login-формой (Flask session; admin / `ADMIN_SECRET`). `/recovery` публичен. Убран Basic Auth. `web/templates/login.html`.
- Колонка «Прокси» (`proxy_requested_at` + `db_update_proxy_requested_at`).

## 2026-05-14 — Аудит безопасности веб-панели

- `/api/users` → требует `ADMIN_SECRET` (64-char hex). Legacy recovery endpoints → `RECOVERY_SECRET`. `/api/traffic` — убран telegram_id из публичного ответа. `bot/config.py` +`admin_secret`/`recovery_secret`. Приватные ключи не в БД.

## 2026-05-14 — IPv6 в AllowedIPs (защита от IPv6 leak)

- Трафик к IPv6 шёл мимо VPN → добавлен `::/0` в AllowedIPs для ПК/iOS. `/opt/amnezia-add-client.sh` + `wireguard_peers.py` + примеры. Android не затронут (срезает `::/0`, Error 1000). Только новые/regen.

## 2026-05-13 — Platform-based доставка конфига (vpn:// Android, файл iOS/PC)

- «📲 Получить VPN» → выбор платформы → доставка. Android: `vpn://` deep link (`generate_vpn_url`: qCompress zlib + base64url). iOS/ПК: `.conf`. `android_safe=True` для Android.

## 2026-05-13 — Задокументирован Trojan-сетап (проверенная схема, не нами)

- Trojan поверх TLS (неотличим от HTTPS), клиент ShadowRocket, VPS NL. UDP+IPv6 off (IPv6-leak — реальный вектор блокировки). Вывод: учитывать IPv6-leak. Не внедряем пока хватает REALITY.

## 2026-05-11 — Защита сервера Fornex от брутфорса и UDP-флуда

- CPU 98% из-за SSH-брутфорса → fail2ban установлен; SSH по паролю отключён (настройка в `/etc/ssh/sshd_config.d/50-cloud-init.conf`). Rate-limit UDP 39580 (iptables, persistent). sysstat. Ключ `id_ed25519_fornex`, алиас `ssh fornex`.

## 2026-05-11 — Багфикс: eu2 → eu1 при /regen и /get_config

- Юзеры с `preferred_server_id="eu2"` падали (бот шёл в неработающий wg0). Фикс: `bot/storage.py` — `eu2` в legacy-слоты, нормализуемые в `eu1`. Патч через sed на Fornex.

## 2026-05-09 — xHTTP packet-up на YC VM (обход ТСПУ-заморозки)

- ТСПУ замораживает TCP+REALITY после 15–20 КБ. Транспорт YC VM `TCP+vision` → `xHTTP packet-up` (path `/download`, без `flow`). `VLESS_REALITY_SHARE_URL` обновлён. `docs/yandex-cloud-reality-setup.md`.

## 2026-05-08 — Анализ конкурентов, удаление eu2, редизайн панели мониторинга

- **Конкуренты:** VlexNet, Barin VPN (199₽/3устр), SPACE Connect (Mini App, split tunneling). Все key-based; наш VLESS+REALITY через YC — преимущество на LTE. `docs/competitors-analysis.md` (7 конкурентов).
- **Удаление eu2** из бота (storage/wireguard_peers/main; кнопка «Выбрать сервер» убрана).
- **Редизайн панели:** root cause трафика — self-SSH; `_get_awg_dump_eu1()` → `docker exec amnezia-awg2 awg show awg0 dump`. Тёмная тема, `/api/traffic` по юзерам, автообновление 60с.

## 2026-05-07 — Рефакторинг UX бота + git setup

- VLESS-ссылка в `<code>` (чистое копирование). Удалены команды `/get_config_android`,`/regen_android`,`/my_config`,`/help`. Inline-меню /start (7 кнопок + ⚙️ Администратор). Первый коммит в `nikkronos/vpnservice` (54 файла). `SESSION_SUMMARY_2026-05-07.md`.

## 2026-05-06 — Yandex Cloud VLESS+REALITY relay (резерв для LTE whitelist-режима)

- Timeweb тоже недоступен на LTE-whitelist. YC VM `vrprnt` (158.160.236.147, Ubuntu 24.04), Xray VLESS+REALITY :443 (SNI `www.yandex.ru` — позже сменён). `/mobile_vpn` отдаёт YC-Reality. Тест Wi-Fi ✅, LTE-whitelist ждёт. `docs/yandex-cloud-reality-setup.md`.

## 2026-05-05 — Cloudflare CDN стек для мобильного LTE (настроен, whitelist-блок)

- CF аккаунт + домен `vpnnkrns.ru`; `sub.vpnnkrns.ru` → Fornex, Proxied, WS on. Xray на Fornex → VLESS+WS (port 80, no TLS). **Итог:** LTE-whitelist блокирует даже CF IP → отложено; CDN-стек как резерв для обычных условий. `SESSION_SUMMARY_2026-05-05.md`.

## 2026-04-13 — Документирован предпрод-план коммерциализации + синхронизация с AI-идеями

- `docs/archive/commercialization-prelaunch-plan-2026-04.md`: as-is архитектура, prelaunch-риски, минимум до запуска (Postgres, prod web stack, мониторинг, бэкапы, webhook), план A/B/C/D. Брать сейчас: Postgres, agent-автоматизация; отложить: рекламные Meta-агенты. (Файл архивирован 06-13.)

## 2026-04-12 — Исправление доступа к мониторингу и recovery (UFW + обновление устаревших ссылок)

- После переноса `vpn-web` на Fornex порт 5001 не был открыт → `ufw allow 5001/tcp`. Обновлены старые ссылки `81.200.146.32:5001` → Fornex в env-примере, mtproxy-rotation, blocking-bypass, deployment.

## 2026-04-11 — Документация и код: пост-миграция бота на Fornex (Россия/EU/SSH)

- На Fornex не было `wireguard-tools` (`/get_config` Россия падал) + не было ключа `id_ed25519_eu1` (`/regen` EU падал). Операции: `apt install wireguard-tools`, ssh-keygen + authorized_keys на EU. `deployment.md` — чеклист хоста бота; `wireguard_peers.py` — понятные ошибки. `SESSION_SUMMARY_2026-04-11.md`.

## 2026-04-11 — `vpn-web` и `/recovery` на Fornex; отключение панели на Timeweb

- Мониторинг + `/recovery` переехали на Fornex (`vpn-web.service`, PORT=5001); `VPN_RECOVERY_URL` обновлён; трафик main через `WG_SSH_*` (ключ `id_ed25519_main`). Timeweb-панель `disable --now`.

## 2026-04-10 — MTProxy Fake TLS на Fornex (порт 8444), починка /proxy_rotate

- После переноса бота Docker не мог занять хост 443 (занят Xray REALITY) → MTProxy внешний порт **8444**. `bot/config.py` `environment_for_mtproxy_rotate()` (проброс `MTPROXY_*` в subprocess). Контейнер `mtproxy-faketls` (8444→443); удалён старый `mtproto-proxy`. `docs/archive/vpn-web-migration-fornex-plan.md`.

## 2026-04-02 — Логические слоты rus1 / rus2 / eu1 / eu2 + recovery EU1+EU2 + ссылка прокси без рестарта

- 4 именованных слота; ключи пиров `{tid}:{server_id}`; rus1/rus2→main, eu1/eu2→eu1 (`canonical_env_server_id`). `/recovery` — 2 блока VPN; `GET /api/recovery/proxy-link` отдаёт `tg://` без рестарта Docker. Юнит бота = `vpn-bot.service`.

## 2026-04-02 (дополнение) — Spec-08: без нового VPS

- Решение владельца: второй VPS не оплачивается. spec-08 переписана: сценарий B (только main+eu1); сценарий A (RU2/EU2) — опция при бюджете.

## 2026-04-02 — Спека вторая нода (RU2/EU2), документ про GearUp/мульти-вход

- `docs/specs/spec-08-multi-node-redundancy-ru2-eu2.md` (план EU2/RU2 → потом «без второго VPS»). `third-party-vpn-boosters-vs-multi-entry.md` (GearUp-подобные). Обновлены blocking-bypass, ROADMAP.

## 2026-03-30 — Сводная документация MTProxy + обновление README

- `docs/telegram-mtproxy-operators-guide.md` — единое руководство (`/proxy`, `/proxy_rotate`, recovery, env, деплой через venv-pip).

## 2026-03-30 — Деплой: явный путь к pip в venv (PEP 668 на Ubuntu 24+)

- `deployment.md`: зависимости через `/opt/vpnservice/venv/bin/pip` (не системный). Согласованы spec-06, web/README.

## 2026-03-30 — Ротация MTProxy: /proxy_rotate, override-файл, документация

- `get_effective_mtproto_proxy_link()` (приоритет `data/mtproto_proxy_link.txt` над env); `/proxy_rotate` (owner) запускает `MTPROXY_ROTATE_SCRIPT`, пишет override. `.gitignore` + `docs/mtproxy-proxy-rotation.md` + `mtproxy-faketls-rotate.sh.example`.

## 2026-03-30 — README: MTProxy Fake TLS vs «голый» MTProto; резюме сессии

- Уточнены таблицы «что работает/нет»: голый MTProto на eu1 — блок по сигнатуре; MTProxy Fake TLS на main — рабочий путь. Правило №5 приведено к `telegram-unblock-algorithm.md`.

## 2026-03-26 — LTE blackhole, MVP/юнит-экономика (документация)

- `blocking-bypass-strategy.md` — выводы по LTE (недоступность HTTP/HTTPS до main/eu1 IP при рабочем Wi-Fi). `docs/mvp-unit-economics-and-plan.md` — юнит-экономика, риски, фазы MVP.

## 2026-03-25 — Веб recovery: Telegram/VPN + ссылка в боте

- Отдельный маршрут `/recovery` (вынесен с `/`); кнопки «Восстановить Telegram/VPN», вход по Telegram ID, Android-safe. Backend `telegram-proxy`/`vpn`. Ссылка recovery в `/start`.

## 2026-03-23 (продолжение) — Документация попытки LTE + eu1

- `docs/archive/mobile-lte-eu1-xray-reality-attempt-2026-03.md`: Xray REALITY на eu1, Streisand, вывод о недоступности IP `185.21.8.91` с LTE; план — REALITY на Timeweb / другой ASN.

## 2026-03-23 — Мобильный резерв: VLESS+REALITY и команда /mobile_vpn

- Спека `spec-07-mobile-fallback-vless-reality.md`; деплой `docs/archive/xray-vless-reality-eu1-deploy.md`. `bot/config.py` чтение `VLESS_REALITY_SHARE_URL`; команда `/mobile_vpn`. Тексты + backup-restore (бэкап Xray).

## 2026-03-15 — Фиксация сторонних альтернатив для Telegram

- `docs/telegram-proxy-alternatives.md` — список альтернатив (локальный SOCKS5 `tg-ws-proxy`, платные SOCKS5), помечен «не наш стек, без гарантий».

## 2026-03-14 — Диагностика тайм-аута AmneziaWG, команда /broadcast, документация

- Тайм-аут на телефоне (конфиг не совпадал с сервером) → решение /regen. Команда `/broadcast` (owner, рассылка + отчёт). `troubleshooting-amneziawg-connection-timeout.md`. Рассылка 11/1.

## 2026-03-07 — Telegram-прокси с Fake TLS, алгоритм разблокировки, оценка провайдера

- Созданы `provider-choice-evaluation.md` (Fornex vs FirstVDS), `telegram-unblock-algorithm.md`, `mtproxy-faketls-deploy.md`. Развёрнут на Timeweb контейнер mtproxy-faketls (маскировка 1c.ru), проверен в Москве.

## 2026-02-26 — Автоматизация выдачи конфигов AmneziaWG + удаление /proxy

- **Автоматизация eu1:** AmneziaWG в Docker `amnezia-awg2`, порт **39580/UDP**, подсеть **10.8.1.0/24**, server pubkey `pevLcgguoIMDWnbtPgQ3ZsSak73fylprex54Tv65ZyI=`. Скрипты `/opt/amnezia-add-client.sh`/`-remove-client.sh`, SSH `id_ed25519_eu1`, env `WG_EU1_*`. Старые peers (10.1.0.x) очищены. Бот выдаёт рабочие конфиги.
- **Очистка:** удалена `/proxy` (блок MTProto), Shadowsocks/MTProto убраны с панели.

## 2026-02-23 — Восстановление eu1, эксперименты Remnawave/Xray/MTProto (неудачны)

- Переустановка eu1 (Ubuntu 24.04). Remnawave (`Invalid SECRET_KEY` → удалён). Возврат AmneziaWG (ПК/iOS работают, конфиги вручную). MTProto :443/:8443 не коннектится (блок по сигнатуре). Xray VLESS/TCP без TLS не работает (DPI/маршрутизация). Вывод: Telegram через VPN; VLESS только с TLS/REALITY.

## 2026-02-22 — Чистый сброс eu1 (Fornex): AmneziaWG, проверка на ПК и iOS

- Сброс eu1 (бэкап `/root/eu1-backup-20260222`), AmneziaWG через приложение, ПК/iOS работают. Бот-выдача AmneziaWG-конфигов (Docker, скрипты `-docker.sh`, извлечение обфускации Jc/Jmin/.../H1–H4). На телефоне с конфигом бота handshake есть, трафик не грузит (открытый вопрос на тот момент).

## 2026-02-21 — Веб-панель: деплой, этапы 2–3, подсказки

- Панель на Timeweb :5001. Блоки «Сервисы» (ping/TCP), «Пользователи», «Трафик» (`wg show dump` локально main / SSH eu1, обновление 30с). Подсказки под блоками.

## 2026-02-21 — Бот: Европа = AmneziaWG (инструкция + опция выдачи конфига через скрипт)

- Для «Европа» бот выдаёт AmneziaWG (инструкция или скрипт по SSH). Спека `spec-05-bot-amneziawg-eu1.md`, скрипты `docs/scripts/`. Функции `create/regenerate_amneziawg_peer_*` в `wireguard_peers.py`.

## 2026-02-21 — AmneziaWG на eu1 работает, iOS через «Поделиться», следующие задачи

- AmneziaWG на eu1 работает (ПК + iPhone/iPad; iOS импорт через «Поделиться»). `client-instructions-amneziawg.md`. Решения: бэкап в Git (приватный repo), второй VPS отложен.

## 2026-02-21 — Стратегия обхода блокировок РКН, выбор AmneziaWG, план развёртывания

- `blocking-bypass-strategy.md` (варианты A/B/C/D). **Выбран A (AmneziaWG)** — один клиент AmneziaVPN на ПК/iOS, при блокировке РКН — добавить Xray в том же приложении. `docs/archive/amneziawg-deploy-instruction.md`, `SESSION_SUMMARY_2026-02-21.md`.

## 2026-02-20 — Улучшение UX и решение проблем тестирования

- UX бота (объяснения режимов, `/help`). Troubleshooting-доки (multiple-devices, ios-devices, telegram-vpn-conflict). Спека `spec-04-unified-profile` (архив). Базовая веб-панель Flask. `vless-alternative.md` (архив).

## 2026-02-18 — Настройка WireGuard + Shadowsocks и клиентов

- На Fornex: `shadowsocks-libev` + `ss-redir` (`ss-wg.service`, 127.0.0.1:1081); WireGuard wg0 peers (10.1.0.4–7), iptables-редирект TCP 80/443 на ss-redir (VPN+GPT-модель). Клиенты владельца+друзей (ПК/iPhone/iPad). _(Архитектура устарела: ныне AmneziaWG, без Shadowsocks.)_

## 2026-02-18 — Установка Telegram MTProto Proxy

- Docker `telegrammessenger/proxy` на Fornex :443, `tg://proxy` ссылка. Спека `spec-02-telegram-mtproto-proxy.md`, `docs/archive/mtproto-setup.md`. _(Голый MTProto позже задавлен по сигнатуре → Fake TLS.)_

## 2026-02-18 — Интеграция бота: инструкции, MTProto-ссылка, VPN+GPT

- `/instruction` (тексты из `bot-instruction-texts/`), `/proxy` (`MTPROTO_PROXY_LINK`). Опция VPN+GPT для eu1 (пул 10.1.0.8–254, `add-ss-redirect.sh`, `profile_type`). Спека `spec-03-bot-integration-instructions.md`.

## 2026-02-15 — Отладка eu1: WG UDP из РФ к Fornex не работает

- Диагностика wg0 на Fornex: сервер настроен корректно (iptables/rp_filter/MTU), но **WireGuard UDP :51820 из России к Fornex не работает** (блокировка/потеря на маршруте РФ↔Fornex). Fornex подтвердил «с нашей стороны ограничений нет». Подготовлены обходные пути (`eu1-workarounds-fornex.md`). → привело к выбору AmneziaWG.

## 2026-02-14 — Вторая нода eu1 (Fornex, Германия)

- VPS Cloud NVMe 1 (Германия), WireGuard wg0 (10.1.0.0/24, :51820). SSH-ключ бота (Timeweb→eu1), env `WG_EU1_*`. `/server` — 2 опции. Имена конфигов → `vpn_<tid>_<server_id>.conf`.

## 2026-02-13 — Лимиты трафика + рабочая /regen

- Timeweb: лимитов по трафику нет. `/regen` доведена (remove+recreate с тем же IP, фикс импорта `find_peer_by_telegram_id`). Repo временно публичный для деплоя (вернуть в приватный, проверить отсутствие секретов).

## 2026-02-11 — Self-service через Telegram-бота

- Модель данных `users.json`/`peers.json`; `bot/storage.py` (dataclass `Peer`), `bot/wireguard_peers.py` (ключи/IP/`wg set`/.conf), `bot/main.py` (`/start`,`/get_config`,`/add_user`,`/users`). env `WG_*`. Друг успешно подключился.

## 2026-02-09 — Базовая структура + первая WireGuard-нода

- Старт проекта: docs-структура, Git-repo `nikkronos/vpnservice`. Первая WireGuard-нода на Timeweb (81.200.146.32, wg0 :51820), `client1.conf`. Тест Windows (~91↓/88↑ Мбит) + iOS (QR) — работают. `docs/deployment.md`.
