"""Per-protocol client management via SSH."""
from __future__ import annotations
import re
import qrcode
import io
import base64
from .ssh_manager import SSHManager


def _qr_b64(text: str) -> str:
    """Return base64-encoded PNG QR code for text."""
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── WireGuard ────────────────────────────────────────────────────────────────

WG_MGMT = "/etc/wireguard/wg-mgmt.sh"


def wg_list_clients(ssh: SSHManager) -> list:
    out, _, _ = ssh.run_command(f"{WG_MGMT} list 2>/dev/null || ls -1 /etc/wireguard/clients/*.conf 2>/dev/null | xargs -r -n1 basename | sed 's/.conf//'")
    clients = []
    for line in out.splitlines():
        name = line.strip()
        if name and not name.startswith("/"):
            clients.append({"name": name})
    return clients


def wg_add_client(ssh: SSHManager, client_name: str) -> dict:
    safe = "".join(ch for ch in client_name if ch.isalnum() or ch in "-_")
    if not safe:
        return {"error": "Недопустимое имя клиента"}
    out, err, code = ssh.run_command(f"{WG_MGMT} add {safe}")
    if code == 0 and "[Interface]" in out:
        return {"name": safe, "config": out, "qr": _qr_b64(out)}
    return {"name": safe, "config": "", "error": (err or out or "Не удалось добавить клиента").strip()[:200]}


def wg_get_client(ssh: SSHManager, client_name: str) -> dict:
    safe = "".join(ch for ch in client_name if ch.isalnum() or ch in "-_")
    conf, _, _ = ssh.run_command(f"{WG_MGMT} show {safe} 2>/dev/null || cat /etc/wireguard/clients/{safe}.conf 2>/dev/null")
    if conf.strip() and "[Interface]" in conf:
        return {"name": safe, "config": conf, "qr": _qr_b64(conf)}
    return {"name": safe, "config": "", "error": "Файл не найден"}


def wg_remove_client(ssh: SSHManager, client_name: str) -> bool:
    safe = "".join(ch for ch in client_name if ch.isalnum() or ch in "-_")
    _, _, code = ssh.run_command(f"{WG_MGMT} remove {safe}")
    return code == 0


# ── OpenVPN ──────────────────────────────────────────────────────────────────

def ovpn_list_clients(ssh: SSHManager) -> list[dict]:
    out, _, _ = ssh.run_command("ls /root/*.ovpn /home/*.ovpn 2>/dev/null || echo ''")
    clients = []
    for line in out.splitlines():
        line = line.strip()
        if line.endswith(".ovpn"):
            name = line.split("/")[-1].replace(".ovpn", "")
            clients.append({"name": name, "path": line})
    return clients


def ovpn_add_client(ssh: SSHManager, client_name: str) -> dict:
    out, _, _ = ssh.run_command(
        f"export AUTO_INSTALL=y CLIENT={client_name} PASS=1 && "
        f"bash /tmp/ovpn-install.sh 2>&1 || bash /root/openvpn-install.sh 2>&1"
    )
    conf, _, _ = ssh.run_command(f"cat /root/{client_name}.ovpn 2>/dev/null || echo ''")
    if conf.strip():
        return {"name": client_name, "config": conf}
    return {"name": client_name, "config": "", "error": "Файл .ovpn не найден"}


def ovpn_get_client(ssh: SSHManager, client_name: str) -> dict:
    conf, _, _ = ssh.run_command(f"cat /root/{client_name}.ovpn 2>/dev/null || echo ''")
    return {"name": client_name, "config": conf}


def ovpn_remove_client(ssh: SSHManager, client_name: str) -> bool:
    ssh.run_command(
        f"export AUTO_INSTALL=y CLIENT={client_name} MENU_OPTION=2 && "
        f"bash /tmp/ovpn-install.sh 2>&1 || true"
    )
    return True


# ── VLESS+Reality ────────────────────────────────────────────────────────────

