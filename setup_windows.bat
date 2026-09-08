@echo off
setlocal EnableExtensions
title Uroflow Setup
cd /d "%~dp0"

echo Setting up Uroflow Analysis...
echo.

set "TESTED_PYTHON_SERIES=3.12"
set "PYTHON_WINGET_ID=Python.Python.3.12"
set "PYTHON_INSTALL_ATTEMPTED=0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo ERROR: The existing .venv does not use Python 3.10 or newer.
        echo Rename or remove the .venv folder, then run this setup again.
        goto :failed
    )

    echo Using the existing .venv environment.
    goto :install
)

if exist ".venv\" (
    echo ERROR: A .venv folder exists, but it is not a standard Windows virtual environment.
    echo Rename or remove the .venv folder, then run this setup again.
    goto :failed
)

:find_python
set "PYTHON_EXE="
set "PYTHON_ARGS="

py.exe -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py.exe"
    set "PYTHON_ARGS=-3"
    goto :create_venv
)

python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python.exe"
    goto :create_venv
)

rem Python installed for the current user may not yet be visible on PATH.
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%~fD\python.exe" (
        "%%~fD\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_EXE=%%~fD\python.exe"
            goto :create_venv
        )
    )
)

rem Also check common system-wide installation locations.
for /d %%D in ("%ProgramFiles%\Python3*") do (
    if exist "%%~fD\python.exe" (
        "%%~fD\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_EXE=%%~fD\python.exe"
            goto :create_venv
        )
    )
)

if "%PYTHON_INSTALL_ATTEMPTED%"=="1" goto :python_not_detected_after_install

echo Python 3.10 or newer was not found.
echo.
choice /c YN /n /m "Python is required. Install tested Python %TESTED_PYTHON_SERIES% now? [Y/N] "
if errorlevel 2 goto :python_install_declined

where.exe winget.exe >nul 2>&1
if errorlevel 1 goto :winget_not_available

echo.
echo Installing Python %TESTED_PYTHON_SERIES% for the current Windows user...
set "PYTHON_INSTALL_ATTEMPTED=1"
winget.exe install --id "%PYTHON_WINGET_ID%" --exact --source winget --scope user --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
set "WINGET_EXIT_CODE=%ERRORLEVEL%"
if not "%WINGET_EXIT_CODE%"=="0" goto :winget_install_failed

echo.
echo Python installation completed. Detecting it...
goto :find_python

:create_venv
echo Found a compatible Python installation:
"%PYTHON_EXE%" %PYTHON_ARGS% --version
echo.
echo Creating .venv...
"%PYTHON_EXE%" %PYTHON_ARGS% -m venv ".venv"
if errorlevel 1 (
    echo ERROR: Could not create .venv.
    goto :failed
)

:install
echo.
echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: Could not upgrade pip.
    goto :failed
)

echo.
echo Installing Uroflow Analysis and its dependencies...
".venv\Scripts\python.exe" -m pip install -e . "opencv-python>=4.8.0"
if errorlevel 1 (
    echo ERROR: Could not install Uroflow Analysis.
    goto :failed
)

echo.
echo Setup completed successfully.
echo Launching Uroflow Analysis...
echo.
call "%~dp0run_gui.bat"
if errorlevel 1 (
    echo.
    echo ERROR: Uroflow Analysis closed with an error.
    goto :failed
)
exit /b 0

:python_install_declined
echo.
echo Python installation was not approved. Setup cannot continue.
goto :manual_python_install

:winget_not_available
echo.
echo ERROR: WinGet is not available on this computer.
goto :manual_python_install

:winget_install_failed
echo.
echo ERROR: WinGet could not install Python. Exit code: %WINGET_EXIT_CODE%
goto :manual_python_install

:python_not_detected_after_install
echo.
echo ERROR: Python installation finished, but Python could not be located.

:manual_python_install
echo Install Python %TESTED_PYTHON_SERIES% manually from:
echo https://www.python.org/downloads/windows/
echo Then run setup_windows.bat again.
goto :failed

:failed
echo.
echo Setup did not complete.
echo.
pause
exit /b 1
