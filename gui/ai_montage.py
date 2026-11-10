"""The optional AI editing workspace. Media remains local."""
from pathlib import Path
from threading import Event
import webbrowser

import customtkinter as ctk

from core.ai_montage import prepare_brief, validate_plan
from core.localization import LButton, LEntry, LLabel, LOptionMenu, t
from gui.palette import ACCENT, BG, BORDER, CARD, MUTED, RAISED, RED, TEXT
from gui.window_style import style_window


PRESETS = (
    ("Najlepsze akcje · YouTube", 90, "16:9",
     "Otwórz najmocniejszą akcją. Ułóż eliminacje, asysty i zwycięstwa w zwięzły film. Zostaw krótki kontekst, usuń długie przerwy i powtórzone akcje."),
    ("Szybki Shorts", 30, "9:16",
     "Zacznij od razu od najmocniejszej akcji. Wybierz kilka krótkich ujęć, zetnij przerwy i zakończ na wyraźnej puencie."),
    ("Zabawne reakcje", 60, "16:9",
     "Wybierz klipy ze znacznikami reakcji mikrofonu. Zachowaj moment poprzedzający reakcję i jej koniec. Pomiń klipy bez reakcji, jeśli są inne opcje."),
)


class AIMontageDialog(ctk.CTkToplevel):
    def __init__(self, app, paths, vertical, apply):
        super().__init__(app)
        self.app, self.paths, self.apply = app, paths, apply
        self.cancelled = Event()
        self.brief = self.plan = None
        self.title(t("Plan montażu AI"))
        self.geometry("720x660")
        self.minsize(620, 590)
        self.transient(app)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        style_window(self)
        panel = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=12)
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        LLabel(panel, text="Plan montażu AI", font=ctk.CTkFont("Segoe UI", 22, weight="bold")).pack(anchor="w", padx=14, pady=(12, 8))
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 8))
        self.provider = LOptionMenu(row, values=["ChatGPT", "Claude · przeglądarka"],
                                    fg_color=RAISED, button_color=BORDER, command=self._provider_changed)
        self.provider.pack(side="left")
        self.seconds = LEntry(row, width=65, fg_color=BG, border_color=BORDER)
        self.seconds.insert(0, "90")
        self.seconds.pack(side="right")
        LLabel(row, text="Długość (s)", text_color=MUTED).pack(side="right", padx=8)
        self.format = ctk.CTkSegmentedButton(row, values=["16:9", "9:16"],
                                            fg_color=RAISED, selected_color=BORDER,
                                            selected_hover_color=BORDER, unselected_color=RAISED,
                                            command=lambda _: self._clear_plan())
        self.format.set("9:16" if vertical else "16:9")
        self.format.pack(side="right", padx=12)
        preset_row = ctk.CTkFrame(panel, fg_color="transparent")
        preset_row.pack(fill="x", padx=14, pady=(4, 6))
        self.preset_buttons = []
        for preset in PRESETS:
            button = LButton(preset_row, text=preset[0], width=150, fg_color=RAISED,
                             command=lambda preset=preset: self._apply_preset(preset))
            button.pack(side="left", padx=(0, 8))
            self.preset_buttons.append(button)
        LLabel(panel, text="Opis dla AI", text_color=MUTED).pack(anchor="w", padx=14)
        self.goal = ctk.CTkTextbox(panel, height=66, fg_color=BG, border_width=1, border_color=BORDER)
        self.goal.pack(fill="x", padx=14, pady=(0, 6))
        LLabel(panel, text="Do modelu trafiają Twój opis i znaczniki klipów.",
               text_color=MUTED).pack(anchor="w", padx=14)
        self.buttons = ctk.CTkFrame(panel, fg_color="transparent")
        self.buttons.pack(fill="x", padx=14, pady=10)
        self.connect_button = self._button("Continue with ChatGPT", self.connect)
        self.generate_button = self._button("Zaproponuj cięcia", self.generate)
        self.paste_button = self._button("Wczytaj odpowiedź", self.paste)
        self.status = LLabel(panel, text="", wraplength=540, justify="left", text_color=MUTED)
        self.status.pack(anchor="w", padx=14)
        self.reply = ctk.CTkTextbox(panel, fg_color=BG, text_color=TEXT, height=112)
        self.reply.pack(fill="x", padx=14, pady=8)
        self.review = LLabel(panel, text="", wraplength=540, justify="left", text_color=TEXT)
        self.review.pack(anchor="w", padx=14)
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=12)
        self.accept = LButton(actions, text="Użyj planu", command=self.accept_plan, fg_color=RAISED, state="disabled")
        self.accept.pack(side="left", padx=(0, 8))
        self.export = LButton(actions, text="Eksportuj z tego planu", command=lambda: self.accept_plan(export=True),
                              fg_color=ACCENT, text_color=BG, state="disabled")
        self.export.pack(side="left")
        self._provider_changed(self.provider.get())

    def _button(self, title, command):
        return LButton(self.buttons, text=title, command=command, fg_color=RAISED)

    def _clear_plan(self):
        self.brief = self.plan = None
        self.review.configure(text="")
        self.status.configure(text="", text_color=MUTED)
        self.accept.configure(state="disabled")
        self.export.configure(state="disabled")
        self.reply.delete("1.0", "end")

    def _apply_preset(self, preset):
        _, seconds, aspect, prompt = preset
        self._clear_plan()
        self.seconds.delete(0, "end")
        self.seconds.insert(0, str(seconds))
        self.format.set(aspect)
        self.goal.delete("1.0", "end")
        self.goal.insert("1.0", t(prompt))

    def _provider_changed(self, provider):
        self._clear_plan()
        for button in (self.connect_button, self.generate_button, self.paste_button):
            button.pack_forget()
        if provider == "ChatGPT":
            self.connect_button.pack(side="left", padx=(0, 8))
            self.connect_button.configure(text="Rozłącz ChatGPT" if self.app.chatgpt_plan.tokens else "Continue with ChatGPT")
            self.generate_button.configure(text="Zaproponuj cięcia")
            self.status.configure(text="", text_color=MUTED)
        else:
            self.generate_button.configure(text="Skopiuj brief i otwórz Claude")
            self.status.configure(text="Wklej brief w Claude, potem wklej tutaj odpowiedź JSON.", text_color=MUTED)
        self.generate_button.pack(side="left", padx=(0, 8))
        self.paste_button.pack(side="left")

    def _job(self, message, work, done):
        self.status.configure(text=message, text_color=MUTED)
        inputs = (self.provider, self.connect_button, self.generate_button, self.paste_button,
                  self.seconds, self.goal, self.format, *self.preset_buttons)
        for widget in inputs:
            widget.configure(state="disabled")
        self.accept.configure(state="disabled")
        self.export.configure(state="disabled")

        def run():
            try:
                return work(), None
            except Exception as exc:
                return None, str(exc)

        def finish(result):
            if self.cancelled.is_set():
                return
            for widget in inputs:
                widget.configure(state="normal")
            value, error = result
            if error:
                if self.provider.get() == "ChatGPT":
                    self.connect_button.configure(text="Rozłącz ChatGPT" if self.app.chatgpt_plan.tokens else "Continue with ChatGPT")
                self.status.configure(text=error, text_color=RED)
                return
            try:
                done(value)
            except (OSError, ValueError, RuntimeError) as exc:
                self.status.configure(text=str(exc), text_color=RED)
        self.app.background(run, finish)

    def connect(self):
        client = self.app.chatgpt_plan
        if client.tokens:
            self._job("Rozłączam ChatGPT…", client.disconnect, lambda _: self._provider_changed(self.provider.get()))
        else:
            self._job("Dokończ logowanie w przeglądarce.", lambda: client.connect(self.cancelled.is_set),
                      lambda _: self._provider_changed(self.provider.get()))

    def generate(self):
        provider = self.provider.get()
        if provider == "ChatGPT" and not self.app.chatgpt_plan.tokens:
            self.status.configure(text="Najpierw połącz konto ChatGPT.", text_color=RED)
            return
        try:
            seconds = int(self.seconds.get())
        except ValueError:
            self.status.configure(text="Podaj długość od 10 do 600 sekund.", text_color=RED)
            return
        goal, language = self.goal.get("1.0", "end-1c"), self.app.config_data["language"]
        vertical = self.format.get() == "9:16"
        self._clear_plan()

        def work():
            brief = prepare_brief(self.paths, goal, seconds, vertical, language)
            if provider == "ChatGPT" and not self.cancelled.is_set():
                return brief, self.app.chatgpt_plan.propose(brief[0], self.cancelled.is_set)
            return brief, None

        def done(result):
            self.brief, reply = result
            if reply is not None:
                self.reply.insert("1.0", reply)
                self.paste()
            else:
                self.app.clipboard_clear()
                self.app.clipboard_append(self.brief[0])
                webbrowser.open("https://claude.ai/new")
                self.status.configure(text="Brief skopiowany. Wklej odpowiedź JSON poniżej.", text_color=ACCENT)
        self._job("Przygotowuję plan montażu…", work, done)

    def paste(self):
        if not self.brief:
            self.status.configure(text="Najpierw przygotuj brief dla tego wyboru.", text_color=RED)
            return
        self.plan = None
        self.accept.configure(state="disabled")
        self.export.configure(state="disabled")
        try:
            self.plan = validate_plan(self.reply.get("1.0", "end"), self.brief[1], self.brief[2])
        except ValueError as exc:
            self.review.configure(text="")
            self.status.configure(text=str(exc), text_color=RED)
            return
        title, cuts = self.plan
        duration = self.app._duration_text(sum(cut.end - cut.start for cut in cuts))
        self.status.configure(text=f"{duration} · {len(cuts)} ujęć", text_color=ACCENT)
        lines = [f"{index:02}.  {Path(cut.path).name}  ·  {cut.start:.1f}–{cut.end:.1f} s"
                 for index, cut in enumerate(cuts, 1)]
        self.review.configure(text="\n".join([title, *lines]))
        self.accept.configure(state="normal")
        self.export.configure(state="normal")

    def accept_plan(self, export=False):
        if self.plan and self.apply(self.paths, self.plan, self.format.get() == "9:16"):
            self.close()
            if export:
                self.app.after_idle(self.app.export_montage)

    def close(self):
        self.cancelled.set()
        self.destroy()
