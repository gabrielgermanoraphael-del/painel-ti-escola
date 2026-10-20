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
    LIMITE_POR_IP: int = int(os.getenv("LIMITE_POR_IP", "10"))          # chamados...
    JANELA_IP_SEG: int = int(os.getenv("JANELA_IP_SEG", "600"))         # ...a cada 10 min
    JANELA_DUPLICADO_SEG: int = int(os.getenv("JANELA_DUPLICADO_SEG", "120"))

    # Fuso usado nas estatísticas por dia
    FUSO: str = os.getenv("FUSO", "America/Sao_Paulo")


config = Config()
