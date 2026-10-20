from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


# Tipos de chamado aceitos (código enviado pela página -> nome exibido)
TIPOS = {
    "internet": "Internet / Wi-Fi",
    "chave": "Chave do carrinho de tablets",
    "lousa": "Lousa digital",
    "projetor": "Projetor",
    "computador": "Computador / notebook",
    "som": "Som",
    "tablet": "Tablet de aluno",
    "impressora": "Impressora",
    "outro": "Outro",
}
STATUS = ("aberto", "atendimento", "resolvido")


class Local(Base):
    """Sala ou setor que tem um QR code. 'codigo' é o valor de ?sala= no link."""
    __tablename__ = "locais"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(80))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(80))
    senha_hash: Mapped[str] = mapped_column(String(200))
    papel: Mapped[str] = mapped_column(String(20), default="tecnico")  # tecnico | admin
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Chamado(Base):
    __tablename__ = "chamados"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locais.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    detalhe: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(15), default="aberto", index=True)
    origem: Mapped[str] = mapped_column(String(15), default="qrcode")  # qrcode | manual
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    atendido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    solucao: Mapped[str] = mapped_column(Text, default="")
    atendido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    local: Mapped[Local] = relationship(lazy="joined")
    atendido_por: Mapped[Usuario | None] = relationship(lazy="joined")
