import tkinter as tk
import unittest
from types import SimpleNamespace
from core.buffer_display import buffer_display


class BufferDisplayTests(unittest.TestCase):
    def test_fractional_seconds_do_not_fill_a_ring_showing_zero(self):
        self.assertEqual(buffer_display(.9,60),('0 s',0,False))
        self.assertEqual(buffer_display(15.8,60),('15 s',.25,False))

    def test_time_format_fits_long_replays_and_stays_within_capacity(self):
        self.assertEqual(buffer_display(59.9,60),('59 s',59/60,False))
        self.assertEqual(buffer_display(60,60),('1:00',1,True))
        self.assertEqual(buffer_display(1805,1800),('30:00',1,True))
        self.assertEqual(buffer_display(125,1800)[0],'2:05')

    def test_invalid_or_negative_values_leave_an_empty_indicator(self):
        for value in (-3,float('nan'),float('inf'),None):
            self.assertEqual(buffer_display(value,60),('0 s',0,False))

    def test_canvas_clears_progress_when_a_new_buffer_starts(self):
        from gui.app_window import FrapGrabApp
        root=tk.Tk();root.withdraw()
        try:
            canvas=tk.Canvas(root)
            widget=SimpleNamespace(ring=canvas,
                ring_number=canvas.create_text(40,40),
                ring_arc=canvas.create_arc(0,0,80,80),
                ring_full=canvas.create_oval(0,0,80,80))
            for seconds,arc,full,label in [(15,'normal','hidden','15 s'),
                (60,'hidden','normal','1:00'),(0,'hidden','hidden','0 s')]:
                FrapGrabApp._update_buffer_display(widget,seconds,60)
                self.assertEqual(canvas.itemcget(widget.ring_arc,'state'),arc)
                self.assertEqual(canvas.itemcget(widget.ring_full,'state'),full)
                self.assertEqual(canvas.itemcget(widget.ring_number,'text'),label)
        finally:root.destroy()
