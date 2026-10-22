#!/usr/bin/env bash
# Prepara uma VM Ubuntu da Oracle Cloud para o servidor ntfy: Docker + firewall (portas 80 e 443).
# Rode uma vez, logo depois de criar a VM:   bash instalar-oracle.sh
set -euo pipefail

echo "==> Instalando Docker e Git"
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

echo "==> Liberando as portas 80 e 443 no firewall do Ubuntu (a imagem da Oracle bloqueia tudo por padrão)"
for porta in 80 443; do
  sudo iptables -C INPUT -p tcp -m state --state NEW --dport "$porta" -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT -p tcp -m state --state NEW --dport "$porta" -j ACCEPT
done
if command -v netfilter-persistent >/dev/null; then
  sudo netfilter-persistent save
else
  sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save
fi

echo
echo "Pronto. Saia (exit) e entre de novo pelo SSH para o Docker funcionar sem sudo."
echo "Depois: git clone do projeto, entre em ntfy-servidor e rode ./configurar.sh"
