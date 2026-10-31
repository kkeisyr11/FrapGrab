"""GPU family presets, real encoder validation and driver-aware local caching."""
import hashlib
import json
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from .media import find_binary,NO_WINDOW,encoder_args
from .config import CONFIG_DIR

CATALOG=Path(__file__).resolve().parents[1]/"assets/gpu_profiles.json"
ENCODER_LABELS={"av1_nvenc":"NVIDIA · AV1","hevc_nvenc":"NVIDIA · HEVC","h264_nvenc":"NVIDIA · H.264",
    "av1_amf":"AMD · AV1","hevc_amf":"AMD · HEVC","h264_amf":"AMD · H.264",
    "av1_qsv":"Intel · AV1","hevc_qsv":"Intel · HEVC","h264_qsv":"Intel · H.264","libx264":"Procesor · H.264"}
_cached=None
_lock=threading.RLock()


def get_gpu_inventory():
    try:
        raw=subprocess.check_output(["powershell","-NoProfile","-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,PNPDeviceID | ConvertTo-Json -Compress"],
            text=True,stderr=subprocess.DEVNULL,creationflags=NO_WINDOW,timeout=12)
        data=json.loads(raw)
        return data if isinstance(data,list) else [data] if isinstance(data,dict) else []
    except (OSError,ValueError,subprocess.SubprocessError):return []


def get_installed_gpus():
    return [g["Name"] for g in get_gpu_inventory() if g.get("Name")]


def get_ffmpeg_encoders():
    try:
        result=subprocess.check_output([find_binary("ffmpeg"),"-encoders"],text=True,
            stderr=subprocess.DEVNULL,creationflags=NO_WINDOW,timeout=10)
        return set(re.findall(r"^\s*V\S*\s+(\w+)",result,re.MULTILINE))
    except (OSError,subprocess.SubprocessError):return set()


def model_profile(name):
    for profile in json.loads(CATALOG.read_text(encoding="utf-8"))["profiles"]:
        if re.search(profile["pattern"],name,re.IGNORECASE):return {**profile,"gpu":name}
    return {"id":"unknown","label":"Nierozpoznana karta","gpu":name,"vendor":"unknown",
            "priority":0,"codecs":[],"fps":30,"quality":"Medium"}


def encoder_smoke_test(codec):
    """A successful encode proves initialization, not gaming FPS or sustained throughput."""
    try:
        with tempfile.TemporaryDirectory(prefix="autoclip_gpu_test_") as folder:
            out=Path(folder)/"probe.mp4"
            cmd=[find_binary("ffmpeg"),"-v","error","-y","-f","lavfi","-i",
                 "testsrc2=size=1280x720:rate=60","-frames:v","6","-an","-pix_fmt","yuv420p",
                 *encoder_args(codec,"High",live=True),str(out)]
            result=subprocess.run(cmd,capture_output=True,timeout=8,creationflags=NO_WINDOW)
            if result.returncode or not out.is_file() or out.stat().st_size<500:
                return {"ok":False,"reason":result.stderr.decode(errors="replace")[-500:] or "Pusty wynik testu"}
            verify=subprocess.run([find_binary("ffmpeg"),"-v","error","-xerror","-i",str(out),"-f","null","-"],
                capture_output=True,timeout=8,creationflags=NO_WINDOW)
            return {"ok":verify.returncode==0,"reason":verify.stderr.decode(errors="replace")[-500:]}
    except (OSError,subprocess.SubprocessError) as exc:return {"ok":False,"reason":str(exc)}


