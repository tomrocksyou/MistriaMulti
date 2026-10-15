@echo off
rem OPTIONAL. You normally do NOT need this file: start Fields of Mistria from Steam and choose Multiplayer
rem (Host a game / Join a game) in the game's own menu. This only pre-sets a role (host or join) that then starts by itself.
echo MistriaMulti: you do not have to run this setup.
echo Start Fields of Mistria from Steam, choose New Game or Load Game, then Multiplayer, then Host a game or Join a game.
echo (The one-time Steam launch option is still needed: see the README, or MistriMulti.exe - Steam setup.)
echo.
echo Press any key only if you want the optional pre-set setup, or close this window.
pause >nul
if exist "%~dp0MistriMultiLauncher.exe" (
    start "" /wait "%~dp0MistriMultiLauncher.exe" --configure
) else (
    start "" /wait "%~dp0build\MistriMultiLauncher.exe" --configure
)
