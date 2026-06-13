# CLEANUP AUDIT — порядок в документах (Фаза 0)

> ВРЕМЕННЫЙ рабочий файл ветки `docs/cleanup-2026-06`. Удаляется перед merge.
> Создан 2026-06-13. Гейт: перемещений нет, пока владелец не утвердит вердикты.

## Принцип границ (source of truth) — фиксируется в CLAUDE.md + docs/README.md

| Файл | Только это | Не должно быть |
|---|---|---|
| CLAUDE.md | как устроено и как работать СЕЙЧАС | история, списки задач |
| ROADMAP_VPN.md | только открытое/будущее | «сделано», нарративы |
| DONE_LIST_VPN.md | хронология выполненного | открытые задачи |
| docs/ | глубокий референс | дубли оперативки |
| docs/sessions/ | журнал сессий | — |
| docs/archive/ | устаревшее (для истории) | актуальное |

**Правило свежести (карантин):** не архивировать документ, если он редактировался
в последние **7 дней** (по `git log -1 --format=%cs`, НЕ по mtime — OneDrive
сдвигает mtime). Свежий рабочий контекст остаётся в активной зоне; в архив — только
после ≥7 дней без правок. Кандидаты под карантином уезжают в архив следующим
проходом, когда «остынут». Это правило фиксируется в `docs/README.md` + `CLAUDE.md`.

## ROOT (переписать, не двигать)
- **CLAUDE.md** (335 стр) — slim: убрать историч. нарративы → ссылки на DONE/session; сохранить ВСЕ правила #0–#13 + pre-deploy checklist дословно; починить докдрифт (покрытие, 4 узла, таблица «Документация»).
- **ROADMAP_VPN.md** (650 стр) — вынести все `[x] DONE` в DONE_LIST (сверив наличие), оставить открытое по приоритетам. Цель ~150–200 стр.
- **DONE_LIST_VPN.md** (1228 стр) — сжать записи к единому формату + оглавление, newest-first, 1 файл. Сверка: число записей до/после.

## docs/ top-level — вердикты (34 файла)

### DEFER — карантин свежести (трогали ≤7 дн, архивировать следующим проходом)
| Файл | git-дата | Когда можно в архив |
|---|---|---|
| plan-phase2B-per-device-impl.md | 2026-06-10 | после 2026-06-17 (Фаза 2B done, но контекст свежий) |

### ARCHIVE (прочитано, подтверждено — выполнено/устарело, >7 дн) → git mv в archive/
| Файл | Причина |
|---|---|
| migration-to-vpnkronos-plan.md | переезд done 05-28 (runbook) |
| commercialization-prelaunch-plan-2026-04.md | апрель; as-is устарел (eu2/rus2/SS); вытеснен ROADMAP + plan-phase-3-4-5 + mvp-unit-economics. **Обновить ссылку в ROADMAP «Ссылки»** |
| yandex-api-gateway-plan.md | «не реализован»; вытеснен Яндекс-фронтом (yc/yc2 socat, 06-10) |
| profile-names.md | устар. архитектура (Shadowsocks/friend-* нейминг) |
| telegram-unblock-algorithm.md | историч. стратегия; канон = telegram-mtproxy-operators-guide |
| amneziawg-deploy-instruction.md | Feb; вытеснен Docker-сетапом + eu1-setup-and-troubleshooting |
| amneziawg-eu1-discovery.md | Feb; одноразовый discovery |
| amneziawg-bot-automation-setup.md | Feb; устар. инфра (бот на Timeweb, порт 48100) |

### ARCHIVE (specs)
| Файл | Причина |
|---|---|
| specs/spec-04-unified-profile-all-services.md | старая SS-архитектура (10.1.0.x); импл уже в archive/spec-04-implementation-*. Свести оба в archive/ |

### KEEP + правка точности (НЕ архив, есть живой контент + дрейф)
| Файл | Дрейф к фиксу |
|---|---|
| eu1-vless-reality-setup.md | «Happ/Streisand удалены, не рекомендовать» — противоречит текущему боту (Happ = главный) |
| provider-choice-evaluation.md | тариф «Cloud NVMe 1, 1 core/1GB» → сейчас NVMe 2, 2/2 |
| risks-and-mitigations.md | статусы R1/R2 устарели (failover через подписку уже есть) |
| telegram-proxy-alternatives.md | ссылка на archived step-by-step-plan-bypass.md |

### KEEP (актуальный референс, без изменений)
backup-restore, blocking-bypass-strategy, competitors-analysis, deployment,
eu1-setup-and-troubleshooting, mvp-unit-economics-and-plan, rkn-notification-guide,
telegram-mtproxy-operators-guide, mtproxy-faketls-deploy, mtproxy-proxy-rotation,
troubleshooting-{ios,multiple-devices,telegram-vpn-conflict,amneziawg-connection-timeout},
client-instructions-amneziawg, plan-phase-3-4-5 (master), plan-phase2-keystone-architecture,
plan-blocking-antifraud-traffic-tariffs, yookassa-setup-instruction, yandex-cloud-reality-setup,
security.

### MERGE (опционально, низкий приоритет)
- eu1-vless-reality-setup.md + yandex-cloud-reality-setup.md → возможно один «vless-reality-nodes.md» (по узлам). По умолчанию KEEP оба + фикс точности.

## docs/specs/ — KEEP (design provenance): spec-05, spec-07, spec-08 (у spec-08 ru2/eu2 частично устар. — пометка).

## docs/sessions/ — LOW PRIORITY: апрель + до ~05-19 → sessions/old/ (уже в подпапке, не корневой шум). Сделать в конце, обновив ссылки.

## НЕ трогаю
Код (bot/, web/, scripts/), docs/scripts/, docs/bot-instruction-texts/ (живые тексты),
env/data/секреты, docs/archive/ (только пополняю).

## Итог по объёму
docs/ top-level: 34 → ~21 KEEP (9 в архив + 4 spec/прочее). + docs/README.md индекс.
