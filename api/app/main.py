"""API de Chamados do TI.

Professores (login Google institucional): POST /auth/google, GET /professor/eu, POST /chamados
Técnicos (usuário e senha):               /chamados, /pessoas, /estatisticas, /locais ...
Administradores do TI:                    /usuarios, criação e edição de locais
Documentação interativa:       /docs
"""
import logging
import os
import secrets
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from . import schemas as S
from .config import config
from .db import Base, SessionLocal, engine, get_db
from .limite import limite_ip
from .google_auth import ErroGoogle, verificar_credencial
from .models import STATUS, TIPOS, Chamado, Local, Pessoa, Usuario, agora
from .notificar import notificar_ntfy
from .security import (conferir_senha, criar_token, criar_token_professor, gerar_hash, professor_atual,
                       somente_admin, usuario_atual)
from .seed import semear_locais

logging.basicConfig(level=logging.INFO)


def _migrar_colunas():
    """Bancos criados antes do login Google não têm a coluna chamados.aberto_por_id."""
    colunas = {c["name"] for c in inspect(engine).get_columns("chamados")}
    if "aberto_por_id" not in colunas:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE chamados ADD COLUMN aberto_por_id INTEGER REFERENCES pessoas(id)"))


@asynccontextmanager
async def ciclo(app: FastAPI):
    if not os.getenv("JWT_SECRET"):
        logging.getLogger("chamados").warning(
            "JWT_SECRET não definido: os logins valem só até o servidor reiniciar. Defina em produção.")
    Base.metadata.create_all(engine)
    _migrar_colunas()
    with SessionLocal() as db:
        semear_locais(db)
    yield


app = FastAPI(
    title="API de Chamados do TI",
    version="1.1.0",
    description="Recebe os chamados abertos pelos QR codes das salas e permite ao TI acompanhar o atendimento.",
    lifespan=ciclo,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
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


@app.get("/config/publica", tags=["público"])
def config_publica():
    """Dados que a página do QR precisa para mostrar o botão do Google."""
    return {"google_client_id": config.GOOGLE_CLIENT_ID, "dominio": config.DOMINIO_PERMITIDO}


# ---------------------------------------------------------------- professores
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O e 1/I, que se confundem


def novo_codigo(db: Session) -> str:
    while True:
        bruto = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(6))
        codigo = f"{bruto[:3]}-{bruto[3:]}"
        if not db.scalar(select(Pessoa.id).where(Pessoa.codigo == codigo)):
            return codigo


def normalizar_codigo(codigo: str) -> str:
    bruto = "".join(ch for ch in codigo.upper() if ch.isalnum())
    return f"{bruto[:3]}-{bruto[3:]}" if len(bruto) == 6 else bruto


@app.post("/auth/google", tags=["professores"], response_model=S.SessaoProfessor)
def login_google(dados: S.LoginGoogle, request: Request, db: Session = Depends(get_db)):
    """Recebe o token do botão "Entrar com Google". Só aceita o domínio institucional.
    No primeiro acesso a pessoa fica "pendente" e recebe um código para o TI liberar."""
    if not limite_ip.permitir("google:" + ip_do_cliente(request), 30, 300):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas. Aguarde alguns minutos.")
    try:
        g = verificar_credencial(dados.credential)
    except ErroGoogle as e:
        raise HTTPException(e.status, e.mensagem) from None

    p = db.scalar(select(Pessoa).where(Pessoa.google_sub == g["sub"]))
    if p is None:
        p = db.scalar(select(Pessoa).where(Pessoa.email == g["email"]))
        if p is not None and p.google_sub != g["sub"]:
            # mesmo e-mail com outra conta Google (conta recriada): mantém os acessos, mas volta a pendente
            p.google_sub, p.status = g["sub"], "pendente"
    if p is None:
        p = Pessoa(google_sub=g["sub"], email=g["email"], nome=g["nome"], foto=g["foto"],
                   codigo=novo_codigo(db), status="pendente")
        db.add(p)
    p.email, p.nome, p.foto, p.ultimo_login = g["email"], g["nome"], g["foto"], agora()
    db.commit()
    db.refresh(p)
    token, expira = criar_token_professor(p)
    return S.SessaoProfessor(access_token=token, expira_em=expira, pessoa=S.PessoaPublica.de(p))


@app.get("/professor/eu", tags=["professores"], response_model=S.PessoaPublica)
def professor_eu(p: Pessoa = Depends(professor_atual)):
    """Situação do professor logado: pendente, ativo (com as salas liberadas) ou bloqueado."""
    return S.PessoaPublica.de(p)


