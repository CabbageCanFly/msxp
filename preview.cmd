@echo off
setlocal
set "MSXP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%MSXP_PYTHON%" set "MSXP_PYTHON=%~dp0..\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe"
if not exist "%MSXP_PYTHON%" (
  echo Python environment missing. Follow README setup to create .venv in this worktree.
  exit /b 1
)
"%MSXP_PYTHON%" "%~dp0tools\preview_pages.py" --demo --live --port 8890 %*
