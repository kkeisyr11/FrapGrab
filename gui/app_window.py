"""Frap Grab desktop workspace. All Tk operations stay on the main thread."""
import json
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
from PIL import Image, ImageOps, ImageTk

from core.config import load_config, save_config, CONFIG_DIR
from core.hardware import detect_hardware_profile,apply_hardware_profile
from core.live_detector import LiveDetector, game_status, grab_killfeed
from core.replay_buffer import ReplayBuffer
from core.editor import VideoEditor,plan_montage
from core.renderer import ClipRenderer
from core.scanner import MatchScanner
from core.media import probe, cancel_media_jobs
from core.monitors import outputs,output_geometry
from core.updater import CURRENT_VERSION,AutoUpdater,repository_name
from core.setup import NICKNAME_HELP,valid_nickname,clean_nickname
from core.games import GAMES,game_choices,requires_nickname,select_game
from core.buffer_display import buffer_display
from gui.images import AppImage
from gui.window_style import style_window

BG = "#101316"
SIDE = "#15191D"
CARD = "#1B2025"
RAISED = "#232A30"
BORDER = "#30383F"
TEXT = "#F1F2ED"
MUTED = "#9CA7AE"
ACCENT = "#D4F78A"
ACCENT_HOVER = "#BBDF72"
RED = "#F5968B"
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
        self.library_page_size = 10
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
        self.plan_selection = None
        self.pending_auto = None
        self.manual_pending = False
        self.exports_active = 0
        self.capture_operation = False
        self.session_clips = 0
        self.session_actions = 0
        self.activity_count = 0
        self._failed_capture = False
        self._last_auto = 0
        self._monitor_stop = threading.Event()
        self.replay_buffer = ReplayBuffer(self._clip_saved, lambda state, msg: self.post(self._capture_status, state, msg),
            lambda level,source:self.live_detector.process_volume(level,source))
        self.live_detector = LiveDetector(lambda *args: self.post(self._trigger, *args),
            lambda volume: self.post(self._volume, volume), lambda msg: self.post(self.activity, "Wykrywanie", msg, RED))
        self._build_layout()
        style_window(self)
        self.setup_wizard=None
        self._nickname_hint()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(60, self._drain)
        self.after(500, self._tick)
        if not preview:
            threading.Thread(target=self._monitor, daemon=True).start()
            if not self.config_data.get("setup_completed"):
                self.after(700,self.open_setup)
            elif self.config_data.get("auto_record_enabled"):
                self.after(1000, self.toggle_recording)
            if self.config_data.get("auto_update_check") and self.config_data.get("github_repository") and time.time()-self.config_data.get("last_update_check",0)>86400:
                self.after(5000,lambda:self._check_updates(True))
        self.activity("Gotowe do gry", "Włącz czuwanie. F8 zapisze powtórkę podczas rozgrywki.")

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
        self.sidebar = ctk.CTkFrame(self, width=202, corner_radius=0, fg_color=SIDE)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(8, weight=1)
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=22, pady=(32, 6), sticky="ew")
        self.logo_image=AppImage(self,Image.open(Path(__file__).resolve().parents[1]/"assets/icon.png"),size=(50,50))
        self.label(brand,"",image=self.logo_image,width=50,height=50).pack(side="left")
        self.nav = {}
        for row, (key, title) in enumerate([("live", "Pulpit"), ("library", "Biblioteka klipów"),
                ("studio", "Stwórz film"), ("scanner", "Analiza nagrania"), ("settings", "Ustawienia")], 2):
            btn = LButton(self.sidebar, text=title, font=font(13), height=44, anchor="w", corner_radius=8,
                fg_color="transparent", text_color=MUTED, hover_color=RAISED, command=lambda k=key: self.show_page(k))
            btn.grid(row=row, column=0, sticky="ew", padx=12, pady=3)
            self.nav[key] = btn
        footer = self.card(self.sidebar)
        footer.grid(row=9, column=0, sticky="ew", padx=14, pady=20)
        self.label(footer, "LOKALNIE NA TWOIM PC", 9, ACCENT, True).pack(anchor="w", padx=12, pady=(12, 2))
        gpu = (self.hardware["gpus"] or ["GPU nierozpoznane"])[0].replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "")
        self.label(footer, gpu, 11, MUTED, wraplength=150, justify="left").pack(anchor="w", padx=12, pady=(0, 12))
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
        self.page_subtitle = self.label(headings, "", 12, MUTED)
        self.state_badge = self.label(top, "●  WSTRZYMANE", 11, MUTED, True, fg_color=CARD, corner_radius=8, padx=14, pady=8)
        self.state_badge.grid(row=0, column=1, padx=14)
        self.arm_button = self.button(top, "Włącz czuwanie", self.toggle_recording, True, width=152)
        self.arm_button.grid(row=0, column=2)
        self.workspace = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.workspace.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 20))
        self.workspace.grid_columnconfigure(0, weight=1)
        self.workspace.grid_rowconfigure(0, weight=1)
        self.pages = {}
        self._build_live()
        self._build_library()
        self._build_studio()
        self._build_scanner()
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
            btn.configure(fg_color=RAISED if page_key == key else "transparent", text_color=ACCENT if page_key == key else MUTED)
        titles={"live":"Pulpit","library":"Biblioteka","studio":"Montaż","scanner":"Analiza","settings":"Ustawienia"}
        self.page_title.configure(text=titles[key])
        if key == "library":
            self.update_idletasks()
            self.refresh_library()
        if key == "studio":
            self._refresh_selection()

    def scroll_page(self, key):
        page = ctk.CTkScrollableFrame(self.workspace, fg_color="transparent", scrollbar_button_color=BORDER)
        self.pages[key] = page
        return page

    def _build_live(self):
        page = self.scroll_page("live")
        game_bar=self.card(page)
        game_bar.pack(fill="x",pady=(0,16))
        self.label(game_bar,"Gra",14,TEXT,True).pack(side="left",padx=24,pady=16)
        self.game_map=game_choices()
        self.game_option=LOptionMenu(game_bar,values=list(self.game_map),width=250,height=38,
            fg_color=RAISED,button_color=BORDER,font=font(14),command=self._select_game)
        self.game_option.set(GAMES[self.config_data['game_id']]['name'])
        self.game_option.pack(side="left",padx=(12,24),pady=16)
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
        self.ring = tk.Canvas(right, width=188, height=174, bg=CARD, highlightthickness=0)
        self.ring.pack()
        self.ring.create_oval(20, 10, 168, 158, outline=BORDER, width=7)
        self.ring_arc = self.ring.create_arc(20, 10, 168, 158, start=90, extent=0, outline=ACCENT, width=7, style="arc",state="hidden")
        self.ring_full = self.ring.create_oval(20, 10, 168, 158, outline=ACCENT, width=7,state="hidden")
        self.ring_number = self.ring.create_text(94, 76, text="0 s", fill=TEXT, font=("Segoe UI", 32, "bold"))
        self.ring_caption=self.ring.create_text(94, 110, text=t("W BUFORZE"), fill=MUTED, font=("Segoe UI", 9))
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
        split = ctk.CTkFrame(page, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.grid_columnconfigure((0, 1), weight=1, uniform="lower")
        detection = self.card(split)
        detection.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.game_settings_title=self.label(detection,GAMES[self.config_data['game_id']]['name'],16,bold=True)
        self.game_settings_title.pack(anchor="w",padx=20,pady=(18,2))
        self.kf_switch = self._switch(detection, "Automatyczny zapis akcji", "killfeed_enabled")
        self.detection_status = self.label(detection, self._detection_description(), 11, ACCENT, wraplength=350, justify="left")
        self.detection_status.pack(anchor="w", padx=20, pady=(2, 8))
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
        self.button(detection, "Skalibruj detekcję graficzną", lambda: self.show_page("settings"), width=230, height=30).pack(anchor="w", padx=20, pady=(0, 10))
        self.mic_switch = self._switch(detection, "Głośna reakcja · mikrofon i rozmowy", "mic_enabled", refresh=True)
        self.label(detection, "Reakcje zachowują więcej czasu po zdarzeniu.\nZapis własnego głosu i Sonar Chat: w ustawieniach.", 11, MUTED,justify="left").pack(anchor="w", padx=20, pady=(3, 8))
        self.vu = ctk.CTkProgressBar(detection, height=5, progress_color=ACCENT, fg_color=BORDER)
        self.vu.pack(fill="x", padx=20, pady=(0, 10))
        self.vu.set(0)
        threshold = ctk.CTkFrame(detection, fg_color="transparent")
        threshold.pack(fill="x", padx=20, pady=(0, 16))
        self.label(threshold, "Próg reakcji", 11, MUTED).pack(side="left")
        self.threshold_label = self.label(threshold, f"{self.config_data['mic_threshold']}%", 11)
        self.threshold_label.pack(side="right")
        slider = ctk.CTkSlider(threshold, from_=5, to=95, width=130, progress_color=ACCENT, button_color=ACCENT,
            command=self._threshold)
        slider.pack(side="left", fill="x", expand=True, padx=12)
        slider.set(self.config_data["mic_threshold"])
        activity = self.card(split)
        activity.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        row = ctk.CTkFrame(activity, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(18, 12))
        self.label(row, "Ostatnia aktywność", 16, bold=True).pack(side="left")
        self.activity_list = ctk.CTkScrollableFrame(activity, height=255, fg_color="transparent")
        self.activity_list.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        foot = ctk.CTkFrame(page, fg_color="transparent")
        foot.pack(fill="x", pady=(18, 0))
        self.label(foot, "Przechwytywanie całego wybranego ekranu · pliki pozostają na komputerze", 11, MUTED).pack(side="left")
        self.button(foot, "Otwórz folder", self.open_folder, width=126, height=30).pack(side="right")

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
        if requires_nickname(self.config_data.get('game_id','wardogs')) and not valid_nickname(self.config_data.get("gamertag","")):return "Podaj nick do automatycznej detekcji"
        if self.config_data.get("detection_mode") == "ocr":
            return "Tryb OCR · rozpoznawanie nicku w tle"
        return "Tryb graficzny · bez OCR" + (" · skalibrowany" if self.config_data.get("pixel_profile") else "\nWymagana jednorazowa kalibracja wzorca")

    def _preference(self, key, value, refresh=False):
        self.config_data[key] = value
        save_config(self.config_data)
        if key in ("gamertag","killfeed_enabled") and hasattr(self,"nickname_help"):self._nickname_hint()
        if key=="killfeed_enabled" and not value:self.pending_calibration=None
        if refresh and self.armed:
            self.background(self.live_detector.refresh_settings)

    def _save_gamertag(self, event=None):
        nickname=clean_nickname(self.gamertag.get())
        if nickname!=self.config_data["gamertag"] and self.config_data.get("auto_hud",True):self.config_data["pixel_profile"]=""
        self._preference("gamertag",nickname)

    def _nickname_hint(self):
        automatic=self.config_data.get("killfeed_enabled",True)
        needed=requires_nickname(self.config_data.get('game_id','wardogs'))
        if not needed:self.player_settings.pack_forget()
        elif not self.player_settings.winfo_manager():self.player_settings.pack(fill="x",after=self.detection_status)
        self.nickname_label.configure(text="Nick gracza *" if automatic else "Nick gracza (opcjonalnie)")
        self.nickname_help.configure(text=NICKNAME_HELP,text_color=BLUE if automatic and not valid_nickname(self.config_data.get("gamertag","")) else MUTED)
        self.detection_status.configure(text=self._detection_description(),text_color=BLUE if needed and automatic and not valid_nickname(self.config_data.get("gamertag","")) else ACCENT)

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
        self.pending_calibration=None
        self.hud_needs_calibration=not bool(config['pixel_profile'])
        self.game_settings_title.configure(text=GAMES[game_id]['name'])
        self.gamertag.delete(0,'end');self.gamertag.insert(0,config['gamertag'])
        for switch,key in ((self.kf_switch,'killfeed_enabled'),(self.mic_switch,'mic_enabled'),(self.hud_auto_switch,'auto_hud')):
            switch.select() if config[key] else switch.deselect()
        self.region_entry.delete(0,'end')
        self.region_entry.insert(0,', '.join(f'{v*100:g}' for v in config['killfeed_region']))
        self.detection_option.set('OCR · analiza tekstu' if config['detection_mode']=='ocr' else 'Grafika · bez OCR')
        self._nickname_hint()

    def _threshold(self, value):
        self.threshold_label.configure(text=f"{int(value)}%")
        self._preference("mic_threshold", int(value))

    def _volume(self, value):
        self.vu.set(value / 100)

    def activity(self, title, detail, color=ACCENT):
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
        self.armed = not self.armed
        self._failed_capture = False
        self.arm_button.configure(text="Zatrzymaj" if self.armed else "Włącz czuwanie", fg_color=RAISED if self.armed else ACCENT,
            hover_color=BORDER if self.armed else ACCENT_HOVER, text_color=TEXT if self.armed else BG)
        if self.armed:
            save_config(self.config_data)
            self.background(self.live_detector.start)
            self.activity("Czuwanie włączone", "Nagrywanie wystartuje po przejściu do gry." if self.config_data["record_only_in_game"] else "Nagrywanie wybranego ekranu.")
        else:
            if self.pending_auto:
                self._export_request(self.pending_auto)
                self.pending_auto = None
            self.background(self.live_detector.stop)
            self.activity("Sesja wstrzymana", "Twoje zapisane klipy są w bibliotece.")

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
            state, color = "●  BŁĄD NAGRYWANIA", RED
        elif buffer.state == "recording" and buffer.is_recording:
            state, color = "●  NAGRYWANIE", ACCENT
        elif buffer.state == "starting" and buffer.is_recording:
            state, color = "●  STARTOWANIE", BLUE
        elif self.armed:
            state, color = "●  CZEKAM NA GRĘ", BLUE
        else:
            state, color = "●  WSTRZYMANE", MUTED
        self.state_badge.configure(text=state, text_color=color)
        self.save_button.configure(state="normal" if seconds > 0 and not self.manual_pending else "disabled")
        if self.pending_auto and time.monotonic() >= self.pending_auto["end"]:
            request = self.pending_auto
            self.pending_auto = None
            self._export_request(request)
        self.after(500, self._tick)

    def _update_buffer_display(self,seconds,capacity):
        text,fraction,full=buffer_display(seconds,capacity)
        self.ring.itemconfigure(self.ring_number,text=text)
        # Tk on Windows can draw a visible arc even for a sub-pixel extent.
        # Hide empty arcs and use a true oval at capacity, without a 359.9° seam.
        self.ring.itemconfigure(self.ring_arc,extent=-360*fraction,
            state="normal" if 0<fraction<1 else "hidden")
        self.ring.itemconfigure(self.ring_full,state="normal" if full else "hidden")

    def _capture_task(self, fn):
        self.capture_operation = True
        def task():
            try:
                fn()
            finally:
                self.post(setattr, self, "capture_operation", False)
        self.background(task)

    def _capture_status(self, state, msg):
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
        with self.replay_buffer.lock:self.replay_buffer.config["buffer_seconds"]=self.config_data["buffer_seconds"]
        self.buffer_caption.configure(text=f"do {self.config_data['buffer_seconds']} sekund wstecz")
        if hasattr(self,"buffer_option"):self.buffer_option.set(str(self.config_data["buffer_seconds"]))
        self.activity("Długość powtórki",f"{duration} s · dostępne teraz: {int(self.replay_buffer.available_seconds)} s")

    def _trigger(self, event_type, reason, extra):
        if not self.armed or self.manual_pending and event_type == "manual":
            return
        if event_type != "manual" and not self.game_foreground:
            return
        if self.replay_buffer.available_seconds < 1:
            self.activity("Bufor się napełnia", "Powtórkę zapiszesz, gdy pojawią się pierwsze sekundy nagrania.", BLUE)
            return
        now = time.monotonic()
        if event_type == "manual":
            self.manual_pending = True
            self._export_request({"start": now-self.config_data["manual_replay_seconds"], "end": now,
                "reason": "manual", "details": extra, "events": []})
        else:
            self.session_actions += 1
            self.metric_labels["actions"].configure(text=f"{self.session_actions} zdarzeń")
            before, after = self.config_data["clip_before_kill"], self.config_data["clip_after_kill"]
            if event_type=="mic":before,after=max(20,before),max(15,after)
            if self.pending_auto and now-self.pending_auto["start"] < 55:
                self.pending_auto["end"] = max(self.pending_auto["end"],now + after)
                self.pending_auto["events"].append(now)
                self.pending_auto["event_types"].append(event_type)
            else:
                if self.pending_auto:
                    self._export_request(self.pending_auto)
                self.pending_auto = {"start": now-before, "end": now+after,
                    "reason": event_type, "details": extra, "events": [now],"event_types":[event_type]}
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
        if self.config_data.get("auto_hud",True) and self.config_data.get("killfeed_enabled",True) and valid_nickname(self.config_data.get("gamertag","")) and (not self.config_data.get("pixel_profile") or self.hud_needs_calibration):self.pending_calibration=path
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
            if not message.startswith("Anulowano"):
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
        self.button(tools, "Stwórz film z zaznaczonych →", lambda: self.show_page("studio"), True, width=236).pack(side="right")
        self.button(tools, "Odśwież", self.refresh_library, width=90).pack(side="right", padx=10)
        self.library_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self.library_scroll.grid(row=1, column=0, sticky="nsew")
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
            container = ctk.CTkFrame(self.library_scroll,fg_color="transparent")
            slot["container"] = container
            header = ctk.CTkFrame(container,fg_color="transparent")
            slot["header"] = header
            slot["date"] = self.label(header,"",16,bold=True)
            slot["date"].pack(side="left")
            self.button(header,"Zaznacz dzień",lambda s=slot:self.select_day(s["day"]),width=128,height=28).pack(side="right")
            row = self.card(container)
            row.pack(fill="x",pady=(0,8))
            slot["row"] = row
            checkbox = LCheckBox(row,text="",width=24,checkbox_width=20,checkbox_height=20,
                fg_color=ACCENT,hover_color=ACCENT_HOVER,checkmark_color=BG,command=lambda s=slot:self.select_clip(s["path"]))
            checkbox.pack(side="left",padx=(16,12))
            slot["checkbox"] = checkbox
            slot["thumb"] = self.label(row,"MP4",12,MUTED,width=120,height=68,fg_color=BG,corner_radius=6)
            slot["thumb"].pack(side="left",pady=12,padx=(0,14))
            content = ctk.CTkFrame(row,fg_color="transparent")
            content.pack(side="left",fill="x",expand=True)
            slot["name"] = self.label(content,"",12,bold=True,anchor="w")
            slot["name"].pack(fill="x")
            slot["info"] = self.label(content,"",11,MUTED,anchor="w")
            slot["info"].pack(fill="x",pady=(4,0))
            self.button(row,"Odtwórz",lambda s=slot:os.startfile(str(s["path"])),width=88,height=32).pack(side="right",padx=(8,14))
            self.button(row,"Edytuj",lambda s=slot:self.edit_clip(s["path"]),width=72,height=32).pack(side="right")
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
        self.library_import = self.button(self.library_scroll,"Importuj klipy",self.import_clips)

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
        self.library_navigation.pack_forget()
        self.library_import.pack_forget()
        self.library_empty.pack_forget()
        self.library_checkboxes = {}
        self.library_thumbnail_paths = {}
        self.thumbnail_images.clear()
        size = sum(p.stat().st_size for p in self.files)/(1024**3)
        self.library_count.configure(text=f"{len(self.files)} klipów  /  {size:.2f} GB  /  zaznaczono {len(self.selected)}")
        max_page = max(0,(len(visible)-1)//self.library_page_size)
        self.library_page = min(self.library_page,max_page)
        offset = self.library_page*self.library_page_size
        page_files = visible[offset:offset+self.library_page_size]
        day = None
        for i,slot in enumerate(self.library_slots):
            if i >= len(page_files):
                slot["container"].pack_forget()
                continue
            path = page_files[i]
            slot["path"] = path
            slot["container"].pack(fill="x")
            this_day = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y")
            slot["day"] = this_day
            if this_day != day:
                day = this_day
                slot["date"].configure(text=day)
                slot["header"].pack(fill="x",pady=(18,10),before=slot["row"])
            else:
                slot["header"].pack_forget()
            checkbox = slot["checkbox"]
            checkbox.select() if path in self.selected else checkbox.deselect()
            self.library_checkboxes[path] = checkbox
            slot["name"].configure(text=path.stem if len(path.stem)<47 else path.stem[:44]+"…")
            stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M")
            slot["info"].configure(text=f"{stamp}   ·   {path.stat().st_size/(1024**2):.1f} MB")
            thumb = slot["thumb"]
            thumb.configure(image=None,text="MP4")
            self.library_thumbnail_paths[thumb] = path
            future = self.thumbnail_pool.submit(self._thumbnail,path)
            future.add_done_callback(lambda f,p=path,w=thumb:self.post(self._set_thumbnail,p,w,f.result()) if not f.cancelled() and f.exception() is None else None)
        if not self.files:
            self.library_empty.pack(fill="x",pady=20)
        if max_page:
            self.previous_page.configure(state="normal" if self.library_page else "disabled")
            self.next_page.configure(state="normal" if self.library_page<max_page else "disabled")
            self.page_number.configure(text=f"Strona {self.library_page+1} / {max_page+1}")
            self.library_navigation.pack(fill="x",pady=12)
        self.library_import.pack(anchor="w",pady=16)

    def _library_page(self,delta):
        self.library_page = max(0,self.library_page+delta)
        self.refresh_library()
        self.library_scroll._parent_canvas.yview_moveto(0)

    @staticmethod
    def _thumbnail(path):
        import cv2
        cap = cv2.VideoCapture(str(path))
        try:
            count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(count*.55)))
            ok, frame = cap.read()
            if ok:
                return ImageOps.fit(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), (240, 136))
        finally:
            cap.release()

    def _set_thumbnail(self, path, widget, image):
        if image is not None and widget.winfo_exists() and self.library_thumbnail_paths.get(widget) == path:
            thumb = AppImage(self,image,size=(120,68))
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
        for text,var in (("Eliminacje",self.include_kills),("Asysty",self.include_assists),("Reakcje i rozmowy",self.include_voice)):
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

    def _option(self, parent, text, values, current=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=6)
        self.label(row, text, 12, MUTED).pack(side="left")
        menu = LOptionMenu(row, values=values, width=250, height=34, fg_color=RAISED,
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
            (f" · usunięto {removed:.1f} s powtórek" if removed>.1 else ""))
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
        removed=report.get("deduplication",{}).get("removed_seconds",0)
        details=f"Zapisano film · {duration}:\n{path}"
        if removed>.1:details+=f"\n\nUsunięto {removed:.1f} s powtórzonego materiału."
        if issues:
            details+="\n\nNie rozpoznano akcji w:\n"+"\n".join(Path(item["source"]).name+": "+item["reason"] for item in issues)
        if tails:
            details+="\n\nNagranie źródłowe kończy się tuż po akcji. Zachowano jego końcówkę, ale dalszy ciąg nie jest zapisany:\n"+"\n".join(Path(item).name for item in tails)
        if issues or tails:
            self.job_status.configure(text="Skrót zapisany · sprawdź informacje o źródłach",text_color=BLUE)
            messagebox.showwarning("Film zapisany — informacje o źródłach",details)
        else:messagebox.showinfo("Film gotowy",details)
        if self.active_page == "library":
            self.refresh_library()

    def _build_scanner(self):
        page = self.scroll_page("scanner")
        panel = self.card(page)
        panel.pack(fill="x")
        self.label(panel, "Znajdź swoje eliminacje w całym meczu", 20, bold=True).pack(anchor="w", padx=24, pady=(22, 8))
        self.label(panel, "Skaner czyta killfeed. Ustaw poprawny nick i obszar OCR w ustawieniach.", 12, MUTED).pack(anchor="w", padx=24)
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
            messagebox.showinfo("Przygotuj analizę", "Wybierz plik i wpisz swój nick na pulpicie nagrywania (minimum 3 znaki).")
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
                Path(str(out)+".json").write_text(json.dumps({"event_offsets": [offset], "reason": event["type"]}), encoding="utf-8")
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
        self.record_chat_switch=self._switch(recording,"Zapisuj rozmowy SteelSeries Sonar Chat","record_chat")
        self.game_switch = self._switch(recording, "Nagrywaj tylko gdy okno War Dogs jest aktywne", "record_only_in_game")
        self.start_switch = self._switch(recording, "Włącz czuwanie po uruchomieniu aplikacji", "auto_record_enabled")
        self.label(recording, "Audio pochodzi z domyślnego wyjścia Windows, także z innych aplikacji.\nObraz obejmuje cały ekran. Alt+Tab w trybie gry wstrzymuje nagrywanie.",
            12, MUTED, justify="left").pack(anchor="w", padx=24, pady=(8, 18))
        timing = self.card(page)
        timing.pack(fill="x", pady=(0, 16))
        self.label(timing, "Zapis momentów", 19, bold=True).pack(anchor="w", padx=24, pady=(20, 12))
        self.before_option = self._option(timing, "Sekundy przed akcją", ["5", "10", "15", "20", "30", "45", "60"], str(self.config_data["clip_before_kill"]))
        self.after_option = self._option(timing, "Sekundy po akcji", ["2", "3", "5", "8", "10", "15"], str(self.config_data["clip_after_kill"]))
        self.hotkey_entry = self._entry(timing, "Skrót zapisu", self.config_data["manual_hotkey"])
        self.folder_entry = self._entry(timing, "Folder klipów", self.config_data["save_folder"])
        self.button(timing, "Wybierz folder", self._choose_folder, width=150).pack(anchor="w", padx=24, pady=(8, 12))
        self.alert_switch = self._switch(timing, "Potwierdzenie dźwiękowe po zapisaniu klipu", "sound_alert")
        self.label(timing, "Kolejne akcje w jednej walce łączą się w jeden klip.\nPoczątek powtórki może zawierać do 2 dodatkowych sekund kontekstu.",
            12, MUTED, justify="left").pack(anchor="w", padx=24, pady=(8, 20))
        calibration = self.card(page)
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
        update=self.card(page);update.pack(fill="x",pady=(0,16))
        self.label(update,"Aktualizacje",19,bold=True).pack(anchor="w",padx=24,pady=(20,10))
        self.github_entry=self._entry(update,"GitHub",self.config_data.get("github_repository",""))
        self.github_entry.configure(placeholder_text="owner/repository")
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
        self.game_settings_title.configure(text=GAMES[config['game_id']]['name'])
        self.setup_wizard=None
        self.pending_calibration=None
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
        self.ring.itemconfigure(self.ring_caption,text=t("W BUFORZE"))
        self.replay_length.set(next((label for label,value in self.replay_lengths.items() if value==config["manual_replay_seconds"]),f"{config['manual_replay_seconds']} s"))
        self.buffer_option.set(str(config["buffer_seconds"]))
        self.buffer_caption.configure(text=f"do {config['buffer_seconds']} sekund wstecz")
        self.monitor_option.set(next(label for label,index in self.monitor_map.items() if index==config["capture_output"]))
        self._gpu_auto_changed()
        self.detection_option.set("Grafika · bez OCR")
        self.metric_labels["format"].configure(text=f"{config['capture_fps']} FPS · MP4")
        self._nickname_hint()
        self.hud_status.configure(text="Profil aktywny" if config.get("pixel_profile") else "Zapisz powtórkę z eliminacją. HUD zostanie rozpoznany po wyjściu z gry." if config["killfeed_enabled"] else "Ręczny zapis F8")
        self.show_page("live")
        self.activity("Konfiguracja zapisana","Włącz czuwanie, aby rozpocząć nagrywanie.")

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
        self.ring.itemconfigure(self.ring_caption,text=t("W BUFORZE"))

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
            region = self._parse_region()
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
                "capture_output": self.monitor_map[self.monitor_option.get()], "clip_before_kill": int(self.before_option.get()),
                "clip_after_kill": int(self.after_option.get()), "manual_hotkey": hotkey,
                "save_folder": str(folder.resolve()), "killfeed_region": region}
            cfg["detection_mode"] = "ocr" if self.detection_option.get().startswith("OCR") else "pixel"
            repo=self.github_entry.get().strip()
            cfg["github_repository"]=repository_name(repo) if repo else ""
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

    def _check_updates(self,silent=False):
        if self.update_busy:return
        repo=self.github_entry.get().strip()
        if not repo:
            if not silent:self.update_status.configure(text="Najpierw wpisz repozytorium GitHub.")
            return
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
        if info["has_update"]:self.activity("Dostępna aktualizacja",info["version"])

    def _download_update(self):
        if self.update_busy or not self.update_info:return
        if self.update_installer:
            if self.armed or self.job_busy or self.exports_active:
                self.update_status.configure(text="Zatrzymaj nagrywanie i poczekaj na zakończenie eksportu.");return
            folder=Path(sys.executable).parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parents[1]/"dist/FrapGrab"
            subprocess.Popen([str(self.update_installer),f"/DIR={folder}","/CLOSEAPPLICATIONS","/RESTARTAPPLICATIONS"])
            self.on_closing();return
        info=dict(self.update_info);updater=AutoUpdater(self.config_data["github_repository"])
        self.update_busy=True
        self.download_update_button.configure(state="disabled")
        self.check_update_button.configure(state="disabled")
        def worker():
            try:
                path=updater.download(info,lambda value:self.post(self._update_progress,value),lambda:self.closing)
                self.post(self._update_downloaded,path,updater.repository)
            except Exception as exc:self.post(self._update_error,str(exc))
        self.background(worker)

    def _update_downloaded(self,path,repository=None):
        if repository and repository!=self.config_data["github_repository"]:
            self.update_info=None;self._update_error("Repozytorium zmienione. Sprawdź aktualizacje ponownie.");return
        self.update_busy=False;self.update_installer=Path(path)
        self.check_update_button.configure(state="normal")
        self.download_update_button.configure(state="normal",text="Zainstaluj aktualizację")
        self.update_status.configure(text="Instalator pobrany · SHA-256 potwierdzone",text_color=ACCENT)

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
