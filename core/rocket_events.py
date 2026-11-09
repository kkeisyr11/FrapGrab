"""Local, read-only Rocket League Stats API client."""

import json
import os
import tempfile
import time
from pathlib import Path

from websocket import WebSocketException, WebSocketTimeoutException, create_connection
from .games import ROCKET_STATS_PORT


STATS_SECTION = "[TAGame.MatchStatsExporter_TA]"


def enable_stats_api(folder):
    config = Path(folder) / "TAGame" / "Config"
    candidates = (config / "TAStatsAPI.ini", config / "DefaultStatsAPI.ini")
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise ValueError("Wybierz główny folder instalacji Rocket League.")
    original = path.read_bytes()
    if original.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
    source = original.decode(encoding)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().casefold() == STATS_SECTION.casefold()), None)
    if start is None:
        start = len(lines)
        lines.append(STATS_SECTION)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    entries = {}
    for index in range(start + 1, end):
        key, sep, value = lines[index].partition("=")
        if sep:
            entries[key.strip().casefold()] = index, value.split(";", 1)[0].strip()

    def number(key):
        try:
            return float(entries[key][1])
        except (KeyError, ValueError):
            return 0

    tcp = number("port") if "port" in entries else 49123
    web = number("webport") if "webport" in entries else ROCKET_STATS_PORT
    if not 0 < web <= 65535 or web != int(web) or web == tcp:
        web = ROCKET_STATS_PORT if tcp != ROCKET_STATS_PORT else ROCKET_STATS_PORT + 1
    changes = {}
    if not 0 < number("packetsendrate") <= 120:
        changes["PacketSendRate"] = 5
    expected_web = number("webport") if "webport" in entries else ROCKET_STATS_PORT
    if "webport" not in entries or expected_web != web:
        changes["WebPort"] = int(web)
    if not changes:
        return int(web)
    for key, value in changes.items():
        position = entries.get(key.casefold())
        if position:
            old_line = lines[position[0]]
            _, comment, text = old_line.partition(";")
            lines[position[0]] = f"{key}={value}" + (f" ;{text}" if comment else "")
        else:
            lines.insert(end, f"{key}={value}")
    updated = (newline.join(lines) + newline).encode(encoding)
    try:
        with path.with_suffix(path.suffix + ".frapgrab.bak").open("xb") as backup:
            backup.write(original)
    except FileExistsError:
        pass
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(updated)
            stream.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return int(web)


class RocketEvents:
    def __init__(self, port=ROCKET_STATS_PORT):
        self.url = f"ws://127.0.0.1:{port}"
        self.connection = None
        self.retry_at = 0.0
        self.baseline = None
        self.replay_file = False

    def close(self):
        if self.connection is not None:
            self.connection.shutdown()
            self.connection = None
        self.baseline = None
        self.replay_file = False

    def poll(self, nickname):
        if self.connection is None:
            if time.monotonic() < self.retry_at:
                return []
            self.retry_at = time.monotonic() + 2
            try:
                self.connection = create_connection(
                    self.url, timeout=.35, suppress_origin=True, http_no_proxy=["127.0.0.1"],
                )
                self.connection.settimeout(.035)
            except (OSError, WebSocketException):
                self.close()
                return []
        highlights = []
        deadline = time.monotonic() + .08
        try:
            while time.monotonic() < deadline:
                message = self.connection.recv()
                if not message:
                    self.close()
                    break
                if len(message) > 262144:
                    self.close()
                    break
                try:
                    events = self.read(json.loads(message), nickname)
                except (ValueError, RecursionError):
                    continue
                highlights.extend((kind, time.monotonic()) for kind in events)
        except WebSocketTimeoutException:
            pass
        except (OSError, WebSocketException):
            self.close()
        return highlights

    def read(self, message, nickname):
        if not isinstance(message, dict):
            return []
        event = message.get("Event")
        if event in ("ReplayCreated", "MatchCreated", "MatchDestroyed"):
            self.baseline = None
            self.replay_file = event == "ReplayCreated"
            return []
        data = message.get("Data")
        if event != "UpdateState" or self.replay_file or not isinstance(data, dict):
            return []
        match_id, players, game = data.get("MatchGuid"), data.get("Players"), data.get("Game")
        if not isinstance(match_id, str) or not match_id or not isinstance(players, list) or not isinstance(game, dict):
            return []
        matches = [player for player in players if isinstance(player, dict)
                   and isinstance(player.get("Name"), str) and player["Name"].casefold() == nickname.casefold()]
        if len(matches) != 1:
            self.baseline = None
            return []
        player = matches[0]
        player_id = player.get("PrimaryId")
        stats = tuple(player.get(field) for field in ("Goals", "Assists", "Saves"))
        if not player_id or any(type(value) is not int or value < 0 for value in stats):
            return []
        key = (match_id, player_id)
        previous = self.baseline[1] if self.baseline and self.baseline[0] == key else None
        if previous is None:
            if game.get("bReplay") is False:
                self.baseline = key, stats
            return []
        self.baseline = key, tuple(max(old, new) for old, new in zip(previous, stats))
        return [kind for kind, old, new in zip(("goal", "assist", "save"), previous, stats) if new > old]
