@echo off
title Alpaca Trading Bot
cd /d "%~dp0"

echo ===================================================
echo    Alpaca Trading Bot - Ross Cameron 15m Momentum
echo ===================================================
echo.

:: Check Node is available
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found. Please install Node.js from https://nodejs.org
    pause
    exit /b 1
)

:: Install dependencies if node_modules is missing
if not exist "node_modules\" (
    echo [Setup] Installing dependencies...
    npm install
    if %errorlevel% neq 0 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
    echo.
)

:: Build TypeScript if dist is missing or src is newer
if not exist "dist\index.js" (
    echo [Build] Compiling TypeScript...
    npx tsc
    if %errorlevel% neq 0 (
        echo [ERROR] TypeScript compilation failed.
        pause
        exit /b 1
    )
    echo.
)

echo [Bot] Starting...
echo Press Ctrl+C to stop gracefully.
echo.

node dist\index.js

echo.
echo [Bot] Stopped.
pause
