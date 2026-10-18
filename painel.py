"""
Painel do Monitor de APs (Streamlit)
------------------------------------
Abre no navegador e mostra em tempo real a situação dos APs, o histórico de
quedas e permite editar a lista de APs.

Instalar (uma vez):     python -m pip install streamlit
Abrir o painel:         python -m streamlit run painel.py

O painel lê os arquivos que o monitor_aps.py gera (status.json e eventos.csv).
Dá para ligar o monitor pelo próprio painel, no botão "Iniciar monitor".
"""

import ipaddress
import json
import platform
import subprocess
import sys
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import monitor_aps as mon

st.set_page_config(page_title="Monitor de APs", page_icon="📡", layout="wide")

if not hasattr(st, "fragment"):
    st.error("Sua versão do Streamlit é antiga. Atualize com:  python -m pip install -U streamlit")
    st.stop()

PASTA = mon.PASTA
CABECALHO_APS = (
    "# Lista de APs da escola - uma linha por AP no formato: Nome;IP\n"
    "# Editada pelo painel. Linhas que começam com # são ignoradas.\n"
)
ICONE = {"online": "🟢", "instavel": "🟡", "fora": "🔴", "aguardando": "⚪"}


# ---------------------------------------------------------------- utilidades
def ler_status():
    try:
        return json.loads(mon.ARQUIVO_STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def idade_segundos(iso):
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return None


def ha_quanto(segundos):
    if segundos is None:
        return "?"
    segundos = int(max(0, segundos))
    if segundos < 60:
        return f"há {segundos}s"
    if segundos < 3600:
        return f"há {segundos // 60} min"
    return f"há {segundos // 3600}h{(segundos % 3600) // 60:02d}"


def monitor_ativo(status):
    if not status:
        return False
    idade = idade_segundos(status.get("atualizado"))
    limite = max(150, status.get("intervalo", 60) * 2.5 + 30)
    return idade is not None and idade < limite


def iniciar_monitor():
    script = PASTA / "monitor_aps.py"
    if platform.system() == "Windows":
        # Abre o monitor numa janela própria do Prompt de Comando
        subprocess.Popen([sys.executable, str(script)], cwd=PASTA,
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen([sys.executable, str(script)], cwd=PASTA, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ler_lista_aps():
    linhas = []
    if mon.ARQUIVO_APS.exists():
        for linha in mon.ARQUIVO_APS.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and ";" in linha:
                nome, ip = (p.strip() for p in linha.split(";", 1))
                linhas.append({"Nome": nome, "IP": ip})
    return pd.DataFrame(linhas, columns=["Nome", "IP"])


def validar_lista(df):
    """Devolve (lista_limpa, erros, avisos)."""
    erros, avisos, lista, vistos = [], [], [], {}
    for n, row in enumerate(df.itertuples(index=False), 1):
        nome = str(row.Nome or "").strip() if pd.notna(row.Nome) else ""
        ip = str(row.IP or "").strip() if pd.notna(row.IP) else ""
        if not nome and not ip:
            continue
        if not nome or not ip:
            erros.append(f"Linha {n}: preencha o nome e o IP.")
            continue
        if ";" in nome:
            erros.append(f"Linha {n}: o nome não pode ter ponto e vírgula.")
            continue
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            erros.append(f"Linha {n}: '{ip}' não é um IP válido.")
            continue
        if ip in vistos:
            avisos.append(f"'{nome}' e '{vistos[ip]}' estão com o mesmo IP ({ip}).")
        vistos.setdefault(ip, nome)
        lista.append((nome, ip))
    if not lista and not erros:
        erros.append("A lista precisa ter pelo menos um AP.")
    return lista, erros, avisos


def ler_eventos():
    try:
        df = pd.read_csv(mon.ARQUIVO_EVENTOS, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=["data_hora", "evento", "ap", "ip", "detalhe"])
    df["data_hora"] = pd.to_datetime(df["data_hora"], errors="coerce")
    return df.dropna(subset=["data_hora"])


NOMES_EVENTO = {
    "CAIU": "🔴 Caiu", "VOLTOU": "🟢 Voltou", "QUEDA_GERAL": "🚨 Todos caíram",
    "REDE_VOLTOU": "🟢 Rede voltou", "MONITOR_LIGADO": "▶️ Monitor ligado",
    "MONITOR_DESLIGADO": "⏹️ Monitor desligado", "LISTA_ATUALIZADA": "✏️ Lista atualizada",
}


# ---------------------------------------------------------------- cabeçalho
st.title("📡 Monitor de APs")


@st.fragment(run_every=10)
def bloco_status():
    status = ler_status()
    ativo = monitor_ativo(status)

    if not ativo:
        c1, c2 = st.columns([4, 1])
        c1.warning("O monitor está **parado**. Os dados abaixo podem estar desatualizados.")
        if c2.button("▶️ Iniciar monitor", use_container_width=True, type="primary"):
            iniciar_monitor()
            st.toast("Monitor iniciado. Em alguns segundos os dados aparecem aqui.")
    elif status.get("sem_rede"):
        st.error("O notebook está **sem rede** agora. Os APs não puderam ser testados nesta rodada.")

    if not status:
        st.info("Ainda não há dados. Inicie o monitor para começar.")
        return

    aps = status.get("aps", [])
    contagem = {k: sum(1 for a in aps if a["estado"] == k) for k in ICONE}
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("APs vigiados", len(aps))
    m2.metric("🟢 Online", contagem["online"])
    m3.metric("🟡 Instáveis", contagem["instavel"])
    m4.metric("🔴 Fora", contagem["fora"])
    m5.metric("Última verificação", ha_quanto(idade_segundos(status.get("atualizado"))))

    # Os que estão com problema aparecem primeiro
    ordem = {"fora": 0, "instavel": 1, "aguardando": 2, "online": 3}
    aps_ordenados = sorted(aps, key=lambda a: ordem.get(a["estado"], 9))
    for i in range(0, len(aps_ordenados), 4):
        cols = st.columns(4)
        for col, ap in zip(cols, aps_ordenados[i:i + 4]):
            with col.container(border=True):
                st.markdown(f"#### {ICONE.get(ap['estado'], '⚪')} {ap['nome']}")
                st.caption(ap["ip"])
                if ap["estado"] == "online":
                    st.write("Respondendo normalmente")
                elif ap["estado"] == "instavel":
                    st.write(f"Sem resposta ({ap['falhas']}/{mon.FALHAS_PARA_ALERTAR} testes)")
                elif ap["estado"] == "fora":
                    desde = ap.get("fora_desde")
                    hora = datetime.fromisoformat(desde).strftime("%H:%M") if desde else "?"
                    st.write(f"**Fora desde {hora}** ({ha_quanto(idade_segundos(desde))})")
                else:
                    st.write("Aguardando primeiro teste")


bloco_status()
st.divider()

aba_hist, aba_lista, aba_teste = st.tabs(["📋 Histórico", "✏️ Lista de APs", "🔎 Testar agora"])

# ---------------------------------------------------------------- histórico
with aba_hist:
    @st.fragment(run_every=30)
    def bloco_historico():
        eventos = ler_eventos()
        if eventos.empty:
            st.info("Nenhum evento registrado ainda.")
            return

        c1, c2 = st.columns([1, 1])
        periodo = c1.selectbox("Período", ["Hoje", "Últimos 7 dias", "Últimos 30 dias", "Tudo"])
        mostrar_monitor = c2.toggle("Mostrar quando o monitor ligou/desligou", value=False)

        hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        inicio = {"Hoje": hoje, "Últimos 7 dias": hoje - timedelta(days=6),
                  "Últimos 30 dias": hoje - timedelta(days=29)}.get(periodo)
        filtrado = eventos if inicio is None else eventos[eventos["data_hora"] >= inicio]
        if not mostrar_monitor:
            filtrado = filtrado[~filtrado["evento"].isin(["MONITOR_LIGADO", "MONITOR_DESLIGADO",
                                                          "LISTA_ATUALIZADA"])]

        quedas = filtrado[filtrado["evento"] == "CAIU"]
        k1, k2, k3 = st.columns(3)
        k1.metric("Quedas de AP", len(quedas))
        k2.metric("Quedas gerais", int((filtrado["evento"] == "QUEDA_GERAL").sum()))
        k3.metric("AP que mais caiu", quedas["ap"].value_counts().index[0] if len(quedas) else "—")

        if len(quedas):
            st.markdown("**Quedas por AP**")
            st.bar_chart(quedas["ap"].value_counts().rename("Quedas"))

        tabela = filtrado.sort_values("data_hora", ascending=False).copy()
        tabela["Quando"] = tabela["data_hora"].dt.strftime("%d/%m %H:%M:%S")
        tabela["Evento"] = tabela["evento"].map(NOMES_EVENTO).fillna(tabela["evento"])
        tabela = tabela.rename(columns={"ap": "AP", "ip": "IP", "detalhe": "Detalhe"})
        st.dataframe(tabela[["Quando", "Evento", "AP", "IP", "Detalhe"]],
                     hide_index=True, use_container_width=True)

        st.download_button("⬇️ Baixar histórico completo (CSV)",
                           data=mon.ARQUIVO_EVENTOS.read_bytes(),
                           file_name="eventos_aps.csv", mime="text/csv")

    bloco_historico()

# ---------------------------------------------------------------- lista de APs
with aba_lista:
    st.caption("Adicione, edite ou apague linhas e clique em Salvar. "
               "O monitor carrega a lista nova sozinho na próxima verificação.")
    editado = st.data_editor(
        ler_lista_aps(), num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "Nome": st.column_config.TextColumn("Nome (sala/local)", required=True),
            "IP": st.column_config.TextColumn("IP", required=True, help="Ex.: 192.168.1.25"),
        },
        key="editor_aps",
    )
    if st.button("💾 Salvar lista", type="primary"):
        lista, erros, avisos = validar_lista(editado)
        for e in erros:
            st.error(e)
        if not erros:
            conteudo = CABECALHO_APS + "".join(f"{n};{ip}\n" for n, ip in lista)
            mon.ARQUIVO_APS.write_text(conteudo, encoding="utf-8")
            st.success(f"Lista salva com {len(lista)} AP(s).")
            for a in avisos:
                st.warning("Atenção: " + a)

# ---------------------------------------------------------------- teste manual
with aba_teste:
    st.caption("Testa todos os APs agora, sem esperar o monitor e sem mandar notificação.")
    if st.button("🔎 Testar todos agora"):
        aps = [(n, ip) for n, ip in validar_lista(ler_lista_aps())[0]]
        if not aps:
            st.warning("A lista de APs está vazia.")
        else:
            with st.spinner(f"Testando {len(aps)} AP(s)..."):
                resultado = mon.testar_todos(aps)
            ok = sum(resultado)
            (st.success if ok == len(aps) else st.warning)(f"{ok} de {len(aps)} APs respondendo.")
            st.dataframe(
                pd.DataFrame({"Status": ["🟢 OK" if r else "🔴 Sem resposta" for r in resultado],
                              "AP": [n for n, _ in aps], "IP": [ip for _, ip in aps]}),
                hide_index=True, use_container_width=True,
            )
