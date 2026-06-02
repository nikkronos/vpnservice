"""
Веб-панель мониторинга VPN-сервиса.

Отображает:
- Статус серверов
- Количество подключённых устройств
- Статистику использования
- Список пользователей (для админа)
"""

import csv
import functools
import hashlib
import hmac
import io
import json
import logging
import pathlib
import shlex
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, Response, jsonify, redirect, render_template, render_template_string, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

# Добавляем путь к модулям бота
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from bot.config import get_effective_mtproto_proxy_link, load_config, _parse_env_file
from bot.storage import Peer, User, get_all_peers, get_all_users, find_user
from bot.database import (
    db_create_otp,
    db_verify_otp,
    db_create_session,
    db_verify_session,
    db_find_user_by_email,
    db_upsert_user,
    db_get_effective_telegram_id,
    db_get_all_users,
    db_accumulate_traffic,
    db_get_lifetime_by_user,
    db_get_subscription,
    db_start_trial,
    db_ensure_referral_code,
    db_count_referrals,
    db_set_referred_by,
    db_get_user_by_referral_code,
    db_set_password,
    db_has_password,
    db_ensure_sub_token,
    db_find_user_by_sub_token,
    db_is_access_active,
    db_find_user_by_telegram_id,
    db_ensure_signup_trial,
    db_record_payment,
    db_find_payment_by_external_id,
    db_extend_subscription,
    db_apply_referral_bonus,
    db_get_pending_claim,
    db_create_payment_claim,
    db_get_claim_by_id,
    db_set_claim_notify_msg,
    db_update_vless_requested_at,
    db_get_vless_server_lifetime,
    db_get_or_create_vless_uuid,
    db_get_per_user_vless_uuid,
    init_db,
)
from bot.email_otp import generate_otp, send_otp_email
from bot.wireguard_peers import (
    WireGuardError,
    create_amneziawg_peer_and_config_for_user,
    execute_server_command,
    generate_vpn_url,
    regenerate_amneziawg_peer_and_config_for_user,
    find_peer_by_telegram_id,
    is_amneziawg_eu1_configured,
)
from bot.vless_peers import create_vless_client_for_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# За CF-прокси/nginx: доверяем X-Forwarded-Proto/Host, чтобы request.host_url
# отдавал https://<домен> (иначе subscription-ссылка/QR соберутся как http).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Загружаем конфиг
import os
try:
    config = load_config()
    ADMIN_ID = config.admin_id
    # Инициализируем SQLite DB (включая миграцию users.json)
    init_db(whitelist_seed=config.telegram_id_whitelist or [])
except Exception as e:
    logger.error(f"Ошибка загрузки конфига/БД: {e}")
    ADMIN_ID = None
    config = None

app.secret_key = (getattr(config, "admin_secret", None) or os.urandom(32).hex())

_recovery_lock = threading.Lock()

# ── Биллинг (Фаза 2/4): значения, легко менять ──
TRIAL_DAYS = 14            # длина пробного периода
REFERRAL_REWARD_DAYS = 14  # +дней обоим при первой оплате приглашённого
SUBSCRIPTION_DAYS_PER_PAYMENT = 30  # сколько дней даёт одна оплата (любым провайдером)
STARS_MONTHLY_PRICE = 150  # цена в Telegram Stars за SUBSCRIPTION_DAYS_PER_PAYMENT дней (~200 ₽)
SUBSCRIPTION_RUB_PRICE = 200  # цена в рублях за SUBSCRIPTION_DAYS_PER_PAYMENT дней

# Реквизиты владельца для ручной оплаты (СБП / карта). Не секрет (для приёма платежей).
MANUAL_PAY = {
    "sbp_phone": "+79213032918",
    "sbp_bank": "Т-Банк (Тинькофф)",
    "card": "2200 7007 6046 4759",
    "card_bank": "Т-Банк (Тинькофф)",
    "owner_tg": "nikkronos",
    "rub": SUBSCRIPTION_RUB_PRICE,
}


