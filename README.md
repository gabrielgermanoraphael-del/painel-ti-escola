# Painel do TI – Escola

Ferramentas para o dia a dia do TI escolar: monitoramento dos pontos de acesso (APs) da rede e controle dos chamados que os professores abrem pelo QR code das salas.

Feito em Python, com painel web em [Streamlit](https://streamlit.io) e notificações no celular pelo [ntfy](https://ntfy.sh).

## O que tem aqui

| Parte | Arquivo | O que faz |
|---|---|---|
| Monitor de APs | `monitor_aps.py` | Testa (ping) cada AP a cada minuto. Se um AP cair ou voltar, manda notificação para o celular. Grava `status.json` e o histórico em `eventos.csv`. |
| Painel | `painel.py` | Mostra cada AP (🟢 online, 🟡 instável, 🔴 fora), histórico de quedas, edição da lista de APs e teste manual. |
| Chamados | `pages/Chamados.py` | Lista os chamados da API e controla o andamento: Aberto → Em atendimento → Resolvido. Também tem registro manual, histórico, exportação para Excel e estatísticas. Mostra quem abriu cada chamado. Na primeira vez pede o endereço da API, usuário e senha (salvos em `api.json`). |
| Professores | `pages/Professores.py` | Libera os professores que entraram com o Google na página do QR: digita o código que apareceu no celular, escolhe as salas e libera. Também bloqueia e, para administradores, gerencia as contas do TI. |
| Atalho | `abrir_painel.pyw`, `criar_atalho.py`, `painel.ico` | Cria o ícone **Painel do TI** na área de trabalho, que abre o painel com um clique. |
| API | `api/` | **Nova:** API de chamados (FastAPI + PostgreSQL) que recebe os chamados do QR code, guarda no banco e atende o painel. Veja [`api/README.md`](api/README.md). |

Os chamados chegam pela página de QR code do repositório [chamar-ti](https://github.com/gabrielgermanoraphael-del/chamar-ti): o professor escaneia, entra com o e-mail institucional (Google), escolhe o problema (internet, chave do carrinho, lousa digital, projetor...) e o aviso chega no celular e no painel.

## Instalação

Precisa do Python 3.9 ou mais novo (no Windows, marque **"Add python.exe to PATH"** ao instalar).

```bash
python -m pip install -r requirements.txt
```

Depois:

1. Copie `aps.exemplo.txt` com o nome `aps.txt` e coloque os seus APs, um por linha, no formato `Sala 5;192.168.1.25`.
2. Troque o tópico do ntfy (`TOPICO_NTFY`) em `monitor_aps.py` pelo seu e inscreva-se nele no app ntfy do celular (os avisos de chamados vêm da API, com o tópico configurado no servidor).
3. (Opcional, Windows) Crie o atalho na área de trabalho:
   ```bash
   python criar_atalho.py
   ```

## Como usar

```bash
python -m streamlit run painel.py     # abre o painel no navegador (ou use o atalho)
python monitor_aps.py --teste         # testa todos os APs uma vez e manda uma notificação de teste
python monitor_aps.py                 # liga o monitor (também dá para ligar pelo botão do painel)
```

## Observações

- Os chamados ficam guardados no banco da API: o painel pode ficar fechado sem perder nada.
- Para o monitor enxergar os APs, o computador precisa estar na mesma rede deles. Se tudo aparecer "sem resposta" no Wi-Fi, use o cabo de rede.
- Os dados da escola (`aps.txt`, `chamados.db`, `eventos.csv`, `status.json` e logs) ficam só no computador e não são enviados ao GitHub (veja o `.gitignore`).
