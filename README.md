# ace-overlay

A lightweight inputs overlay for **Assetto Corsa EVO**: throttle / brake / clutch bars, a ~4 s
input trace, gear, speed, RPM with shift lights, and per-tyre surface temperatures (inner /
middle / outer).

Tyre wear isn't shown because AC EVO doesn't publish it. The in-game HUD calculates it
internally and never writes it to shared memory.

AC EVO has no in-game app API, so this is an external program. It reads the game's
shared-memory telemetry (`Local\acevo_pmf_physics`) and draws a transparent, always-on-top,
click-through window over the game.

## Requirements

- Windows, Python 3.10+
- The game in **borderless / windowed** mode. Exclusive fullscreen and VR draw over any desktop
  window, so the overlay won't be visible there.

## Run

```bash
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\python -m ace_overlay
```

| Flag | Purpose |
| --- | --- |
| `--demo` | Fake telemetry, so you can work on the overlay without the game running |
| `--dump` | Print the telemetry fields to the console instead of showing the overlay |

**Moving it:** click the pin button next to the overlay's top-right corner to unpin it. The pin
turns yellow and the overlay gets a dashed border. Drag the overlay where you want it, then click
the pin again to lock it in place. A locked overlay lets clicks pass through to the game, and the
position is remembered between runs. The tray icon's *Move overlay* item does the same thing.

**Settings:** the gear button under the pin (or *Settings…* in the tray menu) opens a settings
window. Changes apply live and are saved:

- **Input trace time window** (2–30 s): how much history the trace shows. The right edge is
  always the live input, and changing the window rescales the whole trace.
- **RPM lights:** the lights spread from *Lights start at* to *Flash at* (in % of max RPM). Each
  light takes colour 1, 2 or 3 depending on the RPM % it stands for, and all lights flash in the
  flash colour once RPM reaches *Flash at*.

## Build the portable package

```bash
.venv\Scripts\pip install -e .[build]
.venv\Scripts\python build.py
```

This produces `dist/ace-overlay-<version>-win64.zip`: a self-contained `ace-overlay` folder with
`ace-overlay.exe`, a user-facing `README.txt` and `Check telemetry.bat` (runs `--dump`). Nothing
needs installing. Extract it and run the exe. The packaged exe stores its settings in
`settings.ini` next to itself, and writes crashes to `error.log`.

## Layout notes

- `ace_overlay/shm.py`: the physics struct (800 bytes, `_pack_ = 4`) and a read-only mapping
  reader. `tests/test_shm.py` pins the documented offsets.
- AC EVO is in early access and Kunos may change the layout. If values look wrong after a game
  patch, run `--dump` and compare against the in-game HUD.
- Layout sources: Kunos' Steam guide
  [#3707421508](https://steamcommunity.com/sharedfiles/filedetails/?id=3707421508) and
  [live-telemetry-evo's SHARED_MEMORY.md](https://github.com/albertowd/live-telemetry-evo/blob/develop/docs/SHARED_MEMORY.md).

## Tests

```bash
.venv\Scripts\python -m unittest discover -s tests
```
