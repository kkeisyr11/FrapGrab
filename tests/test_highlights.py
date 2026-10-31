import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from core.highlights import highlight_ranges,audio_activity,_metadata_events,voice_stream_indices
from core.editor import VideoEditor
from core.media import run_command
import sys


class HighlightTests(unittest.TestCase):
    def test_mp4_voice_tracks_are_separated_from_gunfire_in_the_mix(self):
        streams=[{"index":1,"codec_type":"audio","tags":{"handler_name":"AutoClip mix"}},
                 {"index":2,"codec_type":"audio","tags":{"handler_name":"AutoClip microphone"}},
                 {"index":3,"codec_type":"audio","tags":{"handler_name":"AutoClip chat"}}]
        self.assertEqual(voice_stream_indices(streams),[2,3])
    def test_both_actual_kills_are_in_a_short_context_window(self):
        events=[{"time":41.125,"type":"kill"},{"time":43.375,"type":"kill"}]
        with patch("core.highlights.discover_events",return_value=events):
            ranges,_=highlight_ranges("clip.mp4",{"format":{"duration":54}})
        self.assertEqual(len(ranges),1)
        start,duration,_=ranges[0]
        self.assertAlmostEqual(start,37.625)
        self.assertAlmostEqual(duration,9.25)
        self.assertTrue(start<=44<=start+duration)

    def test_each_distant_event_survives_the_plan(self):
        events=[{"time":8,"type":"kill"},{"time":30,"type":"mic"},{"time":52,"type":"kill"}]
        with patch("core.highlights.discover_events",return_value=events):
            ranges,_=highlight_ranges("clip.mp4",{"format":{"duration":60}})
        for e in events:self.assertTrue(any(a<=e["time"]<=a+d for a,d,_ in ranges))
        self.assertLess(sum(d for _,d,_ in ranges),40)

    def test_unrecognized_clip_does_not_become_a_full_or_random_shot(self):
        with patch("core.highlights.discover_events",return_value=[]):
            ranges,_=highlight_ranges("clip.mp4",{"format":{"duration":60}})
        self.assertEqual(ranges,[])

    def test_stationary_loud_audio_is_not_the_whole_movie(self):
        self.assertEqual(audio_activity(np.full(16000*5,.5,np.float32)),[])

    def test_short_loud_audio_run_gets_a_bounded_event(self):
        samples=np.zeros(16000*10,np.float32)
        samples[16000*4:16000*5]=.2
        events=audio_activity(samples)
        self.assertEqual(len(events),1)
        self.assertAlmostEqual(events[0]["time"],4)
        self.assertAlmostEqual(events[0]["end"],5)

    def test_mixed_markers_keep_their_voice_type(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"clip.mp4"
            Path(str(p)+".json").write_text(json.dumps({"events":[{"time":5,"type":"kill"},{"time":20,"type":"mic"}]}))
            self.assertEqual([e["type"] for e in _metadata_events(p,30)],["kill","mic"])

    def test_no_events_produces_an_actionable_error_instead_of_a_bad_movie(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/"result.mp4"
            info={"format":{"duration":60},"streams":[{"codec_type":"video"}]}
            with patch("core.editor.probe",return_value=info),patch("core.highlights.discover_events",return_value=[]):
                with self.assertRaisesRegex(RuntimeError,"Nie rozpoznano"):
                    VideoEditor.create_montage(["clip.mp4"],out)
            self.assertFalse(out.exists())

    def test_streamed_analysis_does_not_duplicate_all_output_in_memory(self):
        chunks=[]
        stdout,_=run_command([sys.executable,"-c","import sys; sys.stdout.buffer.write(b'frames')"],on_data=chunks.append)
        self.assertEqual(b"".join(chunks),b"frames")
        self.assertEqual(stdout,b"")


if __name__=="__main__":unittest.main()
