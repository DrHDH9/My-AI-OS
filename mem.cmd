@echo off
rem My-AI-OS memory command wrapper (Windows).
rem
rem Two problems this solves:
rem   1. PATH "python" may hit the Microsoft Store stub and fail.
rem   2. Console codepage 936 vs Python UTF-8 causes mojibake.
rem mem.py handles the codepage itself; this wrapper only pins the interpreter.
rem
rem Nothing here is machine-specific: it probes python, then py -3.

setlocal
set "PY="

python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto run

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto run

echo [My-AI-OS] Python 3 not found.
echo   1^) Install Python 3.9+ and tick "Add python.exe to PATH"
echo   2^) Open a NEW terminal, then run this again
echo   Or call it by full path, e.g. "C:\Python3X\python.exe" mem.py check
exit /b 127

:run
%PY% "%~dp0mem.py" %*
exit /b %ERRORLEVEL%
