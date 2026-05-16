@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title SlimeDeals — Build launcher (.exe)

set "HERE=%~dp0"
pushd "%HERE%.." >nul 2>&1
set "SFFROOT=%CD%"
popd >nul 2>&1

if not exist "%SFFROOT%\Main_gui.py" (
    echo [ERREUR] Lance ce script depuis launcher\SFF\BUILDER — Main_gui.py introuvable.
    echo Dossier attendu : launcher\SFF
    pause
    exit /b 1
)

set "VENV=%HERE%.venv_build"
set "STASH=%TEMP%\SlimeDealsBuild_oauth_%RANDOM%"
set "BUILD_ERR=0"
set "GUI_OUT="

echo ========================================
echo  Build SlimeDeals ^(GUI^) — package propre
echo ========================================
echo.
echo  Racine projet : %SFFROOT%
echo  Livrable GUI  : dist2\SteaMidra_GUI\ ^(ancien dist\ ignore pour eviter verrous Windows^)
echo  Environnement : %VENV% ^(pip isole, evite conflits avec TensorFlow, etc.^)
echo  Exclut du .exe : fichiers client_secret*.json ^(deplaces temporairement^) ;
echo    identifiants peuvent etre embarques via _gc_secrets.py genere juste avant.
echo  Connexion SlimeDeals : jamais dans le build ^(%%USERPROFILE%%\.slimedeals\ par utilisateur^).
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] python introuvable sur le PATH.
    pause
    exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
    echo [BUILDER] Creation du venv ^(premiere fois^)…
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer le venv. Verifie Python 3.12 ou 3.13 ^(64 bits^).
        pause
        exit /b 1
    )
)

call "%VENV%\Scripts\activate.bat"
cd /d "%SFFROOT%"

REM Deblocage dist\ : tuer l'app et les processus enfants Qt WebEngine (/T).
echo [BUILDER] Fermeture eventuelle de SteaMidra_GUI.exe ^(arborescence /T^)…
taskkill /F /T /IM SteaMidra_GUI.exe >nul 2>&1
timeout /t 3 /nobreak >nul

REM --- Nettoyage artefacts PyInstaller précédents ---
if exist "build\build_sff_gui" (
    echo [BUILDER] Suppression build\build_sff_gui
    rmdir /s /q "build\build_sff_gui"
)
REM PyInstaller + livrable : tout sous dist2\ ^(evite dist\SteaMidra_GUI souvent verrouille^).
if exist "dist2\SteaMidra_GUI" (
    echo [BUILDER] Suppression dist2\SteaMidra_GUI ^(si verrou, on renommera apres build^)
    rmdir /s /q "dist2\SteaMidra_GUI" 2>nul
    if exist "dist2\SteaMidra_GUI" echo [BUILDER] Note: ancien dist2\SteaMidra_GUI encore la.
)

for %%F in ("debug.log" "crash.log") do if exist "%%~F" (
    echo [BUILDER] Suppression %%~F
    del /f /q "%%~F" 2>nul
)

echo [BUILDER] OAuth Google : generation sff\_gc_secrets.py si JSON ^(racine/sff/^) ou variables…
python prepare_gdrive_for_build.py
if errorlevel 1 (
    echo [ERREUR] prepare_gdrive_for_build ^(defini SFF_STRICT_GDRIVE_BUILD sans identifiants ?^)
    set "BUILD_ERR=1"
    goto :RestoreOAuth
)

mkdir "%STASH%" 2>nul
for %%F in ("client_secret*.json") do (
    if exist "%%~fF" (
        echo [BUILDER] Hors package : %%~nxF — restauration en fin de script.
        move /Y "%%~fF" "%STASH%\" >nul
    )
)

echo [BUILDER] Python :
python --version

echo [BUILDER] pip / setuptools / wheel — a jour
python -m pip install -q --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [ERREUR] Mise a jour pip a echoue.
    set "BUILD_ERR=1"
    goto :RestoreOAuth
)

echo [BUILDER] pip install -r requirements.txt
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] pip install -r requirements.txt a echoue.
    set "BUILD_ERR=1"
    goto :RestoreOAuth
)

