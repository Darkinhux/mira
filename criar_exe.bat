@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -m pip install --upgrade -r requirements.txt pyinstaller || (pause & exit /b 1)
%PY% build_exe.py || (pause & exit /b 1)
echo.
echo O Mira.exe esta na pasta dist. Pode copiar para onde quiser.
explorer dist
pause
