@rem Prepara o ambiente (usado pelos outros .bat). Nao rode direto.
chcp 65001 >nul
set "PASTA=%~dp0"
if exist "%PASTA%config_local.cmd" goto :temconfig

echo Primeira vez: criando config_local.cmd ...
set SEGREDO=
for /f "delims=" %%s in ('python -c "import secrets;print(secrets.token_urlsafe(48))"') do set "SEGREDO=%%s"
if "%SEGREDO%"=="" goto :sempython
> "%PASTA%config_local.cmd" echo @rem Configuracao do servidor Chamar o TI. NAO compartilhe este arquivo.
>>"%PASTA%config_local.cmd" echo set GOOGLE_CLIENT_ID=COLE-AQUI-O-ID.apps.googleusercontent.com
>>"%PASTA%config_local.cmd" echo set JWT_SECRET=%SEGREDO%
>>"%PASTA%config_local.cmd" echo set CORS_ORIGINS=https://gabrielgermanoraphael-del.github.io,http://localhost:8080
>>"%PASTA%config_local.cmd" echo set NTFY_URL=https://ntfy.sh
>>"%PASTA%config_local.cmd" echo set NTFY_TOPIC=
echo.
echo Preencha GOOGLE_CLIENT_ID e NTFY_TOPIC no Bloco de Notas, salve e rode o .bat de novo.
notepad "%PASTA%config_local.cmd"
set AMBIENTE_OK=
exit /b 1

:sempython
echo Nao consegui rodar o Python para gerar o segredo. Confira se o comando "python" funciona.
set AMBIENTE_OK=
exit /b 1

:temconfig
call "%PASTA%config_local.cmd"
if not exist "%PASTA%..\dados" mkdir "%PASTA%..\dados"
for %%d in ("%PASTA%..\dados") do set "DADOS=%%~fd"
set "DATABASE_URL=sqlite:///%DADOS:\=/%/chamados.db"
cd /d "%PASTA%..\api"
if exist ".venv\Scripts\activate.bat" goto :temvenv
echo.
echo Nao achei o ambiente da API (.venv). Na pasta api, rode uma vez:
echo    py -3.12 -m venv .venv
echo    .venv\Scripts\activate
echo    python -m pip install -r requirements.txt
set AMBIENTE_OK=
exit /b 1

:temvenv
call .venv\Scripts\activate.bat
set AMBIENTE_OK=1
exit /b 0
