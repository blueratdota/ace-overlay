# CLAUDE.md

External telemetry overlay for Assetto Corsa EVO. It reads the game's Windows shared memory and draws
a transparent, always-on-top, click-through Qt window. It's Windows-only, written in Python with PySide6.

## Commands

```bash
python -m venv .venv && .venv\Scripts\pip install -e .[build,dev]
.venv\Scripts\python -m ace_overlay --demo                 # simulated telemetry, no game needed
.venv\Scripts\python -m ace_overlay --dump                 # print live fields to compare with the in-game HUD
.venv\Scripts\python -m unittest discover -s tests         # unittest, not pytest
.venv\Scripts\python tools\screenshots.py                  # regenerate docs/images (README)
.venv\Scripts\python build.py                              # dist/ace-overlay-<version>-win64.zip
```

## Telemetry facts that aren't obvious from the code

- **Only the physics block** (`Local\acevo_pmf_physics`, 800 bytes, `_pack_ = 4`) is used. Its offsets
  are fixed and pinned by `tests/test_shm.py`. The graphics block has `char[33]`/`bool` padding, so
  its offsets shift. Don't read single fields from it without modelling the whole struct.
- **Not yet verified against the live game.** The layout comes from Kunos' Steam guide #3707421508
  and live-telemetry-evo's `docs/SHARED_MEMORY.md`. The least certain fields are `tyreTempI/M/O`. If
  they turn out wrong, the graphics block's `tyre_temperature_left/center/right` are community-verified
  to match the HUD.
- **Tyre wear isn't published** anywhere in shared memory (physics `tyreWear` is always 0). Don't add it.
- **TC/ABS side is inferred.** The game only sends single `tcInAction`/`absInAction` flags, so
  `slipping_sides()` picks the side from per-wheel `slipRatio`.
- Attach with `OpenFileMappingW`, never `mmap.mmap(tagname=...)`: mmap silently creates an empty
  mapping when the game isn't running. `LiveSource` reattaches when `packetId` stops changing, so it
  notices game restarts.

## UI architecture

- The locked overlay is click-through (`WindowTransparentForInput`), so **any clickable control must
  be its own window**. See `SideButton` (pin, gear). Those use `WindowDoesNotAcceptFocus` so clicking
  them doesn't take focus from the game.
- The layout is constant-driven at the top of `overlay.py` (`CT`, `CH`, `*_X`, `W`). Add sections by
  extending that chain, not with hard-coded coordinates.
- **Settings:** add a field to the `Config` dataclass (`config.py`) and a widget in `SettingsDialog`.
  Load/save is generic. Dev runs persist to the registry; the frozen exe uses `settings.ini` beside itself.
- The input trace stores `(time, gas, brake, clutch)` every tick and positions points by age, so the
  right edge is always live and changing `trace_seconds` rescales instantly.

## Keep in mind

- `tools/screenshots.py` swaps the `time` module in `ace_overlay.demo` and `ace_overlay.overlay` for
  a fake clock. Keep using `import time` / `time.monotonic()` there, not `from time import monotonic`.
- The demo lap is deterministic (`lap_speed(t)`), so the GIF loops and every lap hits the shift light.
- After visible UI changes, regenerate `docs/images` so the README stays accurate.
- `build.py` prunes unused Qt DLLs/plugins (`PRUNE`) and fails if anything still imports one. If you
  start using another Qt module (e.g. QtNetwork, QtOpenGL), check it isn't in `PRUNE`.
- UI text uses British spelling ("colour") to match the existing strings.
