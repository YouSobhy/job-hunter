@echo off
cd /d D:\Joe\JobHunter
set "PYEXE=C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=py"
"%PYEXE%" -m streamlit run dashboard.py
