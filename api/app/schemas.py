from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from .models import TIPOS


def _utc(dt: datetime | None) -> datetime | None:
    """Garante fuso UTC nas datas (o SQLite devolve sem fuso)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class ChamadoNovo(BaseModel):
    """Enviado pela página do QR code."""
    sala: str = Field(min_length=1, max_length=60, description="Valor de ?sala= no link do QR")
    tipo: str = Field(description="Código do tipo: " + ", ".join(TIPOS))
    detalhe: str = Field(default="", max_length=300)

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: str) -> str:
        if v not in TIPOS:
            raise ValueError("tipo inválido")
        return v

    @field_validator("detalhe", "sala")
    @classmethod
    def limpa(cls, v: str) -> str:
        return " ".join(v.split())


class ChamadoManual(BaseModel):
    """Registrado pelo técnico (pedido no corredor, telefone...)."""
    local_id: int
    tipo: str
    detalhe: str = Field(default="", max_length=300)

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: str) -> str:
        if v not in TIPOS:
            raise ValueError("tipo inválido")
        return v


class Resolucao(BaseModel):
    solucao: str = Field(default="", max_length=500)


class Login(BaseModel):
    usuario: str
    senha: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em: datetime
    nome: str
    papel: str


class LocalOut(BaseModel):
    id: int
    codigo: str
    nome: str
    ativo: bool


class LocalNovo(BaseModel):
    codigo: str = Field(min_length=1, max_length=60)
    nome: str = Field(min_length=1, max_length=80)


class ChamadoCriado(BaseModel):
    """Resposta pública: não expõe dados internos."""
    id: int
    local: str
    tipo: str
    tipo_nome: str
    criado_em: datetime
    duplicado: bool = False


class ChamadoOut(BaseModel):
    id: int
    local_id: int
    local: str
    tipo: str
    tipo_nome: str
    detalhe: str
    status: str
    origem: str
    criado_em: datetime
    atendido_em: datetime | None
    resolvido_em: datetime | None
    solucao: str
    atendido_por: str | None
    aberto_por: str | None = None
    aberto_por_email: str | None = None

    @classmethod
    def de(cls, c) -> "ChamadoOut":
        return cls(
            id=c.id, local_id=c.local_id, local=c.local.nome, tipo=c.tipo, tipo_nome=TIPOS.get(c.tipo, c.tipo),
            detalhe=c.detalhe or "", status=c.status, origem=c.origem, criado_em=_utc(c.criado_em),
            atendido_em=_utc(c.atendido_em), resolvido_em=_utc(c.resolvido_em), solucao=c.solucao or "",
            atendido_por=c.atendido_por.nome if c.atendido_por else None,
            aberto_por=c.aberto_por.nome if c.aberto_por else None,
            aberto_por_email=c.aberto_por.email if c.aberto_por else None,
        )


class Estatisticas(BaseModel):
    dias: int
    total: int
    abertos: int
    em_atendimento: int
    resolvidos: int
    tempo_medio_resolucao_min: float | None
    por_tipo: dict[str, int]
    por_local: dict[str, int]
    por_dia: dict[str, int]


# ---------------------------------------------------------------- professores (login Google)
class LoginGoogle(BaseModel):
    credential: str = Field(min_length=20, max_length=4096, description="ID token devolvido pelo botão do Google")


class SalaCurta(BaseModel):
    codigo: str
    nome: str


class PessoaPublica(BaseModel):
    """O que o próprio professor vê sobre si na página do QR."""
    nome: str
    email: str
    foto: str
    codigo: str
    status: str
    todas_salas: bool
    salas: list[SalaCurta]

    @classmethod
    def de(cls, p) -> "PessoaPublica":
        return cls(nome=p.nome, email=p.email, foto=p.foto or "", codigo=p.codigo, status=p.status,
                   todas_salas=p.todas_salas, salas=[SalaCurta(codigo=s.codigo, nome=s.nome) for s in p.salas])


class SessaoProfessor(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em: datetime
    pessoa: PessoaPublica


class PessoaOut(BaseModel):
    """Visão do TI."""
    id: int
    nome: str
    email: str
    foto: str
    codigo: str
    status: str
    todas_salas: bool
    salas: list[LocalOut]
    criado_em: datetime
    ultimo_login: datetime | None
    liberado_em: datetime | None
    liberado_por: str | None

    @classmethod
    def de(cls, p) -> "PessoaOut":
        return cls(id=p.id, nome=p.nome, email=p.email, foto=p.foto or "", codigo=p.codigo, status=p.status,
                   todas_salas=p.todas_salas,
                   salas=[LocalOut(id=s.id, codigo=s.codigo, nome=s.nome, ativo=s.ativo) for s in p.salas],
                   criado_em=_utc(p.criado_em), ultimo_login=_utc(p.ultimo_login), liberado_em=_utc(p.liberado_em),
                   liberado_por=p.liberado_por.nome if p.liberado_por else None)


class AcessoPessoa(BaseModel):
    """Definido pelo TI: libera, bloqueia e escolhe as salas."""
    status: str = Field(pattern="^(pendente|ativo|bloqueado)$")
    todas_salas: bool = False
    salas: list[int] = Field(default_factory=list, max_length=200, description="IDs dos locais (GET /locais)")


class UsuarioOut(BaseModel):
    id: int
    usuario: str
    nome: str
    papel: str
    ativo: bool


class UsuarioAtualizar(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=80)
    papel: str | None = Field(default=None, pattern="^(tecnico|admin)$")
    ativo: bool | None = None
    senha: str | None = Field(default=None, min_length=8, max_length=128)
