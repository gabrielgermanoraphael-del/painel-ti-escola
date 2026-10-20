"""API de Chamados do TI.

Público (página do QR code):  POST /chamados
Técnicos (com login):          /chamados, /estatisticas, /locais ...
Documentação interativa:       /docs
"""
import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import schemas as S
from .config import config
from .db import Base, SessionLocal, engine, get_db
from .limite import limite_ip
from .models import STATUS, TIPOS, Chamado, Local, Usuario, agora
from .notificar import notificar_ntfy
from .security import conferir_senha, criar_token, gerar_hash, somente_admin, usuario_atual
from .seed import semear_locais

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def ciclo(app: FastAPI):
    if not os.getenv("JWT_SECRET"):
        logging.getLogger("chamados").warning(
            "JWT_SECRET não definido: os logins valem só até o servidor reiniciar. Defina em produção.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        semear_locais(db)
    yield


app = FastAPI(
    title="API de Chamados do TI",
    version="1.0.0",
    description="Recebe os chamados abertos pelos QR codes das salas e permite ao TI acompanhar o atendimento.",
    lifespan=ciclo,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)


def ip_do_cliente(request: Request) -> str:
    # Na nuvem a requisição passa por um proxy, que acrescenta o IP real no fim do X-Forwarded-For
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "?"


def buscar_local(db: Session, codigo: str) -> Local | None:
    local = db.scalar(select(Local).where(Local.codigo == codigo, Local.ativo.is_(True)))
    if local:
        return local
    alvo = codigo.strip().casefold()
    for l in db.scalars(select(Local).where(Local.ativo.is_(True))):
        if l.codigo.casefold() == alvo:
            return l
    return None


def buscar_chamado(db: Session, id_: int) -> Chamado:
    c = db.get(Chamado, id_)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chamado não encontrado")
    return c


# ---------------------------------------------------------------- público
@app.get("/", include_in_schema=False)
def raiz():
    return {"servico": "API de Chamados do TI", "documentacao": "/docs"}


@app.get("/saude", tags=["público"])
def saude(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"ok": True, "hora": agora()}


@app.get("/locais/publico/{codigo}", tags=["público"], response_model=S.LocalOut)
def local_publico(codigo: str, db: Session = Depends(get_db)):
    local = buscar_local(db, codigo)
    if not local:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Local não cadastrado")
    return S.LocalOut(id=local.id, codigo=local.codigo, nome=local.nome, ativo=local.ativo)


@app.post("/chamados", tags=["público"], response_model=S.ChamadoCriado, status_code=status.HTTP_201_CREATED)
def abrir_chamado(dados: S.ChamadoNovo, request: Request, tarefas: BackgroundTasks,
                  db: Session = Depends(get_db)):
    """Abre um chamado a partir do QR code da sala (não precisa de login)."""
    if not limite_ip.permitir(ip_do_cliente(request), config.LIMITE_POR_IP, config.JANELA_IP_SEG):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Muitos chamados em pouco tempo. Aguarde alguns minutos ou procure o TI pessoalmente.")
    local = buscar_local(db, dados.sala)
    if not local:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala não cadastrada")

    # Mesmo pedido repetido em poucos minutos: devolve o chamado que já está aberto
    limite = agora() - timedelta(seconds=config.JANELA_DUPLICADO_SEG)
    repetido = db.scalar(select(Chamado).where(
        Chamado.local_id == local.id, Chamado.tipo == dados.tipo, Chamado.status != "resolvido",
        Chamado.criado_em >= limite).order_by(Chamado.id.desc()))
    if repetido:
        return S.ChamadoCriado(id=repetido.id, local=local.nome, tipo=repetido.tipo, tipo_nome=TIPOS[repetido.tipo],
                               criado_em=S._utc(repetido.criado_em), duplicado=True)

    c = Chamado(local_id=local.id, tipo=dados.tipo, detalhe=dados.detalhe, origem="qrcode")
    db.add(c)
    db.commit()
    db.refresh(c)
    tarefas.add_task(notificar_ntfy, f"{local.nome}: {TIPOS[c.tipo]}",
                     c.detalhe or f"Chamado #{c.id}", ["bell"], 4)
    return S.ChamadoCriado(id=c.id, local=local.nome, tipo=c.tipo, tipo_nome=TIPOS[c.tipo],
                           criado_em=S._utc(c.criado_em))


# ---------------------------------------------------------------- login
@app.post("/auth/login", tags=["login"], response_model=S.Token)
def login(dados: S.Login, request: Request, db: Session = Depends(get_db)):
    if not limite_ip.permitir("login:" + ip_do_cliente(request), 10, 300):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas. Aguarde 5 minutos.")
    u = db.scalar(select(Usuario).where(Usuario.usuario == dados.usuario.strip().lower()))
    if not u or not u.ativo or not conferir_senha(dados.senha, u.senha_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário ou senha incorretos")
    token, expira = criar_token(u)
    return S.Token(access_token=token, expira_em=expira, nome=u.nome, papel=u.papel)


@app.get("/eu", tags=["login"])
def eu(u: Usuario = Depends(usuario_atual)):
    return {"usuario": u.usuario, "nome": u.nome, "papel": u.papel}


# ---------------------------------------------------------------- chamados (TI)
@app.get("/chamados", tags=["chamados"], response_model=list[S.ChamadoOut])
def listar(status_: list[str] | None = Query(None, alias="status", description="aberto, atendimento, resolvido"),
           desde: datetime | None = None, ate: datetime | None = None, local_id: int | None = None,
           limite: int = Query(200, ge=1, le=1000),
           db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)):
    q = select(Chamado)
    if status_:
        invalidos = set(status_) - set(STATUS)
        if invalidos:
            raise HTTPException(422, f"Status inválido: {', '.join(invalidos)}")
        q = q.where(Chamado.status.in_(status_))
    if desde:
        q = q.where(Chamado.criado_em >= desde)
    if ate:
        q = q.where(Chamado.criado_em <= ate)
    if local_id:
        q = q.where(Chamado.local_id == local_id)
    q = q.order_by(Chamado.criado_em.desc(), Chamado.id.desc()).limit(limite)
    return [S.ChamadoOut.de(c) for c in db.scalars(q).unique()]


@app.get("/chamados/{id_}", tags=["chamados"], response_model=S.ChamadoOut)
def detalhe(id_: int, db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)):
    return S.ChamadoOut.de(buscar_chamado(db, id_))


