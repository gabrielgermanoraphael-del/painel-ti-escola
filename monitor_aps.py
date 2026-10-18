#!/usr/bin/env python3
"""
Monitor de APs da escola
------------------------
Testa (ping) cada AP da lista em aps.txt a cada minuto e manda um aviso
para o celular pelo ntfy quando algum AP cai e quando ele volta.

Uso:
    python monitor_aps.py          -> começa a monitorar (Ctrl+C para parar)
    python monitor_aps.py --teste  -> testa todos os APs uma vez e manda
                                      uma notificação de teste

Só usa bibliotecas que já vêm com o Python. Funciona no Windows, Linux e macOS.
"""

import csv
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# ====================== CONFIGURAÇÃO ======================
TOPICO_NTFY = "chamados-aparecido-batista"  # mesmo tópico do app ntfy
INTERVALO_SEGUNDOS = 60      # de quanto em quanto tempo testa os APs
FALHAS_PARA_ALERTAR = 3      # quantos testes seguidos sem resposta antes de avisar
TENTATIVAS_POR_TESTE = 2     # pings por AP em cada teste
TIMEOUT_PING_MS = 1000       # espera máxima de cada ping
# ===========================================================

PASTA = Path(__file__).resolve().parent
ARQUIVO_APS = PASTA / "aps.txt"
ARQUIVO_LOG = PASTA / "monitor_aps.log"
NO_WINDOWS = platform.system() == "Windows"


