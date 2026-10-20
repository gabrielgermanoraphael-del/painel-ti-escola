from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
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


# Salas em que cada professor pode abrir chamado
pessoa_sala = Table(
    "pessoa_sala", Base.metadata,
    Column("pessoa_id", ForeignKey("pessoas.id", ondelete="CASCADE"), primary_key=True),
    Column("local_id", ForeignKey("locais.id", ondelete="CASCADE"), primary_key=True),
)

STATUS_PESSOA = ("pendente", "ativo", "bloqueado")


class Pessoa(Base):
    """Professor/funcionário que entra com a conta Google institucional pela página do QR."""
    __tablename__ = "pessoas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120))
    foto: Mapped[str] = mapped_column(String(400), default="")
    codigo: Mapped[str] = mapped_column(String(10), unique=True, index=True)  # código de vínculo
    status: Mapped[str] = mapped_column(String(12), default="pendente", index=True)
    todas_salas: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    liberado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    liberado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)

    salas: Mapped[list[Local]] = relationship(secondary=pessoa_sala, lazy="selectin", order_by="Local.id")
    liberado_por: Mapped[Usuario | None] = relationship(lazy="joined")

    def pode_abrir_em(self, local: Local) -> bool:
        return self.status == "ativo" and (self.todas_salas or any(s.id == local.id for s in self.salas))


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
    aberto_por_id: Mapped[int | None] = mapped_column(ForeignKey("pessoas.id"), nullable=True)

    local: Mapped[Local] = relationship(lazy="joined")
    atendido_por: Mapped[Usuario | None] = relationship(lazy="joined")
    aberto_por: Mapped["Pessoa | None"] = relationship(lazy="joined")
