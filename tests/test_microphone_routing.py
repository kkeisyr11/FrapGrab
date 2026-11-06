"""Recording switches must not control event detection or route chat into it."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import numpy as np

from core.audio_capture import DesktopAudio,MicrophoneMonitor,audio_thread
from core.config import DEFAULT_CONFIG
from core.highlights import discover_events
from core.live_detector import LiveDetector


class MicrophoneRoutingTests(unittest.TestCase):
    def test_monitor_opens_and_closes_the_device_on_the_same_worker(self):
        owners=[]
        with patch('core.audio_capture.DesktopAudio') as audio:
            audio.side_effect=lambda *args,**kwargs:(owners.append(threading.get_ident()) or Mock(
                close=lambda:owners.append(threading.get_ident())))
            monitor=MicrophoneMonitor(Mock())
            monitor.start()
            monitor.close()
        self.assertEqual(len(owners),2)
        self.assertEqual(owners[0],owners[1])
        self.assertNotEqual(owners[0],threading.get_ident())

    def test_audio_thread_balances_its_own_com_initialization_on_errors(self):
        for result,uninitialize in ((0,True),(1,True),(-2147417850,False)):
            with self.subTest(result=result),patch('core.audio_capture.ctypes.windll.ole32') as ole:
                ole.CoInitializeEx.return_value=result
                with self.assertRaisesRegex(RuntimeError,'inside'):
                    with audio_thread():raise RuntimeError('inside')
                self.assertEqual(ole.CoUninitialize.call_count,int(uninitialize))

    def test_monitor_runs_with_microphone_recording_on_or_off(self):
        for recorded in (False,True):
            with self.subTest(recorded=recorded),patch('core.live_detector.load_config',return_value={
                **DEFAULT_CONFIG,'record_microphone':recorded,'mic_enabled':True}),\
                patch('core.live_detector.MicrophoneMonitor') as audio,\
                patch('core.live_detector.keyboard.add_hotkey'),\
                patch('core.live_detector.keyboard.remove_hotkey'):
                detector=LiveDetector()
                detector.is_running=True
                detector.refresh_settings()
                audio.assert_called_once_with(detector.process_volume)
                audio.return_value.start.assert_called_once()
                detector.stop()
                audio.return_value.close.assert_called_once()

    def test_failed_microphone_still_starts_visual_detection(self):
        with patch('core.live_detector.load_config',return_value={**DEFAULT_CONFIG,'mic_enabled':True}),\
            patch('core.live_detector.MicrophoneMonitor') as audio,\
            patch('core.live_detector.keyboard.add_hotkey'),\
            patch('core.live_detector.keyboard.remove_hotkey'),\
            patch('core.live_detector.threading.Thread') as worker:
            audio.return_value.start.side_effect=OSError('device unavailable')
            status=Mock()
            detector=LiveDetector(on_status=status)
            detector.start()
            self.assertTrue(detector.is_running)
            self.assertIsNone(detector.mic_stream)
            worker.assert_called_once_with(target=detector._loop,daemon=True)
            worker.return_value.start.assert_called_once()
            audio.return_value.close.assert_called_once()
            status.assert_called_once()
            detector.stop()

    def test_meter_only_capture_has_no_socket_queue_or_writer(self):
        manager=Mock()
        manager.get_default_wasapi_device.return_value={
            'index':7,'defaultSampleRate':48000,'maxInputChannels':1,'name':'Test microphone'}
        with patch('pyaudiowpatch.PyAudio',return_value=manager),\
            patch('core.audio_capture.socket.socket') as socket,\
            patch('core.audio_capture.threading.Thread') as writer:
            levels=[]
            monitor=DesktopAudio('microphone',lambda *args:levels.append(args),monitor_only=True)
            monitor.start()
            data=np.full(1024,16384,dtype=np.int16).tobytes()
            monitor._callback(data,1024,None,0)
            self.assertEqual(levels,[(100,'microphone')])
            self.assertIsNone(monitor.queue)
            socket.assert_not_called()
            writer.assert_not_called()
            monitor.close()
            manager.get_default_wasapi_device.assert_called_once_with(d_in=True)

    def test_visual_autoclips_are_independent_of_both_microphone_switches(self):
        from gui.app_window import FrapGrabApp
        for recorded in (False,True):
            for reactions in (False,True):
                with self.subTest(recorded=recorded,reactions=reactions):
                    app=SimpleNamespace(armed=True,manual_pending=False,game_foreground=True,
                        replay_buffer=SimpleNamespace(available_seconds=40,is_recording=True,state='recording'),session_actions=0,
                        metric_labels={'actions':Mock()},pending_auto=None,activity=Mock(),
                        config_data={**DEFAULT_CONFIG,'record_microphone':recorded,'mic_enabled':reactions})
                    FrapGrabApp._trigger(app,'visual','kill','')
                    self.assertEqual(app.pending_auto['event_types'],['visual'])

    def test_offline_analysis_never_uses_chat_or_mix_as_microphone(self):
        for mic in (False,True):
            with self.subTest(microphone_track=mic),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'clip.mp4'
                path.write_bytes(b'test')
                Path(str(path)+'.json').write_text(json.dumps({'events':[{'time':2,'type':'mic'}]}))
                streams=[{'index':0,'codec_type':'video','width':64,'height':64},
                    {'index':1,'codec_type':'audio','tags':{'title':'Frap Grab mix'}},
                    {'index':2,'codec_type':'audio','tags':{'title':'Frap Grab chat'}}]
                if mic:streams.append({'index':3,'codec_type':'audio','tags':{'title':'Frap Grab microphone'}})
                def decode(cmd,*args,**kwargs):
                    self.assertEqual(cmd[cmd.index('-map')+1],'0:3')
                    samples=np.zeros(16000*5,dtype=np.float32)
                    samples[16000:32000]=.3
                    kwargs['on_data'](samples.tobytes())
                with patch('core.highlights.load_config',return_value=DEFAULT_CONFIG.copy()),\
                    patch('core.highlights.CONFIG_DIR',folder),\
                    patch('core.highlights.find_binary',return_value='ffmpeg'),\
                    patch('core.highlights.run_command',side_effect=decode) as decoder:
                    events=discover_events(path,{'format':{'duration':5},'streams':streams})
                self.assertIn({'time':2.0,'type':'mic','confidence':'recorded_marker'},events)
                self.assertEqual(decoder.call_count,int(mic))
                self.assertEqual(len([e for e in events if e['type']=='audio']),int(mic))


if __name__=='__main__':unittest.main()
