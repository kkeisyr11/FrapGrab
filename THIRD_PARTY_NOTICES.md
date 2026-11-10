# Third-party software

Frap Grab invokes the bundled FFmpeg and FFprobe as separate executables.
These are unmodified Gyan.dev FFmpeg 9.0.2 full static Windows builds, GPL v3.
Copyright (c) 2000-2026 the FFmpeg developers. No warranty is provided by FFmpeg.

- License: [licenses/FFmpeg-GPL-3.0.txt](licenses/FFmpeg-GPL-3.0.txt).
- Original build documentation/configuration: [licenses/FFmpeg-build.txt](licenses/FFmpeg-build.txt).
- Binary provider: https://www.gyan.dev/ffmpeg/builds/.
- Exact upstream package: https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2.
- FFmpeg source revision: https://github.com/FFmpeg/FFmpeg/commit/946fcce07b.
- Source archive: https://github.com/FFmpeg/FFmpeg/archive/946fcce07b.tar.gz
  (also provided as `FFmpeg-946fcce07b-source.tar.gz` beside the Frap Grab installer).
- External codec libraries are listed in the original build documentation;
  their upstream projects and source links are in FFmpeg's bundled
  `doc/general.html` and https://ffmpeg.org/general.html#External-libraries.

Pinned upstream ZIP SHA-256:
`759d0a9831c436a0eb331ad36f236c06cb04aaa0005da46571f0e9d3d9206f6b`.
`tools/prepare_ffmpeg.py` verifies it before extracting tools and license notices.

Python and third-party Python packages retain their own licenses. Copies for the
runtime dependencies are in `licenses/python/`, `licenses/Python.txt`, and the
application's `_internal` distribution directories (including Tcl/Tk terms).
Packages include CustomTkinter, NumPy, OpenCV, Pillow, MSS, sounddevice, CFFI,
keyboard, RapidOCR/ONNX Runtime, PyAudioWPatch, DXcam, comtypes, psutil, packaging and websocket-client.
The AI editor uses PyJWT and cryptography for ChatGPT sign-in verification.
Their upstream license texts are in `licenses/python/`.
The ONNX models shipped with RapidOCR retain that package's upstream notices:
https://github.com/RapidAI/RapidOCR.

Frap Grab is an independent project and is not affiliated with the game publisher,
NVIDIA, AMD, Intel, SteelSeries or Medal. Third-party licenses apply to their
respective components; publication does not replace them with an Frap Grab license.
