@echo off
title Servidor Chamar o TI
call "%~dp0_ambiente.cmd"
if not "%AMBIENTE_OK%"=="1" goto :jaligado
echo O servidor JA ESTA LIGADO em outra janela (veja a barra de tarefas).
echo Nao precisa abrir de novo.

:fim

python -c "import socket,sys;sys.exit(1 if socket.socket().connect_ex(('127.0.0.1',8000))==0 else 0)"
if errorlevel 1 goto :jaligado

python "%~dp0backup_banco.py" "%DADOS%"
echo.
echo ================================================================
echo  Servidor do Chamar o TI LIGADO. Deixe esta janela aberta.
echo  Teste neste PC:   http://127.0.0.1:8000/saude
echo  Endereco publico: o do Tailscale Funnel (veja o README)
echo  Banco de dados:   %DADOS%\chamados.db
echo  Para desligar:    Ctrl+C ou feche esta janela
echo ================================================================
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
echo.
echo O servidor parou. Se foi erro, veja a mensagem acima.

:fim
pause
