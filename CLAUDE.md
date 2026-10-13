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
- **Tyre pressure follows bulk temperature exactly:** psi = garage psi + 0.096 × (`TyreState.temperature_c`
  − 40 °C), with R² = 1.000 on all tyres. `temperature_c` equals physics `tyreCoreTemperature`.
  There's no target pressure. The normalised values are exactly 1.0 inside a per-compound ideal
  window and linear outside it: pressure 1/3 per psi, surface temperature 1/30 per °C, core 1/20 per
  °C. SuperCar: pressure ≥ 27.0 psi (top edge not yet seen), surface 60–95 °C, core ≥ 60 °C.
  `tyres.py` learns the windows live (saved under `tyres/…` in settings), projects each tyre to the
  middle of its ideal temperature window, and recommends the garage pressure. Never judge pressure
  without its temperature.
- **"Driving" = `graphics.status == STATUS_LIVE (2)` and not `is_in_pit_box`** (`shm.is_driving`).
  Status is 2 both in the box and on track, and **3 in a replay** (the graphics packetId also stops
  advancing then). The HUD's "only while driving" setting uses this with a 2 s hide delay, and always
  shows while unpinned. The setting is off by default.
- **Turbo:** `graphics.turbo_boost` (bar, relative). `max_turbo_boost` **can't tell turbo cars apart**:
  it read 0.66 on the naturally aspirated BMW M3 E46 CSL, where every boost field stayed 0 over 2,000
  full-throttle samples. Live boost on a real turbo car is still unverified. (The HUD's boost/torque
  bar was dropped in the pill redesign; `current_torque` is live if it's ever needed.)
- **Always log `graphics.car_model` in live probes.** The user switches cars between sessions, and
  findings must be attributed to the right car.
- **TC is unverified.** No TC signal fired in a 4-minute recording, possibly because TC never cut in.
  It's handled like ABS (`tcInAction | tc > 0 | tc_active`).
- **Tyre wear isn't published** anywhere in shared memory (physics `tyreWear` is always 0). Don't add it.
- **TC/ABS side is inferred.** The game only sends car-wide flags, so `slipping_sides()` picks the
  side from per-wheel `slipRatio` (populated during ABS on the Golf; graphics `TyreState.lock` never fired).
- **Physics `airTemp`/`roadTemp` read 0 in some states** (seen with status 3). Use `shm.air_temp()`
  (falls back to graphics `air_temperature_c`) and `shm.track_temp()` (None → "–").
- For live investigation, attach to both blocks while the user drives and count how often each
  candidate signal fires. Don't trust docs alone: several documented fields are dead in EVO.
- Attach with `OpenFileMappingW`, never `mmap.mmap(tagname=...)`: mmap silently creates an empty
  mapping when the game isn't running. `LiveSource` reattaches when `packetId` stops changing, so it
  notices game restarts.

## UI architecture

- The locked overlay is click-through (`WindowTransparentForInput`), so **any clickable control must
  be its own window**. See `SideButton` (pin, gear). Those use `WindowDoesNotAcceptFocus` so clicking
  them doesn't take focus from the game.
- The HUD is a pill. Its rounded ends are thin TC/ABS arc lines (upper quarter TC, lower quarter
  ABS; left end = car's left wheels, right end = right wheels, via `slipping_sides()`). The gear ring
  is concentric with the left end. Throttle fills 3/4 clockwise from the top-left (135°) and brake the
  west quarter, with the gear and speed inside it. Then come the dot shift lights (the only RPM display;
  there's no RPM number; 26 dots along the top edge) over the trace, which starts at `CX0` and fills
  the height down to the chip, then the position. A chip (track °C, air °C, current lap) hangs below
  the bottom edge, overlapping it by `CHIP_OVERLAP`. The layout is
  constant-driven at the top of `overlay.py` (`PH`, `R`, `RING_*`, `CX0`, `TRACE_*`, `POS_*`, `W`):
  extend that chain, not hard-coded coordinates. Fonts go through `font()` (Bahnschrift, then Segoe UI).
- Tyre temperatures, pedal bars and the boost bar were dropped from the HUD in the redesign at the
  user's request. Tyre data lives in the info panel.
- **Settings:** add a field to the `Config` dataclass (`config.py`) and a widget in `SettingsDialog`.
  Load/save is generic. Dev runs persist to the registry; the frozen exe uses `settings.ini` beside itself.
- The input trace stores `(time, gas, brake, clutch, tc, abs)` every tick and positions points by age, so the
  right edge is always live and changing `trace_seconds` rescales instantly.

## Keep in mind

- `tools/screenshots.py` swaps the `time` module in `ace_overlay.demo` and `ace_overlay.overlay` for
  a fake clock. Keep using `import time` / `time.monotonic()` there, not `from time import monotonic`.
- The demo lap is deterministic (`lap_speed(t)`), so the GIF loops and every lap hits the shift light.
- After visible UI changes, regenerate `docs/images` so the README stays accurate.
- `build.py` prunes unused Qt DLLs/plugins (`PRUNE`) and fails if anything still imports one. If you
  start using another Qt module (e.g. QtNetwork, QtOpenGL), check it isn't in `PRUNE`.
- UI text uses British spelling ("colour") to match the existing strings.
