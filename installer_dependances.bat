@echo off
rem Installe les bibliotheques necessaires a l interface AFR.
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
    echo Python est introuvable. Installer Python 3.9 ou plus recent
    echo depuis https://www.python.org/downloads/ en cochant
    echo "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Installation des bibliotheques avec : %PYTHON%
%PYTHON% -m pip install --upgrade pip
%PYTHON% -m pip install -r requirements.txt

echo.
echo Verification :
%PYTHON% run_afr.py --check
echo.
pause
