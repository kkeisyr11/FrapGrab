"""Frap Grab desktop workspace. All Tk operations stay on the main thread."""
import json
from io import BytesIO
import logging
import os
import queue
import threading
import time
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from core.localization import filedialog,messagebox,t,set_language,LLabel,LButton,LSwitch,LEntry,LCheckBox,LTextbox,LOptionMenu
import customtkinter as ctk
from PIL import Image, ImageTk

from core.config import load_config, save_config, CONFIG_DIR
from core.hardware import detect_hardware_profile,apply_hardware_profile
from core.live_detector import LiveDetector, game_status, grab_killfeed
from core.replay_buffer import ReplayBuffer
from core.editor import VideoEditor,plan_montage
from core.renderer import ClipRenderer
from core.scanner import MatchScanner
from core.media import NO_WINDOW, find_binary, probe, cancel_media_jobs
from core.monitors import outputs,output_geometry
from core.updater import CURRENT_VERSION, AutoUpdater, release_notes_for_language
from core.setup import NICKNAME_HELP, ROCKET_NICKNAME_HELP, valid_nickname, clean_nickname
from core.games import GAME_EVENTS, GAMES, game_choices, requires_nickname, select_game, uses_hud
from core.events import ClipEventFilter, EVENT_LABELS, clip_event_label
from core.rocket_events import enable_stats_api
from core.banner_events import BANNER_PROFILES
from core.game_installations import game_install_folder
from core.valve_events import VALVE_GAMES, configure_valve_game
from core.buffer_display import buffer_display
from core.audio_capture import output_devices
from gui.images import AppImage
from gui.palette import BG, SIDE, CARD, RAISED, BORDER, TEXT, MUTED, ACCENT, ACCENT_HOVER, ACTIVE, RED
from gui.widgets import ReplayGauge,GameSelector
from gui.window_style import style_window

BLUE = "#9BC8EE"
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


def font(size=13, bold=False):
    return ctk.CTkFont(family="Segoe UI", size=size, weight="bold" if bold else "normal")


