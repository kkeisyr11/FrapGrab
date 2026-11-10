import os
import json
from .games import GAMES, DEFAULT_GAME, GAME_EVENTS, PROFILE_KEYS, ROCKET_STATS_PORT

CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FrapGrab")
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_REPOSITORY = "kkeisyr11/FrapGrab"


def migrate_legacy_config(legacy_file, target_file):
    """Copy preferences on first renamed launch; never overwrite a newer profile."""
    from pathlib import Path
    source, target = Path(legacy_file), Path(target_file)
    if target.exists() or not source.is_file():return
    data = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(data, dict):raise ValueError('Invalid legacy profile')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents concurrent startup from overwriting preferences.
    with target.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=4)


try:
    migrate_legacy_config(os.path.join(os.path.dirname(CONFIG_DIR), 'AutoClipWarDogs', 'config.json'), CONFIG_FILE)
except (OSError, ValueError):
    pass

DEFAULT_CONFIG = {
    "game_id": DEFAULT_GAME,
    "game_profiles": {},
    "language": "pl",             # "pl" (Polski) or "en" (English)
    "gamertag": "",
    "setup_completed":False,
    "save_folder": os.path.join(os.path.expanduser("~"), "Videos", "FrapGrab"),
    "buffer_seconds": 60,
    "manual_replay_seconds":60,
    "auto_hud":True,
    "github_repository":DEFAULT_REPOSITORY,
    "auto_update_check":True,
    "claude_montage_enabled": False,
    "last_update_check":0,
    "manual_hotkey": "F8",
    "video_codec": "h264_nvenc",
    "video_quality": "High",
    "auto_gpu_settings": True,
    "mic_enabled": False,
    "mic_threshold": 45,          # 1 - 100%
    "mic_cooldown": 15,           # seconds
    "killfeed_enabled": True,
    "clip_events": None,
    "assist_near_seconds": 0,
    "rocket_stats_port": ROCKET_STATS_PORT,
    "gsi_token": "",
    "sound_alert": True,
    "clip_before_kill": 15,       # For scanner: seconds before kill
    "clip_after_kill": 5,         # For scanner: seconds after kill
    "export_format": "16:9",
    "auto_record_enabled": False,
    "record_only_in_game": True,
    "capture_fps": 60,
    "capture_output": 0,
    "desktop_audio": True,
    "record_microphone": True,
    "record_chat": True,
    "chat_device": "",          # empty: auto-detect Sonar; otherwise a WASAPI output name
    "killfeed_region": [0.009, 0.435, 0.20, 0.11],
    "detection_mode": "pixel",
    "pixel_profile": "",
    "update_url": ""              # URL feedu aktualizacji (GitHub API lub plik JSON)
}

def validate_config(data):
    config = DEFAULT_CONFIG.copy()
    if isinstance(data, dict):
        config.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    for key, lo, hi in [("buffer_seconds", 10, 1800), ("manual_replay_seconds",10,1800), ("last_update_check",0,4_000_000_000), ("capture_fps", 15, 60),
                        ("mic_threshold", 1, 100), ("mic_cooldown", 2, 120),
                        ("clip_before_kill", 2, 60), ("clip_after_kill", 0, 30), ("capture_output", 0, 15),
                        ("rocket_stats_port", 1, 65535)]:
        try:
            config[key] = max(lo, min(hi, int(config[key])))
        except (ValueError, TypeError, OverflowError):
            config[key] = DEFAULT_CONFIG[key]
    for key, default in DEFAULT_CONFIG.items():
        if isinstance(default, bool) and not isinstance(config[key], bool):
            config[key] = default
        elif isinstance(default, str) and not isinstance(config[key], str):
            config[key] = default
    if config["video_quality"] not in {"Medium", "High", "Ultra"}:
        config["video_quality"] = "High"
    if config["language"] not in ("pl","en"):config["language"]="pl"
    if config["game_id"] not in GAMES:config["game_id"]=DEFAULT_GAME
    allowed = GAME_EVENTS.get(config["game_id"], ())
    selected = config["clip_events"]
    config["clip_events"] = ([kind for kind in allowed if kind in selected]
                             if isinstance(selected, list)
                             else list(allowed[:2] if config["game_id"] == DEFAULT_GAME else allowed))
    if config["assist_near_seconds"] not in (0, 8, 15):
        config["assist_near_seconds"] = 0
    token = config["gsi_token"]
    if len(token) != 48 or set(token).difference("0123456789abcdef"):
        config["gsi_token"] = ""
    profiles=config['game_profiles']
    config['game_profiles']={key:{k:v for k,v in profile.items() if k in PROFILE_KEYS}
        for key,profile in profiles.items() if key in GAMES and isinstance(profile,dict)} if isinstance(profiles,dict) else {}
    config["buffer_seconds"]=max(config["buffer_seconds"],config["manual_replay_seconds"])
    if config["detection_mode"] not in {"pixel", "ocr"}:
        config["detection_mode"] = "pixel"
    try:
        x, y, w, h = [float(v) for v in config["killfeed_region"]]
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1-x and 0 < h <= 1-y):
            raise ValueError()
        config["killfeed_region"] = [x, y, w, h]
    except (TypeError, ValueError):
        config["killfeed_region"] = DEFAULT_CONFIG["killfeed_region"].copy()
    return config

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data,dict) and "setup_completed" not in data and (data.get("gamertag") or data.get("pixel_profile")):
                    data={**data,"setup_completed":True}
                # Pre-publication profiles had no release feed. Enable the official
                # feed once; an existing repository and opt-out stay unchanged.
                if isinstance(data,dict) and not data.get("github_repository"):
                    data={**data,"github_repository":DEFAULT_REPOSITORY,"auto_update_check":True}
                elif isinstance(data,dict) and data.get("github_repository") in ('pkgilarski/AutoClip','https://github.com/pkgilarski/AutoClip','pkgilarski/FrapGrab','https://github.com/pkgilarski/FrapGrab'):
                    data={**data,"github_repository":DEFAULT_REPOSITORY}
                return validate_config(data)
        except Exception:
            pass
    return validate_config({})

def save_config(config: dict):
    path=None
    try:
        import tempfile
        fd, path = tempfile.mkstemp(dir=CONFIG_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(validate_config(config), f, indent=4, ensure_ascii=False)
        os.replace(path, CONFIG_FILE)
        return True
    except Exception as e:
        if path:
            try:os.unlink(path)
            except OSError:pass
        print(f"Błąd zapisu config: {e}")
        return False
