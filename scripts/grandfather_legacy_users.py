#!/usr/bin/env python3
"""
One-shot data migration: grandfather всех существующих активных юзеров.

Запускается ОДИН раз перед включением enforcement. Идемпотентно: повторный запуск
ничего не делает для юзеров с уже установленным expires_at.

Логика:
- Берёт всех users WHERE active=1 AND expires_at IS NULL.
- Ставит expires_at='2099-01-01T00:00:00', subscription_status='active'.
- Эти юзеры — legacy/grandfather, доступ без ограничения. db_is_access_active вернёт True.
- Новые юзеры (после запуска) пойдут через auto-trial (db_ensure_signup_trial) и получат 14 дней.

Usage (на сервере Fornex):
    cd /opt/vpnservice && venv/bin/python scripts/grandfather_legacy_users.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.database import _conn, init_db

GRANDFATHER_DATE = "2099-01-01T00:00:00"


def main() -> int:
    init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT id, telegram_id, email, username FROM users "
            "WHERE active = 1 AND expires_at IS NULL ORDER BY id"
        ).fetchall()
        count = len(rows)
        print(f"Найдено {count} активных юзеров без expires_at — grandfather до {GRANDFATHER_DATE}")
        if not count:
            print("Ничего делать не надо. Выход.")
            return 0
        for r in rows:
            tid = r["telegram_id"] or "-"
            email = r["email"] or "-"
            uname = r["username"] or "-"
            print(f"  id={r['id']:>3} tg={tid:>14} email={email:<40} username={uname}")

        con.execute(
            "UPDATE users SET expires_at = ?, subscription_status = 'active' "
            "WHERE active = 1 AND expires_at IS NULL",
            (GRANDFATHER_DATE,),
        )
        remaining = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE active = 1 AND expires_at IS NULL"
        ).fetchone()
        print(f"Готово. Осталось без expires_at: {remaining['n']} (должно быть 0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
