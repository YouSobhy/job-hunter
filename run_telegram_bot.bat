@echo off
cd /d D:\Joe\JobHunter
set "PYEXE=C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYEXE%" set "PYEXE=pyw"
start "" "%PYEXE%" -X utf8 telegram_bot.py
