#!/bin/bash
# Скрипт диагностики для сервера eu1 (Fornex)
# Собирает всю диагностическую информацию и сохраняет в файл
# Использование: sudo ./diagnose-eu1.sh

set -e

OUTPUT="/tmp/eu1-diagnosis-$(date +%Y%m%d-%H%M%S).txt"

{
    echo "=== Диагностика eu1 (Fornex) ==="
    echo "Дата: $(date)"
    echo ""
    
    echo "=== WireGuard Status ==="
    wg show || echo "Ошибка: wg show не выполнен"
    
    echo -e "\n=== IP Forwarding ==="
    sysctl net.ipv4.ip_forward || echo "Ошибка: sysctl не выполнен"
    
    echo -e "\n=== iptables FORWARD ==="
    iptables -L FORWARD -n -v || echo "Ошибка: iptables FORWARD не выполнен"
    
    echo -e "\n=== iptables NAT POSTROUTING ==="
    iptables -t nat -L POSTROUTING -n -v || echo "Ошибка: iptables NAT POSTROUTING не выполнен"
    
    echo -e "\n=== iptables NAT PREROUTING ==="
    iptables -t nat -L PREROUTING -n -v | head -30 || echo "Ошибка: iptables NAT PREROUTING не выполнен"
    
    echo -e "\n=== Routes ==="
    ip route show || echo "Ошибка: ip route не выполнен"
    
    echo -e "\n=== wg0 Interface ==="
    ip addr show wg0 || echo "Ошибка: интерфейс wg0 не найден"
    
    echo -e "\n=== Shadowsocks Status ==="
    systemctl status shadowsocks-libev-local@ss-wg.service --no-pager -l || echo "Ошибка: сервис Shadowsocks не найден"
    
    echo -e "\n=== Shadowsocks Logs (last 50) ==="
    journalctl -u shadowsocks-libev-local@ss-wg.service -n 50 --no-pager || echo "Ошибка: логи Shadowsocks не найдены"
    
    echo -e "\n=== ss-redir Port (1081) ==="
    ss -tlnp | grep 1081 || echo "Порт 1081 не слушается"
    
    echo -e "\n=== ipset unified_ss_dst (если настроен) ==="
    ipset list unified_ss_dst 2>/dev/null || echo "ipset unified_ss_dst не найден (это нормально, если Unified не настроен)"
    
    echo -e "\n=== Проверка правил для Unified (10.1.0.20-50) ==="
    iptables -t nat -L PREROUTING -n -v | grep -E "10\.1\.0\.(20|50)|unified" || echo "Правила для Unified не найдены"
    
    echo -e "\n=== Проверка правил для VPN+GPT (10.1.0.8-254) ==="
    iptables -t nat -L PREROUTING -n -v | grep -E "10\.1\.0\.(8|9|1[0-9]|2[0-9]|3[0-9]|4[0-9]|5[0-9]|[6-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-4])" | head -10 || echo "Правила для VPN+GPT не найдены"
    
    echo -e "\n=== Системная информация ==="
    echo "Hostname: $(hostname)"
    echo "Uptime: $(uptime)"
    echo "Load average: $(cat /proc/loadavg 2>/dev/null || echo 'N/A')"
    
} > "$OUTPUT" 2>&1

echo "Диагностика сохранена в: $OUTPUT"
echo ""
echo "Содержимое файла:"
echo "=================="
cat "$OUTPUT"
