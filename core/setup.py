"""First-run settings and the shared nickname requirement."""
import re
from pathlib import Path
from .config import validate_config
from .events import normalize
from .games import DEFAULT_GAME, requires_nickname, select_game


NICKNAME_HELP="Nick jest wymagany do wykrywania Twoich eliminacji i analizy nagrań. F8 i reakcje głosowe działają bez nicku."
ROCKET_NICKNAME_HELP="Wpisz nazwę z tablicy wyników Rocket League, żeby zapisywać własne akcje."


def clean_nickname(value, game_id=DEFAULT_GAME):
    if game_id == "rocket_league":
        return str(value).strip()
    return re.sub(r"^\s*\[[^\]]+\]\s*","",str(value)).strip()


def valid_nickname(value, game_id=DEFAULT_GAME):
    value=clean_nickname(value, game_id)
    if game_id == "rocket_league":
        return 1 <= len(value) <= 128 and not any(c in value for c in "\r\n\t")
    return 3<=len(value)<=64 and len(normalize(value))>=3 and not any(c in value for c in "\r\n\t")


def complete_setup(existing,draft):
    selected=select_game(existing, draft.get("game_id", existing.get("game_id", DEFAULT_GAME)))
    config={**selected,**draft}
    game_id = selected["game_id"]
    nickname=clean_nickname(config.get("gamertag",""), game_id)
    if requires_nickname(game_id) and (nickname or config.get("killfeed_enabled", True)) and not valid_nickname(nickname, game_id):
        raise ValueError(ROCKET_NICKNAME_HELP if game_id == "rocket_league" else
                         "Wpisz swój nick z gry (minimum 3 znaki) albo wyłącz automatyczną detekcję.")
    folder=Path(str(config.get("save_folder","")).strip()).expanduser()
    if not str(config.get("save_folder","")).strip():raise ValueError("Wybierz folder nagrań.")
    config.update(gamertag=nickname,setup_completed=True,auto_gpu_settings=True,auto_hud=True,detection_mode="pixel")
    if nickname!=selected.get("gamertag",""):
        config["pixel_profile"]=""
    config=validate_config(config)
    folder.mkdir(parents=True,exist_ok=True)
    config["save_folder"]=str(folder.resolve())
    return config
