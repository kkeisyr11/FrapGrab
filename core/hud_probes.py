"""Additional calibrated HUD cues shared by live and offline pixel detection."""
from pathlib import Path


def auxiliary_profiles(profile):
    # This template is for the Polish War Dogs HUD at the calibrated 16:9 layout.
    # It is the result notification, so assists do not need an own-name killfeed row.
    template=Path(__file__).resolve().parents[1]/"assets/patterns/wardogs-assist-pl.png"
    if not template.is_file():return []
    return [{"template":str(template),"anchor_x":67,"patch_size":[410,115],
             "region":[1075/2560,986/1440,410/2560,115/1440],
             "monitor_size":[2560,1440],"threshold":.88,"feature":"white","event_type":"assist"}]


def pixel_profiles(profile):
    return [{**profile,"event_type":"kill"},*auxiliary_profiles(profile)]


def adapt_profile(profile,width,height):
    """Keep HUD pixel scale tied to height, including wide and narrow monitors."""
    base_w,base_h=profile["monitor_size"]
    x,y,w,h=profile["region"]
    scale=height/base_h
    left=x*base_w*scale
    if profile.get("event_type")=="assist":left=width/2+(x*base_w-base_w/2)*scale
    left=max(0,min(width-2,left))
    region=[left/width,y,min(w*base_w*scale,width-left)/width,min(h,1-y)]
    result={**profile,"region":region}
    if "patch_size" in profile:
        result.update(patch_size=[max(2,round(region[2]*width)),max(2,round(region[3]*height))],
            anchor_x=round(profile["anchor_x"]*scale),template_scale=scale)
        if profile.get("event_type")=="assist" and abs(scale-1)>.001:
            result["threshold"]=.8
    return result


class HudCapture:
    """One Desktop Duplication read for several small pixel probes, without OCR."""
    def __init__(self,profiles,monitor):
        from .pixel_detector import PixelMatcher,VisualPatch
        self.profiles=profiles
        self.monitor=monitor
        self.matchers=[PixelMatcher(p) for p in profiles]
        self.rects=[]
        for p in profiles:
            x,y,w,h=p["region"]
            self.rects.append((round(x*monitor["width"]),round(y*monitor["height"]),
                               round(w*monitor["width"]),round(h*monitor["height"])))
        self.left=min(r[0] for r in self.rects);self.top=min(r[1] for r in self.rects)
        width=max(x+w for x,y,w,h in self.rects)-self.left
        height=max(y+h for x,y,w,h in self.rects)-self.top
        self.capture=VisualPatch(width,height,monitor)
        self.backend=self.capture.backend

    def read(self):
        import cv2
        image=self.capture.grab(self.monitor["left"]+self.left,self.monitor["top"]+self.top)
        if image is None:return []
        events=[]
        for profile,matcher,(x,y,w,h) in zip(self.profiles,self.matchers,self.rects):
            patch=image[y-self.top:y-self.top+h,x-self.left:x-self.left+w]
            if tuple(patch.shape[1::-1])!=tuple(profile["patch_size"]):
                patch=cv2.resize(patch,tuple(profile["patch_size"]))
            fresh,score=matcher.update(patch)
            if fresh:events.append((profile["event_type"],score))
        return events

    def close(self):
        self.capture.close()
