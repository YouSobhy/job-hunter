@echo off
cd /d D:\Joe\JobHunter
set "PYEXE=C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=py"

echo Starting JobHunter Backend API...
start "" "%PYEXE%" -m uvicorn api:app --host 0.0.0.0 --reload --port 8000

echo Launching Dashboard in browser...
timeout /t 2 /nobreak >nul
start http://localhost:8000
