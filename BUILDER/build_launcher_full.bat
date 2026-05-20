@echo off
REM Build SlimeDeals COMPLET : GreenLuma, SlimeDealsBPRG, third_party, etc.
REM Prérequis avant lancement :
REM   - greenlumafix.rar à la racine de launcher\SFF\
REM   - SlimeDealsBPRG\SlimeDealsBPRG.exe (ou compiler via build_simple_gui.bat)
cd /d "%~dp0"
call "%~dp0build_launcher.bat" full
