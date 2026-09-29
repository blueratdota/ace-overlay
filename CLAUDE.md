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

- **The overlay consumes a `Physics` frame.** `LiveSource` reads the physics block (800 bytes, fixed
  offsets) plus the leading part of the graphics block (`Graphics`, up to the four `TyreState`s), and
  patches physics fields that EVO leaves empty. Offsets for both are pinned by `tests/test_shm.py`. The
  graphics block has `bool`/`int16`/`char[33]` padding, so every field before the one you want must
  be modelled.
- **Verified live (Golf 8 R, 2026-09-29):** pedals, gear, speed and RPM from physics are correct.
  Physics `tyreTempI/M/O` are **always 0**, so the real values come from graphics
  `TyreState.temperature_left/center/right`. Left/right are car-relative: left wheels have outer = left,
  right wheels have inner = left. Physics `absInAction` **never fires**. ABS shows up as `physics.abs`
  (0/1) and `graphics.abs_active`, which match exactly, so `LiveSource` ORs all three.
- **The graphics block feeds the info panel** (`panel.py`): fuel (`fuel_liter_per_lap`,
  `laps_possible_with_fuel`), lap times, `delta_time_ms`/`predicted_lap_time_ms` (0 in the pits),
  `session_state.time_left_ms`/`total_lap` (0 = timed session), `electronics` (TC/ABS/map levels,
  brake bias), and gaps. All verified live. `current_pos` is 0 in practice.
- **There is no target tyre pressure.** `TyreState.normalized_pressure` is exactly 1.0 anywhere
  inside the compound's ideal window (1.0 from about 27.0 to at least 31.6 psi on SuperCar tyres),
  and 1/3 per psi below it (26.0 psi read 0.669). The over-window slope is assumed to be the same.
  `pressure_adjust()` turns this into "add/remove ≈x psi".
- **TC is unverified.** No TC signal fired in a 4-minute recording, possibly because TC never cut in.
  It's handled like ABS (`tcInAction | tc > 0 | tc_active`).
- **Tyre wear isn't published** anywhere in shared memory (physics `tyreWear` is always 0). Don't add it.
- **TC/ABS side is inferred.** The game only sends car-wide flags, so `slipping_sides()` picks the
  side from per-wheel `slipRatio` (populated during ABS on the Golf; graphics `TyreState.lock` never fired).
- For live investigation, attach to both blocks while the user drives and count how often each
  candidate signal fires. Don't trust docs alone: several documented fields are dead in EVO.
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
