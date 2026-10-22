"""Configuração lida das variáveis de ambiente (veja o .env.example)."""
import os
import secrets


def _lista(valor: str) -> list[str]:
    return [v.strip() for v in valor.split(",") if v.strip()]


class Config:
    # Banco de dados. Ex.: postgresql+psycopg://usuario:senha@host:5432/chamados
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./chamados_dev.db")
    # Serviços como Neon/Render entregam "postgres://..." ou "postgresql://...": usa o driver psycopg 3
    for _prefixo in ("postgres://", "postgresql://"):
        if DATABASE_URL.startswith(_prefixo):
            DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(_prefixo):]

    # Assinatura dos tokens de login. Em produção, defina um valor longo e secreto.
    JWT_SECRET: str = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
    JWT_HORAS: int = int(os.getenv("JWT_HORAS", "12"))

    # Sites que podem chamar a API pelo navegador (a página do QR code).
    CORS_ORIGINS: list[str] = _lista(os.getenv(
        "CORS_ORIGINS", "https://gabrielgermanoraphael-del.github.io"))

    # Notificação no celular do técnico (ntfy). O tópico fica só no servidor.
    NTFY_URL: str = os.getenv("NTFY_URL", "https://ntfy.sh")
    NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "")      # vazio = não notifica
    NTFY_TOKEN: str = os.getenv("NTFY_TOKEN", "")      # opcional (servidor ntfy próprio)

    # Proteção contra abuso no endpoint público
    # Na escola todos os celulares saem pelo mesmo IP: o limite principal é por professor
    LIMITE_POR_PESSOA: int = int(os.getenv("LIMITE_POR_PESSOA", "10"))  # chamados por professor...
    LIMITE_POR_IP: int = int(os.getenv("LIMITE_POR_IP", "60"))          # ...e por IP...
    JANELA_IP_SEG: int = int(os.getenv("JANELA_IP_SEG", "600"))         # ...a cada 10 min
    JANELA_DUPLICADO_SEG: int = int(os.getenv("JANELA_DUPLICADO_SEG", "120"))

    # Login dos professores com Google
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    DOMINIO_PERMITIDO: str = os.getenv("DOMINIO_PERMITIDO", "educ.indaiatuba.sp.gov.br").lower()
    PROFESSOR_TOKEN_DIAS: int = int(os.getenv("PROFESSOR_TOKEN_DIAS", "30"))

    # O professor confirma se o chamado foi resolvido; sem resposta nesse prazo, confirma sozinho
    CONFIRMACAO_HORAS: int = int(os.getenv("CONFIRMACAO_HORAS", "48"))

    # Fuso usado nas estatísticas por dia
    FUSO: str = os.getenv("FUSO", "America/Sao_Paulo")


config = Config()
