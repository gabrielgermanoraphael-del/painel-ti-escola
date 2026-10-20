"""
Professores (página do painel Streamlit)
----------------------------------------
Libera o acesso de quem entrou com o e-mail institucional na página do QR code.

1. O professor escaneia o QR e entra com o Google (@educ.indaiatuba.sp.gov.br).
2. Aparece um código no celular dele (ex.: K7P-3QX).
3. Aqui o TI digita o código, escolhe as salas em que ele pode abrir chamado e libera.

Administradores também gerenciam as contas do TI (quem acessa este painel).
"""

import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_cliente import ErroAPI, api, eh_admin, exigir_configuracao  # noqa: E402

FUSO = "America/Sao_Paulo"
SITUACAO = {"pendente": "⏳ Aguardando liberação", "ativo": "🟢 Liberado", "bloqueado": "🚫 Bloqueado"}

st.set_page_config(page_title="Professores", page_icon="👩‍🏫", layout="wide")
st.title("👩‍🏫 Professores")
if "aviso" in st.session_state:
    st.toast(st.session_state.pop("aviso"), icon="✅")

exigir_configuracao()


def data_local(valor):
    if not valor:
        return ""
    return pd.Timestamp(valor).tz_convert(FUSO).strftime("%d/%m/%Y %H:%M")


def problema_conta(usuario, nome, senha):
    if not re.fullmatch(r"[a-zA-Z0-9._-]{3,40}", usuario.strip()):
        return "Usuário: de 3 a 40 caracteres, só letras sem acento, números, ponto, hífen ou _."
    if not nome.strip():
        return "Preencha o nome."
    if len(senha) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    return None


def texto_salas(p):
    if p["todas_salas"]:
        return "Todas as salas"
    return ", ".join(s["nome"] for s in p["salas"]) or "—"


def editor_acesso(p, locais, chave):
    """Formulário para liberar/alterar/bloquear o acesso de uma pessoa."""
    with st.container(border=True):
        c_foto, c_info = st.columns([1, 6])
        if p.get("foto"):
            c_foto.image(p["foto"], width=56)
        c_info.markdown(f"**{p['nome']}**  \n{p['email']}")
        c_info.caption(f"Código {p['codigo']} · {SITUACAO[p['status']]} · salas: {texto_salas(p)}"
                       + (f" · liberado por {p['liberado_por']} em {data_local(p['liberado_em'])}"
                          if p.get("liberado_por") else ""))

        with st.form(f"acesso_{chave}_{p['id']}"):
            todas = st.checkbox("Pode abrir chamado em **todas** as salas (coordenação, direção...)",
                                value=p["todas_salas"])
            atuais = [s["id"] for s in p["salas"] if s["id"] in locais]
            salas = st.multiselect("Salas em que dá aula", list(locais), default=atuais, format_func=locais.get,
                                   placeholder="Escolha as salas")
            opcoes = ["ativo", "bloqueado", "pendente"]
            situacao = st.radio("Situação", opcoes, horizontal=True,
                                index=0 if p["status"] == "pendente" else opcoes.index(p["status"]),
                                format_func={"ativo": "🟢 Liberado", "bloqueado": "🚫 Bloqueado",
                                             "pendente": "⏳ Pendente"}.get)
            rotulo = "✅ Liberar acesso" if p["status"] == "pendente" else "💾 Salvar"
            if st.form_submit_button(rotulo, type="primary"):
                if situacao == "ativo" and not todas and not salas:
                    st.error("Escolha pelo menos uma sala (ou marque todas as salas).")
                    return
                try:
                    api("PUT", f"/pessoas/{p['id']}/acesso",
                        {"status": situacao, "todas_salas": todas, "salas": [] if todas else salas})
                except ErroAPI as e:
                    st.error(str(e))
                    return
                st.session_state["aviso"] = f"{p['nome']}: {'acesso liberado' if situacao == 'ativo' else SITUACAO[situacao].lower()}"
                st.session_state.pop("pessoa_codigo", None)
                st.rerun()


try:
    locais = {l["id"]: l["nome"] for l in api("GET", "/locais") if l["ativo"]}
    pessoas = api("GET", "/pessoas")
except ErroAPI as e:
    st.error(f"Não consegui falar com a API agora. {e}")
    st.stop()

pendentes = [p for p in pessoas if p["status"] == "pendente"]

# ---------------------------------------------------------------- liberar pelo código
st.subheader("🔑 Liberar pelo código")
st.caption("O professor entra com o Google na página do QR e recebe um código. Digite aqui o código que aparece no celular dele.")
with st.form("buscar_codigo"):
    c1, c2 = st.columns([3, 1])
    codigo = c1.text_input("Código", placeholder="Ex.: K7P-3QX", label_visibility="collapsed")
    if c2.form_submit_button("Buscar", use_container_width=True) and codigo.strip():
        try:
            st.session_state["pessoa_codigo"] = api("GET", f"/pessoas/codigo/{codigo.strip()}")
        except ErroAPI as e:
            st.session_state.pop("pessoa_codigo", None)
            st.error("Código não encontrado. Confira com o professor." if e.status == 404 else str(e))

if "pessoa_codigo" in st.session_state:
    editor_acesso(st.session_state["pessoa_codigo"], locais, "codigo")

