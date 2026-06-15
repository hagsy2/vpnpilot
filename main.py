import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from modules.ssh_manager import SSHManager, test_connection
from modules.os_detector import detect_os, parse_arch
from modules.vpn_installer import PROTOCOLS
from modules.ai_assistant import looks_like_error, ask_ai, extract_config_from_output
from modules import storage, vpn_manager

try:
    __version__ = (Path(__file__).parent / "VERSION").read_text().strip()
except Exception:
    __version__ = "0.0.0"

app = FastAPI(title="VPNPilot", version=__version__)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Active installation sessions
sessions: dict[str, dict] = {}


# ── Pydantic models ───────────────────────────────────────────────────────────

class TestConnRequest(BaseModel):
    host: str
    port: int = 22
    username: str = "root"
    password: str


class InstallRequest(BaseModel):
    host: str
    port: int = 22
    username: str = "root"
    password: str
    protocol: str
    deepseek_api_key: str = ""


class AddClientRequest(BaseModel):
    client_name: str


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("static/index.html").read_text()


# ── Protocols ─────────────────────────────────────────────────────────────────

@app.get("/api/protocols")
async def get_protocols():
    return [
        {
            "id": p.id, "name": p.name, "description": p.description, "icon": p.icon,
            "blocking_level": p.blocking_level, "blocking_text": p.blocking_text,
            "ease": p.ease, "devices": p.devices, "recommended": p.recommended,
        }
        for p in PROTOCOLS.values()
    ]


# ── Connection test ───────────────────────────────────────────────────────────

@app.post("/api/test-connection")
async def api_test_connection(req: TestConnRequest):
    ok, msg = await test_connection(req.host, req.port, req.username, req.password)
    if ok:
        # Запоминаем сервер сразу после успешного теста — попадёт в список.
        storage.save_host(req.host, req.port, req.username, req.password)
    return {"success": ok, "message": msg}


# ── Install ───────────────────────────────────────────────────────────────────

@app.post("/api/install")
async def api_install(req: InstallRequest):
    if req.protocol not in PROTOCOLS:
        return JSONResponse({"error": "Неизвестный протокол"}, status_code=400)
    # Запоминаем сервер, чтобы не вводить IP/пароль в следующий раз.
    storage.save_host(req.host, req.port, req.username, req.password)
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "status": "pending",
        "log": [],
        "config": None,
        "error": None,
        "cancel": False,
        "ssh": None,
        "req": req.model_dump(),
    }
    asyncio.create_task(run_installation(session_id))
    return {"session_id": session_id}


@app.post("/api/install/{session_id}/cancel")
async def api_cancel_install(session_id: str):
    """Остановить зависшую/идущую установку."""
    session = sessions.get(session_id)
    if not session:
        return JSONResponse({"error": "Сессия не найдена"}, status_code=404)
    session["cancel"] = True
    # Рвём SSH-соединение, чтобы заблокированное чтение в потоке сразу освободилось.
    ssh = session.get("ssh")
    if ssh:
        try:
            ssh.disconnect()
        except Exception:
            pass
    return {"success": True}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    await ws.accept()
    sent = 0
    try:
        while True:
            if session_id not in sessions:
                await ws.send_json({"type": "error", "message": "Сессия не найдена"})
                break
            session = sessions[session_id]
            log = session["log"]
            while sent < len(log):
                await ws.send_json({"type": "log", "message": log[sent]})
                sent += 1
            if session["status"] in ("done", "error"):
                await ws.send_json({
                    "type": "done",
                    "status": session["status"],
                    "config": session.get("config"),
                    "error": session.get("error"),
                    "server_id": session.get("server_id"),
                })
                break
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass


# ── Server management ─────────────────────────────────────────────────────────

@app.get("/api/servers")
async def api_list_servers():
    servers = storage.list_servers()
    # Don't expose passwords in list
    return [
        {k: v for k, v in s.items() if k != "password"}
        for s in servers
    ]


@app.delete("/api/servers/{server_id}")
async def api_delete_server(server_id: str):
    ok = storage.delete_server(server_id)
    return {"success": ok}


@app.get("/api/hosts")
async def api_list_hosts():
    """Сохранённые серверы для автозаполнения формы установки."""
    return storage.list_hosts()