@app.post("/chamados/manual", tags=["chamados"], response_model=S.ChamadoOut, status_code=201)
def manual(dados: S.ChamadoManual, db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)):
    """Registra um pedido feito pessoalmente ou por telefone."""
    local = db.get(Local, dados.local_id)
    if not local:
        raise HTTPException(404, "Local não encontrado")
    c = Chamado(local_id=local.id, tipo=dados.tipo, detalhe=dados.detalhe, origem="manual")
    db.add(c)
    db.commit()
    db.refresh(c)
    return S.ChamadoOut.de(c)


@app.post("/chamados/{id_}/atender", tags=["chamados"], response_model=S.ChamadoOut)
def atender(id_: int, db: Session = Depends(get_db), u: Usuario = Depends(usuario_atual)):
    c = buscar_chamado(db, id_)
    if c.status == "resolvido":
        raise HTTPException(409, "Chamado já resolvido. Reabra antes de atender.")
    c.status = "atendimento"
    c.atendido_em = c.atendido_em or agora()
    c.atendido_por = u
    db.commit()
    return S.ChamadoOut.de(c)


@app.post("/chamados/{id_}/resolver", tags=["chamados"], response_model=S.ChamadoOut)
def resolver(id_: int, dados: S.Resolucao, db: Session = Depends(get_db), u: Usuario = Depends(usuario_atual)):
    c = buscar_chamado(db, id_)
    c.status = "resolvido"
    c.atendido_em = c.atendido_em or agora()
    c.resolvido_em = agora()
    c.solucao = dados.solucao.strip()
    if c.atendido_por is None:
        c.atendido_por = u
    db.commit()
    return S.ChamadoOut.de(c)


