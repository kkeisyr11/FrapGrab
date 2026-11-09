"""DPI-aware controls with supersampled graphics and native text."""
import math
import tkinter as tk
from tkinter import font as tkfont
import customtkinter as ctk
from PIL import Image,ImageDraw,ImageTk
from .images import AppImage
from .palette import ACCENT, ACTIVE, BG, BORDER, CARD, MUTED, RAISED, TEXT


def chevron_image(size,color):
    scale=6
    image=Image.new('RGBA',(size*scale,size*scale))
    draw=ImageDraw.Draw(image)
    points=[(size*.24,size*.38),(size*.5,size*.64),(size*.76,size*.38)]
    points=[(round(x*scale),round(y*scale)) for x,y in points]
    width=max(1,round(size*.115*scale));radius=width/2
    draw.line(points,fill=color,width=width,joint='curve')
    for x,y in points:draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color)
    return image.resize((size,size),Image.Resampling.LANCZOS)


def controller_image(size):
    scale=6;s=size*scale
    image=Image.new('RGBA',(s,s));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((0,0,s-1,s-1),radius=s*.28,fill=ACTIVE)
    draw.rounded_rectangle((s*.19,s*.29,s*.81,s*.73),radius=s*.14,outline=ACCENT,width=round(s*.045))
    draw.line((s*.3,s*.51,s*.46,s*.51),fill=ACCENT,width=round(s*.045))
    draw.line((s*.38,s*.43,s*.38,s*.59),fill=ACCENT,width=round(s*.045))
    for x,y in ((.65,.45),(.72,.55)):
        draw.ellipse((s*(x-.027),s*(y-.027),s*(x+.027),s*(y+.027)),fill=ACCENT)
    return image.resize((size,size),Image.Resampling.LANCZOS)


