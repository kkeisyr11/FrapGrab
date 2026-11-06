# Frap Grab validation

## 2.1.5 capture hotfix

The earlier short capture tests missed a long-running failure. A 60 FPS AV1 test
with three audio sources reproduced stalled segments and the 12-second watchdog.
Silent PCM sources now follow an absolute monotonic clock, avoiding cumulative
Windows timer rounding. The segment manifest is append-only with bounded,
short-lived read snapshots, avoiding Windows rename conflicts. Logging is
explicitly configured even if a dependency has installed handlers first.

113 tests passed. A 90-second real capture kept advancing and exported three
clips while recording; all three decoded fully. This is a focused regression
check, not a guarantee for every driver or multi-hour session.

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
