import unittest
import customtkinter as ctk
from core.localization import LOptionMenu,set_language
from gui.widgets import GameSelector


class RenderingTests(unittest.TestCase):
    def test_dropdowns_survive_disabled_named_colors_language_and_dpi_changes(self):
        root=ctk.CTk();root.withdraw()
        try:
            menu=LOptionMenu(root,values=['Czyste cięcia','Krótkie przenikanie'])
            game=GameSelector(root,values=['War Dogs'])
            menu.set('Krótkie przenikanie')
            for scale in (1,1.25,1.5,2):
                ctk.set_widget_scaling(scale)
                for state in ('disabled','normal'):
                    menu.configure(state=state,text_color_disabled='gray68')
                    game.configure(state=state)
                    root.update_idletasks()
                    self.assertEqual(menu.get(),'Krótkie przenikanie')
                    self.assertEqual(game.get(),'War Dogs')
                    self.assertEqual(menu._canvas.itemcget('dropdown_arrow','state'),'hidden')
                    self.assertEqual(game._chevron_photo.width(),round(game._apply_widget_scaling(14)))
                set_language('en')
                self.assertEqual(menu.get(),'Krótkie przenikanie')
                set_language('pl')
        finally:
            ctk.set_widget_scaling(1)
            for timer in root.tk.call('after','info'):root.after_cancel(timer)
            root.destroy()
