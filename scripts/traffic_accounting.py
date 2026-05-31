#!/usr/bin/env python3
"""
Периодический сэмплер трафика AmneziaWG → накопительный учёт в SQLite.

Запускается по cron (каждые 5 минут). Читает текущие счётчики rx/tx из
`awg show awg0 dump` и копит lifetime-трафик в таблице traffic_accounting
(reset-aware, см. bot.database.db_accumulate_traffic).

Зачем cron, если /api/traffic тоже накапливает: панель смотрят нерегулярно,
а между просмотрами пользователь может перегенерировать конфиг (новый pubkey,
старые счётчики исчезают). Cron гарантирует, что трафик не теряется.
"""

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bot.storage import get_all_peers
from bot.database import db_accumulate_traffic, db_record_traffic_snapshot, init_db


def _awg_dump() -> str:
    """awg живёт внутри Docker-контейнера amnezia-awg2."""
    try:
        out = subprocess.run(
            ["docker", "exec", "amnezia-awg2", "awg", "show", "awg0", "dump"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return ""


def main() -> int:
    init_db()
    dump = _awg_dump()
    if not dump.strip():
        print("traffic_accounting: empty awg dump, skip", flush=True)
        return 0

    # pubkey -> (rx, tx); первая строка dump — интерфейс, пропускаем
    transfer = {}
    for line in dump.strip().split("\n")[1:]:
        parts = line.split("\t")
        if len(parts) >= 7:
            try:
                transfer[parts[0].strip()] = (int(parts[5]), int(parts[6]))
            except (ValueError, IndexError):
                continue
    if not transfer:
        print("traffic_accounting: no peers in awg dump, skip", flush=True)
        return 0

    samples = []
    total_bytes_this_run = 0
    for peer in get_all_peers():
        if peer.server_id != "eu1" or not peer.active:
            continue
        pk = (peer.public_key or "").strip()
        if pk in transfer:
            rx, tx = transfer[pk]
            samples.append({
                "public_key": pk,
                "telegram_id": peer.telegram_id,
                "rx": rx,
                "tx": tx,
            })
            total_bytes_this_run += rx + tx

    db_accumulate_traffic(samples)
    # Snapshot history для диагностики «кто качал в N мск» (14 дней rolling).
    # См. db_record_traffic_snapshot + scripts/traffic_diagnosis.py.
    db_record_traffic_snapshot(samples)
    # Видимая лог-строка — чтобы `journalctl -t traffic-accounting` не молчал
    # и было легко увидеть что cron жив и какое-то значение отщёлкивает.
    print(
        f"traffic_accounting: sampled {len(samples)} peers, "
        f"session rx+tx={total_bytes_this_run / 1024**2:.1f} MB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
