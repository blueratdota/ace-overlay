@echo off
setlocal
set "ace=%USERPROFILE%\Saved Games\ACE"
set "loader=%ace%\mods\ACEUIAppLoader.kspkg"
set "bridge=%ace%\mods\uiresources\ACEUIAppLoader\ace-standings-bridge"
set "marker=%ace%\Video\ACEUIAppLoader-ace-standings-bridge.settingspreset"

if not exist "%ace%\" (
    echo Start Assetto Corsa EVO once before running this setup.
    goto failed
)
if not exist "%~dp0ACEUIAppLoader.kspkg" goto failed
if not exist "%~dp0ace-standings-bridge\app.json" goto failed
if not exist "%~dp0ace-standings-bridge\bridge.js" goto failed
if exist "%loader%" (
    fc /b "%loader%" "%~dp0ACEUIAppLoader.kspkg" >nul
    if errorlevel 1 echo Keeping your existing ACE UI App Loader. Verify that it matches your game build.
)
if not exist "%bridge%\" (
    mkdir "%bridge%" || goto failed
)
if not exist "%ace%\Video\" (
    mkdir "%ace%\Video" || goto failed
)
if not exist "%loader%" (
    copy /y "%~dp0ACEUIAppLoader.kspkg" "%loader%" >nul || goto failed
)
copy /y "%~dp0ace-standings-bridge\app.json" "%bridge%\app.json" >nul || goto failed
copy /y "%~dp0ace-standings-bridge\bridge.js" "%bridge%\bridge.js" >nul || goto failed
if not exist "%marker%" (
    type nul > "%marker%" || goto failed
)

echo Standings bridge installed. The bundled loader targets AC EVO 0.9.1+release.6.
echo Restart AC EVO, open the right-edge HUD drawer, and enable ACE Standings Bridge.
pause
exit /b 0

:failed
echo Setup failed. Extract the entire ZIP and check that the AC EVO folder is writable.
pause
exit /b 1
