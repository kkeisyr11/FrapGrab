import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.highlights import select_events
from core.editor import plan_montage


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.events=[{"time":10,"type":"kill"},{"time":11,"type":"visual"},
                     {"time":16,"type":"assist"},{"time":35,"type":"assist"},
                     {"time":40,"type":"mic"},{"time":42,"type":"audio","end":43}]

    def test_kills_only_excludes_assist_and_voice_anchors(self):
        result=select_events(self.events,{"kills":True,"assists":False,"voice":False})
        self.assertEqual([e["type"] for e in result],["kill","visual"])

    def test_nearby_assists_do_not_keep_distant_assists(self):
        result=select_events(self.events,{"voice":False,"assist_near_seconds":8})
        self.assertEqual([e["time"] for e in result],[10,11,16])

    def test_assists_only_and_voice_only_are_independent(self):
        self.assertEqual([e["time"] for e in select_events(self.events,{"kills":False,"voice":False})],[16,35])
        self.assertEqual([e["type"] for e in select_events(self.events,{"kills":False,"assists":False})],["mic","audio"])

    def test_nearby_assist_in_a_different_overlapping_file_uses_shared_time(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/"kill",Path(temp)/"assist"
            for p,start in ((a,0),(b,10)):
                Path(str(p)+".json").write_text(json.dumps({"recording":{"session":"same","start":start}}))
            def events(path,*args):return [{"time":15,"type":"kill"}] if path==a else [{"time":10,"type":"assist"},{"time":28,"type":"assist"}]
            info={"format":{"duration":40},"streams":[{"codec_type":"video"}]}
            with patch("core.editor.probe",return_value=info),patch("core.highlights.discover_events",side_effect=events):
                plan=plan_montage([a,b],event_options={"kills":True,"assists":True,"voice":False,"assist_near_seconds":8})
            self.assertEqual(plan["selected_events"][1]["events"],[{"time":10,"type":"assist"}])
            self.assertLess(plan["estimated_duration"],20)

    def test_empty_filters_do_not_make_an_unrelated_movie(self):
        info={"format":{"duration":60},"streams":[{"codec_type":"video"}]}
        with patch("core.editor.probe",return_value=info),patch("core.highlights.discover_events",return_value=self.events):
            with self.assertRaisesRegex(ValueError,"filtr"):
                plan_montage(["clip"],event_options={"kills":False,"assists":False,"voice":False})

    def test_preview_counts_crossfades_instead_of_reporting_source_length(self):
        info={"format":{"duration":60},"streams":[{"codec_type":"video"}]}
        with patch("core.editor.probe",return_value=info),patch("core.highlights.discover_events",return_value=[{"time":10,"type":"kill"},{"time":40,"type":"kill"}]):
            plan=plan_montage(["clip"],transitions=True)
        self.assertEqual(len(plan["jobs"]),2)
        self.assertAlmostEqual(plan["estimated_duration"],13.78)


if __name__=="__main__":unittest.main()
