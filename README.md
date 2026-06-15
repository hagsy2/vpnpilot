# VPNPilot 🛡️

> Веб-панель для автоматической установки VPN на удалённые серверы по SSH.  
> Вводишь IP и пароль — остальное делает она.

![Version](https://img.shields.io/badge/version-0.4.1--beta-orange)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Protocols](https://img.shields.io/badge/протоколов-7-6366f1)
![License](https://img.shields.io/badge/license-MIT-22c55e)

---

## Что умеет

- **Подключается к серверу по SSH** — IP + пароль, больше ничего не нужно
- **Определяет ОС автоматически** — Debian, Ubuntu, CentOS, AlmaLinux, Rocky, Fedora, Arch
- **Устанавливает VPN одной кнопкой** — 7 протоколов, свежие конфиги
- **Выдаёт QR-коды и конфиг-файлы** сразу после установки
- **Управляет клиентами** — добавляй/удаляй прямо из панели
- **Сносит VPN с сервера** — полностью, одним кликом
- **AI-помощник** чинит ошибки установки на лету (Groq, Gemini, OpenRouter, DeepSeek)

---

## Протоколы

| Протокол | Стойкость к блокировкам | Для новичков | Рекомендуем |
|---|---|---|---|
| WireGuard | ⭐⭐ Низкая | ✅ Просто | |
| OpenVPN | ⭐⭐⭐ Средняя | ✅ Просто | |
| **VLESS + Reality** | **⭐⭐⭐⭐⭐ Максимум** | ⚠️ Средне | ✅ **Да** |
| 3X-UI | ⭐⭐⭐⭐⭐ Максимум | ✅ Просто | |
| Shadowsocks | ⭐⭐⭐⭐ Высокая | ✅ Просто | |
| **Outline** | **⭐⭐⭐⭐ Высокая** | **✅ Просто** | ✅ **Да** |
| IKEv2 | ⭐⭐⭐ Средняя | ✅ Просто | |

---

## Установка

### 🐧 Установка в Proxmox (рекомендуется)

Запусти **на хосте Proxmox** — скрипт создаст LXC-контейнер и поднимет панель внутри:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/hagsy2/vpnpilot/main/proxmox-install.sh)"
```

После установки открой `http://<IP-контейнера>:8080` в браузере.

### 📦 Установка в готовый контейнер / VM

Внутри Debian/Ubuntu:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/hagsy2/vpnpilot/main/install.sh)"
```

### 🐳 Docker

```bash
docker build -t vpnpilot .
docker run -d -p 8080:8080 -v $(pwd)/data:/app/data vpnpilot
```

### 💻 Локально (разработка)

```bash
git clone https://github.com/hagsy2/vpnpilot
cd vpnpilot
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Открой [http://localhost:8080](http://localhost:8080).

---

## AI-помощник

Сервера бывают разные — иногда установка спотыкается на неожиданных ошибках. AI читает вывод, понимает что пошло не так, и сам применяет исправление.

Вставь ключ любого провайдера в форму — приложение определит его автоматически по префиксу:

| Провайдер | Префикс ключа | Стоимость | Где взять |
|---|---|---|---|
| **Groq** ⭐ | `gsk_...` | **Бесплатно, без карты** | [console.groq.com/keys](https://console.groq.com/keys) |
| Google Gemini | `AIza...` | Бесплатный tier | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| OpenRouter | `sk-or-...` | Есть бесплатные модели | [openrouter.ai/keys](https://openrouter.ai/keys) |
| DeepSeek | `sk-...` | ~$2 мин. баланс | [platform.deepseek.com](https://platform.deepseek.com) |

> AI необязателен — установка работает и без него. Но с ним гораздо надёжнее.

---

## Обновления

В шапке панели есть кнопка **🔄 Проверить обновления** — она сверяет твою версию с GitHub и, если есть новая, делает `git pull` + `pip install` + перезапуск прямо из браузера. После обновления страница сама перезагрузится.

Из консоли контейнера то же самое одной командой:

```bash
vpnpilot-update
```

> **Приватный репозиторий?** Тогда серверу нужен доступ к GitHub — настрой токен один раз внутри контейнера:
> ```bash
> cd /opt/ha-vpn-auto
> git remote set-url origin https://USER:TOKEN@github.com/hagsy2/vpnpilot.git
> ```
> После этого кнопка и `vpnpilot-update` работают без ввода пароля.

### Если установлено из старой версии (нет кнопки)

Один раз обнови вручную внутри контейнера — дальше появится кнопка:

```bash
cd /opt/ha-vpn-auto && git pull && systemctl restart ha-vpn-auto
```

## Управление сервисом

```bash
systemctl status  ha-vpn-auto    # статус
systemctl restart ha-vpn-auto    # перезапуск
journalctl -u ha-vpn-auto -f     # логи в реальном времени
```

---

## Структура проекта

```
vpnpilot/
├── main.py                  # FastAPI-сервер, WebSocket, все API-эндпоинты
├── modules/
│   ├── ssh_manager.py       # SSH-подключение, стриминг вывода
│   ├── os_detector.py       # определение ОС (/etc/os-release)
│   ├── vpn_installer.py     # рецепты установки и сноса (7 протоколов)
│   ├── vpn_manager.py       # управление клиентами, генерация QR и ссылок
│   ├── ai_assistant.py      # мульти-провайдерный AI, авто-фикс ошибок
│   └── storage.py           # JSON-хранилище серверов
├── static/
│   ├── index.html           # основной UI (2 вкладки)
│   ├── app.js               # вся логика фронтенда
│   └── style.css            # GitHub Dark тема
├── install.sh               # установщик внутри контейнера/VM
├── proxmox-install.sh       # создание LXC на хосте Proxmox
├── Dockerfile
└── requirements.txt
```

---

## Безопасность

- Пароли серверов хранятся **локально** в `data/servers.json` (в `.gitignore`, никогда не коммитится)
- Панель даёт root-доступ к твоим серверам — держи её в **закрытой сети** или за VPN
- Для публичного доступа рекомендуется reverse-proxy (nginx/caddy) с Basic Auth или mTLS

---

## Лицензия

MIT — делай что хочешь, ссылка приветствуется.
