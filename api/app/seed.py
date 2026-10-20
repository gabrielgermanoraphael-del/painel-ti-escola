"""Locais iniciais: os mesmos códigos já impressos nos QR codes (?sala=...)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Local

LOCAIS_INICIAIS = [(str(n), f"Sala {n}") for n in range(1, 9)] + [
    ("11", "Sala 11"),
    ("12", "Sala 12"),
    ("Sala 13 (IPP)", "Sala 13 (IPP)"),
    ("secretaria", "Secretaria"),
    ("professores", "Sala dos Professores"),
    ("Coordenação", "Coordenação"),
]


def semear_locais(db: Session) -> int:
    """Cadastra os locais só na primeira vez (tabela vazia)."""
    if db.scalar(select(func.count()).select_from(Local)):
        return 0
    db.add_all(Local(codigo=c, nome=n) for c, n in LOCAIS_INICIAIS)
    db.commit()
    return len(LOCAIS_INICIAIS)
