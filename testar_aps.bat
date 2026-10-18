@echo off
title Teste do Monitor de APs
cd /d "%~dp0"
echo.
if not exist "monitor_aps.py" goto semarquivo
set "PY="
py --version >nul 2>&1 && set "PY=py"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY goto sempython
echo Usando: %PY%
echo.
%PY% monitor_aps.py --teste
echo.
pause
exit /b

:semarquivo
echo ERRO: nao encontrei o monitor_aps.py nesta pasta.
echo Extraia o zip primeiro: clique com o botao direito no monitor-aps.zip,
echo escolha "Extrair Tudo" e rode o .bat de dentro da pasta extraida.
echo.
pause
exit /b

:sempython
echo ERRO: o Python nao esta instalado neste computador.
echo Baixe em https://www.python.org/downloads/ e, na instalacao,
echo marque a opcao "Add python.exe to PATH". Depois rode este arquivo de novo.
echo.
pause
exit /b
