@echo off
rem JobHunter scheduled-task entry point. No output redirection here --
rem Python owns logging (jobhunter.log + job_results_log.txt + status.json).
cd /d D:\Joe\JobHunter
set "PYEXE=C:\Users\Lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=py"
"%PYEXE%" -X utf8 run.py
