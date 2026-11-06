"""Replay from finalized segments: unique sessions, no wrap, no open-file exports."""
import csv
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from .config import load_config
from .media import find_binary, encoder_args, concat_entry, run_media, NO_WINDOW
from .monitors import output_geometry

BUFFER_TEMP_DIR = os.path.join(tempfile.gettempdir(), "FrapGrab_Buffer")


def get_ffmpeg_path():
    return find_binary("ffmpeg")


class ReplayBuffer:
    SEGMENT_SECONDS = 2

    def __init__(self, on_clip_saved_callback=None, on_status=None):
        self.on_clip_saved_callback = on_clip_saved_callback
        self.on_status = on_status
        self.lock = threading.RLock()
        self.export_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.is_recording = False
        self.state = "idle"
        self.error = ""
        self.proc = None
        self.audio = None
        self.audio_inputs=[]
        self.audio_sources=[]
        self.temp_dir = None
        self.config = load_config()
        self.capture_method = ""
        self._thread = None
        self._origin = None

    def _status(self, state, message=""):
        if state!="warning":self.state = state
        if state == "error":
            self.error = message
        if self.on_status:
            self.on_status(state, message)
        if message:logging.info("Capture %s: %s",state,message)

    @property
    def available_seconds(self):
        with self.lock:
            rows = self._read_segments()
            return min(float(self.config["buffer_seconds"]), sum(b-a for _, a, b in rows))

    def _read_segments(self):
        rows = []
        if not self.temp_dir:
            return rows
        try:
            with open(Path(self.temp_dir) / "segments.csv", newline="", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) != 3:
                        continue
                    try:
                        path = Path(self.temp_dir) / Path(row[0]).name
                        start, end = float(row[1]), float(row[2])
                        if path.is_file() and math.isfinite(start) and math.isfinite(end) and end > start:
                            rows.append((path, start, end))
                    except (OSError, ValueError):
                        continue
        except OSError:
            pass
        return rows

    def _command(self, method):
        fps, codec = self.config["capture_fps"], self.config["video_codec"]
        output = self.config.get("capture_output", 0)
        cmd = [get_ffmpeg_path(), "-hide_banner", "-loglevel", "warning", "-y"]
        if method.startswith("DXGI"):
            source = f"ddagrab=output_idx={output}:framerate={fps}:draw_mouse=0"
            if method=="DXGI-copy" or not codec.endswith(("_nvenc","_amf")):
                source += ",hwdownload,format=bgra"
            cmd += ["-thread_queue_size", "128", "-f", "lavfi", "-i", source]
        else:
            monitor = output_geometry(output)
            cmd += ["-thread_queue_size", "128", "-f", "gdigrab", "-framerate", str(fps),
                    "-offset_x", str(monitor["left"]), "-offset_y", str(monitor["top"]),
                    "-video_size", f'{monitor["width"]}x{monitor["height"]}', "-draw_mouse", "0", "-i", "desktop"]
        for audio in self.audio_inputs:
            cmd += ["-thread_queue_size", "512", "-probesize", "32", "-analyzeduration", "0",
                    "-f", "s16le", "-ar", str(audio.rate), "-ac", str(audio.channels), "-i",audio.input_url]
        cmd += ["-map", "0:v:0"]
        if self.audio_inputs:
            filters=[]
            voice_tracks=[]
            for i in range(len(self.audio_inputs)):
                converted=f"[{i+1}:a]aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo"
                if self.audio_inputs[i].role in ("microphone","chat"):
                    filters.append(converted+f",asplit=2[a{i}][voice{i}]")
                    voice_tracks.append((i,self.audio_inputs[i].role))
                else:filters.append(converted+f"[a{i}]")
            channels="".join(f"[a{i}]" for i in range(len(self.audio_inputs)))
            filters.append(channels+f"amix=inputs={len(self.audio_inputs)}:duration=longest:normalize=0,alimiter=limit=0.95:level=0[aout]")
            cmd += ["-filter_complex",";".join(filters),"-map","[aout]","-metadata:s:a:0","title=Frap Grab mix","-metadata:s:a:0","handler_name=Frap Grab mix","-disposition:a:0","default"]
            for track,(i,role) in enumerate(voice_tracks,1):
                cmd += ["-map",f"[voice{i}]",f"-metadata:s:a:{track}",f"title=Frap Grab {role}",f"-metadata:s:a:{track}",f"handler_name=Frap Grab {role}",f"-disposition:a:{track}","0"]
            cmd += ["-c:a","aac","-b:a","192k","-ac","2","-ar","48000"]
        cmd += encoder_args(codec, self.config["video_quality"], live=True)
        cmd += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
        if method != "DXGI" or not codec.endswith(("_nvenc","_amf")):
            cmd += ["-pix_fmt", "yuv420p"]
        cmd += ["-g", str(fps * self.SEGMENT_SECONDS), "-f", "segment", "-segment_time", str(self.SEGMENT_SECONDS),
                "-segment_list", str(Path(self.temp_dir) / "segments.csv"), "-segment_list_type", "csv",
                "-segment_list_size", "2048", "-reset_timestamps", "1", str(Path(self.temp_dir) / "buf_%08d.mp4")]
        return cmd

    def start_rolling_buffer(self):
        with self.export_lock, self.lock:
            if self._thread and self._thread.is_alive():
                return
            if self.temp_dir:
                self._remove_session()
            self.config = load_config()
            self.stop_event.clear()
            self.error, self._origin = "", None
            os.makedirs(BUFFER_TEMP_DIR, exist_ok=True)
            self.temp_dir = tempfile.mkdtemp(prefix="session_", dir=BUFFER_TEMP_DIR)
            self.is_recording = True
            self._status("starting", "Uruchamianie przechwytywania…")
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def _worker(self):
        from .audio_capture import audio_thread
        try:
            with audio_thread():self._capture_worker()
        except Exception as exc:
            logging.exception("Replay audio initialization failed")
            self.is_recording=False
            if not self.stop_event.is_set():self._status("error",str(exc))

    def _capture_worker(self):
        try:
            methods=("DXGI","DXGI-copy","GDI") if self.config["video_codec"].endswith(("_nvenc","_amf")) else ("DXGI-copy","GDI")
            for method in methods:
                if self.stop_event.is_set():
                    break
                from .audio_capture import DesktopAudio
                self.audio_inputs=[]
                for role,enabled in [("system",self.config["desktop_audio"]),("microphone",self.config["record_microphone"]),("chat",self.config["record_chat"])]:
                    if not enabled:continue
                    try:
                        endpoint=DesktopAudio(role,device_name=self.config["chat_device"],exclude_default=self.config["desktop_audio"]) if role=="chat" else DesktopAudio(role)
                        self.audio_inputs.append(endpoint)
                    except LookupError:
                        continue
                    except Exception as exc:
                        if role=="system":raise
                        self._status("warning",f"Nie można nagrywać źródła {role}: {exc}")
                self.audio=self.audio_inputs[0] if self.audio_inputs else None
                self.audio_sources=[{"role":a.role,"name":a.device["name"],"rate":a.rate,"channels":a.channels} for a in self.audio_inputs]
                self.capture_method = method
                with open(Path(self.temp_dir) / "capture.log", "ab") as log:
                    self.proc = subprocess.Popen(self._command(method), stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=log, creationflags=NO_WINDOW, bufsize=0)
                    for audio in self.audio_inputs:audio.start()
                    started, ready = time.monotonic(), False
                    last_progress,last_end=started,-1
                    while not self.stop_event.wait(0.2):
                        if self.proc.poll() is not None:
                            break
                        with self.lock:
                            rows = self._read_segments()
                            if rows:
                                if rows[-1][2]>last_end:
                                    last_progress,last_end=time.monotonic(),rows[-1][2]
                                if self._origin is None:
                                    self._origin = time.monotonic() - rows[-1][2]
                                if not ready:
                                    self._status("recording", f"{method} · {self.config['video_codec']} · {self.config['capture_fps']} FPS")
                                    ready = True
                                keep = max(self.config["buffer_seconds"], self.config["clip_before_kill"] + self.config["clip_after_kill"]) + 20
                                for path, a, b in rows:
                                    if b < rows[-1][2] - keep:
                                        path.unlink(missing_ok=True)
                        if not ready and time.monotonic() - started > 18:
                            break
                        if ready and time.monotonic()-last_progress>12:
                            raise RuntimeError("Bufor nie otrzymuje nowych klatek. Uruchom czuwanie ponownie.")
                    if self.stop_event.is_set():
                        break
                    self._close_process()
                    if method.startswith("DXGI") and not ready:
                        for path in Path(self.temp_dir).glob("buf_*.mp4"):
                            path.unlink(missing_ok=True)
                        (Path(self.temp_dir) / "segments.csv").unlink(missing_ok=True)
                        self._status("starting", "Próba DXGI z kopiowaniem klatek…" if method=="DXGI" else "DXGI niedostępne. Próba GDI…")
                        continue
                    log_text = (Path(self.temp_dir) / "capture.log").read_text(errors="replace")[-900:]
                    raise RuntimeError(f"Silnik nagrywania zatrzymał się. {log_text}")
        except Exception as exc:
            if not self.stop_event.is_set():
                logging.exception("Replay capture failed")
                self._status("error", str(exc))
        finally:
            self._close_process()
            self.is_recording = False
            if self.state != "error":
                self._status("idle", "Nagrywanie zatrzymane")

    def _close_process(self):
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                proc.wait(timeout=4)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                proc.kill()
                proc.wait(timeout=4)
        self.proc = None
        for audio in self.audio_inputs:audio.close()
        self.audio_inputs=[]
        self.audio=None
        if proc and proc.stdin and not proc.stdin.closed:
            proc.stdin.close()

    def stop_rolling_buffer(self):
        self.stop_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=7)
        self.is_recording = False

    def export_last_buffer(self, reason="Ręczny zapis", extra="", duration=0.0, end_at=None, event_times=None,event_types=None):
        with self.export_lock:
            config = load_config()
            target = float(duration or config["buffer_seconds"])
            with self.lock:
                origin = self._origin
            if origin is None:
                raise RuntimeError("Bufor jeszcze się napełnia. Poczekaj na pierwsze 2 sekundy nagrania.")
            requested_end = max(0.0, (time.monotonic() if end_at is None else end_at) - origin)
            start = max(0, requested_end - target)
            end = requested_end
            deadline = time.monotonic() + max(15, end - (time.monotonic() - origin) + 10)
            while True:
                with self.lock:
                    rows = self._read_segments()
                if rows and rows[-1][2] >= end:
                    break
                if not self.is_recording or time.monotonic() > deadline:
                    if not rows:
                        raise RuntimeError("Brak ukończonych segmentów nagrania.")
                    end = min(end, rows[-1][2])
                    break
                time.sleep(0.15)
            if end<=start:
                raise RuntimeError("Żądana akcja jest poza zapisanym buforem. Nie utworzono klipu ze starszego fragmentu.")
            save_dir = Path(config["save_folder"]) / datetime.now().strftime("%Y-%m-%d")
            save_dir.mkdir(parents=True, exist_ok=True)
            clean = "".join(c for c in reason if c.isalnum() or c in "_-")[:28] or "clip"
            out = save_dir / f"FrapGrab_{datetime.now():%Y-%m-%d_%H-%M-%S_%f}_{clean}.mp4"
            with tempfile.TemporaryDirectory(prefix="export_", dir=BUFFER_TEMP_DIR) as temp:
                with self.lock:
                    rows = [r for r in self._read_segments() if r[2] > start and r[1] < end]
                    if not rows:
                        raise RuntimeError("Ten fragment nie jest już dostępny w buforze.")
                    if any(right[1]-left[2]>.1 for left,right in zip(rows,rows[1:])):
                        raise RuntimeError("W nagraniu występuje przerwa. Nie można poprawnie umieścić znaczników akcji.")
                    copies = []
                    for i, (path, a, b) in enumerate(rows):
                        copy = Path(temp) / f"part_{i:04}.mp4"
                        shutil.copy2(path, copy)
                        copies.append(copy)
                manifest = Path(temp) / "concat.txt"
                manifest.write_text("".join(concat_entry(p) for p in copies), encoding="utf-8")
                # Keyframe alignment can add up to one 2s segment before the requested start.
                actual_start = rows[0][1]
                partial = out.with_suffix(".partial.mp4")
                try:
                    run_media([get_ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(manifest), "-t", str(end - actual_start), "-map", "0:v:0", "-map", "0:a?",
                        "-c", "copy", "-movflags", "+faststart", str(partial)], partial, timeout=120)
                    os.replace(partial, out)
                    events=[];missing=[]
                    for i,stamp in enumerate(event_times or []):
                        event={"time":stamp-origin-actual_start,"type":event_types[i] if event_types and i<len(event_types) else ("mic" if reason=="mic" else "kill")}
                        (events if 0<=event["time"]<=end-actual_start else missing).append(event)
                    metadata = {"reason": reason, "details": extra,
                        "event_offsets": [event["time"] for event in events],"events":events,"missing_events":missing,
                        "truncated":end<requested_end-.1,"requested_end":requested_end,
                        "recording":{"session":rows[0][0].parent.name,"start":actual_start,"end":end},
                        "capture": self.capture_method,"audio_sources":self.audio_sources, "created": datetime.now().isoformat()}
                    Path(str(out) + ".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                    logging.info("Replay exported: duration=%.3fs events=%d missing=%d truncated=%s",end-actual_start,len(events),len(missing),metadata["truncated"])
                finally:
                    partial.unlink(missing_ok=True)
            if self.on_clip_saved_callback:
                self.on_clip_saved_callback(str(out), reason, extra)
            if metadata["missing_events"] or metadata["truncated"]:
                self._status("warning","Powtórka jest niepełna: przechwytywanie zakończyło się przed końcem żądanego fragmentu. Sprawdź zapisany klip.")
            return str(out)

    def cleanup(self):
        self.stop_rolling_buffer()
        with self.export_lock:
            if self.temp_dir:
                self._remove_session()

    def _remove_session(self):
        path = Path(self.temp_dir).resolve()
        root = Path(BUFFER_TEMP_DIR).resolve()
        if not path.is_relative_to(root) or path.parent != root or not path.name.startswith("session_"):
            raise RuntimeError("Odmowa usunięcia katalogu poza buforem sesji.")
        shutil.rmtree(path, ignore_errors=True)
