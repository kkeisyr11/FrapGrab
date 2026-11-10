"""Deterministic highlight editing, normalized media, checked/atomic exports."""
import json
import os
import subprocess
import tempfile
import hashlib
import time
import logging
import re
from pathlib import Path
from .media import find_binary, encoder_args, probe, run_media, concat_entry, NO_WINDOW, run_command, MediaCancelled
from .config import CONFIG_DIR
from .hardware import decode_backends,decoder_args,decoder_device_args,decoder_device


def decoded_frame_count(path,gpu=True,cancelled=None):
    for backend in (decode_backends() if gpu else ["cpu"]):
        cmd=[find_binary("ffmpeg"),"-v","error","-progress","pipe:1"]
        cmd += decoder_args(backend,hardware_frames=True)
        cmd += ["-i",str(path),"-map","0:v:0","-an","-fps_mode","passthrough","-f","null","-"]
        try:
            data,_=run_command(cmd,cancelled=cancelled)
            counts=re.findall(rb"(?:^|\n)frame=(\d+)",data)
            if not counts:raise RuntimeError("Nie można policzyć odczytanych klatek.")
            return int(counts[-1])
        except MediaCancelled:raise
        except RuntimeError:
            if backend=="cpu":raise


def plan_ranges(path,total,duration=8,mode="preserve",gpu=True,on_progress=None,cancelled=None):
    """Never silently discard unclassified footage in the default mode."""
    if mode=="preserve":
        return [(0.0,total,"Pełny klip — bez pomijania materiału")]
    if mode=="markers":
        try:
            metadata=json.loads(Path(str(path)+".json").read_text(encoding="utf-8"))
            markers=sorted({float(t) for t in metadata.get("event_offsets",[]) if 0<=float(t)<=total})
        except (OSError,ValueError,TypeError):
            markers=[]
        if not markers:
            return [(0.0,total,"Brak wiarygodnych znaczników — zachowano całość")]
        windows=[]
        for stamp in markers:
            left,right=max(0,stamp-duration*.65),min(total,stamp+duration*.35)
            if windows and left<=windows[-1][1]:windows[-1][1]=max(windows[-1][1],right)
            else:windows.append([left,right])
        return [(a,b-a,"Wszystkie zapisane znaczniki akcji") for a,b in windows]
    if mode!="short":raise ValueError("Nieznany sposób wyboru materiału.")
    start,method=best_window(path,duration,total,gpu,on_progress,cancelled)
    return [(start,min(duration,total),method+" — skrót wymagający przeglądu")]


def video_filter(vertical=False):
    if vertical:
        return ("split=2[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,boxblur=20:2[blur];"
                "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
                "[blur][front]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=60,format=yuv420p")
    return "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=60,format=yuv420p"


