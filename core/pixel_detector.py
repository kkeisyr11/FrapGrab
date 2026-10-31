"""Calibrated visual matching, with no OCR/model inference at runtime."""
import ctypes as c
from ctypes import wintypes as w
import json
import time
from pathlib import Path
import cv2
import numpy as np


class ScreenPatch:
    """Reusable top-down DIB and GDI handles, correctly typed for 64-bit Windows."""
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.user, self.gdi = c.windll.user32, c.windll.gdi32
        self.user.GetDC.argtypes, self.user.GetDC.restype = [c.c_void_p], c.c_void_p
        self.user.ReleaseDC.argtypes = [c.c_void_p, c.c_void_p]
        self.gdi.CreateCompatibleDC.argtypes, self.gdi.CreateCompatibleDC.restype = [c.c_void_p], c.c_void_p
        self.gdi.SelectObject.argtypes, self.gdi.SelectObject.restype = [c.c_void_p, c.c_void_p], c.c_void_p
        self.gdi.CreateDIBSection.argtypes = [c.c_void_p, c.c_void_p, w.UINT, c.POINTER(c.c_void_p), c.c_void_p, w.DWORD]
        self.gdi.CreateDIBSection.restype = c.c_void_p
        self.gdi.BitBlt.argtypes = [c.c_void_p, c.c_int, c.c_int, c.c_int, c.c_int, c.c_void_p, c.c_int, c.c_int, w.DWORD]
        self.gdi.BitBlt.restype = w.BOOL
        self.gdi.DeleteObject.argtypes = [c.c_void_p]
        self.gdi.DeleteDC.argtypes = [c.c_void_p]
        # BITMAPINFOHEADER (40 bytes), BI_RGB, negative height -> top-down BGRA.
        import struct
        info = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40,width,-height,1,32,0,width*height*4,0,0,0,0))
        self.screen = self.user.GetDC(None)
        self.dc = self.gdi.CreateCompatibleDC(self.screen)
        bits = c.c_void_p()
        self.bitmap = self.gdi.CreateDIBSection(self.screen,info,0,c.byref(bits),None,0)
        if not all((self.screen,self.dc,self.bitmap,bits.value)):
            self.close()
            raise OSError("Nie można przygotować graficznego podglądu ekranu.")
        self.previous = self.gdi.SelectObject(self.dc,self.bitmap)
        self.buffer = (c.c_ubyte * (width*height*4)).from_address(bits.value)

    def grab(self, left, top):
        if not self.gdi.BitBlt(self.dc,0,0,self.width,self.height,self.screen,left,top,0x00CC0020):
            raise OSError("Nie można pobrać obszaru ekranu.")
        return np.frombuffer(self.buffer,dtype=np.uint8).reshape(self.height,self.width,4)[:,:,:3].copy()

    def close(self):
        if getattr(self,"previous",None):
            self.gdi.SelectObject(self.dc,self.previous)
        if getattr(self,"bitmap",None):
            self.gdi.DeleteObject(self.bitmap)
            self.bitmap = None
        if getattr(self,"dc",None):
            self.gdi.DeleteDC(self.dc)
            self.dc = None
        if getattr(self,"screen",None):
            self.user.ReleaseDC(None,self.screen)
            self.screen = None


class VisualPatch:
    """Prefer region-aware Desktop Duplication; keep an explicit GDI fallback."""
    def __init__(self,width,height,monitor):
        self.width,self.height,self.monitor = width,height,monitor
        self.camera,self.fallback = None,None
        try:
            import dxcam
            self.camera = dxcam.create(device_idx=0,output_idx=monitor["index"],output_color="BGR",max_buffer_len=2)
            self.backend = "DXGI"
        except Exception:
            self.fallback = ScreenPatch(width,height)
            self.backend = "GDI"

    def grab(self,left,top):
        if self.camera:
            x,y = left-self.monitor["left"],top-self.monitor["top"]
            return self.camera.grab(region=(x,y,x+self.width,y+self.height),new_frame_only=False)
        return self.fallback.grab(left,top)

    def close(self):
        if self.camera:
            self.camera.release()
            self.camera = None
        if self.fallback:
            self.fallback.close()
            self.fallback = None


