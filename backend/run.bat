@echo off
rem Serwer HALO -> Arcade (Windows).  backend\run.bat --install  (raz: srodowisko), potem backend\run.bat (start)
setlocal
cd /d "%~dp0.."
if "%~1"=="--install" goto install
if not exist backend\.venv\Scripts\python.exe goto install
goto run

:install
py -3.13 -m venv backend\.venv 2>nul ||python -m venv backend\.venv || exit /b 1
backend\.venv\Scripts\python -m pip install -q -r backend\requirements.txt || exit /b 1
if "%~1"=="--install" exit /b 0

:run
backend\.venv\Scripts\python -m backend %*
