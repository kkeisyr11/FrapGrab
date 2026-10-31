# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
root = Path(SPECPATH)
datas = [(str(root / 'assets'), 'assets')]
binaries = []
hiddenimports = []
for package in ('customtkinter', 'rapidocr_onnxruntime', 'pyaudiowpatch', 'dxcam'):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += imports
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=['pytest', 'IPython', 'notebook', 'matplotlib', 'torch', 'tensorflow'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FrapGrab', debug=False,
    strip=False, upx=False, console=False, icon=str(root / 'assets' / 'icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FrapGrab')
