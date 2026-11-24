@echo off
echo Stopping Restaurant QR Menu Server on port 8085...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8085 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Server stopped.
pause