@app.delete("/api/hosts/{host}/{port}")
async def api_delete_host(host: str, port: int):
    return {"success": storage.delete_host(host, port)}


@app.post("/api/servers/{server_id}/uninstall")
async def api_uninstall(server_id: str):
    """Fully remove the VPN from the remote server, then drop it from the list."""
    srv = storage.get_server(server_id)
    if not srv:
        return JSONResponse({"error": "Сервер не найден"}, status_code=404)
    proto = PROTOCOLS.get(srv["protocol"])
    if not proto or not proto.uninstall_cmd:
        return JSONResponse({"error": "Снос не поддерживается для этого протокола"}, status_code=400)

    ssh = SSHManager()
    log_lines: list = []
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: ssh.connect(srv["host"], srv["port"], srv["username"], srv["password"])
        )
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ssh.run_command_stream(proto.uninstall_cmd, lambda l: log_lines.append(l), timeout=300),
        )
        storage.delete_server(server_id)
        return {"success": True, "log": log_lines[-40:]}
    except Exception as e:
        return JSONResponse({"error": str(e), "log": log_lines[-40:]}, status_code=500)
    finally:
        ssh.disconnect()


@app.post("/api/servers/{server_id}/reinstall")
async def api_reinstall(server_id: str, body: dict = None):
    """Re-run the installation for a saved server (e.g. after a hung/broken install).

    By default wipes the old install first (clean=True), then reinstalls. Streams
    over the same /ws/{session_id} channel as a fresh install.
    """
    srv = storage.get_server(server_id)
    if not srv:
        return JSONResponse({"error": "Сервер не найден"}, status_code=404)
    if srv["protocol"] not in PROTOCOLS:
        return JSONResponse({"error": "Неизвестный протокол"}, status_code=400)

    body = body or {}
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "status": "pending",
        "log": [],
        "config": None,
        "error": None,
        "cancel": False,
        "ssh": None,
        "req": {
            "host": srv["host"],
            "port": srv["port"],
            "username": srv["username"],
            "password": srv["password"],
            "protocol": srv["protocol"],
            "deepseek_api_key": body.get("deepseek_api_key", ""),
            "clean": body.get("clean", True),
        },
    }
    asyncio.create_task(run_installation(session_id))
    return {"session_id": session_id}


@app.get("/api/servers/{server_id}/clients")
async def api_get_clients(server_id: str):
    srv = storage.get_server(server_id)
    if not srv:
        return JSONResponse({"error": "Сервер не найден"}, status_code=404)
    ssh = SSHManager()
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: ssh.connect(srv["host"], srv["port"], srv["username"], srv["password"])
        )
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: vpn_manager.get_clients(ssh, srv["protocol"], srv["host"], srv.get("config", {}))
        )
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        ssh.disconnect()


@app.post("/api/servers/{server_id}/clients")
async def api_add_client(server_id: str, req: AddClientRequest):
    srv = storage.get_server(server_id)
    if not srv:
        return JSONResponse({"error": "Сервер не найден"}, status_code=404)
    ssh = SSHManager()
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: ssh.connect(srv["host"], srv["port"], srv["username"], srv["password"])
        )
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: vpn_manager.add_client(ssh, srv["protocol"], req.client_name)
        )
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        ssh.disconnect()


@app.delete("/api/servers/{server_id}/clients/{client_name}")
async def api_remove_client(server_id: str, client_name: str):
    srv = storage.get_server(server_id)
    if not srv:
        return JSONResponse({"error": "Сервер не найден"}, status_code=404)
    ssh = SSHManager()
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: ssh.connect(srv["host"], srv["port"], srv["username"], srv["password"])
        )
        ok = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: vpn_manager.remove_client(ssh, srv["protocol"], client_name)
        )
        return {"success": ok}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        ssh.disconnect()


@app.get("/api/servers/{server_id}/clients/{client_name}/config")
async def api_get_client_config(server_id: str, client_name: str):
    srv = storage.get_server(server_id)
    if not srv:
        return JSONResponse({"error": "Сервер не найден"}, status_code=404)
    ssh = SSHManager()
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: ssh.connect(srv["host"], srv["port"], srv["username"], srv["password"])
        )
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: vpn_manager.get_client_config(ssh, srv["protocol"], client_name)
        )
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        ssh.disconnect()


