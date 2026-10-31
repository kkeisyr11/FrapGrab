# Translations module for Frap Grab

TRANSLATIONS = {
    "pl": {
        # Header
        "title": "⚡ AUTOCLIP WAR DOGS PRO",
        "gpu_prefix": "🚀 GPU:",
        "game_active": "● War Dogs: AKTYWNE (W grze)",
        "game_inactive": "○ War Dogs: Nieuruchomione",
        "lang_name": "🇵🇱 Polski",
        
        # Tabs
        "tab_live": "🔴 NA ŻYWO (Live Rec)",
        "tab_gallery": "📼 GALERIA & PODGLĄD",
        "tab_studio": "🎬 STUDIO MONTAŻU",
        "tab_scanner": "🔍 SKANER MECZÓW",
        "tab_settings": "⚙️ USTAWIENIA",
        
        # Master Power Switch
        "master_btn_on": "⚡ AUTOCLIP: WŁĄCZONY",
        "master_btn_off": "⏸️ AUTOCLIP: WYŁĄCZONY",
        "master_sidebar_title": "⚡ GŁÓWNY WŁĄCZNIK",
        "master_sidebar_switch": "Nagrywanie aktywne",
        "master_live_switch": "⚡ Główny włącznik nagrywania (WŁĄCZ / WYŁĄCZ)",
        "master_btn_stop": "WYŁĄCZ SILNIK",
        "master_btn_start": "WŁĄCZ SILNIK",
        "master_banner_on": "🟢 Silnik aktywny: automatycznie zapisuje kille, zgony, ratunki i emocje na mikrofonie.",
        "master_banner_off": "⏸️ Silnik WYŁĄCZONY: nasłuchiwanie i nagrywanie są wstrzymane (0% zasobów).",
        
        # Tab 1: Live
        "btn_manual_clip": "🎬 ZAPISZ OSTATNIĄ MINUTĘ TERAZ [ Klawisz {key} ]",
        "switch_live_engine": "Włącz Samodzielnego Asystenta (Nasłuch mikrofonu, detektora zdarzeń i klawisza)",
        "mic_title": "🎙️ Wykrywacz emocji i krzyku na mikrofonie (Hype Detector)",
        "mic_threshold_label": "Próg czułości mikrofonu:",
        "switch_kf": "Wykrywaj Kille, Powalenia i Zgony (Pixel Probe • 0% Lag)",
        "gamertag_label": "Twój Gamertag w grze:",
        "gamertag_placeholder": "Wpisz swój nick z War Dogs...",
        "log_title": "📜 Dziennik zarejestrowanych akcji:",
        "btn_open_folder": "📁 Otwórz folder klipów",
        "status_running": "🟢 Asystent na żywo został URUCHOMIONY.",
        "status_stopped": "⚪ Asystent na żywo został ZATRZYMANY.",
        "log_action_detected": "💥 [{time}] WYKRYTO AKCJĘ: {reason} ({extra})",
        "log_clip_saved": "✅ ZAPISANO PLIK KLIPU: {filename}",
        
        # Tab 2: Gallery
        "btn_refresh": "🔄 Odśwież listę",
        "btn_open_explorer": "📁 W Eksploratorze",
        "clips_found": "Znaleziono: {count} klipów ({size:.1f} MB)",
        "no_clips": "Brak zapisanych klipów w folderze.\n\nZagraj w War Dogs i wciśnij F8 lub krzyknij do mikrofonu!",
        "preview_title": "📺 PODGLĄD I AKCJE",
        "no_preview_selected": "Wybierz klip z listy po lewej stronie\naby zobaczyć podgląd i opcje",
        "btn_play": "▶ ODTWÓRZ KLIP WIDEO",
        "btn_convert_shorts": "✂ Konwertuj do Shorts (9:16 TikTok)",
        "btn_trim_clip": "✂ Przytnij ten klip...",
        "btn_delete": "🗑 Usuń ten klip",
        "delete_confirm": "Czy na pewno chcesz usunąć klip:\n{filename}?",
        
        # Badges
        "badge_kill": "💀 KILL",
        "badge_headshot": "🎯 HEADSHOT",
        "badge_death": "⚰️ ZGON",
        "badge_revive": "💉 RATUNEK",
        "badge_mic": "🎙️ MIKROFON",
        "badge_manual": "🎬 POWTÓRKA F8",
        "badge_montage": "⭐ MONTAŻ",
        
        # Trim Dialog
        "trim_title": "✂ Przytnij klip wideo",
        "trim_start": "Początek cięcia (s):",
        "trim_duration": "Czas trwania fragmentu (s):",
        "trim_btn_confirm": "Zapisz przycięty klip",
        "trim_success": "Pomyślnie przycięto i utworzono nowy klip:\n{filename}",
        
        # Tab 3: Studio
        "studio_title": "🎬 STUDIO MONTAŻU — TWORZENIE HIGHLIGHT REEL",
        "studio_desc": "Zaznacz najlepsze akcje z listy, a program zmontuje z nich jeden dynamiczny film!",
        "studio_select_all": "Zaznacz wszystkie",
        "studio_deselect_all": "Odznacz wszystkie",
        "studio_clip_len": "Długość fragmentu każdego killa (s):",
        "studio_bg_music": "Opcjonalna muzyka w tle (.mp3/.wav):",
        "btn_browse_music": "🎵 Dodaj muzykę...",
        "btn_generate_montage": "🌟 ZMONTUJ FILM Z NAJLEPSZYCH AKCJI (SUPERCUT)",
        "montage_success": "Twój filmik z najlepszymi akcjami został utworzony:\n{path}",
        
        # Tab 4: Scanner
        "scanner_file_placeholder": "Wybierz plik nagrania meczu (.mp4, .mkv, .mov)...",
        "btn_browse": "📁 Przeglądaj...",
        "scanner_before": "Przed killem (s):",
        "scanner_after": "Po killu (s):",
        "scanner_format": "Format:",
        "btn_scan": "🔍 SKANUJ MECZ",
        "btn_export_clips": "💾 Wygeneruj pojedyncze klipy",
        "btn_export_supercut": "⭐ Stwórz Kompilację (Supercut)",
        
        # Tab 5: Settings
        "settings_gpu": "Wykryty procesor graficzny:",
        "settings_codec": "Enkoder i Kodek Wideo (Akceleracja sprzętowa):",
        "settings_quality": "Jakość nagrywania (Bitrate):",
        "settings_buffer": "Długość bufora powtórek (Czas cofnięcia):",
        "settings_hotkey": "Skrót klawiszowy ręcznego zapisu:",
        "btn_save_hotkey": "Zapisz skrót",
        "settings_folder": "Folder docelowy na klipy:",
        "btn_change_folder": "Zmień folder...",
        "settings_lang": "Język interfejsu (Language):",
        "settings_updater": "🔄 Moduł Auto-Aktualizacji:",
        "updater_placeholder": "Adres URL aktualizacji (GitHub API lub JSON)...",
        "btn_save_url": "Zapisz URL",
        "btn_check_update": "🔍 Sprawdź wersję",
        "updater_current": "Bieżąca wersja programu: v{version}"
    },
    
    "en": {
        # Header
        "title": "⚡ AUTOCLIP WAR DOGS PRO",
        "gpu_prefix": "🚀 GPU:",
        "game_active": "● War Dogs: ACTIVE (In-Game)",
        "game_inactive": "○ War Dogs: Not Running",
        "lang_name": "🇬🇧 English",
        
        # Tabs
        "tab_live": "🔴 LIVE (Live Rec)",
        "tab_gallery": "📼 GALLERY & PREVIEW",
        "tab_studio": "🎬 MONTAGE STUDIO",
        "tab_scanner": "🔍 MATCH SCANNER",
        "tab_settings": "⚙️ SETTINGS",
        
        # Master Power Switch
        "master_btn_on": "⚡ AUTOCLIP: ACTIVE",
        "master_btn_off": "⏸️ AUTOCLIP: DISABLED",
        "master_sidebar_title": "⚡ MASTER POWER",
        "master_sidebar_switch": "Recording active",
        "master_live_switch": "⚡ Master recording switch (ON / OFF)",
        "master_btn_stop": "STOP ENGINE",
        "master_btn_start": "START ENGINE",
        "master_banner_on": "🟢 Engine active: auto-saving kills, deaths, revives and mic hype.",
        "master_banner_off": "⏸️ Engine DISABLED: all listening and recording paused (0% resources).",
        
        # Tab 1: Live
        "btn_manual_clip": "🎬 SAVE LAST MINUTE NOW [ Key {key} ]",
        "switch_live_engine": "Enable Standalone Assistant (Mic, event detector & hotkey listening)",
        "mic_title": "🎙️ Voice Excitement & Scream Detector (Hype Detector)",
        "mic_threshold_label": "Microphone Sensitivity Threshold:",
        "switch_kf": "Detect Kills, Downed & Deaths (Pixel Probe • 0% Lag)",
        "gamertag_label": "Your In-Game Gamertag:",
        "gamertag_placeholder": "Enter your War Dogs nickname...",
        "log_title": "📜 Activity Action Log:",
        "btn_open_folder": "📁 Open Clips Folder",
        "status_running": "🟢 Live Assistant has been STARTED.",
        "status_stopped": "⚪ Live Assistant has been STOPPED.",
        "log_action_detected": "💥 [{time}] ACTION DETECTED: {reason} ({extra})",
        "log_clip_saved": "✅ CLIP SAVED: {filename}",
        
        # Tab 2: Gallery
        "btn_refresh": "🔄 Refresh List",
        "btn_open_explorer": "📁 In Explorer",
        "clips_found": "Found: {count} clips ({size:.1f} MB)",
        "no_clips": "No saved clips in folder.\n\nPlay War Dogs and press F8 or scream into mic!",
        "preview_title": "📺 PREVIEW & ACTIONS",
        "no_preview_selected": "Select a clip from the list on the left\nto view thumbnail and actions",
        "btn_play": "▶ PLAY VIDEO CLIP",
        "btn_convert_shorts": "✂ Convert to Shorts (9:16 TikTok)",
        "btn_trim_clip": "✂ Trim this clip...",
        "btn_delete": "🗑 Delete this clip",
        "delete_confirm": "Are you sure you want to delete clip:\n{filename}?",
        
        # Badges
        "badge_kill": "💀 KILL",
        "badge_headshot": "🎯 HEADSHOT",
        "badge_death": "⚰️ DEATH",
        "badge_revive": "💉 REVIVE",
        "badge_mic": "🎙️ MIC SCREAM",
        "badge_manual": "🎬 REPLAY F8",
        "badge_montage": "⭐ MONTAGE",
        
        # Trim Dialog
        "trim_title": "✂ Trim Video Clip",
        "trim_start": "Cut Start (s):",
        "trim_duration": "Clip Duration (s):",
        "trim_btn_confirm": "Save Trimmed Clip",
        "trim_success": "Successfully trimmed and created new clip:\n{filename}",
        
        # Tab 3: Studio
        "studio_title": "🎬 MONTAGE STUDIO — CREATE HIGHLIGHT REELS",
        "studio_desc": "Select the best plays from your clips, and the app will edit them into one epic montage!",
        "studio_select_all": "Select All",
        "studio_deselect_all": "Deselect All",
        "studio_clip_len": "Clip duration per highlight (s):",
        "studio_bg_music": "Optional Background Music (.mp3/.wav):",
        "btn_browse_music": "🎵 Add Music...",
        "btn_generate_montage": "🌟 RENDER HIGHLIGHT REEL (SUPERCUT)",
        "montage_success": "Your highlight reel was created:\n{path}",
        
        # Tab 4: Scanner
        "scanner_file_placeholder": "Select recorded match file (.mp4, .mkv, .mov)...",
        "btn_browse": "📁 Browse...",
        "scanner_before": "Before kill (s):",
        "scanner_after": "After kill (s):",
        "scanner_format": "Format:",
        "btn_scan": "🔍 SCAN MATCH",
        "btn_export_clips": "💾 Export Individual Clips",
        "btn_export_supercut": "⭐ Create Supercut Montage",
        
        # Tab 5: Settings
        "settings_gpu": "Detected GPU Hardware:",
        "settings_codec": "Video Hardware Encoder & Codec:",
        "settings_quality": "Recording Quality (Bitrate):",
        "settings_buffer": "Replay Buffer Length (Lookback Time):",
        "settings_hotkey": "Manual Replay Hotkey:",
        "btn_save_hotkey": "Save Hotkey",
        "settings_folder": "Destination Clips Folder:",
        "btn_change_folder": "Change Folder...",
        "settings_lang": "Interface Language:",
        "settings_updater": "🔄 Auto-Update Module:",
        "updater_placeholder": "Update Feed URL (GitHub API or JSON)...",
        "btn_save_url": "Save URL",
        "btn_check_update": "🔍 Check Version",
        "updater_current": "Current App Version: v{version}"
    }
}

def t(_key: str, _lang: str = "pl", **kwargs) -> str:
    lang_dict = TRANSLATIONS.get(_lang, TRANSLATIONS["pl"])
    text = lang_dict.get(_key, TRANSLATIONS["pl"].get(_key, _key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            pass
    return text
