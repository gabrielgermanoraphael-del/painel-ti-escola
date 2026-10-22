"""
Cria o atalho "Painel do TI" na área de trabalho (Windows).
Rode uma vez, no cmd aberto nesta pasta:   python criar_atalho.py
"""

import os
import subprocess
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent


def tem_streamlit(python: Path) -> bool:
    try:
        return subprocess.run([str(python), "-c", "import streamlit"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# Prefere o ambiente da API (api\.venv), que é o mesmo do servidor; se não tiver Streamlit, usa o Python atual
candidatos = [PASTA / "api" / ".venv" / "Scripts" / "python.exe", Path(sys.executable).with_name("python.exe"), Path(sys.executable)]
python = next((c for c in candidatos if c.exists() and tem_streamlit(c)), None)
if python is None:
    venv = PASTA / "api" / ".venv" / "Scripts" / "python.exe"
    print("Nenhum Python com o Streamlit instalado foi encontrado.")
    print("Instale no ambiente da API e rode este script de novo:")
    print(f'  "{venv}" -m pip install -r "{PASTA / "requirements.txt"}"')
    sys.exit(1)
pythonw = python.with_name("pythonw.exe")
if not pythonw.exists():
    pythonw = python  # sem pythonw: funciona igual, só pode piscar uma janela
print("Usando:", pythonw)

# Os caminhos vão por variáveis de ambiente para não ter problema com espaços e acentos
env = dict(os.environ,
           AT_ALVO=str(pythonw),
           AT_ARGS=f'"{PASTA / "abrir_painel.pyw"}"',
           AT_PASTA=str(PASTA),
           AT_ICONE=str(PASTA / "painel.ico"))

ps = (
    "$desk = [Environment]::GetFolderPath('Desktop');"
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desk 'Painel do TI.lnk'));"
    "$s.TargetPath = $env:AT_ALVO; $s.Arguments = $env:AT_ARGS;"
    "$s.WorkingDirectory = $env:AT_PASTA; $s.IconLocation = $env:AT_ICONE;"
    "$s.Description = 'Monitor de APs e Chamados do TI'; $s.Save();"
    "Write-Output (Join-Path $desk 'Painel do TI.lnk')"
)

try:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, env=env, timeout=30)
    ok = r.returncode == 0 and r.stdout.strip()
except (OSError, subprocess.TimeoutExpired) as e:
    ok, r = False, None
    print("Erro:", e)

if ok:
    print("Atalho criado em:", r.stdout.strip())
    print("Agora é só dar dois cliques em 'Painel do TI' na área de trabalho.")
else:
    if r is not None and r.stderr:
        print(r.stderr.strip())
    print("\nNão consegui criar o atalho automaticamente. Faça manualmente:")
    print(f"  1. Botão direito na área de trabalho > Novo > Atalho")
    print(f'  2. No local do item, cole:  "{pythonw}" "{PASTA / "abrir_painel.pyw"}"')
    print(f"  3. Nome: Painel do TI  >  Concluir")
    print(f"  4. Botão direito no atalho > Propriedades > Alterar ícone > escolha {PASTA / 'painel.ico'}")
