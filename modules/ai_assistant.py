import httpx
import json
import re
from typing import Optional

# All these providers expose an OpenAI-compatible /chat/completions endpoint,
# so the same code works with any of them — only base URL + model differ.
PROVIDERS = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
        "label": "DeepSeek",
        "free": False,
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "label": "Groq (бесплатно)",
        "free": True,
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "deepseek/deepseek-chat-v3.1:free",
        "label": "OpenRouter (бесплатно)",
        "free": True,
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-2.0-flash",
        "label": "Google Gemini (бесплатно)",
        "free": True,
    },
}

DEEPSEEK_API_URL = PROVIDERS["deepseek"]["url"]  # back-compat


def detect_provider(api_key: str) -> dict:
    """Guess provider from the key prefix so the user just pastes a key."""
    k = (api_key or "").strip()
    if k.startswith("gsk_"):
        return PROVIDERS["groq"]
    if k.startswith("sk-or-"):
        return PROVIDERS["openrouter"]
    if k.startswith("AIza"):
        return PROVIDERS["gemini"]
    # default: DeepSeek (sk-...)
    return PROVIDERS["deepseek"]

SYSTEM_PROMPT = """Ты — AI-ассистент для автоматической установки VPN на Linux сервер.
Твоя задача — анализировать вывод терминала и помогать исправлять ошибки.

Правила:
1. Если видишь ошибку — верни ТОЛЬКО команду bash для её исправления в блоке ```bash ... ```
2. Если ошибка не требует исправления или это просто предупреждение — верни пустую строку
3. Не объясняй много, будь краток
4. Учитывай дистрибутив Linux (Ubuntu, Debian, CentOS и тд)
5. Команды должны быть неинтерактивными (DEBIAN_FRONTEND=noninteractive, -y флаги)
6. Если ошибка критическая и нет решения — напиши: FATAL: <причина>
"""

ERROR_PATTERNS = [
    r"error",
    r"failed",
    r"failure",
    r"fatal",
    r"command not found",
    r"no such file",
    r"permission denied",
    r"unable to",
    r"cannot",
    r"ошибка",
    r"E:.*",
    r"dpkg.*error",
    r"apt-get.*error",
    r"curl.*failed",
    r"wget.*error",
]

_compiled = [re.compile(p, re.IGNORECASE) for p in ERROR_PATTERNS]


def looks_like_error(line: str) -> bool:
    return any(p.search(line) for p in _compiled)


async def ask_ai(api_key: str, context_lines: list, os_info: str, vpn_protocol: str):
    """Send error context to the AI, return (fix_command, error_reason).

    fix_command: str with a shell fix, "FATAL:..." if unfixable, or None.
    error_reason: human-readable reason the AI couldn't help (or None on success).
    """
    if not api_key:
        return None, "ключ не указан"

    provider = detect_provider(api_key)
    context = "\n".join(context_lines[-30:])  # last 30 lines for context
    user_msg = f"""
Дистрибутив: {os_info}
VPN протокол: {vpn_protocol}

Последние строки вывода терминала:
```
{context}
```

Нужно исправить ошибку. Верни команду для исправления или пустую строку если исправление не нужно.
"""

    try:
        async with httpx.AsyncClient(timeout=40) as client:
            resp = await client.post(
                provider["url"],
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": provider["model"],
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.1,
                },
            )
            if resp.status_code == 402:
                return None, f"{provider['label']}: недостаточно баланса на счёте API"
            if resp.status_code == 401:
                return None, f"{provider['label']}: ключ недействителен"
            if resp.status_code == 429:
                return None, f"{provider['label']}: превышен лимит запросов, подожди немного"
            if resp.status_code != 200:
                body = resp.text[:120]
                return None, f"{provider['label']}: ошибка API {resp.status_code} {body}"

            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()

            if reply.startswith("FATAL:"):
                return f"FATAL:{reply[6:]}", None

            match = re.search(r"```(?:bash|sh)?\n(.*?)```", reply, re.DOTALL)
            if match:
                return match.group(1).strip(), None

            return None, None  # AI replied but no fix needed
    except httpx.TimeoutException:
        return None, f"{provider['label']}: таймаут ответа"
    except Exception as e:
        return None, f"{provider['label']}: {type(e).__name__}: {e}"


def extract_config_from_output(output: str, protocol: str) -> dict:
    """Try to extract client config info from installation output."""
    result = {}

    if protocol == "wireguard":
        # Look for WireGuard client config
        wg_match = re.search(r"\[Interface\].*?\[Peer\].*?AllowedIPs.*", output, re.DOTALL)
        if wg_match:
            result["config"] = wg_match.group(0)

    elif protocol == "3x-ui":
        # Look for 3X-UI panel URL and credentials
        url_match = re.search(r"http://\S+:\d+", output)
        if url_match:
            result["panel_url"] = url_match.group(0)
        user_match = re.search(r"username:\s*(\S+)", output, re.IGNORECASE)
        pass_match = re.search(r"password:\s*(\S+)", output, re.IGNORECASE)
        if user_match:
            result["username"] = user_match.group(1)
        if pass_match:
            result["password"] = pass_match.group(1)

    elif protocol == "openvpn":
        ovpn_match = re.search(r"client\.ovpn|\.ovpn file", output, re.IGNORECASE)
        if ovpn_match:
            result["note"] = "Файл .ovpn создан на сервере"

    return result
