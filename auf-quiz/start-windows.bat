@echo off
title AUF University Week Quiz
cd /d "%~dp0"
where python >nul 2>nul && (python server.py %*) || (py -3 server.py %*)
echo.
echo The quiz server has stopped. If you saw an error above, check that Python 3 is installed.
pause
