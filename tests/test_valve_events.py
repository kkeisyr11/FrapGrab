import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from core.valve_events import ValveEvents, ValveState, configure_valve_game


def cs2(kills, assists=0, deaths=0, *, player="local", phase="live"):
    return {"provider": {"appid": 730, "steamid": "local"},
            "map": {"name": "de_mirage", "mode": "competitive", "phase": phase},
            "player": {"activity": "playing", "steamid": player,
                       "match_stats": {"kills": kills, "assists": assists, "deaths": deaths}}}


def dota(kills, assists=0, deaths=0, *, match="35123"):
    return {"provider": {"appid": 570},
            "map": {"matchid": match, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
            "player": {"activity": "playing", "steamid": "local", "kills": kills, "assists": assists, "deaths": deaths}}


class ValveEventTests(unittest.TestCase):
    def test_cs2_counts_own_actions_only_and_baselines_new_matches(self):
        state = ValveState("cs2")
        self.assertEqual(state.read(cs2(5)), [])
        self.assertEqual(state.read(cs2(20, player="spectated")), [])
        self.assertEqual(state.read(cs2(6, 1, 1)), ["kill", "assist", "death"])
        self.assertEqual(state.read(cs2(6, 1, 1)), [])
        self.assertEqual(state.read(cs2(7, 1, 1, phase="gameover")), ["kill"])
        self.assertEqual(state.read(cs2(0, phase="warmup")), [])
        self.assertEqual(state.read(cs2(0)), [])
        self.assertEqual(state.read(cs2(1)), ["kill"])

    def test_dota_matches_are_separate_and_repeated_packets_are_ignored(self):
        state = ValveState("dota2")
        self.assertEqual(state.read(dota(10)), [])
        self.assertEqual(state.read(dota(10, 1)), ["assist"])
        self.assertEqual(state.read(dota(10, 1)), [])
        self.assertEqual(state.read(dota(0, match="35124")), [])
        self.assertEqual(state.read(dota(1, match="35124")), ["kill"])

    def test_listener_requires_matching_token_and_game_on_loopback(self):
        token = "a" * 48
        feed = ValveEvents("cs2", token, port=0)
        self.addCleanup(feed.close)
        host, port = feed.server.server_address
        self.assertEqual(host, "127.0.0.1")

        def send(packet, auth=token):
            request = urllib.request.Request(f"http://{host}:{port}/events",
                data=json.dumps({**packet, "auth": {"token": auth}}).encode())
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 204)

        with self.assertRaises(urllib.error.HTTPError) as error:
            send(cs2(10), "different")
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as error:
            send(dota(10))
        self.assertEqual(error.exception.code, 400)
        send(cs2(5))
        send(cs2(6))
        self.assertEqual([kind for kind, _ in feed.poll()], ["kill"])
        self.assertEqual(feed.poll(), [])

    def test_game_configuration_is_idempotent_and_leaves_other_apps_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / "game/dota/cfg/gamestate_integration"
            cfg.mkdir(parents=True)
            other = cfg / "gamestate_integration_other.cfg"
            other.write_text("other", encoding="utf-8")
            token = configure_valve_game(folder, "dota2", "")
            self.assertEqual(len(token), 48)
            self.assertEqual(configure_valve_game(folder, "dota2", ""), token)
            self.assertEqual(other.read_text(encoding="utf-8"), "other")
            self.assertIn('"player" "1"', (cfg / "gamestate_integration_frapgrab.cfg").read_text(encoding="utf-8"))
