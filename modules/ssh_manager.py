import asyncio
import paramiko
import socket
import time
from typing import Callable, Optional, Tuple


class SSHManager:
    def __init__(self):
        self.client: Optional[paramiko.SSHClient] = None
        self.connected = False

    def connect(self, host: str, port: int, username: str, password: str = None, key_path: str = None, timeout: int = 30):  # type: ignore
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(hostname=host, port=port, username=username, timeout=timeout, banner_timeout=30, auth_timeout=30)
        if key_path:
            kwargs["key_filename"] = key_path
        else:
            kwargs["password"] = password
        self.client.connect(**kwargs)
        self.connected = True

    def disconnect(self):
        if self.client:
            self.client.close()
            self.connected = False

    def run_command(self, command: str, timeout: int = 300) -> tuple[str, str, int]:
        """Run command synchronously, return (stdout, stderr, exit_code)."""
        if not self.client:
            raise RuntimeError("Not connected")
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout, get_pty=True)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return out, err, code

    def run_command_stream(self, command: str, on_output: Callable[[str], None], timeout: int = 600):
        """Run command and stream output line by line via callback."""
        if not self.client:
            raise RuntimeError("Not connected")

        transport = self.client.get_transport()
        channel = transport.open_session()
        channel.get_pty(width=200, height=50)
        channel.set_combine_stderr(True)
        channel.exec_command(command)

        buffer = ""
        channel.setblocking(False)
        deadline = time.time() + timeout

        while time.time() < deadline:
            if channel.exit_status_ready() and not channel.recv_ready():
                break
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                buffer += chunk
                while "\n" in buffer or "\r" in buffer:
                    for sep in ["\n", "\r\n", "\r"]:
                        if sep in buffer:
                            line, buffer = buffer.split(sep, 1)
                            if line.strip():
                                on_output(line.rstrip())
                            break
            else:
                time.sleep(0.05)

        if buffer.strip():
            on_output(buffer.strip())

        return channel.recv_exit_status()

    def get_file_content(self, path: str) -> str:
        out, _, _ = self.run_command(f"cat {path}")
        return out

    def file_exists(self, path: str) -> bool:
        _, _, code = self.run_command(f"test -f {path}")
        return code == 0


async def test_connection(host: str, port: int, username: str, password: str) -> Tuple[bool, str]:
    """Quick connection test."""
    try:
        mgr = SSHManager()
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: mgr.connect(host, port, username, password)
        )
        out, _, _ = await asyncio.get_event_loop().run_in_executor(
            None, lambda: mgr.run_command("echo OK && uname -a")
        )
        mgr.disconnect()
        return True, out.strip()
    except paramiko.AuthenticationException:
        return False, "Ошибка аутентификации — проверь логин/пароль"
    except socket.timeout:
        return False, f"Таймаут подключения к {host}:{port}"
    except Exception as e:
        return False, str(e)
