import pathlib
from dataclasses import dataclass
from typing import Dict


@dataclass
class BotConfig:
    bot_token: str
    admin_id: int
    base_dir: pathlib.Path
    mtproto_proxy_link: str | None = None


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

    return BotConfig(
        bot_token=token,
        admin_id=admin_id,
        base_dir=base_dir,
        mtproto_proxy_link=mtproto_proxy_link,
    )


