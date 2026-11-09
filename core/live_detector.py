"""Background OCR/microphone detection. No UI calls on worker threads."""
import ctypes
import json
from pathlib import Path
import logging
import threading
import time
import keyboard
import mss
import numpy as np
import psutil
from .audio_capture import MicrophoneMonitor
from .config import load_config
from .events import parse_killfeed
from .monitors import output_geometry
from .setup import valid_nickname
from .games import DEFAULT_GAME,matches_game_process,requires_nickname
from .league_events import LeagueEvents


def game_status(game_id=DEFAULT_GAME):
    """Launchers are not gameplay. Never activate capture just for the launcher."""
    pids = set()
    for process in psutil.process_iter(["name", "pid"]):
        name = (process.info["name"] or "").lower()
        if matches_game_process(name,game_id):
            pids.add(process.info["pid"])
    foreground = False
    if pids:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(user32.GetForegroundWindow()), ctypes.byref(pid))
        foreground = pid.value in pids
    return bool(pids), foreground


def grab_killfeed(config):
    with mss.mss() as screen:
        monitor = output_geometry(config.get("capture_output", 0))
        x, y, w, h = config.get("killfeed_region", [.009, .435, .20, .11])
        area = {"left": monitor["left"] + int(x * monitor["width"]),
                "top": monitor["top"] + int(y * monitor["height"]),
                "width": max(1, int(w * monitor["width"])), "height": max(1, int(h * monitor["height"]))}
        return np.asarray(screen.grab(area))[:, :, :3].copy()


