"""Images bound to the owning Tcl interpreter, shared by app windows."""
import customtkinter as ctk
from PIL import ImageTk


class AppImage(ctk.CTkImage):
    def __init__(self,master,*args,**kwargs):
        self.master=master
        super().__init__(*args,**kwargs)

    def _get_scaled_light_photo_image(self,size):
        if size not in self._scaled_light_photo_images:
            self._scaled_light_photo_images[size]=ImageTk.PhotoImage(self._light_image.resize(size),master=self.master)
        return self._scaled_light_photo_images[size]

    def _get_scaled_dark_photo_image(self,size):
        if size not in self._scaled_dark_photo_images:
            self._scaled_dark_photo_images[size]=ImageTk.PhotoImage(self._dark_image.resize(size),master=self.master)
        return self._scaled_dark_photo_images[size]
