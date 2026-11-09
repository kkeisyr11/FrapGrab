"""Local Valve Game State Integration for Counter-Strike 2 and Dota 2."""

import hmac
import json
import re
import secrets
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

GSI_PORT = 49381
_CFG_NAME = "gamestate_integration_frapgrab.cfg"
VALVE_GAMES = {
    "cs2": (730, Path("game/csgo/cfg"), ("provider", "map", "player_id", "player_match_stats")),
    "dota2": (570, Path("game/dota/cfg"), ("provider", "map", "player")),
}


def configure_valve_game(folder, game_id, token):
    _, cfg, fields = VALVE_GAMES[game_id]
    directory = Path(folder) / cfg
    if not directory.is_dir():
        raise ValueError("Wybierz główny folder instalacji wybranej gry Steam.")
    if game_id == "dota2":
        directory /= "gamestate_integration"
        directory.mkdir(exist_ok=True)
    path = directory / _CFG_NAME
    if path.is_file():
        source = path.read_text(encoding="utf-8")
        found = re.search(r'"token"\s+"([0-9a-f]{48})"', source)
        if not source.startswith('"Frap Grab"\n') or not found or f'http://127.0.0.1:{GSI_PORT}/events' not in source:
            raise ValueError("Istniejący plik konfiguracji Frap Grab ma inny format.")
        return found.group(1)
    token = token if re.fullmatch("[0-9a-f]{48}", token) else secrets.token_hex(24)
    data = "\n".join(f'    "{field}" "1"' for field in fields)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(f'''"Frap Grab"
{{
  "uri" "http://127.0.0.1:{GSI_PORT}/events"
  "timeout" "2.0"
  "buffer" "0.1"
  "throttle" "0.2"
  "heartbeat" "5.0"
  "auth"
  {{
    "token" "{token}"
  }}
  "data"
  {{
{data}
  }}
}}
''')
    return token


class ValveState:
    def __init__(self, game_id):
        self.game_id = game_id
        self.app_id = VALVE_GAMES[game_id][0]
        self.baseline = None

    def read(self, packet):
        if not isinstance(packet, dict):
            return []
        provider = packet.get("provider")
        if not isinstance(provider, dict) or provider.get("appid") != self.app_id:
            return []
        player, match = packet.get("player"), packet.get("map")
        if not isinstance(player, dict) or not isinstance(match, dict) or player.get("activity") != "playing":
            self.baseline = None
            return []
        player_id = player.get("steamid")
        if not isinstance(player_id, str) or not player_id:
            self.baseline = None
            return []
        if self.game_id == "cs2":
            identity = (player_id, match.get("name"), match.get("mode"))
            phase = match.get("phase")
            if provider.get("steamid") != player_id:
                return []  # While dead the player section can follow a teammate.
            if phase not in ("live", "gameover"):
                self.baseline = None
                return []
            stats = player.get("match_stats")
        else:
            identity = (player_id, match.get("matchid"))
            if match.get("game_state") not in ("DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", "DOTA_GAMERULES_STATE_POST_GAME"):
                self.baseline = None
                return []
            stats = player
        if not isinstance(stats, dict) or not identity[1]:
            return []
        counts = tuple(stats.get(name) for name in ("kills", "assists", "deaths"))
        if any(type(value) is not int or value < 0 for value in counts):
            return []
        previous, self.baseline = self.baseline, (identity, counts)
        if not previous or previous[0] != identity or any(new < old for old, new in zip(previous[1], counts)):
            return []
        return [kind for kind, old, new in zip(("kill", "assist", "death"), previous[1], counts) if new > old]


class ValveEvents:
    def __init__(self, game_id, token, port=GSI_PORT):
        self.state = ValveState(game_id)
        self.last_packet = None
        self.events = deque(maxlen=32)
        self.lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def setup(handler):
                handler.request.settimeout(.6)
                super().setup()

            def do_POST(handler):
                if handler.path != "/events":
                    handler.send_error(404)
                    return
                try:
                    size = int(handler.headers.get("Content-Length", 0))
                    if not 0 < size <= 65536:
                        raise ValueError
                    packet = json.loads(handler.rfile.read(size))
                    auth = packet.get("auth") if isinstance(packet, dict) else None
                    provided = auth.get("token") if isinstance(auth, dict) else None
                except (ValueError, OSError, RecursionError):
                    handler.send_error(400)
                    return
                if not isinstance(provided, str) or not provided.isascii() or not hmac.compare_digest(provided, token):
                    handler.send_error(403)
                    return
                provider = packet.get("provider")
                if not isinstance(provider, dict) or provider.get("appid") != self.state.app_id:
                    handler.send_error(400)
                    return
                stamp = time.monotonic()
                with self.lock:
                    if self.last_packet is not None and stamp - self.last_packet > 12:
                        self.state.baseline = None
                    self.last_packet = stamp
                    self.events.extend((kind, stamp) for kind in self.state.read(packet))
                handler.send_response(204)
                handler.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
        self.thread.start()

    def poll(self):
        with self.lock:
            events = list(self.events)
            self.events.clear()
        return events

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
