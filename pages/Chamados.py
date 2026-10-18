"""
Chamados do TI (página do painel Streamlit)
-------------------------------------------
Busca os chamados enviados pelos QR codes das salas (via ntfy), guarda tudo
num banco local (chamados.db) e permite acompanhar cada um:
Aberto -> Em atendimento -> Resolvido.

Abre junto com o painel:   python -m streamlit run painel.py   (menu lateral "Chamados")
Ou sozinho:                python -m streamlit run pages/Chamados.py

Observação: o ntfy.sh guarda as mensagens por cerca de 12 horas. Deixe o painel
aberto durante o expediente (ou abra pelo menos uma vez por dia) para não perder nada.
"""

import json
import sqlite3
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ====================== CONFIGURAÇÃO ======================
TOPICO_NTFY = "chamados-aparecido-batista"
ATUALIZAR_A_CADA = 15  # segundos
LOCAIS = [f"Sala {n}" for n in range(1, 9)] + ["Sala 11", "Secretaria", "Sala dos Professores",
                                               "Coordenação", "Outro local"]
TIPOS = ["Internet / Wi-Fi", "Chave do carrinho de tablets", "Lousa digital", "Projetor",
         "Computador / notebook", "Som", "Tablet de aluno", "Impressora", "Outro"]
# ===========================================================

PASTA = Path(__file__).resolve().parent
if PASTA.name == "pages":
    PASTA = PASTA.parent
BANCO = PASTA / "chamados.db"

ICONE_TIPO = {"Internet / Wi-Fi": "📶", "Chave do carrinho de tablets": "🔑", "Lousa digital": "🖊️",
              "Projetor": "📽️", "Computador / notebook": "💻", "Som": "🔊", "Tablet de aluno": "📱",
              "Impressora": "🖨️", "Outro": "💬", "Chamado geral": "🔔"}
STATUS = {"aberto": "🔴 Aberto", "atendimento": "🟡 Em atendimento", "resolvido": "🟢 Resolvido"}


