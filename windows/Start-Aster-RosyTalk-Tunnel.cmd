@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Aster-RosyTalk-Tunnel.ps1"
set "ASTER_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%ASTER_EXIT_CODE%"=="0" (
  echo The Aster RosyTalk Tunnel helper has stopped.
) else (
  echo The Aster RosyTalk Tunnel helper stopped with exit code %ASTER_EXIT_CODE%.
)
echo This window will remain open so you can read any message above.
pause
endlocal & exit /b %ASTER_EXIT_CODE%
