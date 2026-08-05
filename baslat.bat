@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" desktop_app.py
) else (
  echo Once kurulum yapin: python -m venv .venv
  echo sonra: .venv\Scripts\pip install -r requirements.txt
  pause
)
