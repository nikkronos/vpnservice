#!/usr/bin/env bash
# bootstrap-relay-node.sh — развернуть аварийный VLESS+REALITY фронт-релей за <15 мин.
# План Б (docs/plan-b-rkn-response-runbook.md, §Рычаги п.4). Клон yc/yc2: REALITY-вход
# xhttp на :443 → ВЕСЬ трафик в outbound на eu1 vless-ws (релей-кред 359e23cc).
# Новый релей юзает ТОТ ЖЕ релей-кред, что eu1 уже принимает → eu1 трогать НЕ нужно.
#
# Запуск НА свежей Ubuntu VPS (любой провайдер) из-под root (или с sudo):
#   scp scripts/bootstrap-relay-node.sh root@NEW_VPS:/tmp/
#   ssh root@NEW_VPS 'bash /tmp/bootstrap-relay-node.sh --sni www.microsoft.com'
#
# Идемпотентен: бэкапит старый config, валидирует через `xray run -test` ДО рестарта.
# После прогона — зарегистрировать узел (3 правки, см. runbook §Рычаги п.4) и залить
# per-user UUID: `python scripts/sync_xray_users.py --server <id>`.
set -euo pipefail

# ── Параметры (дефолты = клон yc) ──
SNI="www.microsoft.com"
DEST=""                                             # default = SNI:443
RELAY_HOST="185.21.8.91"                            # eu1
RELAY_PORT="80"
RELAY_UUID="359e23cc-f90c-4e43-97af-bd1b662ff043"   # shared relay cred (eu1 vless-ws)
RELAY_PATH="/vpn"
XHTTP_PATH="/download"
TEST_UUID=""                                        # опц.: seed-клиент для T2-вёттинга до полного sync
CONFIG="/usr/local/etc/xray/config.json"

usage(){ sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
while [ $# -gt 0 ]; do
  case "$1" in
    --sni) SNI="$2"; shift 2;;
    --dest) DEST="$2"; shift 2;;
    --relay-host) RELAY_HOST="$2"; shift 2;;
    --relay-port) RELAY_PORT="$2"; shift 2;;
    --relay-uuid) RELAY_UUID="$2"; shift 2;;
    --relay-path) RELAY_PATH="$2"; shift 2;;
    --xhttp-path) XHTTP_PATH="$2"; shift 2;;
    --test-uuid) TEST_UUID="$2"; shift 2;;
    -h|--help) usage;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done
[ -z "$DEST" ] && DEST="${SNI}:443"

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== bootstrap relay node =="
echo "  SNI=$SNI  DEST=$DEST"
echo "  relay -> $RELAY_HOST:$RELAY_PORT path=$RELAY_PATH uuid=${RELAY_UUID:0:8}..."

# 1. Xray (официальный инсталлер, идемпотентен)
if ! command -v xray >/dev/null 2>&1; then
  echo "-- installing Xray..."
  $SUDO bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
else
  echo "-- xray already installed: $(xray version 2>/dev/null | head -1)"
fi

# 2. REALITY keypair + shortId (свежие, НЕ копируем ключи yc)
echo "-- generating REALITY keys..."
KP="$(xray x25519)"
PRIV="$(echo "$KP" | grep -i 'private' | awk '{print $NF}')"
PUB="$(echo "$KP" | grep -iE 'public|password' | awk '{print $NF}')"
[ -z "$PRIV" ] && PRIV="$(echo "$KP" | sed -n '1p' | awk '{print $NF}')"
[ -z "$PUB" ]  && PUB="$(echo "$KP" | sed -n '2p' | awk '{print $NF}')"
SHORTID="$(openssl rand -hex 8)"
if [ -z "$PRIV" ] || [ -z "$PUB" ]; then echo "!! key generation failed" >&2; exit 1; fi

# 3. clients[] seed (опц. один тестовый клиент для немедленного T2-вёттинга)
CLIENTS="[]"
if [ -n "$TEST_UUID" ]; then
  CLIENTS="[{\"id\":\"$TEST_UUID\",\"email\":\"tid_test@kronos\"}]"
fi

# 4. backup + dirs
$SUDO mkdir -p /usr/local/etc/xray /var/log/xray
[ -f "$CONFIG" ] && $SUDO cp "$CONFIG" "$CONFIG.bak.bootstrap.$(date +%s)"

