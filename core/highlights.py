"""Offline action windows: every marker, player-specific HUD event and loud audio run.

No random motion-only or filename-only selection is treated as a verified action.
Unclassified sources are reported explicitly, never padded into a long movie.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import cv2
from .config import load_config,CONFIG_DIR
from .media import find_binary,run_command,MediaCancelled
from .pixel_detector import PixelMatcher
from .hud_probes import pixel_profiles,adapt_profile
from .hardware import decode_backends,decoder_args


def voice_stream_indices(streams):
    return [s["index"] for s in streams if s["codec_type"]=="audio" and
        any(s.get("tags",{}).get(key,"") in ("Frap Grab microphone","Frap Grab chat","AutoClip microphone","AutoClip chat") for key in ("title","handler_name"))]


def merge_ranges(ranges,total):
    merged=[]
    for start,end in sorted((max(0,a),min(total,b)) for a,b in ranges if b>a):
        if merged and start<=merged[-1][1]+.6:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    return merged


def audio_activity(samples,rate=16000):
    size=int(rate*.1)
    count=len(samples)//size
    if count<2:return []
    blocks=samples[:count*size].reshape(count,size)
    db=20*np.log10(np.maximum(1e-6,np.sqrt(np.mean(blocks*blocks,axis=1))))
    return activity_from_db(db)


def activity_from_db(db):
    if len(db)<2:return []
    threshold=max(-35,float(np.percentile(db,35))+8)
    active=np.flatnonzero(db>=threshold)
    groups=[]
    for index in active:
        t=float(index)*.1
        if groups and t-groups[-1][1]<=.8:groups[-1][1]=t+.1
        else:groups.append([t,t+.1])
    return [{"time":a,"end":b,"type":"audio","confidence":"loud_audio"} for a,b in groups]


def _metadata_events(path,total):
    try:data=json.loads(Path(str(path)+".json").read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):return []
    events=[]
    for item in data.get("events",[]):
        try:
            stamp=float(item["time"])
            if 0<=stamp<=total:events.append({"time":stamp,"type":item.get("type","kill"),"confidence":"recorded_marker"})
        except (KeyError,TypeError,ValueError):pass
    if not events:
        for stamp in data.get("event_offsets",[]):
            try:
                stamp=float(stamp)
                if 0<=stamp<=total:events.append({"time":stamp,"type":"mic" if data.get("reason")=="mic" else "kill","confidence":"recorded_marker"})
            except (TypeError,ValueError):pass
    return events


def discover_events(path,info,on_progress=None,cancelled=None):
    path=Path(path)
    total=float(info["format"]["duration"])
    events=_metadata_events(path,total)
    config=load_config()
    profile_path=Path(config.get("pixel_profile") or "__no_profile__")
    try:profile=json.loads(profile_path.read_text(encoding="utf-8"));profile_stamp=profile_path.stat().st_mtime_ns
    except (OSError,ValueError):profile=None;profile_stamp=0
    stat=path.stat()
    probe_stamps=[Path(p["template"]).stat().st_mtime_ns for p in pixel_profiles(profile)] if profile else []
    key=hashlib.sha256(f"events-v6-native-hud|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{profile_stamp}|{probe_stamps}|{config.get('auto_hud',True)}".encode()).hexdigest()
    cache=Path(CONFIG_DIR)/"highlight_cache"/(key+".json")
    try:
        found=json.loads(cache.read_text(encoding="utf-8"))
        if on_progress:on_progress(1,"Akcje odczytane z pamięci podręcznej")
        return events+found
    except (OSError,ValueError):pass
    found=[]
    video=next(s for s in info["streams"] if s["codec_type"]=="video")
    for current_profile in pixel_profiles(profile) if profile else []:
        W,H=video["width"],video["height"]
        if config.get("auto_hud",True) or current_profile["event_type"]=="assist":current_profile=adapt_profile(current_profile,W,H)
        x,y,w,h=current_profile["region"]
        width,height=max(2,round(w*W)),max(2,round(h*H))
        left,top=round(x*W),round(y*H)
        for backend in decode_backends():
            if on_progress:on_progress(0,"Wykrywanie eliminacji i asyst · "+backend.upper())
            cmd=[find_binary("ffmpeg"),"-v","error","-progress","pipe:2","-nostats"]
            cmd += decoder_args(backend,hardware_frames=True)
            vf="fps=4,"+("hwdownload,format=nv12," if backend=="cuda" else "")+f"crop={width}:{height}:{left}:{top}:exact=1,format=bgr24"
            cmd += ["-i",str(path),"-an","-sn","-dn","-vf",vf,"-f","rawvideo","pipe:1"]
            matcher=PixelMatcher(current_profile)
            pending=bytearray()
            frame_size=width*height*3
            frame_index=0
            video_events=[]
            target=tuple(current_profile["patch_size"])
            def consume(chunk):
                nonlocal frame_index
                pending.extend(chunk)
                while len(pending)>=frame_size:
                    if cancelled and cancelled():raise MediaCancelled("Anulowano analizę akcji.")
                    packet=bytes(pending[:frame_size]);del pending[:frame_size]
                    frame=np.frombuffer(packet,dtype=np.uint8).reshape(height,width,3)
                    if (width,height)!=target:frame=cv2.resize(frame,target)
                    fresh,score=matcher.update(frame)
                    if fresh:video_events.append({"time":(frame_index+.5)/4,"type":current_profile["event_type"],"confidence":"player_hud","score":round(score,3)})
                    frame_index+=1
            try:
                run_command(cmd,max(90,total*2),cancelled,
                    (lambda t:on_progress(min(.8,.8*t/total),"Wykrywanie wszystkich eliminacji")) if on_progress else None,"stderr",on_data=consume)
                break
            except MediaCancelled:raise
            except RuntimeError:
                if backend=="cpu":raise
        found+=video_events
    audio_streams=[s for s in info["streams"] if s["codec_type"]=="audio"]
    voices=voice_stream_indices(audio_streams)
    if audio_streams:
        if on_progress:on_progress(.8,"Szukanie głośnych reakcji i rozmów")
        audio_pending=bytearray();levels=[]
        def consume_audio(chunk):
            audio_pending.extend(chunk)
            while len(audio_pending)>=6400:
                block=np.frombuffer(bytes(audio_pending[:6400]),dtype=np.float32);del audio_pending[:6400]
                levels.append(20*np.log10(max(1e-6,float(np.sqrt(np.mean(block*block))))))
        cmd=[find_binary("ffmpeg"),"-v","error","-i",str(path),"-vn"]
        if len(voices)>1:
            inputs="".join(f"[0:{index}]" for index in voices)
            cmd += ["-filter_complex",inputs+f"amix=inputs={len(voices)}:normalize=0:duration=longest[voice]","-map","[voice]"]
        elif voices:cmd += ["-map",f"0:{voices[0]}"]
        else:cmd += ["-map","0:a:0"]
        cmd += ["-ac","1","-ar","16000","-f","f32le","pipe:1"]
        run_command(cmd,max(90,total*2),cancelled,on_data=consume_audio)
        audio_events=activity_from_db(np.asarray(levels))
        for event in audio_events:event["confidence"]="voice_track" if voices else "mixed_audio_candidate"
        found += audio_events
    try:
        cache.parent.mkdir(parents=True,exist_ok=True)
        cache.write_text(json.dumps(found),encoding="utf-8")
    except OSError:pass
    if on_progress:on_progress(1,f"Rozpoznano {len(found)+len(events)} sygnałów akcji")
    return events+found


def select_events(events,options=None,kill_times=None):
    options=options or {}
    kills=[event["time"] for event in events if event["type"] in ("kill","visual")]
    if kill_times is not None:kills=kill_times
    near=options.get("assist_near_seconds")
    result=[]
    for event in events:
        kind=event["type"]
        if kind in ("kill","visual"):
            keep=options.get("kills",True)
        elif kind=="assist":
            keep=options.get("assists",True) and (near is None or any(abs(t-event["time"])<=float(near) for t in kills))
        else:keep=options.get("voice",True)
        if keep:result.append(event)
    return result


def ranges_for_events(events,total):
    windows=[]
    for event in events:
        stamp=event["time"]
        if event["type"] in ("mic","chat"):
            windows.append((stamp-5,event.get("end",stamp)+8))
        elif event["type"]=="audio":
            windows.append((stamp-2,event.get("end",stamp)+3))
        else:
            windows.append((stamp-3.5,stamp+3.5))
    merged=merge_ranges(windows,total)
    ranges=[(a,b-a,"Wybrane akcje i reakcje z kontekstem") for a,b in merged]
    return ranges


def highlight_ranges(path,info,on_progress=None,cancelled=None):
    events=discover_events(path,info,on_progress,cancelled)
    return ranges_for_events(events,float(info["format"]["duration"])),events