def _notify_inviter_about_signup(referral_code: str) -> None:
    """
    Уведомляет пригласителя в TG что по его реф-ссылке зарегистрировался
    новый пользователь. Вызывается только при УСПЕШНОЙ привязке (когда
    db_set_referred_by вернул True).

    Не падает при ошибках — это psychological-уведомление, не критичный
    функционал. Если не дойдёт — реф-бонус всё равно начислится при оплате.
    """
    try:
        bot_token = getattr(config, "bot_token", None) if config else None
        if not bot_token or not referral_code:
            return
        inviter = db_get_user_by_referral_code(referral_code)
        if not inviter:
            return
        inviter_tid = inviter.get("telegram_id")
        if not inviter_tid:
            return
        text = (
            "👋 <b>По твоей реф-ссылке зарегистрировался новый пользователь.</b>\n\n"
            f"Бонус +{REFERRAL_REWARD_DAYS} дней начислится тебе и ему, "
            "когда он впервые оплатит подписку."
        )
        api_body = json.dumps({
            "chat_id": int(inviter_tid),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=api_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        logger.warning("notify inviter about signup failed: %s", e)


def _require_admin_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("admin_panel"))
    error = None
    if request.method == "POST":
        admin_secret = getattr(config, "admin_secret", None) if config else None
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == "admin" and admin_secret and password == admin_secret:
            session["logged_in"] = True
            return redirect(url_for("admin_panel"))
        error = "Неверный логин или пароль"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _check_recovery_secret() -> Optional[tuple]:
    """
    Проверяет RECOVERY_SECRET из заголовка X-Recovery-Secret или query-параметра recovery_secret.
    Возвращает None если всё ок, или (jsonify(error), status_code) если проверка не прошла.
    Если секрет не задан в env — запрещаем доступ к legacy-эндпоинтам (fail secure).
    """
    secret = getattr(config, "recovery_secret", None) if config else None
    if not secret:
        return jsonify({"error": "Recovery secret not configured on server"}), 503
    provided = (
        request.headers.get("X-Recovery-Secret")
        or request.args.get("recovery_secret")
        or (request.get_json(silent=True) or {}).get("recovery_secret")
    )
    if not provided or provided != secret:
        return jsonify({"error": "Unauthorized"}), 403
    return None


def _parse_tg_proxy_link(link: Optional[str]) -> Dict[str, str]:
    """
    Parse tg://proxy?server=...&port=...&secret=... into dict.
    Returns empty dict if link is missing/invalid.
    """
    if not link:
        return {}
    try:
        # Example: tg://proxy?server=185.21.8.91&port=443&secret=...
        parsed = urllib.parse.urlparse(link)
        if not parsed.query:
            return {}
        qs = urllib.parse.parse_qs(parsed.query)
        out: Dict[str, str] = {}
        for k, v in qs.items():
            if v:
                out[k] = str(v[0])
        return out
    except Exception:
        return {}


def _restart_proxy_container_on_server(server_id: str, candidates: List[str]) -> Dict[str, str]:
    """
    Restarts first docker container that matches any candidate name substring.
    Uses SSH via existing VPN utilities.
    """
    # List running containers
    stdout, stderr = execute_server_command(
        server_id,
        "docker ps --format '{{.Names}}'",
        timeout=25,
    )
    names = []
    for line in (stdout or "").splitlines():
        name = line.strip()
        if name:
            names.append(name)

    matched = None
    for c in candidates:
        for n in names:
            if c in n:
                matched = n
                break
        if matched:
            break

    if not matched:
        return {
            "ok": "false",
            "error": f"No docker container matched candidates on {server_id}. Candidates={candidates}, running={names}",
        }

    # Restart matched container
    stdout2, stderr2 = execute_server_command(
        server_id,
        f"docker restart {matched}",
        timeout=25,
    )
    _ = stdout2  # restart output not always useful
    return {
        "ok": "true",
        "server_id": server_id,
        "container": matched,
        "stderr": (stderr2 or "").strip(),
    }


def _determine_target_server_id_from_env(proxy_server_ip: str) -> Optional[str]:
    """
    Map proxy server IP to our internal server_id ("main" or "eu1") using env_vars.txt.
    """
    base = pathlib.Path(__file__).parent.parent
    env = _parse_env_file(base / "env_vars.txt")
    if not proxy_server_ip:
        return None

    main_host = env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST")
    eu1_host = env.get("WG_EU1_ENDPOINT_HOST") or env.get("WG_EU1_SSH_HOST")

    if eu1_host and proxy_server_ip == eu1_host:
        return "eu1"
    if main_host and proxy_server_ip == main_host:
        return "main"
    return None


def check_server_status(server_id: str, endpoint_host: Optional[str] = None) -> Dict[str, any]:
    """
    Проверяет статус VPN-сервера.
    
    Returns:
        dict с полями: status (online/offline), ping_ms, last_check
    """
    if not endpoint_host:
        return {
            "status": "unknown",
            "ping_ms": None,
            "last_check": datetime.now().isoformat(),
            "error": "Endpoint host not specified"
        }
    
    try:
        # Простая проверка ping (может не работать на всех системах)
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", endpoint_host],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # Парсим время ответа из вывода ping
            ping_ms = None
            for line in result.stdout.split("\n"):
                if "time=" in line:
                    try:
                        ping_ms = float(line.split("time=")[1].split(" ")[0])
                        break
                    except (IndexError, ValueError):
                        pass
            
            return {
                "status": "online",
                "ping_ms": ping_ms,
                "last_check": datetime.now().isoformat()
            }
        else:
            return {
                "status": "offline",
                "ping_ms": None,
                "last_check": datetime.now().isoformat(),
                "error": "Ping failed"
            }
    except Exception as e:
        logger.exception(f"Ошибка проверки сервера {server_id}: {e}")
        return {
            "status": "error",
            "ping_ms": None,
            "last_check": datetime.now().isoformat(),
            "error": str(e)
        }


def _parse_wg_dump_transfer(stdout: str) -> Dict[str, tuple]:
    """Парсит dump → public_key -> (rx_bytes, tx_bytes)."""
    result: Dict[str, tuple] = {}
    for line in stdout.strip().split("\n")[1:]:
        parts = line.split("\t")
        if len(parts) >= 7:
            try:
                result[parts[0].strip()] = (int(parts[5]), int(parts[6]))
            except (ValueError, IndexError):
                continue
    return result


def _parse_wg_dump_full(stdout: str) -> Dict[str, Dict]:
    """Парсит dump → public_key -> {rx, tx, last_handshake}."""
    result: Dict[str, Dict] = {}
    for line in stdout.strip().split("\n")[1:]:
        parts = line.split("\t")
        if len(parts) >= 7:
            try:
                result[parts[0].strip()] = {
                    "rx": int(parts[5]),
                    "tx": int(parts[6]),
                    "last_handshake": int(parts[4]),
                }
            except (ValueError, IndexError):
                continue
    return result


def _get_awg_dump_eu1() -> str:
    """awg живёт внутри Docker-контейнера amnezia-awg2."""
    try:
        out = subprocess.run(
            ["docker", "exec", "amnezia-awg2", "awg", "show", "awg0", "dump"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return ""


def _get_wg_transfer_for_server(server_id: str) -> Dict[str, tuple]:
    """Трафик по pubkey для eu1 (локально, панель на том же хосте)."""
    if server_id == "eu1":
        stdout = _get_awg_dump_eu1()
        if stdout:
            return _parse_wg_dump_transfer(stdout)
        return {}
    return {}


def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Проверяет доступность TCP-порта на хосте."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


@app.route("/")
def landing():
    """
    Публичный лендинг (Phase 3i — prerequisite для ЮKassa-модерации).
    Залогиненный admin автоматически редиректится в /admin (удобство — букмарк).
    Все остальные видят landing-страницу с описанием сервиса, ценой и контактами.
    """
    if session.get("logged_in"):
        return redirect(url_for("admin_panel"))
    return render_template("landing.html")


@app.route("/oferta")
def oferta():
    """Публичный договор-оферта (для ЮKassa-модерации и юр. чистоты)."""
    return render_template("oferta.html")


@app.route("/contacts")
def contacts():
    """Публичная страница с реквизитами исполнителя."""
    return render_template("contacts.html")


@app.route("/privacy")
def privacy():
    """Политика обработки персональных данных (152-ФЗ)."""
    return render_template("privacy.html")


@app.route("/admin")
@_require_admin_auth
def admin_panel():
    """Админ-панель с общей статистикой (раньше была на /)."""
    try:
        peers = get_all_peers()
        users = get_all_users()
        
        # Статистика
        active_peers = [p for p in peers if p.active]
        active_users = [u for u in users if u.active]
        
        # Группировка по серверам
        by_server: Dict[str, int] = {}
        for peer in active_peers:
            by_server[peer.server_id] = by_server.get(peer.server_id, 0) + 1
        
        # Сводка по пользователям (без telegram_id): имя/псевдоним, серверы, кол-во пиров
        users_summary: List[Dict] = []
        for i, user in enumerate(users):
            user_peers = [p for p in peers if p.telegram_id == user.telegram_id]
            if not user_peers:
                continue
            servers = list({p.server_id for p in user_peers if p.active})
            if user.username:
                display_name = f"@{user.username}"
            elif user.telegram_id:
                display_name = f"ID {user.telegram_id}"
            elif user.email:
                display_name = user.email
            else:
                display_name = f"Пользователь {i + 1}"
            users_summary.append({
                "display_name": display_name,
                "servers": sorted(servers),
                "peer_count": len([p for p in user_peers if p.active]),
            })
        
        stats = {
            "total_users": len(users),
            "active_users": len(active_users),
            "total_peers": len(peers),
            "active_peers": len(active_peers),
            "by_server": by_server,
            "users_summary": users_summary,
        }
        
        return render_template("index.html", stats=stats)
    except Exception as e:
        logger.exception(f"Ошибка на главной странице: {e}")
        return f"Ошибка: {e}", 500


@app.route("/recovery")
def recovery_page():
    """Отдельная страница для восстановления (Telegram proxy / VPN конфиг)."""
    recovery_secret = getattr(config, "recovery_secret", "") if config else ""
    return render_template("recovery.html", stats={}, recovery_secret=recovery_secret)


@app.route("/api/servers")
def api_servers():
    """API: статус серверов."""
    try:
        from bot.wireguard_peers import get_available_servers, canonical_env_server_id
        from bot.config import _parse_env_file

        servers_info = get_available_servers()
        env = _parse_env_file(pathlib.Path(__file__).parent.parent / "env_vars.txt")

        servers_status = {}
        for server_id, info in servers_info.items():
            physical = canonical_env_server_id(server_id)
            if physical == "main":
                endpoint_host = env.get("WG_ENDPOINT_HOST") or env.get("VPN_SERVER_HOST")
            else:
                endpoint_host = env.get(f"WG_{physical.upper()}_ENDPOINT_HOST")

            status = check_server_status(server_id, endpoint_host)
            servers_status[server_id] = {
                "name": info["name"],
                "description": info.get("description", ""),
                "endpoint": endpoint_host,
                **status
            }
        
        return jsonify(servers_status)
    except Exception as e:
        logger.exception(f"Ошибка API серверов: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/services")
def api_services():
    """API: статус сервисов eu1 (AmneziaWG локально + VLESS порт)."""
    try:
        env = _parse_env_file(pathlib.Path(__file__).parent.parent / "env_vars.txt")
        eu1_host = env.get("WG_EU1_ENDPOINT_HOST") or env.get("WG_EU1_SSH_HOST") or "185.21.8.91"

        dump = _get_awg_dump_eu1()
        awg_ok = bool(dump.strip())

        vless_port = 443
        vless_ok = check_port("158.160.0.1", vless_port, timeout=2.0)
        try:
            yc_host = env.get("VLESS_YC_HOST") or ""
            if yc_host:
                vless_ok = check_port(yc_host, vless_port, timeout=2.0)
        except Exception:
            pass

        services_list = [
            {
                "service": "AmneziaWG",
                "status": "online" if awg_ok else "offline",
                "note": "eu1 — обход блокировок из РФ",
            },
            {
                "service": "VLESS+REALITY (мобильный)",
                "status": "online" if vless_ok else "unknown",
                "note": "YC VM → eu1, для LTE/5G",
            },
        ]
        return jsonify({"services": services_list})
    except Exception as e:
        logger.exception(f"Ошибка API сервисов: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/users")
def api_users():
    """API: список пользователей (только для админа)."""
    admin_secret = getattr(config, "admin_secret", None) if config else None
    if not admin_secret:
        return jsonify({"error": "Admin secret not configured on server"}), 503
    admin_key = request.args.get("admin_key")
    if not admin_key or admin_key != admin_secret:
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        users = get_all_users()
        peers = get_all_peers()
        
        # Группируем пиры по пользователям
        users_data = []
        for user in users:
            user_peers = [p for p in peers if p.telegram_id == user.telegram_id]
            users_data.append({
                "telegram_id": user.telegram_id,
                "username": user.username,
                "role": user.role,
                "active": user.active,
                "peers_count": len(user_peers),
                "active_peers": [p.server_id for p in user_peers if p.active]
            })
        
        return jsonify(users_data)
    except Exception as e:
        logger.exception(f"Ошибка API пользователей: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/traffic")
def api_traffic():
    """
    API: единая сводка по всем пользователям в БД (не только с AWG peer-ом).

    Для каждого юзера возвращает:
      - identity (username / telegram_id / email_verified)
      - peer-данные (wg_ip, platform, last_handshake, rx/tx) — None если peer-а нет
      - подписка (subscription_status, days_left, is_grandfather)
      - status: одно из {active, idle, onboarding, no_config, expired}
      - proxy_requested_at

    Сортировка: активные (свежий handshake) → тихие с peer-ом → онбординг →
    без конфига → истёкшие. Внутри группы — по активности desc.
    """
    try:
        peers = get_all_peers()
        dump_stdout = _get_awg_dump_eu1()
        full_data = _parse_wg_dump_full(dump_stdout) if dump_stdout else {}

        db_users = db_get_all_users()
        now_dt = datetime.now()
        now_ts = int(now_dt.timestamp())

        # Индексируем peer-ы по telegram_id (только active eu1).
        peers_by_uid: Dict[int, List] = {}
        samples: List[Dict] = []
        for peer in peers:
            if peer.server_id != "eu1" or not peer.active:
                continue
            peers_by_uid.setdefault(peer.telegram_id, []).append(peer)
            pk = (peer.public_key or "").strip()
            if pk in full_data:
                d = full_data[pk]
                samples.append({
                    "public_key": pk,
                    "telegram_id": peer.telegram_id,
                    "rx": d["rx"],
                    "tx": d["tx"],
                })

        # Накопительный учёт (reset-aware) — должен сработать ДО построения
        # users_list, чтобы lifetime_map был актуальным.
        try:
            db_accumulate_traffic(samples)
            lifetime_map = db_get_lifetime_by_user()
        except Exception as e:
            logger.warning("Traffic accounting failed: %s", e)
            lifetime_map = {}

        users_list: List[Dict] = []
        for u in db_users:
            uid = u.get("telegram_id")
            if not uid:
                continue
            uid = int(uid)

            # --- subscription ---
            expires_at = u.get("expires_at")
            is_grandfather = not expires_at
            days_left: Optional[int] = None
            if expires_at:
                # У части юзеров expires_at записан как ISO 8601 с T-разделителем
                # и микросекундами (`2026-07-10T15:51:14.040134`), у других — в
                # формате SQLite (`2026-06-10 22:48:20`). fromisoformat принимает
                # оба варианта; если придёт что-то ещё — пробуем strptime fallback.
                try:
                    exp_dt = datetime.fromisoformat(expires_at)
                except (ValueError, TypeError):
                    try:
                        exp_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError):
                        exp_dt = None
                if exp_dt is not None:
                    # fromisoformat может вернуть aware datetime если в строке есть
                    # tz-offset; приводим к naive, чтобы вычесть now_dt без TypeError.
                    if exp_dt.tzinfo is not None:
                        exp_dt = exp_dt.replace(tzinfo=None)
                    days_left = (exp_dt - now_dt).days

            # --- peer aggregate ---
            user_peers = peers_by_uid.get(uid, [])
            rx = tx = last_hs = 0
            wg_ip: Optional[str] = None
            platform: Optional[str] = None
            for peer in user_peers:
                pk = (peer.public_key or "").strip()
                d = full_data.get(pk) or {"rx": 0, "tx": 0, "last_handshake": 0}
                rx += d["rx"]
                tx += d["tx"]
                if d["last_handshake"] > last_hs:
                    last_hs = d["last_handshake"]
                    platform = peer.platform or "pc"
                if wg_ip is None:
                    wg_ip = peer.wg_ip
                    if platform is None:
                        platform = peer.platform or "pc"

            # --- vless proof-of-life ---
            # Сигнал что юзер пользуется VLESS (вместо/в дополнение к AWG).
            # Пишется в bot/web при выдаче vless:// и при subscription URL hit
            # (см. db_update_vless_requested_at). Это компенсирует отсутствие
            # AWG-handshake до тех пор пока не сделаем per-user UUID + Xray stats.
            vless_req = u.get("vless_requested_at")
            vless_ts = 0
            if vless_req:
                try:
                    vless_ts = int(datetime.strptime(vless_req, "%Y-%m-%d %H:%M:%S").timestamp())
                except (ValueError, TypeError):
                    pass
            recent_vless = vless_ts and (now_ts - vless_ts) < 7 * 86400

            # --- status ---
            has_peer = bool(user_peers)
            recent_hs = last_hs and (now_ts - last_hs) < 7 * 86400
            if not has_peer:
                # Без AWG-peer'а юзер всё ещё может пользоваться VLESS
                # (Быстрый VPN через subscription URL не требует AWG-peer'а).
                # Это переводит статус из «без конфига» в «VLESS-only активный».
                if recent_vless:
                    status_key = "active"
                else:
                    status_key = "onboarding" if u.get("migrated_at") else "no_config"
            elif not is_grandfather and days_left is not None and days_left < 0:
                status_key = "expired"
            elif recent_hs or recent_vless:
                status_key = "active"
            else:
                status_key = "idle"

            lt = lifetime_map.get(uid)
            total_bytes = lt["total"] if lt else (rx + tx)

            users_list.append({
                "telegram_id": uid,
                "username": u.get("username"),
                "email_verified": bool(u.get("email_verified")),
                "wg_ip": wg_ip,
                "platform": platform,
                "rx_bytes": rx,
                "tx_bytes": tx,
                "total_bytes": total_bytes,
                "last_handshake": last_hs,
                "proxy_requested_at": u.get("proxy_requested_at"),
                "vless_requested_at": u.get("vless_requested_at"),
                "migrated_at": u.get("migrated_at"),
                "subscription_status": u.get("subscription_status"),
                "days_left": days_left,
                "is_grandfather": is_grandfather,
                "status": status_key,
                "has_peer": has_peer,
            })

        # Сортировка: priority группа → внутри по последней активности desc.
        _STATUS_PRIORITY = {
            "active": 0,
            "idle": 1,
            "onboarding": 2,
            "no_config": 3,
            "expired": 4,
        }

        def _activity_ts(u: Dict) -> int:
            hs = u.get("last_handshake") or 0
            proxy_ts = u.get("proxy_requested_at") or ""
            proxy_unix = 0
            if proxy_ts:
                try:
                    proxy_unix = int(datetime.strptime(proxy_ts, "%Y-%m-%d %H:%M:%S").timestamp())
                except (ValueError, TypeError):
                    pass
            return max(hs, proxy_unix)

        users_list.sort(
            key=lambda x: (
                _STATUS_PRIORITY.get(x["status"], 9),
                -_activity_ts(x),
                -(x["rx_bytes"] + x["tx_bytes"]),
            )
        )

        resp = jsonify({
            "users": users_list,
            "last_update": datetime.now().isoformat(),
        })
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    except Exception as e:
        logger.exception(f"Ошибка API трафика: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    """
    API: сводная статистика активности.

    Активность по handshake AmneziaWG на eu1 + использование MTProxy.
    Метрики:
      - total_users / active_users (флаг active в БД)
      - email_verified_users
      - active_24h / active_7d / active_30d (handshake свежее N часов/дней)
      - proxy_requests_30d (пользователей, нажимавших MTProxy за 30 дней)
      - total_rx_bytes / total_tx_bytes (агрегат за время существования peer'ов)
    """
    try:
        import time as _t
        peers = get_all_peers()
        users = get_all_users()
        db_users = db_get_all_users()

        active_peers = [p for p in peers if p.active]
        active_users = [u for u in users if u.active]

        by_server: Dict[str, int] = {}
        for peer in active_peers:
            by_server[peer.server_id] = by_server.get(peer.server_id, 0) + 1

        # Activity windows: handshake по живым peer'ам eu1
        dump_stdout = _get_awg_dump_eu1()
        full_data = _parse_wg_dump_full(dump_stdout) if dump_stdout else {}

        now_ts = int(_t.time())
        win_24h = now_ts - 86400
        win_7d = now_ts - 7 * 86400
        win_30d = now_ts - 30 * 86400

        # tg_id → самый свежий handshake
        latest_hs_by_user: Dict[int, int] = {}
        total_rx = 0
        total_tx = 0
        for peer in active_peers:
            if peer.server_id != "eu1":
                continue
            d = full_data.get((peer.public_key or "").strip())
            if not d:
                continue
            hs = d.get("last_handshake", 0) or 0
            total_rx += d.get("rx", 0) or 0
            total_tx += d.get("tx", 0) or 0
            prev = latest_hs_by_user.get(peer.telegram_id, 0)
            if hs > prev:
                latest_hs_by_user[peer.telegram_id] = hs

        active_24h = sum(1 for hs in latest_hs_by_user.values() if hs >= win_24h)
        active_7d = sum(1 for hs in latest_hs_by_user.values() if hs >= win_7d)
        active_30d = sum(1 for hs in latest_hs_by_user.values() if hs >= win_30d)

        # Email-verified
        email_verified = sum(1 for u in db_users if u.get("email_verified"))

        # MTProxy: пользователей нажимавших за 30 дней
        proxy_requests_30d = 0
        for u in db_users:
            proxy_ts = u.get("proxy_requested_at")
            if not proxy_ts:
                continue
            try:
                t = int(datetime.strptime(proxy_ts, "%Y-%m-%d %H:%M:%S").timestamp())
                if t >= win_30d:
                    proxy_requests_30d += 1
            except (ValueError, TypeError):
                continue

        # Per-server VLESS lifetime (пишется scripts/vless_summary_accounting.py
        # каждые 5 мин через Xray stats API). Сюда попадают inbound-агрегаты
        # vless-ws + vless-xhttp + vless-tcp по каждому серверу. Per-user
        # разбивки тут нет (общие UUIDs — см. ROADMAP P2).
        vless_by_server: Dict[str, int] = {}
        vless_total_bytes = 0
        try:
            vless_lifetime = db_get_vless_server_lifetime()
            for srv_id, data in vless_lifetime.items():
                total = int(data.get("total") or 0)
                vless_by_server[srv_id] = total
                vless_total_bytes += total
        except Exception as e:
            logger.warning("vless_summary read failed: %s", e)

        return jsonify({
            "total_users": len(users),
            "active_users": len(active_users),
            "total_peers": len(peers),
            "active_peers": len(active_peers),
            "email_verified_users": email_verified,
            "active_24h": active_24h,
            "active_7d": active_7d,
            "active_30d": active_30d,
            "proxy_requests_30d": proxy_requests_30d,
            "total_rx_bytes": total_rx,
            "total_tx_bytes": total_tx,
            "vless_by_server": vless_by_server,
            "vless_total_bytes": vless_total_bytes,
            "by_server": by_server,
            "last_update": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.exception(f"Ошибка API статистики: {e}")
        return jsonify({"error": str(e)}), 500


def _qr_datauri(data: str) -> Optional[str]:
    """
    Генерирует QR-код для строки → PNG data-URI (для <img src>).
    Возвращает None, если данных нет или библиотека qrcode недоступна
    (graceful degradation — фронт просто не покажет QR).
    """
    if not data:
        return None
    try:
        import base64
        import qrcode
        img = qrcode.make(
            data,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        logger.warning("QR generation failed: %s", e)
        return None


def _validate_init_data(init_data: str) -> Optional[Dict]:
    """
    Валидация Telegram Mini App initData по HMAC.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Возвращает распарсенный dict (с ключом 'user' = объект) при успехе, иначе None.
    Проверяет: hash подпись + freshness (auth_date < 24ч).
    """
    if not init_data:
        return None
    try:
        parsed = urllib.parse.parse_qs(init_data, keep_blank_values=True)
        data = {k: v[0] for k, v in parsed.items()}
        recv_hash = data.pop("hash", None)
        if not recv_hash:
            return None
        # Anti-replay: auth_date не старше 24ч
        try:
            auth_date = int(data.get("auth_date", "0"))
            if abs(int(time.time()) - auth_date) > 86400:
                return None
        except (ValueError, TypeError):
            return None
        # data_check_string: пары "k=v", отсортированные по ключу, склеенные через \n
        data_check_string = "\n".join(
            f"{k}={data[k]}" for k in sorted(data.keys())
        )
        bot_token = getattr(config, "bot_token", None) if config else None
        if not bot_token:
            return None
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, recv_hash):
            return None
        user_str = data.get("user")
        if not user_str:
            return None
        user = json.loads(user_str)
        data["user"] = user
        return data
    except Exception as e:
        logger.warning("init_data validation failed: %s", e)
        return None


def _verify_email_session(body: dict) -> tuple:
    """
    Универсальный auth по email-token (для всех recovery endpoints с email-flow).
    Возвращает (user_row, telegram_id) при успехе или (None, error_response) при отказе.
    """
    token = (body.get("token") or "").strip()
    if not token:
        return None, (jsonify({"error": "token обязателен"}), 401)

    email = db_verify_session(token)
    if not email:
        return None, (jsonify({"error": "Сессия недействительна или истекла. Войди заново."}), 401)

    user_row = db_find_user_by_email(email)
    if not user_row or not user_row.get("active"):
        return None, (jsonify({"error": "Пользователь не найден или заблокирован."}), 403)

    telegram_id = user_row.get("telegram_id")
    if not telegram_id:
        return None, (jsonify({
            "error": (
                "Этот email пока не связан с Telegram-аккаунтом. "
                "Открой @vpnkronos_bot, нажми /start и пройди короткую регистрацию — "
                "после этого ЛК заработает."
            )
        }), 403)

    return (user_row, int(telegram_id)), None


@app.route("/api/recovery/proxy-link-by-email", methods=["POST"])
def api_recovery_proxy_link_by_email():
    """
    Возвращает актуальную tg://proxy ссылку (как /proxy в боте), без перезапуска контейнера.
    Auth: email-token из активной OTP-сессии.
    Тело: {token}
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err

        fresh_cfg = load_config()
        effective_link = get_effective_mtproto_proxy_link(fresh_cfg) or ""
        effective_link = effective_link.strip()
        if not effective_link.startswith("tg://proxy"):
            return jsonify({"error": "MTPROTO proxy link is not configured"}), 503

        return jsonify({
            "ok": True,
            "mtproto_proxy_link": effective_link,
            "hint": (
                "Та же ссылка, что по команде /proxy в боте. "
                "Нажми кнопку, чтобы открыть её прямо в Telegram, или скопируй вручную."
            ),
            "qr": _qr_datauri(effective_link),
        })
    except Exception as e:
        logger.exception("Ошибка api/recovery/proxy-link-by-email: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/recovery/awg-config-by-email", methods=["POST"])
def api_recovery_awg_config_by_email():
    """
    Основной VPN (AmneziaWG eu1) с выбором платформы. Auth: email-token.
    Тело: {token, platform: "pc" | "ios" | "android"}
    Ответ: {ok, filename, config, vpn_url?}
        - config: текст .conf файла
        - vpn_url: vpn:// deep link (только для platform=android — для удобного импорта в AmneziaVPN)
        - filename: рекомендуемое имя файла (awg_eu1.conf)
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        _user_row, telegram_id = auth

        # Enforcement gate (под ENV-флагом ENFORCEMENT_ENABLED). Subscription URL уже гейтится в /sub/<token>.
        if getattr(config, "enforcement_enabled", False) and not db_is_access_active(telegram_id):
            return jsonify({"error": "Подписка неактивна. Продли в ЛК или боте.", "subscription_inactive": True}), 402

        platform = str(body.get("platform") or "pc").strip().lower()
        if platform not in ("pc", "ios", "android"):
            return jsonify({"error": "platform must be one of: pc, ios, android"}), 400

        if not is_amneziawg_eu1_configured():
            return jsonify({"error": "AmneziaWG is not configured on server. Try later or ask owner."}), 503

        android_safe = (platform == "android")
        peer = find_peer_by_telegram_id(telegram_id, server_id="eu1", platform=platform)
        if peer and peer.active:
            peer, cfg = regenerate_amneziawg_peer_and_config_for_user(
                telegram_id, android_safe=android_safe, server_id="eu1", platform=platform
            )
        else:
            peer, cfg = create_amneziawg_peer_and_config_for_user(
                telegram_id, android_safe=android_safe, server_id="eu1", platform=platform
            )

        response = {
            "ok": True,
            "filename": f"awg_{peer.server_id}.conf",
            "config": cfg,
            "platform": platform,
        }
        if platform == "android":
            try:
                response["vpn_url"] = generate_vpn_url(cfg)
            except Exception as e:
                logger.warning("Не удалось сгенерировать vpn:// deep link: %s", e)
        # QR конфига для мобильных — скан в приложении AmneziaWG/AmneziaVPN
        if platform in ("ios", "android"):
            response["qr"] = _qr_datauri(cfg)
        return jsonify(response)
    except Exception as e:
        logger.exception("Ошибка api/recovery/awg-config-by-email: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/recovery/mobile-link-by-email", methods=["POST"])
def api_recovery_mobile_link_by_email():
    """
    Мобильный резерв (VLESS+REALITY) с выбором оператора. Auth: email-token.
    Тело: {token, operator: "megafon" | "yota" | "beeline" | "mts" | "tele2" | "tmobile" | "other"}
    Ответ: {ok, vless_url, operator, hint}

    Routing:
        - megafon | yota → vless_cdn_tls_share_url (main REALITY, SNI=cloud.mail.ru) — работает при БС
        - другие → vless_reality_share_url (eu1/yc REALITY, SNI=www.microsoft.com)
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        _row, telegram_id = auth

        # Enforcement gate (под ENV-флагом ENFORCEMENT_ENABLED).
        if getattr(config, "enforcement_enabled", False) and not db_is_access_active(telegram_id):
            return jsonify({"error": "Подписка неактивна. Продли в ЛК или боте.", "subscription_inactive": True}), 402

        operator = str(body.get("operator") or "").strip().lower()
        if operator not in ("megafon", "yota", "beeline", "mts", "tele2", "tmobile", "other"):
            return jsonify({"error": "operator must be one of: megafon, yota, beeline, mts, tele2, tmobile, other"}), 400

        fresh_cfg = load_config()
        # server_id для per-user UUID: megafon/yota → main (REALITY cloud.mail.ru),
        # остальные операторы → yc (REALITY www.microsoft.com).
        if operator in ("megafon", "yota"):
            template_url = (
                getattr(fresh_cfg, "vless_cdn_tls_share_url", None)
                or getattr(fresh_cfg, "vless_cdn_share_url", None)
                or getattr(fresh_cfg, "vless_reality_share_url", None)
            )
            target_server = "main"
            hint = (
                "Резервная ссылка для Мегафон/Yota — работает при активных белых списках РКН. "
                "Скопируй vless://... целиком и импортируй в приложение."
            )
        else:
            template_url = getattr(fresh_cfg, "vless_reality_share_url", None)
            target_server = "yc"
            hint = (
                "Резервный мобильный VPN. Скопируй vless://... целиком. "
                "Android: v2rayNG или Hiddify → «+» → «Импорт из буфера». "
                "iOS: Streisand, FoXray, V2Box или Hiddify → импорт ссылки."
            )

        if not template_url:
            return jsonify({"error": "VLESS link is not configured on server"}), 503

        # Подстановка per-user UUID (с автосинхронизацией Xray-config через async sync).
        vless_url = _personalize_vless_url(template_url, target_server, telegram_id)

        # Proof-of-life для VLESS — компенсирует отсутствие AWG-handshake.
        # Ставим после успешной выдачи; если что-то упадёт в обновлении —
        # это не должно ломать саму выдачу конфига.
        try:
            db_update_vless_requested_at(telegram_id)
        except Exception:
            logger.warning("vless_requested_at update failed for tid=%s", telegram_id)

        return jsonify({
            "ok": True,
            "vless_url": vless_url.strip(),
            "operator": operator,
            "hint": hint,
            "qr": _qr_datauri(vless_url.strip()),
        })
    except Exception as e:
        logger.exception("Ошибка api/recovery/mobile-link-by-email: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/account/info", methods=["POST"])
def api_account_info():
    """
    Сводка по аккаунту для экрана «Мой аккаунт». Auth: email-token.
    Тело: {token}
    Ответ: статус подписки, срок, доступность триала, реферальный код/ссылка/счётчик.
    """
    try:
        import math
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        _user_row, telegram_id = auth

        sub = db_get_subscription(telegram_id) or {}
        code = db_ensure_referral_code(telegram_id)
        sub_token = db_ensure_sub_token(telegram_id)
        sub_link_path = f"/sub/{sub_token}" if sub_token else None
        sub_full = (request.host_url.rstrip("/") + sub_link_path) if sub_link_path else None
        sub_qr = _qr_datauri(sub_full) if sub_full else None
        expires_at = sub.get("expires_at")
        grandfathered = expires_at is None
        status = sub.get("subscription_status") or "none"

        days_left = None
        if expires_at:
            try:
                delta = datetime.fromisoformat(expires_at) - datetime.utcnow()
                days_left = max(0, math.ceil(delta.total_seconds() / 86400.0))
            except (ValueError, TypeError):
                days_left = None

        pending_claim = db_get_pending_claim(telegram_id)
        return jsonify({
            "ok": True,
            "status": status,
            "expires_at": expires_at,
            "days_left": days_left,
            "grandfathered": grandfathered,
            "trial_used": bool(sub.get("trial_used")),
            # Триал доступен: не использовался И нет активной подписки (expires_at IS NULL или истекла).
            # Покрывает: новые юзеры; юзеры со «skip» в онбординге (expires_at=NOW); просрочки без активации.
            # Grandfather с trial_used=1 (после migration reset) — не видят кнопку.
            "trial_available": (not bool(sub.get("trial_used"))) and (
                (expires_at is None) or (days_left is not None and days_left == 0)
            ),
            "trial_days": TRIAL_DAYS,
            "has_password": db_has_password(telegram_id),
            "manual_pay": MANUAL_PAY,
            "subscription_rub_price": SUBSCRIPTION_RUB_PRICE,
            "stars_monthly_price": STARS_MONTHLY_PRICE,
            "subscription_days": SUBSCRIPTION_DAYS_PER_PAYMENT,
            "referral_code": code,
            "referral_link_path": f"/recovery?ref={code}" if code else None,
            "invited_count": db_count_referrals(code) if code else 0,
            "referral_reward_days": REFERRAL_REWARD_DAYS,
            "sub_link_path": sub_link_path,
            "sub_link": sub_full,
            "sub_qr": sub_qr,
            "pending_claim": ({
                "id": pending_claim["id"],
                "claimed_at": pending_claim["claimed_at"],
                "days": pending_claim["days"],
            } if pending_claim else None),
        })
    except Exception as e:
        logger.exception("api/account/info: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/account/start-trial", methods=["POST"])
def api_account_start_trial():
    """
    Активирует пробный период (TRIAL_DAYS). Auth: email-token. Тело: {token}.
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        _user_row, telegram_id = auth

        new_exp = db_start_trial(telegram_id, TRIAL_DAYS)
        if not new_exp:
            return jsonify({"error": "Пробный период уже был использован."}), 409
        return jsonify({"ok": True, "expires_at": new_exp, "trial_days": TRIAL_DAYS})
    except Exception as e:
        logger.exception("api/account/start-trial: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/billing/create-stars-invoice", methods=["POST"])
def api_billing_create_stars_invoice():
    """
    Создаёт invoice-ссылку для оплаты Telegram Stars (currency=XTR).
    Auth: email-token. Возвращает {invoice_link, amount, days}.
    Параметр recurring=true → добавляем subscription_period=2592000 (30 дней) →
    Telegram сам продлевает подписку ежемесячно и шлёт новые successful_payment
    события (обрабатываются тем же хендлером, идемпотентно по charge_id).
    Фронтенд (в Mini App): tg.openInvoice(invoice_link, cb) → on 'paid' → reload account.
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        _row, telegram_id = auth
        recurring = bool(body.get("recurring", False))

        bot_token = getattr(config, "bot_token", None) if config else None
        if not bot_token:
            return jsonify({"error": "Bot token не настроен"}), 503

        # Payload — самоидентифицируется в successful_payment-хендлере бота.
        # Префикс stars_sub один и тот же для one-time и recurring: хендлер всегда
        # продлевает на N дней из payload, что корректно и для авто-продления.
        payload = f"stars_sub:{telegram_id}:{SUBSCRIPTION_DAYS_PER_PAYMENT}:{int(time.time())}"

        api_body_dict = {
            "title": "VPN Kronos — подписка" + (" (авто-продление)" if recurring else ""),
            "description": (
                f"Доступ на {SUBSCRIPTION_DAYS_PER_PAYMENT} дней"
                + (", обновляется автоматически каждый месяц" if recurring else "")
            ),
            "payload": payload,
            "currency": "XTR",
            "prices": [{"label": f"{SUBSCRIPTION_DAYS_PER_PAYMENT} дней", "amount": STARS_MONTHLY_PRICE}],
        }
        if recurring:
            # Bot API 8.0: subscription_period=2592000 (30 дней) → нативный recurring биллинг.
            api_body_dict["subscription_period"] = 2592000
        api_body = json.dumps(api_body_dict).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/createInvoiceLink",
            data=api_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            tg_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.exception("createInvoiceLink HTTP error: %s", e)
            return jsonify({"error": "Telegram API недоступен"}), 502
        if not tg_data.get("ok"):
            logger.warning("Telegram createInvoiceLink failed: %s", tg_data)
            return jsonify({"error": tg_data.get("description", "Telegram API error")}), 502

        invoice_link = tg_data["result"]
        return jsonify({
            "ok": True,
            "invoice_link": invoice_link,
            "amount_stars": STARS_MONTHLY_PRICE,
            "days": SUBSCRIPTION_DAYS_PER_PAYMENT,
            "recurring": recurring,
        })
    except Exception as e:
        logger.exception("api/billing/create-stars-invoice: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/billing/claim-payment", methods=["POST"])
def api_billing_claim_payment():
    """
    Donation-flow: юзер жмёт «✅ Я перевёл деньги». Создаём pending-заявку
    и отправляем владельцу уведомление в TG с inline-кнопками approve/decline.
    Если pending уже есть — переотправляем уведомление (на случай если оно
    потерялось), без дублирования заявки.

    Auth: email-token. Тело: {token, source?: 'webapp'|'bot'}.
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        row, telegram_id = auth
        source = (body.get("source") or "webapp").strip()[:32]

        if not ADMIN_ID:
            return jsonify({"error": "ADMIN_TELEGRAM_ID не настроен"}), 503
        bot_token = getattr(config, "bot_token", None) if config else None
        if not bot_token:
            return jsonify({"error": "Bot token не настроен"}), 503

        # Создаём или возвращаем существующую pending-заявку
        existing = db_get_pending_claim(telegram_id)
        claim_id = db_create_payment_claim(
            telegram_id,
            days=SUBSCRIPTION_DAYS_PER_PAYMENT,
            source=source,
        )
        if not claim_id:
            return jsonify({"error": "Не удалось создать заявку"}), 500
        reused = bool(existing)

        # Готовим текст уведомления владельцу
        sub = db_get_subscription(telegram_id) or {}
        username = (row.get("username") if isinstance(row, dict) else None) or "—"
        email = (row.get("email") if isinstance(row, dict) else None) or "—"
        days_left = sub.get("days_left", 0) or 0
        expires_at = (sub.get("expires_at") or "")[:10] or "—"
        grandfather = sub.get("grandfathered")
        if grandfather:
            status_line = "Бессрочный (grandfather)"
        elif days_left > 0:
            status_line = f"до {expires_at} (осталось {days_left} дн)"
        else:
            status_line = "Подписка неактивна"
        text = (
            f"💳 <b>Новая оплата — {SUBSCRIPTION_DAYS_PER_PAYMENT} дней</b>\n\n"
            f"👤 @{username} (id: <code>{telegram_id}</code>)\n"
            f"📧 {email}\n"
            f"📅 Сейчас: {status_line}\n"
            f"🪵 Источник: {source}"
            + ("\n♻️ Переотправка существующей заявки" if reused else "")
        )
        inline_keyboard = {
            "inline_keyboard": [[
                {"text": f"✅ Подтвердить +{SUBSCRIPTION_DAYS_PER_PAYMENT} дн",
                 "callback_data": f"claim_approve:{claim_id}"},
                {"text": "❌ Отклонить",
                 "callback_data": f"claim_decline:{claim_id}"},
            ]]
        }

        # Шлём владельцу через TG API напрямую (Flask не имеет инстанса бота)
        api_body = json.dumps({
            "chat_id": ADMIN_ID,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": inline_keyboard,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=api_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            tg_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.exception("notify owner (claim) failed: %s", e)
            return jsonify({"ok": True, "claim_id": claim_id, "pending": True,
                            "notify_failed": True})
        if tg_data.get("ok"):
            msg_id = (tg_data.get("result") or {}).get("message_id")
            if msg_id:
                try:
                    db_set_claim_notify_msg(claim_id, int(msg_id))
                except Exception as e:
                    logger.warning("save notify_msg_id failed: %s", e)
        else:
            logger.warning("Telegram sendMessage failed: %s", tg_data)

        return jsonify({
            "ok": True,
            "claim_id": claim_id,
            "pending": True,
            "reused": reused,
        })
    except Exception as e:
        logger.exception("api/billing/claim-payment: %s", e)
        return jsonify({"error": str(e)}), 500


_ADMIN_CREDIT_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Подтверждение оплаты — VPN Kronos</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0f1419; color: #e6e6e6; margin: 0; padding: 20px; }
  .wrap { max-width: 560px; margin: 0 auto; }
  h1 { font-size: 1.4em; }
  form { background: #1a1f2b; padding: 18px; border-radius: 10px;
         border: 1px solid #2a3243; }
  label { display: block; margin-top: 12px; font-weight: 600; color: #c0c8d4; }
  input, select, textarea { width: 100%; box-sizing: border-box; margin-top: 4px;
    padding: 9px 11px; background: #0f1419; border: 1px solid #2a3243;
    color: #e6e6e6; border-radius: 7px; font-size: 1em; }
  .hint { font-size: 0.85em; color: #8b94a3; margin-top: 4px; }
  button { margin-top: 18px; padding: 11px 16px; background: #4a9eff;
    color: #fff; border: 0; border-radius: 8px; font-size: 1em;
    font-weight: 600; cursor: pointer; }
  button:hover { background: #5dade2; }
  .ok { background: #1b3a2a; border: 1px solid #2d6a48; color: #8eff9e;
        padding: 12px; border-radius: 8px; margin-bottom: 14px; }
  .err { background: #3a1b1b; border: 1px solid #6a2d2d; color: #ff8e8e;
        padding: 12px; border-radius: 8px; margin-bottom: 14px; }
  details { margin-top: 16px; color: #8b94a3; }
  code { background: #0a0d12; padding: 2px 6px; border-radius: 4px; }
</style></head><body><div class="wrap">
<h1>💳 Подтверждение ручной оплаты</h1>
{% if msg_ok %}<div class="ok">{{ msg_ok }}</div>{% endif %}
{% if msg_err %}<div class="err">{{ msg_err }}</div>{% endif %}
<form method="POST" action="/admin/credit">
  <label>Email пользователя <span class="hint">(или telegram_id ниже — что-то одно)</span></label>
  <input type="email" name="email" placeholder="user@example.com" value="{{ form.email or '' }}">

  <label>Telegram ID <span class="hint">(если знаешь — точнее, чем email)</span></label>
  <input type="number" name="telegram_id" placeholder="123456789" value="{{ form.telegram_id or '' }}">

  <label>Дней продления</label>
  <input type="number" name="days" value="{{ form.days or 30 }}" min="1" max="3650" required>

  <label>Сумма оплаты</label>
  <input type="number" name="amount" step="0.01" value="{{ form.amount or 200 }}" required>

  <label>Валюта</label>
  <select name="currency">
    <option value="RUB" {% if form.currency == 'RUB' or not form.currency %}selected{% endif %}>RUB</option>
    <option value="USD" {% if form.currency == 'USD' %}selected{% endif %}>USD</option>
    <option value="XTR" {% if form.currency == 'XTR' %}selected{% endif %}>XTR (Stars)</option>
  </select>

  <label>Провайдер</label>
  <select name="provider">
    <option value="manual_sbp" {% if form.provider == 'manual_sbp' or not form.provider %}selected{% endif %}>СБП (ручной)</option>
    <option value="manual_card" {% if form.provider == 'manual_card' %}selected{% endif %}>Карта (ручной)</option>
    <option value="manual_crypto" {% if form.provider == 'manual_crypto' %}selected{% endif %}>Крипта (ручной)</option>
    <option value="manual_other" {% if form.provider == 'manual_other' %}selected{% endif %}>Другое</option>
  </select>

  <label>External ID <span class="hint">(номер чека / транзакции; для идемпотентности — повторный submit с тем же ID не зачислит дважды)</span></label>
  <input type="text" name="external_id" value="{{ form.external_id or '' }}" placeholder="напр. tbnk-2025-05-27-12345">

  <label>Заметка <span class="hint">(опционально)</span></label>
  <textarea name="notes" rows="2" placeholder="напр. перевод от Ивана 2200**4759">{{ form.notes or '' }}</textarea>

  <button type="submit">✅ Зачислить</button>
</form>

<details><summary>Как пользоваться</summary>
<p>Когда пользователь сообщил об оплате (СБП/карта) — открой эту форму, введи email <i>или</i> telegram_id, сумму и дни (обычно 30). Submit:</p>
<ul>
  <li>создаётся запись в <code>payments</code> (status=<code>succeeded</code>) с указанным <code>external_id</code> для идемпотентности;</li>
  <li>продлевается подписка на N дней;</li>
  <li>если у пользователя был <code>referred_by</code> и бонус ещё не начислен — оба получают +{{ referral_days }} дней.</li>
</ul>
<p>Повторный submit с тем же <code>external_id</code> вернёт ошибку — двойного зачисления не будет.</p>
</details>

</div></body></html>"""


@app.route("/admin/credit", methods=["GET", "POST"])
@_require_admin_auth
def admin_credit():
    """
    Админ-форма для ручного подтверждения оплат (СБП / карта / крипта).
    Защищена @_require_admin_auth (cookie-сессия после /login).
    POST → db_record_payment + db_extend_subscription + db_apply_referral_bonus.
    Idempotent по external_id (если задан).
    """
    msg_ok = None
    msg_err = None
    form = {}

    if request.method == "POST":
        form = {
            "email": (request.form.get("email") or "").strip().lower(),
            "telegram_id": (request.form.get("telegram_id") or "").strip(),
            "days": (request.form.get("days") or "").strip(),
            "amount": (request.form.get("amount") or "").strip(),
            "currency": (request.form.get("currency") or "RUB").strip(),
            "provider": (request.form.get("provider") or "manual_sbp").strip(),
            "external_id": (request.form.get("external_id") or "").strip() or None,
            "notes": (request.form.get("notes") or "").strip(),
        }
        try:
            # Резолвим пользователя
            telegram_id = None
            user_email = form["email"] or None
            if form["telegram_id"]:
                try:
                    telegram_id = int(form["telegram_id"])
                except ValueError:
                    raise ValueError("telegram_id должен быть числом")
                row = db_find_user_by_telegram_id(telegram_id)
                if not row:
                    raise ValueError(f"Пользователь с telegram_id={telegram_id} не найден")
                if not user_email:
                    user_email = (row.get("email") or "").lower() or None
            elif user_email:
                row = db_find_user_by_email(user_email)
                if not row:
                    raise ValueError(f"Пользователь с email={user_email} не найден")
                telegram_id = int(row["telegram_id"])
            else:
                raise ValueError("Укажи email или telegram_id")

            # Парсим числа
            try:
                days = int(form["days"])
                if days < 1 or days > 3650:
                    raise ValueError
            except ValueError:
                raise ValueError("Дней: число 1–3650")
            try:
                amount = float(form["amount"])
            except ValueError:
                raise ValueError("Сумма должна быть числом")

            # Идемпотентность по external_id
            if form["external_id"]:
                existing = db_find_payment_by_external_id(form["external_id"])
                if existing:
                    raise ValueError(
                        f"Платёж с external_id='{form['external_id']}' уже зачислен "
                        f"(payment_id={existing.get('id')}, status={existing.get('status')})"
                    )

            # 1) Запись платежа
            pay_id = db_record_payment(
                provider=form["provider"],
                amount=amount,
                currency=form["currency"],
                telegram_id=telegram_id,
                email=user_email,
                external_id=form["external_id"],
                plan=f"manual_{days}d",
                days=days,
                status="succeeded",
            )
            # 2) Продление подписки
            new_exp = db_extend_subscription(telegram_id, days=days, plan="paid", status="active")
            # 2a) Auto-restore (enforcement gap hook): AWG + VLESS soft-restore.
            restored_awg = []
            restored_vless = False
            try:
                from bot.wireguard_peers import restore_user_revoked_peers
                restored_awg = restore_user_revoked_peers(int(telegram_id))
            except Exception as e:
                logger.exception("/admin/credit AWG restore failed: %s", e)
            # VLESS: async sync_xray_users.py если у юзера есть UUIDs
            try:
                if (db_get_per_user_vless_uuid(int(telegram_id), "main")
                        or db_get_per_user_vless_uuid(int(telegram_id), "yc")):
                    import subprocess as _sp
                    script_path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "sync_xray_users.py"
                    _sp.Popen(
                        [sys.executable, str(script_path), "--all", "--no-shared"],
                        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                        start_new_session=True,
                    )
                    restored_vless = True
                    logger.info("/admin/credit: spawned VLESS sync for tid=%s", telegram_id)
            except Exception as e:
                logger.warning("/admin/credit VLESS sync failed: %s", e)
            # Уведомление юзеру если хоть что-то восстановлено
            if (restored_awg or restored_vless) and config and getattr(config, "bot_token", None):
                notify_body = json.dumps({
                    "chat_id": int(telegram_id),
                    "text": "✅ <b>Доступ восстановлен.</b>\n\n"
                            "Твой существующий конфиг снова работает — переподключаться не нужно.",
                    "parse_mode": "HTML",
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{config.bot_token}/sendMessage",
                    data=notify_body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    urllib.request.urlopen(req, timeout=10).read()
                except Exception as e:
                    logger.warning("/admin/credit notify-restore failed: %s", e)
            # 3) Реферальный бонус (idempotent)
            inviter_tid = db_apply_referral_bonus(telegram_id, REFERRAL_REWARD_DAYS)

            msg_ok = (
                f"✅ Зачислено: payment_id={pay_id}, +{days} дн (до {new_exp}). "
                + (f"Реферальный бонус +{REFERRAL_REWARD_DAYS} дн обоим (inviter tid={inviter_tid})." if inviter_tid else "")
            )
            form = {}  # очистить форму после успеха
        except ValueError as ve:
            msg_err = str(ve)
        except Exception as e:
            logger.exception("/admin/credit POST: %s", e)
            msg_err = f"Ошибка: {e}"

    return render_template_string(
        _ADMIN_CREDIT_TEMPLATE,
        msg_ok=msg_ok,
        msg_err=msg_err,
        form=form,
        referral_days=REFERRAL_REWARD_DAYS,
    )


@app.route("/api/account/set-password", methods=["POST"])
def api_account_set_password():
    """
    Устанавливает/меняет пароль. Auth: email-token (личность подтверждена входом).
    Тело: {token, password}. Пароль ≥ 8 символов.
    """
    try:
        body = request.get_json() or {}
        auth, err = _verify_email_session(body)
        if err:
            return err
        _user_row, telegram_id = auth
        password = (body.get("password") or "").strip()
        if len(password) < 8:
            return jsonify({"error": "Пароль должен быть не короче 8 символов."}), 400
        db_set_password(telegram_id, generate_password_hash(password))
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("api/account/set-password: %s", e)
        return jsonify({"error": str(e)}), 500


_SUB_LABEL_MAP = {
    # технические метки в исходных vless-ссылках → user-friendly для подписки
    "YC-Reality": "🇪🇺 Европа",
    "EU1-VLESS":  "🇪🇺 Европа",
    "RU-REALITY": "🇷🇺 Россия",
}


def _replace_uuid_in_vless_url(url: str, new_uuid: str) -> str:
    """
    Заменяет UUID в vless://<UUID>@host:port?...#fragment на new_uuid.
    Если URL некорректный — возвращает исходный (graceful).
    """
    if not url or not url.startswith("vless://") or "@" not in url or not new_uuid:
        return url
    head, rest = url.split("@", 1)
    return f"vless://{new_uuid}@{rest}"


def _sync_xray_after_new_uuid(server_id: str) -> None:
    """
    Фоновая синхронизация Xray config после создания нового per-user UUID.
    Запускается в отдельном subprocess чтобы не блокировать HTTP-ответ.
    Юзер сразу получает ссылку; Xray-config обновится за ~5-10 сек.

    Если sync упадёт — юзер сможет подключиться только после следующего
    sync (cron / повторный sync_xray_users.py вручную).
    """
    try:
        import subprocess as _sp
        script_path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "sync_xray_users.py"
        # Используем Popen — non-blocking, родительский процесс не ждёт
        _sp.Popen(
            [sys.executable, str(script_path), "--server", server_id],
            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )
        logger.info("Spawned async sync_xray_users for server %s", server_id)
    except Exception as e:
        logger.warning("Failed to spawn sync_xray_users for %s: %s", server_id, e)


# Маппинг VLESS-сервера → ENV-атрибут (для генерации ссылок)
_VLESS_SERVER_TO_ATTR = {
    "yc":   "vless_reality_share_url",       # YC REALITY xHTTP (T2/МТС/Билайн)
    "main": "vless_cdn_tls_share_url",       # Main REALITY (Мегафон/Yota)
}


def _personalize_vless_url(template_url: str, server_id: str, telegram_id: int) -> str:
    """
    Берёт env-template (общий vless://OLD_UUID@...) и подставляет per-user UUID
    для конкретного юзера. Если UUID ещё не создан в БД — создаёт + триггерит
    async sync Xray (≈10 сек до готовности на сервере).

    Если что-то пошло не так — возвращает оригинальный template (graceful
    degradation: юзер получит общую ссылку, продолжит работать как раньше).
    """
    if not template_url or not telegram_id:
        return template_url
    try:
        existing = db_get_per_user_vless_uuid(telegram_id, server_id)
        per_user_uuid = db_get_or_create_vless_uuid(telegram_id, server_id)
        if not per_user_uuid:
            return template_url
        if not existing:
            # Только что создан → нужна синхронизация Xray
            _sync_xray_after_new_uuid(server_id)
        return _replace_uuid_in_vless_url(template_url, per_user_uuid)
    except Exception as e:
        logger.warning("personalize_vless_url failed for tid=%s server=%s: %s",
                       telegram_id, server_id, e)
        return template_url


def _build_subscription_links(telegram_id: Optional[int] = None) -> List[str]:
    """
    Список vless:// для subscription. Если telegram_id передан — подставляем
    per-user UUID для каждого сервера (миграция 2026-06-01). Если None
    (legacy путь) — возвращаем общие share-ссылки из env.
    """
    cfg = load_config()
    out: List[str] = []
    seen = set()
    # (env_attr, default_label, server_id для per-user UUID)
    config_list = (
        ("vless_reality_share_url", "🇪🇺 Европа", "yc"),
        ("vless_cdn_tls_share_url", "🇷🇺 Россия", "main"),
    )
    for attr, default_label, server_id in config_list:
        u = (getattr(cfg, attr, None) or "").strip()
        if not u.startswith("vless://") or u in seen:
            continue
        seen.add(u)
        # Подстановка per-user UUID
        if telegram_id:
            u = _personalize_vless_url(u, server_id, telegram_id)
        if "#" in u:
            base, frag = u.rsplit("#", 1)
            current = urllib.parse.unquote(frag)
            label = _SUB_LABEL_MAP.get(current, default_label)
            u = base + "#" + urllib.parse.quote(label, safe="")
        else:
            u = u + "#" + urllib.parse.quote(default_label, safe="")
        out.append(u)
    return out


@app.route("/sub/<token>")
def api_subscription(token):
    """
    Subscription-URL (СПАЙК, аддитивно): GET /sub/<sub_token> → base64-список
    vless:// для HAPP / Streisand / V2Box / Hiddify. Токен = креденшл (стабильный).
    Гейтинг по сроку (db_is_access_active) — хук enforcement: истёк срок → пустая
    подписка → все устройства отваливаются. Сейчас все grandfathered → отдаётся всем.
    """
    try:
        import base64 as _b64
        user = db_find_user_by_sub_token(token)
        if not user or not user.get("active"):
            return Response("", mimetype="text/plain", status=404)

        tid = user.get("telegram_id")
        if tid and not db_is_access_active(int(tid)):
            # enforcement: нет доступа → пустая подписка (нет серверов)
            return Response("", mimetype="text/plain")

        # Proof-of-life для VLESS — каждый hit /sub/<token> означает что у юзера
        # есть VPN-клиент с настроенной подпиской (HAPP/Streisand/...) который
        # автоматически проверяет URL каждые ~12 ч (Profile-Update-Interval).
        # Это ЛУЧШИЙ proof-of-life сигнал: клиент жив → юзер пользуется.
        if tid:
            try:
                db_update_vless_requested_at(int(tid))
            except Exception:
                logger.warning("vless_requested_at update failed for sub tid=%s", tid)

        links = _build_subscription_links(telegram_id=int(tid) if tid else None)
        body = _b64.b64encode("\n".join(links).encode("utf-8")).decode("ascii")
        resp = Response(body, mimetype="text/plain; charset=utf-8")
        resp.headers["Profile-Update-Interval"] = "12"
        resp.headers["Cache-Control"] = "no-store"
        exp = user.get("expires_at")
        if exp:
            try:
                ts = int(datetime.fromisoformat(exp).timestamp())
                resp.headers["Subscription-Userinfo"] = f"upload=0; download=0; total=0; expire={ts}"
            except (ValueError, TypeError):
                pass
        return resp
    except Exception as e:
        logger.exception("api/subscription: %s", e)
        return Response("", mimetype="text/plain", status=500)


@app.route("/api/auth/send-otp", methods=["POST"])
def api_auth_send_otp():
    """Отправляет OTP-код на указанный email. Создаёт пользователя если нет."""
    try:
        body = request.get_json() or {}
        email = (body.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return jsonify({"error": "Некорректный email"}), 400

        if not config or not config.resend_api_key:
            return jsonify({"error": "Email-сервис не настроен. Обратись к администратору."}), 503

        user_row = db_find_user_by_email(email)
        if not user_row:
            db_upsert_user({
                "email": email,
                "role": "user",
                "active": True,
                "preferred_server_id": "eu1",
                "email_verified": False,
            })

        code = generate_otp()
        db_create_otp(email, code)

        sent = send_otp_email(
            to_email=email,
            code=code,
            api_key=config.resend_api_key,
            from_email=config.resend_from_email,
        )
        if not sent:
            return jsonify({"error": "Не удалось отправить письмо. Проверь адрес или попробуй позже."}), 502

        return jsonify({"ok": True, "message": f"Код отправлен на {email}"})
    except Exception as e:
        logger.exception("Ошибка api/auth/send-otp: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/verify-otp", methods=["POST"])
def api_auth_verify_otp():
    """Проверяет OTP. При успехе возвращает session token (60 мин)."""
    try:
        body = request.get_json() or {}
        email = (body.get("email") or "").strip().lower()
        code = (body.get("code") or "").strip().replace(" ", "")

        if not email or not code:
            return jsonify({"error": "email и code обязательны"}), 400

        if not db_verify_otp(email, code):
            return jsonify({"error": "Неверный или просроченный код"}), 401

        db_upsert_user({"email": email, "email_verified": True, "active": True})
        token = db_create_session(email, ttl_minutes=60)

        # Post-auth: реферал-атрибуция + авто-триал (только для юзеров с telegram_id)
        try:
            row = db_find_user_by_email(email)
            tid = row.get("telegram_id") if row else None
            if tid:
                ref = (body.get("ref") or "").strip()
                if ref:
                    # db_set_referred_by возвращает True только при УСПЕШНОЙ
                    # первой привязке (не при повторном переходе по ссылке).
                    if db_set_referred_by(int(tid), ref):
                        _notify_inviter_about_signup(ref)
                # idempotent — для grandfather/уже-платящих ничего не делает
                db_ensure_signup_trial(int(tid), days=TRIAL_DAYS)
        except Exception as e:
            logger.warning("post-auth (ref/trial) failed: %s", e)

        return jsonify({"ok": True, "token": token})
    except Exception as e:
        logger.exception("Ошибка api/auth/verify-otp: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/login-password", methods=["POST"])
def api_auth_login_password():
    """
    Вход по email + паролю (альтернатива OTP). Возвращает session token (60 мин).
    Тело: {email, password}.
    """
    try:
        body = request.get_json() or {}
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        if not email or not password:
            return jsonify({"error": "Введите email и пароль."}), 400
        row = db_find_user_by_email(email)
        # одинаковый ответ для всех неуспехов — не раскрываем, что именно не так
        if (not row or not row.get("active") or not row.get("password_hash")
                or not check_password_hash(row["password_hash"], password)):
            return jsonify({"error": "Неверный email или пароль."}), 401
        token = db_create_session(email, ttl_minutes=60)
        # Авто-триал (idempotent): покрывает кейс, если юзер не залогинился по email раньше
        try:
            tid = row.get("telegram_id")
            if tid:
                db_ensure_signup_trial(int(tid), days=TRIAL_DAYS)
        except Exception as e:
            logger.warning("auto-trial in login-password: %s", e)
        return jsonify({"ok": True, "token": token})
    except Exception as e:
        logger.exception("api/auth/login-password: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/tg-webapp", methods=["POST"])
def api_auth_tg_webapp():
    """
    Авторизация через Telegram Mini App. Валидируем initData (HMAC с BOT_TOKEN),
    извлекаем telegram_id → upsert юзера (синтетический email tg_<id>@kronos.internal
    если нет своего) → выдаём session-token (60 мин, как verify-otp).

    Поддержка реферала: t.me/<bot>?startapp=ref_<CODE> → start_param обработается.
    Auto-trial: новый юзер сразу получает TRIAL_DAYS дней.

    Тело: {init_data: <Telegram.WebApp.initData string>}
    """
    try:
        body = request.get_json() or {}
        init_data = (body.get("init_data") or "").strip()
        parsed = _validate_init_data(init_data)
        if not parsed:
            return jsonify({"error": "Invalid Telegram WebApp data"}), 401

        user_info = parsed.get("user") or {}
        try:
            tid = int(user_info.get("id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Missing telegram user id"}), 401
        username = user_info.get("username") or None
        start_param = (parsed.get("start_param") or "").strip()

        # Upsert: для новых — синтетический email; для существующих — оставляем их email
        existing = db_find_user_by_telegram_id(tid)
        email = (existing.get("email") if existing else None) or f"tg_{tid}@kronos.internal"
        db_upsert_user({
            "telegram_id": tid,
            "username": username,
            "email": email,
            "email_verified": True,
            "active": True,
        })

        # Реферал-атрибуция: ?startapp=ref_<CODE>
        if start_param.startswith("ref_"):
            try:
                ref_code = start_param[4:]
                # True только при первой успешной привязке.
                if db_set_referred_by(tid, ref_code):
                    _notify_inviter_about_signup(ref_code)
            except Exception as e:
                logger.warning("referral attribution failed: %s", e)

        # Авто-триал для новых (idempotent для grandfather/использовавших)
        try:
            db_ensure_signup_trial(tid, days=TRIAL_DAYS)
        except Exception as e:
            logger.warning("auto-trial failed: %s", e)

        token = db_create_session(email, ttl_minutes=60)
        return jsonify({"ok": True, "token": token})
    except Exception as e:
        logger.exception("api/auth/tg-webapp: %s", e)
        return jsonify({"error": str(e)}), 500


def _check_admin_secret() -> Optional[tuple]:
    """
    Проверяет ADMIN_SECRET из query-параметра admin_key или заголовка X-Admin-Key.
    Возвращает None если ок, иначе (jsonify(error), status_code).
    """
    admin_secret = getattr(config, "admin_secret", None) if config else None
    if not admin_secret:
        return jsonify({"error": "Admin secret not configured on server"}), 503
    provided = (
        request.headers.get("X-Admin-Key")
        or request.args.get("admin_key")
        or (request.get_json(silent=True) or {}).get("admin_key")
    )
    if not provided or provided != admin_secret:
        return jsonify({"error": "Unauthorized"}), 403
    return None


@app.route("/api/admin/users.csv")
def api_admin_users_csv():
    """
    Экспортирует всех пользователей в CSV.
    Защищено admin_key (query-параметр или X-Admin-Key header).

    Поля: id, telegram_id, username, email, role, active, preferred_server_id,
          email_verified, has_vless, peers_count, created_at
    """
    err = _check_admin_secret()
    if err is not None:
        return err
    try:
        from bot.database import db_get_all_users
        users = db_get_all_users()
        peers = get_all_peers()

        # Индекс: telegram_id → кол-во активных пиров
        peer_count: Dict[int, int] = {}
        for p in peers:
            if p.active:
                peer_count[p.telegram_id] = peer_count.get(p.telegram_id, 0) + 1

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "telegram_id", "username", "email", "role",
            "active", "preferred_server_id", "email_verified",
            "has_vless", "peers_count", "created_at",
        ])
        for u in users:
            tid = u.get("telegram_id")
            writer.writerow([
                u.get("id", ""),
                tid or "",
                u.get("username", ""),
                u.get("email", ""),
                u.get("role", "user"),
                "1" if u.get("active") else "0",
                u.get("preferred_server_id", ""),
                "1" if u.get("email_verified") else "0",
                "1" if u.get("vless_uuid") else "0",
                peer_count.get(tid, 0) if tid else 0,
                u.get("created_at", ""),
            ])

        csv_data = output.getvalue()
        filename = f"vpn_users_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            csv_data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Ошибка /api/admin/users.csv: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/sync-sheets", methods=["POST"])
def api_admin_sync_sheets():
    """
    Запускает синхронизацию пользователей в Google Sheets.
    Защищено admin_key.
    Возвращает {ok, updated, message} или {ok: false, error}.
    """
    err = _check_admin_secret()
    if err is not None:
        return err
    try:
        from bot.google_sheets import sync_users_to_sheets
        result = sync_users_to_sheets()
        status = 200 if result.get("ok") else 502
        return jsonify(result), status
    except ImportError:
        return jsonify({"ok": False, "error": "bot.google_sheets модуль не найден"}), 500
    except Exception as e:
        logger.exception("Ошибка /api/admin/sync-sheets: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    import os
    debug = os.environ.get("FLASK_ENV") == "development"
    port = int(os.environ.get("PORT", "5000"))
    # Биндим на localhost: nginx (на той же машине) проксирует :8443 → 127.0.0.1:5001.
    # Снаружи :5001 недоступен — HTTP без шифрования был бы дырой (пароли, токены).
    # Можно переопределить через FLASK_HOST=0.0.0.0 для отладки.
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=debug)