# ---------------------------------------------------------------- banco de dados
def conectar():
    con = sqlite3.connect(BANCO)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS chamados (
            id TEXT PRIMARY KEY,
            recebido_em TEXT NOT NULL,
            local TEXT, tipo TEXT, detalhe TEXT,
            status TEXT NOT NULL DEFAULT 'aberto',
            atendido_em TEXT, resolvido_em TEXT, solucao TEXT,
            origem TEXT
        )""")
    con.execute("CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT)")
    return con


def agora_iso():
    return datetime.now().isoformat(timespec="seconds")


def ler_meta(con, chave, padrao=None):
    linha = con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
    return linha["valor"] if linha else padrao


def gravar_meta(con, chave, valor):
    con.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES (?, ?)", (chave, str(valor)))


# ---------------------------------------------------------------- ntfy
def interpretar(msg):
    """Transforma uma mensagem do ntfy num chamado. Devolve None se não for chamado."""
    if msg.get("event") != "message" or "bell" not in (msg.get("tags") or []):
        return None  # ignora alertas do monitor de APs e outras mensagens
    titulo = (msg.get("title") or "").strip()
    texto = (msg.get("message") or "").strip()
    if titulo == "Chamado TI":                      # formato antigo (botão único)
        local, tipo, detalhe = texto.replace(" chamando", "").strip() or "?", "Chamado geral", ""
    elif ": " in titulo:                            # formato novo: "Sala 3: Projetor"
        local, tipo = titulo.split(": ", 1)
        # Sem detalhe, a página manda só "<ícone> <tipo>"
        detalhe = "" if texto.endswith(tipo) and len(texto) <= len(tipo) + 4 else texto
    else:
        local, tipo, detalhe = "?", titulo or "Chamado", texto
    return {
        "id": msg["id"],
        "recebido_em": datetime.fromtimestamp(msg["time"]).isoformat(timespec="seconds"),
        "local": local, "tipo": tipo, "detalhe": detalhe, "origem": "QR code",
    }


def buscar_ntfy(desde):
    url = f"https://ntfy.sh/{TOPICO_NTFY}/json?poll=1&since={desde}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return [json.loads(l) for l in r.read().decode("utf-8").splitlines() if l.strip()]


def sincronizar():
    """Busca mensagens novas no ntfy e grava os chamados. Devolve (novos, erro)."""
    con = conectar()
    try:
        desde = ler_meta(con, "ultimo_tempo", "all")
        try:
            mensagens = buscar_ntfy(desde)
        except Exception as e:  # noqa: BLE001
            return [], str(e)
        novos = []
        maior_tempo = int(desde) if str(desde).isdigit() else 0
        for m in mensagens:
            maior_tempo = max(maior_tempo, int(m.get("time", 0)))
            c = interpretar(m)
            if not c:
                continue
            cur = con.execute(
                "INSERT OR IGNORE INTO chamados (id, recebido_em, local, tipo, detalhe, origem) "
                "VALUES (:id, :recebido_em, :local, :tipo, :detalhe, :origem)", c)
            if cur.rowcount:
                novos.append(c)
        if maior_tempo:
            gravar_meta(con, "ultimo_tempo", maior_tempo)
        gravar_meta(con, "ultima_sincronizacao", agora_iso())
        con.commit()
        return novos, None
    finally:
        con.close()


# ---------------------------------------------------------------- ações
def mudar_status(id_, status, solucao=None):
    con = conectar()
    if status == "atendimento":
        con.execute("UPDATE chamados SET status='atendimento', atendido_em=COALESCE(atendido_em, ?) "
                    "WHERE id=?", (agora_iso(), id_))
    elif status == "resolvido":
        con.execute("UPDATE chamados SET status='resolvido', resolvido_em=?, solucao=?, "
                    "atendido_em=COALESCE(atendido_em, ?) WHERE id=?",
                    (agora_iso(), solucao or "", agora_iso(), id_))
    elif status == "aberto":
        con.execute("UPDATE chamados SET status='aberto', resolvido_em=NULL WHERE id=?", (id_,))
    con.commit()
    con.close()


def criar_manual(local, tipo, detalhe):
    con = conectar()
    con.execute("INSERT INTO chamados (id, recebido_em, local, tipo, detalhe, origem) VALUES (?,?,?,?,?,?)",
                ("manual-" + uuid.uuid4().hex[:10], agora_iso(), local, tipo, detalhe, "Manual"))
    con.commit()
    con.close()


def carregar(status=None):
    con = conectar()
    if status:
        marcas = ",".join("?" * len(status))
        df = pd.read_sql_query(f"SELECT * FROM chamados WHERE status IN ({marcas}) ORDER BY recebido_em",
                               con, params=list(status))
    else:
        df = pd.read_sql_query("SELECT * FROM chamados ORDER BY recebido_em DESC", con)
    con.close()
    for c in ("recebido_em", "atendido_em", "resolvido_em"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def ha_quanto(dt):
    if dt is None or pd.isna(dt):
        return ""
    s = int((datetime.now() - dt.to_pydatetime()).total_seconds())
    if s < 60:
        return "agora"
    if s < 3600:
        return f"há {s // 60} min"
    if s < 86400:
        return f"há {s // 3600}h{(s % 3600) // 60:02d}"
    return dt.strftime("%d/%m %H:%M")


def minutos(inicio, fim):
    if pd.isna(inicio) or pd.isna(fim):
        return None
    return (fim - inicio).total_seconds() / 60


# ================================================================ interface
st.set_page_config(page_title="Chamados do TI", page_icon="🛠️", layout="wide")
if not hasattr(st, "fragment"):
    st.error("Sua versão do Streamlit é antiga. Atualize com:  python -m pip install -U streamlit")
    st.stop()

st.title("🛠️ Chamados do TI")
if "aviso" in st.session_state:
    st.toast(st.session_state.pop("aviso"), icon="✅")


@st.fragment(run_every=ATUALIZAR_A_CADA)
def bloco_ativos():
    novos, erro = sincronizar()
    for c in novos:
        st.toast(f"🔔 Novo chamado: **{c['local']}** – {c['tipo']}", icon="🔔")
    if erro:
        st.warning(f"Não consegui buscar chamados novos agora (sem internet?). Detalhe: {erro}")

    ativos = carregar(["aberto", "atendimento"])
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    todos = carregar()
    resolvidos_hoje = todos[(todos["status"] == "resolvido") & (todos["resolvido_em"] >= hoje)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🔴 Abertos", int((ativos["status"] == "aberto").sum()))
    m2.metric("🟡 Em atendimento", int((ativos["status"] == "atendimento").sum()))
    m3.metric("🟢 Resolvidos hoje", len(resolvidos_hoje))
    con = conectar()
    ult = ler_meta(con, "ultima_sincronizacao")
    con.close()
    m4.metric("Última busca", ult[11:16] if ult else "—")

    if ativos.empty:
        st.success("Nenhum chamado pendente. 🎉")
        return

    for _, c in ativos.iterrows():
        with st.container(border=True):
            col_info, col_acao = st.columns([3, 1])
            icone = ICONE_TIPO.get(c["tipo"], "🔔")
            col_info.markdown(f"### {icone} {c['local']} — {c['tipo']}")
            linha = f"{STATUS[c['status']]} · recebido {ha_quanto(c['recebido_em'])} " \
                    f"({c['recebido_em'].strftime('%H:%M')}) · {c['origem']}"
            if c["status"] == "atendimento" and not pd.isna(c["atendido_em"]):
                linha += f" · atendendo desde {c['atendido_em'].strftime('%H:%M')}"
            col_info.caption(linha)
            if c["detalhe"]:
                col_info.write(f"💬 {c['detalhe']}")

            if c["status"] == "aberto":
                if col_acao.button("🚶 Atender", key=f"at_{c['id']}", use_container_width=True):
                    mudar_status(c["id"], "atendimento")
                    st.rerun()
            with col_acao.popover("✅ Resolver", use_container_width=True):
                solucao = st.text_input("O que foi feito? (opcional)", key=f"sol_{c['id']}",
                                        placeholder="Ex.: troquei a pilha do controle")
                if st.button("Confirmar", key=f"ok_{c['id']}", type="primary"):
                    mudar_status(c["id"], "resolvido", solucao)
                    st.session_state["aviso"] = f"Resolvido: {c['local']} – {c['tipo']}"
                    st.rerun()


bloco_ativos()

with st.expander("➕ Registrar chamado manualmente (pedido no corredor, por telefone...)"):
    with st.form("novo_chamado", clear_on_submit=True):
        c1, c2 = st.columns(2)
        local = c1.selectbox("Local", LOCAIS)
        tipo = c2.selectbox("Tipo", TIPOS)
        detalhe = st.text_input("Detalhe (opcional)")
        if st.form_submit_button("Registrar", type="primary"):
            criar_manual(local, tipo, detalhe.strip())
            st.session_state["aviso"] = f"Chamado registrado: {local} – {tipo}"
            st.rerun()

st.divider()
aba_hist, aba_stats = st.tabs(["📋 Histórico", "📊 Estatísticas"])

with aba_hist:
    df = carregar()
    if df.empty:
        st.info("Nenhum chamado registrado ainda.")
    else:
        f1, f2, f3 = st.columns(3)
        periodo = f1.selectbox("Período", ["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Tudo"], index=1)
        f_status = f2.multiselect("Status", list(STATUS.values()), default=list(STATUS.values()))
        f_local = f3.multiselect("Local", sorted(df["local"].dropna().unique()))

        hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        inicio = {"Hoje": hoje, "Últimos 7 dias": hoje - timedelta(days=6),
                  "Últimos 30 dias": hoje - timedelta(days=29)}.get(periodo)
        filt = df if inicio is None else df[df["recebido_em"] >= inicio]
        filt = filt[filt["status"].map(STATUS).isin(f_status)]
        if f_local:
            filt = filt[filt["local"].isin(f_local)]

        tabela = pd.DataFrame({
            "Recebido": filt["recebido_em"].dt.strftime("%d/%m %H:%M"),
            "Local": filt["local"], "Tipo": filt["tipo"], "Detalhe": filt["detalhe"],
            "Status": filt["status"].map(STATUS),
            "Resolvido": filt["resolvido_em"].dt.strftime("%d/%m %H:%M").fillna(""),
            "Solução": filt["solucao"].fillna(""), "Origem": filt["origem"],
        })
        st.dataframe(tabela, hide_index=True, use_container_width=True)

        # Reabrir um chamado resolvido por engano
        resolvidos = filt[filt["status"] == "resolvido"]
        if not resolvidos.empty:
            with st.expander("↩️ Reabrir um chamado resolvido"):
                opcoes = {f"{r.recebido_em:%d/%m %H:%M} – {r.local} – {r.tipo}": r.id
                          for r in resolvidos.itertuples()}
                escolha = st.selectbox("Chamado", list(opcoes))
                if st.button("Reabrir"):
                    mudar_status(opcoes[escolha], "aberto")
                    st.rerun()

        csv = tabela.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button("⬇️ Baixar (CSV / Excel)", csv, "chamados.csv", "text/csv")

with aba_stats:
    df = carregar()
    if df.empty:
        st.info("As estatísticas aparecem quando houver chamados.")
    else:
        dias = st.selectbox("Considerar os últimos", [7, 30, 90, 365], index=1,
                            format_func=lambda d: f"{d} dias")
        base = df[df["recebido_em"] >= datetime.now() - timedelta(days=dias)]
        res = base[base["status"] == "resolvido"]
        tempos = [t for t in (minutos(a, b) for a, b in zip(res["recebido_em"], res["resolvido_em"]))
                  if t is not None]
        s1, s2, s3 = st.columns(3)
        s1.metric("Chamados no período", len(base))
        s2.metric("Resolvidos", len(res))
        s3.metric("Tempo médio até resolver", f"{sum(tempos) / len(tempos):.0f} min" if tempos else "—")

        if not base.empty:
            g1, g2 = st.columns(2)
            g1.markdown("**Chamados por tipo**")
            g1.bar_chart(base["tipo"].value_counts().rename("Chamados"))
            g2.markdown("**Chamados por local**")
            g2.bar_chart(base["local"].value_counts().rename("Chamados"))
            st.markdown("**Chamados por dia**")
            st.bar_chart(base.groupby(base["recebido_em"].dt.date).size().rename("Chamados"))
