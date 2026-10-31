import tempfile
import unittest
from unittest.mock import patch
from core.games import GAMES,select_game,requires_nickname
from core.config import validate_config
from core.setup import complete_setup


class GameProfileTests(unittest.TestCase):
    def test_player_settings_are_saved_per_game_and_global_recording_stays_unchanged(self):
        config=validate_config({'game_id':'wardogs','gamertag':'ExamplePlayer',
            'pixel_profile':'D:/Profiles/wardogs.json','auto_gpu_settings':False,
            'video_codec':'hevc_nvenc','mic_threshold':70})
        with patch.dict(GAMES,{'testgame':{'name':'Test game','requires_nickname':False,'process_keywords':('testgame',)}}):
            other=select_game(config,'testgame')
            self.assertEqual((other['gamertag'],other['pixel_profile']),('',''))
            self.assertFalse(other['auto_gpu_settings'])
            self.assertEqual(other['video_codec'],'hevc_nvenc')
            self.assertFalse(requires_nickname('testgame'))
            with tempfile.TemporaryDirectory() as folder:
                saved=complete_setup(other,{'gamertag':'','save_folder':folder,'killfeed_enabled':True})
            restored=select_game(saved,'wardogs')
            self.assertEqual((restored['gamertag'],restored['pixel_profile'],restored['mic_threshold']),
                ('ExamplePlayer','D:/Profiles/wardogs.json',70))

    def test_unimplemented_games_cannot_be_selected(self):
        with self.assertRaises(ValueError):select_game({},'unimplemented')
        self.assertTrue(requires_nickname('wardogs'))
