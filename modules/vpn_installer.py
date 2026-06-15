"""VPN installation recipes per protocol."""

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class InstallStep:
    description: str
    command: str
    timeout: int = 300
    ignore_error: bool = False


@dataclass
class VPNProtocol:
    id: str
    name: str
    description: str
    icon: str
    steps_fn: Callable  # (os_info: dict, server_ip: str) -> list[InstallStep]
    post_install_fn: Optional[Callable] = None  # (ssh, os_info) -> dict with config
    uninstall_cmd: str = ""  # shell command to fully remove the VPN from the server
    # ── newbie-friendly metadata ──
    blocking_level: int = 3      # 1..5 — устойчивость к блокировкам (5 = почти не блокируется)
    blocking_text: str = ""      # короткое объяснение про блокировки
    ease: str = "Средне"         # Легко / Средне / Для опытных — простота настройки клиента
    devices: str = ""            # на чём работает
    recommended: bool = False    # бейдж "рекомендуем"


def base_steps(os_info: dict) -> list:
    """Universal first steps: update + install essential tools.

    Minimal cloud images (esp. Debian) often ship without curl/wget/ca-certificates,
    so we install them explicitly before any download-based step.
    """
    p = os_info["profile"]
    return [
        InstallStep(
            "Обновление пакетов",
            f"export DEBIAN_FRONTEND=noninteractive && {p['update_cmd']}",
            timeout=180,
            ignore_error=True,
        ),
        InstallStep(
            "Установка базовых утилит (curl, wget, ca-certificates)",
            f"export DEBIAN_FRONTEND=noninteractive && {p['install_cmd']} curl wget ca-certificates tar",
            timeout=180,
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# WireGuard
# ──────────────────────────────────────────────────────────────────────────────

# Server-side management helper installed to /etc/wireguard/wg-mgmt.sh.
# Provides headless add/remove/list/show of clients with full control over
# IP allocation and live `wg` sync — no interactive upstream script needed.
WG_MGMT_SCRIPT = r'''#!/bin/bash
# WireGuard client manager
set -e
WG_DIR=/etc/wireguard
WG_NIC=wg0
CLIENTS=$WG_DIR/clients
PARAMS=$WG_DIR/params
source "$PARAMS"

next_ip() {
    for i in $(seq 2 254); do
        if ! grep -q "AllowedIPs = 10.66.66.$i/32" "$WG_DIR/$WG_NIC.conf"; then
            echo "$i"; return
        fi
    done
    echo "ERROR: no free IP" >&2; exit 1
}

case "$1" in
  add)
    NAME="$2"
    [ -z "$NAME" ] && { echo "name required" >&2; exit 1; }
    [ -f "$CLIENTS/$NAME.conf" ] && { echo "client exists" >&2; exit 1; }
    umask 077
    IP=$(next_ip)
    CPRIV=$(wg genkey)
    CPUB=$(echo "$CPRIV" | wg pubkey)
    PSK=$(wg genpsk)
    # append peer to server conf
    cat >> "$WG_DIR/$WG_NIC.conf" <<EOF

# $NAME
[Peer]
PublicKey = $CPUB
PresharedKey = $PSK
AllowedIPs = 10.66.66.$IP/32
EOF
    # live add to running interface
    wg set $WG_NIC peer "$CPUB" preshared-key <(echo "$PSK") allowed-ips 10.66.66.$IP/32
    # write client config
    cat > "$CLIENTS/$NAME.conf" <<EOF
[Interface]
PrivateKey = $CPRIV
Address = 10.66.66.$IP/24
DNS = 1.1.1.1, 1.0.0.1

[Peer]
PublicKey = $SERVER_PUB_KEY
PresharedKey = $PSK
Endpoint = $SERVER_PUB_IP:$SERVER_PORT
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF
    cat "$CLIENTS/$NAME.conf"
    ;;
  remove)
    NAME="$2"
    [ -f "$CLIENTS/$NAME.conf" ] || { echo "no such client" >&2; exit 1; }
    CPUB=$(grep -A4 "^# $NAME$" "$WG_DIR/$WG_NIC.conf" | grep PublicKey | awk '{print $3}' | head -1)
    [ -n "$CPUB" ] && wg set $WG_NIC peer "$CPUB" remove || true
    # strip the peer block from conf
    python3 - "$WG_DIR/$WG_NIC.conf" "$NAME" <<'PYEOF'
import sys, re
path, name = sys.argv[1], sys.argv[2]
txt = open(path).read()
txt = re.sub(r'\n# %s\n\[Peer\].*?(?=\n# |\n*\Z)' % re.escape(name), '\n', txt, flags=re.S)
open(path,'w').write(txt)
PYEOF
    rm -f "$CLIENTS/$NAME.conf"
    echo "removed $NAME"
    ;;
  list)
    ls -1 "$CLIENTS"/*.conf 2>/dev/null | xargs -r -n1 basename | sed 's/\.conf$//'
    ;;
  show)
    cat "$CLIENTS/$2.conf"
    ;;
esac
'''


def _wg_setup_script(server_ip: str) -> str:
    return r'''set -e
export DEBIAN_FRONTEND=noninteractive
PUBIP="''' + server_ip + r'''"
NIC=$(ip -4 route ls | grep default | grep -oP 'dev \K\S+' | head -1)
PORT=51820
mkdir -p /etc/wireguard/clients
cd /etc/wireguard
umask 077

wg genkey | tee server_private.key | wg pubkey > server_public.key
SERVER_PRIV=$(cat server_private.key)
SERVER_PUB=$(cat server_public.key)

# params file consumed by the management helper
cat > /etc/wireguard/params <<EOF
SERVER_PUB_IP=$PUBIP
SERVER_PUB_NIC=$NIC
SERVER_PORT=$PORT
SERVER_PUB_KEY=$SERVER_PUB
EOF

cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = 10.66.66.1/24
ListenPort = $PORT
PrivateKey = $SERVER_PRIV
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o $NIC -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -D FORWARD -o wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o $NIC -j MASQUERADE
EOF

echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-wireguard.conf
sysctl -w net.ipv4.ip_forward=1 >/dev/null

systemctl enable wg-quick@wg0 >/dev/null 2>&1
systemctl restart wg-quick@wg0
sleep 1
echo "Service: $(systemctl is-active wg-quick@wg0)"

# install management helper and create first client
cat > /etc/wireguard/wg-mgmt.sh <<'MGMT_EOF'
''' + WG_MGMT_SCRIPT + r'''
MGMT_EOF
chmod +x /etc/wireguard/wg-mgmt.sh
/etc/wireguard/wg-mgmt.sh add client1 >/dev/null
echo "First client created: client1"
'''


def wireguard_steps(os_info: dict, server_ip: str) -> list[InstallStep]:
    return base_steps(os_info) + [
        InstallStep(
            "Установка WireGuard-tools",
            "export DEBIAN_FRONTEND=noninteractive && "
            f"{os_info['profile']['install_cmd']} wireguard-tools iptables qrencode",
            timeout=240,
        ),
        InstallStep(
            "Настройка WireGuard сервера и первого клиента",
            _wg_setup_script(server_ip),
            timeout=120,
        ),
    ]


def wireguard_config(ssh, os_info: dict) -> dict:
    config = ssh.get_file_content("/etc/wireguard/clients/client1.conf")
    return {"type": "wireguard", "client_config": config, "filename": "client1.conf"}


# ──────────────────────────────────────────────────────────────────────────────
# OpenVPN
# ──────────────────────────────────────────────────────────────────────────────

def openvpn_steps(os_info: dict, server_ip: str) -> list[InstallStep]:
    return base_steps(os_info) + [
        InstallStep(
            "Скачивание скрипта openvpn-install",
            "curl -fsSL https://raw.githubusercontent.com/angristan/openvpn-install/master/openvpn-install.sh -o /tmp/ovpn-install.sh && chmod +x /tmp/ovpn-install.sh",
            timeout=60,
        ),
        InstallStep(
            "Установка OpenVPN",
            (
                "export AUTO_INSTALL=y "
                f"APPROVE_IP={server_ip} "
                "ENDPOINT={server_ip} "
                "APPROVE_INSTALL=y "
                "PORT_CHOICE=1 "
                "PROTOCOL_CHOICE=1 "
                "DNS=1 "
                "COMPRESSION_ENABLED=n "
                "CUSTOMIZE_ENC=n "
                "CLIENT=client1 "
                "PASS=1 && "
                "bash /tmp/ovpn-install.sh"
            ),
            timeout=400,
        ),
    ]


def openvpn_config(ssh, os_info: dict) -> dict:
    # Try common locations
    for path in ["/root/client1.ovpn", "/home/client1.ovpn"]:
        if ssh.file_exists(path):
            config = ssh.get_file_content(path)
            return {"type": "openvpn", "client_config": config, "filename": "client1.ovpn"}
    return {"type": "openvpn", "note": "Файл .ovpn находится в /root/"}


# ──────────────────────────────────────────────────────────────────────────────
# 3X-UI (XRay — VLESS/VMESS/Trojan/Reality)
# ──────────────────────────────────────────────────────────────────────────────

def xui_steps(os_info: dict, server_ip: str) -> list[InstallStep]:
    return base_steps(os_info) + [
        InstallStep(
            "Установка 3X-UI панели",
            "curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh -o /tmp/3xui.sh && "
            'printf "y\\n\\n\\n\\n" | bash /tmp/3xui.sh',
            timeout=600,
        ),
    ]


def xui_config(ssh, os_info: dict) -> dict:
    out, _, _ = ssh.run_command("x-ui settings 2>/dev/null || cat /etc/x-ui/x-ui.db 2>/dev/null | head -5 || echo 'check panel'")
    port_out, _, _ = ssh.run_command("cat /usr/local/x-ui/bin/config.json 2>/dev/null | python3 -c \"import sys,json;d=json.load(sys.stdin);print(d.get('port',2053))\" 2>/dev/null || echo 2053")
    panel_port = port_out.strip() or "2053"
    return {
        "type": "3x-ui",
        "panel_url": f"http://SERVER_IP:{panel_port}/",
        "default_user": "admin",
        "default_pass": "admin",
        "note": "Войди в панель и смени пароль! Затем добавь inbound (VLESS+Reality рекомендуется)",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Shadowsocks (libev)
# ──────────────────────────────────────────────────────────────────────────────

def shadowsocks_steps(os_info: dict, server_ip: str) -> list[InstallStep]:
    family = os_info["profile"]["family"]
    install_cmd = os_info["profile"]["install_cmd"]

    if family != "debian":
        return base_steps(os_info) + [
            InstallStep(
                "Установка pip и shadowsocks",
                f"{install_cmd} python3-pip && pip3 install shadowsocks",
                timeout=180,
            ),
        ]

    return base_steps(os_info) + [
        InstallStep(
            "Установка shadowsocks-libev",
            f"export DEBIAN_FRONTEND=noninteractive && {install_cmd} shadowsocks-libev",
            timeout=240,
        ),
        InstallStep(
            "Генерация конфига со случайным паролем",
            r"""SS_PASS=$(openssl rand -base64 16) && cat > /etc/shadowsocks-libev/config.json << EOF
{
    "server": "0.0.0.0",
    "server_port": 8388,
    "password": "$SS_PASS",
    "timeout": 300,
    "method": "chacha20-ietf-poly1305",
    "fast_open": false,
    "mode": "tcp_and_udp"
}
EOF
echo "Password set: $SS_PASS" """,
            timeout=30,
        ),
        InstallStep(
            "Запуск сервиса",
            "systemctl enable shadowsocks-libev && systemctl restart shadowsocks-libev && sleep 1 && systemctl is-active shadowsocks-libev",
            timeout=30,
        ),
    ]


def shadowsocks_config(ssh, os_info: dict) -> dict:
    config = ssh.get_file_content("/etc/shadowsocks-libev/config.json")
    return {
        "type": "shadowsocks",
        "server_config": config,
        "port": 8388,
        "method": "chacha20-ietf-poly1305",
        "note": "Используй клиент Shadowsocks или Outline",
    }


# ──────────────────────────────────────────────────────────────────────────────
# IKEv2 / IPSec (strongSwan через hwdsl2)
# ──────────────────────────────────────────────────────────────────────────────

def ikev2_steps(os_info: dict, server_ip: str) -> list[InstallStep]:
    return base_steps(os_info) + [
        InstallStep(
            "Скачивание скрипта IKEv2/IPSec",
            "curl -fsSL https://get.vpnsetup.net -o /tmp/ikev2-setup.sh && chmod +x /tmp/ikev2-setup.sh",
            timeout=60,
        ),
        InstallStep(
            "Установка strongSwan IKEv2",
            f"VPN_IPSEC_PSK=$(openssl rand -base64 32) VPN_USER=vpnuser VPN_PASSWORD=$(openssl rand -base64 16) bash /tmp/ikev2-setup.sh",
            timeout=400,
        ),
        InstallStep(
            "Создание IKEv2 клиента",
            f"ikev2.sh --addclient vpnclient1 2>/dev/null || echo 'client created'",
            timeout=60,
            ignore_error=True,
        ),
    ]


def ikev2_config(ssh, os_info: dict) -> dict:
    creds, _, _ = ssh.run_command("grep -A3 'VPN credentials' /var/log/syslog 2>/dev/null || cat /etc/ipsec.secrets 2>/dev/null | head -5")
    return {
        "type": "ikev2",
        "note": "Учётные данные VPN сохранены в /etc/ipsec.d/",
        "server": "SERVER_IP",
        "raw": creds[:500] if creds else "",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Outline (Shadowsocks managed)
# ──────────────────────────────────────────────────────────────────────────────

def outline_steps(os_info: dict, server_ip: str) -> list[InstallStep]:
    return [
        InstallStep(
            "Установка Docker",
            (
                "curl -fsSL https://get.docker.com | bash || "
                "apt-get install -y docker.io || "
                "yum install -y docker"
            ),
            timeout=300,
        ),
        InstallStep(
            "Запуск Docker",
            "systemctl enable docker && systemctl start docker",
            timeout=30,
        ),
        InstallStep(
            # Остатки от прошлых попыток ломают install_server.sh: контейнер
            # watchtower с тем же именем уже существует → шаг падает FAILED ещё
            # до записи apiUrl. Сносим старые контейнеры (сертификаты/ключи в
            # /opt/outline остаются, переустановка их переиспользует).
            "Очистка старых контейнеров Outline",
            "docker rm -f shadowbox watchtower 2>/dev/null; echo 'cleaned'",
            timeout=30,
            ignore_error=True,
        ),
        InstallStep(
            "Установка Outline сервера",
            # Watchtower (auto-updater) may fail in unprivileged LXC — that's fine,
            # Shadowbox (the actual server) works without it. We force exit 0.
            'bash -c "$(curl -fsSL https://raw.githubusercontent.com/Jigsaw-Code/outline-server/master/src/server_manager/install_scripts/install_server.sh)" ; '
            'docker ps | grep -q shadowbox && echo "Outline OK" || (echo "Shadowbox not running" && exit 1)',
            timeout=300,
        ),
    ]


def outline_config(ssh, os_info: dict) -> dict:
    """Собрать ключ для Outline Manager.

    Не полагаемся на access.txt: если install_server.sh падает на шаге Watchtower
    (напр. конфликт имён контейнера), он не успевает дописать строку apiUrl. Поэтому
    собираем ключ напрямую из контейнера shadowbox — порт и секретный префикс берём
    из его env, certSha256 вычисляем из сертификата. Это всегда даёт рабочий ключ,
    пока контейнер shadowbox жив.
    """
    import json as _json

    def sh(cmd):
        out, _, _ = ssh.run_command(cmd)
        return out.strip()

    # 1. Параметры API из env контейнера shadowbox.
    env = sh("docker inspect shadowbox --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null")
    api_port = api_prefix = ""
    for line in env.splitlines():
        if line.startswith("SB_API_PORT="):
            api_port = line.split("=", 1)[1].strip()
        elif line.startswith("SB_API_PREFIX="):
            api_prefix = line.split("=", 1)[1].strip()

    # 2. Внешний хост — Outline сам пишет его в свой конфиг.
    host = ""
    cfg = sh("cat /opt/outline/persisted-state/shadowbox_server_config.json 2>/dev/null")
    try:
        host = _json.loads(cfg).get("hostname", "")
    except Exception:
        host = ""

    # 3. certSha256 — вычисляем из текущего сертификата (надёжнее, чем access.txt).
    cert = sh(
        "openssl x509 -in /opt/outline/persisted-state/shadowbox-selfsigned.crt "
        "-noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//; s/://g'"
    )

    # 4. Фолбэк на access.txt для всего, что не удалось собрать напрямую.
    access_raw = sh("cat /opt/outline/access.txt 2>/dev/null || cat ~/access.txt 2>/dev/null")
    if not cert or not api_port or not api_prefix:
        for line in access_raw.replace("\r", "").splitlines():
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "certSha256" and v and not cert:
                cert = v
            elif k == "apiUrl" and v and not (api_port and api_prefix):
                # apiUrl = https://host:port/prefix — разбираем как запасной источник
                api_url_fb = v
                try:
                    rest = v.split("://", 1)[1]
                    hostport, _, pref = rest.partition("/")
                    h, _, p = hostport.partition(":")
                    host = host or h
                    api_port = api_port or p
                    api_prefix = api_prefix or pref
                except Exception:
                    pass

    api_url = f"https://{host}:{api_port}/{api_prefix}" if (host and api_port and api_prefix) else ""
    manager_key = _json.dumps({"apiUrl": api_url, "certSha256": cert}) if (api_url and cert) else ""

    return {
        "type": "outline",
        "manager_key": manager_key,
        "api_url": api_url,
        "access_info": access_raw,
        "note": "Вставь ключ-строку (с фигурными скобками) в Outline Manager → Step 2",
    }


# ──────────────────────────────────────────────────────────────────────────────
# VLESS+Reality (Xray standalone, без панели)
# ──────────────────────────────────────────────────────────────────────────────

def vless_reality_steps(os_info: dict, server_ip: str) -> list[InstallStep]:
    return base_steps(os_info) + [
        InstallStep(
            "Установка Xray через официальный скрипт",
            "bash -c \"$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)\" @ install",
            timeout=300,
        ),
        InstallStep(
            "Генерация ключей Reality",
            "xray x25519 > /tmp/reality_keys.txt && cat /tmp/reality_keys.txt",
            timeout=30,
        ),
        InstallStep(
            "Создание конфига VLESS+Reality",
            r"""
UUID=$(xray uuid)
KEYS=$(cat /tmp/reality_keys.txt)
# xray x25519 output value is always the LAST field on each line
# (formats vary: "Private key:" / "PrivateKey:" / "Password (PublicKey):")
PRIVATE_KEY=$(echo "$KEYS" | grep -i 'private' | awk '{print $NF}')
PUBLIC_KEY=$(echo "$KEYS" | grep -iE 'public' | awk '{print $NF}')
SHORT_ID=$(openssl rand -hex 8)

cat > /usr/local/etc/xray/config.json << EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [{
    "listen": "0.0.0.0",
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{"id": "$UUID", "flow": "xtls-rprx-vision"}],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "show": false,
        "dest": "www.microsoft.com:443",
        "xver": 0,
        "serverNames": ["www.microsoft.com"],
        "privateKey": "$PRIVATE_KEY",
        "shortIds": ["$SHORT_ID"]
      }
    },
    "sniffing": {"enabled": true, "destOverride": ["http","tls"]}
  }],
  "outbounds": [
    {"protocol": "freedom", "tag": "direct"},
    {"protocol": "blackhole", "tag": "block"}
  ]
}
EOF

# Save connection params for the management panel (avoids recomputing pubkey)
cat > /usr/local/etc/xray/reality_client.txt << EOF
UUID=$UUID
PUBLIC_KEY=$PUBLIC_KEY
SHORT_ID=$SHORT_ID
SNI=www.microsoft.com
PORT=443
EOF

echo "=== VLESS LINK ==="
echo "vless://$UUID@SERVER_IP:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.microsoft.com&fp=chrome&pbk=$PUBLIC_KEY&sid=$SHORT_ID&type=tcp#MyVLESS"
echo "PUBLIC_KEY=$PUBLIC_KEY"
echo "UUID=$UUID"
echo "SHORT_ID=$SHORT_ID"
""",
            timeout=60,
        ),
        InstallStep(
            "Запуск Xray",
            "systemctl enable xray && systemctl restart xray && systemctl status xray --no-pager",
            timeout=30,
        ),
    ]


def vless_reality_config(ssh, os_info: dict) -> dict:
    config = ssh.get_file_content("/usr/local/etc/xray/config.json")
    return {
        "type": "vless-reality",
        "server_config": config,
        "note": "Используй клиент v2rayN / Streisand / Sing-Box. Ссылка vless:// была в логах установки.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

PROTOCOLS: dict[str, VPNProtocol] = {
    "wireguard": VPNProtocol(
        id="wireguard",
        name="WireGuard",
        description="Самый быстрый VPN. Лёгкая настройка, мало жрёт батарею.",
        icon="🔒",
        steps_fn=wireguard_steps,
        post_install_fn=wireguard_config,
        uninstall_cmd=(
            "systemctl stop wg-quick@wg0 2>/dev/null; "
            "systemctl disable wg-quick@wg0 2>/dev/null; "
            "rm -rf /etc/wireguard /etc/sysctl.d/99-wireguard.conf; "
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get remove --purge -y wireguard-tools 2>/dev/null; "
            "echo 'WireGuard удалён'"
        ),
        blocking_level=2,
        blocking_text="Отлично работает там, где нет жёсткой цензуры. В странах с DPI (Россия, Иран, Китай) может замедляться или блокироваться — там бери VLESS.",
        ease="Очень легко",
        devices="Windows, Mac, Linux, iOS, Android",
    ),
    "openvpn": VPNProtocol(
        id="openvpn",
        name="OpenVPN",
        description="Проверенный временем VPN. Работает почти везде и со всеми приложениями.",
        icon="🛡️",
        steps_fn=openvpn_steps,
        post_install_fn=openvpn_config,
        uninstall_cmd=(
            "systemctl stop openvpn@server openvpn-server@server 2>/dev/null; "
            "systemctl disable openvpn@server openvpn-server@server 2>/dev/null; "
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get remove --purge -y openvpn 2>/dev/null; "
            "rm -rf /etc/openvpn /root/*.ovpn /home/*.ovpn; "
            "echo 'OpenVPN удалён'"
        ),
        blocking_level=2,
        blocking_text="Надёжен для обычного использования, но его «почерк» легко распознаётся системами цензуры. В странах с DPI часто блокируется.",
        ease="Легко",
        devices="Windows, Mac, Linux, iOS, Android",
    ),
    "3x-ui": VPNProtocol(
        id="3x-ui",
        name="3X-UI Панель",
        description="VPN с веб-панелью: добавляй пользователей мышкой, смотри трафик. Внутри — те же протоколы что и VLESS.",
        icon="⚡",
        steps_fn=xui_steps,
        post_install_fn=xui_config,
        uninstall_cmd=(
            "systemctl stop x-ui 2>/dev/null; "
            "systemctl disable x-ui 2>/dev/null; "
            "rm -f /etc/systemd/system/x-ui.service; "
            "rm -rf /usr/local/x-ui /etc/x-ui /usr/bin/x-ui; "
            "systemctl daemon-reload 2>/dev/null; "
            "echo '3X-UI удалён'"
        ),
        blocking_level=5,
        blocking_text="Поддерживает Reality — лучшую на сегодня маскировку. При правильной настройке обходит даже самую жёсткую цензуру.",
        ease="Для опытных",
        devices="Все (через клиенты v2rayN, Hiddify, Streisand)",
    ),
    "vless-reality": VPNProtocol(
        id="vless-reality",
        name="VLESS + Reality",
        description="Лучший выбор для обхода блокировок. Для цензора выглядит как обычный заход на сайт.",
        icon="🌐",
        steps_fn=vless_reality_steps,
        post_install_fn=vless_reality_config,
        uninstall_cmd=(
            "systemctl stop xray 2>/dev/null; "
            "bash -c \"$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)\" @ remove --purge 2>/dev/null; "
            "rm -rf /usr/local/etc/xray /usr/local/bin/xray /etc/systemd/system/xray.service /etc/systemd/system/xray@.service; "
            "systemctl daemon-reload 2>/dev/null; "
            "echo 'Xray/VLESS удалён'"
        ),
        blocking_level=5,
        blocking_text="Технология Reality маскирует трафик под обычный HTTPS к реальному сайту (напр. microsoft.com). Сейчас практически не блокируется даже в России и Иране.",
        ease="Средне",
        devices="Все (v2rayN, Hiddify, Streisand, Sing-Box)",
        recommended=True,
    ),
    "shadowsocks": VPNProtocol(
        id="shadowsocks",
        name="Shadowsocks",
        description="Лёгкий прокси, придуман для обхода цензуры. Простой и шустрый.",
        icon="🔑",
        steps_fn=shadowsocks_steps,
        post_install_fn=shadowsocks_config,
        uninstall_cmd=(
            "systemctl stop shadowsocks-libev 2>/dev/null; "
            "systemctl disable shadowsocks-libev 2>/dev/null; "
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get remove --purge -y shadowsocks-libev 2>/dev/null; "
            "rm -rf /etc/shadowsocks-libev; "
            "echo 'Shadowsocks удалён'"
        ),
        blocking_level=3,
        blocking_text="Долго был главным средством обхода цензуры. Сейчас в самых строгих странах (Китай) определяется, но в большинстве мест работает хорошо.",
        ease="Легко",
        devices="Все (Outline, Shadowrocket, v2rayN)",
    ),
    "outline": VPNProtocol(
        id="outline",
        name="Outline",
        description="Самый простой для новичка: ставишь приложение Outline Manager и раздаёшь ключи в один клик. От создателей из Google Jigsaw.",
        icon="📦",
        steps_fn=outline_steps,
        post_install_fn=outline_config,
        uninstall_cmd=(
            "docker rm -f $(docker ps -aq --filter name=shadowbox) "
            "$(docker ps -aq --filter name=watchtower) 2>/dev/null; "
            "rm -rf /opt/outline /root/access.txt; "
            "echo 'Outline удалён (Docker оставлен)'"
        ),
        blocking_level=3,
        blocking_text="Под капотом Shadowsocks. Хорошо работает в большинстве стран, очень прост в управлении. В Китае может определяться.",
        ease="Очень легко",
        devices="Windows, Mac, Linux, iOS, Android (приложение Outline)",
        recommended=True,
    ),
    "ikev2": VPNProtocol(
        id="ikev2",
        name="IKEv2 / IPSec",
        description="Уже встроен в твой телефон и ноутбук — не нужно ставить приложения. Стабильно держит связь при переключении WiFi/мобильной сети.",
        icon="📱",
        steps_fn=ikev2_steps,
        post_install_fn=ikev2_config,
        uninstall_cmd=(
            "systemctl stop ipsec strongswan strongswan-starter 2>/dev/null; "
            "systemctl disable ipsec strongswan strongswan-starter 2>/dev/null; "
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get remove --purge -y strongswan libstrongswan 2>/dev/null; "
            "rm -rf /etc/ipsec.d /etc/ipsec.secrets /etc/ipsec.conf /etc/swanctl; "
            "echo 'IKEv2/strongSwan удалён'"
        ),
        blocking_level=1,
        blocking_text="Удобный и встроенный, но легко блокируется — использует стандартные порты, которые цензоры закрывают первыми. Для обхода блокировок не подходит.",
        ease="Очень легко",
        devices="iOS, Mac, Windows, Android (без приложений)",
    ),
}
