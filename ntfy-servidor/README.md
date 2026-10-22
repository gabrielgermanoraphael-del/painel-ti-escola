# Servidor de notificações próprio (ntfy)

Servidor **ntfy** do TI, fechado com login, para os avisos de chamados e de APs chegarem no celular sem passar pelo ntfy.sh público.

```
API de chamados ──token "api" (só publica em chamados)──┐
Monitor de APs  ──token "monitor" (só publica em aps)───┤──HTTPS──▶  ntfy (Oracle Cloud)  ──▶ app ntfy no Android
                                                         │                                    (usuário e senha, só lê)
Qualquer outra pessoa ──────────────── bloqueado (403) ──┘
```

| Antes (ntfy.sh público) | Agora (servidor próprio) |
|---|---|
| Quem soubesse o nome do tópico lia e mandava avisos | Ninguém lê nem publica sem login (`deny-all`) |
| Avisos passavam por um servidor de terceiros | Os avisos ficam só no seu servidor |
| Uma "senha" (o tópico) para tudo | Um token por remetente, que **só publica**; uma senha por técnico, que **só lê** |
| | HTTPS automático, sem site público (só o app e a API acessam) |

Arquivos desta pasta:

| Arquivo | Para quê |
|---|---|
| `instalar-oracle.sh` | Instala Docker e libera as portas 80/443 na VM (uma vez) |
| `configurar.sh` | Cria usuários, permissões e tokens. Gera `server.yml`, `.env` e `credenciais.txt` (nenhum vai para o GitHub) |
| `docker-compose.yml` | Sobe o ntfy e o Caddy (HTTPS automático com Let's Encrypt) |
| `Caddyfile` | Configuração do HTTPS |
| `server.exemplo.yml` | Modelo comentado do que o `configurar.sh` gera |

## 1. Criar a VM gratuita na Oracle Cloud

1. Crie uma conta em **oracle.com/cloud/free**. Ela pede cartão só para confirmar a identidade; os recursos *Always Free* não são cobrados. Escolha a região **Brazil East (São Paulo)** (não dá para trocar depois).
2. No console: **Compute → Instances → Create instance**.
   - **Image**: Canonical **Ubuntu 24.04**.
   - **Shape**: *Ampere* `VM.Standard.A1.Flex` com 1 OCPU e 6 GB (Always Free). Se aparecer *Out of capacity*, use `VM.Standard.E2.1.Micro` (AMD, também Always Free; sobra para o ntfy).
   - **SSH keys**: *Generate a key pair* e **baixe a chave privada** (sem ela não dá para entrar na VM).
3. Anote o **Public IP address** da instância.
4. Libere as portas na rede da Oracle: na página da instância, clique na **subnet → Security Lists → Default Security List → Add Ingress Rules**:
   - Source CIDR `0.0.0.0/0`, IP Protocol **TCP**, Destination Port Range **80**
   - Source CIDR `0.0.0.0/0`, IP Protocol **TCP**, Destination Port Range **443**

> **Atenção:** a Oracle pode recuperar VMs *Always Free* que ficam quase paradas por vários dias, e o ntfy usa pouquíssimo processamento. Para evitar isso, faça o *upgrade* da conta para **Pay As You Go**: os recursos *Always Free* continuam sem custo e as instâncias deixam de ser recuperadas por ociosidade. Confira as regras atuais na página da Oracle e crie um **alerta de orçamento** (*Billing → Budgets*) de R$ 1 para ser avisado de qualquer cobrança.

## 2. Domínio gratuito (DuckDNS)

O HTTPS precisa de um nome, não só do IP.

1. Entre em **duckdns.org** (com Google ou GitHub).
2. Crie um subdomínio, por exemplo `ti-escola` → fica `ti-escola.duckdns.org`.
3. No campo *current ip*, coloque o IP público da VM e clique em **update ip**.

## 3. Instalar e ligar o servidor

No seu computador (PowerShell no Windows), entre na VM:

```bash
ssh -i caminho/da/chave.key ubuntu@IP_DA_VM
```

Na VM:

```bash
git clone https://github.com/gabrielgermanoraphael-del/painel-ti-escola.git
cd painel-ti-escola/ntfy-servidor
bash instalar-oracle.sh
exit                                    # saia e entre de novo pelo ssh
```

Depois de entrar de novo:

```bash
cd painel-ti-escola/ntfy-servidor
./configurar.sh                         # pergunta o domínio, a sua senha e outros técnicos
docker compose up -d
docker compose logs -f                  # espere aparecer "certificate obtained successfully" (Ctrl+C para sair)
```

Teste no navegador: `https://ti-escola.duckdns.org/v1/health` deve mostrar `{"healthy":true}`.

As senhas dos outros técnicos e os tokens ficam em `credenciais.txt`. Copie para um lugar seguro (gerenciador de senhas) e apague: `rm credenciais.txt`.

## 4. Celular (Android)

1. Instale o app **ntfy** (Play Store ou F-Droid).
2. **Configurações → Gerenciar usuários → Adicionar usuário**: URL `https://ti-escola.duckdns.org`, usuário `gabriel` e a sua senha.
3. Na tela inicial, toque em **+**:
   - Tópico `chamados`, marque **Usar outro servidor** e coloque `https://ti-escola.duckdns.org`.
   - Repita para o tópico `aps`.
4. Tire o ntfy da **otimização de bateria** do Android (o app sugere isso), senão os avisos podem atrasar.

Com servidor próprio, o app mantém uma conexão aberta e mostra uma notificação fixa de "conectado". Dá para escondê-la nas configurações de notificação do Android, sem desligar os avisos.

## 5. Ligar a API e o monitor de APs

**API de chamados** (variáveis no Render, valores em `credenciais.txt`):

```
NTFY_URL=https://ti-escola.duckdns.org
NTFY_TOPIC=chamados
NTFY_TOKEN=tk_...
```

**Monitor de APs**: crie o arquivo `ntfy.json` na pasta do painel (ao lado do `monitor_aps.py`) com a linha que está em `credenciais.txt`:

```json
{"servidor": "https://ti-escola.duckdns.org", "topico": "aps", "token": "tk_..."}
```

Teste com `python monitor_aps.py --teste`: a notificação deve chegar no tópico `aps`. O `ntfy.json` não vai para o GitHub. Se ele estiver com erro, o monitor **não** manda o aviso para o ntfy.sh público: registra o problema no `monitor_aps.log`.

## Manutenção

| Quero... | Como |
|---|---|
| Ver se está tudo no ar | `docker compose ps` (os dois com *Up*; o ntfy com *healthy*) |
| Atualizar | Troque a versão em `docker-compose.yml` e rode `docker compose pull && docker compose up -d` |
| Adicionar um técnico **sem trocar os tokens** | `docker run --rm -it binwiederhier/ntfy:v2.32.0 user hash` (gera o hash da senha). No `server.yml`, acrescente `- "nome:HASH:user"` em `auth-users` e `- "nome:chamados:ro"` e `- "nome:aps:ro"` em `auth-access`. Depois: `docker compose restart ntfy` |
| Tirar o acesso de alguém | Apague as linhas da pessoa no `server.yml` e `docker compose restart ntfy` (o usuário é apagado ao reiniciar) |
| Trocar todas as senhas e tokens | `./configurar.sh` de novo, `docker compose restart ntfy` e atualize o Render e o `ntfy.json` |

O ntfy guarda os avisos por 24 horas (o celular recebe o que perdeu se ficar sem internet). A configuração de usuários fica toda no `server.yml`: guarde uma cópia segura dele.
