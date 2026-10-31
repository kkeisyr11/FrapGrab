import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.config import load_config, DEFAULT_REPOSITORY,migrate_legacy_config,validate_config
from core.games import game_choices,matches_game_process
from core.highlights import voice_stream_indices
from tools.audit_release import contains_private


class PublicationTests(unittest.TestCase):
    def test_public_repository_reference_does_not_exempt_a_private_player_name(self):
        repo='PlayerOne/Recorder'
        for text in (repo,'https://github.com/'+repo+'/releases'):
            self.assertFalse(contains_private(text,['PlayerOne'],[repo]))
        for text in ('PlayerOne','PlayerOne/Other','prefixPlayerOne/Recorder',
                     'PlayerOne/RecorderPrivate','https://github.com/'+repo+' PlayerOne'):
            self.assertTrue(contains_private(text,['PlayerOne'],[repo]))

    def test_only_supported_games_are_offered_and_launchers_do_not_start_capture(self):
        self.assertEqual(game_choices(), {'War Dogs': 'wardogs'})
        self.assertTrue(matches_game_process('WarDogs-Win64-Shipping.exe'))
        for name in ('WarDogsLauncher.exe','WarDogsCrashReport.exe','OtherGame.exe'):
            self.assertFalse(matches_game_process(name))
        self.assertFalse(matches_game_process('WarDogs.exe','unsupported'))
        self.assertEqual(validate_config({'game_id':'unsupported'})['game_id'],'wardogs')

    def test_renamed_app_preserves_legacy_preferences_without_overwriting_new_ones(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder)/'old.json', Path(folder)/'new.json'
            data={'gamertag':'ExamplePlayer','pixel_profile':'C:/UserProfile/hud.json',
                  'save_folder':'D:/MyClips','manual_replay_seconds':300}
            old.write_text(json.dumps(data),encoding='utf-8')
            migrate_legacy_config(old,new)
            self.assertEqual(json.loads(new.read_text()),data)
            new.write_text('{"language":"en"}',encoding='utf-8')
            migrate_legacy_config(old,new)
            self.assertEqual(json.loads(new.read_text()),{'language':'en'})
            self.assertEqual(json.loads(old.read_text()),data)

    def test_existing_voice_tracks_remain_usable_after_rename(self):
        tags=['AutoClip microphone','AutoClip chat','Frap Grab microphone','Frap Grab chat','Frap Grab mix']
        streams=[{'index':i,'codec_type':'audio','tags':{'handler_name':tag}} for i,tag in enumerate(tags)]
        self.assertEqual(voice_stream_indices(streams),[0,1,2,3])

    def test_previous_official_feed_follows_the_renamed_repository(self):
        cfg=self.load({'github_repository':'pkgilarski/AutoClip','auto_update_check':False})
        self.assertEqual(cfg['github_repository'],DEFAULT_REPOSITORY)
        self.assertFalse(cfg['auto_update_check'])

    def load(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('core.config.CONFIG_FILE', str(path)):
                return load_config()

    def test_prepublication_profile_gets_feed_without_losing_player_settings(self):
        cfg = self.load({'github_repository': '', 'auto_update_check': False,
                         'gamertag': 'ExamplePlayer', 'manual_replay_seconds': 300})
        self.assertEqual(cfg['github_repository'], DEFAULT_REPOSITORY)
        self.assertTrue(cfg['auto_update_check'])
        self.assertEqual((cfg['gamertag'], cfg['manual_replay_seconds']), ('ExamplePlayer', 300))

    def test_explicit_feed_and_update_opt_out_are_preserved(self):
        for repository in (DEFAULT_REPOSITORY, 'other/project'):
            cfg = self.load({'github_repository': repository, 'auto_update_check': False})
            self.assertEqual(cfg['github_repository'], repository)
            self.assertFalse(cfg['auto_update_check'])
