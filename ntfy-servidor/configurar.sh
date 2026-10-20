#!/usr/bin/env bash
# Gera o server.yml (usuários, permissões e tokens) e o .env (domínio) do servidor ntfy.
# Rode no servidor, dentro desta pasta:   ./configurar.sh
# Rodar de novo gera senhas e tokens NOVOS (atualize a API e o monitor depois).
set -euo pipefail
cd "$(dirname "$0")"
umask 077

NTFY_CMD=${NTFY_CMD:-"docker run --rm -i binwiederhier/ntfy:v2.32.0"}

hash_senha() {  # bcrypt da senha, pelo próprio ntfy
  printf '%s\n%s\n' "$1" "$1" | $NTFY_CMD user hash 2>/dev/null | grep -o '\$2[aby]\$[0-9][0-9]\$[./A-Za-z0-9]\{53\}' | tail -1
}
novo_token() { $NTFY_CMD token generate 2>/dev/null | grep -o 'tk_[a-z0-9]\{29\}' | tail -1; }
senha_aleatoria() { head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20; }

if [[ -f server.yml && -z "${SEM_PERGUNTAS:-}" ]]; then
  read -r -p "Já existe um server.yml. Gerar tudo de novo (senhas e tokens novos)? [s/N] " r
  [[ "$r" =~ ^[sS]$ ]] || { echo "Nada foi alterado."; exit 0; }
fi

# ---- domínio
if [[ -z "${DOMINIO:-}" ]]; then
  read -r -p "Domínio do servidor (ex.: ti-escola.duckdns.org): " DOMINIO
fi
DOMINIO=$(echo "$DOMINIO" | tr 'A-Z' 'a-z' | sed -E 's#^https?://##; s#/.*$##')
[[ "$DOMINIO" =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]] || { echo "Domínio inválido: $DOMINIO"; exit 1; }

# ---- senha do Gabriel (para o app no celular)
if [[ -z "${SENHA_GABRIEL:-}" ]]; then
  while true; do
    read -r -s -p "Crie a senha do usuário 'gabriel' (mínimo 10 caracteres): " SENHA_GABRIEL; echo
    read -r -s -p "Repita a senha: " s2; echo
    [[ "$SENHA_GABRIEL" == "$s2" && ${#SENHA_GABRIEL} -ge 10 ]] && break
    echo "As senhas não conferem ou têm menos de 10 caracteres. Tente de novo."
  done
fi

# ---- outros técnicos (recebem senha aleatória)
if [[ -z "${TECNICOS+x}" ]]; then
  read -r -p "Outros técnicos que vão receber os avisos (usuários separados por espaço, Enter para nenhum): " TECNICOS
fi
TECNICOS=$(echo "${TECNICOS:-}" | tr 'A-Z' 'a-z')
for t in $TECNICOS; do
  [[ "$t" =~ ^[a-z0-9_.-]{2,30}$ && "$t" != "gabriel" && "$t" != "api" && "$t" != "monitor" ]] \
    || { echo "Nome de usuário inválido: $t"; exit 1; }
done

echo "Gerando senhas criptografadas e tokens (pode levar alguns segundos)..."
H_GABRIEL=$(hash_senha "$SENHA_GABRIEL")
H_API=$(hash_senha "$(senha_aleatoria)")
H_MONITOR=$(hash_senha "$(senha_aleatoria)")
TK_API=$(novo_token)
TK_MONITOR=$(novo_token)
for v in "$H_GABRIEL" "$H_API" "$H_MONITOR" "$TK_API" "$TK_MONITOR"; do
  [[ -n "$v" ]] || { echo "Falha ao gerar hash/token. O Docker está funcionando? (docker run hello-world)"; exit 1; }
done

USUARIOS="  - \"gabriel:$H_GABRIEL:user\"
  - \"api:$H_API:user\"
  - \"monitor:$H_MONITOR:user\""
ACESSOS="  - \"gabriel:chamados:ro\"
  - \"gabriel:aps:ro\"
  - \"api:chamados:wo\"
  - \"monitor:aps:wo\""
SENHAS_TECNICOS=""
for t in $TECNICOS; do
  s=$(senha_aleatoria)
  USUARIOS+=$'\n'"  - \"$t:$(hash_senha "$s"):user\""
  ACESSOS+=$'\n'"  - \"$t:chamados:ro\""$'\n'"  - \"$t:aps:ro\""
  SENHAS_TECNICOS+="  $t / $s"$'\n'
done

cat > server.yml <<YML
# Gerado por configurar.sh em $(date '+%d/%m/%Y %H:%M'). Não vai para o GitHub.
listen-http: ":80"
behind-proxy: true
cache-file: "/var/lib/ntfy/cache.db"
cache-duration: "24h"

auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"
enable-signup: false
web-root: "disable"

auth-users:
$USUARIOS

auth-access:
$ACESSOS

auth-tokens:
  - "api:$TK_API:API de chamados"
  - "monitor:$TK_MONITOR:Monitor de APs"
YML

echo "DOMINIO=$DOMINIO" > .env

cat > credenciais.txt <<TXT
Servidor ntfy do TI — guarde em local seguro e apague daqui depois de copiar.
Gerado em $(date '+%d/%m/%Y %H:%M').

Endereço do servidor:  https://$DOMINIO

API de chamados (variáveis no Render):
  NTFY_URL=https://$DOMINIO
  NTFY_TOPIC=chamados
  NTFY_TOKEN=$TK_API

Monitor de APs (arquivo ntfy.json na pasta do painel):
  {"servidor": "https://$DOMINIO", "topico": "aps", "token": "$TK_MONITOR"}

App ntfy no celular: usuário gabriel + a senha que você criou.
$( [[ -n "$SENHAS_TECNICOS" ]] && printf 'Outros técnicos (usuário / senha):\n%s' "$SENHAS_TECNICOS" )
TXT

echo
echo "Pronto! Arquivos gerados: server.yml, .env e credenciais.txt"
echo "Agora ligue o servidor:   docker compose up -d"
echo "As senhas e tokens estão em credenciais.txt (só você consegue ler este arquivo)."
