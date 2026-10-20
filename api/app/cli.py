"""Comandos de administração.

    python -m app.cli criar-usuario gabriel "Gabriel" --admin
    python -m app.cli listar-usuarios
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import Usuario
from .security import gerar_hash
from .seed import semear_locais


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("criar-usuario", help="cria um técnico (ou admin)")
    c.add_argument("usuario")
    c.add_argument("nome")
    c.add_argument("--admin", action="store_true")
    sub.add_parser("listar-usuarios")
    a = p.parse_args(argv)

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        semear_locais(db)
        if a.cmd == "listar-usuarios":
            for u in db.scalars(select(Usuario)):
                print(f"{u.usuario:15} {u.papel:8} {'ativo' if u.ativo else 'inativo':8} {u.nome}")
            return
        login = a.usuario.lower()
        if db.scalar(select(Usuario).where(Usuario.usuario == login)):
            sys.exit(f"O usuário '{login}' já existe.")
        senha = getpass.getpass("Senha (mín. 8 caracteres): ")
        if len(senha) < 8 or senha != getpass.getpass("Repita a senha: "):
            sys.exit("Senha curta ou não confere.")
        db.add(Usuario(usuario=login, nome=a.nome, senha_hash=gerar_hash(senha),
                       papel="admin" if a.admin else "tecnico"))
        db.commit()
        print(f"Usuário '{login}' criado ({'admin' if a.admin else 'técnico'}).")


if __name__ == "__main__":
    main()
