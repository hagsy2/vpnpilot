#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# HA VPN Auto Installer — in-container installer (Debian/Ubuntu LXC or VM)
# Installs the web app, creates a systemd service, opens the firewall port.
#
# Usage (inside a Debian/Ubuntu container):
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/hagsy2/vpnpilot/main/install.sh)"
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Repo can be overridden:  REPO_URL=https://github.com/user/repo  bash install.sh
REPO_URL="${REPO_URL:-https://github.com/hagsy2/vpnpilot}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/ha-vpn-auto}"
SERVICE_NAME="ha-vpn-auto"
PORT="${PORT:-8080}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()   { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

cat <<'BANNER'

  ██╗  ██╗ █████╗     ██╗   ██╗██████╗ ███╗   ██╗
  ██║  ██║██╔══██╗    ██║   ██║██╔══██╗████╗  ██║
  ███████║███████║    ██║   ██║██████╔╝██╔██╗ ██║
  ██╔══██║██╔══██║    ╚██╗ ██╔╝██╔═══╝ ██║╚██╗██║
  ██║  ██║██║  ██║     ╚████╔╝ ██║     ██║ ╚████║
  ╚═╝  ╚═╝╚═╝  ╚═╝      ╚═══╝  ╚═╝     ╚═╝  ╚═══╝
  AUTO INSTALLER — VPN на твой сервер в один клик

BANNER

[[ $EUID -ne 0 ]] && die "Запусти от root: sudo bash install.sh"

# ── Dependencies ──────────────────────────────────────────────────────────────
info "Установка зависимостей..."
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get &>/dev/null; then
  apt-get update -y -q
  apt-get install -y -q python3 python3-pip python3-venv git curl
else
  die "Поддерживается только Debian/Ubuntu (apt). Для другой ОС поставь python3, git, curl вручную."
fi
ok "Зависимости установлены"

# ── Get the code ──────────────────────────────────────────────────────────────
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/main.py" ]]; then
  info "Копирую файлы из локальной папки..."
  mkdir -p "$INSTALL_DIR"
  cp -r "$(dirname "${BASH_SOURCE[0]}")/." "$INSTALL_DIR/"
else
  info "Клонирую репозиторий $REPO_URL ($REPO_BRANCH)..."
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 -b "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR" \
    || die "Не удалось клонировать $REPO_URL — проверь URL/ветку"
fi
ok "Код в $INSTALL_DIR"

# ── Python venv ───────────────────────────────────────────────────────────────
info "Создаю виртуальное окружение Python..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
ok "Python-окружение готово"

# ── systemd service ───────────────────────────────────────────────────────────
info "Создаю systemd-сервис..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=HA VPN Auto Installer Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
systemctl restart "$SERVICE_NAME"
ok "Сервис $SERVICE_NAME запущен"

# ── Update helper (CLI fallback to the in-UI button) ──────────────────────────
info "Устанавливаю команду обновления vpnpilot-update..."
cat > /usr/local/bin/vpnpilot-update <<EOF
#!/usr/bin/env bash
set -e
cd "${INSTALL_DIR}"
echo "🔄 git pull..."
git pull --rebase
echo "📦 pip install..."
"${INSTALL_DIR}/venv/bin/pip" install -q -r requirements.txt
echo "🔁 restart..."
systemctl restart ${SERVICE_NAME}
echo "✅ Обновлено."
EOF
chmod +x /usr/local/bin/vpnpilot-update
ok "Команда vpnpilot-update готова"

# ── Firewall (optional) ───────────────────────────────────────────────────────
if command -v ufw &>/dev/null; then
  ufw allow "$PORT"/tcp >/dev/null 2>&1 || true
  info "UFW: открыт порт $PORT"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ HA VPN Auto Installer установлен!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Открой в браузере:  ${CYAN}http://${IP}:${PORT}${NC}"
echo ""
echo -e "  Управление:"
echo -e "    systemctl status  $SERVICE_NAME"
echo -e "    systemctl restart $SERVICE_NAME"
echo -e "    journalctl -u $SERVICE_NAME -f"
echo ""
