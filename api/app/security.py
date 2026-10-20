"""Senhas (PBKDF2, biblioteca padrão do Python) e tokens de login (JWT)."""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import config
from .db import get_db
from .models import Usuario

ITERACOES = 600_000
_bearer = HTTPBearer(auto_error=False)


def gerar_hash(senha: str) -> str:
    sal = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, ITERACOES)
    return "pbkdf2_sha256${}${}${}".format(
        ITERACOES, base64.b64encode(sal).decode(), base64.b64encode(dk).decode())


def conferir_senha(senha: str, guardado: str) -> bool:
    try:
        _, it, sal, dk = guardado.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", senha.encode(), base64.b64decode(sal), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def criar_token(u: Usuario) -> tuple[str, datetime]:
    expira = datetime.now(timezone.utc) + timedelta(hours=config.JWT_HORAS)
    token = jwt.encode({"sub": str(u.id), "papel": u.papel, "exp": expira}, config.JWT_SECRET, algorithm="HS256")
    return token, expira


def usuario_atual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                  db: Session = Depends(get_db)) -> Usuario:
    erro = HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login para continuar",
                         headers={"WWW-Authenticate": "Bearer"})
    if cred is None:
        raise erro
    try:
        dados = jwt.decode(cred.credentials, config.JWT_SECRET, algorithms=["HS256"])
        u = db.get(Usuario, int(dados["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise erro
    if not u or not u.ativo:
        raise erro
    return u


def somente_admin(u: Usuario = Depends(usuario_atual)) -> Usuario:
    if u.papel != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Apenas administradores")
    return u
