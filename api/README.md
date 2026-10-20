# API de Chamados do TI

Servidor que recebe os chamados abertos pelos QR codes das salas, guarda tudo num banco **PostgreSQL** e permite ao TI acompanhar o atendimento. Feito com **FastAPI**.

```
Professor ──QR code──▶ Página (GitHub Pages) ──"Entrar com Google"──▶ POST /auth/google ──▶ API ──▶ PostgreSQL
                                             ──POST /chamados (com token)─────────────────▶  │
                                                                                              └──▶ ntfy próprio ──▶ celular do TI
Painel do TI (Streamlit) ──usuário e senha + /chamados, /pessoas, /estatisticas──▶ API
```

Só quem entra com o e-mail institucional **@educ.indaiatuba.sp.gov.br** e foi liberado pelo TI consegue abrir chamado, e só nas salas liberadas para ele.

O que muda em relação à versão anterior:

| Antes | Com a API |
|---|---|
| O tópico do ntfy ficava visível no código da página | O tópico fica só no servidor; a página só fala com a API |
| Chamados guardados num SQLite no notebook | Banco PostgreSQL na nuvem, com histórico completo |
| Só um computador via os chamados | Qualquer técnico com login acessa, de qualquer lugar |
| Qualquer valor de `?sala=` era aceito | Só salas cadastradas; o resto recebe "sala não cadastrada" |
| Sem proteção contra repetição | Limite por professor e por IP; chamados repetidos em 2 minutos são unificados |
| Qualquer pessoa com o link abria chamado | Login Google institucional + liberação pelo TI, sala por sala |
| Não dava para saber quem chamou | Cada chamado mostra quem abriu (nome e e-mail) |

## Endpoints

Documentação interativa em **`/docs`** depois que a API estiver no ar.

| Método | Rota | Acesso | Para quê |
|---|---|---|---|
| GET | `/saude` | público | Verifica se a API e o banco estão no ar |
| GET | `/config/publica` | público | Client ID do Google e domínio permitido (a página usa para montar o botão) |
| GET | `/locais/publico/{codigo}` | público | Nome de um local pelo código do QR |
| POST | `/auth/google` | público | Login do professor com o token do Google. Primeiro acesso: fica **pendente** e recebe um código |
| GET | `/professor/eu` | professor | Situação do professor: pendente, liberado (com as salas) ou bloqueado |
| POST | `/chamados` | professor liberado | Abre um chamado (`sala`, `tipo`, `detalhe`), só nas salas liberadas |
| POST | `/auth/login` | público | Login do técnico (devolve um token) |
| GET | `/pessoas?status=` | técnico | Professores que já entraram (pendentes, liberados, bloqueados) |
| GET | `/pessoas/codigo/{codigo}` | técnico | Acha o professor pelo código que apareceu no celular dele |
| PUT | `/pessoas/{id}/acesso` | técnico | Libera, bloqueia e define as salas (`status`, `todas_salas`, `salas`) |
| GET | `/chamados` | técnico | Lista com filtros (`status`, `desde`, `ate`, `local_id`) |
| GET | `/chamados/{id}` | técnico | Detalhe de um chamado |
| POST | `/chamados/manual` | técnico | Registra um pedido feito pessoalmente |
| POST | `/chamados/{id}/assumir` | técnico | Assume o chamado (registra quem e quando) e avisa a equipe. Se outro técnico já assumiu, devolve 409; com `?transferir=true` passa para você |
| POST | `/chamados/{id}/resolver` | técnico | Marca "Resolvido", com a solução. Só quem assumiu (ou um administrador) resolve |
| POST | `/chamados/{id}/reabrir` | técnico | Volta para "Aberto", sem ninguém assumido |
| GET | `/chamados/{id}/registro` | técnico | Linha do tempo: aberto, registrado, assumido, transferido, resolvido, reaberto (quem e quando) |
| GET | `/estatisticas?dias=30` | técnico | Totais, tempo médio, por tipo, por local e por dia |
| GET | `/locais` | técnico | Salas cadastradas |
| POST/PATCH | `/locais` | admin | Cadastra ou desativa salas |
| GET/POST | `/usuarios` | admin | Lista e cria contas do TI (técnico ou administrador) |
| PATCH | `/usuarios/{id}` | admin | Muda papel, desativa ou troca a senha de uma conta do TI |

