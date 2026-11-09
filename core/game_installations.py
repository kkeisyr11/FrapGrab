"""Locate locally installed games without starting their launchers."""
import json
import os
import re
from pathlib import Path

from .valve_events import VALVE_GAMES


def _read(path):
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def steam_game_folder(steam, app_id, required_directory):
    libraries = [steam]
    settings = _read(steam / "steamapps" / "libraryfolders.vdf")
    libraries.extend(Path(path.replace("\\\\", "\\")) for path in re.findall(r'"path"\s*"([^"]+)"', settings))
    for library in libraries:
        apps = library / "steamapps"
        manifest = _read(apps / f"appmanifest_{app_id}.acf")
        match = re.search(r'"installdir"\s*"([^"/\\:]+)"', manifest)
        if match and match[1] not in (".", ".."):
            folder = apps / "common" / match[1]
            if (folder / required_directory).is_dir():
                return folder
    return None


def epic_rocket_folder(manifests):
    for path in manifests.glob("*.item"):
        try:
            data = json.loads(_read(path))
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("AppName") != "Sugar":
            continue
        location = data.get("InstallLocation")
        if isinstance(location, str) and location:
            folder = Path(location)
            if (folder / "Binaries" / "Win64" / "RocketLeague.exe").is_file():
                return folder
    return None


def game_install_folder(game_id):
    if game_id == "rocket_league":
        program_data = os.environ.get("ProgramData")
        if program_data:
            epic = Path(program_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
            folder = epic_rocket_folder(epic)
            if folder:
                return folder
        app_id, required = 252950, Path("TAGame/Config")
    elif game_id in VALVE_GAMES:
        app_id, required, _ = VALVE_GAMES[game_id]
    else:
        return None
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam, _ = winreg.QueryValueEx(key, "SteamPath")
            return steam_game_folder(Path(steam), app_id, required)
        except (OSError, TypeError):
            return None
    return None
