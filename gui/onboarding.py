"""First-run configuration. Screens use real settings with no bundled player profile."""
from pathlib import Path
import customtkinter as ctk
from PIL import Image
from gui.images import AppImage
from gui.palette import BG, CARD, RAISED, BORDER, TEXT, MUTED, ACCENT, ACCENT_HOVER, RED
from gui.window_style import style_window
from core.localization import LLabel,LButton,LEntry,LCheckBox,LOptionMenu,filedialog,set_language,t
from core.setup import NICKNAME_HELP, ROCKET_NICKNAME_HELP, valid_nickname, clean_nickname, complete_setup
from core.hardware import apply_hardware_profile,ENCODER_LABELS
from core.updater import CURRENT_VERSION
from core.games import GAMES, game_choices, requires_nickname, uses_hud
from core.valve_events import VALVE_GAMES
from core.banner_events import BANNER_PROFILES
from core.audio_capture import output_devices

class SetupWizard(ctk.CTkToplevel):
    def __init__(self,parent,config,hardware,monitors,on_finish,on_cancel=None):
        super().__init__(parent)
        self.config_data=config.copy();self.hardware=hardware;self.monitors=monitors
        self.on_finish=on_finish;self.on_cancel=on_cancel;self.step=0;self.pages=[];self.summary_labels={}
        self.title(t("Pierwsze uruchomienie"));self.geometry("940x720");self.minsize(880,680)
        self.configure(fg_color=BG);self.transient(parent)
        self.grid_columnconfigure(1,weight=1);self.grid_rowconfigure(1,weight=1)
        header=ctk.CTkFrame(self,fg_color="transparent");header.grid(row=0,column=0,columnspan=2,sticky="ew",padx=28,pady=(24,20))
        self.logo_image=AppImage(self,Image.open(Path(__file__).resolve().parents[1]/"assets/icon.png"),size=(46,46))
        self.label(header,"",image=self.logo_image,width=46,height=46).pack(side="left")
        icon=Path(__file__).resolve().parents[1]/"assets/icon.ico"
        self.after(250,lambda:self.iconbitmap(str(icon)) if self.winfo_exists() else None)
        self.label(header,"Pierwsze uruchomienie",22,TEXT,True).pack(side="left",padx=16)
        self.label(header,CURRENT_VERSION,11,MUTED).pack(side="right")
        rail=ctk.CTkFrame(self,fg_color="transparent",width=185);rail.grid(row=1,column=0,sticky="nsew",padx=(24,12))
        self.rail=[]
        for i,name in enumerate(("Język","Detekcja","Nagrywanie","Podsumowanie")):
            label=self.label(rail,f"0{i+1}  {name}",13,MUTED,True,anchor="w",width=170,height=44,corner_radius=8)
            label.pack(fill="x",pady=(0,8));self.rail.append(label)
        self.body=ctk.CTkFrame(self,fg_color=CARD,corner_radius=12,border_width=1,border_color=BORDER)
        self.body.grid(row=1,column=1,sticky="nsew",padx=(0,28))
        self.body.grid_columnconfigure(0,weight=1);self.body.grid_rowconfigure(0,weight=1)
        self._language_page();self._detection_page();self._recording_page();self._summary_page()
        footer=ctk.CTkFrame(self,fg_color="transparent");footer.grid(row=2,column=0,columnspan=2,sticky="ew",padx=28,pady=20)
        self.cancel_button=self.button(footer,"Nie teraz",self.cancel,width=125);self.cancel_button.pack(side="left")
        self.next_button=self.button(footer,"Dalej",self.next,primary=True,width=150);self.next_button.pack(side="right")
        self.back_button=self.button(footer,"Wstecz",lambda:self.show_step(self.step-1),width=120);self.back_button.pack(side="right",padx=10)
        self.protocol("WM_DELETE_WINDOW",self.cancel)
        self.show_step(0)
        style_window(self)
        self.after(200,self._focus)

    def _focus(self):
        if self.winfo_exists():self.lift();self.grab_set()

    def label(self,parent,text,size=13,color=TEXT,bold=False,**kwargs):
        return LLabel(parent,text=text,font=ctk.CTkFont("Segoe UI",size,weight="bold" if bold else "normal"),text_color=color,**kwargs)

    def button(self,parent,text,command,primary=False,**kwargs):
        return LButton(parent,text=text,command=command,height=40,corner_radius=8,
            fg_color=ACCENT if primary else RAISED,hover_color=ACCENT_HOVER if primary else BORDER,
            text_color=BG if primary else TEXT,font=ctk.CTkFont("Segoe UI",13,weight="bold"),**kwargs)

    def page(self,title):
        page=ctk.CTkFrame(self.body,fg_color="transparent")
        page.grid(row=0,column=0,sticky="nsew",padx=28,pady=24)
        self.label(page,title,24,TEXT,True).pack(anchor="w",pady=(0,24))
        self.pages.append(page);return page

    def choice(self,parent,label,values,current):
        self.label(parent,label,12,MUTED).pack(anchor="w",pady=(8,6))
        menu=LOptionMenu(parent,values=values,width=280,height=36,fg_color=RAISED,button_color=BORDER)
        menu.set(current);menu.pack(anchor="w");return menu

    def checkbox(self,parent,label,selected,command=None):
        box=LCheckBox(parent,text=label,fg_color=ACCENT,hover_color=ACCENT_HOVER,checkmark_color=BG,
            text_color=TEXT,font=ctk.CTkFont("Segoe UI",13),command=command)
        box.pack(anchor="w",pady=8)
        if selected:box.select()
        return box

    def _language_page(self):
        page=self.page("Język")
        self.language=self.choice(page,"Język interfejsu",["Polski","English"],"English" if self.config_data["language"]=="en" else "Polski")
        self.language.configure(command=self._language_changed)
        self.game_map=game_choices()
        self.game=self.choice(page,"Gra",list(self.game_map),GAMES[self.config_data['game_id']]['name'])
        self.game.configure(command=lambda _:self._nickname_hint())
        box=ctk.CTkFrame(page,fg_color=BG,corner_radius=10);box.pack(fill="x",pady=(32,0))
        profile=self.hardware["selected_profile"]
        self.label(box,"Karta graficzna",11,MUTED).pack(anchor="w",padx=18,pady=(16,5))
        self.label(box,profile["gpu"],17,TEXT,True,wraplength=520,justify="left").pack(anchor="w",padx=18)
        codec=ENCODER_LABELS.get(profile["codec"],profile["codec"]).split(" · ")[-1]
        self.label(box,f"{codec} · {profile['fps']} FPS",12,ACCENT if self.hardware["hardware_encoding"] else RED).pack(anchor="w",padx=18,pady=(6,16))
        self.label(page,"Ustawienia nagrywania zostaną dobrane automatycznie.",12,MUTED,wraplength=540,justify="left").pack(anchor="w",pady=14)

    def _detection_page(self):
        page=self.page("Detekcja")
        self.auto_kills=self.checkbox(page,"Automatyczne wykrywanie eliminacji i asyst",self.config_data["killfeed_enabled"],self._nickname_hint)
        self.player_settings=ctk.CTkFrame(page,fg_color="transparent");self.player_settings.pack(fill="x")
        self.nickname_label=self.label(self.player_settings,"Nick gracza *",13,TEXT,True);self.nickname_label.pack(anchor="w",pady=(18,8))
        self.nickname=LEntry(self.player_settings,placeholder_text="Nick z gry, bez tagu klanu",height=42,fg_color=BG,border_color=BORDER,font=ctk.CTkFont("Segoe UI",15))
        self.nickname.pack(fill="x");self.nickname.insert(0,self.config_data["gamertag"])
        self.nickname_help = self.label(self.player_settings,NICKNAME_HELP,12,MUTED,wraplength=535,justify="left")
        self.nickname_help.pack(anchor="w",pady=(10,8))
        self.name_error=self.label(page,"",12,RED,wraplength=535,justify="left");self.name_error.pack(anchor="w",pady=(0,8))
        self.voice=self.checkbox(page,"Reakcje z mojego mikrofonu",self.config_data["mic_enabled"])
        self._nickname_hint()

    def _recording_page(self):
        page=self.page("Nagrywanie")
        self.monitor_map={f"{m['index']+1} · {m['width']} × {m['height']}":m["index"] for m in self.monitors}
        current=next((label for label,index in self.monitor_map.items() if index==self.config_data["capture_output"]),next(iter(self.monitor_map)))
        self.monitor=self.choice(page,"Ekran",list(self.monitor_map),current)
        self.lengths={"30 s":30,"1 min":60,"2 min":120,"3 min":180,"5 min":300,"10 min":600,"15 min":900,"30 min":1800}
        if self.config_data["manual_replay_seconds"] not in self.lengths.values():
            self.lengths[f"{self.config_data['manual_replay_seconds']} s"]=self.config_data["manual_replay_seconds"]
        current=next((label for label,value in self.lengths.items() if value==self.config_data["manual_replay_seconds"]),"1 min")
        self.length=self.choice(page,"Długość ręcznej powtórki",list(self.lengths),current)
        self.label(page,"Folder nagrań",12,MUTED).pack(anchor="w",pady=(16,6))
        row=ctk.CTkFrame(page,fg_color="transparent");row.pack(fill="x")
        self.folder=LEntry(row,height=36,fg_color=BG,border_color=BORDER,font=ctk.CTkFont("Segoe UI",12))
        self.folder.pack(side="left",fill="x",expand=True,padx=(0,8));self.folder.insert(0,self.config_data["save_folder"])
        self.button(row,"Wybierz",self._folder,width=90).pack(side="right")
        self.system_audio=self.checkbox(page,"Dźwięk gry i systemu",self.config_data["desktop_audio"])
        self.microphone=self.checkbox(page,"Zapisuj mikrofon",self.config_data["record_microphone"])
        self.chat=self.checkbox(page,"Zapisuj dodatkowe źródło rozmów",self.config_data["record_chat"])
        self.chat_sources={"Automatycznie · Sonar":""}
        try:
            for name in output_devices():self.chat_sources[name]=name
        except Exception:pass
        selected_chat=self.config_data["chat_device"]
        if selected_chat:self.chat_sources[selected_chat]=selected_chat
        self.chat_source=self.choice(page,"Źródło rozmów",list(self.chat_sources),next(label for label,name in self.chat_sources.items() if name==selected_chat))
        self.record_error=self.label(page,"",12,RED,wraplength=535,justify="left")
        self.record_error.pack(anchor="w",pady=(8,0))

    def _summary_page(self):
        page=self.page("Podsumowanie")
        for key,title in (("detection","Detekcja"),("gpu","Karta graficzna"),("recording","Nagrywanie"),("folder","Folder nagrań"),("audio","Dźwięk")):
            self.label(page,title,11,MUTED).pack(anchor="w",pady=(0,3))
            label=ctk.CTkLabel(page,text="",font=ctk.CTkFont("Segoe UI",13,weight="bold"),text_color=TEXT,wraplength=530,justify="left")
            label.pack(anchor="w",pady=(0,14));self.summary_labels[key]=label
        self.calibration_note=self.label(page,"",12,ACCENT,wraplength=530,justify="left")
        self.calibration_note.pack(anchor="w",pady=(4,0))

    def _language_changed(self,choice):
        set_language("en" if choice=="English" else "pl")
        self.title(t("Pierwsze uruchomienie"))

    def _nickname_hint(self):
        if not hasattr(self,'nickname'):return
        game_id = self.game_map[self.game.get()]
        needed = requires_nickname(game_id)
        if not needed:self.player_settings.pack_forget()
        elif not self.player_settings.winfo_manager():self.player_settings.pack(fill="x",after=self.auto_kills)
        self.nickname_label.configure(text="Nick gracza *" if self.auto_kills.get() else "Nick gracza (opcjonalnie)")
        self.nickname_help.configure(text=ROCKET_NICKNAME_HELP if game_id == "rocket_league" else NICKNAME_HELP)
        self.nickname.configure(placeholder_text="Nazwa z tablicy wyników" if game_id == "rocket_league" else "Nick z gry, bez tagu klanu")
        captions = {"rocket_league": "Automatyczne wykrywanie goli, asyst i obron",
                    **dict.fromkeys(BANNER_PROFILES, "Testowa detekcja zwycięstwa · angielski HUD")}
        self.auto_kills.configure(text=captions.get(game_id, "Automatyczne wykrywanie eliminacji i asyst"))
        if hasattr(self,"name_error"):self.name_error.configure(text="")
        self.nickname.configure(border_color=BORDER)

    def _folder(self):
        path=filedialog.askdirectory(parent=self,title="Folder nagrań")
        if path:self.folder.delete(0,"end");self.folder.insert(0,path)

    def draft(self):
        duration=self.lengths[self.length.get()]
        game_id=self.game_map[self.game.get()]
        return {"language":"en" if self.language.get()=="English" else "pl","game_id":game_id,
            "gamertag":clean_nickname(self.nickname.get(), game_id) if requires_nickname(game_id) else "",
            "killfeed_enabled":bool(self.auto_kills.get()),"mic_enabled":bool(self.voice.get()),
            "capture_output":self.monitor_map[self.monitor.get()],"manual_replay_seconds":duration,
            "buffer_seconds":max(60,duration),"save_folder":self.folder.get().strip(),
            "desktop_audio":bool(self.system_audio.get()),"record_microphone":bool(self.microphone.get()),"record_chat":bool(self.chat.get()),
            "chat_device":self.chat_sources[self.chat_source.get()]}

    def show_step(self,step):
        self.step=max(0,min(3,step))
        for index,page in enumerate(self.pages):page.grid() if index==self.step else page.grid_remove()
        for index,label in enumerate(self.rail):label.configure(fg_color=RAISED if index==self.step else "transparent",text_color=ACCENT if index==self.step else MUTED)
        self.back_button.configure(state="disabled" if self.step==0 else "normal")
        self.next_button.configure(text="Zapisz" if self.step==3 else "Dalej")
        if self.step==3:self._summary()

    def _summary(self):
        data=self.draft()
        needs_hud=uses_hud(data["game_id"])
        detection = data["gamertag"] or GAMES[data["game_id"]]["name"]
        self.summary_labels["detection"].configure(text=detection if data["killfeed_enabled"] else t("Ręczny zapis F8 · nick niewymagany"))
        profile=self.hardware["selected_profile"]
        codec=ENCODER_LABELS.get(profile["codec"],profile["codec"]).split(" · ")[-1]
        self.summary_labels["gpu"].configure(text=f"{profile['gpu']} · {codec}")
        self.summary_labels["recording"].configure(text=f"{self.monitor.get()} · {self.length.get()} · {self.config_data['manual_hotkey']}")
        self.summary_labels["folder"].configure(text=data["save_folder"])
        audio=[name for key,name in (("desktop_audio","Gra"),("record_microphone","Mikrofon"),("record_chat","Dodatkowe rozmowy")) if data[key]]
        self.summary_labels["audio"].configure(text=" · ".join(t(name) for name in audio) or t("Bez dźwięku"))
        if not data["killfeed_enabled"]:
            note = "Gotowe do ręcznego zapisu."
        elif data["game_id"] == "rocket_league" or data["game_id"] in VALVE_GAMES:
            note = "Otwórz zakładkę gry i wybierz Włącz dane meczu."
        elif not needs_hud:
            note = ""
        elif self.config_data.get("pixel_profile"):
            note = "Profil HUD jest już zapisany."
        else:
            note = "Po pierwszej eliminacji zapisz powtórkę klawiszem F8. Po powrocie do aplikacji HUD zostanie rozpoznany automatycznie."
        self.calibration_note.configure(text=note)

    def next(self):
        if self.step==1:
            game_id = self.game_map[self.game.get()]
            if requires_nickname(game_id) and (self.auto_kills.get() or self.nickname.get().strip()) and not valid_nickname(self.nickname.get(), game_id):
                self.name_error.configure(text=ROCKET_NICKNAME_HELP if game_id == "rocket_league" else
                                          "Wpisz swój nick z gry (minimum 3 znaki) albo wyłącz automatyczną detekcję.")
                self.nickname.configure(border_color=RED);self.nickname.focus_set();return
            self.nickname.configure(border_color=BORDER);self.name_error.configure(text="")
        if self.step==2:
            if not self.folder.get().strip():self.record_error.configure(text="Wybierz folder nagrań.");return
            self.record_error.configure(text="")
        if self.step<3:self.show_step(self.step+1);return
        try:
            config=complete_setup(self.config_data,self.draft())
            monitor=next(m for m in self.monitors if m["index"]==config["capture_output"])
            config=apply_hardware_profile(config,self.hardware,monitor["height"])
            self.on_finish(config)
        except (ValueError,OSError) as exc:
            self.show_step(2)
            self.record_error.configure(text=str(exc));return
        self.grab_release();self.destroy()

    def cancel(self):
        set_language(self.config_data["language"])
        if self.on_cancel:self.on_cancel()
        self.grab_release();self.destroy()