echo [BUILDER] pip install steam==1.4.4 --no-deps
python -m pip install -q steam==1.4.4 --no-deps
if errorlevel 1 (
    echo [ERREUR] pip install steam a echoue.
    set "BUILD_ERR=1"
    goto :RestoreOAuth
)

echo [BUILDER] pip install pyinstaller
python -m pip install -q pyinstaller
if errorlevel 1 (
    echo [ERREUR] pip install pyinstaller a echoue.
    set "BUILD_ERR=1"
    goto :RestoreOAuth
)

echo.
echo [BUILDER] PyInstaller — staging dist2\_pyi_stage_* puis livrable dist2\SteaMidra_GUI
echo           ^(le dossier dist\ ancien n'est plus utilise pour eviter les verrous Windows^).
echo.
set PYTHONWARNINGS=ignore::UserWarning
if not exist "dist2" mkdir "dist2"
set "PYI_STAGE=dist2\_pyi_stage_!RANDOM!"
echo [BUILDER] Dossier staging : !PYI_STAGE!
python -m PyInstaller --noconfirm --distpath "!PYI_STAGE!" build_sff_gui.spec
if errorlevel 1 (
    set "BUILD_ERR=1"
    if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
) else (
    if not exist "!PYI_STAGE!\SteaMidra_GUI\SteaMidra_GUI.exe" (
        echo [ERREUR] Exe produit introuvable : !PYI_STAGE!\SteaMidra_GUI\
        set "BUILD_ERR=1"
        if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
    ) else (
        echo [BUILDER] Copie vers dist2\SteaMidra_GUI ^(robocopy, plus fiable que move sous Windows^)…
        taskkill /F /T /IM SteaMidra_GUI.exe >nul 2>&1
        timeout /t 5 /nobreak >nul
        set "GUI_OUT=dist2\SteaMidra_GUI"
        if exist "!GUI_OUT!" rmdir /s /q "!GUI_OUT!" 2>nul
        if exist "!GUI_OUT!" (
            ren "!GUI_OUT!" "SteaMidra_GUI.bak_!RANDOM!" 2>nul
        )
        if exist "!GUI_OUT!" (
            set "GUI_OUT=dist2\SteaMidra_gui_!RANDOM!"
            echo [BUILDER] dist2\SteaMidra_GUI verrouille — livrable dans : !GUI_OUT!
        )
        robocopy "!PYI_STAGE!\SteaMidra_GUI" "!GUI_OUT!" /E /COPY:DAT /R:5 /W:2 /NFL /NDL /NJH /NJS
        if errorlevel 8 (
            echo [ERREUR] robocopy a echoue — build complet dans : !PYI_STAGE!\SteaMidra_GUI\
            set "BUILD_ERR=1"
        ) else (
            if not exist "!GUI_OUT!\SteaMidra_GUI.exe" (
                echo [ERREUR] SteaMidra_GUI.exe introuvable dans !GUI_OUT!
                set "BUILD_ERR=1"
            ) else (
                rmdir /s /q "!PYI_STAGE!" 2>nul
            )
        )
    )
)

:RestoreOAuth
echo.
dir /b "%STASH%\*.json" >nul 2>&1 && (
    echo [BUILDER] Restauration des client_secret*.json vers la racine SFF…
    for %%F in ("%STASH%\*.json") do if exist "%%~fF" move /Y "%%~fF" "%SFFROOT%\"
)
if exist "%STASH%" rmdir /s /q "%STASH%" 2>nul

if not "!BUILD_ERR!"=="0" (
    echo ========================================
    echo  ECHEC du build — voir les messages ci-dessus.
    echo ========================================
    pause
    exit /b 1
)

if "!GUI_OUT!"=="" set "GUI_OUT=dist2\SteaMidra_GUI"

echo ========================================
echo  Build termine avec succes.
echo ========================================
echo.
echo  Dossier a distribuer ^(ZIP entier, obligatoire pour Qt WebEngine^) :
echo    %SFFROOT%\!GUI_OUT!\
echo  Executable :
echo    %SFFROOT%\!GUI_OUT!\SteaMidra_GUI.exe
echo.
echo  Rappel : client_secret Google non inclus dans le package.
echo.
pause
exit /b 0
