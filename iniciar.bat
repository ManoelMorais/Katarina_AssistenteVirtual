@echo off
title Katarina
 
echo.
echo  Iniciando Katarina...
echo.
 
start "Servidor" cmd /k "cd /d "%~dp0core" && python -m uvicorn servidor:app --host 0.0.0.0 --port 8000"
 
timeout /t 6 /nobreak > nul
 
start "Overlay" cmd /k "cd /d "%~dp0overlay" && npx electron ."
 
timeout /t 2 /nobreak > nul
 
start "Telegram" cmd /k "cd /d "%~dp0interfaces" && node telegram.js"
 
start "Voz" cmd /k "cd /d "%~dp0core" && python voz.py"
 
timeout /t 3 /nobreak > nul
 
start "Loop" cmd /k "cd /d "%~dp0core" && python loop_autonomo.py"
 
exit
 