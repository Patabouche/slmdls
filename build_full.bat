@echo off
REM Raccourci racine — build complet (GreenLuma + tout embarqué)
cd /d "%~dp0"
call "%~dp0BUILDER\build_launcher.bat" full
