@echo off
setlocal
title Uroflow GUI

set "GUI_EXE=%~dp0.venv\Scripts\uroflow-gui.exe"

if not exist "%GUI_EXE%" (
    echo ERROR: Uroflow Analysis is not installed in this repository.
    echo Run setup_windows.bat first, then try again.
    echo.
    pause
    exit /b 1
)

echo Starting Uroflow GUI...
echo.
"%GUI_EXE%" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
    echo GUI has closed.
) else (
    echo Uroflow GUI exited with error code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
