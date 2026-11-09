import unittest

from core.banner_events import BANNER_PROFILES, BannerLatch, matches_banner
from core.config import validate_config
from core.games import GAME_EVENTS, matches_game_process


def box(text, left=10, top=10, width=140, height=30, confidence=.98):
    return ([(left, top), (left + width, top), (left + width, top + height),
             (left, top + height)], text, confidence)


class BannerEventsTests(unittest.TestCase):
    def test_profiles_have_distinct_phrases_and_only_victory_settings(self):
        for game, (_, phrases) in BANNER_PROFILES.items():
            with self.subTest(game=game):
                self.assertEqual(GAME_EVENTS[game], ("win",))
                self.assertEqual(validate_config({"game_id": game})["clip_events"], ["win"])
                self.assertTrue(matches_banner([box(phrases[0].upper())], phrases, 250))
                self.assertFalse(matches_banner([box("Eliminated Player")], phrases, 250))
        self.assertTrue(matches_game_process("TSLGame.exe", "pubg"))
        self.assertFalse(matches_game_process("TSLGame_BE.exe", "pubg"))

    def test_confidence_text_and_banner_size(self):
        phrases = BANNER_PROFILES["fortnite"][1]
        for negative in [box("Victory Royale", height=10), box("Victory Royale", confidence=.6),
                         box("Last Victory Royale"), box("Victory Royale Countdown")]:
            self.assertFalse(matches_banner([negative], phrases, 250))
        self.assertTrue(matches_banner([box("#1 VICTORY ROYALE!")], phrases, 250))

    def test_split_banner_requires_neighboring_boxes(self):
        phrases = BANNER_PROFILES["pubg"][1]
        first = box("Winner Winner")
        self.assertTrue(matches_banner([first, box("Chicken Dinner", left=168)], phrases, 250))
        self.assertTrue(matches_banner([first, box("Chicken Dinner", top=48)], phrases, 250))
        self.assertFalse(matches_banner([first, box("Chicken Dinner", left=230)], phrases, 250))
        self.assertFalse(matches_banner([first, box("Chicken Dinner", top=110)], phrases, 250))

    def test_latch_requires_confirmation_and_suppresses_duplicate_clips(self):
        latch = BannerLatch()
        self.assertIsNone(latch.observe(True, 1))
        self.assertIsNone(latch.observe(True, 4))
        self.assertEqual(latch.observe(True, 5), 4)
        self.assertIsNone(latch.observe(False, 6))
        self.assertIsNone(latch.observe(True, 7))
        for stamp in (8, 9, 10):
            self.assertIsNone(latch.observe(False, stamp))
        self.assertIsNone(latch.observe(True, 11))
        self.assertEqual(latch.observe(True, 12), 11)
