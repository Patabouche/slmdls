@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title SlimeDeals — Signature Authenticode

set "HERE=%~dp0"
set "GUI_OUT=%~1"
if "%GUI_OUT%"=="" set "GUI_OUT=dist2\SteaMidra_GUI"

pushd "%HERE%.." >nul 2>&1
set "SFFROOT=%CD%"
popd >nul 2>&1

set "TARGET=%SFFROOT%\%GUI_OUT%"
set "MAIN_EXE=%TARGET%\SteaMidra_GUI.exe"

if not exist "%MAIN_EXE%" (
    echo [ERREUR] Executable introuvable : %MAIN_EXE%
    echo Usage : sign_release.bat [chemin\vers\dist2\SteaMidra_GUI]
    exit /b 1
)

if "%SLIMEDEALS_SIGN_PFX%"=="" (
    echo.
    echo [INFO] Variable SLIMEDEALS_SIGN_PFX non definie.
    echo.
    echo Pour signer le launcher ^(requis pour SmartScreen / confiance Windows^) :
    echo   set SLIMEDEALS_SIGN_PFX=C:\chemin\certificat.pfx
    echo   set SLIMEDEALS_SIGN_PASSWORD=votre_mot_de_passe
    echo   BUILDER\sign_release.bat
    echo.
    echo Certificat recommande : Authenticode OV ou EV ^(DigiCert, Sectigo, etc.^)
    echo Voir BUILDER\README_TRUST.md
    exit /b 2
)

where signtool >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] signtool introuvable. Installez le Windows SDK ^(Signing Tools^).
    exit /b 1
)

set "TS_URL=http://timestamp.digicert.com"
if not "%SLIMEDEALS_TIMESTAMP_URL%"=="" set "TS_URL=%SLIMEDEALS_TIMESTAMP_URL%"

echo [SIGN] SteaMidra_GUI.exe
signtool sign /fd sha256 /f "%SLIMEDEALS_SIGN_PFX%" /p "%SLIMEDEALS_SIGN_PASSWORD%" /tr "%TS_URL%" /td sha256 /d "SlimeDeals Launcher" "%MAIN_EXE%"
if errorlevel 1 exit /b 1

REM Signer les .exe/.dll embarques visibles par l'utilisateur ^(optionnel mais utile^)
for %%E in ("%TARGET%\_internal\*.exe") do (
    echo [SIGN] %%~nxE
    signtool sign /fd sha256 /f "%SLIMEDEALS_SIGN_PFX%" /p "%SLIMEDEALS_SIGN_PASSWORD%" /tr "%TS_URL%" /td sha256 /d "SlimeDeals Launcher" "%%~fE"
)

echo.
echo [OK] Signature terminee pour %TARGET%
signtool verify /pa "%MAIN_EXE%"
exit /b 0
