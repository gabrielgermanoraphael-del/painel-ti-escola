@echo off
title Criar usuario do painel
call "%~dp0_ambiente.cmd"
if not "%AMBIENTE_OK%"=="1" goto :fim

echo Criar conta do TI no banco: %DADOS%\chamados.db
set /p LOGIN=Usuario (ex.: gabriel): 
set /p NOME=Nome para exibir (ex.: Gabriel): 
set /p ADM=Administrador? (s/n): 
if /i "%ADM%"=="s" (python -m app.cli criar-usuario "%LOGIN%" "%NOME%" --admin) else (python -m app.cli criar-usuario "%LOGIN%" "%NOME%")
echo.
python -m app.cli listar-usuarios

:fim
pause
