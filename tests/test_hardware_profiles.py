import unittest
from core.hardware import model_profile,select_profile,apply_hardware_profile,decode_backends,decoder_args
from core.config import DEFAULT_CONFIG,validate_config


class HardwareProfileTests(unittest.TestCase):
    def choose(self,name,failed=()):
        codes={"av1_nvenc","hevc_nvenc","h264_nvenc","av1_amf","hevc_amf","h264_amf","libx264"}
        return select_profile([{"Name":name}],codes,{c:{"ok":c not in failed} for c in codes})
    def test_rtx_3000_never_offers_av1_even_if_ffmpeg_lists_it(self):
        for name in ("NVIDIA GeForce RTX 3060","RTX 3070 Ti","NVIDIA GeForce RTX 3080 Laptop GPU","RTX 3090"):
            p=self.choose(name)
            self.assertEqual(p["default_encoder"],"hevc_nvenc")
            self.assertNotIn("av1_nvenc",[code for _,code in p["supported_options"]])
    def test_known_modern_cards_choose_their_own_av1_backend(self):
        for name in ("RTX 4060","RTX 4070 Ti SUPER","RTX 4090","NVIDIA GeForce RTX 5080"):
            self.assertEqual(self.choose(name)["default_encoder"],"av1_nvenc")
        for name in ("AMD Radeon RX 7900 XTX","Radeon RX 9070 XT","AMD Radeon RX 9060 XT 16GB"):
            self.assertEqual(self.choose(name)["default_encoder"],"av1_amf")
    def test_card_without_encoder_and_failed_driver_do_not_claim_gpu_recording(self):
        p=self.choose("AMD Radeon RX 6500 XT")
        self.assertFalse(p["hardware_encoding"])
        self.assertEqual(p["auto_settings"]["capture_fps"],30)
        self.assertEqual(self.choose("RTX 4060",("av1_nvenc","hevc_nvenc","h264_nvenc"))["default_encoder"],"libx264")
    def test_failed_av1_falls_back_to_verified_hevc(self):
        self.assertEqual(self.choose("Radeon RX 9070 XT",("av1_amf",))["default_encoder"],"hevc_amf")
    def test_discrete_rtx_is_preferred_over_integrated_radeon(self):
        codes={"av1_nvenc","hevc_amf","libx264"}
        p=select_profile([{"Name":"AMD Radeon(TM) Graphics"},{"Name":"NVIDIA GeForce RTX 5080"}],codes,{c:{"ok":True} for c in codes})
        self.assertEqual(p["selected_profile"]["id"],"rtx50")
    def test_auto_and_manual_modes_respect_unrelated_preferences(self):
        p=self.choose("RTX 4060")
        cfg={**DEFAULT_CONFIG,"buffer_seconds":600,"mic_threshold":77,"capture_fps":30,"video_codec":"h264_nvenc"}
        selected=apply_hardware_profile(cfg,p,1440)
        self.assertEqual((selected["video_codec"],selected["capture_fps"]),("av1_nvenc",60))
        self.assertEqual((selected["buffer_seconds"],selected["mic_threshold"]),(600,77))
        manual=apply_hardware_profile({**cfg,"auto_gpu_settings":False},p,2160)
        self.assertEqual((manual["video_codec"],manual["capture_fps"],manual["video_quality"]),("h264_nvenc",30,"High"))
        self.assertEqual(apply_hardware_profile(cfg,p,2160)["video_quality"],"Ultra")
    def test_amd_does_not_request_cuda_and_cpu_has_no_hardware_flags(self):
        self.assertEqual(decode_backends("hevc_amf"),["d3d11va","cpu"])
        self.assertNotIn("cuda",decoder_args("d3d11va",True))
        self.assertEqual(decode_backends("libx264"),["cpu"])
    def test_replay_can_grow_to_thirty_minutes_and_invalid_language_is_repaired(self):
        cfg=validate_config({"manual_replay_seconds":1800,"buffer_seconds":60,"language":"bad"})
        self.assertEqual(cfg["buffer_seconds"],1800)
        self.assertEqual(cfg["language"],"pl")
