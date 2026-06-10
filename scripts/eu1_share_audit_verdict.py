#!/usr/bin/env python3
"""
Вердикт по liveness-аудиту 9 инструментированных eu1 vless-tcp shared-UUID.

Читает /var/log/eu1-share-audit.log (его пишет eu1_share_audit_sampler.sh раз в
6ч). Когда набрано достаточно сэмплов (MIN_SAMPLES ≈ 6 дней) — выносит вердикт и
ОДИН раз шлёт владельцу в TG (dedup через marker-файл), чтобы «не забыть и
прогнать»:
  - все сэмплы «никто не использовался» → МЕРТВЫ, можно удалять.
  - хоть один auditshare_* появился → ЖИВ, не рубить вслепую.

Запускается из eu1_share_audit_sampler.sh в конце (после дозаписи лога).
Можно и вручную для статуса: venv/bin/python scripts/eu1_share_audit_verdict.py
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

LOG = pathlib.Path("/var/log/eu1-share-audit.log")
MARKER = pathlib.Path("/var/lib/eu1-share-audit.done")
MIN_SAMPLES = 24  # ~6 дней при cron каждые 6ч
DEAD_MARK = "никто из 9 не использовался"


def main() -> int:
    if not LOG.exists():
        print("лог ещё не создан")
        return 0
    lines = [ln for ln in LOG.read_text(encoding="utf-8").splitlines() if ln.strip()]
    n = len(lines)
    used_lines = [ln for ln in lines if DEAD_MARK not in ln]
    seen_uuids = sorted(set(re.findall(r"auditshare_[0-9a-f]+", "\n".join(used_lines))))

    print(f"сэмплов: {n}/{MIN_SAMPLES}; строк с использованием: {len(used_lines)}; "
          f"UUID замечены: {seen_uuids or '—'}")

    if MARKER.exists():
        print("вердикт уже отправлен (marker есть) — выход")
        return 0
    if not seen_uuids and n < MIN_SAMPLES:
        print("рано: нулевой трафик, но сэмплов недостаточно — ждём")
        return 0

    # есть вердикт: либо набрали окно с нулём, либо кто-то всплыл
    if seen_uuids:
        msg = (
            "⚠️ <b>Аудит 9 eu1-shared:</b> обнаружено ИСПОЛЬЗОВАНИЕ — это живые юзеры "
            "на старых ссылках, НЕ удалять вслепую.\n"
            f"UUID: {', '.join(seen_uuids)}\n"
            "Разобрать/мигрировать. Лог: /var/log/eu1-share-audit.log"
        )
    else:
        msg = (
            f"✅ <b>Аудит 9 eu1-shared:</b> ~{n // 4} дней нулевого трафика — мертвы.\n"
            "Можно удалять: <code>sync_eu1_vless.py --no-shared --force</code> "
            "(релей сохранится сам). Потом снять sampler-cron + instrument/sampler-скрипты.\n"
            "Детали: DONE_LIST 2026-06-10."
        )

    try:
        from health_check import send_tg  # noqa: E402
        from bot.config import load_config  # noqa: E402
        cfg = load_config()
        if cfg.bot_token and cfg.admin_id:
            ok = send_tg(cfg.bot_token, str(cfg.admin_id), msg)
            print(f"TG-вердикт отправлен: {ok}")
            if ok:
                MARKER.parent.mkdir(parents=True, exist_ok=True)
                MARKER.write_text("sent\n")
        else:
            print("нет bot_token/admin_id — вердикт не отправлен")
    except Exception as e:  # noqa: BLE001
        print(f"ошибка отправки вердикта: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