# 5. write config (heredoc раскрывает переменные)
TMP="$(mktemp)"
cat > "$TMP" <<JSON
{
  "log": { "access": "/var/log/xray/access.log", "error": "", "loglevel": "warning" },
  "inbounds": [
    {
      "port": 443, "protocol": "vless",
      "settings": { "clients": $CLIENTS, "decryption": "none" },
      "streamSettings": {
        "network": "xhttp", "security": "reality",
        "realitySettings": {
          "dest": "$DEST", "serverNames": ["$SNI"],
          "privateKey": "$PRIV", "shortIds": ["$SHORTID"]
        },
        "xhttpSettings": { "mode": "packet-up", "path": "$XHTTP_PATH" }
      },
      "tag": "vless-xhttp"
    },
    { "listen": "127.0.0.1", "port": 10085, "protocol": "dokodemo-door",
      "settings": { "address": "127.0.0.1" }, "tag": "api" }
  ],
  "outbounds": [
    {
      "tag": "eu1", "protocol": "vless",
      "settings": { "vnext": [ { "address": "$RELAY_HOST", "port": $RELAY_PORT,
        "users": [ { "id": "$RELAY_UUID", "encryption": "none" } ] } ] },
      "streamSettings": { "network": "ws", "security": "none",
        "wsSettings": { "path": "$RELAY_PATH" } }
    },
    { "tag": "direct", "protocol": "freedom" },
    { "protocol": "freedom", "tag": "api" }
  ],
  "routing": { "rules": [
    { "type": "field", "inboundTag": ["api"], "outboundTag": "api" },
    { "type": "field", "outboundTag": "eu1", "network": "tcp,udp" }
  ] },
  "stats": {},
  "api": { "tag": "api", "services": ["StatsService"] },
  "policy": { "system": { "statsInboundUplink": true, "statsInboundDownlink": true },
    "levels": { "0": { "statsUserUplink": true, "statsUserDownlink": true } } }
}
JSON

# 6. validate ДО применения
echo "-- validating config..."
$SUDO mv "$TMP" "$CONFIG"
if ! $SUDO xray run -test -c "$CONFIG"; then
  echo "!! VALIDATE FAILED — config оставлен на $CONFIG (бэкап *.bak.bootstrap.*)" >&2
  exit 1
fi

# 7. logrotate (как на остальных узлах: daily/maxsize/rotate/copytruncate)
$SUDO tee /etc/logrotate.d/xray >/dev/null <<'LR'
/var/log/xray/*.log {
  daily
  maxsize 100M
  rotate 3
  missingok
  notifempty
  copytruncate
}
LR

# 8. enable + start + check
$SUDO systemctl enable xray >/dev/null 2>&1 || true
$SUDO systemctl restart xray
sleep 2
$SUDO systemctl is-active xray

# 9. firewall (yc требовал открыть 443)
if command -v ufw >/dev/null 2>&1; then $SUDO ufw allow 443/tcp >/dev/null 2>&1 || true; fi

# 10. вывод данных для регистрации в пуле
IP="$(curl -s --max-time 8 ifconfig.me || echo '<this-vps-ip>')"
cat <<OUT

============================================================
✅ Relay node up. Данные для регистрации в пуле подписки:
------------------------------------------------------------
IP:        $IP
SNI:       $SNI   (dest=$DEST)
pubkey:    $PUB
shortId:   $SHORTID
xhttp:     mode=packet-up  path=$XHTTP_PATH

vless:// template (per-user UUID подставит sync; в env_vars.txt как VLESS_<NODE>_SHARE_URL).
⚠ Сверь порядок query-параметров с текущей VLESS_REALITY_SHARE_URL (формат под Happ):
vless://REPLACE_UUID@$IP:443?security=reality&encryption=none&pbk=$PUB&fp=chrome&type=xhttp&sni=$SNI&sid=$SHORTID&path=$XHTTP_PATH&mode=packet-up#Europe-N

Далее (docs/plan-b-rkn-response-runbook.md §Рычаги п.4):
  1) scripts/sync_xray_users.py → SERVERS[<id>]: inbound_tag=vless-xhttp, flow="",
     db_column=vless_uuid_yc, sudo="sudo ", ssh=<ssh-alias к этой VPS>
  2) web/app.py _build_subscription_links → config_list (+ env VLESS_<NODE>_SHARE_URL)
  3) python scripts/sync_xray_users.py --server <id>   # зальёт per-user UUID из БД
------------------------------------------------------------
Для немедленного T2-вёттинга без полной регистрации: перезапусти с
  --test-uuid <твой-vless_uuid_yc>  и собери vless:// выше со своим UUID.
============================================================
OUT
