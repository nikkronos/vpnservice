# Быстрое исправление MTU на сервере TimeWeb

## Проблема

Текущий MTU интерфейса `wg0` = 1280, рекомендуется 1420 для лучшей производительности.

## Решение

### Шаг 1: Проверить текущий конфиг

```bash
# Проверить, есть ли MTU в конфиге
grep -A 10 "^\[Interface\]" /etc/wireguard/wg0.conf | head -15
```

### Шаг 2: Добавить MTU в конфиг

**Вариант А: Если MTU нет в конфиге**

```bash
# Создать резервную копию
sudo cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.backup.$(date +%Y%m%d)

# Добавить MTU после строки [Interface]
sudo sed -i '/^\[Interface\]/a MTU = 1420' /etc/wireguard/wg0.conf

# Проверить изменения
grep -A 5 "^\[Interface\]" /etc/wireguard/wg0.conf
```

**Вариант Б: Если MTU уже есть, но другое значение**

```bash
# Заменить существующий MTU
sudo sed -i 's/^MTU.*/MTU = 1420/' /etc/wireguard/wg0.conf

# Проверить изменения
grep "^MTU" /etc/wireguard/wg0.conf
```

### Шаг 3: Перезапустить WireGuard

```bash
sudo systemctl restart wg-quick@wg0
```

### Шаг 4: Проверить, что MTU применился

```bash
ip link show wg0 | grep mtu
```

Должно показать: `mtu 1420`

## Если что-то пошло не так

Восстановить из резервной копии:
```bash
sudo cp /etc/wireguard/wg0.conf.backup.* /etc/wireguard/wg0.conf
sudo systemctl restart wg-quick@wg0
```
