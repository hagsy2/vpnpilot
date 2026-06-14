import re

OS_PROFILES = {
    "ubuntu": {
        "pkg_manager": "apt",
        "update_cmd": "apt-get update -y",
        "install_cmd": "apt-get install -y",
        "family": "debian",
    },
    "debian": {
        "pkg_manager": "apt",
        "update_cmd": "apt-get update -y",
        "install_cmd": "apt-get install -y",
        "family": "debian",
    },
    "centos": {
        "pkg_manager": "yum",
        "update_cmd": "yum update -y",
        "install_cmd": "yum install -y",
        "family": "rhel",
    },
    "almalinux": {
        "pkg_manager": "dnf",
        "update_cmd": "dnf update -y",
        "install_cmd": "dnf install -y",
        "family": "rhel",
    },
    "rocky": {
        "pkg_manager": "dnf",
        "update_cmd": "dnf update -y",
        "install_cmd": "dnf install -y",
        "family": "rhel",
    },
    "fedora": {
        "pkg_manager": "dnf",
        "update_cmd": "dnf update -y",
        "install_cmd": "dnf install -y",
        "family": "rhel",
    },
    "arch": {
        "pkg_manager": "pacman",
        "update_cmd": "pacman -Syu --noconfirm",
        "install_cmd": "pacman -S --noconfirm",
        "family": "arch",
    },
}


def detect_os(ssh_output: str) -> dict:
    """Parse /etc/os-release output and return OS profile."""
    info = {}
    for line in ssh_output.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            info[k.strip().lower()] = v.strip().strip('"').lower()

    name = info.get("id", "")
    version = info.get("version_id", "unknown")
    pretty = info.get("pretty_name", name)

    profile = OS_PROFILES.get(name)
    if not profile:
        for key in OS_PROFILES:
            if key in name:
                profile = OS_PROFILES[key]
                break

    if not profile:
        profile = OS_PROFILES["ubuntu"]  # safe default

    return {
        "name": name,
        "version": version,
        "pretty": pretty,
        "profile": profile,
    }


def parse_arch(uname_output: str) -> str:
    out = uname_output.strip()
    if "aarch64" in out or "arm64" in out:
        return "arm64"
    if "armv" in out:
        return "arm"
    return "amd64"