def _parse_kv(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def vless_get_link(ssh: SSHManager, server_ip: str) -> dict:
    # Preferred: read params saved at install time.
    saved, _, _ = ssh.run_command("cat /usr/local/etc/xray/reality_client.txt 2>/dev/null || echo ''")
    info = _parse_kv(saved)

    uid = info.get("UUID", "")
    pub_key = info.get("PUBLIC_KEY", "")
    short_id = info.get("SHORT_ID", "")
    sni = info.get("SNI", "www.microsoft.com")
    port = info.get("PORT", "443")

    # Fallback: read uuid/shortId from config if the saved file is missing.
    if not uid:
        cfg, _, _ = ssh.run_command("cat /usr/local/etc/xray/config.json 2>/dev/null || echo '{}'")
        try:
            import json
            d = json.loads(cfg)
            inbound = d["inbounds"][0]
            uid = inbound["settings"]["clients"][0]["id"]
            rs = inbound["streamSettings"]["realitySettings"]
            short_id = (rs.get("shortIds") or [""])[0]
            sni = (rs.get("serverNames") or ["www.microsoft.com"])[0]
            port = str(inbound.get("port", 443))
            priv = rs.get("privateKey", "")
            if priv and not pub_key:
                pub_out, _, _ = ssh.run_command(f"echo {priv} | xray x25519 -i 2>/dev/null | grep -i public | awk '{{print $NF}}'")
                pub_key = pub_out.strip()
        except Exception as e:
            return {"link": "", "error": str(e)}

    if not (uid and pub_key):
        return {"link": "", "error": "Не удалось получить параметры подключения (uuid/pubkey)"}

    link = (f"vless://{uid}@{server_ip}:{port}?encryption=none&flow=xtls-rprx-vision"
            f"&security=reality&sni={sni}&fp=chrome&pbk={pub_key}&sid={short_id}&type=tcp#MyVLESS")
    return {"link": link, "qr": _qr_b64(link), "uid": uid, "port": port}


# ── Shadowsocks ──────────────────────────────────────────────────────────────

def ss_get_info(ssh: SSHManager, server_ip: str) -> dict:
    cfg, _, _ = ssh.run_command("cat /etc/shadowsocks-libev/config.json 2>/dev/null || echo '{}'")
    try:
        import json
        d = json.loads(cfg)
        port = d.get("server_port", 8388)
        method = d.get("method", "chacha20-ietf-poly1305")
        password = d.get("password", "")
        import base64 as b64
        userinfo = b64.b64encode(f"{method}:{password}".encode()).decode()
        link = f"ss://{userinfo}@{server_ip}:{port}#MyServer"
        return {"link": link, "qr": _qr_b64(link), "port": port, "method": method, "password": password}
    except Exception as e:
        return {"error": str(e)}


# ── Outline access keys (ss:// ссылки для подключения клиентов) ───────────────

def _outline_api(ssh: SSHManager):
    """Вернуть (api_url, config) — собирает управляющий ключ через outline_config."""
    from .vpn_installer import outline_config
    cfg = outline_config(ssh, {})
    return cfg.get("api_url", ""), cfg


def outline_list_keys(ssh: SSHManager) -> dict:
    """Список ключей доступа Outline (то, что вставляют в клиент Outline)."""
    import json
    api, cfg = _outline_api(ssh)
    manager_key = cfg.get("manager_key", "")
    if not api:
        return {"keys": [], "manager_key": manager_key, "error": "Не удалось получить доступ к Outline API"}
    out, _, _ = ssh.run_command(f"curl -sk --max-time 12 {api}/access-keys")
    keys = []
    try:
        for k in json.loads(out).get("accessKeys", []):
            url = k.get("accessUrl", "")
            kid = str(k.get("id"))
            keys.append({
                "id": kid,
                "name": k.get("name") or f"Ключ {kid}",
                "link": url,
                "qr": _qr_b64(url) if url else "",
            })
    except Exception as e:
        return {"keys": [], "manager_key": manager_key, "error": str(e)}
    return {"keys": keys, "manager_key": manager_key, "api_url": api}


def outline_add_key(ssh: SSHManager, name: str = "") -> dict:
    import json
    api, _ = _outline_api(ssh)
    if not api:
        return {"error": "Не удалось получить доступ к Outline API"}
    out, _, _ = ssh.run_command(f"curl -sk --max-time 12 -X POST {api}/access-keys")
    try:
        k = json.loads(out)
    except Exception as e:
        return {"error": f"Не удалось создать ключ: {e}"}
    kid = str(k.get("id"))
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip()
    if safe:
        ssh.run_command(
            f"curl -sk --max-time 12 -X PUT {api}/access-keys/{kid}/name "
            f"-H 'Content-Type: application/json' -d '{{\"name\":\"{safe}\"}}'"
        )
    url = k.get("accessUrl", "")
    return {"id": kid, "name": safe or f"Ключ {kid}", "link": url,
            "qr": _qr_b64(url) if url else "", "config": url}


def outline_remove_key(ssh: SSHManager, key_id: str) -> bool:
    api, _ = _outline_api(ssh)
    if not api:
        return False
    out, _, _ = ssh.run_command(
        f"curl -sk --max-time 12 -o /dev/null -w '%{{http_code}}' -X DELETE {api}/access-keys/{key_id}"
    )
    return out.strip().startswith("2")


# ── Dispatcher ───────────────────────────────────────────────────────────────

def enrich_install_config(ssh: SSHManager, protocol: str, config: dict, server_ip: str) -> dict:
    """Add ready-to-use connection links and QR codes to the install result,
    so a newbie can connect immediately after install."""
    try:
        if protocol == "wireguard" and config.get("client_config"):
            cfg = config["client_config"].replace("SERVER_IP", server_ip)
            config["client_config"] = cfg
            config["qr"] = _qr_b64(cfg)  # WireGuard apps scan the full config
        elif protocol == "vless-reality":
            info = vless_get_link(ssh, server_ip)
            if info.get("link"):
                config["link"] = info["link"]
                config["qr"] = info.get("qr")
        elif protocol == "shadowsocks":
            info = ss_get_info(ssh, server_ip)
            if info.get("link"):
                config["link"] = info["link"]
                config["qr"] = info.get("qr")
    except Exception:
        pass
    return config


def get_clients(ssh: SSHManager, protocol: str, server_ip: str, config: dict) -> dict:
    if protocol == "wireguard":
        return {"clients": wg_list_clients(ssh)}
    if protocol == "openvpn":
        return {"clients": ovpn_list_clients(ssh)}
    if protocol == "vless-reality":
        return {"info": vless_get_link(ssh, server_ip)}
    if protocol == "shadowsocks":
        return {"info": ss_get_info(ssh, server_ip)}
    if protocol == "outline":
        data = outline_list_keys(ssh)
        return {"clients": data.get("keys", []),
                "info": {"manager_key": data.get("manager_key", ""),
                         "server_ip": server_ip, "error": data.get("error", "")}}
    if protocol == "3x-ui":
        return {"info": config}
    return {"clients": []}


def add_client(ssh: SSHManager, protocol: str, client_name: str) -> dict:
    if protocol == "wireguard":
        return wg_add_client(ssh, client_name)
    if protocol == "openvpn":
        return ovpn_add_client(ssh, client_name)
    if protocol == "outline":
        return outline_add_key(ssh, client_name)
    return {"error": "Добавление клиентов не поддерживается для этого протокола через панель"}


def remove_client(ssh: SSHManager, protocol: str, client_name: str) -> bool:
    if protocol == "wireguard":
        return wg_remove_client(ssh, client_name)
    if protocol == "openvpn":
        return ovpn_remove_client(ssh, client_name)
    if protocol == "outline":
        return outline_remove_key(ssh, client_name)
    return False


def get_client_config(ssh: SSHManager, protocol: str, client_name: str) -> dict:
    if protocol == "wireguard":
        return wg_get_client(ssh, client_name)
    if protocol == "openvpn":
        return ovpn_get_client(ssh, client_name)
    return {}
