"""Copia o banco SQLite com segurança (mesmo com a API ligada). Um arquivo por dia; guarda os últimos 30."""
import sqlite3, sys
from datetime import date
from pathlib import Path

dados = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "dados"
banco = dados / "chamados.db"
if not banco.exists():
    print("Backup: banco ainda não existe (primeira vez).")
    sys.exit(0)
pasta = dados / "backup"
pasta.mkdir(exist_ok=True)
destino = pasta / f"chamados_{date.today().isoformat()}.db"
if not destino.exists():
    with sqlite3.connect(banco) as origem, sqlite3.connect(destino) as copia:
        origem.backup(copia)
    print(f"Backup salvo: {destino}")
antigos = sorted(pasta.glob("chamados_*.db"))[:-30]
for a in antigos:
    a.unlink()
