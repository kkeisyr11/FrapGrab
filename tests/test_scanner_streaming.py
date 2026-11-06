import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from core.scanner import MatchScanner


class StreamingScannerTests(unittest.TestCase):
    def test_calibrated_scanner_uses_confirmed_hud_events_without_ocr_or_marker_duplicates(self):
        info={'format':{'duration':20},'streams':[{'codec_type':'video','width':100,'height':100}]}
        with tempfile.TemporaryDirectory() as folder:
            profile=Path(folder)/'profile.json';profile.write_text('{}')
            with patch('core.scanner.probe',return_value=info),\
                patch('core.scanner.load_config',return_value={'pixel_profile':str(profile),'gamertag':'Player'}),\
                patch('core.highlights.discover_events',return_value=[
                    {'time':8,'type':'kill','confidence':'player_hud'},
                    {'time':8.1,'type':'visual','confidence':'recorded_marker'},
                    {'time':9,'type':'audio','confidence':'voice_track'}]),\
                patch('rapidocr_onnxruntime.RapidOCR',side_effect=AssertionError('OCR not needed')):
                events=MatchScanner('clip.mp4','Player').scan()
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['timestamp'],8)

    def test_gpu_failure_restarts_a_sequential_scan_without_duplicate_events(self):
        info={'format':{'duration':2},'streams':[{'codec_type':'video','width':100,'height':100}]}
        frame=np.zeros((100,100,3),np.uint8).tobytes()
        attempt=[]
        def run(cmd,*args,**kwargs):
            attempt.append(cmd)
            kwargs['on_data'](frame[:17000])
            kwargs['on_data'](frame[17000:])
            if len(attempt)==1:raise RuntimeError('GPU decoder failed')
            kwargs['on_data'](frame)
        event={'signature':'same','event_type':'kill','raw_text':'Player Enemy'}
        with patch('core.scanner.probe',return_value=info),\
            patch('core.scanner.load_config',return_value={'killfeed_region':[0,0,1,1]}),\
            patch('core.scanner.find_binary',return_value='ffmpeg'),\
            patch('core.scanner.decode_backends',return_value=['cuda','cpu']),\
            patch('core.scanner.run_command',side_effect=run),\
            patch('core.scanner.parse_killfeed',return_value=[event]),\
            patch('rapidocr_onnxruntime.RapidOCR',return_value=Mock(return_value=([],None))),\
            self.assertLogs(level='ERROR'):
            result=MatchScanner('clip.mp4','Player').scan()
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['timestamp'],0)
        self.assertEqual(len(attempt),2)
        self.assertIn('-hwaccel',attempt[0])
        self.assertNotIn('-ss',attempt[0])
        self.assertNotIn('-ss',attempt[1])


if __name__=='__main__':unittest.main()
