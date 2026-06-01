#!/usr/bin/env python3
"""
Отзыв доступа для юзеров с истёкшей подпиской (Enforcement Gap fix).

Default mode — DRY-RUN: ничего не меняет, только показывает кандидатов.
Реальный отзыв — флагом `--apply`.

Логика отзыва (Soft-revoke / Variant A):
1. Кандидат: `expires_at < now - GRACE_PERIOD_HOURS`, не grandfather, есть active AWG peer на eu1.
2. Действия при отзыве:
   - AmneziaWG peer: `awg set awg0 peer <pk> remove` + `amnezia-save-conf.sh`
     (peer-credentials в peers.json остаются с active=false для последующего восстановления)
   - `db_clear_sub_token(tid)` — VLESS subscription URL отдаст пустоту, клиент HAPP/Streisand отвалится за ~12 ч
   - Уведомление юзеру в TG
3. При восстановлении (`db_extend_subscription` после оплаты) — auto-recreate с теми же pubkey/ip:
   старый .conf на устройстве юзера снова работает.

Запуск:
    # Безопасная проверка — список кандидатов, ничего не делает
    /opt/vpnservice/venv/bin/python scripts/enforce_expired.py

    # Реальный отзыв (после подтверждения владельца после dry-run)
    /opt/vpnservice/venv/bin/python scripts/enforce_expired.py --apply
"""
from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# ── Конфигурация ──
GRACE_PERIOD_HOURS = 12


def _fmt_user(username: Optional[str], telegram_id: int) -> str:
    return f"@{username}" if username else f"id{telegram_id}"


