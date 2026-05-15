# CLAUDE.md — правила для агентов (читается автоматически)

## Старт сессии

Перед любой работой выполни:
```bash
git status
git log --oneline -3
```
Если есть незакоммиченные изменения — разберись с ними прежде чем писать новый код.

## Деплой

Изменения на сервер доставляются через **SCP**, не через git pull:
```bash
scp -i "$HOME/.ssh/id_ed25519_fornex" <файл> root@185.21.8.91:/opt/vpnservice/...
ssh -i "$HOME/.ssh/id_ed25519_fornex" root@185.21.8.91 "systemctl restart vpn-bot.service"
```
Сервисы: `vpn-bot.service` (бот), `vpn-web.service` (веб-панель).

## Git — обязательное правило

После каждого изменения кода:
1. `git add <конкретные файлы>`
2. `git commit -m "..."`
3. `git push`

**Не пропускай push.** Следующий агент начнёт с `git pull` и столкнётся с конфликтом, если изменения остались только локально.

## Завершение сессии

1. Убедись, что все изменения закоммичены и запушены (`git status` должен быть чистым)
2. Обнови `ROADMAP_VPN.md` (отметь выполненные задачи)
3. Создай `docs/sessions/SESSION_SUMMARY_YYYY-MM-DD.md`

## Ключевые файлы

- `ROADMAP_VPN.md` — текущие задачи
- `DONE_LIST_VPN.md` — что сделано
- `docs/agent-onboarding.md` — полный онбординг
- `docs/architecture.md` — архитектура
- `bot/main.py`, `bot/database.py`, `web/app.py` — основной код
