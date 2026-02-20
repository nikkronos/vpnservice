#!/bin/bash
# Скрипт для проверки MTU в конфиге WireGuard
# Использование: ./check-mtu-config.sh

echo "=== Проверка MTU в конфиге WireGuard ==="
echo ""

# Проверить текущий MTU интерфейса
echo "--- Текущий MTU интерфейса wg0 ---"
ip link show wg0 | grep -oP 'mtu \K[0-9]+' || echo "MTU не найден"
echo ""

# Проверить MTU в конфиге
echo "--- MTU в конфиге /etc/wireguard/wg0.conf ---"
if grep -q "^MTU" /etc/wireguard/wg0.conf; then
    echo "✅ MTU найден в конфиге:"
    grep "^MTU" /etc/wireguard/wg0.conf
else
    echo "❌ MTU не найден в конфиге"
    echo ""
    echo "Рекомендуется добавить в секцию [Interface]:"
    echo "MTU = 1420"
fi
echo ""

# Проверить, есть ли секция [Interface]
echo "--- Секция [Interface] в конфиге ---"
if grep -A 10 "^\[Interface\]" /etc/wireguard/wg0.conf | head -15; then
    echo ""
    echo "💡 Если MTU не установлен, добавь строку 'MTU = 1420' после других параметров в секции [Interface]"
else
    echo "❌ Секция [Interface] не найдена"
fi
