import json
import tempfile
import threading
import time
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from core.editor import best_window
from core.media import run_command,MediaCancelled


class EditSpeedTests(unittest.TestCase):
    def test_legacy_event_clip_does_not_scan_video(self):
        with patch("core.editor.run_command",side_effect=AssertionError("Do not decode an event replay")):
            start,method=best_window("WarDogs_2026-10-27_19-30-20_mic_Reakcja.mp4",8,60)
        self.assertEqual(start,52)
        self.assertIn("starszego",method)

    def test_imported_clip_is_scanned_once_then_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/"imported.mp4"
            source.write_bytes(b"video")
            frames=np.stack([np.zeros((90,160),np.uint8),np.full((90,160),100,np.uint8),np.full((90,160),130,np.uint8)])
            with patch("core.editor.CONFIG_DIR",temp),patch("core.editor.run_command",return_value=(frames.tobytes(),b"")) as runner:
                first=best_window(source,2,10,gpu=False)
                second=best_window(source,2,10,gpu=False)
                self.assertEqual(first,second)
                runner.assert_called_once()
                self.assertNotIn("-ss",runner.call_args.args[0])

    def test_markers_are_preferred_to_legacy_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/"WarDogs_date_kill_Test.mp4"
            Path(str(source)+".json").write_text(json.dumps({"event_offsets":[20]}))
            start,method=best_window(source,8,60)
            self.assertAlmostEqual(start,14.8)
            self.assertEqual(method,"Znacznik akcji")

    def test_cancel_kills_only_owned_child_promptly(self):
        cancel=threading.Event()
        timer=threading.Timer(.3,cancel.set)
        timer.start()
        started=time.monotonic()
        with self.assertRaises(MediaCancelled):
            run_command([sys.executable,"-c","import time; time.sleep(30)"],cancelled=cancel.is_set)
        timer.join()
        self.assertLess(time.monotonic()-started,3)


if __name__=="__main__":unittest.main()
