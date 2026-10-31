"""Automatic HUD calibration from a saved replay; OCR never runs in the live loop."""
import re
import json
from pathlib import Path
import numpy as np
import cv2
from .events import normalize
from .media import probe,run_command,find_binary,MediaCancelled
from .hardware import decode_backends,decoder_args
from .pixel_detector import save_profile


def identity(text):
    return normalize(text).translate(str.maketrans({"1":"i","l":"i","0":"o"}))


def own_name_box(results,nickname,width,image=None):
    wanted=identity(nickname)
    for box,text,score in results or []:
        cleaned=re.sub(r"\[[^\]]*\]",lambda m:" "*len(m.group()),text)
        if score<.75 or wanted not in [identity(t) for t in re.findall(r"[\w-]+",cleaned)]:continue
        x0=min(p[0] for p in box);x1=max(p[0] for p in box)
        y0=min(p[1] for p in box);y1=max(p[1] for p in box);cy=(y0+y1)/2
        if x0>width*.45 or y1-y0<8:continue
        tokens=list(re.finditer(r"[\w-]+",cleaned))
        if len(tokens)>2 and identity(tokens[0].group())==wanted and image is not None:
            # OCR sometimes returns an entire killfeed row. Find the actual blank
            # gap after the nickname, excluding the changing weapon and victim.
            prefix=tokens[0].end();h=y1-y0
            crop=image[max(0,round(y0)):round(y1),round(x0):round(x1)]
            bright=(crop.min(axis=2)>150)&((crop.max(axis=2).astype(float)-crop.min(axis=2))<75)
            occupied=np.flatnonzero(bright.any(axis=0))
            gaps=[(a,b) for a,b in zip(occupied[:-1],occupied[1:]) if b-a>=max(5,h*.25) and h*.3*prefix<a<h*.6*prefix]
            if gaps:
                end=gaps[0][0]+2
                return tuple(round(v) for v in (x0,y0,x0+end,y1))
        row=[(min(p[0] for p in b),txt) for b,txt,c in results if c>=.65 and abs(sum(p[1] for p in b)/len(b)-cy)<max(8,(y1-y0)*.6)]
        row.sort()
        if not row or identity(row[0][1])!=identity(text):continue
        if not any(x>x1+15 and len(re.sub(r"[^A-Za-z]","",txt))>=2 for x,txt in row):continue
        return tuple(round(v) for v in (x0,y0,x1,y1))
    return None


def auto_calibrate(path,nickname,folder,cancelled=None):
    if len(nickname.strip())<3:raise ValueError("Wpisz nick gracza.")
    from rapidocr_onnxruntime import RapidOCR
    engine=RapidOCR(intra_op_num_threads=1,inter_op_num_threads=1)
    info=probe(path);video=next(s for s in info["streams"] if s["codec_type"]=="video")
    W,H=video["width"],video["height"]
    width=max(2,round(W*.5));top=round(H*.2);height=round(H*.65)
    found=None
    for backend in decode_backends():
        pending=bytearray();size=width*height*3
        cmd=[find_binary("ffmpeg"),"-v","error",*decoder_args(backend,True),"-ss",str(max(0,float(info["format"]["duration"])-180)),"-i",str(path),"-an"]
        vf="fps=1,"+("hwdownload,format=nv12," if backend=="cuda" else "")+f"crop={width}:{height}:0:{top}:exact=1,format=bgr24"
        cmd += ["-vf",vf,"-frames:v","180","-f","rawvideo","pipe:1"]
        def consume(chunk):
            nonlocal found
            pending.extend(chunk)
            while len(pending)>=size:
                image=np.frombuffer(bytes(pending[:size]),np.uint8).reshape(height,width,3);del pending[:size]
                if cancelled and cancelled():raise MediaCancelled("Kalibracja wstrzymana podczas gry.")
                if found:continue
                results,_=engine(image)
                rectangle=own_name_box(results,nickname,width,image)
                if rectangle:
                    x0,y0,x1,y1=rectangle
                    y0+=top;y1+=top
                    left=max(0,x0-round(32*H/1440));up=max(0,y0-round(140*H/1440))
                    right=min(W,left+max(round(520*H/1440),x1-left+round(250*H/1440)))
                    bottom=min(H,up+round(320*H/1440))
                    # Preserve native pixels; use the same region for all future frames.
                    full=np.zeros((H,W,3),np.uint8);full[top:top+height,:width]=image
                    patch=full[up:bottom,left:right]
                    found=save_profile(folder,patch,(x0-left-2,y0-up-2,x1-left+2,y1-up+2),
                        [left/W,up/H,(right-left)/W,(bottom-up)/H],(W,H))
        try:
            run_command(cmd,timeout=max(120,float(info["format"]["duration"])*3),cancelled=cancelled,on_data=consume)
            break
        except MediaCancelled:raise
        except RuntimeError:
            if backend=="cpu":raise
    if not found:raise ValueError("Nie znaleziono Twojej eliminacji. Wybierz powtórkę z widocznym nickiem w killfeedzie.")
    data=json.loads(Path(found).read_text(encoding="utf-8"));data.update(gamertag=nickname,calibration="automatic")
    Path(found).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return found
