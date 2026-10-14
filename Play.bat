@echo off
rem Sets up multiplayer (host or join) once. Afterwards just click Play in Steam.
if exist "%~dp0MistriMultiLauncher.exe" (
    start "" /wait "%~dp0MistriMultiLauncher.exe" --configure
) else (
    start "" /wait "%~dp0build\MistriMultiLauncher.exe" --configure
)
