# Servidor no computador do TI (piloto)

Este modo roda a API no próprio computador do TI e a publica na internet com HTTPS pelo **Tailscale Funnel**: é gratuito, o endereço é fixo e não precisa mexer no roteador da escola. Assim o celular dos professores alcança o sistema de qualquer rede (Wi‑Fi da escola ou 4G).

```
Celular do professor ─HTTPS─▶ página do QR (GitHub Pages) ─HTTPS─▶ Tailscale Funnel ─▶ API neste PC (porta 8000)
Painel do TI (Streamlit, neste PC) ─────────────────────────────────────────────────▶ http://127.0.0.1:8000
```

| Arquivo | Para quê |
|---|---|
| `iniciar_servidor.bat` | Liga a API (dois cliques). Também faz o backup do dia. |
| `criar_usuario.bat` | Cria uma conta do TI para o painel. |
| `config_local.cmd` | Criado na 1ª vez. Guarda o Client ID, o segredo e o tópico. **Fica só neste PC** (está no `.gitignore`). |
| `../dados/chamados.db` | O banco de dados. Os backups ficam em `../dados/backup` (os últimos 30 dias). Também fora do GitHub. |

## Uma vez só

1. **Ambiente da API** (Python 3.12, igual ao teste local). Pule esta etapa se a pasta `api\.venv` já existe:
   ```bat
   cd api
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   python -m pip install -r requirements.txt
   ```
2. **Configuração:** dê dois cliques em `iniciar_servidor.bat`. Na 1ª vez ele cria o `config_local.cmd`, já com um segredo aleatório, e abre esse arquivo no Bloco de Notas. Preencha:
   - `GOOGLE_CLIENT_ID`: o mesmo ID do teste local.
   - `NTFY_TOPIC`: invente um tópico longo e difícil de adivinhar, por exemplo `ti-escola-k7Qp2xVm9RtA4wLz`. No app **ntfy** do celular, assine esse mesmo tópico. Quem souber o nome do tópico consegue ler os avisos, então não divulgue.

   Salve o arquivo.
3. **Sua conta do painel:** dê dois cliques em `criar_usuario.bat`. Responda `s` em "Administrador?". Como o banco é novo (em `dados/`), a conta do teste local não vem junto.
4. **Tailscale Funnel:**
   - Instale o Tailscale ([tailscale.com/download](https://tailscale.com/download)) e entre com uma conta, por exemplo a sua do Google.
   - Abra o **cmd como administrador** e rode:
     ```bat
     tailscale funnel --bg 8000
     ```
   - Na 1ª vez ele mostra um link para ativar o HTTPS e o Funnel na sua conta. Abra o link, autorize e rode o comando de novo.
   - Ele mostra o endereço público, algo como `https://nome-do-pc.tail1234.ts.net`. **Anote.**
   - O `--bg` deixa o túnel ligado sempre, inclusive depois de reiniciar o PC. Para conferir: `tailscale funnel status`. Para desligar: `tailscale funnel --https=443 off`.
5. **Teste do celular (no 4G, fora do Wi‑Fi):** abra `https://SEU-ENDERECO.ts.net/saude`. Tem que aparecer `{"status":"ok"...}`.
6. **Página do QR** (repositório `chamar-ti`): troque o `index.html` pelo `pagina-qr/index.html` deste projeto, com `API_URL` = o endereço do Funnel (sem barra no final).
7. **Painel:** `python -m streamlit run painel.py` (como no teste). Na página Chamados, use o endereço `http://127.0.0.1:8000` e entre com a conta do passo 3.

## Para o PC não "dormir"

O Windows suspende sozinho depois de um tempo, e suspenso o PC não recebe chamados. Num cmd como administrador:
```bat
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```
A tela ainda pode apagar; o que importa é o PC não suspender.

## Ligar sozinho ao entrar no Windows (opcional)

1. Aperte `Win + R`, digite `shell:startup` e dê Enter.
2. Nessa pasta, crie um **atalho** para `iniciar_servidor.bat`.

## Cuidados

- PC desligado, suspenso ou sem internet = professores veem "Sem conexão" até ele voltar.
- Os dados dos professores (nome, e-mail) ficam neste PC. Combine com a gestão (LGPD).
- Não apague a pasta `dados`. Copie `dados/backup` para um pendrive de vez em quando.
- Se a rede da escola bloquear o Tailscale, use a opção em nuvem (Render + Neon, descrita no README da API).
