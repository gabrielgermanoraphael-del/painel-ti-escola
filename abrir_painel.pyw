"""
Abre o Painel do TI (Streamlit) com um clique, sem janela preta.

- Se o painel já estiver rodando, só abre a página no navegador.
- Se não estiver, liga o painel escondido e abre o navegador quando ele estiver pronto.

Use pelo atalho da área de trabalho (crie com:  python criar_atalho.py).
"""

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PORTA = 8501
ENDERECO = f"http://localhost:{PORTA}"
PASTA = Path(__file__).resolve().parent
LOG = PASTA / "painel_erros.log"


def porta_aberta():
    try:
        with socket.create_connection(("127.0.0.1", PORTA), timeout=1):
            return True
    except OSError:
        return False


def avisar_erro(msg):
    try:
        import tkinter
        from tkinter import messagebox
        raiz = tkinter.Tk()
        raiz.withdraw()
        messagebox.showerror("Painel do TI", msg)
        raiz.destroy()
    except Exception:  # noqa: BLE001
        pass


def main():
    if porta_aberta():
        webbrowser.open(ENDERECO)
        return

    # Usa o python.exe (não o pythonw) para rodar o Streamlit, mas sem abrir janela
    exe = Path(sys.executable)
    python = exe.with_name("python.exe") if exe.name.lower() == "pythonw.exe" else exe
    if not python.exists():
        python = exe

    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    with open(LOG, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(python), "-m", "streamlit", "run", str(PASTA / "painel.py"),
             "--server.headless", "true", "--server.port", str(PORTA)],
            cwd=PASTA, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
        )

    for _ in range(60):  # espera até 30 segundos
        time.sleep(0.5)
        if porta_aberta():
            webbrowser.open(ENDERECO)
            return
        if proc.poll() is not None:  # o Streamlit fechou com erro: não precisa esperar mais
            break

    detalhe = ""
    try:
        detalhe = LOG.read_text(encoding="utf-8", errors="ignore")[-600:]
    except OSError:
        pass
    if "No module named streamlit" in detalhe:
        dica = "O Streamlit não está instalado.\nNo cmd, rode:  python -m pip install streamlit"
    else:
        dica = "O painel não abriu em 30 segundos."
    avisar_erro(f"{dica}\n\nDetalhes em: {LOG}\n\n{detalhe}")


if __name__ == "__main__":
    main()
