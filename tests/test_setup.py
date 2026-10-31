import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.config import DEFAULT_CONFIG,validate_config,load_config,save_config
from core.setup import complete_setup,valid_nickname,clean_nickname


class FirstRunTests(unittest.TestCase):
    def test_failed_save_keeps_old_config_and_cleans_the_partial_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"config.json";path.write_text('{"gamertag":"PreviousPlayer"}',encoding="utf-8")
            with patch("core.config.CONFIG_DIR",temp),patch("core.config.CONFIG_FILE",str(path)), \
                 patch("core.config.os.replace",side_effect=PermissionError("read only")),patch("builtins.print"):
                self.assertFalse(save_config({**DEFAULT_CONFIG,"gamertag":"NewPlayer"}))
            self.assertEqual(json.loads(path.read_text())["gamertag"],"PreviousPlayer")
            self.assertEqual([p.name for p in Path(temp).iterdir()],["config.json"])
    def test_new_installation_has_no_player_or_private_hud(self):
        with tempfile.TemporaryDirectory() as temp,patch("core.config.CONFIG_FILE",str(Path(temp)/"missing.json")):
            cfg=load_config()
        self.assertEqual(cfg["gamertag"],"")
        self.assertEqual(cfg["pixel_profile"],"")
        self.assertFalse(cfg["setup_completed"])

    def test_existing_player_migrates_without_losing_settings_or_repeating_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"config.json"
            path.write_text(json.dumps({"gamertag":"ExamplePlayer","manual_replay_seconds":300}),encoding="utf-8")
            with patch("core.config.CONFIG_FILE",str(path)):cfg=load_config()
        self.assertTrue(cfg["setup_completed"])
        self.assertEqual((cfg["gamertag"],cfg["manual_replay_seconds"]),("ExamplePlayer",300))

    def test_automatic_detection_cannot_finish_with_a_missing_or_invalid_nickname(self):
        for nick in ("","ab","---","player\nname"):
            with self.subTest(nick=nick),self.assertRaises(ValueError):
                complete_setup(DEFAULT_CONFIG,{"gamertag":nick,"killfeed_enabled":True})

    def test_manual_and_voice_mode_can_finish_without_a_nickname(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=complete_setup(DEFAULT_CONFIG,{"gamertag":"","killfeed_enabled":False,"mic_enabled":True,
                "save_folder":str(Path(temp)/"Clips"),"manual_replay_seconds":300,"buffer_seconds":300})
            self.assertTrue(Path(cfg["save_folder"]).is_dir())
        self.assertEqual(cfg["gamertag"],"")
        self.assertTrue(cfg["mic_enabled"])
        self.assertTrue(cfg["setup_completed"])
        self.assertEqual(cfg["manual_replay_seconds"],300)

    def test_changing_the_player_clears_the_previous_template(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=complete_setup({**DEFAULT_CONFIG,"gamertag":"OldPlayer","pixel_profile":"private-template.json"},
                {"gamertag":"[TEAM] NewPlayer","save_folder":temp})
        self.assertEqual(cfg["gamertag"],"NewPlayer")
        self.assertEqual(cfg["pixel_profile"],"")
        self.assertTrue(valid_nickname(cfg["gamertag"]))

    def test_completed_manual_setup_stays_completed_without_a_player(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"config.json"
            path.write_text(json.dumps({"setup_completed":True,"gamertag":"","killfeed_enabled":False}),encoding="utf-8")
            with patch("core.config.CONFIG_FILE",str(path)):cfg=load_config()
        self.assertTrue(cfg["setup_completed"])
        self.assertFalse(cfg["killfeed_enabled"])
