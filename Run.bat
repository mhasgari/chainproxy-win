@echo off
rem One-click entry: installs whatever is missing (Python, sing-box), then starts the app.
rem   Run.bat        -> window (GUI)
rem   Run.bat cli    -> console version
rem   Run.bat shortcut -> (re)create the Desktop / Start Menu shortcut
rem The first run also creates a 'Chain Proxy' shortcut on the Desktop and in the Start Menu.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup failed - see the message above.
  pause
)
