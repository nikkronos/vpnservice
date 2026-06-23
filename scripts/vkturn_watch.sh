#!/bin/bash
# vkturn_watch.sh — еженедельный твотчер релизов cacggghp/vk-turn-proxy.
# Whitelist-обход запаркован 06-23: vk-turn не работает, т.к. VK сменил капчу,
# а тулза её не парсит (missing captcha_sid). Когда выйдет НОВЫЙ релиз — возможно,
# в нём фикс капчи → шлём TG-сигнал владельцу «время ретестить vk-turn».
# Cron (Fornex root, еженедельно): 0 12 * * 1  /opt/vpnservice/scripts/vkturn_watch.sh
# Состояние: /var/lib/vpn-health/vkturn_watch.state (последний виденный тег).
set -u
REPO="cacggghp/vk-turn-proxy"
STATE_DIR="/var/lib/vpn-health"
STATE="$STATE_DIR/vkturn_watch.state"
ENV="/opt/vpnservice/env_vars.txt"
mkdir -p "$STATE_DIR"

BOT_TOKEN=$(grep -E '^BOT_TOKEN=' "$ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' \r')
ADMIN_ID=$(grep -E '^ADMIN_ID=' "$ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' \r')

LATEST=$(curl -s --max-time 30 "https://api.github.com/repos/$REPO/releases/latest" \
  | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
[ -z "$LATEST" ] && exit 0   # сеть/API недоступны — тихо выходим, попробуем на следующей неделе

PREV=$(cat "$STATE" 2>/dev/null || echo "")

# Алертим только если тег сменился И это не самый первый запуск (PREV не пуст).
if [ -n "$PREV" ] && [ "$LATEST" != "$PREV" ]; then
  MSG="🛰️ vk-turn-proxy: новый релиз ${LATEST} (был ${PREV}). Whitelist-обход запаркован 06-23 из-за VK-капчи — возможно, в этом релизе фикс. Время ретестить vk-turn: скажи Claude «ретест vk-turn». github.com/${REPO}/releases"
  if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_ID" ]; then
    curl -s --max-time 15 "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${ADMIN_ID}" \
      --data-urlencode "text=${MSG}" >/dev/null
  fi
fi

printf '%s' "$LATEST" > "$STATE"
