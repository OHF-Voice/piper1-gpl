@echo off
setlocal

REM Build script for libpiper on Windows
REM This script configures, builds, and installs libpiper

cd /d "%~dp0"

echo ========================================
echo Building libpiper
echo ========================================

REM Configure
echo.
echo [1/3] Configuring CMake...
cmake -Bbuild -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="%~dp0install"
if errorlevel 1 (
    echo CMake configuration failed!
    exit /b 1
)

REM Build
echo.
echo [2/3] Building...
cmake --build build --config Release
if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

REM Install
echo.
echo [3/3] Installing...
cmake --install build --config Release
if errorlevel 1 (
    echo Install failed!
    exit /b 1
)

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
echo Installed files:
echo   - Library: %~dp0install\piper.dll
echo   - Header:  %~dp0install\include\piper.h
echo   - ONNX Runtime: %~dp0install\lib\
echo   - espeak-ng data: %~dp0install\espeak-ng-data\
echo.

endlocal
