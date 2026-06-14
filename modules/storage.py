"""Simple JSON-file persistence for managed servers."""
import json
import uuid
from pathlib import Path
from typing import Optional

DATA_FILE = Path(__file__).parent.parent / "data" / "servers.json"


def _load() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"servers": {}}


def _save(data: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def list_servers() -> list:
    return list(_load()["servers"].values())


def get_server(server_id: str) -> Optional[dict]:
    return _load()["servers"].get(server_id)


def save_server(host: str, port: int, username: str, password: str,
                protocol: str, protocol_name: str, config: dict) -> str:
    data = _load()
    # Reuse existing entry for same host+protocol
    for sid, s in data["servers"].items():
        if s["host"] == host and s["protocol"] == protocol:
            s.update({"port": port, "username": username, "password": password,
                       "config": config, "protocol_name": protocol_name})
            _save(data)
            return sid
    sid = str(uuid.uuid4())[:8]
    data["servers"][sid] = {
        "id": sid,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "protocol": protocol,
        "protocol_name": protocol_name,
        "config": config,
    }
    _save(data)
    return sid


def delete_server(server_id: str) -> bool:
    data = _load()
    if server_id in data["servers"]:
        del data["servers"][server_id]
        _save(data)
        return True
    return False
