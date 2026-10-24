@echo off
setlocal
title Servidor do mapa eleitoral - NAO FECHE
cd /d "%~dp0"

set "PORT=8766"
set "ARQUIVO=mapa_eleitoral_parauapebas_2026.html"
set "PY=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"

echo.
echo  Mapa eleitoral - servidor local
echo  Abrindo http://127.0.0.1:%PORT%/%ARQUIVO%
echo.
echo  NAO FECHE esta janela enquanto estiver usando o mapa.
echo  Para desligar o servidor, feche esta janela ou aperte Ctrl+C.
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:%PORT%/%ARQUIVO%'"
"%PY%" -m http.server %PORT% --bind 127.0.0.1
