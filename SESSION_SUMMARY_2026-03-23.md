# Резюме сессии 2026-03-23 — мобильный резерв VLESS+REALITY

## Контекст

Пользователь подтвердил: VPN/прокси не работают по мобильной сети на разных телефонах и операторах; по Wi‑Fi — работают. Полный VPN критичен; готовы к параллельному сложному стеку.

## Выполнено в репозитории (код и документация)

1. **Спецификация** `docs/specs/spec-07-mobile-fallback-vless-reality.md` — цели, риски, чеклист.
2. **Инструкция по развёртыванию** `docs/xray-vless-reality-eu1-deploy.md` — бэкап перед правками, установка Xray, пример REALITY inbound, systemd, шаблон `vless://`, интеграция с ботом.
3. **Бот:** переменная `VLESS_REALITY_SHARE_URL` в `env_vars.txt`; команда **`/mobile_vpn`** для зарегистрированных пользователей (ссылка вторым сообщением без HTML).
4. Обновлены: `env_vars.example.txt`, `README_FOR_NEXT_AGENT.md`, `docs/backup-restore.md`, `docs/blocking-bypass-strategy.md`, `docs/deployment.md`, `DONE_LIST_VPN.md`.

## Что сделать на серверах (владельцу)

1. На **eu1:** по `docs/xray-vless-reality-eu1-deploy.md` — бэкап, Xray, открыть TCP-порт, сгенерировать `vless://`.
2. На **Timeweb:** добавить в `/opt/vpnservice/env_vars.txt` строку `VLESS_REALITY_SHARE_URL=...`, `git pull` в `/opt/vpnservice`, `systemctl restart vpn-bot.service`.
3. Проверить с LTE: клиент v2rayNG / Streisand / Hiddify + `/mobile_vpn`.

## Для следующего агента

- Per-user UUID для REALITY пока не делали — одна общая ссылка; ротация вручную на сервере + обновление env.
- Если 443/tcp занят на eu1 — использовать 8443 и тот же порт в ссылке.