def edges(image):
    return cv2.Canny(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 70, 150)


def features(image, mode="white"):
    if mode == "edges":
        return edges(image).astype(np.float32)/255
    low = image.min(axis=2)
    high = image.max(axis=2)
    mask = ((low > 150) & ((high.astype(np.float32)-low) < 75)).astype(np.float32)
    # Soft glyph mask tolerates compressed edges and changing background textures.
    return cv2.GaussianBlur(mask,(3,3),0)


class PixelMatcher:
    def __init__(self, profile):
        self.profile = profile
        raw = cv2.imdecode(np.fromfile(profile["template"],dtype=np.uint8),cv2.IMREAD_COLOR)
        if raw is None:
            raise ValueError("Nie można odczytać wzorca. Skalibruj go ponownie.")
        scale=float(profile.get("template_scale",1))
        if abs(scale-1)>.001:
            raw=cv2.resize(raw,(max(2,round(raw.shape[1]*scale)),max(2,round(raw.shape[0]*scale))))
        self.mode = profile.get("feature", "white")
        self.template = features(raw,self.mode)
        if np.count_nonzero(self.template) < 15 or float(self.template.std()) < .03:
            raise ValueError("Wzorzec nie zawiera wystarczająco wyraźnego kształtu.")
        self.active_count = 0
        self.candidate = 0
        self.confirmations = 0
        self.absent = 0

    def count_matches(self, image):
        if list(image.shape[1::-1]) != self.profile["patch_size"]:
            raise ValueError("Zmieniono rozdzielczość lub obszar HUD-u. Skalibruj wzorzec ponownie.")
        x = self.profile["anchor_x"]
        tw, th = self.template.shape[1], self.template.shape[0]
        left, right = max(0,x-12), min(image.shape[1],x+tw+12)
        search = features(image[:,left:right],self.mode)
        if search.shape[0] < th or search.shape[1] < tw:
            return 0, 0.0
        scores = cv2.matchTemplate(search,self.template,cv2.TM_CCOEFF_NORMED)
        best = float(scores.max())
        peaks = np.max(scores,axis=1)
        rows = []
        for row in np.argsort(peaks)[::-1]:
            if peaks[row] < self.profile.get("threshold",.8):
                break
            if all(abs(int(row)-y) >= max(8,int(th*.8)) for y in rows):
                rows.append(int(row))
        return len(rows), best

    def update(self, image):
        count, score = self.count_matches(image)
        self.confirmations = self.confirmations+1 if count == self.candidate else 1
        self.candidate = count
        if self.confirmations < 2:
            return False, score
        if count == 0:
            self.absent += 1
            if self.absent >= 2:
                self.active_count = 0
            return False, score
        self.absent = 0
        fresh = count > self.active_count
        self.active_count = count
        return fresh, score


def save_profile(folder, image, rectangle, region, monitor_size):
    x0,y0,x1,y1 = [int(v) for v in rectangle]
    x0,x1 = sorted((max(0,min(image.shape[1],x0)),max(0,min(image.shape[1],x1))))
    y0,y1 = sorted((max(0,min(image.shape[0],y0)),max(0,min(image.shape[0],y1))))
    template = image[y0:y1,x0:x1]
    if template.shape[0] < 8 or template.shape[1] < 25 or np.count_nonzero(edges(template)) < 15:
        raise ValueError("Zaznacz wyraźny nick/znak: co najmniej 25 × 8 pikseli.")
    folder = Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    template_path = folder / f"pattern_{time.time_ns()}.png"
    ok, encoded = cv2.imencode(".png",template)
    if not ok:
        raise ValueError("Nie można zapisać wzorca.")
    encoded.tofile(str(template_path))
    profile = {"template":str(template_path),"anchor_x":x0,"patch_size":[image.shape[1],image.shape[0]],
               "region":region,"monitor_size":list(monitor_size),"threshold":.8,
               "feature":"white" if float(features(template).std()) > .03 else "edges"}
    path = folder / "pixel-profile.json"
    path.write_text(json.dumps(profile,indent=2),encoding="utf-8")
    return str(path)
