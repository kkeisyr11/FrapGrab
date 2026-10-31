import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from core.hud_probes import adapt_profile,pixel_profiles
from core.calibration import own_name_box
from core.localization import set_language,t,LOptionMenu,LLabel


def box(x,y,text):return [[[x,y],[x+100,y],[x+100,y+18],[x,y+18]],text,.98]


def close_root(root):
    for timer in root.tk.call("after","info"):
        root.after_cancel(timer)
    root.destroy()


class AutoHudTests(unittest.TestCase):
    def test_hud_width_does_not_stretch_on_ultrawide_monitors(self):
        p={"monitor_size":[2560,1440],"region":[.009,.435,.2,.11]}
        wide=adapt_profile(p,3440,1440)
        hd=adapt_profile(p,1920,1080)
        self.assertAlmostEqual(wide["region"][2]*3440,512)
        self.assertAlmostEqual(hd["region"][2]*1920,384)
        self.assertAlmostEqual(wide["region"][0]*3440,hd["region"][0]*1920/0.75)
    def test_assist_notification_stays_centered_and_is_not_disabled_at_1080p(self):
        p={"monitor_size":[1920,1080],"region":[.01,.4,.2,.1]}
        assist=pixel_profiles(p)[1]
        original=adapt_profile(assist,2560,1440);wide=adapt_profile(assist,3440,1440)
        self.assertAlmostEqual(wide["region"][0]*3440-original["region"][0]*2560,440)
    def test_calibration_requires_our_name_as_attacker_with_an_opponent(self):
        self.assertIsNotNone(own_name_box([box(20,30,"PLAYER"),box(200,30,"Enemy")],"player",600))
        self.assertIsNone(own_name_box([box(20,30,"Enemy"),box(200,30,"PLAYER")],"player",600))
        self.assertIsNone(own_name_box([box(20,30,"PLAYER")],"player",600))


class LanguageAndReplayTests(unittest.TestCase):
    def test_thumbnail_can_be_cleared_collected_and_replaced_on_refresh(self):
        import customtkinter as ctk
        import gc
        from PIL import Image
        from gui.app_window import AppImage
        root=ctk.CTk();root.withdraw()
        try:
            image=AppImage(root,Image.new("RGB",(120,68),"red"),size=(120,68))
            label=LLabel(root,text="",image=image)
            label.configure(image=None,text="MP4")
            del image;gc.collect()
            label.configure(text="MP4")
            replacement=AppImage(root,Image.new("RGB",(120,68),"blue"),size=(120,68))
            label.configure(text="",image=replacement)
            self.assertTrue(str(label._label.cget("image")))
        finally:close_root(root)
    def test_runtime_language_switch_keeps_filter_values_stable(self):
        import customtkinter as ctk
        root=ctk.CTk();root.withdraw()
        try:
            set_language("pl")
            menu=LOptionMenu(root,values=["Czyste cięcia","Krótkie przenikanie"])
            menu.set("Krótkie przenikanie")
            label=LLabel(root,text="Pulpit")
            set_language("en")
            self.assertEqual(menu.get(),"Krótkie przenikanie")
            self.assertEqual(label.cget("text"),"Dashboard")
            self.assertEqual(t("do 900 sekund wstecz"),"up to 900 seconds retained")
            set_language("pl")
            self.assertEqual(label.cget("text"),"Pulpit")
        finally:set_language("pl");close_root(root)
    def test_manual_save_uses_selected_duration_instead_of_the_whole_buffer(self):
        from gui.app_window import FrapGrabApp
        export=Mock()
        app=SimpleNamespace(armed=True,manual_pending=False,game_foreground=False,
            replay_buffer=SimpleNamespace(available_seconds=1000),config_data={"buffer_seconds":1800,"manual_replay_seconds":900},
            _export_request=export)
        with patch("gui.app_window.time.monotonic",return_value=1000):FrapGrabApp._trigger(app,"manual","","")
        request=export.call_args.args[0]
        self.assertEqual(request["end"]-request["start"],900)
