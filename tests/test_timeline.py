import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import cv2
import numpy as np
from core.timeline import visual_offset,deduplicate_jobs
from core.hud_probes import auxiliary_profiles,HudCapture


class TimelineTests(unittest.TestCase):
    def test_moving_replay_alignment_requires_several_matching_frames(self):
        rng=np.random.default_rng(128)
        sequence=rng.integers(0,255,(40,54,96),dtype=np.uint8)
        found=visual_offset(sequence[:30],sequence[10:])
        self.assertEqual(found["offset"],5)
        self.assertGreaterEqual(found["matching_frames"],4)

    def test_static_view_and_one_similar_frame_do_not_remove_other_actions(self):
        sky=np.full((20,54,96),120,np.uint8)
        self.assertIsNone(visual_offset(sky,sky))
        rng=np.random.default_rng(42)
        a=rng.integers(0,255,(20,54,96),dtype=np.uint8)
        b=rng.integers(0,255,(20,54,96),dtype=np.uint8);b[8]=a[12]
        self.assertIsNone(visual_offset(a,b))

    def test_a_longer_replay_can_connect_two_previously_separate_groups(self):
        rng=np.random.default_rng(11)
        frames=rng.integers(0,255,(80,54,96),dtype=np.uint8)
        data={"a":frames[:20],"b":frames[40:60],"bridge":frames[10:50]}
        jobs=[(name,{"format":{"duration":len(data[name])*.5}},0,len(data[name])*.5,name) for name in data]
        with patch("core.timeline.fingerprints",side_effect=lambda p,*args:data[p]):
            out,report=deduplicate_jobs(jobs)
        self.assertAlmostEqual(sum(row[3] for row in out),30)
        self.assertAlmostEqual(report["removed_seconds"],10)

    def test_overlap_union_preserves_the_later_unique_assist_and_reaction(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/"kill.mp4",Path(temp)/"reaction.mp4"
            for p,start in ((a,0),(b,10)):
                Path(str(p)+".json").write_text(json.dumps({"recording":{"session":"same","start":start}}))
            ia={"format":{"duration":22}};ib={"format":{"duration":36}}
            jobs=[(a,ia,13.3,7.1,"action"),(b,ib,3.4,7,"action"),(b,ib,10.1,18.8,"assist and voice")]
            with patch("core.timeline.fingerprints",side_effect=AssertionError("Known coordinates need no video decoding")):
                out,report=deduplicate_jobs(jobs)
            self.assertAlmostEqual(report["removed_seconds"],7.3)
            self.assertEqual(len(out),1)
            self.assertEqual(out[0][0],b)
            self.assertAlmostEqual(out[0][2],3.3)
            self.assertAlmostEqual(out[0][3],25.6)

    def test_overlapping_sources_split_only_when_no_single_file_covers_the_union(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/"a",Path(temp)/"b"
            for p,start in ((a,0),(b,5)):
                Path(str(p)+".json").write_text(json.dumps({"recording":{"session":"same","start":start}}))
            info={"format":{"duration":10}}
            out,report=deduplicate_jobs([(a,info,2,8,"a"),(b,info,0,9,"b")])
            self.assertAlmostEqual(sum(row[3] for row in out),12)
            self.assertEqual([(r[0],r[2],r[3]) for r in out],[(a,2,8),(b,5,4)])

    def test_later_visual_event_cannot_shorten_a_pending_voice_recording(self):
        from gui.app_window import FrapGrabApp
        pending={"start":80,"end":120,"events":[95],"event_types":["mic"]}
        app=SimpleNamespace(armed=True,manual_pending=False,game_foreground=True,
            replay_buffer=SimpleNamespace(available_seconds=40),session_actions=1,
            metric_labels={"actions":Mock()},config_data={"clip_before_kill":15,"clip_after_kill":5},
            pending_auto=pending,activity=Mock())
        with patch("gui.app_window.time.monotonic",return_value=100):
            FrapGrabApp._trigger(app,"visual","kill","")
        self.assertEqual(pending["end"],120)
        self.assertEqual(pending["event_types"],["mic","visual"])


class AssistProbeTests(unittest.TestCase):
    def test_late_assist_extends_the_previous_kill_window_to_the_end(self):
        from core.highlights import highlight_ranges
        events=[{"time":35.375,"type":"kill"},{"time":39.125,"type":"kill"},
                {"time":43.875,"type":"assist"}]
        with patch("core.highlights.discover_events",return_value=events):
            ranges,_=highlight_ranges("helicopter.mp4",{"format":{"duration":43.973}})
        self.assertEqual(len(ranges),1)
        self.assertAlmostEqual(ranges[0][0]+ranges[0][1],43.973)

    def test_assist_is_a_separate_pixel_event_and_does_not_load_ocr(self):
        profile=auxiliary_profiles({"monitor_size":[2560,1440]})[0]
        image=np.zeros((115,410,3),np.uint8)
        template=cv2.imread(profile["template"])
        image[42:42+template.shape[0],67:67+template.shape[1]]=template
        class Capture:
            backend="test"
            def __init__(self,*args):pass
            def grab(self,*args):return image
            def close(self):pass
        with patch("core.pixel_detector.VisualPatch",Capture):
            hud=HudCapture([profile],{"left":0,"top":0,"width":2560,"height":1440})
            self.assertEqual(hud.rects[0][2:],(410,115))
            self.assertEqual(hud.read(),[])
            self.assertEqual(hud.read()[0][0],"assist")
            self.assertEqual(hud.read(),[])


if __name__=="__main__":unittest.main()
