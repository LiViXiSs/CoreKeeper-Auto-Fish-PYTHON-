@echo off
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; assert sys.maxsize > 2**32" >nul 2>&1
    if not errorlevel 1 (
        py -3 "%~dp0core_keeper_fisher.py"
        if errorlevel 1 pause
        exit /b
    )
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys, tkinter; assert sys.maxsize > 2**32" >nul 2>&1
    if not errorlevel 1 (
        python "%~dp0core_keeper_fisher.py"
        if errorlevel 1 pause
        exit /b
    )
)
rem Optional fallback for this machine and other Codex installations.
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0core_keeper_fisher.py"
    if errorlevel 1 pause
    exit /b
)
echo Install 64-bit Python with Tcl/Tk support, then run this launcher again.
pause
exit /b 1