class FrapGrabApp(ctk.CTk):
    def __init__(self, preview=False):
        super().__init__()
        self.preview_mode = preview
        self.config_data = load_config()
        set_language(self.config_data["language"])
        if self.config_data.get("auto_hud",True) and not Path(self.config_data.get("pixel_profile") or "__missing__").is_file():
            self.config_data["pixel_profile"]=""
        self.hardware = detect_hardware_profile()
        try:height=output_geometry(self.config_data["capture_output"])["height"]
        except ValueError:height=None
        self.hud_needs_calibration=not bool(self.config_data.get("pixel_profile"))
        if self.config_data.get("pixel_profile"):
            try:self.hud_needs_calibration=json.loads(Path(self.config_data["pixel_profile"]).read_text(encoding="utf-8"))["monitor_size"][1]!=height
            except (OSError,ValueError,KeyError,TypeError):self.hud_needs_calibration=True
        self.config_data=apply_hardware_profile(self.config_data,self.hardware,height)
        if not preview:save_config(self.config_data)
        self.title(f"Frap Grab · {CURRENT_VERSION}")
        self.geometry("1260x850")
        self.minsize(1080, 740)
        self.configure(fg_color=BG)
        icon = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
        self.events = queue.Queue()
        self.workers = set()
        self.workers_lock = threading.Lock()
        self.closing = False
        self.armed = False
        self.game_running = False
        self.game_foreground = False
        self.active_page = "live"
        self.selected = set()
        self.files = []
        self.thumbnail_images = {}
        self.thumbnail_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbnail")
        self.library_page = 0
        self.library_page_size = 9
        self.scanned_events = []
        self.scan = None
        self.job_busy = False
        self.job_cancel = threading.Event()
        self.job_started = 0
        self.calibrating=False
        self.pending_calibration=None
        self.last_movie_path = None
        self.update_info=None
        self.update_busy=False
        self.update_installer=None
        self.update_dialog = None
        self.plan_selection = None
        self.pending_auto = None
        self.clip_event_filter = ClipEventFilter()
        self.manual_pending = False
        self.exports_active = 0
        self.capture_operation = False
        self.session_clips = 0
        self.session_actions = 0
        self.activity_count = 0
        self._failed_capture = False
        self._last_auto = 0
        self._monitor_stop = threading.Event()
        self.replay_buffer = ReplayBuffer(self._clip_saved, lambda state, msg: self.post(self._capture_status, state, msg))
        self.live_detector = LiveDetector(lambda *args: self.post(self._trigger, *args),
            lambda volume: self.post(self._volume, volume), lambda msg: self.post(self.activity, "Wykrywanie", msg, RED))
        self._build_layout()
        style_window(self)
        self.setup_wizard=None
        self._nickname_hint()
        self._game_event_options()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(60, self._drain)
        self.after(500, self._tick)
        if not preview:
            threading.Thread(target=self._monitor, daemon=True).start()
            if not self.config_data.get("setup_completed"):
                self.after(700,self.open_setup)
            elif self.config_data.get("auto_record_enabled"):
                self.after(1000, self.toggle_recording)
            if self.config_data.get("auto_update_check") and self.config_data.get("github_repository"):
                self.after(5000, lambda: self._check_updates() if self.config_data.get("auto_update_check") else None)

    def post(self, fn, *args):
        if not self.closing:
            self.events.put((fn, args))

    def _drain(self):
        for _ in range(150):
            try:
                fn, args = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                logging.exception("UI event failed")
        if not self.closing:
            self.after(60, self._drain)

    def label(self, parent, text, size=13, color=TEXT, bold=False, **kwargs):
        return LLabel(parent, text=text, font=font(size, bold), text_color=color, **kwargs)

    def button(self, parent, text, command, primary=False, **kwargs):
        return LButton(parent, text=text, command=command, font=font(13, True),
            height=kwargs.pop("height", 38), corner_radius=8, fg_color=ACCENT if primary else RAISED,
            hover_color=ACCENT_HOVER if primary else BORDER, text_color=BG if primary else TEXT, **kwargs)

    def card(self, parent, **kwargs):
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER, **kwargs)

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = ctk.CTkFrame(self, width=178, corner_radius=0, fg_color=SIDE)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(8, weight=1)
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=22, pady=(32, 6), sticky="ew")
        self.logo_image=AppImage(self,Image.open(Path(__file__).resolve().parents[1]/"assets/icon.png"),size=(50,50))
        self.label(brand,"",image=self.logo_image,width=50,height=50).pack(side="left")
        self.nav = {}
        for row, (key, title) in enumerate([("live", "Pulpit"), ("library", "Klipy"),
                ("studio", "Montaż"), ("game", GAMES[self.config_data["game_id"]]["name"]),
                ("settings", "Ustawienia")], 2):
            btn = LButton(self.sidebar, text=title, font=font(13, True), height=42, anchor="w", corner_radius=6,
                fg_color="transparent", text_color=MUTED, hover_color=RAISED, command=lambda k=key: self.show_page(k))
            btn.grid(row=row, column=0, sticky="ew", padx=12, pady=3)
            self.nav[key] = btn
        self.label(self.sidebar, f"v{CURRENT_VERSION}", 11, MUTED).grid(row=9, column=0, sticky="w", padx=20, pady=20)
        self.main_area = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main_area.grid(row=0, column=1, sticky="nsew")
        self.main_area.grid_columnconfigure(0, weight=1)
        self.main_area.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self.main_area, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=30, pady=(24, 20))
        top.grid_columnconfigure(0, weight=1)
        headings = ctk.CTkFrame(top, fg_color="transparent")
        headings.grid(row=0, column=0, sticky="w")
        self.page_title = self.label(headings, "Pulpit", 23, bold=True)
        self.page_title.pack(anchor="w")
        self.game_map = game_choices()
        self.game_option = GameSelector(top, values=list(self.game_map), command=self._select_game)
        self.game_option.set(GAMES[self.config_data["game_id"]]["name"])
        self.game_option.grid(row=0, column=1)
        self.state_badge = self.label(top, "●  Nie nagrywa", 12, MUTED, True, fg_color=CARD, corner_radius=8, padx=14, pady=8)
        self.state_badge.grid(row=0, column=2, padx=12)
        self.arm_button = self.button(top, "Włącz nagrywanie", self.toggle_recording, True, width=168, height=42)
        self.arm_button.grid(row=0, column=3)
        self.workspace = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.workspace.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 20))
        self.workspace.grid_columnconfigure(0, weight=1)
        self.workspace.grid_rowconfigure(0, weight=1)
        self.pages = {}
        self._build_live()
        self._build_library()
        self._build_studio()
        self._build_game()
        self._build_settings()
        self.show_page("live")

    def show_page(self, key):
        self.active_page = key
        for page_key, page in self.pages.items():
            if page_key == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
        for page_key, btn in self.nav.items():
            btn.configure(fg_color=ACTIVE if page_key == key else "transparent", text_color=ACCENT if page_key == key else MUTED)
        titles={"live":"Pulpit","library":"Klipy","studio":"Montaż",
                "game":GAMES[self.config_data["game_id"]]["name"],"settings":"Ustawienia"}
        self.page_title.configure(text=titles[key])
        if key == "library":
            self.refresh_library()
        if key == "studio":
            self._refresh_selection()

    def scroll_page(self, key):
        page = ctk.CTkScrollableFrame(self.workspace, fg_color="transparent", scrollbar_button_color=BORDER)
        self.pages[key] = page
        return page

    def _build_live(self):
        page = self.scroll_page("live")
        hero = self.card(page)
        hero.pack(fill="x", pady=(0, 16))
        hero.grid_columnconfigure(0, weight=1)
        left = ctk.CTkFrame(hero, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=26, pady=24)
        self.label(left,"Powtórka",25,TEXT,True).pack(anchor="w")
        self.replay_lengths={"30 s":30,"1 min":60,"2 min":120,"3 min":180,"5 min":300,"10 min":600,"15 min":900,"30 min":1800}
        self.replay_length=LOptionMenu(left,values=list(self.replay_lengths),width=170,height=34,fg_color=RAISED,
            button_color=BORDER,command=self._manual_length_changed,font=font(12))
        value=self.config_data["manual_replay_seconds"]
        self.replay_length.set(next((label for label,seconds in self.replay_lengths.items() if seconds==value),f"{value} s"))
        self.replay_length.pack(anchor="w",pady=(16,0))
        actions = ctk.CTkFrame(left, fg_color="transparent")
        actions.pack(anchor="w", pady=(22, 0))
        self.save_button = self.button(actions, "Zapisz powtórkę", self.manual_clip, True, width=180, height=42)
        self.save_button.pack(side="left")
        self.hotkey_badge = self.label(actions, self.config_data["manual_hotkey"].upper(), 12, TEXT, True,
            fg_color=RAISED, corner_radius=6, width=46, height=32)
        self.hotkey_badge.pack(side="left", padx=12)
        right = ctk.CTkFrame(hero, fg_color="transparent", width=220)
        right.grid(row=0, column=1, padx=(0, 28), pady=20)
        self.ring = ReplayGauge(right,caption=t('W BUFORZE'))
        self.ring.pack()
        self.buffer_caption = self.label(right, f"do {self.config_data['buffer_seconds']} sekund wstecz", 12, MUTED)
        self.buffer_caption.pack()
        metrics = ctk.CTkFrame(page, fg_color="transparent")
        metrics.pack(fill="x", pady=(0, 18))
        metrics.grid_columnconfigure((0, 1, 2), weight=1, uniform="metric")
        self.metric_labels = {}
        for i, (key, title, value) in enumerate([("clips", "ZAPISANE W SESJI", "0 klipów"),
                ("actions", "WYKRYTE AKCJE", "0 zdarzeń"), ("format", "PROFIL NAGRANIA", f"{self.config_data['capture_fps']} FPS · MP4")]):
            panel = self.card(metrics)
            panel.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            self.label(panel, title, 9, MUTED, True).pack(anchor="w", padx=16, pady=(12, 2))
            val = self.label(panel, value, 20, TEXT, True)
            val.pack(anchor="w", padx=16, pady=(0, 12))
            self.metric_labels[key] = val
        activity = self.card(page)
        activity.pack(fill="x")
        row = ctk.CTkFrame(activity, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(18, 12))
        self.label(row, "Ostatnia aktywność", 16, bold=True).pack(side="left")
        self.activity_list = ctk.CTkScrollableFrame(activity, height=255, fg_color="transparent")
        self.activity_list.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.activity_empty = self.label(self.activity_list, "Brak aktywności", 12, MUTED)
        self.activity_empty.pack(anchor="w", padx=8, pady=6)
        foot = ctk.CTkFrame(page, fg_color="transparent")
        foot.pack(fill="x", pady=(18, 0))
        self.label(foot, "Przechwytywanie całego wybranego ekranu · pliki pozostają na komputerze", 11, MUTED).pack(side="left")
        self.button(foot, "Otwórz folder", self.open_folder, width=126, height=30).pack(side="right")

    def _build_game(self):
        page = ctk.CTkFrame(self.workspace, fg_color="transparent")
        self.pages["game"] = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        tabs = ctk.CTkFrame(page, fg_color="transparent")
        tabs.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.game_tabbar = tabs
        self.game_tabs = {}
        for key, label in (("options", "Ustawienia gry"), ("analysis", "Analiza nagrania")):
            button = self.button(tabs, label, lambda tab=key: self._show_game_tab(tab), width=158)
            button.pack(side="left", padx=(0, 8))
            self.game_tabs[key] = button
        self.game_options = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color=BORDER)
        self.game_analysis = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color=BORDER)
        self._build_scanner(self.game_analysis)
        columns = ctk.CTkFrame(self.game_options, fg_color="transparent")
        columns.pack(fill="x", pady=(0, 16))
        columns.grid_columnconfigure((0, 1), weight=1, uniform="game_options")
        detection = self.card(columns)
        detection.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.label(detection, "Automatyczne klipy", 16, bold=True).pack(anchor="w", padx=20, pady=(18, 6))
        self.kf_switch = self._switch(detection, "Automatyczny zapis akcji", "killfeed_enabled")
        self.detection_status = self.label(detection, self._detection_description(), 11, ACCENT, wraplength=350, justify="left")
        self.detection_status.pack(anchor="w", padx=20, pady=(2, 8))
        self.event_options = ctk.CTkFrame(detection, fg_color="transparent")
        self.event_options.pack(fill="x", padx=20, pady=(4, 12))
        self.player_settings=ctk.CTkFrame(detection,fg_color="transparent")
        self.player_settings.pack(fill="x")
        self.nickname_label=self.label(self.player_settings, "Nick gracza *", 11, MUTED)
        self.nickname_label.pack(anchor="w", padx=20, pady=(0,4))
        self.gamertag = LEntry(self.player_settings, placeholder_text="Nick z gry, bez tagu klanu", height=36, fg_color=BG, border_color=BORDER, font=font())
        self.gamertag.pack(fill="x", padx=20, pady=(0,6))
        self.gamertag.insert(0, self.config_data["gamertag"])
        self.gamertag.bind("<FocusOut>", self._save_gamertag)
        self.gamertag.bind("<Return>", self._save_gamertag)
        self.nickname_help=self.label(self.player_settings,NICKNAME_HELP,11,MUTED,wraplength=355,justify="left")
        self.nickname_help.pack(anchor="w",padx=20,pady=(0,12))
        self.calibration_button = self.button(detection, "Skalibruj detekcję graficzną", self._show_calibration, width=230, height=30)
        self.calibration_button.pack(anchor="w", padx=20, pady=(0, 10))
        self.match_setup_button = self.button(detection, "Włącz dane meczu", self._match_setup, width=218, height=32)
        audio_timing = ctk.CTkFrame(columns, fg_color="transparent")
        audio_timing.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._build_game_timing(audio_timing)
        microphone = self.card(audio_timing)
        microphone.pack(fill="x", pady=(0, 16))
        self.label(microphone, "Mikrofon", 16, bold=True).pack(anchor="w", padx=20, pady=(16, 5))
        self.mic_switch = self._switch(microphone, "Reakcje z mojego mikrofonu", "mic_enabled", refresh=True)
        self.label(microphone, "Dźwięk Discorda nie wyzwala klipów.\nZapis własnego głosu: w ustawieniach.", 11, MUTED,justify="left").pack(anchor="w", padx=20, pady=(3, 8))
        self.vu = ctk.CTkProgressBar(microphone, height=5, progress_color=ACCENT, fg_color=BORDER)
        self.vu.pack(fill="x", padx=20, pady=(0, 10))
        self.vu.set(0)
        threshold = ctk.CTkFrame(microphone, fg_color="transparent")
        threshold.pack(fill="x", padx=20, pady=(0, 16))
        self.label(threshold, "Próg reakcji", 11, MUTED).pack(side="left")
        self.threshold_label = self.label(threshold, f"{self.config_data['mic_threshold']}%", 11)
        self.threshold_label.pack(side="right")
        self.threshold_slider = ctk.CTkSlider(threshold, from_=5, to=95, width=130, progress_color=ACCENT, button_color=ACCENT,
            command=self._threshold)
        self.threshold_slider.pack(side="left", fill="x", expand=True, padx=12)
        self.threshold_slider.set(self.config_data["mic_threshold"])
        self._build_game_calibration()
        self._show_game_tab("options")

    def _show_game_tab(self, key):
        self.game_tab = "analysis" if key == "analysis" and uses_hud(self.config_data["game_id"]) else "options"
        for name, panel in (("options", self.game_options), ("analysis", self.game_analysis)):
            selected = name == self.game_tab
            if selected:
                panel.grid(row=1, column=0, sticky="nsew")
            else:
                panel.grid_remove()
            self.game_tabs[name].configure(fg_color=ACTIVE if selected else RAISED,
                                            text_color=ACCENT if selected else MUTED)

    def _show_calibration(self):
        self._show_game_tab("options")
        self.after_idle(lambda: self.game_options._parent_canvas.yview_moveto(1))

    def _switch(self, parent, text, key, refresh=False):
        switch = LSwitch(parent, text=text, font=font(12, True), progress_color=ACCENT,
            button_color=TEXT, button_hover_color=ACCENT, fg_color=BORDER)
        switch.configure(command=lambda: self._preference(key, bool(switch.get()), refresh))
        switch.pack(anchor="w", padx=20, pady=3)
        if self.config_data.get(key):
            switch.select()
        return switch

    def _detection_description(self):
        if not self.config_data.get("killfeed_enabled",True):return "Ręczny zapis F8"
        game_id = self.config_data["game_id"]
        if requires_nickname(game_id) and not valid_nickname(self.config_data.get("gamertag", ""), game_id):
            return "Podaj nick do automatycznej detekcji"
        if game_id == "league":
            return "Automatyczne wykrywanie eliminacji i asyst"
        if game_id in BANNER_PROFILES:
            return "Testowa detekcja zwycięstwa · angielski HUD"
        if game_id in VALVE_GAMES and not self.config_data["gsi_token"]:
            return "Skonfiguruj dane meczu"
        if game_id == "rocket_league" or game_id in VALVE_GAMES:
            if self.live_detector.match_feed == "error":
                return "Port danych meczu jest zajęty"
            if self.live_detector.match_feed == "connected":
                return "Dane meczu aktywne"
            return "Oczekiwanie na dane meczu" if self.armed else "Włącz nagrywanie, aby połączyć się z grą"
        if self.config_data.get("detection_mode") == "ocr":
            return "Tryb OCR · rozpoznawanie nicku w tle"
        uses_extra_ocr = any(kind in self.config_data["clip_events"] for kind in ("death", "knockdown", "downed"))
        mode = "Detekcja graficzna i OCR" if uses_extra_ocr else "Tryb graficzny · bez OCR"
        return mode + (" · skalibrowany" if self.config_data.get("pixel_profile") else "\nWymagana jednorazowa kalibracja wzorca")

    def _preference(self, key, value, refresh=False):
        if key in ("gamertag", "killfeed_enabled", "clip_events", "assist_near_seconds") and self.config_data.get(key) != value:
            self.clip_event_filter.reset()
        self.config_data[key] = value
        save_config(self.config_data)
        if key in ("gamertag","killfeed_enabled") and hasattr(self,"nickname_help"):self._nickname_hint()
        if key == "killfeed_enabled":
            if not value:
                self.pending_calibration = None
            self._game_event_options()
        if refresh and self.armed:
            self.background(self.live_detector.refresh_settings)

    def _save_gamertag(self, event=None):
        nickname=clean_nickname(self.gamertag.get(), self.config_data["game_id"])
        if nickname!=self.config_data["gamertag"] and self.config_data.get("auto_hud",True):self.config_data["pixel_profile"]=""
        self._preference("gamertag",nickname)

    def _nickname_hint(self):
        automatic=self.config_data.get("killfeed_enabled",True)
        game_id = self.config_data["game_id"]
        self.nav["game"].configure(text=GAMES[game_id]["name"])
        needed = requires_nickname(game_id)
        needs_hud = uses_hud(game_id)
        if needed:
            if not self.player_settings.winfo_manager():
                self.player_settings.pack(fill="x", after=self.event_options)
        else:
            self.player_settings.pack_forget()
        if needs_hud:
            if not self.calibration_button.winfo_manager():
                self.calibration_button.pack(anchor="w", padx=20, pady=(0, 10), after=self.player_settings)
            if not self.calibration_settings.winfo_manager():
                self.calibration_settings.pack(fill="x", pady=(0, 16))
            self.game_tabbar.grid()
        else:
            self.calibration_button.pack_forget()
            self.calibration_settings.pack_forget()
            self.game_tabbar.grid_remove()
            if self.game_tab == "analysis":
                self._show_game_tab("options")
        if game_id == "rocket_league" or game_id in VALVE_GAMES:
            if not self.match_setup_button.winfo_manager():
                self.match_setup_button.pack(anchor="w", padx=20, pady=(0, 10), after=self.detection_status)
        else:
            self.match_setup_button.pack_forget()
        self.nickname_label.configure(text="Nick gracza *" if automatic else "Nick gracza (opcjonalnie)")
        missing = needed and automatic and not valid_nickname(self.config_data.get("gamertag", ""), game_id)
        self.nickname_help.configure(text=ROCKET_NICKNAME_HELP if game_id == "rocket_league" else NICKNAME_HELP,
                                     text_color=BLUE if missing else MUTED)
        self.gamertag.configure(placeholder_text="Nazwa z tablicy wyników" if game_id == "rocket_league" else "Nick z gry, bez tagu klanu")
        self.detection_status.configure(text=self._detection_description(), text_color=BLUE if missing else ACCENT)

    def _match_setup(self):
        game_id = self.config_data["game_id"]
        name = GAMES[game_id]["name"]
        if game_status(game_id)[0]:
            messagebox.showinfo(name, "Zamknij grę przed zmianą ustawień.", parent=self)
            return
        detected = game_install_folder(game_id)
        folder = filedialog.askdirectory(parent=self, title="Wybierz folder instalacji gry",
                                         initialdir=str(detected) if detected else None)
        if not folder:
            return
        try:
            if game_status(game_id)[0]:
                raise ValueError("Zamknij grę przed zmianą ustawień.")
            if game_id == "rocket_league":
                self._preference("rocket_stats_port", enable_stats_api(folder))
            else:
                token = configure_valve_game(folder, game_id, self.config_data["gsi_token"])
                self._preference("gsi_token", token)
        except (OSError, ValueError) as exc:
            messagebox.showerror(name, str(exc), parent=self)
            return
        self._nickname_hint()
        note = ("Dodaj -gamestateintegration w opcjach uruchamiania Dota 2 w Steam, a następnie uruchom grę."
                if game_id == "dota2" else "Konfiguracja zapisana. Uruchom grę i włącz nagrywanie.")
        messagebox.showinfo(name, note, parent=self)

    def _game_event_options(self):
        for widget in self.event_options.winfo_children():
            widget.destroy()
        game_id = self.config_data["game_id"]
        if not self.config_data["killfeed_enabled"] or game_id not in GAME_EVENTS:
            return
        self.label(self.event_options, "Zapisuj zdarzenia", 12, bold=True).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        selected = self.config_data["clip_events"]
        for index, kind in enumerate(GAME_EVENTS[game_id]):
            check = LCheckBox(self.event_options, text=EVENT_LABELS[kind], font=font(12), checkbox_width=17,
                              checkbox_height=17, fg_color=ACCENT, hover_color=ACCENT_HOVER, checkmark_color=BG)
            check.configure(command=lambda event=kind, box=check: self._set_clip_event(event, bool(box.get())))
            if kind in selected:
                check.select()
            check.grid(row=1 + index // 2, column=index % 2, padx=(0, 12), pady=3, sticky="w")
        if uses_hud(game_id):
            if any(kind in selected for kind in ("death", "knockdown", "downed")):
                self.label(self.event_options, "Śmierć i powalenia korzystają z OCR.", 11, MUTED).grid(
                    row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
            if "assist" in selected:
                choices = {"Wszystkie asysty": 0, "Do 8 s od mojego zabójstwa": 8, "Do 15 s od mojego zabójstwa": 15}
                menu = LOptionMenu(self.event_options, values=list(choices), width=228, height=31,
                                   fg_color=RAISED, button_color=BORDER, font=font(11),
                                   command=lambda label: self._preference("assist_near_seconds", choices[label]))
                menu.set(next(label for label, seconds in choices.items() if seconds == self.config_data["assist_near_seconds"]))
                menu.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 2))

    def _set_clip_event(self, kind, enabled):
        choices = set(self.config_data["clip_events"])
        if enabled:
            choices.add(kind)
        else:
            choices.discard(kind)
        self._preference("clip_events", [kind for kind in GAME_EVENTS[self.config_data["game_id"]] if kind in choices])
        self._nickname_hint()
        self._game_event_options()

    def _select_game(self,choice):
        game_id=self.game_map[choice]
        if game_id==self.config_data['game_id']:return
        if self.armed or self.job_busy or self.capture_operation or self.exports_active:
            self.game_option.set(GAMES[self.config_data['game_id']]['name'])
            messagebox.showinfo("Gra","Zatrzymaj nagrywanie i poczekaj na zakończenie eksportu.");return
        self._save_gamertag()
        config=select_game(self.config_data,game_id)
        if not save_config(config):
            self.game_option.set(GAMES[self.config_data['game_id']]['name'])
            messagebox.showerror("Gra","Nie można zapisać ustawień. Sprawdź uprawnienia do profilu użytkownika.");return
        self.config_data=config
        self.clip_event_filter.reset()
        self.pending_calibration=None
        self.hud_needs_calibration=not bool(config['pixel_profile'])
        self.gamertag.delete(0,'end');self.gamertag.insert(0,config['gamertag'])
        for switch,key in ((self.kf_switch,'killfeed_enabled'),(self.mic_switch,'mic_enabled'),(self.hud_auto_switch,'auto_hud')):
            switch.select() if config[key] else switch.deselect()
        self.region_entry.delete(0,'end')
        self.region_entry.insert(0,', '.join(f'{v*100:g}' for v in config['killfeed_region']))
        self.detection_option.set('OCR · rozpoznawanie nicku' if config['detection_mode']=='ocr' else 'Grafika · bez OCR')
        self.before_option.set(str(config["clip_before_kill"]))
        self.after_option.set(str(config["clip_after_kill"]))
        self.threshold_slider.set(config["mic_threshold"])
        self.threshold_label.configure(text=f"{config['mic_threshold']}%")
        self._nickname_hint()
        self._game_event_options()
        self._show_game_tab("options")
        self.show_page("game")

    def _threshold(self, value):
        self.threshold_label.configure(text=f"{int(value)}%")
        self._preference("mic_threshold", int(value))

    def _volume(self, value):
        self.vu.set(value / 100)

    def activity(self, title, detail, color=ACCENT):
        self.activity_empty.pack_forget()
        row = ctk.CTkFrame(self.activity_list, fg_color="transparent")
        row.pack(fill="x", pady=(0, 12))
        self.label(row, "●", 10, color).pack(side="left", anchor="n", padx=(2, 10))
        content = ctk.CTkFrame(row, fg_color="transparent")
        content.pack(side="left", fill="x", expand=True)
        self.label(content, title, 12, TEXT, True, anchor="w").pack(fill="x")
        self.label(content, str(detail)[:350], 11, MUTED, wraplength=310, justify="left", anchor="w").pack(fill="x", pady=(2, 0))
        self.label(content, datetime.now().strftime("%H:%M:%S"), 10, MUTED, anchor="w").pack(fill="x")
        children = self.activity_list.winfo_children()
        for child in children[:-30]:
            child.destroy()

    def toggle_recording(self):
        if self.preview_mode:
            return
        self._save_gamertag()
        self.clip_event_filter.reset()
        self.armed = not self.armed
        self._failed_capture = False
        self.arm_button.configure(text="Zatrzymaj nagrywanie" if self.armed else "Włącz nagrywanie", fg_color=RAISED if self.armed else ACCENT,
            hover_color=BORDER if self.armed else ACCENT_HOVER, text_color=TEXT if self.armed else BG)
        if self.armed:
            save_config(self.config_data)
            self.background(self.live_detector.start)
            if self.config_data["record_only_in_game"]:
                self.activity("Czeka na grę", GAMES[self.config_data["game_id"]]["name"])
        else:
            if self.pending_auto:
                self._export_request(self.pending_auto)
                self.pending_auto = None
            self.background(self.live_detector.stop)
            self.activity("Nagrywanie zatrzymane", "")

    def _monitor(self):
        while not self._monitor_stop.wait(1):
            try:
                running, foreground = game_status(self.config_data['game_id'])
                self.post(self._game_changed, running, foreground)
            except Exception:
                logging.exception("Game monitor failed")

    def _game_changed(self, running, foreground):
        self.game_running, self.game_foreground = running, foreground

    def _tick(self):
        if self.closing:
            return
        game_id = self.config_data["game_id"]
        if self.active_page == "game" and (game_id == "rocket_league" or game_id in VALVE_GAMES):
            description = self._detection_description()
            if self.detection_status._source_text != description:
                self.detection_status.configure(text=description)
        if self.pending_calibration and not self.game_foreground and not self.calibrating and not self.job_busy:
            path=self.pending_calibration;self.pending_calibration=None;self._start_auto_calibration(path)
        buffer = self.replay_buffer
        should_record = self.armed and (not self.config_data["record_only_in_game"] or self.game_foreground)
        if not self.capture_operation:
            if should_record and not buffer.is_recording and not self._failed_capture and not self.pending_auto and not self.exports_active:
                self._capture_task(buffer.start_rolling_buffer)
            elif not should_record and buffer.is_recording:
                if self.pending_auto:
                    self._export_request(self.pending_auto)
                    self.pending_auto=None
                self._capture_task(buffer.stop_rolling_buffer)
        seconds = buffer.available_seconds
        cap = self.config_data["buffer_seconds"]
        self._update_buffer_display(seconds,cap)
        if buffer.state == "error":
            state, color = "●  Błąd nagrywania", RED
        elif buffer.state == "recording" and buffer.is_recording:
            state, color = "●  Nagrywa", ACCENT
        elif should_record:
            state, color = "●  Uruchamia nagrywanie", BLUE
        elif self.armed:
            state, color = "●  Czeka na grę", BLUE
        else:
            state, color = "●  Nie nagrywa", MUTED
        self.state_badge.configure(text=state, text_color=color)
        can_save = seconds > 0 and not self.manual_pending
        self.save_button.configure(
            state="normal" if can_save else "disabled",
            fg_color=ACCENT if can_save else RAISED, text_color_disabled=MUTED,
        )
        if self.pending_auto and time.monotonic() >= self.pending_auto["end"]:
            request = self.pending_auto
            self.pending_auto = None
            self._export_request(request)
        self.after(500, self._tick)

    def _update_buffer_display(self,seconds,capacity):
        text,fraction,_=buffer_display(seconds,capacity)
        self.ring.set_value(text,fraction)

    def _capture_task(self, fn):
        self.capture_operation = True
        def task():
            try:
                fn()
            finally:
                self.post(setattr, self, "capture_operation", False)
        self.background(task)

    def _capture_status(self, state, msg):
        if state in ("starting", "idle", "error"):
            self.clip_event_filter.reset()
        if state == "error":
            self._failed_capture = True
            self.activity("Nagrywanie zatrzymane", msg, RED)
        elif state == "recording":
            audio = " · audio: "+", ".join(item["role"] for item in self.replay_buffer.audio_sources)
            self.activity("Obraz jest przechwytywany", msg + audio)
        elif state=="warning":
            self.activity("Uwaga dotycząca dźwięku",msg,RED)

    def manual_clip(self):
        self._trigger("manual", "Ręczny zapis", self.config_data["manual_hotkey"])

    def _manual_length_changed(self,choice):
        duration=self.replay_lengths[choice]
        self.config_data["manual_replay_seconds"]=duration
        self.config_data["buffer_seconds"]=max(duration,self.config_data["buffer_seconds"])
        save_config(self.config_data)
        self.replay_buffer.config["buffer_seconds"] = self.config_data["buffer_seconds"]
        self.buffer_caption.configure(text=f"do {self.config_data['buffer_seconds']} sekund wstecz")
        if hasattr(self,"buffer_option"):self.buffer_option.set(str(self.config_data["buffer_seconds"]))
        self.activity("Długość powtórki",f"{duration} s · dostępne teraz: {int(self.replay_buffer.available_seconds)} s")

    def _trigger(self, event_type, reason, extra, occurred_at=None):
        if not self.armed or self.manual_pending and event_type == "manual":
            return
        if event_type != "manual" and not self.game_foreground:
            return
        if event_type != "manual" and (not self.replay_buffer.is_recording or self.replay_buffer.state!="recording"):
            logging.warning("Automatic event ignored while capture is inactive: %s",event_type)
            return
        if self.replay_buffer.available_seconds < 1:
            self.activity("Bufor się napełnia", "Powtórkę zapiszesz, gdy pojawią się pierwsze sekundy nagrania.", BLUE)
            return
        now = time.monotonic() if occurred_at is None else occurred_at
        if event_type == "manual":
            self.manual_pending = True
            self._export_request({"start": now-self.config_data["manual_replay_seconds"], "end": now,
                "reason": "manual", "details": extra, "events": []})
        else:
            accepted = [(event_type, reason, extra, now)]
            if event_type != "mic" and "clip_events" in self.config_data:
                accepted = self.clip_event_filter.select(
                    accepted[0], self.config_data["clip_events"], self.config_data["assist_near_seconds"])
            for event_type, reason, extra, now in accepted:
                self._queue_automatic_event(event_type, reason, extra, now)

    def _queue_automatic_event(self, event_type, reason, extra, now):
        self.session_actions += 1
        self.metric_labels["actions"].configure(text=f"{self.session_actions} zdarzeń")
        before, after = self.config_data["clip_before_kill"], self.config_data["clip_after_kill"]
        if event_type == "mic":
            before, after = max(20, before), max(15, after)
        start, end = now - before, now + after
        pending = self.pending_auto
        if (pending and start <= pending["end"] and end >= pending["start"]
                and max(end, pending["end"]) - min(start, pending["start"]) <= 55):
            pending["start"] = min(pending["start"], start)
            pending["end"] = max(pending["end"], end)
            pending["events"].append(now)
            pending["event_types"].append(event_type)
        else:
            if pending:
                self._export_request(pending)
            self.pending_auto = {"start": start, "end": end, "reason": event_type,
                                 "details": extra, "events": [now], "event_types": [event_type]}
        self.activity(reason, extra)

    def _export_request(self, request):
        self.exports_active += 1
        self.activity("Zapisywanie powtórki", "Domykanie fragmentu i tworzenie pliku MP4…", BLUE)
        def worker():
            try:
                self.replay_buffer.export_last_buffer(request["reason"], request["details"],
                    request["end"]-request["start"], request["end"], request["events"],request.get("event_types"))
            finally:
                self.post(self._export_released)
                if request["reason"] == "manual":
                    self.post(setattr, self, "manual_pending", False)
        self.background(worker)

    def _export_released(self):
        self.exports_active = max(0, self.exports_active-1)

    def _clip_saved(self, path, reason, extra):
        self.post(self._clip_saved_ui, path)

    def _clip_saved_ui(self, path):
        config = self.config_data
        if (uses_hud(config["game_id"]) and config.get("auto_hud", True)
                and config.get("killfeed_enabled", True) and valid_nickname(config.get("gamertag", ""))
                and (not config.get("pixel_profile") or self.hud_needs_calibration)):
            self.pending_calibration = path
        self.session_clips += 1
        self.metric_labels["clips"].configure(text=f"{self.session_clips} klipów")
        self.activity("Powtórka zapisana", Path(path).name)
        self.background(self.live_detector.play_alert_sound)
        if self.active_page == "library":
            self.refresh_library()

    def background(self, fn, callback=None, job=False):
        def worker():
            try:
                value = fn()
                if callback:
                    self.post(callback, value)
            except Exception as exc:
                logging.exception("Background job failed")
                self.post(self.activity, "Nie udało się wykonać operacji", str(exc), RED)
                if job:
                    self.post(self._job_failed, str(exc))
            finally:
                with self.workers_lock:
                    self.workers.discard(threading.current_thread())
        thread = threading.Thread(target=worker, daemon=True)
        with self.workers_lock:
            self.workers.add(thread)
        thread.start()
        return thread

    def _job_failed(self, message):
        if self.job_busy:
            self._finish_studio_job()
            self.scan_button.configure(state="normal", text="Rozpocznij analizę")
            self.job_status.configure(text="Błąd: " + message[:220], text_color=RED)
            self.scan_results.insert("end", "\nBłąd: " + message + "\n")
            if not message.startswith("Anulowano") and not self.game_foreground:
                messagebox.showerror("Operacja przerwana", message)

    def open_folder(self):
        folder = Path(self.config_data["save_folder"])
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _build_library(self):
        page = ctk.CTkFrame(self.workspace, fg_color="transparent")
        self.pages["library"] = page
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)
        tools = ctk.CTkFrame(page, fg_color="transparent")
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.library_count = self.label(tools, "Twoje klipy", 14, bold=True)
        self.library_count.pack(side="left")
        self.day_filter = LOptionMenu(tools, values=["Wszystkie dni"], width=145, height=36,
            fg_color=RAISED, button_color=BORDER, font=font(12), command=lambda _: self._filter_day())
        self.day_filter.pack(side="left", padx=12)
        self.button(tools, "Montaż zaznaczonych", lambda: self.show_page("studio"), True, width=176).pack(side="right")
        self.button(tools, "Importuj klipy", self.import_clips, width=112).pack(side="right", padx=8)
        self.button(tools, "Odśwież", self.refresh_library, width=86).pack(side="right")
        self.library_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent", scrollbar_button_color=BORDER)
        self.library_scroll.grid(row=1, column=0, sticky="nsew")
        self.library_scroll.grid_columnconfigure((0, 1, 2), weight=1, uniform="clip")
        self.library_checkboxes = {}
        self._create_library_slots()

    def _filter_day(self):
        self.library_page = 0
        self.refresh_library()

    def _create_library_slots(self):
        self.library_slots = []
        self.library_thumbnail_paths = {}
        for _ in range(self.library_page_size):
            slot = {"path": None, "day": ""}
            header = ctk.CTkFrame(self.library_scroll, fg_color="transparent")
            slot["header"] = header
            slot["date"] = self.label(header,"",16,bold=True)
            slot["date"].pack(side="left")
            self.button(header,"Zaznacz dzień",lambda s=slot:self.select_day(s["day"]),width=128,height=28).pack(side="right")
            card = self.card(self.library_scroll)
            slot["card"] = card
            slot["thumb"] = self.label(card, "MP4", 12, MUTED, width=256, height=144, fg_color=BG, corner_radius=6)
            slot["thumb"].pack(fill="x", padx=8, pady=(8, 0))
            slot["thumb"].bind("<Button-1>", lambda _, s=slot: os.startfile(str(s["path"])))
            details = ctk.CTkFrame(card, fg_color="transparent")
            details.pack(fill="x", padx=12, pady=(8, 6))
            slot["name"] = self.label(details, "", 13, bold=True, anchor="w", wraplength=236, justify="left")
            slot["name"].pack(fill="x")
            slot["info"] = self.label(details, "", 11, MUTED, anchor="w")
            slot["info"].pack(fill="x")
            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.pack(fill="x", padx=12, pady=(0, 10))
            checkbox = LCheckBox(actions, text="", width=24, checkbox_width=18, checkbox_height=18,
                fg_color=ACCENT, hover_color=ACCENT_HOVER, checkmark_color=BG, command=lambda s=slot: self.select_clip(s["path"]))
            checkbox.pack(side="left")
            slot["checkbox"] = checkbox
            self.button(actions, "Odtwórz", lambda s=slot: os.startfile(str(s["path"])), width=78, height=28).pack(side="right")
            self.button(actions, "Edytuj", lambda s=slot: self.edit_clip(s["path"]), width=66, height=28).pack(side="right", padx=6)
            self.library_slots.append(slot)
        self.library_empty = self.card(self.library_scroll)
        self.label(self.library_empty,"Brak klipów",24,bold=True).pack(pady=(48,10))
        self.label(self.library_empty,"Zapisz powtórkę klawiszem F8 lub importuj własne nagrania.",13,MUTED).pack(pady=(0,48))
        self.library_navigation = ctk.CTkFrame(self.library_scroll,fg_color="transparent")
        self.previous_page = self.button(self.library_navigation,"← Poprzednia",lambda:self._library_page(-1),width=140)
        self.previous_page.pack(side="left")
        self.page_number = self.label(self.library_navigation,"",12,MUTED)
        self.page_number.pack(side="left",padx=20)
        self.next_page = self.button(self.library_navigation,"Następna →",lambda:self._library_page(1),width=140)
        self.next_page.pack(side="left")

    def refresh_library(self):
        folder = Path(self.config_data["save_folder"])
        self.files = sorted([p for p in folder.rglob("*.mp4") if ".partial." not in p.name and "autoclip_montage_" not in str(p)],
            key=lambda p:p.stat().st_mtime,reverse=True) if folder.exists() else []
        self.selected.intersection_update(set(self.files))
        days = list(dict.fromkeys(datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y") for p in self.files))
        self.day_filter.configure(values=["Wszystkie dni"]+days)
        active_day = self.day_filter.get()
        if active_day not in ["Wszystkie dni"]+days:
            active_day = "Wszystkie dni"
            self.day_filter.set(active_day)
        visible = [p for p in self.files if active_day == "Wszystkie dni" or datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y")==active_day]
        self.library_navigation.grid_remove()
        self.library_empty.grid_remove()
        self.library_checkboxes = {}
        self.library_thumbnail_paths = {}
        self.thumbnail_images.clear()
        size = sum(p.stat().st_size for p in self.files)/(1024**3)
        self.library_count.configure(text=f"{len(self.files)} klipów  /  {size:.2f} GB  /  zaznaczono {len(self.selected)}")
        max_page = max(0,(len(visible)-1)//self.library_page_size)
        self.library_page = min(self.library_page,max_page)
        offset = self.library_page*self.library_page_size
        page_files = visible[offset:offset+self.library_page_size]
        for slot in self.library_slots:
            slot["card"].grid_remove()
            slot["header"].grid_remove()
        day = None
        row, column = 0, 0
        for path, slot in zip(page_files, self.library_slots):
            slot["path"] = path
            this_day = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y")
            slot["day"] = this_day
            if this_day != day:
                if column:
                    row += 1
                    column = 0
                day = this_day
                slot["date"].configure(text=day)
                slot["header"].grid(row=row, column=0, columnspan=3, sticky="ew", padx=5, pady=(10, 8))
                row += 1
            slot["card"].grid(row=row, column=column, sticky="nsew", padx=5, pady=(0, 10))
            column += 1
            if column == 3:
                column = 0
                row += 1
            checkbox = slot["checkbox"]
            checkbox.select() if path in self.selected else checkbox.deselect()
            self.library_checkboxes[path] = checkbox
            try:
                metadata = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = None
            fallback = path.stem if len(path.stem) <= 28 else path.stem[:27] + "…"
            slot["name"].configure(text=clip_event_label(metadata) or fallback)
            stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M")
            slot["info"].configure(text=f"{stamp}   ·   {path.stat().st_size/(1024**2):.1f} MB")
            thumb = slot["thumb"]
            thumb.configure(image=None,text="MP4")
            self.library_thumbnail_paths[thumb] = path
            future = self.thumbnail_pool.submit(self._thumbnail,path)
            future.add_done_callback(lambda f,p=path,w=thumb:self.post(self._set_thumbnail,p,w,f.result()) if not f.cancelled() and f.exception() is None else None)
        if not page_files:
            self.library_empty.grid(row=0, column=0, columnspan=3, sticky="ew", padx=5, pady=20)
        if max_page:
            self.previous_page.configure(state="normal" if self.library_page else "disabled")
            self.next_page.configure(state="normal" if self.library_page<max_page else "disabled")
            self.page_number.configure(text=f"Strona {self.library_page+1} / {max_page+1}")
            self.library_navigation.grid(row=row + bool(column), column=0, columnspan=3, sticky="ew", padx=5, pady=12)

    def _library_page(self,delta):
        self.library_page = max(0,self.library_page+delta)
        self.refresh_library()
        self.library_scroll._parent_canvas.yview_moveto(0)

    @staticmethod
    def _thumbnail(path):
        try:
            result = subprocess.run([
                find_binary("ffmpeg"), "-nostdin", "-v", "error", "-threads", "1", "-i", str(path),
                "-map", "0:v:0", "-an", "-filter_threads", "1",
                "-vf", "scale=512:288:force_original_aspect_ratio=increase,crop=512:288",
                "-frames:v", "1", "-c:v", "mjpeg", "-threads", "1", "-f", "image2pipe", "pipe:1",
            ], capture_output=True, timeout=8, creationflags=NO_WINDOW, check=True)
            with Image.open(BytesIO(result.stdout)) as image:
                return image.convert("RGB")
        except (OSError, subprocess.SubprocessError):
            return None

    def _set_thumbnail(self, path, widget, image):
        if image is not None and widget.winfo_exists() and self.library_thumbnail_paths.get(widget) == path:
            thumb = AppImage(self,image,size=(256,144))
            self.thumbnail_images[path] = thumb
            widget.configure(text="", image=thumb)

    def select_clip(self, path):
        if path in self.selected:
            self.selected.remove(path)
        else:
            self.selected.add(path)
        self.library_count.configure(text=f"{len(self.files)} klipów  /  zaznaczono {len(self.selected)}")

    def select_day(self, day):
        for path in self.files:
            if datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y") == day:
                self.selected.add(path)
                if path in self.library_checkboxes:
                    self.library_checkboxes[path].select()
        self.library_count.configure(text=f"{len(self.files)} klipów  /  zaznaczono {len(self.selected)}")

    def import_clips(self):
        import shutil
        paths = filedialog.askopenfilenames(filetypes=[("Nagrania MP4", "*.mp4")])
        folder = Path(self.config_data["save_folder"])
        folder.mkdir(parents=True, exist_ok=True)
        for src in paths:
            dest = folder / Path(src).name
            if dest.resolve() == Path(src).resolve():
                continue
            if dest.exists():
                dest = folder / f"{Path(src).stem}_{time.time_ns()}.mp4"
            shutil.copy2(src, dest)
            sidecar = Path(str(src)+".json")
            if sidecar.exists():
                shutil.copy2(sidecar, str(dest)+".json")
        self.refresh_library()

    def edit_clip(self, path):
        dialog = ctk.CTkToplevel(self)
        dialog.title(t("Przytnij / przygotuj Shorts"))
        dialog.geometry("440x360")
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        self.label(dialog, "Dopasuj ten moment", 23, bold=True).pack(anchor="w", padx=24, pady=(24, 16))
        self.label(dialog, "Początek i długość w sekundach", 12, MUTED).pack(anchor="w", padx=24)
        start = LEntry(dialog, height=36)
        start.insert(0, "0")
        start.pack(fill="x", padx=24, pady=6)
        duration = LEntry(dialog, height=36)
        duration.insert(0, "20")
        duration.pack(fill="x", padx=24, pady=6)
        aspect = LOptionMenu(dialog, values=["YouTube · 16:9", "Shorts · 9:16"], fg_color=RAISED, button_color=BORDER)
        aspect.pack(fill="x", padx=24, pady=8)
        def export():
            try:
                begin, length = float(start.get()), float(duration.get())
                if begin < 0 or length <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Nieprawidłowy zakres", "Podaj początek ≥ 0 i długość > 0.", parent=dialog)
                return
            vertical = "9:16" in aspect.get()
            out = path.with_name(path.stem + ("_shorts_" if vertical else "_trim_") + datetime.now().strftime("%H%M%S") + ".mp4")
            dialog.destroy()
            self.activity("Eksport ujęcia", out.name, BLUE)
            self.background(lambda: VideoEditor.trim_clip(path, begin, length, out, self.config_data["video_codec"], vertical),
                lambda _: self._render_done(out))
        self.button(dialog, "Zapisz nowy klip", export, True).pack(fill="x", padx=24, pady=16)

    def _build_studio(self):
        page = self.scroll_page("studio")
        panel = self.card(page)
        panel.pack(fill="x", pady=(0, 16))
        self.label(panel, "01  /  TWOJE UJĘCIA", 10, ACCENT, True).pack(anchor="w", padx=24, pady=(20, 8))
        self.selection_label = self.label(panel, "Zaznacz klipy w bibliotece.", 14, bold=True)
        self.selection_label.pack(anchor="w", padx=24)
        self.selection_list = LTextbox(panel, height=120, fg_color=BG, font=font(12), text_color=MUTED)
        self.selection_list.pack(fill="x", padx=24, pady=12)
        self.button(panel, "Wybierz klipy w bibliotece", lambda: self.show_page("library"), width=220).pack(anchor="w", padx=24, pady=(0, 20))
        panel = self.card(page)
        panel.pack(fill="x", pady=(0, 16))
        self.label(panel, "02  /  MONTAŻ I FORMAT", 10, ACCENT, True).pack(anchor="w", padx=24, pady=(20, 12))
        self.montage_format = self._option(panel, "Gdzie opublikujesz film?", ["YouTube · 16:9", "Shorts / Reels · 9:16"])
        self.selection_modes={"Automatyczne wycinki":"highlights","Wszystkie zapisane znaczniki":"markers","Ręcznie: krótki wybór":"short","Pełne klipy · bez skracania":"preserve"}
        self.selection_mode=self._option(panel,"Co zachować w filmie?",list(self.selection_modes))
        self.selection_mode.configure(command=self._selection_mode_changed)
        filter_row=ctk.CTkFrame(panel,fg_color="transparent")
        filter_row.pack(fill="x",padx=24,pady=(10,8))
        self.include_kills=tk.BooleanVar(master=self,value=True)
        self.include_assists=tk.BooleanVar(master=self,value=True)
        self.include_voice=tk.BooleanVar(master=self,value=True)
        self.event_checkboxes=[]
        for text,var in (("Akcje w grze",self.include_kills),("Asysty",self.include_assists),("Reakcje i rozmowy",self.include_voice)):
            box=LCheckBox(filter_row,text=text,variable=var,command=self._invalidate_plan,
                fg_color=ACCENT,hover_color=ACCENT_HOVER,text_color=TEXT,checkmark_color=BG,font=font(12))
            box.pack(side="left",padx=(0,22));self.event_checkboxes.append(box)
        self.assist_rule=self._option(panel,"Które asysty?",["Wszystkie asysty","Przy eliminacji · do 8 s","Przy eliminacji · do 15 s"])
        self.assist_rule.configure(command=lambda _:self._invalidate_plan())
        self.montage_duration = self._option(panel, "Zakres znacznika / ręcznego skrótu", ["8 sekund", "5 sekund", "12 sekund", "20 sekund"])
        self.montage_style = self._option(panel, "Łączenie ujęć", ["Czyste cięcia", "Krótkie przenikanie"])
        self.montage_order = self._option(panel, "Kolejność materiałów", ["Chronologicznie", "Najnowsze najpierw"])
        for menu in (self.montage_duration,self.montage_style,self.montage_order,self.montage_format):
            menu.configure(command=lambda _:self._invalidate_plan())
        self.preview_button=self.button(panel,"Sprawdź długość filmu",self.preview_montage,width=225)
        self.preview_button.pack(anchor="w",padx=24,pady=(12,6))
        self.plan_label=self.label(panel,"Długość po wyborze akcji: kliknij przycisk powyżej.",13,ACCENT,wraplength=800,justify="left")
        self.plan_label.pack(anchor="w",padx=24,pady=(0,20))
        self._selection_mode_changed()
        panel=self.card(page)
        panel.pack(fill="x",pady=(0,16))
        self.label(panel,"03  /  MUZYKA I GOTOWY FILM",10,ACCENT,True).pack(anchor="w",padx=24,pady=(20,10))
        self.music_entry = LEntry(panel, placeholder_text="Opcjonalny plik z muzyką", height=36, fg_color=BG, border_color=BORDER)
        self.music_entry.pack(fill="x", padx=24, pady=(0,6))
        self.button(panel, "Wybierz muzykę", self._choose_music, width=150).pack(anchor="w", padx=24, pady=(0,12))
        row=ctk.CTkFrame(panel,fg_color="transparent");row.pack(fill="x",padx=24,pady=(0,12))
        self.music_gain_label=self.label(row,"Głośność muzyki · 16%",12,MUTED)
        self.music_gain_label.pack(side="left")
        self.music_gain=ctk.CTkSlider(row,from_=0,to=60,number_of_steps=60,width=250,progress_color=ACCENT,
            command=lambda value:self.music_gain_label.configure(text=f"Głośność muzyki · {value:.0f}%"))
        self.music_gain.set(16);self.music_gain.pack(side="right")
        self.completed_label=self.label(panel,"Możesz najpierw zmontować film, obejrzeć go i dopiero dodać podkład.",12,MUTED,wraplength=800,justify="left")
        self.completed_label.pack(anchor="w",padx=24,pady=(0,10))
        row=ctk.CTkFrame(panel,fg_color="transparent");row.pack(fill="x",padx=24,pady=(0,20))
        self.choose_movie_button=self.button(row,"Wybierz gotowy film",self._choose_completed_movie,width=180)
        self.choose_movie_button.pack(side="left",padx=(0,8))
        self.play_movie_button=self.button(row,"Odtwórz",lambda:os.startfile(self.last_movie_path),width=100,state="disabled")
        self.play_movie_button.pack(side="left",padx=(0,8))
        self.mix_button=self.button(row,"Dodaj muzykę do filmu",self.add_music_to_movie,width=205,state="disabled")
        self.mix_button.pack(side="left")
        export = self.card(page)
        export.pack(fill="x")
        self.export_button = self.button(export, "Eksportuj gotowy film", self.export_montage, True, width=225, height=44)
        self.export_button.pack(anchor="w", padx=24, pady=(20, 12))
        self.cancel_montage = self.button(export,"Anuluj montaż",self.job_cancel.set,width=160,state="disabled")
        self.cancel_montage.pack(anchor="w",padx=24,pady=(0,10))
        self.job_progress = ctk.CTkProgressBar(export, progress_color=ACCENT, fg_color=BORDER)
        self.job_progress.pack(fill="x", padx=24, pady=4)
        self.job_progress.set(0)
        self.job_status = self.label(export, "MP4 · 1080p · 60 FPS · wyrównany dźwięk", 12, MUTED, wraplength=750, justify="left")
        self.job_status.pack(anchor="w", padx=24, pady=(4, 20))

    def _option(self, parent, text, values, current=None, *, width=250):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=6)
        self.label(row, text, 12, MUTED).pack(side="left")
        menu = LOptionMenu(row, values=values, width=width, height=34, fg_color=RAISED,
            button_color=BORDER, button_hover_color=BORDER, font=font(12), dropdown_font=font(12))
        menu.pack(side="right")
        if current:
            menu.set(current)
        return menu

    def _selection_mode_changed(self,choice=None):
        mode=self.selection_modes[self.selection_mode.get()]
        self.montage_duration.configure(state="disabled" if mode in ("preserve","highlights") else "normal")
        self.montage_style.configure(state="disabled" if mode=="preserve" else "normal")
        if mode=="preserve":self.montage_style.set("Czyste cięcia")
        for box in getattr(self,"event_checkboxes",[]):box.configure(state="normal" if mode=="highlights" else "disabled")
        if hasattr(self,"assist_rule"):self.assist_rule.configure(state="normal" if mode=="highlights" else "disabled")
        self._invalidate_plan()

    def _invalidate_plan(self):
        if hasattr(self,"plan_label"):
            self.plan_label.configure(text="Długość po wyborze akcji: kliknij «Sprawdź długość filmu».")

    def _event_options(self):
        rule=self.assist_rule.get()
        return {"kills":self.include_kills.get(),"assists":self.include_assists.get(),"voice":self.include_voice.get(),
                "assist_near_seconds":8 if "8 s" in rule else 15 if "15 s" in rule else None}

    def _studio_settings(self):
        return {"clip_paths":sorted(self.selected,key=lambda p:p.stat().st_mtime,reverse="Najnowsze" in self.montage_order.get()),
                "clip_duration":int(self.montage_duration.get().split()[0]),"codec":self.config_data["video_codec"],
                "selection_mode":self.selection_modes[self.selection_mode.get()],
                "transitions":"przenikanie" in self.montage_style.get(),"event_options":self._event_options()}

    @staticmethod
    def _duration_text(seconds):
        seconds=max(0,round(seconds))
        return f"{seconds//60}:{seconds%60:02}"

    def _begin_studio_job(self,text):
        self.job_busy=True;self.job_started=time.monotonic();self.job_cancel.clear()
        self.cancel_montage.configure(state="normal")
        self.export_button.configure(state="disabled",text=text)
        for button in (self.preview_button,self.mix_button,self.choose_movie_button):button.configure(state="disabled")
        self.job_status.configure(text=text,text_color=MUTED)
        self.job_progress.set(0)

    def _finish_studio_job(self):
        self.job_busy=False
        self.export_button.configure(state="normal",text="Eksportuj gotowy film")
        self.cancel_montage.configure(state="disabled")
        self.preview_button.configure(state="normal")
        self.choose_movie_button.configure(state="normal")
        self.mix_button.configure(state="normal" if self.last_movie_path else "disabled")

    def preview_montage(self):
        if self.job_busy:return
        self._refresh_selection()
        if not self.selected:self.show_page("library");return
        settings=self._studio_settings()
        self._begin_studio_job("Analizuję długość i wybór akcji…")
        self.background(lambda:plan_montage(**settings,on_progress=lambda value,msg:self.post(self._montage_progress,value,msg),
            cancelled=self.job_cancel.is_set),lambda plan:self._preview_done(plan,settings),job=True)

    def _preview_done(self,plan,settings):
        self._finish_studio_job();self.job_progress.set(1)
        if settings!=self._studio_settings():
            self._invalidate_plan();self.job_status.configure(text="Ustawienia zmieniły się podczas analizy. Przelicz długość ponownie.")
            return
        removed=plan["deduplication"]["removed_seconds"]
        self.plan_label.configure(text=f"Około {self._duration_text(plan['estimated_duration'])} · {len(plan['jobs'])} ujęć"+
            (f" · usunięto {removed:.1f} s powtórek" if removed>.1 else "")+
            (f" · ostrzeżenia: {len(plan.get('source_warnings',[]))}" if plan.get('source_warnings') else ""))
        self.job_status.configure(text="Plan gotowy. Możesz zmienić filtry, wybrać muzykę lub wyeksportować film.",text_color=ACCENT)

    def _show_completed_movie(self,path):
        info=probe(path)
        self.last_movie_path=Path(path)
        duration=self._duration_text(float(info["format"]["duration"]))
        self.completed_label.configure(text=f"Gotowy film · {duration} · {Path(path).name}",text_color=ACCENT)
        self.mix_button.configure(state="disabled" if self.job_busy else "normal")
        self.play_movie_button.configure(state="normal")
        return duration

    def _choose_completed_movie(self):
        if self.job_busy:return
        path=filedialog.askopenfilename(title="Wybierz gotowy film do udźwiękowienia",filetypes=[("Film MP4","*.mp4")])
        if path:
            try:self._show_completed_movie(path)
            except (OSError,RuntimeError,ValueError) as exc:messagebox.showerror("Nie można otworzyć filmu",str(exc))

    def add_music_to_movie(self):
        if self.job_busy or not self.last_movie_path:return
        if not self.music_entry.get().strip():self._choose_music()
        music=self.music_entry.get().strip()
        if not music:return
        source=self.last_movie_path
        out=filedialog.asksaveasfilename(title="Zapisz wersję z muzyką",defaultextension=".mp4",
            initialdir=str(source.parent),initialfile=source.stem+"_z_muzyka.mp4",filetypes=[("Film MP4","*.mp4")])
        if not out:return
        if Path(out).resolve()==source.resolve():
            messagebox.showerror("Wybierz inną nazwę","Zachowaj oryginał i zapisz wersję z muzyką pod inną nazwą.");return
        gain=self.music_gain.get()/100
        self._begin_studio_job("Dodaję muzykę…")
        self.background(lambda:VideoEditor.add_music(source,music,out,gain,self.job_cancel.is_set,
            lambda value:self.post(self._montage_progress,value,"Dodawanie podkładu")),lambda _:self._render_done(Path(out)),job=True)

    def _refresh_selection(self):
        self.selected = {p for p in self.selected if p.exists()}
        selection=tuple(sorted(str(p) for p in self.selected))
        if selection!=self.plan_selection:
            self.plan_selection=selection;self._invalidate_plan()
        self.selection_label.configure(text=f"{len(self.selected)} klipów w Twoim filmie")
        self.selection_list.configure(state="normal")
        self.selection_list.delete("1.0", "end")
        for i, path in enumerate(sorted(self.selected, key=lambda p: p.stat().st_mtime), 1):
            self.selection_list.insert("end", f"{i:02}.  {path.name}\n")
        self.selection_list.configure(state="disabled")

    def _choose_music(self):
        path = filedialog.askopenfilename(filetypes=[("Muzyka", "*.mp3 *.wav *.flac *.m4a *.ogg")])
        if path:
            self.music_entry.delete(0, "end")
            self.music_entry.insert(0, path)

    def export_montage(self):
        if self.job_busy:
            return
        self._refresh_selection()
        if not self.selected:
            self.show_page("library")
            return
        out = filedialog.asksaveasfilename(title="Zapisz gotowy film", defaultextension=".mp4",
            initialfile=f"FrapGrab_Highlights_{datetime.now():%Y-%m-%d}.mp4", initialdir=self.config_data["save_folder"], filetypes=[("Film MP4", "*.mp4")])
        if not out:
            return
        if Path(out).resolve() in {p.resolve() for p in self.selected}:
            messagebox.showerror("Wybierz inną nazwę", "Film wynikowy nie może zastąpić wybranego klipu źródłowego.")
            return
        clips = sorted(self.selected, key=lambda p: p.stat().st_mtime, reverse="Najnowsze" in self.montage_order.get())
        duration = int(self.montage_duration.get().split()[0])
        vertical = "9:16" in self.montage_format.get()
        transitions = "przenikanie" in self.montage_style.get()
        music = self.music_entry.get().strip()
        codec = self.config_data["video_codec"]
        mode=self.selection_modes[self.selection_mode.get()]
        options=self._event_options()
        gain=self.music_gain.get()/100
        self._begin_studio_job("Trwa montaż…")
        self.background(lambda: VideoEditor.create_montage(clips, out, duration, music, codec, vertical, transitions,
            lambda value, msg: self.post(self._montage_progress, value, msg),self.job_cancel.is_set,mode,options,gain), lambda _: self._render_done(Path(out)), job=True)

    def _montage_progress(self, value, text):
        self.job_progress.set(value)
        elapsed = int(time.monotonic()-self.job_started)
        self.job_status.configure(text=f"{value:.0%} · {elapsed//60}:{elapsed%60:02} · {text}")

    def _render_done(self, path):
        self._finish_studio_job()
        duration=self._show_completed_movie(path)
        self.job_status.configure(text=f"Film gotowy · {duration} · {path.name}", text_color=ACCENT)
        self.activity("Eksport zakończony", path.name)
        try:report=json.loads(Path(str(path)+".edit.json").read_text(encoding="utf-8"))
        except (OSError,ValueError):report={}
        issues=report.get("unclassified_sources",[])
        tails=report.get("tail_limited_sources",[])
        source_warnings=report.get("source_warnings",[])
        removed=report.get("deduplication",{}).get("removed_seconds",0)
        details=f"Zapisano film · {duration}:\n{path}"
        if removed>.1:details+=f"\n\nUsunięto {removed:.1f} s powtórzonego materiału."
        if issues:
            details+="\n\nNie rozpoznano akcji w:\n"+"\n".join(Path(item["source"]).name+": "+item["reason"] for item in issues)
        if tails:
            details+="\n\nNagranie źródłowe kończy się tuż po akcji. Zachowano jego końcówkę, ale dalszy ciąg nie jest zapisany:\n"+"\n".join(Path(item).name for item in tails)
        if source_warnings:
            details+="\n\nNiepełne nagrania lub znaczniki poza plikiem:\n"+"\n".join(Path(item['source']).name for item in source_warnings)
        if issues or tails or source_warnings:
            self.job_status.configure(text="Skrót zapisany · sprawdź informacje o źródłach",text_color=BLUE)
            if not self.game_foreground:messagebox.showwarning("Film zapisany — informacje o źródłach",details)
        elif not self.game_foreground:messagebox.showinfo("Film gotowy",details)
        if self.active_page == "library":
            self.refresh_library()

    def _build_scanner(self, page):
        panel = self.card(page)
        panel.pack(fill="x")
        self.label(panel, "Nagranie do analizy", 20, bold=True).pack(anchor="w", padx=24, pady=(22, 8))
        self.scan_path = LEntry(panel, placeholder_text="Wybierz nagranie meczu…", height=38, fg_color=BG, border_color=BORDER)
        self.scan_path.pack(fill="x", padx=24, pady=16)
        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.pack(fill="x", padx=24, pady=(0, 16))
        self.button(controls, "Wybierz nagranie", self._choose_recording, width=160).pack(side="left")
        self.scan_button = self.button(controls, "Rozpocznij analizę", self.start_scan, True, width=180)
        self.scan_button.pack(side="left", padx=10)
        self.button(controls, "Anuluj", lambda: self.scan.cancel() if self.scan else None, width=80).pack(side="left")
        self.scan_progress = ctk.CTkProgressBar(panel, progress_color=ACCENT, fg_color=BORDER)
        self.scan_progress.pack(fill="x", padx=24, pady=(0, 16))
        self.scan_progress.set(0)
        self.scan_results = LTextbox(page, height=300, fg_color=CARD, font=font(12), text_color=TEXT)
        self.scan_results.pack(fill="both", expand=True, pady=16)
        self.scan_export = self.button(page, "Zapisz wykryte akcje jako klipy", self.export_scanned, True, width=260)
        self.scan_export.pack(anchor="w")

    def _choose_recording(self):
        path = filedialog.askopenfilename(filetypes=[("Nagrania", "*.mp4 *.mkv *.mov *.avi")])
        if path:
            self.scan_path.delete(0, "end")
            self.scan_path.insert(0, path)

    def start_scan(self):
        if self.job_busy:
            return
        self._save_gamertag()
        if not Path(self.scan_path.get()).is_file() or len(self.config_data["gamertag"]) < 3:
            messagebox.showinfo("Przygotuj analizę", "Wybierz plik i wpisz nick w ustawieniach tej gry (minimum 3 znaki).")
            return
        self.job_busy = True
        self.scan_button.configure(state="disabled", text="Analizuję…")
        self.scanned_events = []
        self.scanned_video = self.scan_path.get()
        self.scan_results.delete("1.0", "end")
        self.scan = MatchScanner(self.scanned_video, self.config_data["gamertag"],
            lambda value, count: self.post(self._scan_progress, value, count))
        self.background(self.scan.scan, self._scan_finished, job=True)

    def _scan_progress(self, value, count):
        self.scan_progress.set(value)
        self.scan_button.configure(text=f"{int(value*100)}% · {count} akcji")

    def _scan_finished(self, events):
        self.job_busy = False
        self.scanned_events = events
        self.scan_button.configure(state="normal", text="Rozpocznij analizę")
        self.scan_results.delete("1.0", "end")
        cancelled = self.scan.stop_requested
        self.scan_results.insert("end", f"{'Przerwano analizę' if cancelled else 'Analiza zakończona'} · {len(events)} akcji\n\n")
        for ev in events:
            self.scan_results.insert("end", f"{ev['time_str']}   {ev['type']}   {ev['raw_text']}\n")

    def export_scanned(self):
        if self.job_busy or not self.scanned_events:
            return
        source, events = self.scanned_video, list(self.scanned_events)
        cfg = self.config_data.copy()
        self.job_busy = True
        def worker():
            folder = Path(cfg["save_folder"]) / datetime.now().strftime("Analiza_%Y-%m-%d_%H-%M-%S")
            folder.mkdir(parents=True, exist_ok=True)
            for i, event in enumerate(events):
                out = folder / f"Akcja_{i+1:03}_{event['time_str'].replace(':','-')}.mp4"
                ClipRenderer.render_single_clip(source, event["timestamp"], out, cfg["clip_before_kill"], cfg["clip_after_kill"], False, cfg["video_codec"])
                offset = min(cfg["clip_before_kill"], event["timestamp"])
                Path(str(out)+".json").write_text(json.dumps({"event_offsets": [offset], "reason": event["event_type"]}), encoding="utf-8")
            return folder
        self.background(worker, self._scan_export_done, job=True)

    def _scan_export_done(self, folder):
        self.job_busy = False
        self.activity("Zapisano akcje z meczu", str(folder))
        self.show_page("library")

    def _build_settings(self):
        page = self.scroll_page("settings")
        recording = self.card(page)
        recording.pack(fill="x", pady=(0, 16))
        self.language_option=self._option(recording,"Język / Language",["Polski","English"],"English" if self.config_data["language"]=="en" else "Polski")
        self.language_option.configure(command=self._language_changed)
        self.button(recording,"Konfiguracja początkowa",self.open_setup,width=230).pack(anchor="w",padx=24,pady=(8,12))
        self.label(recording, "Nagrywanie", 19, bold=True).pack(anchor="w", padx=24, pady=(20, 12))
        profile=self.hardware["selected_profile"]
        self.gpu_profile_label=self.label(recording,f"{profile['gpu']}\n{profile['label']} · enkoder sprawdzony testem" if self.hardware["hardware_encoding"] else "Brak działającego enkodera GPU · awaryjny profil CPU, 30 FPS",
            12,ACCENT if self.hardware["hardware_encoding"] else RED,wraplength=800,justify="left")
        self.gpu_profile_label.pack(anchor="w",padx=24,pady=(0,10))
        self.auto_gpu_switch=LSwitch(recording,text="Automatycznie dobieraj ustawienia do karty graficznej",font=font(12,True),
            progress_color=ACCENT,button_color=TEXT,command=self._gpu_auto_changed)
        self.auto_gpu_switch.pack(anchor="w",padx=24,pady=(0,10))
        if self.config_data.get("auto_gpu_settings",True):self.auto_gpu_switch.select()
        options = self.hardware["supported_options"] or [("Procesor · H.264", "libx264")]
        self.codec_map = dict(options)
        current = next((label for label, code in options if code == self.config_data["video_codec"]), options[0][0])
        self.codec_option = self._option(recording, "Enkoder", list(self.codec_map), current)
        self.quality_option = self._option(recording, "Jakość / bitrate", ["Medium · 15 Mb/s", "High · 25 Mb/s", "Ultra · 50 Mb/s"],
            {"Medium": "Medium · 15 Mb/s", "High": "High · 25 Mb/s", "Ultra": "Ultra · 50 Mb/s"}.get(self.config_data["video_quality"]))
        self.fps_option = self._option(recording, "Klatki na sekundę", ["60", "30"], str(self.config_data["capture_fps"]))
        self.buffer_option = self._option(recording, "Długość bufora", ["30", "45", "60", "90", "120", "180", "300", "600", "900", "1800"], str(self.config_data["buffer_seconds"]))
        self.monitor_map = {f"{m['index']} · {m['width']} × {m['height']} ({m['left']}, {m['top']})": m["index"] for m in outputs()}
        monitor_label = next((label for label, index in self.monitor_map.items() if index == self.config_data["capture_output"]), next(iter(self.monitor_map)))
        self.monitor_option = self._option(recording, "Ekran do przechwytywania", list(self.monitor_map), monitor_label)
        self.monitor_option.configure(command=lambda _:self._gpu_auto_changed())
        self._gpu_auto_changed()
        self.audio_switch = self._switch(recording, "Nagrywaj dźwięk systemowy (WASAPI)", "desktop_audio")
        self.record_mic_switch=self._switch(recording,"Zapisuj mój mikrofon w filmie","record_microphone")
        self.record_chat_switch=self._switch(recording,"Zapisuj dodatkowe źródło rozmów","record_chat")
        self.chat_device_map={"Automatycznie · Sonar":""}
        try:
            for name in output_devices():self.chat_device_map[name]=name
        except Exception:logging.exception("Could not enumerate conversation outputs")
        selected_chat=self.config_data["chat_device"]
        if selected_chat:self.chat_device_map[selected_chat]=selected_chat
        self.chat_device_option=self._option(recording,"Źródło rozmów",list(self.chat_device_map),
            next(label for label,name in self.chat_device_map.items() if name==selected_chat))
        self.game_switch = self._switch(recording, "Nagrywaj tylko gdy okno wybranej gry jest aktywne", "record_only_in_game")
        self.start_switch = self._switch(recording, "Włącz nagrywanie przy starcie aplikacji", "auto_record_enabled")
        self.label(recording, "Audio pochodzi z domyślnego wyjścia Windows, także z innych aplikacji.\nObraz obejmuje cały ekran. Alt+Tab w trybie gry wstrzymuje nagrywanie.",
            12, MUTED, justify="left").pack(anchor="w", padx=24, pady=(8, 18))
        self.hotkey_entry = self._entry(recording, "Skrót zapisu", self.config_data["manual_hotkey"])
        self.folder_entry = self._entry(recording, "Folder klipów", self.config_data["save_folder"])
        self.button(recording, "Wybierz folder", self._choose_folder, width=150).pack(anchor="w", padx=24, pady=(8, 12))
        self.alert_switch = self._switch(recording, "Potwierdzenie dźwiękowe po zapisaniu klipu", "sound_alert")
        update=self.card(page);update.pack(fill="x",pady=(0,16))
        self.label(update,"Aktualizacje",19,bold=True).pack(anchor="w",padx=24,pady=(20,10))
        self.update_auto_switch=self._switch(update,"Sprawdzaj aktualizacje przy uruchomieniu","auto_update_check")
        self.update_status=self.label(update,f"Wersja {CURRENT_VERSION}",12,MUTED,wraplength=800,justify="left")
        self.update_status.pack(anchor="w",padx=24,pady=(10,8))
        row=ctk.CTkFrame(update,fg_color="transparent");row.pack(fill="x",padx=24,pady=(0,20))
        self.check_update_button=self.button(row,"Sprawdź aktualizacje",self._check_updates,width=200)
        self.check_update_button.pack(side="left",padx=(0,10))
        self.download_update_button=self.button(row,"Pobierz aktualizację",self._download_update,width=210,state="disabled")
        self.download_update_button.pack(side="left")
        self.button(page, "Zapisz i zastosuj ustawienia", self.apply_settings, True, width=260, height=44).pack(anchor="w", pady=8)
        self.label(page, "Zmiana profilu nagrania rozpocznie nowy bufor. Zapisane klipy pozostają w bibliotece.", 12, MUTED).pack(anchor="w", pady=6)

    def _build_game_timing(self, parent):
        timing = self.card(parent)
        timing.pack(fill="x", pady=(0, 16))
        self.label(timing, "Długość klipu", 16, bold=True).pack(anchor="w", padx=24, pady=(16, 8))
        self.before_option = self._option(timing, "Sekundy przed akcją",
            ["5", "10", "15", "20", "30", "45", "60"], str(self.config_data["clip_before_kill"]), width=112)
        self.after_option = self._option(timing, "Sekundy po akcji",
            ["2", "3", "5", "8", "10", "15"], str(self.config_data["clip_after_kill"]), width=112)
        self.before_option.configure(command=lambda value: self._preference("clip_before_kill", int(value)))
        self.after_option.configure(command=lambda value: self._preference("clip_after_kill", int(value)))

    def _build_game_calibration(self):
        calibration = self.card(self.game_options)
        self.calibration_settings = calibration
        calibration.pack(fill="x", pady=(0, 16))
        self.label(calibration, "Detekcja i kalibracja", 19, bold=True).pack(anchor="w", padx=24, pady=(20, 8))
        self.detection_option = self._option(calibration, "Sposób wykrywania akcji", ["Grafika · bez OCR", "OCR · rozpoznawanie nicku"],
            "OCR · rozpoznawanie nicku" if self.config_data.get("detection_mode") == "ocr" else "Grafika · bez OCR")
        self.hud_auto_switch=self._switch(calibration,"Automatyczne dopasowanie HUD do ekranu","auto_hud")
        self.hud_status=self.label(calibration,"Profil aktywny" if self.config_data.get("pixel_profile") else "Zapisz powtórkę z eliminacją. HUD zostanie rozpoznany po wyjściu z gry.",12,MUTED,wraplength=800,justify="left")
        self.hud_status.pack(anchor="w",padx=24,pady=(6,10))
        self.button(calibration,"Wykryj HUD z powtórki",self._choose_auto_calibration,width=230).pack(anchor="w",padx=24,pady=(0,10))
        self.hud_advanced=ctk.CTkFrame(calibration,fg_color="transparent")
        self.button(calibration,"Zaawansowane",self._toggle_hud_advanced,width=150).pack(anchor="w",padx=24,pady=(0,16))
        region=", ".join(f"{v*100:g}" for v in self.config_data["killfeed_region"])
        self.region_entry=self._entry(self.hud_advanced,"Obszar HUD (%)",region)
        self.button(self.hud_advanced,"Kalibracja ręczna",self.calibrate_pixel,width=220).pack(anchor="w",padx=24,pady=(8,10))
        self.button(self.hud_advanced,"Test OCR",self.test_ocr,width=150).pack(anchor="w",padx=24,pady=(0,16))
        self.button(calibration, "Zapisz detekcję", self._save_game_detection, True, width=168).pack(anchor="w", padx=24, pady=(0, 16))

    def _save_game_detection(self):
        try:
            region = self._parse_region()
        except ValueError as exc:
            messagebox.showerror("Sprawdź ustawienia", str(exc), parent=self)
            return
        mode = "ocr" if self.detection_option.get().startswith("OCR") else "pixel"
        config = {**self.config_data, "killfeed_region": region, "detection_mode": mode}
        if region != self.config_data["killfeed_region"] and not config["auto_hud"]:
            config["pixel_profile"] = ""
        if not save_config(config):
            messagebox.showerror("Sprawdź ustawienia", "Nie można zapisać ustawień.", parent=self)
            return
        self.config_data = config
        self._nickname_hint()
        messagebox.showinfo("Zapisano", "Ustawienia detekcji zapisane.", parent=self)

    def _entry(self, parent, text, value):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=6)
        self.label(row, text, 12, MUTED, width=150, anchor="w").pack(side="left")
        entry = LEntry(row, height=34, fg_color=BG, border_color=BORDER, font=font(12))
        entry.pack(side="right", fill="x", expand=True, padx=(12, 0))
        entry.insert(0, value)
        return entry

    def open_setup(self):
        if self.closing:return
        if self.setup_wizard and self.setup_wizard.winfo_exists():self.setup_wizard.lift();return self.setup_wizard
        if self.armed or self.job_busy or self.capture_operation or self.exports_active:
            messagebox.showinfo("Konfiguracja początkowa","Zatrzymaj nagrywanie i poczekaj na zakończenie eksportu.");return
        from gui.onboarding import SetupWizard
        self.setup_wizard=SetupWizard(self,self.config_data,self.hardware,outputs(),self._setup_finished,self._setup_cancelled)
        return self.setup_wizard

    def _setup_cancelled(self):
        self.setup_wizard=None

    def _setup_finished(self,config):
        if not save_config(config):raise OSError("Nie można zapisać ustawień. Sprawdź uprawnienia do profilu użytkownika.")
        self.config_data=config
        self.game_option.set(GAMES[config['game_id']]['name'])
        self.setup_wizard=None
        self.pending_calibration=None
        if config["chat_device"]:self.chat_device_map[config["chat_device"]]=config["chat_device"]
        self.chat_device_option.configure(values=list(self.chat_device_map))
        self.chat_device_option.set(next(label for label,name in self.chat_device_map.items() if name==config["chat_device"]))
        self.hud_needs_calibration=not bool(config.get("pixel_profile"))
        self.gamertag.delete(0,"end");self.gamertag.insert(0,config["gamertag"])
        self.folder_entry.delete(0,"end");self.folder_entry.insert(0,config["save_folder"])
        for switch,key in ((self.kf_switch,"killfeed_enabled"),(self.mic_switch,"mic_enabled"),
                           (self.audio_switch,"desktop_audio"),(self.record_mic_switch,"record_microphone"),
                           (self.record_chat_switch,"record_chat")):
            switch.select() if config[key] else switch.deselect()
        self.auto_gpu_switch.select();self.hud_auto_switch.select()
        self.language_option.set("English" if config["language"]=="en" else "Polski")
        set_language(config["language"])
        self.ring.set_caption(t("W BUFORZE"))
        self.replay_length.set(next((label for label,value in self.replay_lengths.items() if value==config["manual_replay_seconds"]),f"{config['manual_replay_seconds']} s"))
        self.buffer_option.set(str(config["buffer_seconds"]))
        self.buffer_caption.configure(text=f"do {config['buffer_seconds']} sekund wstecz")
        self.monitor_option.set(next(label for label,index in self.monitor_map.items() if index==config["capture_output"]))
        self._gpu_auto_changed()
        self.detection_option.set("Grafika · bez OCR")
        self.metric_labels["format"].configure(text=f"{config['capture_fps']} FPS · MP4")
        self._nickname_hint()
        self._game_event_options()
        self.hud_status.configure(text="Profil aktywny" if config.get("pixel_profile") else "Zapisz powtórkę z eliminacją. HUD zostanie rozpoznany po wyjściu z gry." if config["killfeed_enabled"] else "Ręczny zapis F8")
        self.show_page("live")
        self.activity("Konfiguracja zapisana", "")

    def _gpu_auto_changed(self):
        auto=bool(self.auto_gpu_switch.get())
        if auto:
            index=self.monitor_map[self.monitor_option.get()]
            try:height=output_geometry(index)["height"]
            except ValueError:height=None
            cfg=apply_hardware_profile({**self.config_data,"auto_gpu_settings":True},self.hardware,height)
            self.codec_option.set(next(label for label,code in self.codec_map.items() if code==cfg["video_codec"]))
            self.quality_option.set({"Medium":"Medium · 15 Mb/s","High":"High · 25 Mb/s","Ultra":"Ultra · 50 Mb/s"}[cfg["video_quality"]])
            self.fps_option.set(str(cfg["capture_fps"]))
        for menu in (self.codec_option,self.quality_option,self.fps_option):menu.configure(state="disabled" if auto else "normal")

    def _language_changed(self,choice):
        self.config_data["language"]="en" if choice=="English" else "pl"
        save_config(self.config_data)
        set_language(self.config_data["language"])
        self.ring.set_caption(t("W BUFORZE"))

    def _choose_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, path)

    def _parse_region(self):
        parts = [float(p.strip())/100 for p in self.region_entry.get().split(",")]
        x, y, w, h = parts
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1-x and 0 < h <= 1-y):
            raise ValueError("Obszar OCR musi mieścić się na ekranie.")
        return parts

    def apply_settings(self):
        import keyboard
        try:
            hotkey = self.hotkey_entry.get().strip()
            keyboard.parse_hotkey(hotkey)
            if not hotkey:
                raise ValueError("Podaj skrót klawiszowy.")
            folder = Path(self.folder_entry.get().strip()).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            cfg = {"video_codec": self.codec_map[self.codec_option.get()], "video_quality": self.quality_option.get().split()[0],
                "game_id":self.game_map[self.game_option.get()],
                "auto_gpu_settings":bool(self.auto_gpu_switch.get()),
                "capture_fps": int(self.fps_option.get()), "buffer_seconds": int(self.buffer_option.get()),
                "manual_replay_seconds":min(self.config_data["manual_replay_seconds"],int(self.buffer_option.get())),
                "capture_output": self.monitor_map[self.monitor_option.get()], "manual_hotkey": hotkey,
                "save_folder": str(folder.resolve())}
            cfg["chat_device"]=self.chat_device_map[self.chat_device_option.get()]
        except Exception as exc:
            messagebox.showerror("Sprawdź ustawienia", str(exc))
            return
        self.config_data.update(cfg)
        self.update_info=None;self.update_installer=None
        self.download_update_button.configure(state="disabled",text="Pobierz aktualizację")
        self.replay_length.set(next((label for label,seconds in self.replay_lengths.items() if seconds==cfg["manual_replay_seconds"]),f"{cfg['manual_replay_seconds']} s"))
        save_config(self.config_data)
        self.hotkey_badge.configure(text=hotkey.upper())
        self.buffer_caption.configure(text=f"do {cfg['buffer_seconds']} sekund wstecz")
        self.metric_labels["format"].configure(text=f"{cfg['capture_fps']} FPS · MP4")
        self.detection_status.configure(text=self._detection_description())
        self._failed_capture = False
        if self.armed:
            self.background(self.live_detector.refresh_settings)
            if not self.capture_operation:
                self._capture_task(self.replay_buffer.stop_rolling_buffer)
        self.activity("Ustawienia zapisane", "Nowy profil zostanie użyty przy rozpoczęciu nagrania.")
        messagebox.showinfo("Zapisano", "Ustawienia zostały zastosowane.")

    def _check_updates(self):
        if self.update_busy or self.closing:return
        repo=self.config_data["github_repository"]
        try:updater=AutoUpdater(repo)
        except ValueError as exc:self.update_status.configure(text=str(exc));return
        self.config_data["github_repository"]=updater.repository
        save_config(self.config_data)
        self.update_busy=True
        self.update_info=None;self.update_installer=None
        self.download_update_button.configure(state="disabled",text="Pobierz aktualizację")
        self.check_update_button.configure(state="disabled")
        self.update_status.configure(text="Sprawdzanie aktualizacji…")
        def worker():
            try:self.post(self._update_checked,updater.check(),updater.repository)
            except Exception as exc:self.post(self._update_error,str(exc))
        self.background(worker)

    def _update_error(self,message):
        self.update_busy=False
        self.check_update_button.configure(state="normal")
        self.download_update_button.configure(state="normal" if self.update_info else "disabled")
        self.update_status.configure(text=message,text_color=MUTED)

    def _update_checked(self,info,repository=None):
        if repository and repository!=self.config_data["github_repository"]:
            self.update_info=None;self._update_error("Repozytorium zmienione. Sprawdź aktualizacje ponownie.");return
        self.update_busy=False;self.update_info=info if info["has_update"] else None
        self.update_installer=None
        self.config_data["last_update_check"]=int(time.time());save_config(self.config_data)
        self.download_update_button.configure(text="Pobierz aktualizację")
        self.check_update_button.configure(state="normal")
        self.download_update_button.configure(state="normal" if info["has_update"] else "disabled")
        self.update_status.configure(text=f"Dostępna wersja {info['version']}" if info["has_update"] else f"Wersja {CURRENT_VERSION} jest aktualna",text_color=ACCENT)
        if info["has_update"]:
            self.activity("Dostępna aktualizacja", info["version"])
            self._prompt_update(info)

    def _update_blocked(self):
        return (self.game_foreground or self.replay_buffer.is_recording or self.job_busy
                or self.capture_operation or self.exports_active or self.pending_auto
                or self.calibrating or self.setup_wizard or self.grab_current() is not None)

    def _prompt_update(self, info):
        if self.closing or info is not self.update_info or self.update_busy:
            return
        if self._update_blocked():
            self.after(1500, lambda: self._prompt_update(info))
            return
        if self.update_dialog and self.update_dialog.winfo_exists():
            self.update_dialog.destroy()
        dialog = ctk.CTkToplevel(self)
        self.update_dialog = dialog
        dialog.title(t("Dostępna aktualizacja"))
        x = self.winfo_rootx() + max(0, (self.winfo_width() - 570) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - 420) // 2)
        dialog.geometry(f"570x420{x:+d}{y:+d}")
        dialog.minsize(480, 330)
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        dialog.iconbitmap(str(Path(__file__).resolve().parents[1] / "assets/icon.ico"))
        style_window(dialog)
        self.label(dialog, f"Frap Grab {info['version']}", 23, bold=True).pack(anchor="w", padx=24, pady=(22, 4))
        self.label(dialog, "Zmiany w tej wersji", 13, MUTED).pack(anchor="w", padx=24, pady=(0, 10))
        notes = ctk.CTkTextbox(dialog, fg_color=CARD, text_color=TEXT, font=font(13), wrap="word")
        notes.pack(fill="both", expand=True, padx=24)
        notes.insert("1.0", release_notes_for_language(info["notes"], self.config_data["language"])
                     or t("Wydanie nie zawiera listy zmian."))
        notes.configure(state="disabled")
        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=18)

        def install():
            dialog.destroy()
            if info is not self.update_info:
                return
            self.show_page("settings")
            self.after_idle(lambda: self.pages["settings"]._parent_canvas.yview_moveto(1))
            self._download_update(install_after=True)

        self.button(actions, "Zainstaluj aktualizację", install, True, width=166).pack(side="right")
        self.button(actions, "Później", dialog.destroy, width=104).pack(side="right", padx=(0, 8))

    def _download_update(self, install_after=False):
        if self.update_busy or not self.update_info:return
        if self.update_installer:
            self._launch_update()
            return
        info=dict(self.update_info);updater=AutoUpdater(self.config_data["github_repository"])
        self.update_busy=True
        self.download_update_button.configure(state="disabled")
        self.check_update_button.configure(state="disabled")
        def worker():
            try:
                path=updater.download(info,lambda value:self.post(self._update_progress,value),lambda:self.closing)
                self.post(self._update_downloaded,path,updater.repository,install_after)
            except Exception as exc:self.post(self._update_error,str(exc))
        self.background(worker)

    def _update_downloaded(self,path,repository=None,install_after=False):
        if repository and repository!=self.config_data["github_repository"]:
            self.update_info=None;self._update_error("Repozytorium zmienione. Sprawdź aktualizacje ponownie.");return
        self.update_busy=False;self.update_installer=Path(path)
        self.check_update_button.configure(state="normal")
        self.download_update_button.configure(state="normal",text="Zainstaluj aktualizację")
        self.update_status.configure(text="Instalator pobrany · SHA-256 potwierdzone",text_color=ACCENT)
        if install_after:
            self._launch_update()

    def _launch_update(self):
        if self.closing or self._update_blocked() or game_status(self.config_data["game_id"])[1]:
            self.update_status.configure(text="Zatrzymaj nagrywanie i poczekaj na zakończenie eksportu.")
            return
        folder = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1] / "dist/FrapGrab"
        try:
            subprocess.Popen([str(self.update_installer), f"/DIR={folder}", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"])
        except OSError as exc:
            self._update_error(str(exc))
            return
        self.on_closing()

    def _update_progress(self,value):
        self.update_status.configure(text=f"Pobieranie · {value:.0%}")

    def _toggle_hud_advanced(self):
        if self.hud_advanced.winfo_manager():self.hud_advanced.pack_forget()
        else:self.hud_advanced.pack(fill="x",pady=(0,12))

    def _choose_auto_calibration(self):
        if self.calibrating:return
        self._save_gamertag()
        if not valid_nickname(self.config_data["gamertag"]):
            self.show_page("live");self.gamertag.focus_set()
            self.activity("Nick gracza",NICKNAME_HELP,BLUE);return
        path=filedialog.askopenfilename(title="Powtórka z Twoją eliminacją",initialdir=self.config_data["save_folder"],filetypes=[("Film MP4","*.mp4")])
        if path:self._start_auto_calibration(path)

    def _start_auto_calibration(self,path):
        if self.game_foreground:
            self.pending_calibration=path;return
        self.calibrating=True
        self.hud_status.configure(text="Rozpoznawanie HUD z powtórki…")
        nickname=self.config_data["gamertag"]
        def worker():
            from core.calibration import auto_calibrate
            from core.media import MediaCancelled
            try:
                profile=auto_calibrate(path,nickname,Path(CONFIG_DIR)/"patterns",
                    cancelled=lambda:self.closing or self.game_foreground or not self.config_data.get("killfeed_enabled",True) or self.config_data.get("gamertag")!=nickname)
                self.post(self._calibration_ready,profile)
            except MediaCancelled:
                self.post(self._calibration_stopped,path,"Kalibracja czeka na zakończenie gry.",True)
            except Exception as exc:self.post(self._calibration_stopped,path,str(exc),False)
        self.background(worker)

    def _calibration_ready(self,path):
        self.calibrating=False
        profile=json.loads(Path(path).read_text(encoding="utf-8"))
        if profile.get("gamertag") and profile["gamertag"]!=self.config_data["gamertag"]:
            self.hud_status.configure(text="Nick zmieniony. Wykryj HUD ponownie.");return
        self.config_data.update(pixel_profile=str(path),killfeed_region=profile["region"])
        try:self.hud_needs_calibration=profile["monitor_size"][1]!=output_geometry(self.config_data["capture_output"])["height"]
        except ValueError:self.hud_needs_calibration=False
        save_config(self.config_data)
        self.region_entry.delete(0,"end");self.region_entry.insert(0,", ".join(f"{v*100:g}" for v in profile["region"]))
        self.hud_status.configure(text="HUD rozpoznany · dopasowanie do rozdzielczości włączone",text_color=ACCENT)
        self.detection_status.configure(text=self._detection_description())
        self.activity("HUD rozpoznany","Detekcja graficzna jest gotowa.")

    def _calibration_stopped(self,path,message,retry):
        self.calibrating=False
        if retry and self.config_data.get("killfeed_enabled",True) and valid_nickname(self.config_data.get("gamertag","")):self.pending_calibration=path
        self.hud_status.configure(text=message,text_color=MUTED)

    def calibrate_pixel(self):
        import cv2
        from PIL import ImageTk
        try:
            region = self._parse_region()
        except Exception as exc:
            messagebox.showerror("Obszar wzorca", str(exc))
            return
        path = filedialog.askopenfilename(title="Wybierz klip z Twoją eliminacją", initialdir=self.config_data["save_folder"],
            filetypes=[("Nagrania", "*.mp4 *.mkv *.mov")])
        if not path:
            return
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 60
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps
        if not cap.isOpened() or total <= 0:
            cap.release()
            messagebox.showerror("Nagranie", "Nie można odczytać klipu.")
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(t("Wzorzec Twojej akcji · bez OCR podczas gry"))
        dialog.geometry("820x620")
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        self.label(dialog, "Zaznacz znak, który oznacza Twoją akcję.", 21, bold=True).pack(anchor="w", padx=24, pady=(20, 8))
        self.label(dialog, "Znajdź klatkę z Twoim nickiem po LEWEJ stronie killfeedu, potem przeciągnij\nprostokąt dokładnie wokół nicku. Nie zaznaczaj ofiary ani ogólnej ikony czaszki.",
            12, MUTED, justify="left").pack(anchor="w", padx=24)
        canvas = tk.Canvas(dialog, width=740, height=230, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        canvas.pack(padx=24, pady=18)
        state = {"patch":None,"scale":1,"rectangle":None,"start":None,"size":None}
        time_label = self.label(dialog, "Klatka nagrania", 12, MUTED)
        time_label.pack()
        slider = ctk.CTkSlider(dialog, from_=0,to=max(.1,total-.1),width=700, progress_color=ACCENT,button_color=ACCENT,
            command=lambda v: time_label.configure(text=f"{v:.1f} / {total:.1f} s"))
        slider.pack(pady=8)
        slider.set(max(0,total-4))
        def frame():
            cap.set(cv2.CAP_PROP_POS_MSEC,slider.get()*1000)
            ok,image = cap.read()
            if not ok:
                return
            H,W = image.shape[:2]
            x,y,w,h = region
            patch = image[int(y*H):int((y+h)*H),int(x*W):int((x+w)*W)]
            state["patch"],state["size"] = patch,(W,H)
            scale = min(740/patch.shape[1],230/patch.shape[0])
            state["scale"] = scale
            preview = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(patch,cv2.COLOR_BGR2RGB)).resize((int(patch.shape[1]*scale),int(patch.shape[0]*scale))))
            canvas.image = preview
            canvas.delete("all")
            canvas.create_image(0,0,image=preview,anchor="nw")
            state["rectangle"] = None
        self.button(dialog,"Pokaż wybraną klatkę",frame,width=210).pack(pady=8)
        def begin(event):
            if state["rectangle"]:
                canvas.delete(state["rectangle"])
            state["start"] = (event.x,event.y)
            state["rectangle"] = canvas.create_rectangle(event.x,event.y,event.x,event.y,outline=ACCENT,width=2)
        def drag(event):
            if state["start"]:
                canvas.coords(state["rectangle"],*state["start"],event.x,event.y)
        canvas.bind("<Button-1>",begin)
        canvas.bind("<B1-Motion>",drag)
        def save():
            from core.pixel_detector import save_profile
            try:
                if state["rectangle"] is None:
                    raise ValueError("Zaznacz prostokąt wokół wzorca.")
                rect = [value/state["scale"] for value in canvas.coords(state["rectangle"])]
                profile = save_profile(Path(CONFIG_DIR)/"patterns",state["patch"],rect,region,state["size"])
                self.config_data.update(pixel_profile=profile,detection_mode="pixel",killfeed_region=region)
                save_config(self.config_data)
                self.detection_option.set("Grafika · bez OCR")
                self.detection_status.configure(text=self._detection_description())
                self.activity("Zapisano wzorzec graficzny", "Detekcja podczas gry korzysta z dopasowania obrazu, bez OCR.")
                cap.release()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("Wzorzec",str(exc),parent=dialog)
        self.button(dialog,"Zapisz wzorzec i używaj detekcji graficznej",save,True,width=380).pack(pady=16)
        def close():
            cap.release()
            dialog.destroy()
        dialog.protocol("WM_DELETE_WINDOW",close)
        frame()

    def test_ocr(self):
        try:
            cfg = self.config_data.copy()
            cfg["killfeed_region"] = self._parse_region()
            cfg["capture_output"] = self.monitor_map[self.monitor_option.get()]
        except Exception as exc:
            messagebox.showerror("Obszar OCR", str(exc))
            return
        def worker():
            import cv2
            from rapidocr_onnxruntime import RapidOCR
            patch = grab_killfeed(cfg)
            results, _ = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)(patch)
            return Image.fromarray(cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)), "\n".join(str(item[1]) for item in results or [])
        self.background(worker, self._ocr_preview)

    def _ocr_preview(self, data):
        image, text = data
        dialog = ctk.CTkToplevel(self)
        dialog.title(t("Podgląd obszaru OCR"))
        dialog.geometry("740x410")
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        preview = ctk.CTkImage(image, size=(660, max(50, min(200, int(660*image.height/image.width)))))
        label = LLabel(dialog, text="", image=preview)
        label.image = preview
        label.pack(padx=20, pady=20)
        self.label(dialog, text or "Nie wykryto tekstu. Sprawdź obszar HUD-u i wróć do gry.", 13, MUTED, wraplength=650, justify="left").pack(padx=20, pady=12)

    def on_closing(self):
        if self.job_busy and not messagebox.askyesno("Zadanie trwa", "Trwa analiza lub eksport. Zamknąć aplikację i przerwać zadanie?"):
            return
        self.closing = True
        cancel_media_jobs()
        self._monitor_stop.set()
        self.thumbnail_pool.shutdown(wait=False, cancel_futures=True)
        if self.scan:
            self.scan.cancel()
        self.withdraw()
        def cleanup():
            self.live_detector.stop()
            self.replay_buffer.cleanup()
            with self.workers_lock:
                workers = list(self.workers)
            for thread in workers:
                thread.join(timeout=30)
        cleanup_thread = threading.Thread(target=cleanup, daemon=True)
        cleanup_thread.start()
        def finish():
            if cleanup_thread.is_alive():
                self.after(100, finish)
            else:
                self.destroy()
        self.after(100, finish)