class LiveDetector:
    def __init__(self, on_trigger_callback=None, on_volume_meter_callback=None, on_status=None):
        self.on_trigger_callback = on_trigger_callback
        self.on_volume_meter_callback = on_volume_meter_callback
        self.on_status = on_status
        self.config = load_config()
        self.is_running = False
        self.mic_stream = None
        self.hotkey_handle = None
        self._stop = threading.Event()
        self._ocr = None
        self._control_lock = threading.RLock()
        self.last_mic_trigger_time = 0
        self._last_meter_update = 0

    def _get_ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        return self._ocr

    def trigger_clip(self, event_type, reason, extra_info="", occurred_at=None):
        if self.is_running and self.on_trigger_callback:
            args = (event_type, reason, extra_info)
            self.on_trigger_callback(*args if occurred_at is None else (*args, occurred_at))

    def play_alert_sound(self, event_type="kill"):
        if self.config.get("sound_alert", True):
            try:
                import winsound
                winsound.Beep(1200, 70)
            except Exception:
                pass

    def process_volume(self,volume,source="microphone"):
        if source!="microphone" or not self.is_running or not self.config.get("mic_enabled",False):return
        now = time.monotonic()
        if now - self._last_meter_update > .15:
            self._last_meter_update = now
            if self.on_volume_meter_callback:
                self.on_volume_meter_callback(volume)
        if volume >= self.config.get("mic_threshold", 45) and now-self.last_mic_trigger_time > min(3,self.config.get("mic_cooldown", 15)):
            self.last_mic_trigger_time = now
            self.trigger_clip("mic", "Reakcja na mikrofonie", f"{source} · poziom {volume:.0f}%")

    def _close_microphone(self):
        stream,self.mic_stream=self.mic_stream,None
        if stream:
            try:stream.close()
            except Exception:logging.exception("Microphone monitor cleanup failed")

    def refresh_settings(self):
        with self._control_lock:
            self._refresh_settings_locked()

    def _refresh_settings_locked(self):
        self.config = load_config()
        if self.hotkey_handle is not None:
            try:keyboard.remove_hotkey(self.hotkey_handle)
            except KeyError:pass
            self.hotkey_handle = None
        if self.is_running:
            try:
                self.hotkey_handle = keyboard.add_hotkey(self.config["manual_hotkey"],
                    lambda: self.trigger_clip("manual", "Ręczny zapis", self.config["manual_hotkey"]))
            except Exception as exc:
                if self.on_status:
                    self.on_status("Skrót klawiszowy: " + str(exc))
        self._close_microphone()
        if self.on_volume_meter_callback:self.on_volume_meter_callback(0)
        # Detection owns a meter-only WASAPI input, independently of recording.
        # Failure to open the microphone must never prevent visual detection.
        if self.is_running and self.config.get("mic_enabled", False):
            try:
                self.mic_stream = MicrophoneMonitor(self.process_volume)
                self.mic_stream.start()
            except Exception as exc:
                self._close_microphone()
                if self.on_status:
                    self.on_status("Mikrofon niedostępny: " + str(exc))

    def _loop(self):
        stop = self._stop
        seen = {}
        matcher, grabber, profile_key, monitor = None, None, None, None
        league = None
        warned = False
        while not stop.wait(.75 if self.config["game_id"] == "league" else .25 if self.config.get("detection_mode") == "pixel" else .65):
            try:
                self.config = load_config()
                if not self.config.get("killfeed_enabled"):
                    if league:
                        league.reset()
                    continue
                if self.config["game_id"] == "league":
                    _, foreground = game_status("league")
                    if foreground:
                        if league is None:
                            league = LeagueEvents()
                        events = league.poll()
                        now = time.monotonic()
                        for kind, age in events:
                            if not stop.is_set():
                                self.trigger_clip(kind, "Eliminacja" if kind == "kill" else "Asysta",
                                                  "League of Legends", occurred_at=now-age)
                    elif league:
                        league.reset()
                    continue
                if requires_nickname(self.config.get('game_id',DEFAULT_GAME)) and not valid_nickname(self.config.get("gamertag","")):
                    if not warned and self.on_status:
                        self.on_status("Podaj nick do automatycznej detekcji. F8 i reakcje głosowe działają bez nicku.")
                        warned=True
                    continue
                if self.config.get("detection_mode") == "pixel":
                    profile_path = self.config.get("pixel_profile", "")
                    if not profile_path:
                        if not warned and self.on_status:
                            self.on_status("Detekcja graficzna wymaga kalibracji. F8 i mikrofon działają niezależnie.")
                            warned = True
                        continue
                    current_monitor=output_geometry(self.config["capture_output"])
                    key = (profile_path, Path(profile_path).stat().st_mtime_ns,
                           self.config["capture_output"], tuple(self.config["killfeed_region"]),self.config.get("auto_hud",True),
                           current_monitor["width"],current_monitor["height"])
                    if profile_key != key:
                        from .hud_probes import HudCapture,pixel_profiles,adapt_profile
                        profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
                        monitor = current_monitor
                        if not self.config.get("auto_hud",True) and (profile["monitor_size"] != [monitor["width"],monitor["height"]] or profile["region"] != self.config["killfeed_region"]):
                            raise ValueError("Wzorzec wymaga ponownej kalibracji po zmianie ekranu lub obszaru.")
                        if grabber:
                            grabber.close()
                        profiles=pixel_profiles(profile)
                        profiles=[adapt_profile(p,monitor["width"],monitor["height"]) for p in profiles]
                        grabber = HudCapture(profiles,monitor)
                        profile_key = key
                    _, foreground = game_status(self.config['game_id'])
                    if not foreground:
                        continue
                    started = time.perf_counter()
                    hits=grabber.read()
                    elapsed_ms = (time.perf_counter()-started)*1000
                    for kind,score in hits:
                        self.trigger_clip("assist" if kind=="assist" else "visual",
                            "Asysta · dopasowanie graficzne" if kind=="assist" else "Akcja · dopasowanie graficzne",
                            f"{grabber.backend} · zgodność {score:.0%} · odczyt i analiza {elapsed_ms:.2f} ms")
                    continue
                if len(self.config.get("gamertag", "").strip()) < 3:
                    continue
                _, foreground = game_status(self.config['game_id'])
                if not foreground:
                    continue
                patch = grab_killfeed(self.config)
                results, _ = self._get_ocr()(patch)
                now = time.monotonic()
                seen = {key: stamp for key, stamp in seen.items() if now - stamp < 12}
                for event in parse_killfeed(results, self.config["gamertag"], patch.shape[1]):
                    signature = event["signature"]
                    fresh = signature not in seen
                    seen[signature] = now
                    if fresh and event["event_type"] in ("kill", "assist"):
                        self.trigger_clip(event["event_type"], "Eliminacja" if event["event_type"] == "kill" else "Asysta", event["raw_text"])
            except Exception as exc:
                logging.exception("Visual detection failed")
                if self.on_status:
                    self.on_status("Wykrywanie akcji: " + str(exc))
                stop.wait(5)
        if grabber:
            grabber.close()

    def start(self):
        with self._control_lock:
            self._start_locked()

    def _start_locked(self):
        if self.is_running:
            return
        self._stop = threading.Event()
        self.is_running = True
        self.refresh_settings()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        with self._control_lock:
            self._stop_locked()

    def _stop_locked(self):
        self.is_running = False
        self._stop.set()
        if self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except KeyError:
                pass
            self.hotkey_handle = None
        self._close_microphone()
        thread = getattr(self, "thread", None)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=8)
