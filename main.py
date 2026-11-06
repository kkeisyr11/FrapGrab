import sys
import os
import logging
from logging.handlers import RotatingFileHandler

# Restrict background matrix worker threads so they never steal CPU slices from games
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# Ensure current directory and exe directory are in sys.path and os.environ["PATH"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXE_DIR = os.path.dirname(sys.executable)
for d in (BASE_DIR, EXE_DIR):
    if d and d not in sys.path:
        sys.path.insert(0, d)
    if d and d not in os.environ.get("PATH", ""):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

from gui.app_window import FrapGrabApp

def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from core.diagnostics import self_test
        raise SystemExit(self_test(sys.argv[2]))
    if len(sys.argv)==3 and sys.argv[1]=="--preview-setup":
        from pathlib import Path
        from PIL import ImageGrab
        import ctypes,json
        from gui.window_style import frame_bounds,caption_state
        app=FrapGrabApp(preview=True)
        if app.config_data["gamertag"] or app.config_data["pixel_profile"]:
            app.destroy()
            raise RuntimeError("Setup preview requires a fresh, isolated LOCALAPPDATA profile.")
        app.geometry(os.environ.get("AUTOCLIP_QA_GEOMETRY","1260x850+40+40"));app.lift()
        wizard=app.open_setup()
        wizard.geometry(os.environ.get("AUTOCLIP_QA_SETUP_GEOMETRY","940x720+200+100"))
        target=Path(sys.argv[2]);target.mkdir(parents=True,exist_ok=True)
        def show(index=0):
            if index==4:
                (target/"preview.json").write_text(json.dumps({"default_nickname_empty":True,"private_template_empty":True,
                    "configuration_saved":False,"demo_nickname":"PlayerOne"},indent=2),encoding="utf-8")
                wizard.cancel();app.thumbnail_pool.shutdown(wait=False,cancel_futures=True);app.destroy();return
            wizard.show_step(index)
            if index==1:wizard.next()
            if index==2:
                wizard.nickname.insert(0,"PlayerOne")
                wizard.folder.delete(0,"end");wizard.folder.insert(0,r"C:\Users\Player\Videos\FrapGrab")
            def shot():
                wizard.update_idletasks()
                ImageGrab.grab(bbox=frame_bounds(wizard),all_screens=True).save(target/f"setup-{index+1}.png")
                if index==0:(target/"caption.json").write_text(json.dumps(caption_state(wizard),indent=2),encoding="utf-8")
                app.after(100,lambda:show(index+1))
            app.after(900,shot)
        app.after(900,show);app.mainloop();return
    if len(sys.argv) == 3 and sys.argv[1] == "--preview-image":
        from PIL import ImageGrab
        import ctypes
        app = FrapGrabApp(preview=True)
        if os.environ.get("AUTOCLIP_QA_GEOMETRY"):
            app.geometry(os.environ["AUTOCLIP_QA_GEOMETRY"])
            app.lift()
        target = os.path.abspath(sys.argv[2])
        page_keys = list(app.pages)
        def show_next(index=0):
            if index >= len(page_keys):
                app.thumbnail_pool.shutdown(wait=False, cancel_futures=True)
                app.destroy()
                return
            app.show_page(page_keys[index])
            app.after(1200,lambda: snapshot(index))
        def snapshot(index):
            app.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(app.winfo_id())
            path = target.replace(".png", f"-{page_keys[index]}.png")
            ImageGrab.grab(window=hwnd).save(path)
            app.after(100,lambda: show_next(index+1))
        app.after(1500, show_next)
        app.mainloop()
        return
    import ctypes
    if os.name == "nt":
        kernel = ctypes.windll.kernel32
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, "Local\\AutoClipWarDogsDesktop")
        if kernel.GetLastError() == 183:
            from core.config import load_config
            from core.localization import messagebox,set_language
            set_language(load_config()["language"])
            messagebox.showinfo("Frap Grab", "Aplikacja jest już uruchomiona. Sprawdź pasek zadań.")
            return
    from core.config import CONFIG_DIR
    os.makedirs(CONFIG_DIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        os.path.join(CONFIG_DIR, "frapgrab.log"), maxBytes=2_000_000, backupCount=2, encoding="utf-8")],
        format="%(asctime)s %(levelname)s %(message)s",force=True)
    app = FrapGrabApp()
    if '--resume-recording' in sys.argv and app.config_data.get('setup_completed') and not app.config_data.get('auto_record_enabled'):
        app.after(1000,app.toggle_recording)
    if len(sys.argv)==3 and sys.argv[1]=="--open-montage":
        import json
        from pathlib import Path
        try:
            request=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
            app.selected={Path(item["source"]) for item in request["clips"] if Path(item["source"]).is_file()}
            app.montage_format.set("Shorts / Reels · 9:16" if request.get("vertical") else "YouTube · 16:9")
            app.montage_style.set("Krótkie przenikanie" if request.get("transitions",True) else "Czyste cięcia")
            app.montage_duration.set(f"{max(1,int(request['clips'][0].get('duration',8)))} sekund")
            mode=request.get("selection_mode","highlights")
            if mode=="preserve":app.montage_duration.set("8 sekund")
            app.selection_mode.set(next((label for label,value in app.selection_modes.items() if value==mode),next(iter(app.selection_modes))))
            app._selection_mode_changed()
            filters=request.get("event_options",{})
            app.include_kills.set(filters.get("kills",True))
            app.include_assists.set(filters.get("assists",True))
            app.include_voice.set(filters.get("voice",True))
            near=filters.get("assist_near_seconds")
            app.assist_rule.set(f"Przy eliminacji · do {near} s" if near in (8,15) else "Wszystkie asysty")
            gain=max(0,min(60,float(request.get("music_gain",.16))*100))
            app.music_gain.set(gain)
            app.music_gain_label.configure(text=f"Głośność muzyki · {gain:.0f}%")
            app.music_entry.insert(0,request.get("music", ""))
            movie=Path(sys.argv[2].removesuffix(".edit.json"))
            if movie.is_file():app._show_completed_movie(movie)
            app.after(200,lambda:app.show_page("studio"))
        except (OSError,ValueError,KeyError,IndexError,TypeError):
            logging.exception("Could not restore montage selection")
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()

if __name__ == "__main__":
    main()
