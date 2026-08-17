#!/usr/bin/env bash
set -Eeuo pipefail

trap 'echo "[ERROR] Environment preparation failed at line $LINENO." >&2' ERR

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root: sudo bash $0" >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  echo "Cannot identify the operating system." >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "This script supports Ubuntu 24.04 only (found ${PRETTY_NAME:-unknown})." >&2
  exit 1
fi

DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-yuncomfyui}}"
APP_DIR="${APP_DIR:-/opt/yuncomfyui}"
BACKUP_DIR="${BACKUP_DIR:-/opt/yuncomfyui-backups}"
TIMEZONE="${TIMEZONE:-Asia/Shanghai}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-2}"
ENABLE_UFW="${ENABLE_UFW:-1}"

if [[ ! "${DEPLOY_USER}" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
  echo "Invalid DEPLOY_USER: ${DEPLOY_USER}" >&2
  exit 1
fi
if [[ ! "${SWAP_SIZE_GB}" =~ ^[0-9]+$ ]]; then
  echo "SWAP_SIZE_GB must be a non-negative integer." >&2
  exit 1
fi
if [[ "${APP_DIR}" != /* || "${BACKUP_DIR}" != /* ]]; then
  echo "APP_DIR and BACKUP_DIR must be absolute paths." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

echo "[1/8] Updating Ubuntu packages..."
apt-get update
apt-get upgrade -y
apt-get install -y \
  ca-certificates \
  curl \
  git \
  gnupg \
  jq \
  openssh-server \
  openssl \
  unattended-upgrades \
  ufw

echo "[2/8] Configuring timezone and automatic security updates..."
timedatectl set-timezone "${TIMEZONE}"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades.service

echo "[3/8] Installing Docker Engine and Compose plugin..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable
EOF
apt-get update
apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin
systemctl enable --now docker.service containerd.service

echo "[4/8] Creating the deployment user and directories..."
if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"
install -d -m 0750 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${APP_DIR}"
install -d -m 0700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${BACKUP_DIR}"

echo "[5/8] Configuring swap when the server has none..."
if [[ "${SWAP_SIZE_GB}" -gt 0 ]] && ! swapon --show --noheadings | grep -q .; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l "${SWAP_SIZE_GB}G" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
  if ! grep -qE '^/swapfile[[:space:]]' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' >>/etc/fstab
  fi
fi

echo "[6/8] Configuring the firewall..."
if [[ "${ENABLE_UFW}" == "1" ]]; then
  ufw default deny incoming
  ufw default allow outgoing
  ssh_port_candidates=()
  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    read -r -a ssh_connection_parts <<<"${SSH_CONNECTION}"
    if [[ "${#ssh_connection_parts[@]}" -ge 4 ]]; then
      ssh_port_candidates+=("${ssh_connection_parts[3]}")
    fi
  fi
  if command -v sshd >/dev/null 2>&1; then
    while IFS= read -r configured_port; do
      ssh_port_candidates+=("${configured_port}")
    done < <(sshd -T 2>/dev/null | awk '$1 == "port" {print $2}')
  fi
  mapfile -t ssh_ports < <(
    printf '%s\n' "${ssh_port_candidates[@]}" | grep -E '^[0-9]+$' | sort -nu
  )
  if [[ "${#ssh_ports[@]}" -eq 0 ]]; then
    ssh_ports=(22)
  fi
  for ssh_port in "${ssh_ports[@]}"; do
    ufw allow "${ssh_port}/tcp" comment 'SSH'
  done
  ufw allow 80/tcp comment 'HTTP ACME'
  ufw allow 443/tcp comment 'HTTPS license API'
  ufw --force enable
else
  echo "UFW configuration skipped because ENABLE_UFW=${ENABLE_UFW}."
fi

echo "[7/8] Verifying Docker..."
docker version >/dev/null
docker compose version >/dev/null

echo "[8/8] Environment is ready."
echo
echo "Docker:       $(docker --version)"
echo "Compose:      $(docker compose version --short)"
echo "Deploy user:  ${DEPLOY_USER}"
echo "Project dir:  ${APP_DIR}"
echo "Backup dir:   ${BACKUP_DIR}"
echo "Timezone:     $(timedatectl show --property=Timezone --value)"
echo
echo "Next steps:"
echo "  1. Upload or clone the repository into ${APP_DIR}."
echo "  2. cd ${APP_DIR}/license_server"
echo "  3. chmod +x scripts/*.sh"
echo "  4. ./scripts/deploy.sh"
echo "  5. Edit .env, set DOMAIN and TLS_EMAIL, then run scripts/enable_https.sh."
echo
echo "Log out and back in before ${DEPLOY_USER} uses Docker without sudo."
