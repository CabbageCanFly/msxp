@echo off
rem msxp for Windows: .\msxp help  (uses .venv once "msxp install" has created it)
setlocal
set "MSXP_SCRIPT=%~dp0tools\msxp.py"
if defined MSXP_PYTHON goto custom
if exist "%~dp0.venv\Scripts\python.exe" goto venv
where py >nul 2>nul && goto launcher
where python >nul 2>nul && goto system
echo Python 3.11 or newer is required: https://www.python.org/downloads/
exit /b 1
:custom
"%MSXP_PYTHON%" "%MSXP_SCRIPT%" %*
exit /b %errorlevel%
:venv
"%~dp0.venv\Scripts\python.exe" "%MSXP_SCRIPT%" %*
exit /b %errorlevel%
:launcher
py -3 "%MSXP_SCRIPT%" %*
exit /b %errorlevel%
:system
python "%MSXP_SCRIPT%" %*
exit /b %errorlevel%
