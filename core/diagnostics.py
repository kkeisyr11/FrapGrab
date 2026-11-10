"""Opt-in packaged-runtime smoke check. No user config changes or screen capture."""
import json
import sys
import traceback
from pathlib import Path


def self_test(output):
    from .updater import CURRENT_VERSION
    report = {"version":CURRENT_VERSION,"frozen": bool(getattr(sys, "frozen", False)), "checks": {}}
    try:
        from .hardware import detect_hardware_profile
        from .media import find_binary
        from .monitors import outputs
        from .audio_capture import DesktopAudio
        from .pixel_detector import VisualPatch
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        import subprocess
        report["hardware"] = detect_hardware_profile()
        report["monitors"] = outputs()
        for name in ("ffmpeg", "ffprobe"):
            path = find_binary(name)
            result = subprocess.run([path, "-version"], capture_output=True, timeout=15, creationflags=0x08000000)
            if result.returncode:
                raise RuntimeError(f"{name} failed")
            report["checks"][name] = path
        ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        ocr(np.zeros((100, 400, 3), dtype=np.uint8))
        report["checks"]["ocr_models"] = "passed"
        audio = DesktopAudio()
        report["checks"]["audio"] = {"rate": audio.rate, "channels": audio.channels}
        audio.close()
        report["checks"]["voice_sources"]={}
        for role in ("microphone","chat"):
            try:
                source=DesktopAudio(role)
                report["checks"]["voice_sources"][role]={"name":source.device["name"],"rate":source.rate,"channels":source.channels}
                source.close()
            except LookupError:
                report["checks"]["voice_sources"][role]="not available / not required"
        monitor = report["monitors"][0]
        patch = VisualPatch(64,64,monitor)
        report["checks"]["pixel_capture"] = patch.backend
        patch.close()
        from .hud_probes import auxiliary_profiles
        from .pixel_detector import PixelMatcher
        assists=auxiliary_profiles({"monitor_size":[2560,1440]})
        if not assists:raise RuntimeError("Missing assist pattern in the application package")
        PixelMatcher(assists[0])
        report["checks"]["assist_pattern"]="passed"
        from .localization import set_language,t
        set_language("en")
        if t("Pulpit")!="Dashboard":raise RuntimeError("Missing English UI catalog")
        set_language("pl")
        report["checks"]["languages"]="pl/en"
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        signed = jwt.encode({"sub": "package-test"}, key, algorithm="RS256")
        if jwt.decode(signed, key.public_key(), algorithms=["RS256"])["sub"] != "package-test":
            raise RuntimeError("Could not verify ChatGPT sign-in dependencies")
        report["checks"]["chatgpt_jwt"] = "passed"
        report["checks"]["gpu_profile"]=report["hardware"]["selected_profile"]["id"]
        report["success"] = True
    except Exception:
        report["success"] = False
        report["error"] = traceback.format_exc()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["success"] else 1
