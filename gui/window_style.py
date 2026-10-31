"""Consistent native Windows caption colors for the app and its dialogs."""
import ctypes as c
from ctypes import wintypes as w
import sys


def window_handle(window):
    user=c.windll.user32
    user.GetAncestor.argtypes=[w.HWND,w.UINT];user.GetAncestor.restype=w.HWND
    return user.GetAncestor(w.HWND(window.winfo_id()),2)


def apply_dark_titlebar(window):
    if sys.platform!="win32":return {}
    try:
        if not window.winfo_exists():return {}
        hwnd=window_handle(window)
        dwm=c.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
        dwm.DwmSetWindowAttribute.restype=c.c_long
        results={}
        for attr,value in ((20,1),(35,0x00161310),(36,0x00EDF2F1),(34,0x003F3830)):
            data=w.DWORD(value)
            results[attr]=dwm.DwmSetWindowAttribute(hwnd,attr,c.byref(data),c.sizeof(data))
        if results[20]!=0:
            data=w.DWORD(1);dwm.DwmSetWindowAttribute(hwnd,19,c.byref(data),c.sizeof(data))
        return results
    except (OSError,AttributeError):return {}


def style_window(window):
    def mapped(event=None):
        if event is None or event.widget is window:window.after(20,lambda:apply_dark_titlebar(window))
    window.bind("<Map>",mapped,add="+")
    window.after(350,mapped)


def caption_state(window):
    """Read actual DWM values for visual regression checks."""
    dwm=c.windll.dwmapi
    dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
    dwm.DwmGetWindowAttribute.restype=c.c_long
    result={}
    for attr in (20,35,36):
        value=w.DWORD()
        if dwm.DwmGetWindowAttribute(window_handle(window),attr,c.byref(value),c.sizeof(value))==0:result[attr]=value.value
    return result


def frame_bounds(window):
    rect=w.RECT()
    dwm=c.windll.dwmapi
    dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
    dwm.DwmGetWindowAttribute.restype=c.c_long
    if dwm.DwmGetWindowAttribute(window_handle(window),9,c.byref(rect),c.sizeof(rect)):
        user=c.windll.user32;user.GetWindowRect.argtypes=[w.HWND,c.POINTER(w.RECT)]
        user.GetWindowRect(window_handle(window),c.byref(rect))
    return rect.left,rect.top,rect.right,rect.bottom
