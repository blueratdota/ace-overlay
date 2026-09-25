@echo off
rem Prints the live telemetry the overlay reads, to compare against the in-game HUD.
rem Close this window (or press Ctrl+C) to stop.
title AC EVO telemetry check
"%~dp0ace-overlay.exe" --dump
