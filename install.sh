#!/usr/bin/env bash
# ==============================================================================
# VPN Config Vault - 1-Click Installer for Ubuntu 24.04 LTS
# Protocols: VLESS, VMess, Shadowsocks, Hysteria 2, Trojan
# ==============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}      VPN Config Vault - Установка на Ubuntu 24.04    ${NC}"
echo -e "${CYAN}======================================================${NC}"

# 1. Check Root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[!] Пожалуйста, запустите скрипт с правами root (sudo bash install.sh)${NC}"
  exit 1
fi

# 2. System updates
echo -e "\n${YELLOW}[1/4] Обновление пакетов системы...${NC}"
apt-get update -y
apt-get install -y --no-install-recommends curl wget git ca-certificates gnupg lsb-release

# 3. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo -e "\n${YELLOW}[2/4] Установка Docker & Docker Compose...${NC}"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
else
    echo -e "\n${GREEN}[✓] Docker уже установлен.${NC}"
fi

# 4. Project Directory setup
INSTALL_DIR="/opt/vpn-aggregator"
echo -e "\n${YELLOW}[3/4] Подготовка файлов в ${INSTALL_DIR}...${NC}"

# If running directly inside the repo folder, copy files, otherwise check
CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$CURRENT_DIR" != "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    cp -r "$CURRENT_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || true
fi

cd "$INSTALL_DIR"
mkdir -p data

# 5. Build and launch container
echo -e "\n${YELLOW}[4/4] Сборка и запуск контейнера...${NC}"
docker compose down 2>/dev/null || true
docker compose up -d --build

SERVER_IP=$(curl -s -4 ifconfig.me || curl -s -4 icanhazip.com || echo "IP_ВАШЕГО_СЕРВЕРА")

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}      Установка успешно завершена!                    ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "Веб-панель управления:  ${CYAN}http://${SERVER_IP}:8080${NC}"
echo -e "Первый вход:            ${YELLOW}При открытии сайта задайте логин и пароль в мастере настройки${NC}"
echo -e "------------------------------------------------------"
echo -e "Ссылка на рабочие Raw:  ${CYAN}http://${SERVER_IP}:8080/sub/raw${NC}"
echo -e "Ссылка на Base64 Sub:   ${CYAN}http://${SERVER_IP}:8080/sub/base64${NC}"
echo -e "======================================================\n"
