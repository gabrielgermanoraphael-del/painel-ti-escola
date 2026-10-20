"""
Chamados do TI (página do painel Streamlit) — versão conectada à API
--------------------------------------------------------------------
Lê e atualiza os chamados pela API de Chamados (pasta api/ do projeto).
Os chamados ficam guardados no banco da API, não mais neste computador.

A conexão com a API fica em api_cliente.py (compartilhada com a página Professores).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_cliente import ErroAPI, api, exigir_configuracao  # noqa: E402

FUSO = "America/Sao_Paulo"
ATUALIZAR_A_CADA = 15  # segundos

ICONE_TIPO = {"internet": "📶", "chave": "🔑", "lousa": "🖊️", "projetor": "📽️", "computador": "💻",
              "som": "🔊", "tablet": "📱", "impressora": "🖨️", "outro": "💬"}
TIPOS = {"internet": "Internet / Wi-Fi", "chave": "Chave do carrinho de tablets", "lousa": "Lousa digital",
         "projetor": "Projetor", "computador": "Computador / notebook", "som": "Som",
         "tablet": "Tablet de aluno", "impressora": "Impressora", "outro": "Outro"}
STATUS = {"aberto": "🔴 Aberto", "atendimento": "🟡 Em atendimento", "resolvido": "🟢 Resolvido"}


def para_df(lista):
    df = pd.DataFrame(lista, columns=["id", "local_id", "local", "tipo", "tipo_nome", "detalhe", "status", "origem",
                                      "criado_em", "atendido_em", "resolvido_em", "solucao", "atendido_por",
                                      "aberto_por"])
    for c in ("criado_em", "atendido_em", "resolvido_em"):
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce").dt.tz_convert(FUSO).dt.tz_localize(None)
    return df


def ha_quanto(dt):
    if dt is None or pd.isna(dt):
        return ""
    s = int((datetime.now(timezone.utc).astimezone().replace(tzinfo=None) - dt.to_pydatetime()).total_seconds())
    if s < 60:
        return "agora"
    if s < 3600:
        return f"há {s // 60} min"
    if s < 86400:
        return f"há {s // 3600}h{(s % 3600) // 60:02d}"
    return dt.strftime("%d/%m %H:%M")


def hoje_local():
    return pd.Timestamp.now(tz=FUSO).tz_localize(None).normalize()


def desde(dias_atras):
    """Meia-noite (horário de Brasília) de N dias atrás, com fuso, para enviar à API."""
    return (pd.Timestamp.now(tz=FUSO).normalize() - timedelta(days=dias_atras)).isoformat()


# ================================================================ interface
st.set_page_config(page_title="Chamados do TI", page_icon="🛠️", layout="wide")
if not hasattr(st, "fragment"):
    st.error("Sua versão do Streamlit é antiga. Atualize com:  python -m pip install -U streamlit")
    st.stop()

st.title("🛠️ Chamados do TI")
if "aviso" in st.session_state:
    st.toast(st.session_state.pop("aviso"), icon="✅")

# ---- primeira configuração
exigir_configuracao()


@st.fragment(run_every=ATUALIZAR_A_CADA)
def bloco_ativos():
    try:
        ativos = para_df(api("GET", "/chamados", params={"status": ["aberto", "atendimento"], "limite": 200}))
        resolvidos = para_df(api("GET", "/chamados", params={"status": "resolvido",
                                                             "desde": desde(2),
                                                             "limite": 500}))
    except ErroAPI as e:
        st.error(f"Não consegui falar com a API agora. {e}")
        return

    # Avisa os chamados que chegaram desde a última atualização
    vistos = st.session_state.setdefault("vistos", None)
    ids = set(ativos["id"])
    if vistos is not None:
        for _, c in ativos[~ativos["id"].isin(vistos)].iterrows():
            st.toast(f"🔔 Novo chamado: **{c['local']}** – {c['tipo_nome']}", icon="🔔")
    st.session_state["vistos"] = ids | (vistos or set())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🔴 Abertos", int((ativos["status"] == "aberto").sum()))
    m2.metric("🟡 Em atendimento", int((ativos["status"] == "atendimento").sum()))
    m3.metric("🟢 Resolvidos hoje", int((resolvidos["resolvido_em"] >= hoje_local()).sum()))
    m4.metric("Atualizado", datetime.now().strftime("%H:%M:%S"))

    if ativos.empty:
        st.success("Nenhum chamado pendente. 🎉")
        return

    for _, c in ativos.sort_values("criado_em").iterrows():
        with st.container(border=True):
            col_info, col_acao = st.columns([3, 1])
            col_info.markdown(f"### {ICONE_TIPO.get(c['tipo'], '🔔')} {c['local']} — {c['tipo_nome']}")
            linha = f"{STATUS[c['status']]} · nº {c['id']} · recebido {ha_quanto(c['criado_em'])} " \
                    f"({c['criado_em']:%H:%M}) · {'QR code' if c['origem'] == 'qrcode' else 'manual'}"
            if c["aberto_por"]:
                linha += f" · por {c['aberto_por']}"
            if c["status"] == "atendimento" and c["atendido_por"]:
                linha += f" · com {c['atendido_por']}"
            col_info.caption(linha)
            if c["detalhe"]:
                col_info.write(f"💬 {c['detalhe']}")

            if c["status"] == "aberto":
                if col_acao.button("🚶 Atender", key=f"at_{c['id']}", use_container_width=True):
                    api("POST", f"/chamados/{c['id']}/atender")
                    st.rerun()
            with col_acao.popover("✅ Resolver", use_container_width=True):
                solucao = st.text_input("O que foi feito? (opcional)", key=f"sol_{c['id']}",
                                        placeholder="Ex.: troquei a pilha do controle")
                if st.button("Confirmar", key=f"ok_{c['id']}", type="primary"):
                    api("POST", f"/chamados/{c['id']}/resolver", {"solucao": solucao})
                    st.session_state["aviso"] = f"Resolvido: {c['local']} – {c['tipo_nome']}"
                    st.rerun()


bloco_ativos()

with st.expander("➕ Registrar chamado manualmente (pedido no corredor, por telefone...)"):
    try:
        locais = {l["nome"]: l["id"] for l in api("GET", "/locais") if l["ativo"]}
    except ErroAPI as e:
        locais = {}
        st.error(str(e))
    if locais:
        with st.form("novo_chamado", clear_on_submit=True):
            c1, c2 = st.columns(2)
            local = c1.selectbox("Local", list(locais))
            tipo = c2.selectbox("Tipo", list(TIPOS), format_func=TIPOS.get)
            detalhe = st.text_input("Detalhe (opcional)")
            if st.form_submit_button("Registrar", type="primary"):
                api("POST", "/chamados/manual", {"local_id": locais[local], "tipo": tipo, "detalhe": detalhe.strip()})
                st.session_state["aviso"] = f"Chamado registrado: {local} – {TIPOS[tipo]}"
                st.rerun()

st.divider()
aba_hist, aba_stats = st.tabs(["📋 Histórico", "📊 Estatísticas"])

with aba_hist:
    f1, f2, f3 = st.columns(3)
    periodo = f1.selectbox("Período", ["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Últimos 365 dias"], index=1)
    dias = {"Hoje": 0, "Últimos 7 dias": 6, "Últimos 30 dias": 29, "Últimos 365 dias": 364}[periodo]
    try:
        df = para_df(api("GET", "/chamados", params={"desde": desde(dias),
                                                     "limite": 1000}))
    except ErroAPI as e:
        df = para_df([])
        st.error(str(e))
    if df.empty:
        st.info("Nenhum chamado no período.")
    else:
        f_status = f2.multiselect("Status", list(STATUS.values()), default=list(STATUS.values()))
        f_local = f3.multiselect("Local", sorted(df["local"].unique()))
        filt = df[df["status"].map(STATUS).isin(f_status)]
        if f_local:
            filt = filt[filt["local"].isin(f_local)]
        tabela = pd.DataFrame({
            "Nº": filt["id"], "Recebido": filt["criado_em"].dt.strftime("%d/%m %H:%M"),
            "Local": filt["local"], "Tipo": filt["tipo_nome"], "Detalhe": filt["detalhe"],
            "Aberto por": filt["aberto_por"].fillna(""),
            "Status": filt["status"].map(STATUS),
            "Resolvido": filt["resolvido_em"].dt.strftime("%d/%m %H:%M").fillna(""),
            "Solução": filt["solucao"], "Atendido por": filt["atendido_por"].fillna(""),
        })
        st.dataframe(tabela, hide_index=True, use_container_width=True)

        res = filt[filt["status"] == "resolvido"]
        if not res.empty:
            with st.expander("↩️ Reabrir um chamado resolvido"):
                opcoes = {f"nº {r.id} – {r.criado_em:%d/%m %H:%M} – {r.local} – {r.tipo_nome}": r.id
                          for r in res.itertuples()}
                escolha = st.selectbox("Chamado", list(opcoes))
                if st.button("Reabrir"):
                    api("POST", f"/chamados/{opcoes[escolha]}/reabrir")
                    st.rerun()
        st.download_button("⬇️ Baixar (CSV / Excel)", tabela.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           "chamados.csv", "text/csv")

with aba_stats:
    dias = st.selectbox("Considerar os últimos", [7, 30, 90, 365], index=1, format_func=lambda d: f"{d} dias")
    try:
        e = api("GET", "/estatisticas", params={"dias": dias})
    except ErroAPI as err:
        e = None
        st.error(str(err))
    if e and e["total"]:
        s1, s2, s3 = st.columns(3)
        s1.metric("Chamados no período", e["total"])
        s2.metric("Resolvidos", e["resolvidos"])
        s3.metric("Tempo médio até resolver",
                  f"{e['tempo_medio_resolucao_min']:.0f} min" if e["tempo_medio_resolucao_min"] is not None else "—")
        g1, g2 = st.columns(2)
        g1.markdown("**Chamados por tipo**")
        g1.bar_chart(pd.Series(e["por_tipo"], name="Chamados"))
        g2.markdown("**Chamados por local**")
        g2.bar_chart(pd.Series(e["por_local"], name="Chamados"))
        st.markdown("**Chamados por dia**")
        st.bar_chart(pd.Series(e["por_dia"], name="Chamados"))
    elif e:
        st.info("As estatísticas aparecem quando houver chamados no período.")