### Quem pode o quê

| Perfil | Como entra | Pode |
|---|---|---|
| Professor | Google institucional, pela página do QR | Abrir chamado nas salas liberadas para ele |
| Técnico | Usuário e senha, no painel | Assumir e resolver chamados, liberar professores e escolher as salas deles |
| Administrador | Usuário e senha, no painel | Tudo do técnico + criar contas do TI, cadastrar e desativar salas |

### Como o professor é liberado

1. O professor escaneia o QR da sala e toca em **Fazer login com o Google** (e-mail institucional).
2. No primeiro acesso aparece **"Falta só liberar o seu acesso"** com um código, por exemplo `K7P-3QX`.
3. No painel, página **Professores**, o TI digita o código, marca as salas em que ele dá aula (ou "todas as salas", para coordenação e direção) e clica em **Liberar acesso**.
4. O professor toca em **Já fui liberado, atualizar** e já pode chamar. Ele fica conectado no celular por 30 dias.

Se o professor abrir o QR de uma sala que não é dele, a página avisa e mostra as salas liberadas. Bloquear alguém no painel corta o acesso na hora.

Tipos aceitos: `internet`, `chave`, `lousa`, `projetor`, `computador`, `som`, `tablet`, `impressora`, `outro`.

As salas já impressas nos QR codes (1 a 8, 11, 12, Sala 13 (IPP), Secretaria, Sala dos Professores e Coordenação) são cadastradas automaticamente na primeira vez.

## Rodar no computador (para testar)

Precisa do Python 3.10 ou mais novo.

```bash
cd api
python -m pip install -r requirements.txt
python -m app.cli criar-usuario gabriel "Gabriel" --admin   # pede a senha
python -m uvicorn app.main:app --reload
```

Sem `DATABASE_URL`, usa um SQLite local (`chamados_dev.db`). Abra http://127.0.0.1:8000/docs.

Testes (27 cenários, incluindo login Google simulado, permissões por sala, segurança e limites):

```bash
python -m unittest -v                                     # SQLite
TEST_DATABASE_URL=postgresql+psycopg://... python -m unittest -v   # PostgreSQL
```

## Publicar na nuvem (piloto)

Sugestão de serviços gratuitos para o piloto: **Neon** para o banco e **Render** para a API.

> Por que não o banco gratuito do próprio Render? Ele expira 30 dias depois de criado. O plano gratuito do Neon não expira.

**1. Banco (Neon)**
1. Crie uma conta em neon.com e um projeto.
2. Copie a *connection string* (`postgresql://...?sslmode=require`).

**2. API (Render)**
1. Em render.com, crie um **Web Service** a partir deste repositório.
2. *Root Directory*: `api` · *Runtime*: Docker (usa o `Dockerfile` desta pasta).
3. Em *Environment*, cadastre as variáveis do `.env.example`:
   - `DATABASE_URL`: a string do Neon
   - `JWT_SECRET`: gere com `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `CORS_ORIGINS`: `https://gabrielgermanoraphael-del.github.io`
   - `NTFY_URL`, `NTFY_TOPIC` e `NTFY_TOKEN`: do servidor ntfy próprio (veja [`ntfy-servidor/`](../ntfy-servidor/README.md)). O token só consegue publicar no tópico `chamados`.
4. Publique e teste `https://SEU-SERVICO.onrender.com/saude`.

   - `GOOGLE_CLIENT_ID`: veja **Login com Google** abaixo
   - `DOMINIO_PERMITIDO`: `educ.indaiatuba.sp.gov.br` (já é o padrão)

**3. Primeiro usuário**

No seu computador, aponte para o banco da nuvem e crie o admin:

```bash
set DATABASE_URL=postgresql://...      (Windows)   |   export DATABASE_URL=...   (Linux/Mac)
python -m app.cli criar-usuario gabriel "Gabriel" --admin
```

Depois disso, novas contas do TI são criadas pelo painel (página **Professores** → *Contas do TI*, só para administradores).

