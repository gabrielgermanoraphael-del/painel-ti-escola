@echo off
chcp 65001 >nul
title Criar atalho do Servidor do TI
rem Cria "Servidor do TI" na area de trabalho (e, se quiser, na inicializacao do Windows).
set "AT_ALVO=%~dp0iniciar_servidor.bat"
set "AT_PASTA=%~dp0"
set "AT_ICONE=%~dp0servidor.ico"
set "AT_LUGAR=Desktop"
call :criar || goto :erro
echo Atalho criado na area de trabalho: "Servidor do TI"
echo.
set /p INICIO=Quer que o servidor ligue sozinho quando o Windows iniciar? (s/n): 
if /i not "%INICIO%"=="s" goto :fim
set "AT_LUGAR=Startup"
call :criar || goto :erro
echo Pronto: o servidor vai abrir minimizado toda vez que voce entrar no Windows.
goto :fim

:criar
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=[Environment]::GetFolderPath($env:AT_LUGAR); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $p 'Servidor do TI.lnk')); $s.TargetPath=$env:AT_ALVO; $s.WorkingDirectory=$env:AT_PASTA; $s.IconLocation=$env:AT_ICONE; $s.WindowStyle=7; $s.Description='Liga o servidor do Chamar o TI'; $s.Save()"
exit /b %errorlevel%

:erro
echo.
echo Nao consegui criar o atalho automaticamente. Faca manualmente:
echo   1. Botao direito na area de trabalho, Novo, Atalho
echo   2. Local do item: "%AT_ALVO%"
echo   3. Nome: Servidor do TI
echo   4. Propriedades: Executar = Minimizada; Alterar icone = "%AT_ICONE%"

:fim
echo.
pause
