@echo off
rem Lance l interface AFR sous Windows (double-clic).
setlocal enabledelayedexpansion

rem Toujours travailler dans le dossier de ce fichier, meme en double-clic.
cd /d "%~dp0"

set "PYTHON="
where py >nul 2>nul
if %errorlevel%==0 set "PYTHON=py -3"
if not defined PYTHON (
    where python >nul 2>nul
    if !errorlevel!==0 set "PYTHON=python"
)

if not defined PYTHON (
    echo.
    echo Python est introuvable sur cette machine.
    echo Installer Python 3.9 ou plus recent depuis https://www.python.org/downloads/
    echo et cocher "Add python.exe to PATH" pendant l installation.
    echo.
    pause
    exit /b 1
)

echo Lancement avec : %PYTHON%
%PYTHON% run_afr.py %*
set "CODE=%errorlevel%"

if not "%CODE%"=="0" (
    echo.
    echo ----------------------------------------------------------------
    echo L application ne s est pas lancee ^(code %CODE%^).
    echo Lire le message ci-dessus ; la trace complete, si elle existe,
    echo se trouve dans afr_error.log a cote de ce fichier.
    echo ----------------------------------------------------------------
)

echo.
pause
exit /b %CODE%
