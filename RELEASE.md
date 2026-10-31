# Releases

Official repository: https://github.com/kkeisyr11/FrapGrab

1. Set the same version in `core/updater.py` and `installer.iss`.
2. Run `python -m unittest discover -s tests -q` and validate capture/editing.
3. Close the app. Run `python build_exe.py`, then compile `installer.iss` with Inno Setup 6.
4. Create a stable release tagged `v<VERSION>` from the tested source commit.
5. Upload `Frap_Grab_Setup_<VERSION>.exe`, its SHA-256 text file, and the FFmpeg
   source archive described in THIRD_PARTY_NOTICES.md.
6. Download the public installer and verify its hash and GitHub asset digest.

The updater checks GitHub Releases at most once a day. Checks can be disabled;
download and installation require a click. An update needs the exact installer
name, a GitHub SHA-256 asset digest, and a download URL from this repository.
Installation is blocked while recording or exporting.

Preferences live in `%LOCALAPPDATA%/FrapGrab`. On the first renamed launch,
preferences from `%LOCALAPPDATA%/AutoClipWarDogs` are copied if no new profile
exists. Existing recordings and personal HUD template paths are preserved.
The installer keeps the previous application ID for upgrades.

Only source, public assets, documentation and dependency licenses belong in Git.
Keep recordings, personal profiles, logs, tools and builds out of the repository.
`build_exe.py` checks empty player defaults and scans the finished application's
modules and resources for private profile data. See `build_output/public-package-audit.json`.
