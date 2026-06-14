# 🛡️ HA VPN Auto Installer

Веб-панель, которая **автоматически устанавливает VPN на твой сервер**. Вводишь IP и пароль — приложение само подключается по SSH, определяет ОС и ставит выбранный VPN-протокол со свежими конфигами. Для новичков и продвинутых.

![status](https://img.shields.io/badge/protocols-7-blue) ![license](https://img.shields.io/badge/license-MIT-green)

## ✨ Возможности

- **7 протоколов**: WireGuard, OpenVPN, VLESS+Reality, 3X-UI, Shadowsocks, Outline, IKEv2
- **Описание стойкости к блокировкам** у каждого — понятно даже новичку
- **QR-коды и конфиг-файлы** сразу после установки
- **Управление клиентами** — добавляй/удаляй прямо из панели
- **Полный снос VPN** с сервера в один клик
- **AI-помощник** (Groq / Gemini / OpenRouter / DeepSeek) — чинит ошибки установки на лету
- **Авто-определение ОС** (Debian, Ubuntu, CentOS, AlmaLinux, Rocky, Fedora, Arch)

## 🚀 Установка в Proxmox (рекомендуется)

Запусти **на хосте Proxmox** (создаст LXC-контейнер автоматически):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/hagsy2/vpnpilot/main/proxmox-install.sh)"
```

После установки открой `http://<IP-контейнера>:8080`.

## 📦 Установка в готовый контейнер / VM

Внутри Debian/Ubuntu контейнера:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/hagsy2/vpnpilot/main/install.sh)"
```

## 🐳 Docker

```bash
docker build -t ha-vpn-auto .
docker run -d -p 8080:8080 -v $(pwd)/data:/app/data ha-vpn-auto
```

## 💻 Локальный запуск (для разработки)

```bash
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
# открой http://localhost:8080
```

## 🤖 AI-помощник (необязательно, но полезно)

Серверы бывают разные, и иногда установка спотыкается. AI читает ошибки и исправляет их сам. Вставь ключ любого провайдера в форму — приложение определит какой по префиксу:

| Провайдер | Ключ | Стоимость |
|-----------|------|-----------|
| **Groq** ⭐ | `gsk_...` | бесплатно, без карты — [console.groq.com/keys](https://console.groq.com/keys) |
| Google Gemini | `AIza...` | бесплатный tier — [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| OpenRouter | `sk-or-...` | есть бесплатные модели — [openrouter.ai/keys](https://openrouter.ai/keys) |
| DeepSeek | `sk-...` | дёшево, нужен баланс ~$2 |

## ⚙️ Управление сервисом

```bash
systemctl status  ha-vpn-auto
systemctl restart ha-vpn-auto
journalctl -u ha-vpn-auto -f
```

## 🔐 Безопасность

- Пароли серверов хранятся локально в `data/servers.json` (не коммитится — в `.gitignore`)
- Запускай панель в закрытой сети или за firewall — она даёт root-доступ к твоим серверам
- Рекомендуется поставить reverse-proxy с авторизацией, если открываешь наружу

## 📁 Структура

```
main.py                 FastAPI сервер + WebSocket
modules/
  ssh_manager.py        SSH-подключение, стриминг вывода
  os_detector.py        определение ОС
  vpn_installer.py      рецепты установки + снос (7 протоколов)
  vpn_manager.py        управление клиентами, QR, ссылки
  ai_assistant.py       AI авто-исправление ошибок
  storage.py            хранение серверов
static/                 веб-интерфейс
install.sh              установщик в контейнер
proxmox-install.sh      создание LXC с хоста Proxmox
```

## 📄 Лицензия

MIT
