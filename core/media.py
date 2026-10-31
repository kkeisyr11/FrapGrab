"""Shared FFmpeg options and portable binary discovery."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import re
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_active = set()
_active_lock = threading.Lock()
_cancelled = threading.Event()


class MediaCancelled(RuntimeError):
    pass


def cancel_media_jobs():
    _cancelled.set()
    with _active_lock:
        for proc in list(_active):
            if proc.poll() is None:
                proc.kill()


def find_binary(name):
    roots = [Path(sys.executable).parent] if getattr(sys, "frozen", False) else [Path(__file__).resolve().parents[1]]
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS))
    roots += [roots[0] / "tools", roots[0] / "_internal", roots[0] / "dist_release" / "AutoClipWarDogs"]
    for root in roots:
        path = root / (name + (".exe" if os.name == "nt" else ""))
        if path.is_file():
            return str(path)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"Brak {name}. Uruchom Start.ps1, aby przygotować aplikację.")


def encoder_args(codec, quality="High", live=False):
    bitrate = {"Medium": "15M", "High": "25M", "Ultra": "50M"}.get(quality, "25M")
    args = ["-c:v", codec]
    if codec.endswith("_nvenc"):
        args += ["-preset", "p2" if live else "p4", "-tune", "ll" if live else "hq"]
    elif codec.endswith("_amf"):
        args += ["-quality", "speed" if live else "balanced","-preanalysis","0"]
        if live:args += ["-usage","lowlatency","-rc","cbr"]
    elif codec.endswith("_qsv"):
        args += ["-preset", "veryfast" if live else "medium"]
    else:
        args += ["-preset", "ultrafast" if live else "fast"]
    return args + ["-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate, "-bf", "0"]


def probe(path):
    result = subprocess.run([find_binary("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                             "-of", "json", str(path)], capture_output=True, text=True,
                            creationflags=NO_WINDOW, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:])
    return json.loads(result.stdout)


def concat_entry(path):
    return "file '" + str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''") + "'\n"


def run_command(cmd, timeout=1800, cancelled=None, on_time=None, progress_stream="stdout",on_data=None):
    """Cancellable FFmpeg operation with live timestamps and owned child processes."""
    if _cancelled.is_set():
        raise MediaCancelled("Anulowano eksport.")
    with _active_lock:
        if _cancelled.is_set():
            raise MediaCancelled("Anulowano eksport.")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        _active.add(proc)
    deadline = time.monotonic()+timeout
    chunks = {"stdout":[],"stderr":[]}
    reader_errors=[]
    def drain(name,pipe):
        try:
            while True:
                data = pipe.readline() if on_time and progress_stream == name else pipe.read(65536)
                if not data:break
                if name=="stdout" and on_data:on_data(data)
                else:chunks[name].append(data)
                if on_time and progress_stream == name:
                    match = re.match(rb"out_time_us=(\d+)",data)
                    if match:on_time(int(match.group(1))/1_000_000)
        except Exception as exc:
            reader_errors.append(exc)
            if proc.poll() is None:proc.kill()
    readers = [threading.Thread(target=drain,args=(name,pipe),daemon=True)
               for name,pipe in (("stdout",proc.stdout),("stderr",proc.stderr))]
    for reader in readers:reader.start()
    try:
        while True:
            if _cancelled.is_set() or cancelled and cancelled():
                proc.kill()
                proc.wait()
                raise MediaCancelled("Anulowano eksport.")
            if time.monotonic()>deadline:
                raise subprocess.TimeoutExpired(cmd,timeout)
            try:
                proc.wait(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                pass
        for reader in readers:reader.join()
        stdout,stderr = b"".join(chunks["stdout"]),b"".join(chunks["stderr"])
        if reader_errors:raise reader_errors[0]
        if proc.returncode:
            raise RuntimeError(stderr.decode("utf-8", errors="replace")[-1800:])
        return stdout,stderr
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError("Eksport przekroczył limit czasu.")
    finally:
        for reader in readers:reader.join(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
        with _active_lock:
            _active.discard(proc)


def run_media(cmd, out_path, timeout=1800, cancelled=None, on_progress=None, duration=None):
    if on_progress:
        cmd = [cmd[0],"-progress","pipe:1","-nostats",*cmd[1:]]
    run_command(cmd,timeout,cancelled,
        (lambda seconds:on_progress(min(.99,seconds/duration))) if on_progress and duration else None)
    if on_progress:
        on_progress(1)
    info = probe(out_path)
    if not any(s["codec_type"] == "video" for s in info["streams"]):
        raise RuntimeError("Plik wynikowy nie zawiera obrazu.")
    return True