@app.post("/chamados", tags=["professores"], response_model=S.ChamadoCriado, status_code=status.HTTP_201_CREATED)
def abrir_chamado(dados: S.ChamadoNovo, request: Request, tarefas: BackgroundTasks,
                  db: Session = Depends(get_db), p: Pessoa = Depends(professor_atual)):
    """Abre um chamado pelo QR code da sala. Precisa do login Google e de acesso liberado à sala."""
    if p.status == "pendente":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Seu acesso ainda não foi liberado. Passe o código {p.codigo} para o TI.")
    if p.status != "ativo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu acesso está bloqueado. Procure o TI.")
    if not limite_ip.permitir(f"pessoa:{p.id}", config.LIMITE_POR_PESSOA, config.JANELA_IP_SEG) or \
            not limite_ip.permitir("ip:" + ip_do_cliente(request), config.LIMITE_POR_IP, config.JANELA_IP_SEG):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Muitos chamados em pouco tempo. Aguarde alguns minutos ou procure o TI pessoalmente.")
    local = buscar_local(db, dados.sala)
    if not local:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sala não cadastrada")
    if not p.pode_abrir_em(local):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Você não tem acesso para abrir chamado em {local.nome}. Peça ao TI para liberar.")

    # Mesmo pedido repetido em poucos minutos: devolve o chamado que já está aberto
    limite = agora() - timedelta(seconds=config.JANELA_DUPLICADO_SEG)
    repetido = db.scalar(select(Chamado).where(
        Chamado.local_id == local.id, Chamado.tipo == dados.tipo, Chamado.status != "resolvido",
        Chamado.criado_em >= limite).order_by(Chamado.id.desc()))
    if repetido:
        return S.ChamadoCriado(id=repetido.id, local=local.nome, tipo=repetido.tipo, tipo_nome=TIPOS[repetido.tipo],
                               criado_em=S._utc(repetido.criado_em), duplicado=True)

    c = Chamado(local_id=local.id, tipo=dados.tipo, detalhe=dados.detalhe, origem="qrcode", aberto_por_id=p.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    texto = (c.detalhe + "\n" if c.detalhe else "") + f"Aberto por {p.nome} · chamado #{c.id}"
    tarefas.add_task(notificar_ntfy, f"{local.nome}: {TIPOS[c.tipo]}", texto, ["bell"], 4)
    return S.ChamadoCriado(id=c.id, local=local.nome, tipo=c.tipo, tipo_nome=TIPOS[c.tipo],
                           criado_em=S._utc(c.criado_em))


# ---------------------------------------------------------------- liberação dos professores (TI)
def buscar_pessoa(db: Session, id_: int) -> Pessoa:
    p = db.get(Pessoa, id_)
    if not p:
        raise HTTPException(404, "Pessoa não encontrada")
    return p


@app.get("/pessoas", tags=["liberação de professores"], response_model=list[S.PessoaOut])
def listar_pessoas(status_: str | None = Query(None, alias="status", pattern="^(pendente|ativo|bloqueado)$"),
                   db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)):
    q = select(Pessoa)
    if status_:
        q = q.where(Pessoa.status == status_)
    return [S.PessoaOut.de(p) for p in db.scalars(q.order_by(Pessoa.nome)).unique()]


@app.get("/pessoas/codigo/{codigo}", tags=["liberação de professores"], response_model=S.PessoaOut)
def pessoa_por_codigo(codigo: str, db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)):
    """Busca o professor pelo código que apareceu no celular dele (aceita com ou sem traço)."""
    p = db.scalar(select(Pessoa).where(Pessoa.codigo == normalizar_codigo(codigo)))
    if not p:
        raise HTTPException(404, "Nenhum professor com esse código. Confira com ele.")
    return S.PessoaOut.de(p)


@app.put("/pessoas/{id_}/acesso", tags=["liberação de professores"], response_model=S.PessoaOut)
def definir_acesso(id_: int, dados: S.AcessoPessoa, db: Session = Depends(get_db),
                   u: Usuario = Depends(usuario_atual)):
    """Libera, bloqueia e define em quais salas o professor pode abrir chamado."""
    p = buscar_pessoa(db, id_)
    ids = set(dados.salas)
    salas = list(db.scalars(select(Local).where(Local.id.in_(ids)))) if ids else []
    if len(salas) != len(ids):
        raise HTTPException(422, "Alguma sala informada não existe")
    if dados.status == "ativo" and not dados.todas_salas and not salas:
        raise HTTPException(422, "Escolha pelo menos uma sala (ou todas) para liberar o acesso")
    if dados.status == "ativo" and p.status != "ativo":
        p.liberado_em, p.liberado_por = agora(), u
    p.status, p.todas_salas, p.salas = dados.status, dados.todas_salas, salas
    db.commit()
    db.refresh(p)
    return S.PessoaOut.de(p)


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


@app.get("/usuarios", tags=["administração"], response_model=list[S.UsuarioOut])
def listar_usuarios(db: Session = Depends(get_db), _: Usuario = Depends(somente_admin)):
    return [S.UsuarioOut(id=u.id, usuario=u.usuario, nome=u.nome, papel=u.papel, ativo=u.ativo)
            for u in db.scalars(select(Usuario).order_by(Usuario.nome))]


@app.patch("/usuarios/{id_}", tags=["administração"], response_model=S.UsuarioOut)
def atualizar_usuario(id_: int, dados: S.UsuarioAtualizar, db: Session = Depends(get_db),
                      eu_: Usuario = Depends(somente_admin)):
    """Troca nome, papel (tecnico/admin), senha ou desativa uma conta do TI."""
    u = db.get(Usuario, id_)
    if not u:
        raise HTTPException(404, "Usuário não encontrado")
    if u.id == eu_.id and (dados.ativo is False or dados.papel == "tecnico"):
        raise HTTPException(409, "Você não pode tirar o seu próprio acesso de administrador")
    if dados.nome is not None:
        u.nome = dados.nome.strip()
    if dados.papel is not None:
        u.papel = dados.papel
    if dados.ativo is not None:
        u.ativo = dados.ativo
    if dados.senha is not None:
        u.senha_hash = gerar_hash(dados.senha)
    db.commit()
    return S.UsuarioOut(id=u.id, usuario=u.usuario, nome=u.nome, papel=u.papel, ativo=u.ativo)
