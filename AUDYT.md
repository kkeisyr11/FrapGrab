# Frap Grab validation

Current audit: [6 November 2026](docs/AUDIT-2026-11-06.md).

Version 2.1.4 fixes stale-buffer event handling, reports incomplete replays,
adds a general WASAPI chat-output selector, and uses the calibrated HUD detector
for recorded-match analysis where available.

110 tests passed. Twenty existing recordings (7 min 39 s) decoded successfully.
One automatic clip contained an invalid event marker and no confirmed HUD kill;
18 other automatic clips contained confirmed HUD actions. Saved clips alone
cannot establish recall for the full gaming session.

Remaining priorities include row-identity detection, optional full-session
recording, per-window capture, hybrid-GPU support, additional HUD languages,
storage limits and broader physical-hardware tests. The installer is unsigned.

Private recordings and per-file audit evidence are not included in the repository.
