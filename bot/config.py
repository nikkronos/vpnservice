import os
import pathlib
from dataclasses import dataclass
from typing import Dict


@dataclass
class BotConfig:
    bot_token: str
    admin_id: int
    base_dir: pathlib.Path
    mtproto_proxy_link: str | None = None
    # Скрипт ротации MTProxy Fake TLS на том же хосте, что и бот (команда /proxy_rotate, только владелец). См. docs/mtproxy-proxy-rotation.md
    mtproxy_rotate_script: str | None = None
    # URL страницы восстановления на web-панели
    vpn_recovery_url: str = "http://81.200.146.32:5001/recovery"
    # Share-ссылка vless:// для мобильного интернета (Xray REALITY), из VLESS_REALITY_SHARE_URL
    vless_reality_share_url: str | None = None


def _parse_env_file(path: pathlib.Path) -> Dict[str, str]:
    """
    Simple parser for env_vars.txt style files: KEY=VALUE per line, '#' comments allowed.
    """
    result: Dict[str, str] = {}
    if not path.exists():
        return result

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def load_config(env_path: str = "env_vars.txt") -> BotConfig:
    """
    Load bot configuration from env_vars.txt in the project root.
    """
    base_dir = pathlib.Path(__file__).resolve().parent.parent
    env_file = base_dir / env_path
    data = _parse_env_file(env_file)

    token = data.get("BOT_TOKEN")
    admin_raw = data.get("ADMIN_ID")

    if not token:
        raise RuntimeError("BOT_TOKEN is not set in env_vars.txt")
    if not admin_raw:
        raise RuntimeError("ADMIN_ID is not set in env_vars.txt")

    try:
        admin_id = int(admin_raw)
    except ValueError as exc:
        raise RuntimeError("ADMIN_ID must be an integer") from exc

    mtproto_proxy_link = data.get("MTPROTO_PROXY_LINK") or None
    if mtproto_proxy_link:
        mtproto_proxy_link = mtproto_proxy_link.strip()

    mtproxy_rotate_script = (data.get("MTPROXY_ROTATE_SCRIPT") or "").strip() or None

    vpn_recovery_url = (data.get("VPN_RECOVERY_URL") or "").strip()
    if not vpn_recovery_url:
        vpn_recovery_url = "http://81.200.146.32:5001/recovery"

    vless_reality_share_url = data.get("VLESS_REALITY_SHARE_URL") or None
    if vless_reality_share_url:
        vless_reality_share_url = vless_reality_share_url.strip()
        if not vless_reality_share_url.lower().startswith("vless://"):
            vless_reality_share_url = None

    return BotConfig(
        bot_token=token,
        admin_id=admin_id,
        base_dir=base_dir,
        mtproto_proxy_link=mtproto_proxy_link,
        mtproxy_rotate_script=mtproxy_rotate_script,
        vpn_recovery_url=vpn_recovery_url,
        vless_reality_share_url=vless_reality_share_url,
    )


def environment_for_mtproxy_rotate(base_dir: pathlib.Path) -> Dict[str, str]:
    """
    Окружение для subprocess скрипта ротации: копия os.environ плюс переменные MTPROXY_*
    из env_vars.txt (иначе бот их не передаёт в bash, т.к. читает файл только через load_config).
    """
    env: Dict[str, str] = dict(os.environ)
    data = _parse_env_file(base_dir / "env_vars.txt")
    for key, value in data.items():
        if key.startswith("MTPROXY_") and value.strip():
            env[key] = value.strip()
    return env


def get_effective_mtproto_proxy_link(bot_config: BotConfig) -> str | None:
    """
    Актуальная ссылка tg://proxy для пользователей.

    Если после ротации записан файл data/mtproto_proxy_link.txt (команда /proxy_rotate),
    он имеет приоритет над MTPROTO_PROXY_LINK в env_vars.txt — без перезапуска бота.
    Значение из env_vars.txt читается с диска при каждом вызове (fallback), чтобы веб-панель
    и бот не отдавали устаревшую ссылку после ручного правления env без перезапуска процесса.
    """
    override = bot_config.base_dir / "data" / "mtproto_proxy_link.txt"
    if override.exists():
        try:
            text = override.read_text(encoding="utf-8").strip()
            if text.startswith("tg://proxy"):
                return text
        except OSError:
            pass
    env = _parse_env_file(bot_config.base_dir / "env_vars.txt")
    link = (env.get("MTPROTO_PROXY_LINK") or "").strip()
    return link or None


