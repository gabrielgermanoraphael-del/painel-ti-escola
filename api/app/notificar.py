"""Envia a notificação para o celular do técnico pelo ntfy (executado em segundo plano)."""
import json
import logging
import urllib.request

from .config import config

log = logging.getLogger("chamados")


def notificar_ntfy(titulo: str, mensagem: str, tags: list[str] | None = None, prioridade: int = 4) -> bool:
    if not config.NTFY_TOPIC:
        return False
    corpo = json.dumps({"topic": config.NTFY_TOPIC, "title": titulo, "message": mensagem,
                        "tags": tags or ["bell"], "priority": prioridade}).encode()
    req = urllib.request.Request(config.NTFY_URL.rstrip("/") + "/", data=corpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    if config.NTFY_TOKEN:
        req.add_header("Authorization", f"Bearer {config.NTFY_TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001 - falha no aviso não pode derrubar o chamado
        log.warning("Falha ao notificar pelo ntfy: %s", e)
        return False
