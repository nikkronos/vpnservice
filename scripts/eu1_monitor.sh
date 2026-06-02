#!/bin/bash
# Лёгкий мониторинг eu1 (Fornex) для расследования жалоб «скорость иногда падает».
#
# Пишет одну CSV-строку в /var/log/eu1-monitor.log каждые 5 минут (cron).
# Только дешёвые метрики — БЕЗ speedtest (не грузим 100-Мбит порт).
# Когда придёт жалоба со временем — коррелируем метрики с этим окном.
#
# Метрики: load1, RAM, swap, conntrack (близость к лимиту = дроп новых соединений),
# кол-во AWG peer-ов, кумулятивные rx/tx байты дефолтного интерфейса
# (дельта между соседними строками / 300с = пропускная способность, видно насыщение порта).
#
# Self-trim: держим header + последние 12000 строк (~6 недель при */5).
#
# Деплой: scp в /opt/vpnservice/scripts/, chmod +x, cron */5 (см. CLAUDE.md).
set -u

LOG=/var/log/eu1-monitor.log

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
load1=$(awk '{print $1}' /proc/loadavg 2>/dev/null)

# Память и swap (MB)
read -r mem_total mem_used <<<"$(free -m 2>/dev/null | awk '/^Mem:/ {print $2, $3}')"
swap_used=$(free -m 2>/dev/null | awk '/^Swap:/ {print $3}')

# conntrack (если модуль загружен)
ct=$(cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo 0)
ctmax=$(cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || echo 0)

# Кол-во AWG peer-ов в контейнере
awg=$(docker exec amnezia-awg2 awg show awg0 2>/dev/null | grep -c '^peer')
[ -z "$awg" ] && awg=0

# Дефолтный интерфейс + кумулятивные байты
ifc=$(ip route 2>/dev/null | awk '/^default/ {print $5; exit}')
[ -z "$ifc" ] && ifc=eth0
rx=$(cat "/sys/class/net/$ifc/statistics/rx_bytes" 2>/dev/null || echo 0)
tx=$(cat "/sys/class/net/$ifc/statistics/tx_bytes" 2>/dev/null || echo 0)

# Header при первом запуске
if [ ! -f "$LOG" ]; then
  echo "ts,load1,mem_used_mb,mem_total_mb,swap_used_mb,conntrack,conntrack_max,awg_peers,ifc,rx_bytes,tx_bytes" > "$LOG"
fi

echo "$ts,${load1:-},${mem_used:-},${mem_total:-},${swap_used:-},$ct,$ctmax,$awg,$ifc,$rx,$tx" >> "$LOG"

# Self-trim до header + 12000 строк
lines=$(wc -l < "$LOG" 2>/dev/null || echo 0)
if [ "$lines" -gt 12001 ]; then
  { head -1 "$LOG"; tail -n 12000 "$LOG"; } > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
