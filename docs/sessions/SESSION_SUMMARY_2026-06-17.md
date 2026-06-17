# SESSION SUMMARY — 2026-06-17

> Три задачи дня: iplimit Stage 2 (калибровка), journald-спам, external uptime
> monitor. Предыдущая (06-15): eu1 → per-user-only — `SESSION_SUMMARY_2026-06-15.md`.

## TL;DR
- ✅ **iplimit Stage 2 — откалибровано: шеринга НЕТ.** Метрика починена (distinct по /24, убран двойной счёт). Enforcement не вводим (нет цели). `3ba6240`.
- ✅ **journald-спам устранён.** Xray access → файл + `loglevel warning` на 4 серверах; watcher читает файл; logrotate. eu1 journald ~700/мин → ~1/мин. `b826028`.
- ✅ **External uptime monitor** — UptimeRobot HTTP-монитор на `supportkronos.online:8443` + email-алерт (free). Telegram у UptimeRobot платный; Healthchecks (free TG) предложен — **владелец отказался, текущее устраивает**. Задача закрыта.

## iplimit (A) — калибровка
- Данные недели Stage 1: в окне 15 мин **макс 2 сети /24** на юзера. «Выбросы» (313482114: 5 сырых IP) = мобильный 4G-churn (РФ-пулы 91.78/31.173, тот же /24), НЕ шеринг.
- Фикс `ip_usage_watcher.py`: `norm_ip` срезает `tcp:`/`udp:`-префикс (regex ловил `from tcp:IP` → калечил в `tcp:IP::/64` → двойной счёт; +вычищено 126 мусорных строк); `report`/порог считают distinct **/24** (IPv4) / /64 (IPv6).
- **Вывод:** enforcement не оправдан (нет шеринга; наивный distinct-IP штрафовал бы честных мобильных). Observe-only, порог-алерт ≥4 сетей/15м (молчит). Привязать к тарифам (`device_limit`→порог) позже.

## journald (B) — access-лог в файл
- eu1/main/yc/yc2: `log.access → /var/log/xray/access.log` + `loglevel: warning` (бэкап→`xray -test`→restart; jump-хосты — base64-helper). Пилот eu1 подтвердил: access-лог пишется и при warning.
- Watcher: чтение файла вместо `journalctl`; окно — host-local `date` (TZ: **main=MSK**, прочие UTC) + строковое сравнение в awk (mawk-совместимо, без mktime).
- logrotate `/etc/logrotate.d/xray` на 4 (daily/maxsize 100M/rotate 3/copytruncate).
- Проверено: eu1 journald 1/мин; watcher пишет в `ip_usage` из файлов (yc/yc2 события идут).

## uptime (C)
- UptimeRobot: HTTP-монитор Up 100%, email-алерт (free). Публичная status-page создалась автоматом — владельцу указано, что можно удалить/запаролить (маскировка). TG/Healthchecks отклонены как не нужное.

## Коммиты (main)
`3ba6240` (iplimit метрика), `b826028` (journald access→файл), `2a82cc1` (доки). Серверы: Xray-конфиги (бэкапы `*.bak.logfile.*`), logrotate ×4, `ip_usage` вычищена от мусора.

## ▶ Следующий заход
ROADMAP актуален. Ближайшее: сбор `drop_reason`/`use_case` из Sheets (~06-20); рефакторинг кода (после 23.06). P1: модель аккаунта (сайт↔Telegram), «Подключить VPN» дефолтным путём. БС-тесты у 4 юзеров (2 Мегафон/1 Yota/1 Волна) — по событию.

---

# SESSION 2 (День-2, 2026-06-17) — План Б (Фаза A) + ревизия трат серверов

## TL;DR
- ✅ **План Б Фаза A:** runbook реакции на удар РКН (`docs/plan-b-rkn-response-runbook.md`) + универсальный bootstrap релей-узла (`scripts/bootstrap-relay-node.sh`, 0 ₽ простоя) + **запасной SNI `ya.ru` вётнут вживую на T2**. Коммиты `ff3dc9d`/`c229917`/`ce67fb5`.
- 💰 **Ревизия трат:** burn ~4125 ₽/мес, Яндекс = 66%. **Клифф: грант Яндекса до 05.07** (баланс 0₽ → риск суспенда yc/yc2). Решение владельца: Яндекс оставить полностью → пополнить до 05.07.
- 🧹 Timeweb `85.193.89.92` («Polite») — мёртвый IP, НЕ сам сервер (= живой main). Убрать IP после сентября (−180₽).

## План Б
- Рамка: резильентность = продукт/ров, но связка «инфра→сарафан» имеет разрыв (мало «ртов»); узкое место — выручка vs стоимость, не инфра. Сделано lean (0 ₽ простоя — bootstrap вместо запасного VPS).
- Bootstrap = клон yc: REALITY xhttp :443 → eu1 vless-ws релей-кредом `359e23cc` (eu1 НЕ трогаем). Проверен `bash -n` + JSON.
- Находка: multi-node подписка (`_build_subscription_links`) уже даёт мгновенный failover при падении одного узла.
- Вёттинг SNI: серверная `openssl -tls1_3 -alpn h2` от yc (ya.ru/vk.com/tbank — РФ-резидентные, гео-консистентны) → живой T2-тест ya.ru (временный inbound yc2:2096 → подключился, выход eu1 → снят).

## Ревизия трат (по биллинг-скринам владельца)
- Fornex eu1 936 + Яндекс yc 1391 + yc2 1340 + Timeweb 458. 26 active / ~13 в день / ~10 платящих / MRR ~1500–2000 → после гранта структурный убыток.
- Решения владельца: Яндекс не дробить и не мигрировать сейчас (оставить полностью); Polite-IP чистить после сентября.

## Память (новое)
- `reference_owner_test_rig` — тест-риг владельца (T2/iPhone/Wi-Fi/2 TG) + что покрывает/нет.
- `project_vpn_server_costs_cliff` — burn по узлам + Яндекс-клифф 05.07.

## ▶ Следующий заход (после Дня-2)
ROADMAP обновлён (План Б → done; срочная метка Яндекс-клифф 05.07). Кандидаты: P1 «модель аккаунта сайт↔Telegram»; сбор drop_reason/use_case из Sheets (~06-20); рефакторинг (после 23.06).
