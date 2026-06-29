#!/bin/bash
# vkturn_watch.sh — еженедельный твотчер релизов ФОРКА vk-turn-proxy.
# История: апстрим cacggghp БРОШЕН (последний пуш 16 апр 2026, issue «Куда пропал Автор»);
# фикс VK-капчи пришёл ФОРКОМ NikKuz99 v1.8.4 (PR #182/#183) — поэтому смотрим форк, не апстрим
# (старый вотчер на cacggghp/releases был слеп: автор не релизит → молчал бы вечно).
# Ретест 06-29 (см. ROADMAP / память hard_whitelist_unbeaten): капча СНЯТА, токен+TURN получены,
# НО трек запаркован по АНТИ-МАСШТАБУ (9-мин cred-TTL + ручная капча = боутик), не по технике.
# Сигнал = форк выпустил новый релиз → актуально ТОЛЬКО если есть конкретный жёсткий-БС юзер под Phase B.
# Cron (Fornex root, еженедельно): 0 12 * * 1  /opt/vpnservice/scripts/vkturn_watch.sh
# Состояние: /var/lib/vpn-health/vkturn_watch.state (последний виденный тег; seed v1.8.4).
set -u
REPO="NikKuz99/vk-turn-proxy"
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
  MSG="🛰️ vk-turn форк ${REPO}: новый релиз ${LATEST} (был ${PREV}). Капча уже снята ретестом 06-29 (тех-часть закрыта), трек запаркован по АНТИ-МАСШТАБУ. Релиз актуален ТОЛЬКО при конкретном жёстком-БС юзере под боутик-Phase B. github.com/${REPO}/releases"
  if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_ID" ]; then
    curl -s --max-time 15 "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${ADMIN_ID}" \
      --data-urlencode "text=${MSG}" >/dev/null
  fi
fi

printf '%s' "$LATEST" > "$STATE"
