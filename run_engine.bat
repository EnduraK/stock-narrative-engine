@echo off
:: Stock Narrative Engine — Daily Runner
:: This file is called by Windows Task Scheduler.
:: It activates the right Python environment and runs the engine.

cd /d "%~dp0"

:: Log start time
echo [%DATE% %TIME%] Starting Stock Narrative Engine >> "%~dp0logs\scheduler.log" 2>&1

:: Run the engine — generates HTML report and opens it in your browser
python main.py --html --congress-days 30 --open >> "%~dp0logs\scheduler.log" 2>&1

:: Log exit code
echo [%DATE% %TIME%] Engine finished with exit code %ERRORLEVEL% >> "%~dp0logs\scheduler.log" 2>&1
