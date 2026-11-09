"""First-run settings and the shared nickname requirement."""
import re
from pathlib import Path
from .config import validate_config
from .events import normalize
from .games import DEFAULT_GAME, requires_nickname, select_game


NICKNAME_HELP="Nick jest wymagany do wykrywania Twoich eliminacji i analizy nagrań. F8 i reakcje głosowe działają bez nicku."


def clean_nickname(value):
    return re.sub(r"^\s*\[[^\]]+\]\s*","",str(value)).strip()


def valid_nickname(value):
    value=clean_nickname(value)
    return 3<=len(value)<=64 and len(normalize(value))>=3 and not any(c in value for c in "\r\n\t")


def complete_setup(existing,draft):
    selected=select_game(existing, draft.get("game_id", existing.get("game_id", DEFAULT_GAME)))
    config={**selected,**draft}
    nickname=clean_nickname(config.get("gamertag",""))
    if config.get("killfeed_enabled",True) and requires_nickname(config.get('game_id','wardogs')) and not valid_nickname(nickname):
        raise ValueError("Wpisz swój nick z gry (minimum 3 znaki) albo wyłącz automatyczną detekcję.")
    if nickname and not valid_nickname(nickname):raise ValueError("Nick musi mieć od 3 do 64 znaków.")
    folder=Path(str(config.get("save_folder","")).strip()).expanduser()
    if not str(config.get("save_folder","")).strip():raise ValueError("Wybierz folder nagrań.")
    config.update(gamertag=nickname,setup_completed=True,auto_gpu_settings=True,auto_hud=True,detection_mode="pixel")
    if nickname!=selected.get("gamertag",""):
        config["pixel_profile"]=""
    config=validate_config(config)
    folder.mkdir(parents=True,exist_ok=True)
    config["save_folder"]=str(folder.resolve())
    return config
