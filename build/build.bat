@echo off
title Adam Packaging Tool
echo ==============================================
echo       Adam Build and Packaging CLI
echo ==============================================
echo.

:: Check for python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in your PATH. Please install Python and try again.
    pause
    exit /b 1
)

:: Run build script
python "%~dp0build.py" %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build pipeline failed. Check logs above.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Packaging complete!
pause
