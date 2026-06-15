#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# HA VPN Auto Installer — Proxmox host script
# Run this ON THE PROXMOX HOST. It creates a Debian LXC container, installs the
# app inside, and prints the URL. No manual container setup needed.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/hagsy2/vpnpilot/main/proxmox-install.sh)"
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/hagsy2/vpnpilot}"
REPO_RAW="${REPO_URL/github.com/raw.githubusercontent.com}/${REPO_BRANCH:-main}"

# Container defaults (override via env: HOSTNAME, DISK, CORES, RAM, BRIDGE, STORAGE)
CT_HOSTNAME="${HOSTNAME:-vpnpilot}"
CT_DISK="${DISK:-4}"          # GB
CT_CORES="${CORES:-1}"
CT_RAM="${RAM:-1024}"         # MB
CT_BRIDGE="${BRIDGE:-vmbr0}"
APP_PORT="${PORT:-8080}"
TEMPLATE="${TEMPLATE:-debian-12-standard}"

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
  PROXMOX AUTO INSTALLER — создаёт LXC и ставит VPN-панель

BANNER

command -v pct &>/dev/null || die "Это не Proxmox-хост (нет команды pct). Запускай на хосте PVE."
[[ $EUID -ne 0 ]] && die "Запусти от root"

# ── Pick container ID ─────────────────────────────────────────────────────────
CTID="${CTID:-$(pvesh get /cluster/nextid 2>/dev/null || echo 200)}"
info "ID контейнера: $CTID"

# ── Storage detection ─────────────────────────────────────────────────────────
# rootfs storage: prefer local-lvm, else first storage that supports rootdir
ROOTFS_STORAGE="${STORAGE:-}"
if [[ -z "$ROOTFS_STORAGE" ]]; then
  if pvesm status -content rootdir 2>/dev/null | awk 'NR>1{print $1}' | grep -qx local-lvm; then
    ROOTFS_STORAGE="local-lvm"
  else
    ROOTFS_STORAGE=$(pvesm status -content rootdir 2>/dev/null | awk 'NR==2{print $1}')
  fi
fi
[[ -z "$ROOTFS_STORAGE" ]] && die "Не нашёл хранилище для контейнеров (rootdir). Укажи через STORAGE=..."
# template storage: where templates live (content=vztmpl), usually 'local'
TMPL_STORAGE=$(pvesm status -content vztmpl 2>/dev/null | awk 'NR==2{print $1}')
TMPL_STORAGE="${TMPL_STORAGE:-local}"
info "Хранилище контейнера: $ROOTFS_STORAGE | шаблоны: $TMPL_STORAGE"

# ── Template download ─────────────────────────────────────────────────────────
info "Обновляю список шаблонов..."
pveam update >/dev/null 2>&1 || true
TMPL_FILE=$(pveam available --section system 2>/dev/null | awk -v t="$TEMPLATE" '$2 ~ t {print $2}' | sort -V | tail -1)
[[ -z "$TMPL_FILE" ]] && die "Шаблон '$TEMPLATE' не найден в pveam available"

if ! pveam list "$TMPL_STORAGE" 2>/dev/null | grep -q "$TMPL_FILE"; then
  info "Скачиваю шаблон $TMPL_FILE (один раз)..."
  pveam download "$TMPL_STORAGE" "$TMPL_FILE" || die "Не удалось скачать шаблон"
fi
ok "Шаблон готов: $TMPL_FILE"

# ── Create container ──────────────────────────────────────────────────────────
info "Создаю контейнер $CTID ($CT_HOSTNAME)..."
pct create "$CTID" "${TMPL_STORAGE}:vztmpl/${TMPL_FILE}" \
  --hostname "$CT_HOSTNAME" \
  --cores "$CT_CORES" \
  --memory "$CT_RAM" \
  --swap 256 \
  --rootfs "${ROOTFS_STORAGE}:${CT_DISK}" \
  --net0 "name=eth0,bridge=${CT_BRIDGE},ip=dhcp" \
  --features nesting=1 \
  --unprivileged 1 \
  --onboot 1 \
  --description "VPNPilot — авто-установщик VPN" \
  >/dev/null || die "pct create не удался"
ok "Контейнер создан"

info "Запускаю контейнер..."
pct start "$CTID"
# wait for network / DHCP lease
for i in $(seq 1 30); do
  IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}') || true
  [[ -n "${IP:-}" ]] && break
  sleep 2
done
[[ -z "${IP:-}" ]] && warn "Контейнер без IP — проверь сеть/DHCP" || ok "IP контейнера: $IP"

# ── Install app inside ────────────────────────────────────────────────────────
info "Устанавливаю приложение внутри контейнера..."
pct exec "$CTID" -- bash -c "apt-get update -y -q && apt-get install -y -q curl" >/dev/null 2>&1 || true
pct exec "$CTID" -- bash -c "REPO_URL='${REPO_URL}' PORT='${APP_PORT}' bash -c \"\$(curl -fsSL ${REPO_RAW}/install.sh)\"" \
  || die "Установка внутри контейнера не удалась"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Готово! LXC $CTID создан и приложение запущено${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Веб-панель:  ${CYAN}http://${IP:-<IP-контейнера>}:${APP_PORT}${NC}"
echo ""
echo -e "  Контейнер:   pct enter $CTID   (зайти внутрь)"
echo -e "  Перезапуск:  pct exec $CTID -- systemctl restart ha-vpn-auto"
echo ""
