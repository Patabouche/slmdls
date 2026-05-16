@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

taskkill /F /T /IM SteaMidra.exe >nul 2>&1
timeout /t 3 /nobreak >nul

echo ========================================
echo Building SteaMidra Executable
echo ========================================
echo.

echo Cleaning old build files...
if exist "build" rmdir /s /q "build"
REM dist\ : ne pas tout supprimer ^(verrous^) — remplacement via staging PyInstaller ci-dessous.

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

echo.
echo Préparation Google Drive (embarqué si JSON ou variables présents)…
python prepare_gdrive_for_build.py
echo.

echo Building executable...
echo This may take 5-10 minutes...
echo.

REM Suppress pkg_resources deprecation from PyInstaller/build deps so log stays clean
set PYTHONWARNINGS=ignore::UserWarning
echo Livrable : dist2\SteaMidra ^(staging dist2\_pyi_stage_*^)
if not exist "dist2" mkdir "dist2"
set "PYI_STAGE=dist2\_pyi_stage_!RANDOM!"
python -m PyInstaller --noconfirm --distpath "!PYI_STAGE!" build_sff.spec
if errorlevel 1 (
    if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
    goto :Fail
)
if not exist "!PYI_STAGE!\SteaMidra\SteaMidra.exe" (
    echo BUILD FAILED: exe manquant dans !PYI_STAGE!
    if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
    goto :Fail
)
taskkill /F /T /IM SteaMidra.exe >nul 2>&1
timeout /t 5 /nobreak >nul
set "CLI_OUT=dist2\SteaMidra"
if exist "!CLI_OUT!" rmdir /s /q "!CLI_OUT!" 2>nul
if exist "!CLI_OUT!" ren "!CLI_OUT!" "SteaMidra.bak_!RANDOM!" 2>nul
if exist "!CLI_OUT!" set "CLI_OUT=dist2\SteaMidra_!RANDOM!"
robocopy "!PYI_STAGE!\SteaMidra" "!CLI_OUT!" /E /COPY:DAT /R:5 /W:2 /NFL /NDL /NJH /NJS
if errorlevel 8 (
    echo BUILD FAILED: robocopy. Build OK dans !PYI_STAGE!\SteaMidra\
    if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
    goto :Fail
)
if not exist "!CLI_OUT!\SteaMidra.exe" (
    echo BUILD FAILED: exe manquant dans !CLI_OUT!
    if exist "!PYI_STAGE!" rmdir /s /q "!PYI_STAGE!" 2>nul
    goto :Fail
)
rmdir /s /q "!PYI_STAGE!" 2>nul
goto :AfterPyinst

:Fail
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

:AfterPyinst

echo.
echo ========================================
echo BUILD SUCCESSFUL!
echo ========================================
echo.
echo Folder:     !CLI_OUT!\
echo Executable: !CLI_OUT!\SteaMidra.exe
echo.

if exist "!CLI_OUT!\SteaMidra.exe" (
    set "SFF_SIZEPATH=!CD!\!CLI_OUT!"
    python -c "import os; p=os.environ['SFF_SIZEPATH']; size=sum(os.path.getsize(os.path.join(r,f)) for r,d,files in os.walk(p) for f in files); print(f'Total size: {size / (1024*1024):.1f} MB')"
    set "SFF_SIZEPATH="
)

echo.
echo You can now run: !CLI_OUT!\SteaMidra.exe
echo Zip le dossier !CLI_OUT!\ pour distribution.
echo Settings will be saved next to the EXE.
echo.
pause
