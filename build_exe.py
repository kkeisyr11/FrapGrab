"""Portable build. No hardcoded user/FFmpeg paths, no deletion of previous releases."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent


def prepare_media_tools():
    folder = BASE / "tools"
    folder.mkdir(exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        target = folder / name
        if not target.exists():
            found = shutil.which(name)
            candidates = [Path(found)] if found else []
            candidates += [BASE / "dist_release" / "FrapGrab" / name]
            source = next((p for p in candidates if p.is_file()), None)
            if not source:
                raise FileNotFoundError(f"Brak {name}. Umieść pełny build FFmpeg w folderze tools.")
            shutil.copy2(source, target)
        subprocess.run([str(target), "-version"], check=True, capture_output=True)


def build_executable(output_dir=None):
    import psutil
    app=Path(output_dir).resolve() if output_dir else BASE / "dist" / "FrapGrab"
    target = (app / "FrapGrab.exe").resolve()
    for process in psutil.process_iter(["exe"]):
        if process.info["exe"] and Path(process.info["exe"]).resolve()==target:
            raise RuntimeError("Zamknij uruchomiony Frap Grab przed aktualizacją plików programu.")
    prepare_media_tools()
    staging_root = BASE / "build_output"
    staging_root.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="release_",dir=staging_root))
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(staging),
        "--workpath", str(BASE / "build_v2"), str(BASE / "FrapGrab.spec")], cwd=BASE, check=True)
    # Copy a complete staged build without recursively deleting an existing release.
    # Windows font services/antivirus can temporarily hold files in a previous tree.
    shutil.copytree(staging / "FrapGrab",app,dirs_exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        shutil.copy2(BASE / "tools" / name, app / name)
    shutil.copy2(BASE / "README.md", app / "README.md")
    shutil.copy2(BASE / "AUDYT.md", app / "AUDYT.md")
    for name in ("README.en.md","RELEASE.md","THIRD_PARTY_NOTICES.md"):
        if (BASE/name).is_file():shutil.copy2(BASE/name,app/name)
    if (BASE/"docs").is_dir():shutil.copytree(BASE/"docs",app/"docs",dirs_exist_ok=True)
    if (BASE/"licenses").is_dir():shutil.copytree(BASE/"licenses",app/"licenses",dirs_exist_ok=True)
    from core.config import load_config,DEFAULT_CONFIG,DEFAULT_REPOSITORY
    from tools.audit_release import audit_bundle
    import json
    if DEFAULT_CONFIG["gamertag"] or DEFAULT_CONFIG["pixel_profile"] or DEFAULT_CONFIG["setup_completed"] or DEFAULT_CONFIG['game_profiles']:
        raise RuntimeError("Publiczne wydanie musi startować bez nicku, wzorca i ukończonej konfiguracji.")
    config=load_config();template=None
    try:template=json.loads(Path(config["pixel_profile"]).read_text(encoding="utf-8"))["template"]
    except (OSError,ValueError,KeyError):pass
    report=audit_bundle(app,[config["gamertag"]] if config["gamertag"] else [],template,[DEFAULT_REPOSITORY])
    (staging_root/"public-package-audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    if not report["success"]:raise RuntimeError("Audyt prywatności paczki nie powiódł się: "+str(report["issues"]))
    print(f"Gotowe: {app / 'FrapGrab.exe'}")
    return True


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',help='Build a separate application directory without replacing a running release')
    build_executable(parser.parse_args().output_dir)
