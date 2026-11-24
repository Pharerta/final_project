@echo off
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0"

set "PY_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if %errorlevel%==0 set "PY_CMD=python"
    if "%PY_CMD%"=="" (
        where py >nul 2>&1
        if %errorlevel%==0 set "PY_CMD=py -3"
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python 3.11+ not found. Run setup.bat or install Python first.
    exit /b 1
)

if /I "%~1"=="demo" goto :run_demo
if /I "%~1"=="test" goto :run_test
if /I "%~1"=="tests" goto :run_test

%PY_CMD% -X utf8 src/main.py %*
exit /b %errorlevel%

:run_demo
shift
%PY_CMD% -X utf8 src/demo.py %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:run_test
shift
%PY_CMD% -m pytest %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%
