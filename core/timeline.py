"""Align overlapping replays using recording coordinates or verified moving frames."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from .config import CONFIG_DIR
from .media import find_binary,run_command,MediaCancelled
from .hardware import decode_backends,decoder_args


def metadata(path):
    try:return json.loads(Path(str(path)+".json").read_text(encoding="utf-8"))
    except (OSError,ValueError):return {}


def fingerprints(path,total,cancelled=None):
    path=Path(path);stat=path.stat()
    key=hashlib.sha256(f"timeline-v1|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()
    cache=Path(CONFIG_DIR)/"highlight_cache"/(key+".npz")
    try:
        with np.load(cache) as saved:return saved["frames"]
    except (OSError,ValueError,KeyError):pass
    for backend in decode_backends():
        cmd=[find_binary("ffmpeg"),"-v","error"]
        cmd += decoder_args(backend,hardware_frames=True)
        vf="fps=2,"+("scale_cuda=96:54,hwdownload,format=nv12," if backend=="cuda" else "scale=96:54,")+"format=gray"
        cmd += ["-i",str(path),"-an","-sn","-dn","-vf",vf,"-f","rawvideo","pipe:1"]
        frames=[];pending=bytearray()
        def consume(chunk):
            pending.extend(chunk)
            while len(pending)>=96*54:
                frames.append(np.frombuffer(bytes(pending[:96*54]),np.uint8).reshape(54,96))
                del pending[:96*54]
        try:
            run_command(cmd,max(90,total*2),cancelled,on_data=consume)
            break
        except MediaCancelled:raise
        except RuntimeError:
            if backend=="cpu":raise
    result=np.asarray(frames,np.uint8)
    try:
        cache.parent.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(cache,frames=result)
    except OSError:pass
    return result


def visual_offset(a,b):
    """Return B's start relative to A. Require several distinct matching frames."""
    if len(a)<4 or len(b)<4:return None
    aa=np.asarray([cv2.resize(f,(24,14)).ravel() for f in a],np.float32)
    bb=np.asarray([cv2.resize(f,(24,14)).ravel() for f in b],np.float32)
    candidates=[]
    # Coherent nearest-frame matches tolerate up to half a sampling interval.
    for j,frame in enumerate(bb):
        errors=np.mean(np.abs(aa-frame),axis=1)
        i=int(np.argmin(errors))
        if errors[i]<6 and np.mean(np.abs(a[i].astype(np.float32)-b[j]))<9:
            candidates.append((i-j,i,j))
    for shift in sorted({r[0] for r in candidates},key=lambda d:-sum(abs(r[0]-d)<=0 for r in candidates)):
        matches=[r for r in candidates if r[0]==shift]
        if len(matches)<4 or max(r[2] for r in matches)-min(r[2] for r in matches)<3:continue
        chosen=aa[[r[1] for r in matches]]
        # A static menu/sky/idle screen is not proof of overlapping recordings.
        if float(np.mean(chosen.max(axis=0)-chosen.min(axis=0)))<8:continue
        return {"offset":shift*.5,"matching_frames":len(matches),"method":"moving_frame_match"}
    return None


def possible_overlap(a,b,ta,tb):
    try:
        ea=datetime.fromisoformat(metadata(a)["created"]).timestamp()
        eb=datetime.fromisoformat(metadata(b)["created"]).timestamp()
        return ea-ta-5<eb+5 and eb-tb-5<ea+5
    except (KeyError,TypeError,ValueError):return True


def deduplicate_jobs(jobs,cancelled=None,on_progress=None,timelines=None):
    """Union selected action windows in aligned source time, then render each once."""
    sources={str(p):(p,info) for p,info,_,_,_ in jobs}
    keys=list(sources);groups=[];alignments=[];samples={}
    if timelines:
        by_group={}
        for key in keys:
            point=timelines[key]
            by_group.setdefault(point["group"],{})[key]=point["offset"]
        groups=list(by_group.values())
    for n,key in enumerate(keys):
        if timelines:break
        if cancelled and cancelled():raise MediaCancelled("Anulowano montaż.")
        p,info=sources[key];total=float(info["format"]["duration"])
        links=[]
        for group in groups:
            for other,origin in group.items():
                op,oi=sources[other];ot=float(oi["format"]["duration"])
                first,second=metadata(op).get("recording",{}),metadata(p).get("recording",{})
                match=None
                if first.get("session") and first.get("session")==second.get("session"):
                    match={"offset":float(second["start"])-float(first["start"]),"method":"recording_coordinates"}
                elif possible_overlap(op,p,ot,total):
                    if on_progress:on_progress(f"Usuwanie powtórek · źródło {n+1}/{len(keys)}")
                    for path,duration in ((other,ot),(key,total)):
                        if path not in samples:samples[path]=fingerprints(sources[path][0],duration,cancelled)
                    match=visual_offset(samples[other],samples[key])
                if match:
                    links.append((group,origin+match["offset"]))
                    alignments.append({"source":key,"relative_to":other,**match})
                    break
        if links:
            base,position=links[0]
            base[key]=position
            for group,other_position in links[1:]:
                base.update({name:stamp+position-other_position for name,stamp in group.items()})
                groups.remove(group)
        else:groups.append({key:0.0})
    result=[]
    for group in groups:
        windows=sorted((group[str(p)]+start,group[str(p)]+start+duration,method)
                       for p,info,start,duration,method in jobs if str(p) in group)
        merged=[]
        for a,b,method in windows:
            if merged and a<=merged[-1][1]+.05:merged[-1][1]=max(merged[-1][1],b)
            else:merged.append([a,b,method])
        for a,b,method in merged:
            cursor=a
            while cursor<b-.001:
                available=[key for key,origin in group.items() if origin<=cursor+.001 and origin+float(sources[key][1]["format"]["duration"])>cursor+.001]
                if not available:raise RuntimeError("Nie można odtworzyć ciągłości nakładających się klipów.")
                key=max(available,key=lambda k:group[k]+float(sources[k][1]["format"]["duration"]))
                end=min(b,group[key]+float(sources[key][1]["format"]["duration"]))
                p,info=sources[key]
                result.append((p,info,max(0,cursor-group[key]),end-cursor,method))
                cursor=end
    mapping={key:{"group":i,"offset":stamp} for i,group in enumerate(groups) for key,stamp in group.items()}
    return result,{"aligned_sources":alignments,"source_timelines":mapping,
                   "removed_seconds":round(sum(j[3] for j in jobs)-sum(j[3] for j in result),3)}
