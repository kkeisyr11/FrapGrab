"""Read the active League of Legends match through Riot's loopback Game Client API."""

import http.client
import json
import math
import ssl
from pathlib import Path


def _identity(value):
    return value.strip().casefold() if isinstance(value, str) else ""


class LeagueEvents:
    def __init__(self):
        cert = Path(__file__).resolve().parents[1] / "assets" / "riotgames.pem"
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.tls.load_verify_locations(cafile=str(cert))
        # The local game certificate chains to Riot's root. Its DNS name may
        # differ from the fixed loopback address used by the Game Client API.
        self.tls.check_hostname = False
        self.reset()

    def reset(self):
        self.game_time = None
        self.last_id = -1

    def poll(self):
        connection = http.client.HTTPSConnection("127.0.0.1", 2999, timeout=.6, context=self.tls)
        try:
            connection.request("GET", "/liveclientdata/allgamedata")
            response = connection.getresponse()
            if response.status == 200:
                return self.read(json.loads(response.read(1024 * 1024)))
        except (OSError, http.client.HTTPException, ValueError):
            pass
        finally:
            connection.close()
        return []

    def read(self, snapshot):
        if not isinstance(snapshot, dict):
            return []
        clock = snapshot.get("gameData")
        player = snapshot.get("activePlayer")
        log = snapshot.get("events")
        if not all(isinstance(section, dict) for section in (clock, player, log)):
            return []
        game_time = clock.get("gameTime")
        events = log.get("Events")
        if type(game_time) not in (float, int) or not math.isfinite(game_time) or not isinstance(events, list):
            return []
        names = {_identity(player.get(field)) for field in ("riotId", "summonerName")} - {""}
        if not names:
            return []
        events = sorted(
            (event for event in events if isinstance(event, dict) and type(event.get("EventID")) is int),
            key=lambda event: event["EventID"],
        )
        if self.game_time is None or game_time < self.game_time - 2:
            self.last_id = events[-1]["EventID"] if events else -1
        self.game_time = game_time
        highlights = []
        for event in events:
            if event["EventID"] <= self.last_id:
                continue
            self.last_id = event["EventID"]
            if event.get("EventName") != "ChampionKill":
                continue
            stamp = event.get("EventTime")
            if type(stamp) not in (float, int) or not 0 <= game_time - stamp <= 3:
                continue
            assists = event.get("Assisters")
            if _identity(event.get("KillerName")) in names:
                highlights.append(("kill", game_time - stamp))
            elif isinstance(assists, list) and any(_identity(name) in names for name in assists):
                highlights.append(("assist", game_time - stamp))
        return highlights
