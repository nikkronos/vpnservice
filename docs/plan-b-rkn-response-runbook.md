# План Б — реакция на удар РКН по IP/SNI (runbook)

> Оперативная инструкция «жалоба → диагноз → рычаг → команды». Создан 2026-06-17.
> Цель — реагировать за минуты, не импровизируя. Связано: `blocking-bypass-strategy.md`
> (стратегия), `CLAUDE.md` (инфра + правила #0/#0.1), память `project_vpn_rkn_ip_block`.

## Что это покрывает — и что НЕ покрывает

**Покрывает:** удар типа волны 06-05 — РКН режет узел по **IP-репутации** или по **SNI**.
Признак: жалобы по конкретному узлу/оператору, при этом **AmneziaWG жив** (значит лёг
вход VLESS, а не сервер/сеть целиком).

**НЕ покрывает:** жёсткий **whitelist / режим при БС** (предпраздничный whitelist, Крым/
«Волна», Мегафон-whitelist). Там TCP до любого незнакомого IP не проходит — никакой свап
SNI/порта/узла не помогает (доказано 05-05). Это отдельные waiting-задачи roadmap; путь
только через relay на physically-whitelisted IP.

## Диагностика (30 секунд)

| Симптом | Диагноз | Рычаг |
|---|---|---|
| VLESS лёг, **AmneziaWG работает** | блок IP **или** SNI конкретного узла | → §Рычаги |
| Лёг конкретный **оператор**, у других ОК | блок IP/ASN на этом операторе | вывести IP из пула |
| Лёг **весь интернет** на LTE кроме госсервисов | whitelist-режим | ⛔ План Б бессилен |

**IP-блок vs SNI-блок** (тест с **выключенным VPN**, лучше на T2-мобайл — `reference_owner_test_rig`):
- TCP до `IP:443` **не встаёт** → блок по **IP** → свап SNI не спасёт, нужен новый IP/узел.
- TCP встаёт, но VLESS-хендшейк падает → блок по **SNI** → свап SNI чинит.

## Текущий пул `/sub` (что уже есть)

Подписка отдаёт **4 узла**; клиент (HAPP/Streisand/V2Box/Hiddify) держит их все и
**авто-failover мгновенный** при падении одного. `Profile-Update-Interval=12h` — только
для подхвата **нового/убранного** узла. Источник: `_build_subscription_links` в `web/app.py`.

| Узел | Метка | IP | SNI (REALITY) | inbound tag | env-attr | Операторы |
|---|---|---|---|---|---|---|
| yc | 🇪🇺 Европа | 158.160.236.147 | www.microsoft.com | vless-xhttp | `VLESS_REALITY_SHARE_URL` | T2/МТС/Билайн |
| yc2 | 🇪🇺 Европа-2 | 84.252.136.139 | www.microsoft.com | vless-xhttp | `VLESS_YC2_SHARE_URL` | резерв yc |
| eu1 | 🇩🇪 Германия | 185.21.8.91 | www.microsoft.com | (REALITY TCP) | `VLESS_EU1_SHARE_URL` | чистая сеть, скорость |
| main | 🇷🇺 Россия | 81.200.146.32 | cloud.mail.ru | vless-tcp | `VLESS_CDN_TLS_SHARE_URL` | Мегафон/Yota при БС |

⚠ **yc/yc2 — фронт-релеи в eu1** (правило #0), не прямые выходы. shared-UUID `359e23cc…`
(main) и `11dd653c…` (yc/yc2) — несущая инфра, **не фрод, не удалять**.

## Рычаги (по скорости реакции)

### 1. AmneziaWG как мост (0 действий, мгновенно)
Первое, что говорим затронутым юзерам: «включи AmneziaWG (ПК/Wi-Fi) — работает сейчас».
Покупает время на ремонт VLESS. AWG на eu1 не трогаем.

### 2. Свап SNI на узле (минуты, server-side, юзер ничего не делает)
Когда диагноз = **блок по SNI** (IP жив). Меняем `serverNames` + `dest` в REALITY-inbound.
Подписка авто-обновится (UUID не меняется). Кандидаты SNI — см. §Шорт-лист.

```bash
# Пример для yc (через fornex jump). Backup → правка → validate → restart.
ssh fornex "ssh yc 'sudo cp /usr/local/etc/xray/config.json /usr/local/etc/xray/config.json.bak.sni.\$(date +%s)'"
# Отредактировать inbound vless-xhttp: realitySettings.dest + serverNames на новый SNI
# (вручную или будущим helper-скриптом — Фаза A п.4).
ssh fornex "ssh yc 'sudo xray run -test -c /usr/local/etc/xray/config.json && sudo systemctl restart xray'"
ssh fornex "ssh yc 'systemctl is-active xray'"
```
> ⚠ Свап SNI на yc-узле требует, чтобы новый `dest` реально слушал TLS 1.3 на :443 и был
> доступен с самого yc. main использует `cloud.mail.ru` (РФ-резидентный) — менять осторожно.

### 3. Вывести забаненный IP из пула (минуты)
Когда узел не чинится (IP-блок) и надо убрать его из подписки, чтобы клиенты не висли на нём.
На **fornex** опустошить соответствующий env-attr → рестарт веб.

```bash
# Пример: вывести yc. Закомментировать/опустошить строку VLESS_REALITY_SHARE_URL.
ssh fornex "sed -i.bak 's/^VLESS_REALITY_SHARE_URL=.*/VLESS_REALITY_SHARE_URL=/' /opt/vpnservice/env_vars.txt"
ssh fornex "systemctl restart vpn-web.service && systemctl is-active vpn-web.service"
```
> Эффект: пустой attr → узел пропадает из `config_list`. Остальные 3 узла уже у клиента
> → деградации нет. Подхват «минус узел» у клиентов — до 12 ч (но failover уже работает).
> Вернуть — восстановить строку из `.bak` + рестарт.

### 4. Поднять новый узел на свежем IP/провайдере (<15 мин) + добавить в пул
Когда легло слишком много (≥2 из 3 не-RU узлов). **Bootstrap: `scripts/bootstrap-relay-node.sh`**
— разворачивает релей-клон yc (REALITY xhttp :443 → eu1 vless-ws) на любой свежей Ubuntu VPS:
```bash
scp scripts/bootstrap-relay-node.sh root@NEW_VPS:/tmp/
ssh root@NEW_VPS 'bash /tmp/bootstrap-relay-node.sh --sni www.microsoft.com'   # генерит ключи, валидирует, печатает данные для регистрации
```
Скрипт использует тот же релей-кред `359e23cc…`, что eu1 уже принимает → **eu1 трогать не нужно**.
Добавление узла в пул = правки в **3 местах** (скрипт печатает их в конце):
1. `scripts/sync_xray_users.py` → словарь `SERVERS` (ssh, inbound_tag, flow, shared_uuid, db_column, sudo).
2. `web/app.py` → `_build_subscription_links` `config_list` (+`_VLESS_SERVER_TO_ATTR` если новый server_id).
3. `/opt/vpnservice/env_vars.txt` → `VLESS_<NODE>_SHARE_URL=vless://...` (template-ссылка).
Затем `sync_xray_users.py --server <node>` зальёт per-user UUID. Деплой app.py — по `deployment.md` + pre-deploy checklist.

## SNI шорт-лист (кандидаты)

Требования: TLS 1.3, популярный, на момент проверки **не заблокирован**, желательно
РФ-резидентный (Яндекс-класс выживает по IP-репутации). **Вёттинг на T2-мобайл, VPN off.**

| Кандидат | dest | Статус вёттинга | Дата |
|---|---|---|---|
| _(текущий yc)_ www.microsoft.com | www.microsoft.com:443 | ✅ работает | 06-13 |
| _(текущий main)_ cloud.mail.ru | cloud.mail.ru:443 | ✅ работает | — |
| **ya.ru** (Яндекс, РФ; гео-консистентно с yc) | ya.ru:443 | ✅ TLS1.3+h2 от yc · ⬜ T2 | 06-17 |
| **vk.com** (VK, РФ) | vk.com:443 | ✅ TLS1.3+h2 от yc · ⬜ T2 | 06-17 |
| **www.tbank.ru** (Т-Банк, РФ) | www.tbank.ru:443 | ✅ TLS1.3+h2 от yc · ⬜ T2 | 06-17 |
| _резерв:_ ozon.ru / www.wildberries.ru / www.avito.ru | …:443 | ✅ TLS1.3+h2 от yc | 06-17 |
| ~~dzen.ru~~ | — | ❌ нет h2, не годится как dest | 06-17 |

> Серверная проверка (06-17, `openssl s_client -tls1_3 -alpn h2` от yc): кандидаты выше
> поддерживают TLS 1.3 + h2 и достижимы из Яндекс-облака = валидные REALITY-dest, РФ-резидентные
> (переживают РКН по IP, гео-консистентны с yc). Остался **живой T2-тест DPI-обхода** (см. ниже).

> Вёттинг: поднять кандидат на запасном/тестовом inbound → дать себе конфиг → T2, VPN off →
> проверить хендшейк + что `dest` не заблокирован. Заполнять таблицу по мере проверки.

## Чего НЕ делаем (Оккам + бюджет)
- ❌ Простаивающий запасной VPS — держим bootstrap-скрипт, не железо (0 ₽ простоя).
- ❌ MTProxy revival / охота за «удачными одиночными IP» — шум, не резильентность.
- ❌ Экзотические протоколы поверх рабочих REALITY + AmneziaWG.
- ❌ Не трогать прод вслепую: релеи yc/yc2→eu1 и shared-UUID — несущие (правило #0,
  `feedback_no_delete_runtime_blind`).
