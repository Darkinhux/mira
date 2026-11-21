@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw mira.py) || (start "" pythonw mira.py)
