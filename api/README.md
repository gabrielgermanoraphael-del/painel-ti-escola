# API de Chamados do TI

Servidor que recebe os chamados abertos pelos QR codes das salas, guarda tudo num banco **PostgreSQL** e permite ao TI acompanhar o atendimento. Feito com **FastAPI**.

```
Professor ──QR code──▶ Página (GitHub Pages) ──POST /chamados──▶ API ──▶ PostgreSQL
                                                                  │
                                                                  └──▶ ntfy ──▶ celular do TI
Painel do TI (Streamlit) ──login + /chamados, /estatisticas──▶ API
```

O que muda em relação à versão anterior:

| Antes | Com a API |
|---|---|
| O tópico do ntfy ficava visível no código da página | O tópico fica só no servidor; a página só fala com a API |
| Chamados guardados num SQLite no notebook | Banco PostgreSQL na nuvem, com histórico completo |
| Só um computador via os chamados | Qualquer técnico com login acessa, de qualquer lugar |
| Qualquer valor de `?sala=` era aceito | Só salas cadastradas; o resto recebe "sala não cadastrada" |
| Sem proteção contra repetição | Limite por IP e chamados repetidos em 2 minutos são unificados |

## Endpoints

Documentação interativa em **`/docs`** depois que a API estiver no ar.

| Método | Rota | Acesso | Para quê |
|---|---|---|---|
| GET | `/saude` | público | Verifica se a API e o banco estão no ar |
| POST | `/chamados` | público | A página do QR abre um chamado (`sala`, `tipo`, `detalhe`) |
| GET | `/locais/publico/{codigo}` | público | Nome de um local pelo código do QR |
| POST | `/auth/login` | público | Login do técnico (devolve um token) |
| GET | `/chamados` | técnico | Lista com filtros (`status`, `desde`, `ate`, `local_id`) |
| GET | `/chamados/{id}` | técnico | Detalhe de um chamado |
| POST | `/chamados/manual` | técnico | Registra um pedido feito pessoalmente |
| POST | `/chamados/{id}/atender` | técnico | Marca "Em atendimento" |
| POST | `/chamados/{id}/resolver` | técnico | Marca "Resolvido", com a solução |
| POST | `/chamados/{id}/reabrir` | técnico | Volta para "Aberto" |
| GET | `/estatisticas?dias=30` | técnico | Totais, tempo médio, por tipo, por local e por dia |
| GET | `/locais` | técnico | Salas cadastradas |
| POST/PATCH | `/locais` | admin | Cadastra ou desativa salas |
| POST | `/usuarios` | admin | Cria técnicos |

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

Testes (14 cenários, incluindo segurança e limites):

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
   - `NTFY_TOPIC`: um tópico **novo**, longo e aleatório. Inscreva-se nele no app ntfy.
4. Publique e teste `https://SEU-SERVICO.onrender.com/saude`.

**3. Primeiro usuário**

No seu computador, aponte para o banco da nuvem e crie o admin:

```bash
set DATABASE_URL=postgresql://...      (Windows)   |   export DATABASE_URL=...   (Linux/Mac)
python -m app.cli criar-usuario gabriel "Gabriel" --admin
```

Depois disso, novos técnicos podem ser criados pela própria API (`POST /usuarios`, em `/docs`).

**4. Ligar a página e o painel**
- **Página do QR** (repositório `chamar-ti`): use o `index.html` da versão com API e preencha `API_URL` com o endereço do Render. Os QR codes impressos continuam os mesmos.
- **Painel**: na página *Chamados*, informe o endereço da API, usuário e senha (fica salvo em `api.json`, fora do GitHub).
- **Monitor de APs** (opcional): preencha `API_SAUDE_URL` no `monitor_aps.py` para manter a API acordada no horário de aula.

### Atenção ao plano gratuito

- O Web Service gratuito do Render **adormece após 15 minutos sem acesso**, e o primeiro chamado depois disso pode levar **cerca de 1 minuto**. O monitor de APs com `API_SAUDE_URL` evita isso durante o expediente. Para produção, use um plano pago sempre ligado.
- O Render dá 750 horas gratuitas por mês por conta, suficiente para 1 serviço ligado o mês todo.
- O Neon gratuito suspende o banco após 5 minutos parado e volta sozinho no próximo acesso.

Os limites dos planos mudam com o tempo; confira nas páginas oficiais antes de publicar.

## Segurança

- Senhas guardadas com PBKDF2-SHA256 (600 mil iterações); login com token JWT de 12 horas.
- Endpoint público com limite por IP (10 chamados a cada 10 minutos) e unificação de repetidos.
- CORS liberado só para a página do QR code.
- O endpoint público não devolve dados internos (nem detalhes de outros chamados).
- O limite por IP fica em memória: vale para **uma instância**. Para várias instâncias, troque por Redis.
- As tabelas são criadas automaticamente na primeira execução. Para mudanças futuras de estrutura, adote o Alembic (migrações).