def best_window(path, duration, total, gpu=True, on_progress=None, cancelled=None):
    """Prefer real trigger markers. For imported files use a bounded visual heuristic."""
    try:
        data = json.loads(Path(str(path) + ".json").read_text(encoding="utf-8"))
        markers = [float(t) for t in data.get("event_offsets", []) if 0 <= float(t) <= total]
        if markers:
            # Densest burst of recorded events, with context before the first action.
            anchor = max(markers, key=lambda t: sum(abs(m-t) <= duration*.45 for m in markers))
            return max(0, min(total-duration, anchor-duration*.65)), "Znacznik akcji"
    except (OSError, ValueError, TypeError):
        pass
    # v1 clips had no JSON markers, but the recorder's filename identifies an
    # event-triggered replay. Its ending contains the saved action; camera motion
    # elsewhere is weaker evidence and does not justify decoding the entire file.
    name = Path(path).stem.lower()
    if name.startswith("wardogs_") and any(tag in name for tag in ("_kill_","_assist_","_visual_","_death_","_revive_","_mic_")):
        if on_progress:on_progress(1,"Starszy klip z akcją · bez ponownego skanowania")
        return max(0,total-duration),"Końcówka starszego klipu ze zdarzeniem"
    import numpy as np
    stat = Path(path).stat()
    key = hashlib.sha256(f"motion-v2|{Path(path).resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{duration}".encode()).hexdigest()
    cache = Path(CONFIG_DIR)/"analysis_cache"/(key+".json")
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if on_progress:on_progress(1,"Gotowa analiza z pamięci podręcznej")
        return float(saved["start"]),saved["method"]
    except (OSError,ValueError,KeyError,TypeError):
        pass
    step = max(.5,total/90)
    scores = []
    for decoder in (decode_backends() if gpu else ["cpu"]):
        backend = decoder.upper()
        if on_progress:on_progress(0,f"Analiza obrazu · {backend}")
        cmd = [find_binary("ffmpeg"),"-hide_banner","-loglevel","error","-progress","pipe:2","-nostats"]
        cmd += decoder_args(decoder,hardware_frames=True)
        vf = f"fps={1/step}," + ("scale_cuda=160:90:format=nv12,hwdownload,format=nv12,format=gray" if decoder=="cuda" else "scale=160:90,format=gray")
        cmd += ["-i",str(path),"-an","-sn","-dn","-vf",vf,"-frames:v","90","-f","rawvideo","pipe:1"]
        try:
            data,_ = run_command(cmd,max(120,total*3),cancelled,
                (lambda t:on_progress(min(.99,t/total),f"Analiza obrazu · {backend}")) if on_progress else None,"stderr")
            logging.info("Motion analysis %s: %s, %d samples",path,backend,len(data)//14400)
            break
        except MediaCancelled:
            raise
        except RuntimeError:
            if decoder=="cpu":raise
            logging.exception("GPU analysis unavailable; trying sequential CPU decode")
    count = len(data)//14400
    frames = np.frombuffer(data[:count*14400],dtype=np.uint8).reshape(count,90,160)
    for i in range(1,count):
        motion = float(np.mean(np.abs(frames[i].astype(np.int16)-frames[i-1].astype(np.int16))))
        score = min(motion,28) if float(frames[i].mean())>12 else 0
        scores.append(((i+.5)*step,score))
    start,method = max(0,total-duration),"Końcówka nagrania"
    if scores:
        anchor = max(scores,key=lambda row:sum(s for t,s in scores if abs(t-row[0])<=duration/2))[0]
        start,method = max(0,min(total-duration,anchor-duration/2)),"Aktywność obrazu (heurystyka)"
    try:
        cache.parent.mkdir(parents=True,exist_ok=True)
        cache.write_text(json.dumps({"start":start,"method":method}),encoding="utf-8")
    except OSError:
        logging.exception("Could not cache analysis")
    if on_progress:on_progress(1,f"Analiza zakończona · {backend}")
    return start,method


def gpu_video_filter(vertical=False):
    if vertical:
        # GPU decode/resize; blur/overlay still run on the CPU at output resolution.
        return "fps=60,scale_cuda=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2:format=nv12,hwdownload,format=nv12,"+video_filter(True)
    return "fps=60,scale_cuda=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2:format=nv12,pad_cuda=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"


def join_transitions(parts, durations, temp, codec, cancelled=None, on_progress=None):
    """Bound concurrent decoders/filter buffers when a whole day is selected."""
    level = 0
    while len(parts) > 1:
        next_parts,next_durations = [],[]
        for offset in range(0,len(parts),8):
            group,times = parts[offset:offset+8],durations[offset:offset+8]
            if len(group) == 1:
                next_parts.append(group[0])
                next_durations.append(times[0])
                continue
            out = Path(temp)/f"transition_{level}_{offset}.mp4"
            cmd = [find_binary("ffmpeg"),"-hide_banner","-loglevel","error","-y","-filter_complex_threads","1"]
            if decode_backends(codec)[0]=="d3d11va":cmd += decoder_device_args(codec)
            for part in group:
                cmd += decoder_args(decode_backends(codec)[0],device=decoder_device(codec))
                cmd += ["-i",str(part)]
            filters = []
            video,audio,elapsed = "0:v","0:a",times[0]
            for i in range(1,len(group)):
                fade = min(.22,times[i-1]/4,times[i]/4)
                filters += [f"[{video}][{i}:v]xfade=transition=fade:duration={fade}:offset={max(0,elapsed-fade)}[v{i}]",
                            f"[{audio}][{i}:a]acrossfade=d={fade}:c1=tri:c2=tri[a{i}]"]
                video,audio = f"v{i}",f"a{i}"
                elapsed += times[i]-fade
            cmd += ["-filter_complex",";".join(filters),"-map",f"[{video}]","-map",f"[{audio}]",
                    *encoder_args(codec),"-pix_fmt","yuv420p","-c:a","aac",str(out)]
            def render(command):
                run_media(command,out,cancelled=cancelled,duration=elapsed,
                    on_progress=(lambda value:on_progress(value,f"Łączenie ujęć · grupa {offset//8+1}")) if on_progress else None)
            try:
                render(cmd)
            except MediaCancelled:raise
            except RuntimeError:
                if decode_backends(codec)[0]=="cpu":raise
                logging.exception("NVDEC transition inputs unavailable; retrying CPU decode")
                fallback=[]
                i=0
                while i<len(cmd):
                    if cmd[i] in ("-hwaccel","-hwaccel_device","-init_hw_device"):i+=2
                    else:fallback.append(cmd[i]);i+=1
                render(fallback)
            info = probe(out)
            duration = float(next(s for s in info["streams"] if s["codec_type"]=="video").get("duration",info["format"]["duration"]))
            next_parts.append(out)
            next_durations.append(duration)
            for part in group:
                if Path(part).resolve().parent == Path(temp).resolve():
                    Path(part).unlink(missing_ok=True)
        parts,durations = next_parts,next_durations
        level += 1
    return parts[0]


def plan_montage(clip_paths,clip_duration=8,codec="h264_nvenc",selection_mode="highlights",
                 transitions=False,event_options=None,on_progress=None,cancelled=None,ai_cuts=None):
    if not clip_paths:raise ValueError("Zaznacz przynajmniej jeden klip.")
    source_events=[];unclassified=[];tail_limited=[];source_warnings=[]
    deduplication={"aligned_sources":[],"removed_seconds":0}
    jobs=[]
    if selection_mode == "ai":
        if not ai_cuts or any(cut.path not in clip_paths for cut in ai_cuts):
            raise ValueError("Przygotuj plan AI dla zaznaczonych klipów.")
        clip_paths = list(dict.fromkeys(cut.path for cut in ai_cuts))
    infos = {}
    for source_index,path in enumerate(clip_paths):
        if cancelled and cancelled():
            raise RuntimeError("Anulowano montaż.")
        info = probe(path)
        total = float(info["format"].get("duration", 0))
        if total < .3:
            raise ValueError(f"Za krótki lub uszkodzony klip: {Path(path).name}")
        if selection_mode == "ai":
            infos[path] = (info, total)
            continue
        from .highlights import source_integrity
        warning=source_integrity(path,total)
        if warning:source_warnings.append(warning)
        progress_plan=(lambda value,msg:on_progress(.15*(source_index+value)/len(clip_paths),f"Źródło {source_index+1}/{len(clip_paths)} · {msg}")) if on_progress else None
        if selection_mode=="highlights":
            from .highlights import highlight_ranges
            ranges,events=highlight_ranges(path,info,progress_plan,cancelled)
            source_events.append({"source":str(path),"events":events})
            if any(event["type"] not in ("mic","chat","audio") and total-event["time"]<2 for event in events):
                tail_limited.append(str(path))
            if any(not any(a<=event["time"]<=a+d for a,d,_ in ranges) for event in events):
                raise RuntimeError("Plan montażu pomija wykryte zdarzenie; eksport zatrzymany.")
            if not ranges:
                unclassified.append({"source":str(path),"reason":"Brak potwierdzonych akcji"+"; nagranie nie ma audio" if not any(s["codec_type"]=="audio" for s in info["streams"]) else "Brak potwierdzonych akcji lub głośnych reakcji"})
        else:
            ranges=plan_ranges(path,total,min(float(clip_duration),total),selection_mode,codec!="libx264",progress_plan,cancelled)
        for start,duration,method in ranges:jobs.append((path,info,start,duration,method))
    if selection_mode == "ai":
        for cut in ai_cuts:
            info, total = infos[cut.path]
            if not 0 <= cut.start < cut.end <= total or cut.end - cut.start < .3:
                raise ValueError("Klip źródłowy zmienił się. Przygotuj plan ponownie.")
            jobs.append((cut.path, info, cut.start, cut.end - cut.start, "Plan AI"))
    if not jobs:
        raise RuntimeError("Nie rozpoznano wiarygodnych akcji. Nie utworzono losowego skrótu; nagrania źródłowe są zachowane.")
    raw_jobs=list(jobs)
    if selection_mode=="highlights":
        from .timeline import deduplicate_jobs
        jobs,deduplication=deduplicate_jobs(jobs,cancelled,
            (lambda message:on_progress(.15,message)) if on_progress else None)
    selected_events=source_events
    if selection_mode=="highlights" and event_options:
        from .highlights import select_events,ranges_for_events
        mapping=deduplication["source_timelines"]
        global_kills={}
        for source in source_events:
            point=mapping.get(source["source"])
            if point:
                global_kills.setdefault(point["group"],[]).extend(e["time"]+point["offset"] for e in source["events"] if e["type"] in ("kill","visual"))
        selected_events=[];selected_jobs=[]
        source_info={str(p):(p,info) for p,info,_,_,_ in raw_jobs}
        for source in source_events:
            key=source["source"];point=mapping.get(key)
            anchors=[t-point["offset"] for t in global_kills.get(point["group"],[])] if point else []
            events=select_events(source["events"],event_options,anchors)
            selected_events.append({"source":key,"events":events})
            if key not in source_info:continue
            p,info=source_info[key]
            for a,d,m in ranges_for_events(events,float(info["format"]["duration"])):
                selected_jobs.append((p,info,a,d,m))
        if not selected_jobs:raise ValueError("Brak zdarzeń pasujących do wybranych filtrów. Zmień wybór eliminacji, asyst lub reakcji.")
        jobs,new_dedup=deduplicate_jobs(selected_jobs,cancelled,timelines=mapping)
        new_dedup["aligned_sources"]=deduplication["aligned_sources"]
        deduplication=new_dedup
        tail_limited=[source["source"] for source in selected_events if source["source"] in tail_limited and any(
            e["type"] not in ("mic","chat","audio") and float(source_info[source["source"]][1]["format"]["duration"])-e["time"]<2 for e in source["events"])]
    times=[job[3] for job in jobs]
    if transitions and selection_mode!="preserve":
        while len(times)>1:
            next_times=[]
            for offset in range(0,len(times),8):
                group=times[offset:offset+8]
                next_times.append(sum(group)-sum(min(.22,group[i-1]/4,group[i]/4) for i in range(1,len(group))))
            times=next_times
    return {"jobs":jobs,"estimated_duration":sum(times),"detected_events":source_events,
            "selected_events":selected_events,"event_options":event_options or {},
            "unclassified_sources":unclassified,"tail_limited_sources":tail_limited,"deduplication":deduplication,
            "source_warnings":source_warnings}


class VideoEditor:
    @staticmethod
    def add_music(input_path,music_path,out_path,music_gain=.16,cancelled=None,on_progress=None):
        """Add the soundtrack after editing; copy all video packets unchanged."""
        if Path(input_path).resolve()==Path(out_path).resolve():
            raise ValueError("Zapisz wersję z muzyką pod inną nazwą.")
        info=probe(input_path)
        if not any(s["codec_type"]=="video" for s in info["streams"]):
            raise ValueError("Wybierz gotowy film MP4.")
        if not any(s["codec_type"]=="audio" for s in probe(music_path)["streams"]):
            raise ValueError("Wybrany podkład nie zawiera dźwięku.")
        duration=float(info["format"]["duration"])
        gain=max(0,min(1,float(music_gain)))
        partial=str(out_path)+".partial.mp4"
        Path(out_path).parent.mkdir(parents=True,exist_ok=True)
        cmd=[find_binary("ffmpeg"),"-v","error","-y","-i",str(input_path),"-stream_loop","-1","-i",str(music_path)]
        music=f"[1:a]volume={gain}[m];"
        mix="[0:a:0][m]amix=inputs=2:duration=first:normalize=0," if any(s["codec_type"]=="audio" for s in info["streams"]) else "[m]"
        filters=music+mix+f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.15,afade=t=out:st={max(0,duration-.35)}:d=0.35[a]"
        cmd += ["-filter_complex",filters,"-map","0:v:0","-map","[a]","-t",str(duration),
                "-c:v","copy","-c:a","aac","-ar","48000","-b:a","192k","-movflags","+faststart",partial]
        try:
            run_media(cmd,partial,cancelled=cancelled,duration=duration,on_progress=on_progress)
            os.replace(partial,out_path)
            try:report=json.loads(Path(str(input_path)+".edit.json").read_text(encoding="utf-8"))
            except (OSError,ValueError):report={}
            report.update({"music":str(music_path),"music_gain":gain,"music_source_movie":str(input_path),
                           "duration":float(probe(out_path)["format"]["duration"]),"video_copy":True})
            Path(str(out_path)+".edit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            return True
        finally:Path(partial).unlink(missing_ok=True)

    @staticmethod
    def trim_clip(input_path, start_sec, duration_sec, out_path, codec="h264_nvenc", vertical=False):
        if start_sec < 0 or duration_sec <= 0:
            raise ValueError("Początek musi być nieujemny, a długość większa od zera.")
        partial = str(out_path) + ".partial.mp4"
        try:
            run_media([find_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(start_sec), "-i", str(input_path), "-t", str(duration_sec),
                "-vf", video_filter(vertical), "-map", "0:v:0", "-map", "0:a?",
                *encoder_args(codec), "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", partial], partial)
            os.replace(partial, out_path)
            return True
        finally:
            Path(partial).unlink(missing_ok=True)

    @staticmethod
    def create_montage(clip_paths, out_path, clip_duration=8, bg_music_path="", codec="h264_nvenc",
                       vertical=False, transitions=False, on_progress=None, cancelled=None, selection_mode="highlights", event_options=None,music_gain=.16,ai_cuts=None):
        if not clip_paths:
            raise ValueError("Zaznacz przynajmniej jeden klip.")
        if bg_music_path and not Path(bg_music_path).is_file():
            raise ValueError("Nie znaleziono pliku muzyki.")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = []
        source_events=[]
        unclassified=[]
        tail_limited=[]
        deduplication={"aligned_sources":[],"removed_seconds":0}
        if selection_mode=="preserve":transitions=False
        partial = str(out_path) + ".partial.mp4"
        try:
            with tempfile.TemporaryDirectory(prefix="autoclip_montage_", dir=out_path.parent) as temp:
                parts, durations = [], []
                plan=plan_montage(clip_paths,clip_duration,codec,selection_mode,transitions,event_options,on_progress,cancelled,ai_cuts)
                jobs=plan["jobs"]
                source_events=plan["detected_events"]
                unclassified=plan["unclassified_sources"]
                tail_limited=plan["tail_limited_sources"]
                deduplication=plan["deduplication"]
                for i,(path,info,start,duration,method) in enumerate(jobs):
                    if cancelled and cancelled():raise MediaCancelled("Anulowano montaż.")
                    started = time.monotonic()
                    def progress(value,message):
                        if on_progress:on_progress(.15+.55*(i+value)/len(jobs),f"Ujęcie {i+1}/{len(jobs)} · {message}")
                    progress(0,method)
                    part = Path(temp) / f"part_{i:04}.mp4"
                    audio = any(s["codec_type"] == "audio" for s in info["streams"])
                    source_video=next(s for s in info["streams"] if s["codec_type"]=="video")
                    try:
                        numerator,denominator=source_video.get("r_frame_rate","0/1").split("/")
                        preserve_frames=selection_mode=="preserve" and abs(float(numerator)/float(denominator)-60)<.001
                    except (ValueError,ZeroDivisionError):preserve_frames=False
                    for decoder in decode_backends(codec):
                        backend = "NVDEC + CUDA + NVENC" if decoder=="cuda" else "D3D11VA + AMF · filtry CPU" if decoder=="d3d11va" and codec.endswith("_amf") else "D3D11VA + Quick Sync · filtry CPU" if decoder=="d3d11va" else "CPU → enkoder"
                        progress(0,f"Przygotowanie obrazu · {backend}")
                        cmd = [find_binary("ffmpeg"),"-hide_banner","-loglevel","error","-y"]
                        if decoder=="d3d11va":cmd += decoder_device_args(codec)
                        cmd += decoder_args(decoder,hardware_frames=True,device=decoder_device(codec) if decoder=="d3d11va" else None)
                        if selection_mode!="preserve":cmd += ["-ss",str(start)]
                        cmd += ["-i",str(path)]
                        if not audio:cmd += ["-f","lavfi","-i","anullsrc=r=48000:cl=stereo"]
                        vf=gpu_video_filter(vertical) if decoder=="cuda" else video_filter(vertical)
                        if preserve_frames:
                            vf="setpts=N/(60*TB),"+vf.replace("fps=60,","").replace(",fps=60","")
                        if selection_mode!="preserve":cmd += ["-t",str(duration)]
                        elif not audio:cmd += ["-shortest"]
                        cmd += ["-vf",vf,
                            "-map","0:v:0","-map","0:a:0" if audio else "1:a:0",*encoder_args(codec),
                            "-c:a","aac","-b:a","192k","-ar","48000","-ac","2",
                            "-af","aresample=async=1:first_pts=0"+(",apad" if selection_mode!="preserve" else ""),"-video_track_timescale","15360",str(part)]
                        if preserve_frames:cmd[-1:-1]=["-fps_mode","passthrough"]
                        try:
                            run_media(cmd,part,cancelled=cancelled,duration=duration,
                                on_progress=lambda value:progress(value,f"Przygotowanie obrazu · {backend}"))
                            break
                        except MediaCancelled:raise
                        except RuntimeError:
                            if decoder=="cpu":raise
                            logging.exception("GPU decode/scale failed; trying CPU filters with selected encoder")
                    part_info = probe(part)
                    video_info = next(s for s in part_info["streams"] if s["codec_type"] == "video")
                    if preserve_frames and source_video.get("nb_frames") and video_info.get("nb_frames"):
                        if int(video_info["nb_frames"])<int(source_video["nb_frames"]):
                            decoded=decoded_frame_count(path,codec!="libx264",cancelled)
                            if int(video_info["nb_frames"])<decoded:
                                raise RuntimeError(f"Eksport pomija klatki źródła {Path(path).name}; wynik nie został zatwierdzony.")
                    actual = float(video_info.get("duration", part_info["format"]["duration"]))
                    parts.append(part)
                    durations.append(actual)
                    report.append({"source": str(path), "start": round(start, 3), "duration": round(duration, 3), "selection": method,
                        "pipeline":backend,"prepare_seconds":round(time.monotonic()-started,3),
                        "source_frames":source_video.get("nb_frames"),"output_frames":video_info.get("nb_frames")})
                    if on_progress:
                        on_progress(.15+.55*(i+1)/len(jobs), f"Przygotowano {i+1}/{len(jobs)} ujęć")
                joined = Path(temp) / "joined.mp4"
                # Fade each normalized boundary using xfade/acrossfade. Hard cuts remain available.
                if transitions and len(parts) > 1:
                    joined = join_transitions(parts,durations,temp,codec,cancelled,
                        (lambda value,msg:on_progress(.7+.2*value,msg)) if on_progress else None)
                else:
                    manifest = Path(temp) / "concat.txt"
                    manifest.write_text("".join(concat_entry(p) for p in parts), encoding="utf-8")
                    run_media([find_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(manifest), "-c", "copy", str(joined)], joined,cancelled=cancelled)
                if cancelled and cancelled():
                    raise RuntimeError("Anulowano montaż.")
                if on_progress:
                    on_progress(.9, "Wyrównywanie dźwięku i zapis filmu…")
                final_duration = float(probe(joined)["format"]["duration"])
                fade_out = max(0, final_duration - .35)
                cmd = [find_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(joined)]
                if bg_music_path:
                    cmd += ["-stream_loop", "-1", "-i", str(bg_music_path), "-filter_complex",
                        f"[1:a]volume={max(0,min(1,float(music_gain)))}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.15,afade=t=out:st={fade_out}:d=0.35[a]",
                        "-map", "0:v:0", "-map", "[a]"]
                else:
                    cmd += ["-map", "0:v:0", "-map", "0:a:0", "-af",
                        f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.15,afade=t=out:st={fade_out}:d=0.35"]
                cmd += ["-t", str(final_duration), "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", partial]
                run_media(cmd,partial,cancelled=cancelled,duration=final_duration,
                    on_progress=(lambda value:on_progress(.9+.1*value,"Wyrównywanie dźwięku i zapis filmu…")) if on_progress else None)
                if selection_mode=="preserve" and all(item["output_frames"] is not None for item in report):
                    final_video=next(s for s in probe(partial)["streams"] if s["codec_type"]=="video")
                    expected=sum(int(item["output_frames"]) for item in report)
                    if final_video.get("nb_frames") and int(final_video["nb_frames"])<expected:
                        raise RuntimeError("Łączenie utraciło klatki; film nie został zatwierdzony.")
                os.replace(partial, out_path)
                Path(str(out_path) + ".edit.json").write_text(json.dumps({"clips": report, "vertical": vertical,
                    "transitions": transitions, "music": bg_music_path,"selection_mode":selection_mode,
                    "detected_events":source_events,"unclassified_sources":unclassified,
                    "deduplication":deduplication,"tail_limited_sources":tail_limited,"source_warnings":plan['source_warnings'],
                    "selected_events":plan["selected_events"],"event_options":plan["event_options"],
                    "estimated_duration":plan["estimated_duration"],"duration":final_duration,"music_gain":music_gain}, ensure_ascii=False, indent=2), encoding="utf-8")
                if on_progress:
                    on_progress(1, "Film gotowy")
                return True
        finally:
            Path(partial).unlink(missing_ok=True)
