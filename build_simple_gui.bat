@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM Evite WinError 5 : tuer l'arborescence du processus Qt WebEngine.
taskkill /F /T /IM SteaMidra_GUI.exe >nul 2>&1
timeout /t 3 /nobreak >nul

echo ========================================
echo Building SteaMidra GUI Executable
echo ========================================
echo.

echo Cleaning old GUI build files...
if exist "build\build_sff_gui" rmdir /s /q "build\build_sff_gui"

if exist "third_party\SteamAutoCrack\Steam-auto-crack-3.5.0.3\Steam-auto-crack-3.5.0.3\SteamAutoCrack.CLI\SteamAutoCrack.CLI.csproj" (
    where dotnet >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo Building SteamAutoCrack CLI v3.5.0.3...
        dotnet publish "third_party\SteamAutoCrack\Steam-auto-crack-3.5.0.3\Steam-auto-crack-3.5.0.3\SteamAutoCrack.CLI\SteamAutoCrack.CLI.csproj" -c Release -r win-x86 --self-contained true -p:PublishSingleFile=false -p:ErrorOnDuplicatePublishOutputFiles=false
        if exist "third_party\SteamAutoCrack\Steam-auto-crack-3.5.0.3\Steam-auto-crack-3.5.0.3\SteamAutoCrack.CLI\bin\Release\net10.0-windows\win-x86\publish\SteamAutoCrack.CLI.exe" (
            if not exist "third_party\SteamAutoCrack\cli" mkdir "third_party\SteamAutoCrack\cli"
            xcopy /E /Y /I "third_party\SteamAutoCrack\Steam-auto-crack-3.5.0.3\Steam-auto-crack-3.5.0.3\SteamAutoCrack.CLI\bin\Release\net10.0-windows\win-x86\publish\*" "third_party\SteamAutoCrack\cli" >nul
            echo SteamAutoCrack CLI v3.5.0.3 built successfully.
        ) else (
            echo WARNING: SteamAutoCrack CLI build did not produce expected output.
        )
        echo.
    )
)

REM ROCKSTAR BYPASS — compile le projet test et copie vers SlimeDealsBPRG\ pour inclusion PyInstaller
set "SDB_PROJ=%~dp0..\..\test\Nightlight-Game-Launcher\V4\SlimeDealsBPRG\SlimeDealsBPRG.csproj"
set "SDB_OUT=%~dp0..\..\test\Nightlight-Game-Launcher\V4\SlimeDealsBPRG\bin\Release"
if exist "%SDB_PROJ%" (
    where dotnet >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo Building SlimeDealsBPRG ^(ROCKSTAR BYPASS^)...
        dotnet build "%SDB_PROJ%" -c Release -v minimal
        if exist "%SDB_OUT%\SlimeDealsBPRG.exe" (
            if not exist "%~dp0SlimeDealsBPRG" mkdir "%~dp0SlimeDealsBPRG"
            copy /Y "%SDB_OUT%\SlimeDealsBPRG.exe" "%~dp0SlimeDealsBPRG\" >nul
            if exist "%SDB_OUT%\Assets" (
                if not exist "%~dp0SlimeDealsBPRG\Assets" mkdir "%~dp0SlimeDealsBPRG\Assets"
                xcopy /E /Y /I "%SDB_OUT%\Assets\*" "%~dp0SlimeDealsBPRG\Assets\" >nul
            )
            echo SlimeDealsBPRG copie dans launcher\SFF\SlimeDealsBPRG pour le package GUI.
        ) else (
            echo WARNING: build SlimeDealsBPRG sans SlimeDealsBPRG.exe dans bin\Release — bouton BYPASS absent du build.
        )
        echo.
    )
) else (
    echo Note: projet SlimeDealsBPRG introuvable ^(%SDB_PROJ%^) — placez SlimeDealsBPRG.exe sous SlimeDealsBPRG\ a la main si besoin.
)

echo.
echo Préparation Google Drive (embarqué dans l'exe si JSON ou variables présents)…
python prepare_gdrive_for_build.py
echo.

echo Building GUI executable...
echo This may take 5-10 minutes...
echo.
echo Pour Google Drive : avec gdrive_oauth_client.json ou client_secret*.json
echo   ^(racine SFF ou dossier sff/^), le build genere automatiquement sff\_gc_secrets.py.
echo.

REM Suppress pkg_resources deprecation from PyInstaller/build deps so log stays clean
set PYTHONWARNINGS=ignore::UserWarning
echo Livrable : dist2\SteaMidra_GUI ^(staging dist2\_pyi_stage_*^)
if not exist "dist2" mkdir "dist2"
set "PYI_STAGE=dist2\_pyi_stage_!RANDOM!"
python -m PyInstaller --noconfirm --distpath "!PYI_STAGE!" build_sff_gui.spec
if errorlevel 1 (
    if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
    echo.
    echo ========================================
    echo BUILD FAILED!
    echo ========================================
    echo.
    echo Install requirements first (two steps):
    echo   1. pip install -r requirements.txt
    echo   2. pip install steam==1.4.4 --no-deps
    echo.
    echo Or just run: install_online_fix_requirements.bat
    pause
    exit /b 1
)
if not exist "!PYI_STAGE!\SteaMidra_GUI\SteaMidra_GUI.exe" (
    echo BUILD FAILED: exe manquant dans !PYI_STAGE!
    if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
    pause
    exit /b 1
)
taskkill /F /T /IM SteaMidra_GUI.exe >nul 2>&1
timeout /t 5 /nobreak >nul
set "GUI_OUT=dist2\SteaMidra_GUI"
if exist "!GUI_OUT!" rmdir /s /q "!GUI_OUT!" 2>nul
if exist "!GUI_OUT!" ren "!GUI_OUT!" "SteaMidra_GUI.bak_!RANDOM!" 2>nul
if exist "!GUI_OUT!" set "GUI_OUT=dist2\SteaMidra_gui_!RANDOM!"
echo Copie ^(robocopy^) vers !GUI_OUT! ...
robocopy "!PYI_STAGE!\SteaMidra_GUI" "!GUI_OUT!" /E /COPY:DAT /R:5 /W:2 /NFL /NDL /NJH /NJS
if errorlevel 8 (
    echo BUILD FAILED: robocopy. Build OK dans !PYI_STAGE!\SteaMidra_GUI\
    pause
    exit /b 1
)
if not exist "!GUI_OUT!\SteaMidra_GUI.exe" (
    echo BUILD FAILED: exe manquant dans !GUI_OUT!
    pause
    exit /b 1
)
rmdir /s /q "!PYI_STAGE!" 2>nul

echo.
echo ========================================
echo BUILD SUCCESSFUL!
echo ========================================
echo.
echo Folder:     !GUI_OUT!\
echo Executable: !GUI_OUT!\SteaMidra_GUI.exe
echo.

if exist "!GUI_OUT!\SteaMidra_GUI.exe" (
    set "SFF_SIZEPATH=!CD!\!GUI_OUT!"
    python -c "import os; p=os.environ['SFF_SIZEPATH']; size=sum(os.path.getsize(os.path.join(r,f)) for r,d,files in os.walk(p) for f in files); print(f'Total size: {size / (1024*1024):.1f} MB')"
    set "SFF_SIZEPATH="
)

echo.
echo You can now run: !GUI_OUT!\SteaMidra_GUI.exe
echo Zip le dossier !GUI_OUT!\ pour distribution.
echo Settings will be saved next to the EXE.
echo.
pause
