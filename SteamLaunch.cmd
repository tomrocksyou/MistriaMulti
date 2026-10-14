@echo off
rem Steam launch option:  "<this folder>\SteamLaunch.cmd" %command%
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\Play.ps1" -FromSteam %*
