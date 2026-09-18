@echo off
rem Lance la nouvelle interface AFR (Qt, graphes interactifs).
setlocal enabledelayedexpansion
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

echo Lancement de l interface Qt avec : %PYTHON%
%PYTHON% run_afr_qt.py %*
set "CODE=%errorlevel%"

if not "%CODE%"=="0" (
    echo.
    echo ----------------------------------------------------------------
    echo L application ne s est pas lancee ^(code %CODE%^).
    echo Rapport d installation : afr_check.log
    echo Trace complete en cas d erreur : afr_error.log
    echo ----------------------------------------------------------------
)

echo.
pause
exit /b %CODE%
