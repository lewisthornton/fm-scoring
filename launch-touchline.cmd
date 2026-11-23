@echo off
setlocal
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 "%~dp0touchline_launch.py" %*
exit /b %errorlevel%
:use_python
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install Python for your user account first.
  exit /b 1
)
python "%~dp0touchline_launch.py" %*
exit /b %errorlevel%