if pendentes:
    with st.expander(f"⏳ Aguardando liberação ({len(pendentes)})", expanded=not st.session_state.get("pessoa_codigo")):
        st.caption("Confira o código com a pessoa antes de liberar: o nome sozinho não garante quem é.")
        for p in pendentes:
            editor_acesso(p, locais, "pend")

# ---------------------------------------------------------------- todos
st.divider()
st.subheader("📋 Professores cadastrados")
if not pessoas:
    st.info("Ninguém entrou ainda. Quando um professor fizer login pela página do QR, ele aparece aqui.")
else:
    f1, f2 = st.columns([1, 2])
    filtro = f1.multiselect("Situação", list(SITUACAO), default=list(SITUACAO), format_func=SITUACAO.get)
    busca = f2.text_input("Buscar por nome ou e-mail")
    lista = [p for p in pessoas if p["status"] in filtro and
             (busca.strip().lower() in (p["nome"] + " " + p["email"]).lower())]
    tabela = pd.DataFrame({
        "Nome": [p["nome"] for p in lista],
        "E-mail": [p["email"] for p in lista],
        "Situação": [SITUACAO[p["status"]] for p in lista],
        "Salas": [texto_salas(p) for p in lista],
        "Código": [p["codigo"] for p in lista],
        "Último acesso": [data_local(p["ultimo_login"]) for p in lista],
        "Liberado por": [p["liberado_por"] or "" for p in lista],
    })
    st.dataframe(tabela, hide_index=True, use_container_width=True)
    st.download_button("⬇️ Baixar lista (CSV / Excel)", tabela.to_csv(index=False, sep=";").encode("utf-8-sig"),
                       "professores.csv", "text/csv")

    with st.expander("✏️ Alterar salas ou bloquear alguém"):
        por_id = {p["id"]: p for p in pessoas}
        escolha = st.selectbox("Pessoa", list(por_id), format_func=lambda i: f"{por_id[i]['nome']} ({por_id[i]['email']})")
        if escolha is not None:
            editor_acesso(por_id[escolha], locais, "editar")

# ---------------------------------------------------------------- contas do TI (só administradores)
if eh_admin():
    st.divider()
    st.subheader("🛡️ Contas do TI")
    st.caption("Só administradores veem esta parte. Técnicos atendem chamados e liberam professores; "
               "administradores também cadastram salas e contas do TI.")
    try:
        contas = api("GET", "/usuarios")
    except ErroAPI as e:
        contas = []
        st.error(str(e))
    if contas:
        st.dataframe(pd.DataFrame({
            "Usuário": [u["usuario"] for u in contas], "Nome": [u["nome"] for u in contas],
            "Papel": ["Administrador" if u["papel"] == "admin" else "Técnico" for u in contas],
            "Ativa": ["Sim" if u["ativo"] else "Não" for u in contas],
        }), hide_index=True, use_container_width=True)

    c_nova, c_edit = st.columns(2)
    with c_nova.expander("➕ Nova conta do TI"):
        with st.form("nova_conta", clear_on_submit=True):
            usuario = st.text_input("Usuário (para entrar no painel)", placeholder="ex.: joao.tec")
            nome = st.text_input("Nome")
            senha = st.text_input("Senha inicial (mínimo 8 caracteres)", type="password")
            admin = st.checkbox("Administrador (pode criar outras contas do TI)")
            if st.form_submit_button("Criar conta", type="primary"):
                problema = problema_conta(usuario, nome, senha)
                if problema:
                    st.error(problema)
                else:
                    try:
                        api("POST", "/usuarios", {"usuario": usuario.strip(), "nome": nome.strip(), "senha": senha,
                                                  "papel": "admin" if admin else "tecnico"})
                        st.session_state["aviso"] = f"Conta {usuario.strip().lower()} criada"
                        st.rerun()
                    except ErroAPI as e:
                        st.error("Já existe uma conta com esse usuário." if e.status == 409 else str(e))

    with c_edit.expander("✏️ Alterar uma conta"):
        if contas:
            por_id = {u["id"]: u for u in contas}
            uid = st.selectbox("Conta", list(por_id), format_func=lambda i: f"{por_id[i]['nome']} ({por_id[i]['usuario']})")
            u = por_id[uid]
            with st.form(f"editar_conta_{uid}"):
                papel = st.radio("Papel", ["tecnico", "admin"], index=1 if u["papel"] == "admin" else 0, horizontal=True,
                                 format_func={"tecnico": "Técnico", "admin": "Administrador"}.get)
                ativa = st.checkbox("Conta ativa", value=u["ativo"])
                nova_senha = st.text_input("Nova senha (deixe em branco para manter)", type="password")
                if st.form_submit_button("Salvar", type="primary"):
                    corpo = {"papel": papel, "ativo": ativa}
                    if nova_senha:
                        if len(nova_senha) < 8:
                            st.error("A senha precisa ter pelo menos 8 caracteres.")
                            st.stop()
                        corpo["senha"] = nova_senha
                    try:
                        api("PATCH", f"/usuarios/{uid}", corpo)
                        st.session_state["aviso"] = f"Conta {u['usuario']} atualizada"
                        st.rerun()
                    except ErroAPI as e:
                        st.error("Você não pode tirar o seu próprio acesso de administrador." if e.status == 409 else str(e))
