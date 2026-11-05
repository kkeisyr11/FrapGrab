import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.editor import plan_ranges
from core.live_detector import LiveDetector


class CoverageTests(unittest.TestCase):
    def test_optional_preserve_mode_keeps_complete_clip(self):
        with patch("core.editor.best_window",side_effect=AssertionError("No guesswork in preserve mode")):
            self.assertEqual(plan_ranges("WarDogs_death_Clip.mp4",54,mode="preserve")[0][:2],(0,54))

    def test_all_markers_are_kept_even_when_far_apart(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"clip.mp4"
            Path(str(path)+".json").write_text(json.dumps({"event_offsets":[5,25,45]}))
            ranges=plan_ranges(path,54,8,"markers")
            for stamp in [5,25,45]:
                self.assertTrue(any(start<=stamp<=start+duration for start,duration,_ in ranges))

    def test_no_markers_means_no_footage_is_discarded(self):
        self.assertEqual(plan_ranges("missing_metadata.mp4",60,8,"markers")[0][:2],(0,60))

    def test_overlapping_event_ranges_are_joined_without_repeating_action(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"clip.mp4"
            Path(str(path)+".json").write_text(json.dumps({"event_offsets":[25,28]}))
            ranges=plan_ranges(path,60,10,"markers")
            self.assertEqual(len(ranges),1)
            self.assertGreater(ranges[0][1],10)

    def test_only_the_microphone_can_trigger_or_change_the_meter(self):
        events=[]
        levels=[]
        detector=LiveDetector(on_trigger_callback=lambda *args:events.append(args),on_volume_meter_callback=levels.append)
        detector.config.update(mic_enabled=True,mic_threshold=40,mic_cooldown=2)
        detector.is_running=True
        detector.process_volume(100,"chat")
        detector.process_volume(100,"system")
        self.assertEqual((events,levels),([],[]))
        detector.process_volume(80,"microphone")
        self.assertEqual(events[0][0],"mic")
        self.assertIn("microphone",events[0][2])
        self.assertEqual(levels,[80])


if __name__=="__main__":unittest.main()
