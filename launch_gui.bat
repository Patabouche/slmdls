@echo off
cd /d "%~dp0"
echo Lancement de SlimeDeals...
.\venv\Scripts\python.exe Main_gui.py
if errorlevel 1 (
    echo.
    echo Erreur au lancement. Appuie sur une touche pour fermer.
    pause
)
