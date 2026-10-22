"""
Conexão do painel com a API de Chamados (usada pelas páginas Chamados e Professores).

Na primeira vez, o painel pede o endereço da API, o usuário e a senha do técnico,
e guarda em api.json (que não vai para o GitHub).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

PASTA = Path(__file__).resolve().parent
ARQ_CONFIG = PASTA / "api.json"


class ErroAPI(Exception):
    def __init__(self, mensagem, status=None):
        super().__init__(mensagem)
        self.status = status


def ler_config():
    try:
        return json.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _requisicao(metodo, caminho, corpo=None, params=None, token=None, url=None):
    cfg = ler_config() or {}
    base = (url or cfg.get("url", "")).rstrip("/")
    endereco = base + caminho
    if params:
        endereco += "?" + urllib.parse.urlencode(params, doseq=True)
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(endereco, data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            detalhe = json.loads(e.read().decode()).get("detail")
        except Exception:  # noqa: BLE001
            detalhe = None
        if isinstance(detalhe, list):  # erro de validação do FastAPI
            detalhe = "; ".join(str(d.get("msg", d)) for d in detalhe)
        raise ErroAPI(f"{e.code}: {detalhe or e.reason}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroAPI(f"API fora do ar ou sem internet ({e})") from None


def entrar(url, usuario, senha):
    r = _requisicao("POST", "/auth/login", {"usuario": usuario, "senha": senha}, url=url)
    st.session_state["token"] = r["access_token"]
    st.session_state["token_expira"] = r["expira_em"]
    st.session_state["nome"] = r["nome"]
    st.session_state["papel"] = r["papel"]


def token():
    expira = st.session_state.get("token_expira")
    if st.session_state.get("token") and expira and \
            datetime.fromisoformat(expira.replace("Z", "+00:00")) > datetime.now(timezone.utc) + timedelta(minutes=5):
        return st.session_state["token"]
    cfg = ler_config()
    entrar(cfg["url"], cfg["usuario"], cfg["senha"])
    return st.session_state["token"]


def api(metodo, caminho, corpo=None, params=None):
    try:
        return _requisicao(metodo, caminho, corpo, params, token=token())
    except ErroAPI as e:
        if e.status == 401:  # token vencido: entra de novo uma vez
            st.session_state.pop("token", None)
            return _requisicao(metodo, caminho, corpo, params, token=token())
        raise


def eh_admin():
    try:
        token()
    except ErroAPI:
        return False
    return st.session_state.get("papel") == "admin"


def exigir_configuracao():
    """Mostra o formulário de conexão se o api.json ainda não existe (e para a página)."""
    if ler_config():
        return
    st.info("Configure a conexão com a API de chamados. Isso fica salvo só neste computador (api.json).")
    with st.form("config"):
        url = st.text_input("Endereço da API", placeholder="https://sua-api.onrender.com")
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.form_submit_button("Conectar", type="primary"):
            try:
                entrar(url.strip(), usuario.strip(), senha)
                ARQ_CONFIG.write_text(json.dumps({"url": url.strip().rstrip("/"), "usuario": usuario.strip(),
                                                  "senha": senha}, indent=1), encoding="utf-8")
                st.session_state["aviso"] = "Conectado à API!"
                st.rerun()
            except ErroAPI as e:
                st.error(f"Não consegui conectar: {e}")
    st.stop()
