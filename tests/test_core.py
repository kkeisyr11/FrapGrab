import tempfile
import unittest
from pathlib import Path
from core.config import validate_config
from core.events import parse_killfeed
from core.media import encoder_args, concat_entry
from core.replay_buffer import ReplayBuffer
import json
import cv2
import numpy as np
import threading
from unittest.mock import patch
from core.pixel_detector import PixelMatcher,save_profile


def box(x, y, text, confidence=.96):
    return [[[x,y],[x+90,y],[x+90,y+18],[x,y+18]], text, confidence]


class KillfeedTests(unittest.TestCase):
    def test_identifies_both_roles_and_does_not_lose_multikill(self):
        results = [box(0,0,"[TEAM]clipper11"),box(230,0,"Enemy"),
                   box(0,35,"Enemy"),box(230,35,"clipper11"),
                   box(0,70,"clipper11"),box(230,70,"Other")]
        self.assertEqual([r["event_type"] for r in parse_killfeed(results,"clipper11",400)], ["kill","death","kill"])

    def test_no_substring_false_positive(self):
        self.assertEqual(parse_killfeed([box(0,0,"patryk Enemy")],"pat",400), [])

    def test_lone_nickname_is_not_an_event(self):
        self.assertEqual(parse_killfeed([box(0,0,"clipper11")],"clipper11",400), [])

    def test_ocr_digit_confusion_and_clan(self):
        self.assertEqual(parse_killfeed([box(0,0,"[TEAM]clipperll Enemy")],"clipper11",400)[0]["event_type"], "kill")

    def test_low_confidence_does_not_trigger(self):
        self.assertEqual(parse_killfeed([box(0,0,"clipper11 Enemy",.3)],"clipper11",400), [])

    def test_empty_nickname_does_not_trigger(self):
        self.assertEqual(parse_killfeed([box(0,0,"Name Enemy")],"",400), [])


class BufferTests(unittest.TestCase):
    def test_only_manifest_committed_files_are_exportable(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/"closed.mp4").write_bytes(b"closed")
            (folder/"open.mp4").write_bytes(b"still writing")
            (folder/"segments.csv").write_text("closed.mp4,0,2\nmissing.mp4,2,4\nbroken,0,\n")
            recorder = ReplayBuffer()
            recorder.temp_dir = temp
            rows = recorder._read_segments()
            self.assertEqual([(p.name,a,b) for p,a,b in rows], [("closed.mp4",0,2)])

    def test_empty_buffer_produces_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "napełnia"):
            ReplayBuffer().export_last_buffer()

    def test_software_encoder_never_gets_nvenc_preset(self):
        args = encoder_args("libx264", live=True)
        self.assertIn("ultrafast", args)
        self.assertNotIn("p2", args)

    def test_quality_setting_changes_real_bitrate(self):
        self.assertIn("50M", encoder_args("h264_nvenc", "Ultra"))
        self.assertIn("15M", encoder_args("h264_nvenc", "Medium"))

    def test_paths_with_apostrophes_are_escaped_for_concat(self):
        self.assertIn("'\\''", concat_entry("player's clip.mp4"))


class PreferencesTests(unittest.TestCase):
    def test_corrupt_values_cannot_break_recording(self):
        cfg = validate_config({"buffer_seconds": "oops", "capture_fps": 600,
                               "killfeed_region": [1,2,3,4], "mic_enabled": "false"})
        self.assertEqual(cfg["buffer_seconds"],60)
        self.assertEqual(cfg["capture_fps"],60)
        self.assertEqual(cfg["killfeed_region"],[.009,.435,.20,.11])
        self.assertFalse(cfg["mic_enabled"])


class PixelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = np.zeros((100,300,3),dtype=np.uint8)
        cv2.putText(self.patch,"PLAYER",(20,35),cv2.FONT_HERSHEY_SIMPLEX,.6,(240,240,240),1,cv2.LINE_AA)
        path = save_profile(self.temp.name,self.patch,(18,18,100,40),[0,0,1,1],(300,100))
        self.profile_path = path
        self.matcher = PixelMatcher(json.loads(Path(path).read_text()))

    def tearDown(self):
        self.temp.cleanup()

    def test_real_pixel_match_without_ocr(self):
        self.assertEqual(self.matcher.count_matches(self.patch)[0],1)
        other = np.zeros_like(self.patch)
        cv2.putText(other,"OTHERS",(20,35),cv2.FONT_HERSHEY_SIMPLEX,.6,(240,240,240),1,cv2.LINE_AA)
        self.assertEqual(self.matcher.count_matches(other)[0],0)

    def test_stable_notification_triggers_once(self):
        triggers = [self.matcher.update(self.patch)[0] for _ in range(8)]
        self.assertEqual(sum(triggers),1)

    def test_absent_then_reappearing_notification_can_trigger(self):
        for _ in range(3):self.matcher.update(self.patch)
        for _ in range(4):self.matcher.update(np.zeros_like(self.patch))
        self.assertEqual(sum(self.matcher.update(self.patch)[0] for _ in range(3)),1)

    def test_resolution_change_requires_recalibration(self):
        with self.assertRaises(ValueError):
            self.matcher.count_matches(np.zeros((120,320,3),dtype=np.uint8))

    def test_live_pixel_path_never_initializes_ocr(self):
        from core.config import DEFAULT_CONFIG
        from core.live_detector import LiveDetector
        cfg = {**DEFAULT_CONFIG,"detection_mode":"pixel","pixel_profile":self.profile_path,
               "killfeed_region":[0,0,1,1],"gamertag":"PLAYER","clip_events":["kill","assist"]}
        image = self.patch
        class FakeCapture:
            backend = "test"
            def __init__(self,*args):pass
            def grab(self,*args):return image
            def close(self):pass
        events=[]
        with patch("core.live_detector.load_config",return_value=cfg), \
             patch("core.live_detector.game_status",return_value=(True,True)), \
             patch("core.live_detector.output_geometry",return_value={"width":300,"height":100,"left":0,"top":0}), \
             patch("core.pixel_detector.VisualPatch",FakeCapture):
            detector = LiveDetector()
            detector.is_running = True
            detector.on_trigger_callback = lambda *args:(events.append(args),detector._stop.set())
            with patch.object(detector,"_get_ocr",side_effect=AssertionError("OCR must remain unloaded")) as ocr:
                worker = threading.Thread(target=detector._loop)
                worker.start()
                worker.join(timeout=2)
                detector._stop.set()
                worker.join(timeout=1)
                self.assertEqual(len(events),1)
                ocr.assert_not_called()
                self.assertIsNone(detector._ocr)


if __name__ == "__main__":
    unittest.main()
