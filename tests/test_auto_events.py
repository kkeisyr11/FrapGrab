import tempfile
import unittest
from pathlib import Path

from core.config import validate_config
from core.events import ClipEventFilter, clip_event_label, parse_killfeed
from core.games import select_game
from core.rocket_events import RocketEvents, enable_stats_api


class AutoEventTests(unittest.TestCase):
    def test_gallery_labels_legacy_kill_and_grouped_events(self):
        self.assertEqual(clip_event_label({"reason": "visual"}), "Zabójstwo")
        self.assertEqual(clip_event_label({"reason": "kill", "events": [
            {"type": "kill"}, {"type": "death"}, {"type": "knockdown"}, {"type": "kill"},
        ]}), "Zabójstwo · Śmierć · Powalenie")
        self.assertEqual(clip_event_label({"reason": "unknown", "events": [{"type": []}]}), "")

    def test_war_dogs_distinguishes_victim_and_attacker_for_knockdowns(self):
        box = [(0, 0), (100, 0), (100, 10), (0, 10)]
        for text, expected in (
            ("PLAYER powalił Enemy", "knockdown"), ("Enemy powalił PLAYER", "downed"),
            ("Enemy PLAYER", "death"), ("PLAYER Downed", "kill"),
        ):
            self.assertEqual(parse_killfeed([(box, text, .95)], "PLAYER", 300)[0]["event_type"], expected)

    def test_assists_can_match_a_kill_before_or_after_without_saving_the_kill(self):
        selection = ClipEventFilter()
        early = ("assist", "", "", 100)
        late = ("assist", "", "", 109)
        unrelated = ("assist", "", "", 120)
        self.assertEqual(selection.select(early, ["assist"], 8), [])
        self.assertEqual(selection.select(("kill", "", "", 104), ["assist"], 8), [early])
        self.assertEqual(selection.select(late, ["assist"], 8), [late])
        self.assertEqual(selection.select(unrelated, ["assist"], 8), [])
        self.assertEqual(selection.select(("kill", "", "", 130), ["assist"], 8), [])

    def test_event_settings_follow_the_selected_game(self):
        wardogs = validate_config({"clip_events": ["kill", "downed"], "assist_near_seconds": 8})
        rocket = select_game(wardogs, "rocket_league")
        self.assertEqual(rocket["clip_events"], ["goal", "assist", "save"])
        restored = select_game(rocket, "wardogs")
        self.assertEqual(restored["clip_events"], ["kill", "downed"])
        self.assertEqual(restored["assist_near_seconds"], 8)

    def test_rocket_uses_own_live_stats_once_and_ignores_replay_files(self):
        adapter = RocketEvents()

        def update(goals, assists, saves, match="match-1", replay=False):
            return {"Event": "UpdateState", "Data": {
                "MatchGuid": match, "Game": {"bReplay": replay}, "Players": [
                    {"Name": "Player", "PrimaryId": "Steam|123|0", "Goals": goals, "Assists": assists, "Saves": saves},
                    {"Name": "Teammate", "PrimaryId": "Steam|456|0", "Goals": 20, "Assists": 0, "Saves": 0},
                ],
            }}

        self.assertEqual(adapter.read(update(2, 1, 1), "Player"), [])
        self.assertEqual(adapter.read(update(3, 2, 2, replay=True), "Player"), ["goal", "assist", "save"])
        self.assertEqual(adapter.read(update(3, 2, 2), "Player"), [])
        adapter.read({"Event": "ReplayCreated"}, "Player")
        self.assertEqual(adapter.read(update(6, 2, 2, replay=True), "Player"), [])
        adapter.read({"Event": "MatchCreated"}, "Player")
        self.assertEqual(adapter.read(update(0, 0, 0, match="match-2"), "Player"), [])
        self.assertEqual(adapter.read(update(0, 0, 1, match="match-2"), "Player"), ["save"])

    def test_rocket_setup_preserves_custom_port_and_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "TAGame" / "Config"
            config.mkdir(parents=True)
            path = config / "DefaultStatsAPI.ini"
            original = b"[TAGame.MatchStatsExporter_TA]\r\nPacketSendRate=0\r\nWebPort=49000\r\n[Other]\r\nPacketSendRate=88\r\n"
            path.write_bytes(original)
            self.assertEqual(enable_stats_api(folder), 49000)
            self.assertEqual(path.read_bytes(), original.replace(b"PacketSendRate=0", b"PacketSendRate=5"))
            self.assertEqual(path.with_suffix(".ini.frapgrab.bak").read_bytes(), original)
            self.assertEqual(enable_stats_api(folder), 49000)