@app.post("/chamados/{id_}/reabrir", tags=["chamados"], response_model=S.ChamadoOut)
def reabrir(id_: int, db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)):
    c = buscar_chamado(db, id_)
    c.status = "aberto"
    c.resolvido_em = None
    db.commit()
    return S.ChamadoOut.de(c)


@app.get("/estatisticas", tags=["chamados"], response_model=S.Estatisticas)
def estatisticas(dias: int = Query(30, ge=1, le=730), db: Session = Depends(get_db),
                 _: Usuario = Depends(usuario_atual)):
    inicio = agora() - timedelta(days=dias)
    lista = list(db.scalars(select(Chamado).where(Chamado.criado_em >= inicio)).unique())
    fuso = ZoneInfo(config.FUSO)
    tempos = [(S._utc(c.resolvido_em) - S._utc(c.criado_em)).total_seconds() / 60
              for c in lista if c.status == "resolvido" and c.resolvido_em]
    return S.Estatisticas(
        dias=dias, total=len(lista),
        abertos=sum(c.status == "aberto" for c in lista),
        em_atendimento=sum(c.status == "atendimento" for c in lista),
        resolvidos=sum(c.status == "resolvido" for c in lista),
        tempo_medio_resolucao_min=round(sum(tempos) / len(tempos), 1) if tempos else None,
        por_tipo=dict(Counter(TIPOS.get(c.tipo, c.tipo) for c in lista).most_common()),
        por_local=dict(Counter(c.local.nome for c in lista).most_common()),
        por_dia=dict(sorted(Counter(S._utc(c.criado_em).astimezone(fuso).date().isoformat() for c in lista).items())),
    )


# ---------------------------------------------------------------- locais e usuários
@app.get("/locais", tags=["administração"], response_model=list[S.LocalOut])
def listar_locais(db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)):
    return [S.LocalOut(id=l.id, codigo=l.codigo, nome=l.nome, ativo=l.ativo)
            for l in db.scalars(select(Local).order_by(Local.id))]


@app.post("/locais", tags=["administração"], response_model=S.LocalOut, status_code=201)
def criar_local(dados: S.LocalNovo, db: Session = Depends(get_db), _: Usuario = Depends(somente_admin)):
    if db.scalar(select(func.count()).select_from(Local).where(Local.codigo == dados.codigo)):
        raise HTTPException(409, "Já existe um local com esse código")
    l = Local(codigo=dados.codigo.strip(), nome=dados.nome.strip())
    db.add(l)
    db.commit()
    return S.LocalOut(id=l.id, codigo=l.codigo, nome=l.nome, ativo=l.ativo)


class LocalAtualizar(BaseModel):
    nome: str | None = Field(default=None, max_length=80)
    ativo: bool | None = None


@app.patch("/locais/{id_}", tags=["administração"], response_model=S.LocalOut)
def atualizar_local(id_: int, dados: LocalAtualizar, db: Session = Depends(get_db),
                    _: Usuario = Depends(somente_admin)):
    l = db.get(Local, id_)
    if not l:
        raise HTTPException(404, "Local não encontrado")
    if dados.nome is not None:
        l.nome = dados.nome.strip()
    if dados.ativo is not None:
        l.ativo = dados.ativo
    db.commit()
    return S.LocalOut(id=l.id, codigo=l.codigo, nome=l.nome, ativo=l.ativo)


class UsuarioNovo(BaseModel):
    usuario: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9._-]+$")
    nome: str = Field(min_length=1, max_length=80)
    senha: str = Field(min_length=8, max_length=128)
    papel: str = Field(default="tecnico", pattern="^(tecnico|admin)$")


@app.post("/usuarios", tags=["administração"], status_code=201)
def criar_usuario(dados: UsuarioNovo, db: Session = Depends(get_db), _: Usuario = Depends(somente_admin)):
    login_ = dados.usuario.lower()
    if db.scalar(select(func.count()).select_from(Usuario).where(Usuario.usuario == login_)):
        raise HTTPException(409, "Usuário já existe")
    u = Usuario(usuario=login_, nome=dados.nome, senha_hash=gerar_hash(dados.senha), papel=dados.papel)
    db.add(u)
    db.commit()
    return {"id": u.id, "usuario": u.usuario, "nome": u.nome, "papel": u.papel}
