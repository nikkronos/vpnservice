#!/bin/bash
# Liveness-sampler для 9 инструментированных eu1 vless-tcp shared-UUID (2026-06-10).
# eu1 per-user STATS не работают → ловим через access-log (journald, `email:
# auditshare_<id8>`). journald хранит ~16ч под нагрузкой → cron каждые 6ч с
# lookback 8ч (overlap) durable копит, какие auditshare-UUID реально использовались.
# По итогу окна: UUID, ни разу не появившиеся, — мертвы → удалять через
# sync_eu1_vless --no-shared --force (релей сохранится).
# ВРЕМЕННЫЙ аудит — снять (cron + этот скрипт), когда 9 будут разобраны.
LOG=/var/log/eu1-share-audit.log
TS=$(date -u +%FT%TZ)
SEEN=$(journalctl -u xray --since '8 hours ago' --no-pager 2>/dev/null \
        | grep -oE 'auditshare_[0-9a-f]+' | sort | uniq -c | tr '\n' ';')
if [ -z "$SEEN" ]; then SEEN="(никто из 9 не использовался)"; fi
echo "$TS  $SEEN" >> "$LOG"
# self-trim
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"

# вердикт + авто-нудж владельцу в TG, когда набрана статистика (dedup внутри).
# Вывод вердикта — в ОТДЕЛЬНЫЙ файл, чтобы не засорять сэмпл-лог (иначе его
# строки попадут в подсчёт сэмплов).
cd /opt/vpnservice && /opt/vpnservice/venv/bin/python scripts/eu1_share_audit_verdict.py \
    >> /var/log/eu1-share-audit-verdict.log 2>&1