**4. Ligar a página e o painel**
- **Página do QR** (repositório `chamar-ti`): use o `index.html` da versão com API e preencha `API_URL` com o endereço do Render. Os QR codes impressos continuam os mesmos.
- **Painel**: na página *Chamados*, informe o endereço da API, usuário e senha (fica salvo em `api.json`, fora do GitHub).
- **Monitor de APs** (opcional): preencha `API_SAUDE_URL` no `monitor_aps.py` para manter a API acordada no horário de aula.

## Login com Google (Client ID)

A página do QR usa o botão oficial **"Fazer login com o Google"**. Ele precisa de um *Client ID* criado no Google Cloud (gratuito):

1. Acesse **console.cloud.google.com** e crie um projeto (ex.: *Chamados TI*). Se puder, crie com a conta institucional, assim o projeto fica dentro da organização da prefeitura.
2. Abra **Google Auth Platform** (no menu antigo: *APIs e serviços → Tela de consentimento OAuth*):
   - *Branding*: nome do app (ex.: *Chamar o TI*) e e-mail de suporte.
   - *Público* (*Audience*): **Interno** se o projeto estiver na organização da prefeitura (só contas do domínio conseguem entrar). Se aparecer só **Externo**, escolha Externo e publique o app em produção. Como o login pede só nome, e-mail e foto, não precisa de verificação do Google.
3. Em **Clientes** (*Credenciais*), crie um **ID do cliente OAuth** do tipo **Aplicativo da Web**:
   - *Origens JavaScript autorizadas*: `https://gabrielgermanoraphael-del.github.io` (sem barra e sem caminho no final).
   - *URIs de redirecionamento*: não precisa.
4. Copie o **ID do cliente** (termina em `.apps.googleusercontent.com`) para a variável `GOOGLE_CLIENT_ID` no Render. A página pega esse valor sozinha pela API.

Mesmo com o projeto *Externo*, a API só aceita contas do domínio institucional: ela confere a assinatura do Google, se o token foi emitido para este Client ID, se o e-mail é verificado e se a conta pertence a `educ.indaiatuba.sp.gov.br`.

> **Se aparecer "Acesso bloqueado" ou "app não aprovado pelo administrador"** no login: o administrador do Google Workspace da prefeitura bloqueou apps de terceiros. Peça para ele marcar o Client ID como **confiável** em *Admin Console → Segurança → Controles de API → Controle de acesso de apps*.

Os menus do Google Cloud mudam de nome com frequência; se não achar um item, procure pelo nome em inglês entre parênteses.

### Atenção ao plano gratuito

- O Web Service gratuito do Render **adormece após 15 minutos sem acesso**, e o primeiro chamado depois disso pode levar **cerca de 1 minuto**. O monitor de APs com `API_SAUDE_URL` evita isso durante o expediente. Para produção, use um plano pago sempre ligado.
- O Render dá 750 horas gratuitas por mês por conta, suficiente para 1 serviço ligado o mês todo.
- O Neon gratuito suspende o banco após 5 minutos parado e volta sozinho no próximo acesso.

Os limites dos planos mudam com o tempo; confira nas páginas oficiais antes de publicar.

## Segurança

- Senhas guardadas com PBKDF2-SHA256 (600 mil iterações); login com token JWT de 12 horas.
- Professores entram com Google: a API confere o token no servidor (assinatura RS256 com as chaves públicas do Google, `aud`, `iss`, validade, e-mail verificado e domínio pelo campo `hd` **e** pelo final do e-mail).
- O token do professor (30 dias) e o do técnico (12 horas) são separados: um não funciona no lugar do outro. A situação do professor é conferida a cada chamado, então bloquear vale na hora.
- O código de liberação só serve para o TI achar a pessoa; quem libera é sempre um técnico logado.
- Limite de 10 chamados a cada 10 minutos por professor e 60 por IP (na escola, todos os celulares saem pelo mesmo IP). Repetidos em 2 minutos são unificados.
- CORS liberado só para a página do QR code.
- Avisos no celular por servidor ntfy próprio, fechado com login: a API usa um token que só publica, e os técnicos usam senha que só lê.
- O endpoint público não devolve dados internos (nem detalhes de outros chamados).
- O limite por IP fica em memória: vale para **uma instância**. Para várias instâncias, troque por Redis.
- As tabelas são criadas automaticamente na primeira execução (bancos da versão anterior ganham a coluna nova sozinhos). Para mudanças futuras de estrutura, adote o Alembic (migrações).
