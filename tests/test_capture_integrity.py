import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from core.config import DEFAULT_CONFIG
from core.highlights import merge_ranges,source_integrity
from core.replay_buffer import ReplayBuffer


class CaptureIntegrityTests(unittest.TestCase):
    def test_manifest_ignores_an_incomplete_append_until_the_line_is_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'first.mp4').write_bytes(b'first');(root/'second.mp4').write_bytes(b'second')
            manifest=root/'segments.csv';manifest.write_text('first.mp4,0,2\nsecond.mp4,2,4.0')
            buffer=ReplayBuffer();buffer.temp_dir=folder
            self.assertEqual(len(buffer._read_segments()),1)
            with manifest.open('a') as stream:stream.write('21354\n')
            self.assertEqual(buffer._read_segments()[-1][2],4.021354)

    def test_bounded_manifest_tail_keeps_the_latest_recording_after_a_long_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'kept.mp4').write_bytes(b'kept')
            data=''.join(f'old_{i:08}.mp4,{i*2},{i*2+2}\n' for i in range(6000))+'kept.mp4,12000,12002\n'
            (root/'segments.csv').write_text(data)
            buffer=ReplayBuffer();buffer.temp_dir=folder
            rows=buffer._read_segments()
            self.assertEqual([(p.name,a,b) for p,a,b in rows],[('kept.mp4',12000,12002)])

    def test_background_export_completion_does_not_open_a_dialog_over_the_game(self):
        from gui.app_window import FrapGrabApp
        app=SimpleNamespace(_finish_studio_job=Mock(),_show_completed_movie=Mock(return_value='0:20'),
            job_status=Mock(),activity=Mock(),active_page='live',game_foreground=True)
        with patch('gui.app_window.messagebox.showinfo') as info,patch('gui.app_window.messagebox.showwarning') as warning:
            FrapGrabApp._render_done(app,Path('nonexistent-audit-test.mp4'))
            info.assert_not_called();warning.assert_not_called()
            app.game_foreground=False
            FrapGrabApp._render_done(app,Path('nonexistent-audit-test.mp4'))
            info.assert_called_once()

    def test_legacy_out_of_file_marker_is_reported_instead_of_silently_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            clip=Path(folder)/'clip.mp4'
            Path(str(clip)+'.json').write_text(json.dumps({'events':[{'time':26.25,'type':'visual'}]}))
            warning=source_integrity(clip,20)
        self.assertEqual(warning['invalid_markers'],1)
        self.assertFalse(warning['truncated'])

    def test_old_buffer_cannot_accept_new_automatic_events_after_alt_tab(self):
        from gui.app_window import FrapGrabApp
        for recording,state in ((False,'idle'),(True,'starting'),(False,'error')):
            with self.subTest(recording=recording,state=state):
                app=SimpleNamespace(armed=True,manual_pending=False,game_foreground=True,
                    replay_buffer=SimpleNamespace(available_seconds=40,is_recording=recording,state=state),
                    pending_auto=None,session_actions=0)
                FrapGrabApp._trigger(app,'visual','kill','')
                self.assertIsNone(app.pending_auto)
                self.assertEqual(app.session_actions,0)

    def test_stopping_early_preserves_the_requested_start_and_reports_missing_action(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'session_test';source.mkdir()
            for index in (30,32,34,36,38):(source/f'{index}.mp4').write_bytes(b'segment')
            (source/'segments.csv').write_text(''.join(f'{n}.mp4,{n},{n+2}\n' for n in (30,32,34,36,38)))
            cfg={**DEFAULT_CONFIG,'save_folder':str(root/'clips')}
            statuses=[]
            with patch('core.replay_buffer.load_config',return_value=cfg),\
                patch('core.replay_buffer.BUFFER_TEMP_DIR',folder),\
                patch('core.replay_buffer.get_ffmpeg_path',return_value='ffmpeg'),\
                patch('core.replay_buffer.run_media',side_effect=lambda cmd,out,**kwargs:Path(out).write_bytes(b'replay')):
                buffer=ReplayBuffer(on_status=lambda *args:statuses.append(args))
                buffer.temp_dir=str(source);buffer._origin=100
                result=buffer.export_last_buffer('visual','',20,150,[145],['visual'])
            meta=json.loads(Path(result+'.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['recording']['start'],30)
            self.assertEqual(meta['recording']['end'],40)
            self.assertEqual(meta['events'],[])
            self.assertEqual(meta['missing_events'],[{'time':15,'type':'visual'}])
            self.assertTrue(meta['truncated'])
            self.assertEqual(statuses[-1][0],'warning')
            self.assertEqual(buffer.state,'idle')

    def test_action_wholly_after_the_stopped_buffer_does_not_export_unrelated_footage(self):
        buffer=ReplayBuffer();buffer._origin=100
        with patch.object(buffer,'_read_segments',return_value=[(Path('old.mp4'),0,20)]),\
            self.assertRaisesRegex(RuntimeError,'poza zapisanym buforem'):
            buffer.export_last_buffer('visual','',20,160,[155],['visual'])

    def test_clamped_ranges_are_positive_and_finite(self):
        self.assertEqual(merge_ranges([(22.75,29.75),(-8,-2),(float('nan'),4),(float('inf'),20),(18,25)],20),[[18,20]])

    def test_warning_keeps_the_actual_capture_state(self):
        buffer=ReplayBuffer();buffer.state='recording'
        buffer._status('warning','partial clip')
        self.assertEqual(buffer.state,'recording')


if __name__=='__main__':unittest.main()