# ── Self-update ───────────────────────────────────────────────────────────────

@app.get("/api/version")
async def api_version():
    import subprocess, os as _os
    here = Path(__file__).parent
    git_env = {**_os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def git(*args, timeout=10):
        return subprocess.check_output(
            ["git", *args], cwd=here, text=True, stderr=subprocess.DEVNULL,
            timeout=timeout, env=git_env,
        ).strip()

    # Semantic version from the VERSION file (source of truth for releases).
    try:
        release = (here / "VERSION").read_text().strip()
    except Exception:
        release = "0.0.0"

    # Local git version — must succeed independently of any network/auth.
    try:
        commit = git("rev-parse", "--short", "HEAD")
        date = git("log", "-1", "--format=%ci")[:10]
    except Exception:
        return {"version": release, "commit": "unknown", "date": "", "up_to_date": None}

    # Remote check — best effort. On a private repo without creds this fails;
    # that's fine, we report up_to_date=null and still allow a manual update.
    up_to_date = None
    try:
        remote = git("ls-remote", "origin", "HEAD", timeout=15).split()[0][:7]
        up_to_date = (remote == commit)
    except Exception:
        up_to_date = None

    return {"version": release, "commit": commit, "date": date, "up_to_date": up_to_date}


def _changelog_top(text: str) -> str:
    """Return the first version section of a Keep-a-Changelog file (## [x.y.z] ...)."""
    lines = text.splitlines()
    out, started = [], False
    for ln in lines:
        if ln.startswith("## "):
            if started:
                break
            started = True
        if started:
            out.append(ln)
    return "\n".join(out).strip()


@app.get("/api/changelog")
async def api_changelog():
    """Patch notes for a pending update: commits between local HEAD and origin,
    plus the latest CHANGELOG section from the remote. Used by the update dialog."""
    import subprocess, os as _os
    here = Path(__file__).parent
    git_env = {**_os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def git(*args, timeout=20):
        return subprocess.check_output(
            ["git", *args], cwd=here, text=True, stderr=subprocess.DEVNULL,
            timeout=timeout, env=git_env,
        ).strip()

    try:
        git("fetch", "origin", "main", timeout=40)
    except Exception:
        return {"available": None, "commits": [], "changelog": "", "error": "Не удалось связаться с GitHub"}

    commits = []
    try:
        raw = git("log", "--pretty=format:%h\x1f%s\x1f%cs", "HEAD..origin/main")
        for line in raw.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                commits.append({"sha": parts[0], "subject": parts[1], "date": parts[2]})
    except Exception:
        pass

    changelog = ""
    try:
        changelog = _changelog_top(git("show", "origin/main:CHANGELOG.md", timeout=10))
    except Exception:
        changelog = ""

    return {"available": len(commits) > 0, "commits": commits, "changelog": changelog}


@app.websocket("/ws/update")
async def ws_update(websocket: WebSocket):
    await websocket.accept()

    async def send(msg: str, level: str = "info"):
        await websocket.send_json({"type": "log", "level": level, "message": msg})

    try:
        install_dir = Path(__file__).parent
        await send("🔄 Получаю обновления из GitHub...")

        # GIT_TERMINAL_PROMPT=0 → never block on a credential prompt.
        import os as _os
        git_env = {**_os.environ, "GIT_TERMINAL_PROMPT": "0"}

        async def run_git(*args):
            proc = await asyncio.create_subprocess_exec(
                "git", *args, cwd=str(install_dir), env=git_env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            return proc.returncode, out.decode(errors="replace").strip()

        # git может ругаться на "dubious ownership" — разрешаем эту директорию.
        await run_git("config", "--global", "--add", "safe.directory", str(install_dir))

        code, out = await run_git("fetch", "origin", "main")
        if out:
            for line in out.splitlines():
                await send(line)
        if code != 0:
            await send("❌ Не удалось связаться с GitHub. Проверь интернет/доступ к репозиторию.", "error")
            await websocket.send_json({"type": "done", "success": False})
            return

        _, local = await run_git("rev-parse", "HEAD")
        _, remote = await run_git("rev-parse", "origin/main")
        if local and local == remote:
            await send("✅ Уже последняя версия, перезапуск не нужен", "ok")
            await websocket.send_json({"type": "done", "success": True, "restart": False})
            return

        _, cur_ver = await run_git("describe", "--tags", "--always")
        await send(f"Текущая версия: {cur_ver or local[:7]}")

        # Надёжное обновление: reset --hard игнорирует любую локальную «грязь»
        # (изменённые права, недокачанный rebase) — git pull --rebase на таком падал.
        await send("⬇️ Применяю обновление (git reset --hard origin/main)...")
        code, out = await run_git("reset", "--hard", "origin/main")
        for line in out.splitlines():
            await send(line)
        if code != 0:
            await send("❌ Не удалось применить обновление.", "error")
            await websocket.send_json({"type": "done", "success": False})
            return
        _, new_ver = await run_git("describe", "--tags", "--always")
        await send(f"Новая версия: {new_ver or remote[:7]}", "ok")

        await send("📦 Обновляю зависимости...")
        venv_pip = install_dir / "venv" / "bin" / "pip"
        pip_bin = str(venv_pip) if venv_pip.exists() else "pip3"
        proc2 = await asyncio.create_subprocess_exec(
            pip_bin, "install", "-q", "-r", str(install_dir / "requirements.txt"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out2, _ = await proc2.communicate()
        for line in out2.decode(errors="replace").strip().splitlines():
            if line.strip():
                await send(line)

        await send("✅ Обновление применено! Сервис перезапустится, страница обновится через 5 секунд.", "ok")
        # ВАЖНО: сначала шлём done, потом перезапускаем. systemctl restart убивает
        # этот же процесс uvicorn — если рестартить до отправки done, фронт его не
        # получит и зависнет. Дав сообщению уйти, запускаем рестарт ОТВЯЗАННО через
        # systemd-run (transient unit вне cgroup сервиса), чтобы он пережил наше
        # завершение и реально перезапустил панель.
        await websocket.send_json({"type": "done", "success": True, "restart": True})
        await asyncio.sleep(0.4)
        import subprocess as _sp
        try:
            _sp.Popen(
                ["systemd-run", "--on-active=1", "systemctl", "restart", "ha-vpn-auto"],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            )
        except FileNotFoundError:
            _sp.Popen(
                "sleep 1; systemctl restart ha-vpn-auto", shell=True,
                start_new_session=True, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            )
    except Exception as e:
        import traceback
        await send(f"❌ Ошибка обновления: {e}", "error")
        for tl in traceback.format_exc().splitlines()[-6:]:
            await send(tl)
        try:
            await websocket.send_json({"type": "done", "success": False})
        except Exception:
            pass


# ── Installation runner ───────────────────────────────────────────────────────

class InstallCancelled(Exception):
    """Поднимается, когда пользователь остановил установку."""


async def run_installation(session_id: str):
    session = sessions[session_id]
    req_data = session["req"]
    session["status"] = "running"

    def log(msg: str, level: str = "info"):
        prefix = {"info": "ℹ️", "ok": "✅", "error": "❌", "warn": "⚠️",
                  "ai": "🤖", "step": "📋"}.get(level, "·")
        session["log"].append(f"{prefix} {msg}")

    ssh = SSHManager()
    session["ssh"] = ssh
    should_cancel = lambda: session.get("cancel", False)
    protocol = PROTOCOLS[req_data["protocol"]]
    all_output_lines: list = []
    error_buffer: list = []

    try:
        log(f"Подключение к {req_data['host']}:{req_data['port']}...")
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ssh.connect(req_data["host"], req_data["port"],
                                 req_data["username"], req_data["password"]),
        )
        log("Соединение установлено", "ok")

        log("Определение операционной системы...")
        os_raw, _, _ = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ssh.run_command("cat /etc/os-release")
        )
        arch_raw, _, _ = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ssh.run_command("uname -m")
        )
        os_info = detect_os(os_raw)
        arch = parse_arch(arch_raw)
        log(f"ОС: {os_info['pretty']} ({arch})", "ok")

        def on_output(line: str):
            all_output_lines.append(line)
            session["log"].append(f"  {line}")
            if looks_like_error(line):
                error_buffer.append(line)

        # Optional clean slate — wipe any previous (possibly broken) install first.
        if req_data.get("clean") and protocol.uninstall_cmd:
            log("Очистка предыдущей установки перед переустановкой...", "step")
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ssh.run_command_stream(protocol.uninstall_cmd, on_output,
                                               timeout=300, should_cancel=should_cancel),
            )
            error_buffer.clear()
            log("Очистка завершена", "ok")

        steps = protocol.steps_fn(os_info, req_data["host"])
        log(f"Начинаю установку {protocol.name} ({len(steps)} шагов)", "step")

        for i, step in enumerate(steps, 1):
            if should_cancel():
                raise InstallCancelled()
            log(f"[{i}/{len(steps)}] {step.description}", "step")

            exit_code = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda s=step: ssh.run_command_stream(s.command, on_output,
                                                      timeout=s.timeout, should_cancel=should_cancel),
            )

            if should_cancel() or exit_code == 130:
                raise InstallCancelled()

            if exit_code != 0 and not step.ignore_error:
                if req_data.get("deepseek_api_key") and error_buffer:
                    log("Обнаружена ошибка, спрашиваю AI...", "ai")
                    fix_cmd, ai_reason = await ask_ai(
                        req_data["deepseek_api_key"],
                        all_output_lines, os_info["pretty"], protocol.name,
                    )
                    if ai_reason and not fix_cmd:
                        log(f"AI не смог помочь — {ai_reason}", "warn")
                    if fix_cmd:
                        if fix_cmd.startswith("FATAL:"):
                            raise RuntimeError(fix_cmd[6:].strip())
                        log(f"AI предлагает: {fix_cmd[:80]}...", "ai")
                        fix_lines: list = []
                        fix_code = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: ssh.run_command_stream(fix_cmd, lambda l: fix_lines.append(l)),
                        )
                        for fl in fix_lines:
                            session["log"].append(f"  [fix] {fl}")
                        if fix_code == 0:
                            log("AI исправление применено, повтор шага...", "ai")
                            retry_code = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda s=step: ssh.run_command_stream(s.command, on_output, timeout=s.timeout),
                            )
                            if retry_code != 0 and not step.ignore_error:
                                raise RuntimeError(f"Шаг '{step.description}' провалился даже после AI-фикса")
                        else:
                            raise RuntimeError(f"AI фикс не помог. Шаг: {step.description}")
                    else:
                        raise RuntimeError(f"Шаг '{step.description}' завершился с ошибкой (код {exit_code})")
                else:
                    if not req_data.get("deepseek_api_key"):
                        log("Произошла ошибка. С ключом DeepSeek AI я бы попробовал исправить её автоматически — добавь ключ и попробуй снова.", "ai")
                    raise RuntimeError(f"Шаг '{step.description}' завершился с ошибкой (код {exit_code})")

            error_buffer.clear()
            log(f"Шаг {i} выполнен", "ok")

        log("Получение конфигурации...", "step")
        if protocol.post_install_fn:
            config = await asyncio.get_event_loop().run_in_executor(
                None, lambda: protocol.post_install_fn(ssh, os_info),
            )
            config["server_ip"] = req_data["host"]
            # add ready-to-use links + QR codes for the user
            config = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: vpn_manager.enrich_install_config(ssh, req_data["protocol"], config, req_data["host"]),
            )
        else:
            config = extract_config_from_output("\n".join(all_output_lines), req_data["protocol"])

        # Save to managed servers
        server_id = storage.save_server(
            req_data["host"], req_data["port"], req_data["username"], req_data["password"],
            req_data["protocol"], protocol.name, config,
        )
        session["config"] = config
        session["server_id"] = server_id
        session["status"] = "done"
        log(f"🎉 {protocol.name} установлен! Сервер сохранён в управление.", "ok")

    except InstallCancelled:
        session["status"] = "error"
        session["error"] = "Установка остановлена пользователем"
        log("⏹️ Установка остановлена. Сервер сохранён — можно попробовать снова.", "warn")
    except Exception as e:
        session["status"] = "error"
        session["error"] = str(e)
        log(f"Ошибка: {e}", "error")
    finally:
        try:
            ssh.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