def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def log(msg):
    linha = f"[{agora()}] {msg}"
    print(linha, flush=True)
    try:
        with open(ARQUIVO_LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


def carregar_aps():
    """Lê aps.txt. Cada linha: Nome;IP  (linhas com # são ignoradas)."""
    if not ARQUIVO_APS.exists():
        sys.exit(f"Arquivo {ARQUIVO_APS} não encontrado. Copie o aps.exemplo.txt com o nome aps.txt "
                 "e coloque seus APs no formato: Sala 5;192.168.1.25")
    aps = []
    for n, linha in enumerate(ARQUIVO_APS.read_text(encoding="utf-8").splitlines(), 1):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if ";" not in linha:
            log(f"Linha {n} do aps.txt ignorada (use Nome;IP): {linha}")
            continue
        nome, ip = (p.strip() for p in linha.split(";", 1))
        if nome and ip:
            aps.append((nome, ip))
    if not aps:
        sys.exit("Nenhum AP no aps.txt. Adicione linhas no formato: Sala 5;192.168.1.25")
    vistos = {}
    for nome, ip in aps:
        if ip in vistos:
            log(f"ATENÇÃO: '{nome}' e '{vistos[ip]}' estão com o mesmo IP ({ip}) no aps.txt. Confira se um deles está errado.")
        vistos.setdefault(ip, nome)
    return aps


def ping(ip):
    """True se o IP respondeu a pelo menos um ping."""
    for _ in range(TENTATIVAS_POR_TESTE):
        if NO_WINDOWS:
            cmd = ["ping", "-n", "1", "-w", str(TIMEOUT_PING_MS), ip]
        elif platform.system() == "Darwin":
            cmd = ["ping", "-c", "1", "-W", str(TIMEOUT_PING_MS), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(max(1, TIMEOUT_PING_MS // 1000)), ip]
        try:
            r = subprocess.run(
                cmd, capture_output=True, timeout=TIMEOUT_PING_MS / 1000 + 3,
                creationflags=0x08000000 if NO_WINDOWS else 0,  # não abre janela no Windows
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        saida = r.stdout.decode(errors="ignore").upper()
        # No Windows o ping pode retornar "sucesso" com "Host de destino inacessível";
        # só conta como resposta se aparecer TTL= na saída.
        if r.returncode == 0 and (not NO_WINDOWS or "TTL=" in saida):
            return True
    return False


def tem_internet():
    """Confere se o próprio notebook está conectado (consegue alcançar o ntfy)."""
    try:
        with socket.create_connection(("ntfy.sh", 443), timeout=5):
            return True
    except OSError:
        return False


def notificar(titulo, mensagem, tags, prioridade=4):
    corpo = json.dumps({
        "topic": TOPICO_NTFY, "title": titulo, "message": mensagem,
        "tags": tags, "priority": prioridade,
    }).encode("utf-8")
    req = urllib.request.Request("https://ntfy.sh/", data=corpo, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001
        log(f"Falha ao enviar notificação: {e}")
        return False


def duracao(segundos):
    m = int(segundos // 60)
    if m < 1:
        return "menos de 1 min"
    if m < 60:
        return f"{m} min"
    return f"{m // 60}h{m % 60:02d}"


def testar_todos(aps):
    """Lista de True/False na mesma ordem do aps.txt (uma posição por linha)."""
    with ThreadPoolExecutor(max_workers=min(16, len(aps))) as ex:
        return list(ex.map(ping, [ip for _, ip in aps]))


def modo_teste(aps):
    print(f"Testando {len(aps)} AP(s)...\n")
    resultado = testar_todos(aps)
    for (nome, ip), ok in zip(aps, resultado):
        print(f"  {'OK          ' if ok else 'SEM RESPOSTA'}  {nome} ({ip})")
    print()
    if notificar("Teste do monitor de APs",
                 f"{sum(resultado)} de {len(aps)} APs respondendo.", ["test_tube"], 3):
        print("Notificação de teste enviada. Confira o celular.")
    else:
        print("Não consegui enviar a notificação (sem internet ou ntfy bloqueado).")


ARQUIVO_STATUS = PASTA / "status.json"
ARQUIVO_EVENTOS = PASTA / "eventos.csv"


def registrar_evento(evento, nome="", ip="", detalhe=""):
    """Guarda cada queda/volta em eventos.csv (usado pelo painel e abre no Excel)."""
    novo = not ARQUIVO_EVENTOS.exists()
    try:
        with open(ARQUIVO_EVENTOS, "a", encoding="utf-8-sig" if novo else "utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            if novo:
                w.writerow(["data_hora", "evento", "ap", "ip", "detalhe"])
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), evento, nome, ip, detalhe])
    except OSError:
        pass


def salvar_status(aps, resultado, falhas, caido_desde, sem_rede=False):
    """Escreve status.json com a situação atual de cada AP (lido pelo painel)."""
    lista = []
    for i, (nome, ip) in enumerate(aps):
        if i in caido_desde:
            estado = "fora"
        elif resultado is not None and resultado[i]:
            estado = "online"
        elif resultado is None:
            estado = "aguardando"
        else:
            estado = "instavel"
        lista.append({
            "nome": nome, "ip": ip, "estado": estado, "falhas": falhas[i],
            "fora_desde": datetime.fromtimestamp(caido_desde[i]).isoformat(timespec="seconds")
            if i in caido_desde else None,
        })
    dados = {
        "atualizado": datetime.now().isoformat(timespec="seconds"),
        "intervalo": INTERVALO_SEGUNDOS, "pid": os.getpid(), "sem_rede": sem_rede, "aps": lista,
    }
    tmp = ARQUIVO_STATUS.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ARQUIVO_STATUS)
    except OSError:
        pass


def monitorar(aps):
    falhas = [0] * len(aps)                  # testes seguidos sem resposta (uma posição por AP)
    caido_desde = {}                         # posição do AP -> horário em que foi considerado caído
    alerta_geral = False                     # já avisou que TODOS caíram?
    mtime_lista = ARQUIVO_APS.stat().st_mtime

    log(f"Monitor iniciado com {len(aps)} AP(s). Ctrl+C para parar.")
    registrar_evento("MONITOR_LIGADO", detalhe=f"{len(aps)} APs")
    salvar_status(aps, None, falhas, caido_desde)
    notificar("Monitor de APs ligado", f"Vigiando {len(aps)} APs.", ["satellite_antenna"], 2)

    while True:
        inicio = time.time()

        # Lista de APs editada (pelo painel ou no bloco de notas)? Recarrega sem precisar reiniciar.
        try:
            mtime = ARQUIVO_APS.stat().st_mtime
            if mtime != mtime_lista:
                mtime_lista = mtime
                novos = carregar_aps()
                antigos = {ap: (falhas[i], caido_desde.get(i)) for i, ap in enumerate(aps)}
                aps = novos
                falhas = [antigos.get(ap, (0, None))[0] for ap in aps]
                caido_desde = {i: antigos[ap][1] for i, ap in enumerate(aps)
                               if ap in antigos and antigos[ap][1] is not None}
                log(f"Lista de APs atualizada: agora são {len(aps)} AP(s).")
                registrar_evento("LISTA_ATUALIZADA", detalhe=f"{len(aps)} APs")
        except (OSError, SystemExit):
            pass

        resultado = testar_todos(aps)

        # Nenhum AP respondeu: pode ser a rede do próprio notebook
        if not any(resultado):
            if not tem_internet():
                log("Nenhum AP respondeu e o notebook está sem internet. Ignorando esta rodada.")
                salvar_status(aps, resultado, falhas, caido_desde, sem_rede=True)
                time.sleep(INTERVALO_SEGUNDOS)
                continue
            falhas = [f + 1 for f in falhas]
            if not alerta_geral and min(falhas) >= FALHAS_PARA_ALERTAR:
                alerta_geral = True
                for i in range(len(aps)):
                    caido_desde.setdefault(i, time.time())
                log("ALERTA: nenhum AP respondendo.")
                registrar_evento("QUEDA_GERAL", detalhe="Nenhum AP respondendo")
                notificar("⚠️ Todos os APs sem resposta",
                          "Nenhum AP responde. Verifique o switch, os injetores PoE ou a energia do rack.",
                          ["rotating_light"], 5)
            salvar_status(aps, resultado, falhas, caido_desde)
            time.sleep(max(0, INTERVALO_SEGUNDOS - (time.time() - inicio)))
            continue

        # Voltando de uma queda geral: um aviso só, em vez de um por AP
        if alerta_geral:
            voltaram = [aps[i][0] for i in range(len(aps)) if resultado[i] and i in caido_desde]
            tempo = duracao(time.time() - min(caido_desde.values()))
            for i in range(len(aps)):
                if resultado[i]:
                    caido_desde.pop(i, None)
                    falhas[i] = 0
            ainda_fora = [aps[i][0] for i in range(len(aps)) if not resultado[i]]
            msg = f"{len(voltaram)} de {len(aps)} APs voltaram após {tempo}."
            if ainda_fora:
                msg += " Ainda sem resposta: " + ", ".join(ainda_fora) + "."
            log("VOLTARAM após queda geral. " + msg)
            registrar_evento("REDE_VOLTOU", detalhe=msg)
            notificar("✅ Rede voltou", msg, ["white_check_mark"], 3)

        for i, (nome, ip) in enumerate(aps):
            if resultado[i]:
                if i in caido_desde:
                    tempo = duracao(time.time() - caido_desde.pop(i))
                    log(f"VOLTOU: {nome} ({ip}) após {tempo}")
                    registrar_evento("VOLTOU", nome, ip, f"fora por {tempo}")
                    notificar(f"✅ AP {nome} voltou", f"{nome} ({ip}) voltou a responder após {tempo}.",
                              ["white_check_mark"], 3)
                falhas[i] = 0
            else:
                falhas[i] += 1
                if falhas[i] >= FALHAS_PARA_ALERTAR and i not in caido_desde:
                    caido_desde[i] = time.time()
                    log(f"CAIU: {nome} ({ip})")
                    registrar_evento("CAIU", nome, ip)
                    notificar(f"⚠️ AP {nome} caiu", f"{nome} ({ip}) parou de responder.",
                              ["warning"], 4)
        alerta_geral = False
        salvar_status(aps, resultado, falhas, caido_desde)

        time.sleep(max(0, INTERVALO_SEGUNDOS - (time.time() - inicio)))


if __name__ == "__main__":
    lista = carregar_aps()
    try:
        if "--teste" in sys.argv:
            modo_teste(lista)
        else:
            monitorar(lista)
    except KeyboardInterrupt:
        log("Monitor encerrado.")
        registrar_evento("MONITOR_DESLIGADO")
