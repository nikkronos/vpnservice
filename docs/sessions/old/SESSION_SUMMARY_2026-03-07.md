# Резюме сессии 2026-03-07 — Telegram-прокси с Fake TLS, документация

## Контекст работы

- Изучены Main_docs (QUICK_START_AGENT, AGENT_PROMPTS, RULES_CURSOR); проект VPN (Projects/VPN).
- Задачи: зафиксировать ответы на вопросы из сторонних чатов (relay, FirstVDS); оценить выбор Fornex; придумать алгоритм сохранения доступа к Telegram при блокировках/троттлинге; развернуть рабочий прокси для себя и знакомого в Москве.

## Выполненные задачи

### 1. Уточнения и фиксации

- **Relay-сервер:** в README_FOR_NEXT_AGENT.md добавлен блок «Уточнения» — в проекте **нет relay-сервера**, только ноды VPN (main, eu1) и бот/панель на Timeweb.
- **Сторонний прокси 79.132.138.66:9443** — испробован пользователем, не работает; зафиксирован в telegram-unblock-algorithm.md для истории.

### 2. Документация

- **docs/provider-choice-evaluation.md** — оценка выбора Fornex, сравнение с FirstVDS (тарифы, канал, когда FirstVDS имеет смысл). Вывод: Fornex для eu1 выбран корректно в рамках текущей задачи.
- **docs/telegram-unblock-algorithm.md** — алгоритм разблокировки Telegram: уровни (MTProxy с Fake TLS → резерв VPN → смена провайдера), почему старый прокси не работал, чеклист. Формулировки в бот не вносились.
- **docs/mtproxy-faketls-deploy.md** — пошаговое развёртывание MTProxy с Fake TLS (nineseconds/mtg:2): шаг 0 — установка Docker, проверка порта 443, генерация секрета, запуск контейнера, сбор ссылки. Команды под копипаст.
- Ссылки на новые документы добавлены в README_FOR_NEXT_AGENT.md и blocking-bypass-strategy.md.

### 3. Развёртывание и проверка MTProxy с Fake TLS

- Пользователь на Timeweb (81.200.146.32) установил Docker (`apt install docker.io`), развернул контейнер `mtproxy-faketls` на порту 443 с секретом (маскировка под 1c.ru).
- Шаг установки Docker добавлен в mtproxy-faketls-deploy.md (Шаг 0).
- **Проверено:** прокси работает у владельца (скорость нормальная, пинг ~95 мс) и у знакомого в Москве. Зафиксировано в telegram-unblock-algorithm.md и mtproxy-faketls-deploy.md.

## Важные замечания для следующего агента

- Telegram-прокси для обхода троттлинга/блокировок: **свой MTProxy с Fake TLS на Timeweb (81.200.146.32:443)**. Ссылку не коммитить; раздавать только доверенным.
- При блокировке прокси: сменить домен маскировки (новый секрет) или перенести контейнер на другой VPS по docs/mtproxy-faketls-deploy.md.
- Путь к проекту VPN: `Projects/VPN/` (при необходимости пользователь даёт прямую ссылку).

## Изменённые/созданные файлы

- README_FOR_NEXT_AGENT.md — блок «Уточнения», ссылки на новые docs
- docs/provider-choice-evaluation.md — новый
- docs/telegram-unblock-algorithm.md — новый, затем правки (прокси 79.132.138.66, проверка в Москве)
- docs/mtproxy-faketls-deploy.md — новый, затем Шаг 0 (Docker), проверка
- docs/blocking-bypass-strategy.md — ссылка на новые документы
