@echo off
cd /d "%~dp0"
rem find Python without relying on PATH (a fresh per-user install may not be on it yet)
set "PYEXE=" & set "PYARG="
for /f "delims=" %%P in ('dir /b /o-n "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\%%P\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\%%P\python.exe"
if not defined PYEXE where py >nul 2>nul && (set "PYEXE=py" & set "PYARG=-3")
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  echo Python was not found. Run Run.bat first.
  exit /b 1
)
"%PYEXE%" %PYARG% chain.py off
