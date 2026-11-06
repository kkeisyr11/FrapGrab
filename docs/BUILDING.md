# Building from source

Developer instructions. Users should install the `.exe` from Releases.

Requirements: Windows, Python 3.12 x64 and Inno Setup 6.

1. Run `Start.ps1 -Setup` to prepare the virtual environment.
2. Run `.venv/Scripts/python.exe tools/prepare_ffmpeg.py` to download the pinned,
   SHA-256 verified media tools.
3. Run `Start.ps1 -Build` to build `dist/FrapGrab/FrapGrab.exe`.
4. Compile `installer.iss` with Inno Setup 6.

Tests: `.venv/Scripts/python.exe -m unittest discover -s tests -q`.
For running the source during development, use `Start.ps1 -Source`.
See [release instructions](../RELEASE.md) before publishing.

To keep an existing release running, use `python build_exe.py --output-dir dist_candidate/FrapGrab`.
Compile with `ISCC.exe /DAppSourceDir=dist_candidate\FrapGrab installer.iss`.
