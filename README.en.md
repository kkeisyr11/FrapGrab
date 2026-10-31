# User guide

[Download for Windows](https://github.com/kkeisyr11/FrapGrab/releases/latest/download/Frap_Grab_Setup_2.1.1.exe) · [Releases](https://github.com/kkeisyr11/FrapGrab/releases) · [Home](README.md)

Windows 10/11, 64-bit. The installer includes the required media tools.

![First run](docs/images/first-run-en.png)

Download **Frap_Grab_Setup_2.1.1.exe** from Releases, run it and follow the installer.
Launch Frap Grab from the Start menu or desktop shortcut.

Choose **English** in Settings. The interface switches immediately.

The first-run wizard configures language, game, detection, recording and audio.
War Dogs is the only supported game profile. Choose your game on the Dashboard. New
profiles have no player name or personal HUD template. Your in-game name is
required for detecting your own kills and analyzing recordings. Manual F8 capture
and voice reactions work without it: turn off automatic kill detection in the wizard.
The wizard can be reopened from Settings. Updates keep existing user preferences.
Personal settings and templates are stored outside the installer.

GPU settings are automatic by default. Family presets cover GeForce RTX 20/30/40/50,
GTX 10/16, Radeon RX 5000/6000/7000/9000 and Intel Arc. A short encode/decode test
checks the actual driver before an encoder is offered. RTX 30 does not get AV1
recording; unsupported codecs are rejected. The fallback is a clearly labelled
30 FPS CPU profile. Advanced users can disable automatic settings.

Live detection uses pixel matching. For initial HUD calibration, enter your player
name and save a replay containing your kill with F8. After leaving the game, the
app can locate your nickname and create a template automatically using offline OCR.
Calibration pauses while the game is active. You can also select **Detect HUD from
a replay**. HUD geometry scales with display height and supports ultrawide layouts.
Custom HUD/font changes may require detecting the HUD again. Manual coordinates
and calibration remain under Advanced.

Choose the manual replay length beside **Save replay**, up to 30 minutes. Increasing
the length grows the disk buffer from that point onwards. Earlier deleted footage
cannot be recovered. Recordings are stored by date.

In Editor, choose kills, assists and voice reactions independently. Assists may be
restricted to within 8 or 15 seconds of a kill. Overlapping replays are aligned and
merged. Estimate the duration before export; the actual duration appears afterwards.
Music can be added before export or to a finished video, preserving video packets.

Updates use kkeisyr11/FrapGrab on GitHub Releases. Version checks run at most
once a day and can be disabled in Settings. Downloads and installation require
your click. Downloads require a matching installer and verified SHA-256.
See `RELEASE.md` for publication details.

Validated locally: RTX 5080 capture and NVIDIA editing, plus HEVC AMF recording
and D3D11VA/AMF editing on the integrated Radeon. Presets for RX 7900 XTX, RX 9070 XT
and RX 9060 XT are not a claim of physical gaming-performance tests on those cards.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency notices.