def find_revoke_candidates() -> List[Dict]:
    """
    Возвращает список юзеров на отзыв доступа:
    - expires_at IS NOT NULL (не grandfather)
    - expires_at < now - GRACE_PERIOD_HOURS
    - Есть хотя бы один active AWG peer на server_id='eu1'

    Для каждого кандидата — список его peer'ов (platform, wg_ip, public_key).
    """
    # Ленивый импорт — чтобы dry-run без production-зависимостей не падал
    from bot.database import _conn, _ensure_init
    from bot.storage import get_all_peers

    _ensure_init()

    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT telegram_id, username, email, expires_at, subscription_status,
                   sub_token, vless_uuid, trial_used
            FROM users
            WHERE telegram_id IS NOT NULL
              AND expires_at IS NOT NULL
              AND datetime(expires_at) < datetime('now', '-{GRACE_PERIOD_HOURS} hours')
            ORDER BY expires_at
            """
        ).fetchall()

    # Index peers by telegram_id — только active eu1
    peers_by_uid: Dict[int, List] = {}
    for peer in get_all_peers():
        if peer.server_id != "eu1" or not peer.active:
            continue
        peers_by_uid.setdefault(peer.telegram_id, []).append(peer)

    candidates: List[Dict] = []
    for r in rows:
        tid = int(r["telegram_id"])
        user_peers = peers_by_uid.get(tid, [])
        if not user_peers:
            continue
        candidates.append({
            "telegram_id": tid,
            "username": r["username"],
            "email": r["email"],
            "expires_at": r["expires_at"],
            "subscription_status": r["subscription_status"],
            "trial_used": bool(r["trial_used"]),
            "sub_token": r["sub_token"],
            "peers": [
                {
                    "platform": p.platform,
                    "wg_ip": p.wg_ip,
                    "public_key": p.public_key,
                }
                for p in user_peers
            ],
        })
    return candidates


def _print_dry_run_report(candidates: List[Dict]) -> None:
    """Читаемый отчёт для проверки владельцем перед --apply."""
    print("=" * 78)
    print(f"ENFORCE EXPIRED — DRY RUN")
    print(f"Grace period: {GRACE_PERIOD_HOURS} часов после expires_at")
    print(f"Время сейчас (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 78)
    print(f"Кандидатов на отзыв: {len(candidates)}\n")

    if not candidates:
        print("✅ Нет юзеров с истёкшей подпиской И активным AWG peer'ом.")
        print("   Либо все продлены, либо у истёкших и так нет peer'а.")
        return

    for i, c in enumerate(candidates, 1):
        user = _fmt_user(c["username"], c["telegram_id"])
        peers = c["peers"]
        peer_summary = f"{len(peers)} peer" + ("ов" if len(peers) != 1 else "")
        # Подсчёт сколько часов прошло с expires
        try:
            exp_dt = datetime.fromisoformat(c["expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - exp_dt)
            hours_past = int(elapsed.total_seconds() / 3600)
            elapsed_str = f"{hours_past}ч назад" if hours_past < 48 else f"{hours_past // 24}д назад"
        except (ValueError, TypeError):
            elapsed_str = "n/a"

        print(f"{i:>3}. {user:<24}  tid={c['telegram_id']:<11}  истёк {elapsed_str:<10}  status={c['subscription_status']}")
        print(f"     email={c['email']}, expires_at={c['expires_at']}, trial_used={c['trial_used']}")
        if c["sub_token"]:
            print(f"     sub_token={c['sub_token'][:16]}... — будет очищен")
        else:
            print(f"     sub_token=(не выдан)")
        for p in peers:
            pk_short = p["public_key"][:20] + "..." if p["public_key"] else "(no pubkey)"
            print(f"     peer: {p['platform']:<8} ip={p['wg_ip']:<14} pk={pk_short}")
        print()

    print("=" * 78)
    print("ДЕЙСТВИЯ КОТОРЫЕ БУДУТ ВЫПОЛНЕНЫ при --apply:")
    print("=" * 78)
    print("Для каждого юзера:")
    print("  1. Для каждого AWG peer:")
    print("     - awg set awg0 peer <pubkey> remove (в контейнере amnezia-awg2)")
    print("     - amnezia-save-conf.sh (persist)")
    print("     - peers.json: active=false (credentials сохраняются для auto-restore)")
    print("  2. db_clear_sub_token(tid) — VLESS subscription URL вернёт пустой ответ")
    print("  3. TG-уведомление юзеру: «⚠ Срок подписки истёк ... доступ временно отозван»")
    print()
    print("При оплате (db_extend_subscription с reactivation hook):")
    print("  - Peer возвращается в runtime с теми ЖЕ pubkey/ip")
    print("  - Старый .conf на устройстве юзера снова работает")
    print("  - TG-уведомление: «✅ Подписка продлена — доступ восстановлен»")
    print()
    print("⚠ Это DRY RUN. Ничего не было изменено.")
    print("   Для реального отзыва: --apply")


def main() -> int:
    parser = argparse.ArgumentParser(description="Отзыв доступа для истёкших подписок (Soft-revoke)")
    parser.add_argument("--apply", action="store_true", help="Реально отозвать (default — dry-run)")
    args = parser.parse_args()

    candidates = find_revoke_candidates()

    if not args.apply:
        _print_dry_run_report(candidates)
        return 0

    # === Production режим: реальный отзыв ===
    return _apply_revocations(candidates)


def _apply_revocations(candidates: List[Dict]) -> int:
    """
    Выполняет реальный отзыв доступа для каждого кандидата.
    Soft-revoke: peer-credentials в peers.json остаются (active=false) для
    последующего auto-restore при оплате.

    Действия:
      1. Для каждого peer: revoke_amneziawg_peer_soft + upsert_peer(active=False)
      2. db_clear_sub_token(tid) — VLESS subscription URL отдаст пустую
      3. TG-уведомление юзеру (best-effort, не падаем если не дошло)
    """
    from bot.database import db_clear_sub_token, db_find_user_by_telegram_id
    from bot.storage import Peer, upsert_peer
    from bot.wireguard_peers import revoke_amneziawg_peer_soft
    from bot.config import load_config
    import json
    import urllib.request

    if not candidates:
        print("Кандидатов нет — ничего не делаем.")
        return 0

    print(f"=== APPLY REVOCATIONS — {len(candidates)} юзер(ов) ===\n")

    cfg = load_config()
    bot_token = getattr(cfg, "bot_token", None) if cfg else None
    notify_user_text = (
        "⚠ <b>Срок подписки истёк более 12 ч назад.</b>\n\n"
        "Доступ временно отозван. Продли подписку — доступ восстановится автоматически, "
        "твой существующий конфиг снова заработает."
    )

    revoked_count = 0
    failed_count = 0
    for i, c in enumerate(candidates, 1):
        tid = c["telegram_id"]
        user_label = _fmt_user(c["username"], tid)
        print(f"[{i}/{len(candidates)}] {user_label} (tid={tid})")

        # 1. Удалить каждый peer из runtime + пометить active=False в peers.json
        for p in c["peers"]:
            pk = p["public_key"]
            wg_ip = p["wg_ip"]
            platform = p["platform"]
            try:
                revoke_amneziawg_peer_soft(pk)
                # peers.json: active=False (credentials сохраняются)
                upsert_peer(Peer(
                    telegram_id=tid,
                    wg_ip=wg_ip,
                    public_key=pk,
                    server_id="eu1",
                    active=False,
                    platform=platform,
                ))
                print(f"    [OK] revoked peer pk={pk[:20]}... ip={wg_ip} platform={platform}")
                revoked_count += 1
            except Exception as e:
                print(f"    [FAIL] revoke peer pk={pk[:20]}... — {e}")
                failed_count += 1

        # 2. Очистка sub_token (VLESS подписки отвалятся через ~12 ч авто-refresh)
        if c.get("sub_token"):
            try:
                db_clear_sub_token(tid)
                print(f"    [OK] sub_token cleared")
            except Exception as e:
                print(f"    [FAIL] clear sub_token — {e}")

        # 3. TG-уведомление юзеру (best-effort через прямой Bot API)
        if bot_token:
            try:
                api_body = json.dumps({
                    "chat_id": tid,
                    "text": notify_user_text,
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
                print(f"    [OK] TG notification sent")
            except Exception as e:
                print(f"    [WARN] TG notify failed: {e}")

        print()

    print("=" * 78)
    print(f"ИТОГО: revoked={revoked_count} peer(ов), failed={failed_count}")
    print("=" * 78)

    # Уведомление владельцу — чтобы видел что cron реально отзывает
    # (без spam при пустых прогонах: только когда reviked > 0 или failures)
    if (revoked_count > 0 or failed_count > 0) and bot_token:
        admin_id = getattr(cfg, "admin_id", None) if cfg else None
        if admin_id:
            try:
                user_list = "\n".join(
                    f"  • {_fmt_user(c['username'], c['telegram_id'])} (истёк {c['expires_at']})"
                    for c in candidates
                )[:1500]
                owner_text = (
                    f"🔒 <b>enforce_expired: отзыв доступа</b>\n\n"
                    f"Отозвано peer'ов: {revoked_count}\n"
                    f"Ошибок: {failed_count}\n\n"
                    f"Юзеры:\n{user_list}\n\n"
                    f"<i>При оплате — peer вернётся auto-restore-хуком, "
                    f"старый .conf снова заработает.</i>"
                )
                api_body = json.dumps({
                    "chat_id": admin_id,
                    "text": owner_text,
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
                print(f"\n[OK] Уведомление владельцу отправлено")
            except Exception as e:
                print(f"\n[WARN] Owner notify failed: {e}")

    return 0 if failed_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
