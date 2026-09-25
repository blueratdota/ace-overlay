AC EVO Overlay
==============

A lightweight on-screen overlay for Assetto Corsa EVO: clutch / brake / throttle bars with %,
input trace, RPM lights, gear, speed, RPM, tyre temperatures and TC / ABS lights.

No installation needed. Just keep this folder together.


HOW TO USE
----------
1. In Assetto Corsa EVO's video settings, set the display mode to BORDERLESS (or windowed).
   The overlay can't show on top of exclusive fullscreen or in VR.

2. Double-click ace-overlay.exe. It shows "Waiting for Assetto Corsa EVO..." until you're
   in a session. You can start it before or after the game.

3. Get on track. The overlay fills with live data.


CONTROLS
--------
Pin button (next to the overlay's top-right corner)
    Click to unpin, drag the overlay where you want it, then click again to lock it.
    When locked, mouse clicks pass straight through to the game.

Gear button (under the pin)
    Settings: input trace time window, RPM light start / colour zones / flash point.

Tray icon (bottom-right of the taskbar; it may be under the ^ arrow)
    Right-click for Move overlay, Settings, and Quit.

Settings and the overlay position are saved to settings.ini in this folder.


FIRST RUN: WINDOWS SMARTSCREEN
------------------------------
This app isn't code-signed, so Windows may show "Windows protected your PC".
Click "More info", then "Run anyway". Some antivirus tools also flag unsigned
PyInstaller apps. That's a false positive.


TROUBLESHOOTING
---------------
- Overlay not visible over the game: make sure the game is in borderless / windowed mode.
- Numbers look wrong, or it stays on "Waiting..." while you're on track: run
  "Check telemetry.bat" while driving and compare against the in-game HUD. AC EVO is in
  early access, so a game update can change its telemetry layout.
- If the overlay crashes, details are written to error.log in this folder.

Tyre wear isn't shown because AC EVO doesn't publish it.
