@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% --version >nul 2>nul || (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/
  echo Marque a opcao "Add python.exe to PATH" durante a instalacao.
  pause & exit /b 1
)
%PY% -m pip install --upgrade -r requirements.txt || (pause & exit /b 1)
echo.
echo Pronto! Agora de dois cliques em iniciar.bat
pause