def select_profile(inventory,encoders,checks):
    profiles=sorted([model_profile(g["Name"]) for g in inventory if g.get("Name")],key=lambda p:-p["priority"])
    options=[];selected=None
    for profile in profiles:
        for codec in profile["codecs"]:
            if codec in encoders and checks.get(codec,{}).get("ok"):
                if codec not in {code for _,code in options}:options.append((ENCODER_LABELS[codec],codec))
                if selected is None:selected={**profile,"codec":codec}
    if "libx264" in encoders and checks.get("libx264",{}).get("ok"):
        options.append((ENCODER_LABELS["libx264"],"libx264"))
    if selected is None:
        selected={"id":"cpu","label":"Awaryjny zapis na procesorze","gpu":"CPU","codec":"libx264",
                  "vendor":"cpu","fps":30,"quality":"Medium","priority":0}
    return {"gpus":[g["Name"] for g in inventory if g.get("Name")],"inventory":inventory,
            "supported_options":options,"default_encoder":selected["codec"],"selected_profile":selected,
            "auto_settings":{"video_codec":selected["codec"],"capture_fps":selected["fps"],"video_quality":selected["quality"]},
            "encoder_checks":checks,"ffmpeg_available":bool(encoders),"hardware_encoding":selected["codec"]!="libx264"}


def detect_hardware_profile(refresh=False):
    global _cached
    with _lock:
        if _cached is not None and not refresh:return _cached
        inventory=get_gpu_inventory();encoders=get_ffmpeg_encoders()
        ff=Path(find_binary("ffmpeg"));fp=Path(find_binary("ffprobe"))
        signature=hashlib.sha256(json.dumps({"schema":2,"gpus":inventory,
            "ffmpeg":[str(ff),ff.stat().st_size,ff.stat().st_mtime_ns],
            "ffprobe":[str(fp),fp.stat().st_size,fp.stat().st_mtime_ns],
            "catalog":CATALOG.read_text(encoding="utf-8")},sort_keys=True).encode()).hexdigest()
        cache=Path(CONFIG_DIR)/"gpu_checks"/(signature+".json")
        checks={}
        if not refresh:
            try:
                data=json.loads(cache.read_text(encoding="utf-8"))
                if time.time()-data["created"]<7*86400:checks=data["checks"]
            except (OSError,ValueError,KeyError,TypeError):pass
        wanted={codec for gpu in inventory if gpu.get("Name") for codec in model_profile(gpu["Name"])["codecs"] if codec in encoders}
        if "libx264" in encoders:wanted.add("libx264")
        for codec in sorted(wanted):
            if codec not in checks:checks[codec]=encoder_smoke_test(codec)
        try:
            cache.parent.mkdir(parents=True,exist_ok=True)
            cache.write_text(json.dumps({"created":time.time(),"checks":checks}),encoding="utf-8")
        except OSError:pass
        _cached={**select_profile(inventory,encoders,checks),"signature":signature}
        return _cached


def apply_hardware_profile(config,hardware,monitor_height=None):
    result=config.copy()
    supported={code for _,code in hardware["supported_options"]}
    if result.get("auto_gpu_settings",True):
        result.update(hardware["auto_settings"])
        if hardware["hardware_encoding"] and monitor_height and monitor_height>=2160:
            result["video_quality"]="Ultra"
    elif result.get("video_codec") not in supported:
        result["video_codec"]=hardware["default_encoder"]
    return result


def decode_backends(codec=None):
    """Choose a vendor route; keep CPU as an explicit last fallback."""
    if codec=="libx264":return ["cpu"]
    if codec and codec.endswith("_nvenc"):return ["cuda","cpu"]
    if codec and codec.endswith(("_amf","_qsv")):return ["d3d11va","cpu"]
    hardware=detect_hardware_profile()
    return ["cuda","cpu"] if hardware["selected_profile"]["vendor"]=="nvidia" else ["d3d11va","cpu"] if hardware["hardware_encoding"] else ["cpu"]


def decoder_device(codec):
    return "autoclip_amf" if codec.endswith("_amf") else "autoclip_intel" if codec.endswith("_qsv") else None


def decoder_device_args(codec):
    device=decoder_device(codec)
    if not device:return []
    vendor="0x1002" if codec.endswith("_amf") else "0x8086"
    return ["-init_hw_device",f"d3d11va={device}:,vendor_id={vendor}"]


def decoder_args(backend,hardware_frames=False,device=None):
    if backend=="cpu":return []
    args=["-hwaccel",backend]
    if device:args += ["-hwaccel_device",device]
    if hardware_frames and backend=="cuda":args += ["-hwaccel_output_format","cuda"]
    return args
