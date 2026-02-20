#!/bin/bash
# Скрипт для установки MTU = 1420 в конфиг WireGuard
# Использование: sudo ./set-mtu-1420.sh

CONFIG_FILE="/etc/wireguard/wg0.conf"
BACKUP_FILE="/etc/wireguard/wg0.conf.backup.$(date +%Y%m%d_%H%M%S)"

echo "=== Установка MTU = 1420 в конфиг WireGuard ==="
echo ""

# Проверить, существует ли конфиг
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Конфиг $CONFIG_FILE не найден!"
    exit 1
fi

# Создать резервную копию
echo "Создаю резервную копию: $BACKUP_FILE"
cp "$CONFIG_FILE" "$BACKUP_FILE"
echo "✅ Резервная копия создана"
echo ""

# Проверить, есть ли уже MTU в конфиге
if grep -q "^MTU" "$CONFIG_FILE"; then
    echo "⚠️  MTU уже установлен в конфиге:"
    grep "^MTU" "$CONFIG_FILE"
    echo ""
    read -p "Заменить на MTU = 1420? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Отменено."
        exit 0
    fi
    # Заменить существующий MTU
    sed -i 's/^MTU.*/MTU = 1420/' "$CONFIG_FILE"
    echo "✅ MTU обновлён на 1420"
else
    # Найти секцию [Interface] и добавить MTU после неё
    if grep -q "^\[Interface\]" "$CONFIG_FILE"; then
        # Добавить MTU после первой строки в секции [Interface]
        sed -i '/^\[Interface\]/a MTU = 1420' "$CONFIG_FILE"
        echo "✅ MTU = 1420 добавлен в конфиг"
    else
        echo "❌ Секция [Interface] не найдена в конфиге!"
        echo "Добавь вручную в начало конфига:"
        echo "[Interface]"
        echo "MTU = 1420"
        exit 1
    fi
fi

echo ""
echo "--- Проверка изменений ---"
grep -A 5 "^\[Interface\]" "$CONFIG_FILE" | head -10
echo ""

echo "⚠️  Теперь нужно перезапустить WireGuard:"
echo "sudo systemctl restart wg-quick@wg0"
echo ""
echo "После перезапуска проверь MTU:"
echo "ip link show wg0 | grep mtu"
