import unittest

from core.games import requires_nickname, select_game
from core.league_events import LeagueEvents


def kill(event_id, stamp, killer, assisters=()):
    return {
        "EventID": event_id, "EventTime": stamp, "EventName": "ChampionKill",
        "KillerName": killer, "Assisters": list(assisters),
    }


def snapshot(clock, *events):
    return {
        "activePlayer": {"riotId": "PlayerOne#FRAP", "summonerName": "PlayerOne"},
        "gameData": {"gameTime": clock},
        "events": {"Events": list(events)},
    }


class LeagueEventsTests(unittest.TestCase):
    def setUp(self):
        self.detector = LeagueEvents()

    def test_tracks_only_the_local_players_kills_and_assists_once(self):
        past = kill(1, 100, "PlayerOne")
        self.assertEqual(self.detector.read(snapshot(100, past)), [])
        current = snapshot(102, past, kill(2, 101, "PlayerOne#FRAP"), kill(3, 101.5, "PlayerOne#Other"),
                           kill(4, 101.75, "Teammate", ["playerone#frap"]))
        self.assertEqual(self.detector.read(current), [("kill", 1), ("assist", .25)])
        self.assertEqual(self.detector.read(current), [])

    def test_new_game_and_foreground_reset_do_not_export_history(self):
        self.detector.read(snapshot(200, kill(20, 200, "PlayerOne")))
        self.assertEqual(self.detector.read(snapshot(1)), [])
        self.assertEqual(self.detector.read(snapshot(5, kill(1, 4, "PlayerOne"))), [("kill", 1)])
        self.detector.reset()
        self.assertEqual(self.detector.read(snapshot(5, kill(1, 4, "PlayerOne"))), [])

    def test_switching_game_keeps_the_war_dogs_profile(self):
        league = select_game({"game_id": "wardogs", "gamertag": "PlayerOne"}, "league")
        self.assertFalse(requires_nickname(league["game_id"]))
        self.assertEqual(league["gamertag"], "")
        self.assertEqual(select_game(league, "wardogs")["gamertag"], "PlayerOne")
