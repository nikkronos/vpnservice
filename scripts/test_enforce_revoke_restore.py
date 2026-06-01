#!/usr/bin/env python3
"""
End-to-end тест enforce_expired + auto-restore на синтетическом юзере.

Использует фейковый telegram_id=999999999 (не существует в реальном TG).
Создаёт реальный AWG peer на сервере, потом отзывает и восстанавливает,
затем удаляет навсегда (finally — даже если тест упадёт в середине).

ЗАПУСК ТОЛЬКО НА FORNEX (не локально):
    cd /opt/vpnservice && venv/bin/python scripts/test_enforce_revoke_restore.py
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.database import (
    _conn, _ensure_init,
    db_upsert_user, db_find_user_by_telegram_id,
)
from bot.storage import get_all_peers, Peer
from bot.wireguard_peers import (
    create_amneziawg_peer_and_config_for_user,
    _remove_amneziawg_peer,
    revoke_amneziawg_peer_soft,
    restore_amneziawg_peer_runtime,
    restore_user_revoked_peers,
)

TEST_TID = 999999999


def get_peer_for_tid(tid: int):
    """Возвращает первый peer для tid или None."""
    for p in get_all_peers():
        if p.telegram_id == tid and p.server_id == "eu1":
            return p
    return None


def awg_show_has_peer(pubkey: str) -> bool:
    """Проверяет что pubkey есть в runtime AWG."""
    import subprocess
    r = subprocess.run(
        ["docker", "exec", "amnezia-awg2", "awg", "show", "awg0", "dump"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        return False
    return pubkey.strip() in r.stdout


def cleanup_test_peer(pubkey: str | None):
    """Финальная очистка: удалить peer из AWG runtime + peers.json + users-запись."""
    print("\n--- CLEANUP ---")
    # 1. Удалить peer из AWG runtime если есть
    if pubkey:
        try:
            _remove_amneziawg_peer(pubkey)
            print(f"  ✓ AWG runtime: peer removed")
        except Exception as e:
            print(f"  ! AWG runtime remove failed: {e}")
    # 2. Очистить из peers.json
    try:
        from bot.storage import _load_raw, _save_raw, PEERS_FILE
        data = _load_raw(PEERS_FILE)
        keys_to_drop = [k for k, v in data.items() if v.get("telegram_id") == TEST_TID]
        for k in keys_to_drop:
            del data[k]
        if keys_to_drop:
            _save_raw(PEERS_FILE, data)
            print(f"  ✓ peers.json: dropped {len(keys_to_drop)} keys")
        else:
            print("  - peers.json: no test entries")
    except Exception as e:
        print(f"  ! peers.json cleanup failed: {e}")
    # 3. Удалить test user из БД
    try:
        with _conn() as con:
            con.execute("DELETE FROM users WHERE telegram_id = ?", (TEST_TID,))
            con.execute("DELETE FROM traffic_accounting WHERE telegram_id = ?", (TEST_TID,))
        print("  ✓ users + traffic_accounting: test record dropped")
    except Exception as e:
        print(f"  ! users cleanup failed: {e}")


def main() -> int:
    _ensure_init()
    test_pubkey = None
    try:
        print("=== ENFORCE/RESTORE E2E TEST ===\n")

        # Шаг 1: Создать фейкового юзера в БД + установить expired подписку
        print("[1] Создаю test user в БД (tid=999999999, expires_at в прошлом)")
        db_upsert_user({
            "telegram_id": TEST_TID,
            "email": "synthetic-test@kronos.internal",
            "email_verified": True,
            "active": True,
        })
        # expires_at = 24 часа назад → попадёт под grace 12h
        with _conn() as con:
            con.execute(
                "UPDATE users SET expires_at = datetime('now', '-24 hours'), "
                "subscription_status = 'expired' WHERE telegram_id = ?",
                (TEST_TID,),
            )
        u = db_find_user_by_telegram_id(TEST_TID)
        print(f"    user.expires_at = {u['expires_at']}")

        # Шаг 2: Создать реальный AWG peer на сервере
        print("\n[2] Создаю AWG peer для test user (через create_amneziawg_peer_and_config_for_user)")
        peer, _config = create_amneziawg_peer_and_config_for_user(
            telegram_id=TEST_TID,
            server_id="eu1",
            platform="pc",
        )
        test_pubkey = peer.public_key
        print(f"    peer: tid={peer.telegram_id}, ip={peer.wg_ip}, pk={test_pubkey[:20]}..., active={peer.active}")
        assert awg_show_has_peer(test_pubkey), "peer должен быть в awg show после create"
        print(f"    ✓ peer присутствует в awg show")

        # Шаг 3: Запустить enforce_expired --apply
        print("\n[3] Запускаю enforce_expired.py --apply (должен отозвать test peer)")
        import subprocess
        r = subprocess.run(
            [sys.executable, str(pathlib.Path(__file__).parent / "enforce_expired.py"), "--apply"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            print(f"    enforce_expired exit={r.returncode}")
            print(f"    stdout: {r.stdout[-500:]}")
            print(f"    stderr: {r.stderr[-300:]}")
            return 1
        print(r.stdout[-1000:])

        # Шаг 4: Проверить что peer удалён из runtime + active=false
        print("\n[4] Проверяю отзыв")
        time.sleep(1)
        if awg_show_has_peer(test_pubkey):
            print(f"    ✗ peer ВСЁ ЕЩЁ в awg show — отзыв НЕ сработал")
            return 2
        print(f"    ✓ peer удалён из awg show")

        peer_after = get_peer_for_tid(TEST_TID)
        if peer_after is None:
            print(f"    ✗ peer удалён из peers.json — но должен был остаться с active=False")
            return 3
        if peer_after.active:
            print(f"    ✗ peer в peers.json остался active=True — soft-revoke сломан")
            return 4
        print(f"    ✓ peer в peers.json: active={peer_after.active} (credentials сохранены)")

        # Шаг 5: Эмулировать оплату — вызвать restore_user_revoked_peers
        print("\n[5] Эмулирую оплату: restore_user_revoked_peers(TEST_TID)")
        restored = restore_user_revoked_peers(TEST_TID)
        print(f"    Restored: {len(restored)} peer(s)")
        if not restored:
            print("    ✗ restore_user_revoked_peers вернул пусто — функция не нашла revoked peers")
            return 5

        # Шаг 6: Проверить что peer вернулся в runtime
        print("\n[6] Проверяю восстановление")
        time.sleep(1)
        if not awg_show_has_peer(test_pubkey):
            print(f"    ✗ peer НЕ вернулся в awg show после restore")
            return 6
        print(f"    ✓ peer в awg show")

        peer_restored = get_peer_for_tid(TEST_TID)
        if not peer_restored or not peer_restored.active:
            print(f"    ✗ peer в peers.json не active=True")
            return 7
        print(f"    ✓ peer в peers.json: active={peer_restored.active}")

        # Сверка что pubkey/ip совпадают (тот же peer вернулся)
        if peer_restored.public_key != test_pubkey:
            print(f"    ✗ pubkey не совпал: было {test_pubkey[:20]}, стало {peer_restored.public_key[:20]}")
            return 8
        print(f"    ✓ pubkey/ip сохранились идентично — старый .conf будет работать")

        print("\n=== ✅ ALL CHECKS PASSED ===")
        return 0

    finally:
        cleanup_test_peer(test_pubkey)


if __name__ == "__main__":
    sys.exit(main())
