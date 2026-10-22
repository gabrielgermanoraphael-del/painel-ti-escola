"""Confere o "ID token" que o botão "Entrar com Google" entrega à página.

A página nunca é confiável: tudo é verificado aqui, no servidor.
- assinatura (chaves públicas do Google, RS256)
- aud = o Client ID desta escola (GOOGLE_CLIENT_ID)
- iss = accounts.google.com, token dentro da validade
- e-mail verificado e do domínio institucional (campo "hd" + final do e-mail)
"""
import jwt

from .config import config

CERTS_GOOGLE = "https://www.googleapis.com/oauth2/v3/certs"
EMISSORES = ["accounts.google.com", "https://accounts.google.com"]

_cliente_jwks: jwt.PyJWKClient | None = None


class ErroGoogle(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def cliente_jwks() -> jwt.PyJWKClient:
    global _cliente_jwks
    if _cliente_jwks is None:
        _cliente_jwks = jwt.PyJWKClient(CERTS_GOOGLE, cache_keys=True, lifespan=3600, timeout=10)
    return _cliente_jwks


def verificar_credencial(credencial: str) -> dict:
    if not config.GOOGLE_CLIENT_ID:
        raise ErroGoogle(503, "Login com Google ainda não foi configurado no servidor")
    try:
        chave = cliente_jwks().get_signing_key_from_jwt(credencial).key
    except jwt.PyJWKClientConnectionError:
        raise ErroGoogle(503, "Não foi possível falar com o Google. Tente de novo.") from None
    except jwt.PyJWTError:
        raise ErroGoogle(401, "Login do Google inválido") from None
    try:
        dados = jwt.decode(
            credencial, chave, algorithms=["RS256"], audience=config.GOOGLE_CLIENT_ID, issuer=EMISSORES,
            leeway=30, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.ExpiredSignatureError:
        raise ErroGoogle(401, "O login expirou. Entre de novo.") from None
    except jwt.PyJWTError:
        raise ErroGoogle(401, "Login do Google inválido") from None

    email = str(dados.get("email", "")).strip().lower()
    dominio = config.DOMINIO_PERMITIDO
    if dados.get("email_verified") is not True or not email:
        raise ErroGoogle(403, "E-mail do Google não verificado")
    if str(dados.get("hd", "")).lower() != dominio or not email.endswith("@" + dominio):
        raise ErroGoogle(403, f"Use o seu e-mail institucional (@{dominio})")
    return {"sub": str(dados["sub"]), "email": email,
            "nome": str(dados.get("name") or email.split("@")[0])[:120],
            "foto": str(dados.get("picture") or "")[:400]}