class SmoothOptionMenu(ctk.CTkOptionMenu):
    def __init__(self, *args, **kwargs):
        self._popup = None
        self._previous_grab = None
        super().__init__(*args, **kwargs)
        self._canvas.configure(takefocus=True)
        for key in ("<Return>", "<space>", "<Down>"):
            self._canvas.bind(key, self._clicked, add="+")
        self.bind("<Unmap>", lambda _: self._close_popup(), add="+")

    def configure(self, **kwargs):
        if any(key in kwargs for key in ("values", "state")):
            self._close_popup()
        super().configure(**kwargs)

    def destroy(self):
        self._close_popup()
        super().destroy()

    def _close_popup(self):
        popup, self._popup = self._popup, None
        previous, self._previous_grab = self._previous_grab, None
        if popup and popup.winfo_exists():
            popup.destroy()
        if previous and previous.winfo_exists() and previous.winfo_viewable() and previous.grab_current() is None:
            previous.grab_set()

    def _clicked(self, event=None):
        if self._popup:
            self._close_popup()
        elif self._state != tk.DISABLED and self._values and self.grab_current() in (None, self.winfo_toplevel()):
            self._open_dropdown_menu()
        return "break"

    def _create_popup(self):
        popup = tk.Toplevel(self)
        self._popup = popup
        self._previous_grab = self.grab_current()
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())

        def click(event):
            if not (popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width()
                    and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty() + popup.winfo_height()):
                self._close_popup()
                return "break"

        def cancel(event=None):
            self._close_popup()
            self._canvas.focus_set()
            return "break"

        def focus_lost(event):
            def close_if_unfocused():
                if self._popup is popup:
                    focus = popup.focus_get()
                    if not focus or focus.winfo_toplevel() != popup:
                        self._close_popup()
            popup.after_idle(close_if_unfocused)

        popup.bind("<ButtonPress-1>", click, add="+")
        popup.bind("<Escape>", cancel)
        popup.bind("<FocusOut>", focus_lost, add="+")
        return popup

    def _choose_popup_value(self, value):
        self._close_popup()
        self._canvas.focus_set()
        self._dropdown_callback(value)

    def _open_dropdown_menu(self):
        popup = self._create_popup()
        popup.configure(bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        row_font = tkfont.Font(root=popup, family="Segoe UI", size=-round(self._apply_widget_scaling(16)))
        current = self._current_value
        values = tuple(self._values)
        rows = [f"    {value}    " for value in values]
        visible_rows = min(8, len(rows))
        padx = round(self._apply_widget_scaling(5))
        listing = tk.Listbox(
            popup, height=visible_rows, font=row_font, bd=0, highlightthickness=0,
            activestyle="none", selectmode=tk.BROWSE, exportselection=False,
            bg=CARD, fg=TEXT, selectbackground=ACTIVE, selectforeground=ACCENT,
        )
        listing.pack(side="left", fill="both", expand=True, padx=padx, pady=padx)
        if len(rows) > visible_rows:
            bar = ctk.CTkScrollbar(popup, width=13, fg_color=CARD, button_color=BORDER,
                                   button_hover_color=MUTED, command=listing.yview)
            bar.pack(side="right", fill="y", pady=padx)
            listing.configure(yscrollcommand=bar.set)
        listing.insert(tk.END, *rows)
        selected = values.index(current) if current in values else 0
        listing.selection_set(selected)
        listing.activate(selected)
        listing.see(selected)

        def choose(event=None):
            selected_rows = listing.curselection()
            if selected_rows:
                self._choose_popup_value(values[selected_rows[0]])
            return "break"

        listing.bind("<ButtonRelease-1>", choose)
        listing.bind("<Return>", choose)
        listing.bind("<space>", choose)
        width = max(self.winfo_width(), max(map(row_font.measure, rows)) + 2 * padx + 19)
        self._show_popup(popup, width, listing)

    def _show_popup(self, popup, width, focus):
        popup.update_idletasks()
        padx = round(self._apply_widget_scaling(6))
        height = popup.winfo_reqheight()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + padx
        owner = self.winfo_toplevel()
        right = owner.winfo_rootx() + owner.winfo_width()
        bottom = owner.winfo_rooty() + owner.winfo_height()
        if y + height > bottom and self.winfo_rooty() - height - padx >= owner.winfo_rooty():
            y = self.winfo_rooty() - height - padx
        x = min(x, right - width)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.deiconify()
        popup.lift()
        popup.update_idletasks()
        popup.grab_set()
        focus.focus_set()

    def _draw(self,*args,**kwargs):
        super()._draw(*args,**kwargs)
        self._canvas.itemconfigure('dropdown_arrow',state='hidden')
        size=max(10,round(self._apply_widget_scaling(14)))
        color=self._apply_appearance_mode(self._text_color_disabled if self._state=='disabled' else self._text_color)
        key=(size,color)
        if key!=getattr(self,'_chevron_key',None):
            rgb=tuple(channel//257 for channel in self.winfo_rgb(color))
            self._chevron_photo=ImageTk.PhotoImage(chevron_image(size,rgb),master=self._canvas)
            self._chevron_key=key
        if not self._canvas.find_withtag('smooth_arrow'):
            self._canvas.create_image(0,0,tags='smooth_arrow')
        self._canvas.itemconfigure('smooth_arrow',image=self._chevron_photo)
        self._canvas.coords('smooth_arrow',self._apply_widget_scaling(self._current_width-self._current_height/2),
            self._apply_widget_scaling(self._current_height/2))
        self._canvas.tag_raise('smooth_arrow')


class GameSelector(SmoothOptionMenu):
    def __init__(self,master,**kwargs):
        super().__init__(master,width=245,height=42,corner_radius=8,
            fg_color=RAISED,button_color=RAISED,button_hover_color=BORDER,
            text_color=TEXT,font=ctk.CTkFont('Segoe UI',15,weight='bold'),**kwargs)

    def _open_dropdown_menu(self):
        popup = self._create_popup()
        popup.configure(bg=BG)
        try:
            popup.attributes("-transparentcolor", BG)
        except tk.TclError:
            pass
        panel = ctk.CTkFrame(popup, bg_color=BG, fg_color=CARD, border_color=BORDER,
                             border_width=1, corner_radius=12)
        panel.pack(fill="both", expand=True)
        values = tuple(self._values)
        row_font = ctk.CTkFont("Segoe UI", 14, weight="bold")
        row_height = 39
        tick = Image.new("RGBA", (80, 80))
        ImageDraw.Draw(tick).line(((17, 41), (32, 55), (64, 22)), fill=ACCENT, width=10, joint="curve")
        selected_icon = AppImage(popup, tick, size=(16, 16))
        empty_icon = AppImage(popup, Image.new("RGBA", (80, 80)), size=(16, 16))
        if len(values) > 6:
            body = ctk.CTkScrollableFrame(panel, height=6 * row_height, fg_color=CARD,
                                          scrollbar_button_color=BORDER, scrollbar_button_hover_color=MUTED)
        else:
            body = ctk.CTkFrame(panel, fg_color="transparent")
        body.pack(fill="x", padx=7, pady=7)

        selected = values.index(self._current_value) if self._current_value in values else 0
        focused = selected
        buttons = []
        for index, value in enumerate(values):
            row = ctk.CTkButton(body, text=value, font=row_font, anchor="w",
                                image=selected_icon if index == selected else empty_icon,
                                height=row_height - 3, corner_radius=8, border_spacing=11,
                                fg_color=ACTIVE if index == selected else CARD,
                                hover_color=RAISED, text_color=ACCENT if index == selected else TEXT,
                                command=lambda value=value: self._choose_popup_value(value))
            row.pack(fill="x", pady=(0, 3))
            buttons.append(row)

        def move(direction):
            nonlocal focused
            buttons[focused].configure(fg_color=ACTIVE if focused == selected else CARD)
            focused = (focused + direction) % len(values)
            buttons[focused].configure(fg_color=ACTIVE if focused == selected else RAISED)
            if len(values) > 6:
                body._parent_canvas.yview_moveto(max(0, focused - 2) / len(values))
            return "break"

        def choose(_event):
            self._choose_popup_value(values[focused])
            return "break"

        popup.bind("<Up>", lambda _: move(-1))
        popup.bind("<Down>", lambda _: move(1))
        popup.bind("<Return>", choose)
        popup.bind("<space>", choose)
        font_metrics = tkfont.Font(root=popup, family="Segoe UI", weight="bold",
                                   size=-round(self._apply_widget_scaling(14)))
        width = max(self.winfo_width(), max(map(font_metrics.measure, values)) +
                    round(self._apply_widget_scaling(72)))
        self._show_popup(popup, width, popup)
        if len(values) > 6:
            body._parent_canvas.yview_moveto(max(0, selected - 2) / len(values))

    def _create_grid(self):
        super()._create_grid()
        self._text_label.grid_configure(padx=(self._apply_widget_scaling(47),self._apply_widget_scaling(self._current_height+3)))

    def _draw(self,*args,**kwargs):
        super()._draw(*args,**kwargs)
        size=max(20,round(self._apply_widget_scaling(29)))
        if size!=getattr(self,'_controller_size',None):
            self._controller_photo=ImageTk.PhotoImage(controller_image(size),master=self._canvas)
            self._controller_size=size
        if not self._canvas.find_withtag('game_icon'):
            self._canvas.create_image(0,0,tags='game_icon')
        self._canvas.itemconfigure('game_icon',image=self._controller_photo)
        self._canvas.coords('game_icon',self._apply_widget_scaling(23),self._apply_widget_scaling(self._current_height/2))


def gauge_image(fraction,size=720):
    image=Image.new('RGBA',(size,size));draw=ImageDraw.Draw(image)
    width=round(size*.028);margin=round(size*.075)
    bounds=(margin,margin,size-margin-1,size-margin-1)
    draw.ellipse(bounds,outline=BORDER,width=width)
    if fraction>=1:draw.ellipse(bounds,outline=ACCENT,width=width)
    elif fraction>0:
        draw.arc(bounds,-90,-90+360*fraction,fill=ACCENT,width=width)
        radius=(size-2*margin-width)/2
        for angle in (-90,-90+360*fraction):
            x=(size-1)/2+radius*math.cos(math.radians(angle))
            y=(size-1)/2+radius*math.sin(math.radians(angle))
            r=width/2;draw.ellipse((x-r,y-r,x+r,y+r),fill=ACCENT)
    return image


class ReplayGauge(ctk.CTkFrame):
    def __init__(self,master,caption,**kwargs):
        super().__init__(master,width=184,height=184,fg_color='transparent',**kwargs)
        self.pack_propagate(False)
        self.fraction=0
        self._gauge_image=AppImage(self,light_image=gauge_image(0),size=(184,184))
        self._graphic=ctk.CTkLabel(self,text='',image=self._gauge_image)
        self._graphic.place(relx=.5,rely=.5,anchor='center')
        self.number=ctk.CTkLabel(self,text='0 s',text_color=TEXT,
            font=ctk.CTkFont('Segoe UI',32,weight='bold'))
        self.number.place(relx=.5,rely=.44,anchor='center')
        self.caption=ctk.CTkLabel(self,text=caption,text_color=MUTED,font=ctk.CTkFont('Segoe UI',10))
        self.caption.place(relx=.5,rely=.63,anchor='center')

    def set_value(self,text,fraction):
        self.number.configure(text=text)
        if fraction!=self.fraction:
            self.fraction=fraction
            self._gauge_image.configure(light_image=gauge_image(fraction))

    def set_caption(self,text):self.caption.configure(text=text)
